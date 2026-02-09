# Claude Instructions for blockhost-provisioner-libvirt

## SETTINGS.md (HIGHEST PRIORITY)

**Read and internalize `SETTINGS.md` at the start of every session.** It defines persona, preferences, and behavioral overrides. It takes precedence over all other instructions in this file.

## SPECIAL.md (HIGHEST PRIORITY)

**Read and internalize `SPECIAL.md` at the start of every session.** It defines per-component priority weights — where to invest extra scrutiny beyond standard professional practice. All stats at 5 = normal competence. Stats above 5 = extra focus.

| Path pattern | Profile | Extra focus areas |
|---|---|---|
| `scripts/vm-gc.py` | S8 P6 E9 C4 I6 A5 L8 | Robustness (destroys resources), reliability (must be idempotent), edge cases (cleanup failures = data loss) |
| `scripts/mint_nft.py` | S7 P8 E7 C4 I6 A6 L7 | Security (permanent chain writes, key handling) |
| `scripts/build-template.sh` | S7 P6 E8 C4 I5 A5 L6 | Reliability (must be idempotent, runs once) |
| `root-agent-actions/` | S8 P9 E7 C4 I8 A6 L7 | Security (privilege boundary, root commands) |
| everything else | S9 P7 E9 C6 I7 A7 L7 | Robustness + reliability (VM lifecycle is unforgiving) |

See `SPECIAL.md` for full stat definitions and the priority allocation model.

## Project Scope

**This Claude session only modifies blockhost-provisioner-libvirt.** Changes to dependency packages (blockhost-common, blockhost-engine, etc.) should be done in their respective Claude sessions with separate prompts.

## Project Overview

This is the libvirt/KVM VM provisioning component of the BlockHost system. It implements the same provisioner contract as blockhost-provisioner-proxmox, but uses libvirt/virsh + cloud-init instead of Proxmox VE + Terraform.

Read `PROJECT.yaml` for the complete machine-readable API specification.

**This is a proof-of-concept provisioner.** Its primary purpose is to validate that the provisioner abstraction layer works — that a second, independent implementation can satisfy the same contract and be loaded by the same engine/installer/root-agent. If this works, the abstraction is proven.

**Dependencies:**
- `blockhost-common` — Provides `blockhost.config`, `blockhost.vm_db`, `blockhost.root_agent`, `blockhost.cloud_init` modules
- `blockhost-broker` — IPv6 tunnel broker (broker-client saves allocation to `/etc/blockhost/broker-allocation.json`)
- `libpam-web3-tools` — Provides signing page HTML and `pam_web3_tool` CLI

## The Provisioner Contract

This provisioner must satisfy the contract defined in `blockhost-common/provisioner-contract.md`. The key integration points:

### 1. Manifest (`provisioner.json`)
Installed to `/usr/share/blockhost/provisioner.json`. Declares all commands, wizard module, first-boot hook, root agent actions, and config keys. The engine, installer, and root agent all discover capabilities through this file.

### 2. CLI Commands
All `blockhost-vm-*` commands must accept the same arguments and produce the same output format as the Proxmox provisioner. The engine calls these commands — it doesn't know or care which hypervisor is behind them.

### 3. Wizard Plugin
Flask Blueprint registered at `blockhost.provisioner_libvirt.wizard`. Must export:
- `blueprint` — Flask Blueprint with config page routes
- `get_finalization_steps()` — Returns `list[tuple[str, str, callable]]` for wizard finalization
- `get_summary_data(session)` — Returns dict for review page
- `get_summary_template()` — Returns template path for summary section

### 4. Root Agent Actions
Python module at `/usr/share/blockhost/root-agent-actions/virsh.py`. Must export an `ACTIONS` dict mapping action names to handler functions. Handlers receive `params: dict` and return `{'ok': True/False, ...}`.

### 5. First-Boot Hook
Script at `/usr/share/blockhost/provisioner-hooks/first-boot.sh`. Installs libvirt/KVM stack. Must be idempotent (step markers). Receives `STATE_DIR` and `LOG_FILE` from caller.

## Key Differences from Proxmox Provisioner

| Aspect | Proxmox | libvirt |
|--------|---------|---------|
| VM management | `qm` commands via root agent | `virsh` commands via root agent |
| Infrastructure provisioning | Terraform + provider | Direct `virt-install` + XML |
| Template | Proxmox VM template (VMID) | qcow2 base image (file path) |
| Disk management | Proxmox storage API | qcow2 overlays (backing file) |
| Network | Proxmox bridge (vmbr0) | Linux bridge or libvirt network |
| Cloud-init delivery | Terraform cloud-init provider | cloud-localds ISO attached as CDROM |
| API auth | Proxmox API token | libvirt local socket (no token needed) |
| First-boot installs | Proxmox VE + Terraform | qemu-kvm + libvirt + virtinst |
| Root agent actions | qm-start, qm-stop, qm-create, etc. | virsh-start, virsh-destroy, virsh-define, etc. |

## Key Files

| File | Purpose |
|------|---------|
| `PROJECT.yaml` | Machine-readable API spec (KEEP UPDATED) |
| `provisioner.json` | Provisioner manifest for engine integration |
| `scripts/vm-create.py` | Main entry point for VM creation |
| `scripts/vm-destroy.sh` | Destroy a VM (virsh + cleanup) |
| `scripts/vm-start.sh` | Start a VM via root agent |
| `scripts/vm-stop.sh` | Gracefully shut down a VM |
| `scripts/vm-kill.sh` | Force-stop a VM |
| `scripts/vm-status.sh` | Print VM status |
| `scripts/vm-list.sh` | List all VMs |
| `scripts/vm-gc.py` | Garbage collection for expired VMs |
| `scripts/vm-resume.py` | Resume a suspended VM |
| `scripts/mint_nft.py` | NFT minting via Foundry cast |
| `scripts/build-template.sh` | qcow2 template builder |
| `scripts/provisioner-detect.sh` | Detect libvirt/KVM host |
| `blockhost/provisioner_libvirt/wizard.py` | Wizard plugin (Blueprint, finalization, summary) |
| `provisioner-hooks/first-boot.sh` | First-boot hook (installs libvirt stack) |
| `root-agent-actions/virsh.py` | Root agent virsh actions plugin |

### From blockhost-common package

| Module/File | Purpose |
|-------------|---------|
| `blockhost.config` | Config loading (load_db_config, load_web3_config) |
| `blockhost.vm_db` | Database abstraction (VMDatabase, MockVMDatabase, get_database) |
| `blockhost.root_agent` | Root agent client (sends action requests to daemon) |
| `blockhost.cloud_init` | Cloud-init template rendering (render_cloud_init, find_template) |
| `/etc/blockhost/db.yaml` | Database config + provisioner-specific keys |
| `/etc/blockhost/web3-defaults.yaml` | Blockchain/NFT settings |

## Mandatory: Keep PROJECT.yaml Updated

**After ANY modification to the scripts, you MUST update `PROJECT.yaml`** to reflect:
1. New/changed CLI arguments
2. New/changed Python functions
3. New/changed config options
4. Changed workflow/behavior

## Testing Changes

Test with mock database:
```bash
python3 scripts/vm-create.py test-vm --owner-wallet 0x1234... --mock --skip-mint
```

## Pre-Push Documentation Check

**Before creating a commit or pushing to GitHub**, you MUST:
1. Re-read `PROJECT.yaml` and verify it reflects all changes
2. Re-read `CLAUDE.md` and verify the Key Files table and other sections are accurate
3. Fix any stale documentation before committing
