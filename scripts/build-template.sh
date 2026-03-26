#!/bin/bash
# blockhost-build-template — Build or update the base VM template image
#
# Contract:
#   blockhost-build-template [--force]
#   exit 0 on success, 1 on failure.
#
# Builds a qcow2 base image from the Debian 12 generic cloud image, customized
# with libpam-web3 for NFT-based SSH authentication. VMs are created as qcow2
# overlays (backing file) for copy-on-write efficiency.
#
# Idempotent: skips download if image exists (unless --force). Always re-runs
# virt-customize since the .deb packages may have been updated.
#
# SPECIAL profile: S7 P6 E8 — reliability focus, must be idempotent.

set -euo pipefail

TEMPLATE_DIR="/var/lib/blockhost/templates"
TEMPLATE_IMAGE="$TEMPLATE_DIR/blockhost-base.qcow2"
TEMPLATE_STAGING="$TEMPLATE_DIR/.blockhost-base.staging.qcow2"
LIBPAM_DEB_DIR="/var/lib/blockhost/template-packages"
CLOUD_IMAGE_URL="https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-generic-amd64.qcow2"
CLOUD_IMAGE_CHECKSUM_URL="https://cloud.debian.org/images/cloud/bookworm/latest/SHA512SUMS"
DOWNLOAD_DIR="$TEMPLATE_DIR/.cache"

FORCE=0
if [ "${1:-}" = "--force" ]; then
    FORCE=1
fi

log() {
    echo "[build-template] $1" >&2
}

die() {
    log "FATAL: $1"
    exit 1
}

# --- Preflight checks ---

command -v virt-customize >/dev/null 2>&1 || die "virt-customize not found (install libguestfs-tools)"
command -v qemu-img >/dev/null 2>&1 || die "qemu-img not found (install qemu-utils)"

mkdir -p "$TEMPLATE_DIR" "$DOWNLOAD_DIR" "$LIBPAM_DEB_DIR"

# --- Download cloud image ---

CLOUD_IMAGE="$DOWNLOAD_DIR/debian-12-generic-amd64.qcow2"

if [ ! -f "$CLOUD_IMAGE" ] || [ "$FORCE" -eq 1 ]; then
    log "Downloading Debian 12 cloud image..."
    curl -fSL --progress-bar -o "${CLOUD_IMAGE}.tmp" "$CLOUD_IMAGE_URL"

    # Verify checksum if available
    if SUMS=$(curl -fsSL "$CLOUD_IMAGE_CHECKSUM_URL" 2>/dev/null); then
        EXPECTED=$(echo "$SUMS" | grep "debian-12-generic-amd64.qcow2" | awk '{print $1}')
        if [ -n "$EXPECTED" ]; then
            ACTUAL=$(sha512sum "${CLOUD_IMAGE}.tmp" | awk '{print $1}')
            if [ "$EXPECTED" != "$ACTUAL" ]; then
                rm -f "${CLOUD_IMAGE}.tmp"
                die "Checksum mismatch for cloud image"
            fi
            log "Checksum verified."
        fi
    else
        log "WARNING: Could not fetch checksums, skipping verification."
    fi

    mv "${CLOUD_IMAGE}.tmp" "$CLOUD_IMAGE"
    log "Cloud image downloaded."
else
    log "Cloud image already cached, skipping download."
fi

# --- Prepare staging copy ---
# Work on a staging copy so a failed customize doesn't corrupt the final image.
# The source image stays pristine in cache for re-runs.

log "Preparing staging image..."
cp "$CLOUD_IMAGE" "$TEMPLATE_STAGING"

# Resize to 4G to have room for package installation inside the image.
# Guest disks will be larger (overlay + resize on first boot via cloud-init).
qemu-img resize "$TEMPLATE_STAGING" 4G

# --- Locate ALL template packages ---

