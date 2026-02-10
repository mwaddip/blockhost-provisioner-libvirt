#!/bin/bash
# blockhost-vm-kill — Force-stop a VM (immediate power off)
#
# Contract:
#   blockhost-vm-kill <name>
#   exit 0 on success, 1 on failure.

set -euo pipefail

if [ $# -lt 1 ]; then
    echo "Usage: blockhost-vm-kill <name>" >&2
    exit 1
fi

VM_NAME="$1"

echo "Force-stopping VM: $VM_NAME" >&2

RESULT=$(python3 -c "
from blockhost.root_agent import call
r = call('virsh-destroy', domain='$VM_NAME')
if not r.get('ok'):
    # 'domain is not running' is not an error for kill
    err = r.get('error', '')
    if 'not running' in err or 'not found' in err:
        print('VM already stopped')
        raise SystemExit(0)
    raise SystemExit(err or 'unknown error')
print(r.get('output', ''))
") || {
    echo "Failed to kill VM: $VM_NAME" >&2
    exit 1
}

echo "VM force-stopped: $VM_NAME"
exit 0
