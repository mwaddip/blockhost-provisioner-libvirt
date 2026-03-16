# blockhost-provisioner-libvirt

libvirt/KVM VM provisioning backend for [BlockHost](https://github.com/mwaddip/blockhost).

Implements the BlockHost provisioner contract using `virsh` + `cloud-init` instead of Proxmox VE + Terraform. Proof-of-concept for the provisioner abstraction layer.

## Status

**Core implemented.** VM create/destroy/start/stop/kill/status/list, wizard, root agent actions, and first-boot hook are working. GC, resume, metrics, and throttle are stubs. The engine owns the full NFT lifecycle; the provisioner receives `--nft-token-id` from the engine and bakes it into cloud-init.

## Prerequisites

- Debian 12 (Bookworm) host with KVM support
- `blockhost-common` package installed
- `blockhost-engine-evm` package installed (provides `nft_tool`)

## Package

```bash
./build-deb.sh
sudo dpkg -i build/blockhost-provisioner-libvirt_0.1.0_all.deb
```

## How It Works

| Component | Proxmox equivalent | libvirt approach |
|-----------|-------------------|-----------------|
| VM creation | Terraform apply | virt-install --import |
| VM management | qm commands | virsh commands |
| Template | Proxmox VM template | qcow2 base image |
| Disk | Proxmox storage | qcow2 overlays (CoW) |
| Cloud-init | Terraform provider | cloud-localds ISO |
| Network | Proxmox bridge | Linux bridge / libvirt network |
| Root agent | qm.py actions | virsh.py actions |
