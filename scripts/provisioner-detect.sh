#!/bin/bash
# Detect whether this host has libvirt/KVM available
# Exits 0 if libvirt is detected, 1 otherwise

command -v virsh >/dev/null 2>&1
