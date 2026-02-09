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

# TODO: Implement via root agent client
# blockhost-root-agent-client '{"action":"virsh-start","params":{"domain":"'"$VM_NAME"'"}}'

echo "ERROR: not yet implemented" >&2
exit 1
