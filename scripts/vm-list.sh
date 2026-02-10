#!/bin/bash
# blockhost-vm-list — List all managed VMs
#
# Contract:
#   blockhost-vm-list [--format json]
#   stdout: tab-separated table (default) or JSON array (--format json)
#   exit 0 always.

set -uo pipefail

FORMAT="table"
if [ "${1:-}" = "--format" ] && [ "${2:-}" = "json" ]; then
    FORMAT="json"
fi

# Query database for managed VMs and cross-reference with virsh domstate.
# Uses Python because the database API is Python-only.
python3 -c "
import json, subprocess, sys

from blockhost.vm_db import get_database

db = get_database()
vms = db.list_vms()
fmt = '$FORMAT'

results = []
for vm in vms:
    name = vm.get('vm_name', '')
    ip = vm.get('ip_address', '')
    created = vm.get('created_at', '')[:10]  # date portion only
    db_status = vm.get('status', 'unknown')

    # If DB says destroyed, trust it
    if db_status == 'destroyed':
        status = 'destroyed'
    else:
        # Cross-check with virsh for live state
        try:
            r = subprocess.run(
                ['virsh', 'domstate', name],
                capture_output=True, text=True, timeout=5,
            )
            state = r.stdout.strip() if r.returncode == 0 else ''
            if state == 'running':
                status = 'active'
            elif state in ('shut off', 'paused', 'pmsuspended'):
                status = 'suspended'
            elif r.returncode != 0:
                status = 'destroyed'
            else:
                status = 'unknown'
        except Exception:
            status = db_status  # fallback to DB

    results.append({'name': name, 'status': status, 'ip': ip, 'created': created})

if fmt == 'json':
    print(json.dumps(results))
else:
    print('NAME\tSTATUS\tIP\tCREATED')
    for r in results:
        print(f\"{r['name']}\t{r['status']}\t{r['ip']}\t{r['created']}\")
" 2>/dev/null || {
    # If database is unavailable, output empty result
    if [ "$FORMAT" = "json" ]; then
        echo "[]"
    else
        echo "NAME	STATUS	IP	CREATED"
    fi
}

exit 0
