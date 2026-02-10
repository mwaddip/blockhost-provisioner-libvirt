#!/bin/bash
# blockhost-vm-start — Start a VM via root agent
#
# Contract:
#   blockhost-vm-start <name>
#   exit 0 on success, 1 on failure.

set -euo pipefail

if [ $# -lt 1 ]; then
    echo "Usage: blockhost-vm-start <name>" >&2
    exit 1
fi

VM_NAME="$1"

echo "Starting VM: $VM_NAME" >&2

RESULT=$(python3 -c "
from blockhost.root_agent import call
r = call('virsh-start', domain='$VM_NAME')
if not r.get('ok'):
    raise SystemExit(r.get('error', 'unknown error'))
print(r.get('output', ''))
") || {
    echo "Failed to start VM: $VM_NAME" >&2
    exit 1
}

echo "VM started: $VM_NAME"
exit 0
