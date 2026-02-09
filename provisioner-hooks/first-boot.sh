#!/bin/bash
#
# libvirt/KVM Provisioner — First Boot Hook
#
# Called by the main first-boot.sh to install provisioner-specific dependencies.
# This script installs:
# - qemu-kvm + libvirt
# - cloud-image-utils (for cloud-init ISO generation)
# - libguestfs-tools (for template customization)
#
# Uses step markers in STATE_DIR for idempotent execution.
#

set -e

STATE_DIR="${STATE_DIR:-/var/lib/blockhost}"
LOG_FILE="${LOG_FILE:-/var/log/blockhost-firstboot.log}"

log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] [provisioner-libvirt] $1"
    echo "$msg" >> "$LOG_FILE"
}

#
# Step: Install libvirt/KVM stack
#
STEP_LIBVIRT="${STATE_DIR}/.step-libvirt"
if [ ! -f "$STEP_LIBVIRT" ]; then
    log "Installing libvirt/KVM stack..."

    # Configure apt proxy if available
    APT_PROXY="http://192.168.122.1:3142"
    if curl -s --connect-timeout 2 "$APT_PROXY" >/dev/null 2>&1; then
        log "Using apt proxy: $APT_PROXY"
        echo "Acquire::http::Proxy \"$APT_PROXY\";" > /etc/apt/apt.conf.d/00proxy
    fi

    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y \
        qemu-kvm \
        libvirt-daemon-system \
        libvirt-clients \
        virtinst \
        cloud-image-utils \
        libguestfs-tools \
        python3-libvirt \
        python3-ecdsa \
        jq

    # Enable and start libvirtd
    systemctl enable libvirtd
    systemctl start libvirtd

    # Add blockhost user to libvirt group
    if id blockhost >/dev/null 2>&1; then
        usermod -aG libvirt blockhost
        log "Added blockhost user to libvirt group."
    fi

    touch "$STEP_LIBVIRT"
    log "libvirt/KVM stack installed."
else
    log "libvirt/KVM already installed, skipping."
fi

#
# Step: Verify KVM support
#
STEP_KVM="${STATE_DIR}/.step-kvm-check"
if [ ! -f "$STEP_KVM" ]; then
    log "Verifying KVM support..."

    if [ ! -e /dev/kvm ]; then
        log "WARNING: /dev/kvm not found — hardware virtualization may not be available."
        log "VMs will run in QEMU emulation mode (much slower)."
    else
        log "KVM hardware acceleration available."
    fi

    touch "$STEP_KVM"
fi

log "Provisioner first-boot hook complete."
exit 0
