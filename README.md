# blockhost-provisioner-libvirt

libvirt/KVM VM provisioning backend for [BlockHost](https://github.com/mwaddip/blockhost).

Implements the BlockHost provisioner contract using `virsh` + `cloud-init` instead of Proxmox VE + Terraform. Proof-of-concept for the provisioner abstraction layer.

## Status

**Scaffolded.** All contract interfaces are wired up (manifest, CLI stubs, wizard plugin, root agent actions, first-boot hook). Implementation of the actual VM lifecycle commands is in progress.

## Prerequisites

- Debian 12 (Bookworm) host with KVM support
- `blockhost-common` package installed
- `libpam-web3-tools` package installed

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
