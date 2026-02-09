#!/bin/bash
# Build blockhost-provisioner-libvirt .deb package
#
# Creates a Debian package with:
# - CLI tools in /usr/bin/
# - Python modules in /usr/lib/python3/dist-packages/blockhost/
# - Root agent actions in /usr/share/blockhost/root-agent-actions/
# - Provisioner hooks in /usr/share/blockhost/provisioner-hooks/
# - Systemd units
# - Documentation in /usr/share/doc/blockhost-provisioner-libvirt/

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION="0.1.0"
PACKAGE_NAME="blockhost-provisioner-libvirt_${VERSION}_all"
BUILD_DIR="${SCRIPT_DIR}/build"

echo "Building ${PACKAGE_NAME}.deb..."

# Create clean build directory
rm -rf "${BUILD_DIR}/pkg"
mkdir -p "${BUILD_DIR}/pkg"

PKG="${BUILD_DIR}/pkg"

# Create DEBIAN control files
mkdir -p "${PKG}/DEBIAN"

cat > "${PKG}/DEBIAN/control" << 'EOF'
Package: blockhost-provisioner-libvirt
Version: 0.1.0
Section: admin
Priority: optional
Architecture: all
Depends: python3 (>= 3.10), blockhost-common (>= 0.1.0), libpam-web3-tools (>= 0.5.0)
Recommends: qemu-kvm, libvirt-daemon-system, libvirt-clients, virtinst, cloud-image-utils
Suggests: libguestfs-tools
Conflicts: blockhost-provisioner-proxmox
Maintainer: Blockhost Team <blockhost@example.com>
Description: libvirt/KVM VM provisioning with NFT-based web3 authentication
 This package provides tools for provisioning libvirt/KVM VMs with
 NFT-based web3 authentication using the libpam-web3 PAM module.
 .
 Uses virsh + cloud-init instead of Proxmox + Terraform.
 .
 Includes:
  - blockhost-vm-create: Create VMs with NFT authentication
  - blockhost-vm-destroy: Destroy a VM
  - blockhost-vm-start: Start a VM
  - blockhost-vm-stop: Gracefully shut down a VM
  - blockhost-vm-kill: Force-stop a VM
  - blockhost-vm-status: Print VM status
  - blockhost-vm-list: List all VMs
  - blockhost-vm-gc: Garbage collect expired VMs
  - blockhost-vm-resume: Resume a suspended VM
  - blockhost-mint-nft: Mint access credential NFTs
  - blockhost-build-template: Build qcow2 VM template
  - blockhost-provisioner-detect: Detect libvirt/KVM host
  - Provisioner manifest for engine integration
  - Systemd timer for daily garbage collection
EOF

# Create postinst script
cat > "${PKG}/DEBIAN/postinst" << 'EOF'
#!/bin/bash
set -e

case "$1" in
    configure)
        # Create directories
        for dir in /var/lib/blockhost/templates /var/lib/blockhost/vms /var/lib/blockhost/cloud-init; do
            if [ ! -d "$dir" ]; then
                mkdir -p "$dir"
                chown root:blockhost "$dir" 2>/dev/null || true
                chmod 750 "$dir"
            fi
        done

        # Enable and start the garbage collection timer
        systemctl daemon-reload
        systemctl enable blockhost-gc.timer
        systemctl start blockhost-gc.timer

        echo ""
        echo "============================================================"
        echo "  blockhost-provisioner-libvirt installed successfully!"
        echo "============================================================"
        echo ""
        ;;
esac

#DEBHELPER#
exit 0
EOF
chmod 755 "${PKG}/DEBIAN/postinst"

# Create prerm script
cat > "${PKG}/DEBIAN/prerm" << 'EOF'
#!/bin/bash
set -e

case "$1" in
    remove|upgrade|deconfigure)
        systemctl stop blockhost-gc.timer 2>/dev/null || true
        systemctl disable blockhost-gc.timer 2>/dev/null || true
        ;;
esac

#DEBHELPER#
exit 0
EOF
chmod 755 "${PKG}/DEBIAN/prerm"

# Create directory structure
mkdir -p "${PKG}/usr/bin"
mkdir -p "${PKG}/usr/lib/python3/dist-packages/blockhost"
mkdir -p "${PKG}/usr/lib/systemd/system"
mkdir -p "${PKG}/usr/share/blockhost"
mkdir -p "${PKG}/usr/share/doc/blockhost-provisioner-libvirt"

