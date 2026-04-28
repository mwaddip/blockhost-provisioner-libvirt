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

echo "VM started: $VM_NAME" >&2

# --- Isolate VM port on bridge (prevent inter-VM L2 traffic) ---
# After start, libvirt creates a new tap interface; isolation from the
# original vm-create is lost, so we must re-apply it.

VM_NAME="$VM_NAME" python3 -c "
import os, sys
from blockhost.provisioner_libvirt.helpers import get_vm_tap_interface
from blockhost.root_agent import call

domain = os.environ['VM_NAME']
tap = get_vm_tap_interface(domain)

if not tap:
    print('WARNING: Could not determine tap interface for bridge port isolation', file=sys.stderr)
    sys.exit(0)

try:
    result = call('bridge-port-isolate', dev=tap)
    if result.get('ok'):
        print(f'Bridge port isolation enabled on {tap}', file=sys.stderr)
    else:
        err = result.get('error')
        print(f'WARNING: Failed to isolate bridge port: {err}', file=sys.stderr)
except Exception as e:
    print(f'WARNING: Bridge port isolation failed: {e}', file=sys.stderr)
" || true  # non-fatal — VM works without isolation

echo "VM started: $VM_NAME"
exit 0
