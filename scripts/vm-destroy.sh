#!/bin/bash
# blockhost-vm-destroy — Destroy a VM and clean up all resources
#
# Contract:
#   blockhost-vm-destroy <name>
#   Must be idempotent — destroying an already-destroyed VM is not an error.
#   exit 0 on success, 1 on failure.

set -euo pipefail

if [ $# -lt 1 ]; then
    echo "Usage: blockhost-vm-destroy <name>" >&2
    exit 1
fi

VM_NAME="$1"

# TODO: Implement VM destruction
# 1. Check if domain exists (virsh dominfo)
# 2. If running: force stop (virsh destroy)
# 3. Remove domain definition (virsh undefine --remove-all-storage)
# 4. Clean up cloud-init ISO
# 5. Release IP back to pool
# 6. Update database record

echo "ERROR: not yet implemented" >&2
exit 1
