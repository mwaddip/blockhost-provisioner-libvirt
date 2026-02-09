#!/bin/bash
# blockhost-vm-list — List all managed VMs
#
# Contract:
#   blockhost-vm-list [--format json]
#   stdout: tab-separated table (default) or JSON array (--format json)
#   exit 0.

set -uo pipefail

FORMAT="table"
if [ "${1:-}" = "--format" ] && [ "${2:-}" = "json" ]; then
    FORMAT="json"
fi

# TODO: Implement VM listing
# 1. Read VM database to get managed VMs
# 2. For each: query virsh domstate
# 3. Output in requested format

if [ "$FORMAT" = "json" ]; then
    echo "[]"
else
    echo "NAME	STATUS	IP	CREATED"
fi
exit 0
