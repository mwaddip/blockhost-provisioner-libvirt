#!/bin/bash
# blockhost-vm-stop — Gracefully shut down a VM
#
# Contract:
#   blockhost-vm-stop <name>
#   exit 0 on success, 1 on failure.

set -euo pipefail

if [ $# -lt 1 ]; then
    echo "Usage: blockhost-vm-stop <name>" >&2
    exit 1
fi

VM_NAME="$1"

echo "Stopping VM (graceful ACPI shutdown): $VM_NAME" >&2

RESULT=$(VM_NAME="$VM_NAME" python3 -c "
import os
from blockhost.root_agent import call
r = call('virsh-shutdown', domain=os.environ['VM_NAME'])
if not r.get('ok'):
    raise SystemExit(r.get('error', 'unknown error'))
print(r.get('output', ''))
") || {
    echo "Failed to stop VM: $VM_NAME" >&2
    exit 1
}

echo "Shutdown signal sent: $VM_NAME"
exit 0
