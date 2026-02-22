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

# Validate VM name format (must match root agent's DOMAIN_RE)
# Contract: exit 0 always — invalid name = "unknown"
if [[ ! "$VM_NAME" =~ ^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$ ]]; then
    echo "unknown"
    exit 0
fi

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