TEMPLATE_DEBS=()
for deb in "$LIBPAM_DEB_DIR"/*.deb; do
    [ -f "$deb" ] || continue
    TEMPLATE_DEBS+=("$deb")
    log "Found template package: $(basename "$deb")"
done

if [ ${#TEMPLATE_DEBS[@]} -eq 0 ]; then
    die "No template packages found in $LIBPAM_DEB_DIR"
fi

CUSTOMIZE_ARGS=()

# Install dependencies needed by template packages
CUSTOMIZE_ARGS+=(--install "libpam-runtime,openssh-server")

# Copy all .deb packages into the VM
for deb in "${TEMPLATE_DEBS[@]}"; do
    CUSTOMIZE_ARGS+=(--copy-in "$deb:/tmp/")
done

# Install all at once (dpkg handles dependency order within the set)
DEB_NAMES=$(printf "/tmp/%s " "${TEMPLATE_DEBS[@]##*/}")
CUSTOMIZE_ARGS+=(--run-command "dpkg -i $DEB_NAMES || apt-get install -f -y")

# Clean up copied .deb files
CUSTOMIZE_ARGS+=(--run-command "rm -f $DEB_NAMES")

# --- Customize the image ---

log "Customizing image with virt-customize..."
if ! virt-customize -a "$TEMPLATE_STAGING" \
    "${CUSTOMIZE_ARGS[@]}" \
    \
    --install "cloud-init,qemu-guest-agent,sudo,curl" \
    \
    --write '/etc/pam.d/sshd:# PAM configuration for SSH — web3 auth via libpam-web3
# Standard preamble
@include common-auth
account    required     pam_nologin.so
@include common-account
session [success=ok ignore=ignore module_unknown=ignore default=bad]        pam_selinux.so close
session    required     pam_loginuid.so
session    optional     pam_keyinit.so force revoke
@include common-session
session [success=ok ignore=ignore module_unknown=ignore default=bad]        pam_selinux.so open
@include common-password
session    optional     pam_mail.so standard nostrstrenv nstrstrstrenv' \
    \
    --write '/etc/ssh/sshd_config.d/50-blockhost.conf:# BlockHost SSH configuration
# Challenge-response for PAM-based web3 auth
ChallengeResponseAuthentication yes
KbdInteractiveAuthentication yes
UsePAM yes
PasswordAuthentication no
PermitRootLogin no
MaxAuthTries 6
LoginGraceTime 60' \
    --run-command 'grep -q "^Include /etc/ssh/sshd_config.d" /etc/ssh/sshd_config || sed -i "1i Include /etc/ssh/sshd_config.d/*.conf" /etc/ssh/sshd_config' \
    --run-command 'sed -i "s/^KbdInteractiveAuthentication no/#KbdInteractiveAuthentication no  # overridden by sshd_config.d/" /etc/ssh/sshd_config' \
    \
    --write '/etc/cloud/cloud.cfg.d/99-blockhost.cfg:# BlockHost cloud-init configuration
# Use NoCloud datasource (ISO attached as CDROM)
datasource_list: [NoCloud, None]
' \
    \
    --run-command "systemctl enable ssh qemu-guest-agent cloud-init" \
    --run-command "systemctl disable systemd-networkd-wait-online.service || true" \
    \
    --run-command "truncate -s 0 /etc/machine-id" \
    --run-command "rm -f /var/lib/dbus/machine-id" \
    --run-command "cloud-init clean --logs 2>/dev/null || true" \
    --run-command "rm -rf /var/lib/cloud/ /var/log/cloud-init*" \
    --run-command "find /var/log -type f -exec truncate -s 0 {} \\;" \
    --run-command "rm -f /etc/ssh/ssh_host_*" \
    --run-command "fstrim / 2>/dev/null || true"
then
    rm -f "$TEMPLATE_STAGING"
    die "virt-customize failed"
fi

# --- Finalize ---
# Atomic move: only replace the final image after full success.

mv "$TEMPLATE_STAGING" "$TEMPLATE_IMAGE"
log "Template image ready: $TEMPLATE_IMAGE"
log "Size: $(du -h "$TEMPLATE_IMAGE" | cut -f1)"
echo "Template built successfully: $TEMPLATE_IMAGE"
exit 0
