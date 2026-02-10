#!/bin/bash
# blockhost-vm-status — Print VM status
#
# Contract:
#   blockhost-vm-status <name>
#   stdout: one of: active, suspended, destroyed, unknown
#   exit 0 always.

set -uo pipefail

if [ $# -lt 1 ]; then
    echo "unknown"
    exit 0
fi

VM_NAME="$1"

# Query libvirt domain state. virsh domstate exits non-zero if the domain
# doesn't exist, which we handle as "destroyed".
STATE=$(virsh domstate "$VM_NAME" 2>/dev/null) || {
    echo "destroyed"
    exit 0
}

case "$STATE" in
    running)
        echo "active"
        ;;
    "shut off"|paused|pmsuspended)
        echo "suspended"
        ;;
    *)
        echo "unknown"
        ;;
esac

exit 0
