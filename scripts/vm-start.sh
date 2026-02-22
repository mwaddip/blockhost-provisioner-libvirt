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

# Validate VM name format (must match root agent's DOMAIN_RE)
if [[ ! "$VM_NAME" =~ ^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$ ]]; then
    echo "Invalid VM name: $VM_NAME" >&2
    exit 1
fi

echo "Starting VM: $VM_NAME" >&2

RESULT=$(VM_NAME="$VM_NAME" python3 -c "
import os
from blockhost.root_agent import call
r = call('virsh-start', domain=os.environ['VM_NAME'])
if not r.get('ok'):
    raise SystemExit(r.get('error', 'unknown error'))
print(r.get('output', ''))
") || {
    echo "Failed to start VM: $VM_NAME" >&2
    exit 1
}

echo "VM started: $VM_NAME"
exit 0