# Install executables to /usr/bin/
cp "${SCRIPT_DIR}/scripts/vm-create.py" "${PKG}/usr/bin/blockhost-vm-create"
cp "${SCRIPT_DIR}/scripts/vm-destroy.sh" "${PKG}/usr/bin/blockhost-vm-destroy"
cp "${SCRIPT_DIR}/scripts/vm-start.sh" "${PKG}/usr/bin/blockhost-vm-start"
cp "${SCRIPT_DIR}/scripts/vm-stop.sh" "${PKG}/usr/bin/blockhost-vm-stop"
cp "${SCRIPT_DIR}/scripts/vm-kill.sh" "${PKG}/usr/bin/blockhost-vm-kill"
cp "${SCRIPT_DIR}/scripts/vm-status.sh" "${PKG}/usr/bin/blockhost-vm-status"
cp "${SCRIPT_DIR}/scripts/vm-list.sh" "${PKG}/usr/bin/blockhost-vm-list"
cp "${SCRIPT_DIR}/scripts/vm-metrics.sh" "${PKG}/usr/bin/blockhost-vm-metrics"
cp "${SCRIPT_DIR}/scripts/vm-throttle.sh" "${PKG}/usr/bin/blockhost-vm-throttle"
cp "${SCRIPT_DIR}/scripts/vm-gc.py" "${PKG}/usr/bin/blockhost-vm-gc"
cp "${SCRIPT_DIR}/scripts/vm-resume.py" "${PKG}/usr/bin/blockhost-vm-resume"
cp "${SCRIPT_DIR}/scripts/mint_nft.py" "${PKG}/usr/bin/blockhost-mint-nft"
cp "${SCRIPT_DIR}/scripts/build-template.sh" "${PKG}/usr/bin/blockhost-build-template"
cp "${SCRIPT_DIR}/scripts/provisioner-detect.sh" "${PKG}/usr/bin/blockhost-provisioner-detect"

chmod 755 "${PKG}/usr/bin/"blockhost-*

# Install systemd units
cp "${SCRIPT_DIR}/systemd/blockhost-gc.service" "${PKG}/usr/lib/systemd/system/"
cp "${SCRIPT_DIR}/systemd/blockhost-gc.timer" "${PKG}/usr/lib/systemd/system/"

# Install provisioner manifest
cp "${SCRIPT_DIR}/provisioner.json" "${PKG}/usr/share/blockhost/provisioner.json"

# Install provisioner hooks
mkdir -p "${PKG}/usr/share/blockhost/provisioner-hooks"
cp "${SCRIPT_DIR}/provisioner-hooks/first-boot.sh" "${PKG}/usr/share/blockhost/provisioner-hooks/first-boot.sh"
chmod 755 "${PKG}/usr/share/blockhost/provisioner-hooks/first-boot.sh"

# Install root agent action modules
mkdir -p "${PKG}/usr/share/blockhost/root-agent-actions"
cp "${SCRIPT_DIR}/root-agent-actions/virsh.py" "${PKG}/usr/share/blockhost/root-agent-actions/"

# Install Python modules
cp "${SCRIPT_DIR}/scripts/vm-create.py" "${PKG}/usr/lib/python3/dist-packages/blockhost/vm_creator.py"
cp "${SCRIPT_DIR}/scripts/mint_nft.py" "${PKG}/usr/lib/python3/dist-packages/blockhost/mint_nft.py"

# Install provisioner wizard plugin
WIZARD_PKG_DIR="${PKG}/usr/lib/python3/dist-packages/blockhost/provisioner_libvirt"
mkdir -p "${WIZARD_PKG_DIR}/templates/provisioner_libvirt"
cp "${SCRIPT_DIR}/blockhost/provisioner_libvirt/__init__.py" "${WIZARD_PKG_DIR}/"
cp "${SCRIPT_DIR}/blockhost/provisioner_libvirt/wizard.py" "${WIZARD_PKG_DIR}/"
if ls "${SCRIPT_DIR}/blockhost/provisioner_libvirt/templates/provisioner_libvirt/"*.html >/dev/null 2>&1; then
    cp "${SCRIPT_DIR}/blockhost/provisioner_libvirt/templates/provisioner_libvirt/"*.html "${WIZARD_PKG_DIR}/templates/provisioner_libvirt/"
fi

# Install documentation
cp "${SCRIPT_DIR}/README.md" "${PKG}/usr/share/doc/blockhost-provisioner-libvirt/" 2>/dev/null || true
cp "${SCRIPT_DIR}/PROJECT.yaml" "${PKG}/usr/share/doc/blockhost-provisioner-libvirt/"

# Create copyright file
cat > "${PKG}/usr/share/doc/blockhost-provisioner-libvirt/copyright" << 'EOF'
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: blockhost-provisioner-libvirt
Source: https://github.com/mwaddip/blockhost-provisioner-libvirt

Files: *
Copyright: 2024-2026 Blockhost Team
License: MIT
 Permission is hereby granted, free of charge, to any person obtaining a copy
 of this software and associated documentation files (the "Software"), to deal
 in the Software without restriction, including without limitation the rights
 to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 copies of the Software, and to permit persons to whom the Software is
 furnished to do so, subject to the following conditions:
 .
 The above copyright notice and this permission notice shall be included in all
 copies or substantial portions of the Software.
 .
 THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 SOFTWARE.
EOF

# Create changelog
cat > "${PKG}/usr/share/doc/blockhost-provisioner-libvirt/changelog.Debian" << EOF
blockhost-provisioner-libvirt (0.1.0) unstable; urgency=low

  * Initial release
  * libvirt/KVM VM provisioning with NFT-based web3 authentication
  * Proof-of-concept for provisioner abstraction layer

 -- Blockhost Team <blockhost@example.com>  $(date -R)
EOF
gzip -9 -n "${PKG}/usr/share/doc/blockhost-provisioner-libvirt/changelog.Debian"

# Build the package
echo "Building package..."
dpkg-deb --build "${PKG}" "${BUILD_DIR}/${PACKAGE_NAME}.deb"

echo ""
echo "============================================================"
echo "Package built: ${BUILD_DIR}/${PACKAGE_NAME}.deb"
echo "============================================================"
