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

# TODO: Implement via root agent client
# virsh destroy (force stop, confusing name but that's libvirt for you)
# blockhost-root-agent-client '{"action":"virsh-destroy","params":{"domain":"'"$VM_NAME"'"}}'

echo "ERROR: not yet implemented" >&2
exit 1
