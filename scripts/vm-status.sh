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

# TODO: Implement status check
# Map libvirt states to blockhost states:
#   running       → active
#   paused        → suspended
#   shut off      → suspended (or destroyed if undefine'd)
#   not found     → destroyed
#   anything else → unknown

echo "unknown"
exit 0
