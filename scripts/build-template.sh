#!/bin/bash
# blockhost-build-template — Build or update the base VM template image
#
# Contract:
#   blockhost-build-template [--force]
#   exit 0 on success, 1 on failure.
#
# Implementation notes:
#   For libvirt, the "template" is a qcow2 base image with:
#   - Debian/Ubuntu cloud image as starting point
#   - libpam-web3 PAM module baked in
#   - SSH configured for PAM auth
#   - cloud-init configured
#
#   The image lives at /var/lib/blockhost/templates/blockhost-base.qcow2
#   VMs are created as qcow2 overlays (backing file) for CoW efficiency.

set -euo pipefail

TEMPLATE_DIR="/var/lib/blockhost/templates"
TEMPLATE_IMAGE="$TEMPLATE_DIR/blockhost-base.qcow2"
LIBPAM_DEB_DIR="/var/lib/blockhost/template-packages"

# TODO: Implement template build
# 1. Download Debian cloud image (or use cached copy)
# 2. Use virt-customize (libguestfs) to:
#    a. Install libpam-web3 .deb
#    b. Configure PAM for web3 auth
#    c. Configure SSH for PAM auth
#    d. Install cloud-init
#    e. Clean up (truncate logs, machine-id, etc.)
# 3. Store as $TEMPLATE_IMAGE

echo "ERROR: not yet implemented" >&2
exit 1
