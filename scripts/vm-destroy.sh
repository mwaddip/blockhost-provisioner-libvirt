#!/bin/bash
# blockhost-vm-destroy — Destroy a VM and clean up all resources
#
# Contract:
#   blockhost-vm-destroy <name>
#   Must be idempotent — destroying an already-destroyed VM is not an error.
#   exit 0 on success, 1 on failure.
#
# Cleanup order matters: stop first, then undefine, then filesystem cleanup,
# then database. Each step tolerates the resource already being gone.
#
# SPECIAL profile: S9 E9 — every step must handle partial prior runs.

set -uo pipefail

if [ $# -lt 1 ]; then
    echo "Usage: blockhost-vm-destroy <name>" >&2
    exit 1
fi

VM_NAME="$1"
VM_DISK_DIR="/var/lib/blockhost/vms"
CLOUD_INIT_DIR="/var/lib/blockhost/cloud-init"
ERRORS=0

log() {
    echo "[destroy] $1" >&2
}

# --- Step 1: Force-stop if running ---
# virsh destroy = force power off (confusing libvirt naming).
# Idempotent: "domain is not running" or "domain not found" are both fine.

log "Stopping domain (if running)..."
if virsh dominfo "$VM_NAME" >/dev/null 2>&1; then
    STATE=$(virsh domstate "$VM_NAME" 2>/dev/null || echo "unknown")
    if [ "$STATE" = "running" ]; then
        python3 -c "
from blockhost.root_agent import call
r = call('virsh-destroy', domain='$VM_NAME')
if not r.get('ok') and 'not running' not in r.get('error', ''):
    print('WARNING: force-stop failed: ' + r.get('error', 'unknown'))
" 2>&1 | while read -r line; do log "$line"; done
    fi
else
    log "Domain not found (already removed or never created)."
fi

# --- Step 2: Undefine domain + remove managed storage ---
# --remove-all-storage removes disks that libvirt knows about (the overlay).
# We also do manual cleanup below for cloud-init ISOs which aren't managed volumes.

log "Removing domain definition..."
if virsh dominfo "$VM_NAME" >/dev/null 2>&1; then
    python3 -c "
from blockhost.root_agent import call
r = call('virsh-undefine', domain='$VM_NAME', remove_storage=True)
if not r.get('ok'):
    print('WARNING: undefine failed: ' + r.get('error', 'unknown'))
    raise SystemExit(1)
" 2>&1 | while read -r line; do log "$line"; done
    if [ $? -ne 0 ]; then
        # Try without --remove-all-storage as fallback
        log "Retrying undefine without storage removal..."
        python3 -c "
from blockhost.root_agent import call
r = call('virsh-undefine', domain='$VM_NAME', remove_storage=False)
if not r.get('ok'):
    print('ERROR: undefine failed: ' + r.get('error', 'unknown'))
    raise SystemExit(1)
" 2>&1 | while read -r line; do log "$line"; done || ERRORS=$((ERRORS + 1))
    fi
else
    log "Domain already undefined."
fi

# --- Step 3: Clean up disk overlay (if undefine didn't get it) ---

if [ -f "$VM_DISK_DIR/${VM_NAME}.qcow2" ]; then
    log "Removing disk overlay: ${VM_NAME}.qcow2"
    rm -f "$VM_DISK_DIR/${VM_NAME}.qcow2"
fi

# --- Step 4: Clean up cloud-init ISO ---

if [ -d "$CLOUD_INIT_DIR/$VM_NAME" ]; then
    log "Removing cloud-init data: $VM_NAME"
    rm -rf "$CLOUD_INIT_DIR/$VM_NAME"
elif [ -f "$CLOUD_INIT_DIR/${VM_NAME}.img" ]; then
    log "Removing cloud-init ISO: ${VM_NAME}.img"
    rm -f "$CLOUD_INIT_DIR/${VM_NAME}.img"
fi

# --- Step 5: Update database ---

log "Updating database..."
python3 -c "
from blockhost.vm_db import get_database
db = get_database()
vm = db.get_vm('$VM_NAME')
if vm and vm.get('status') != 'destroyed':
    db.mark_destroyed('$VM_NAME')
    print('Database record marked destroyed.')
elif vm:
    print('Already marked destroyed in database.')
else:
    print('No database record found (not an error).')
" 2>&1 | while read -r line; do log "$line"; done

# --- Done ---

if [ "$ERRORS" -gt 0 ]; then
    log "Completed with $ERRORS error(s)."
    exit 1
fi

echo "VM destroyed: $VM_NAME"
exit 0
