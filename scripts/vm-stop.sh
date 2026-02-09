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

# TODO: Implement via root agent client
# virsh shutdown (graceful, ACPI signal)
# blockhost-root-agent-client '{"action":"virsh-shutdown","params":{"domain":"'"$VM_NAME"'"}}'

echo "ERROR: not yet implemented" >&2
exit 1
