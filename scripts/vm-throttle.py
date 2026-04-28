#!/usr/bin/env python3
"""
blockhost-vm-throttle — Apply or remove resource limits on a running VM.

Contract:
  blockhost-vm-throttle <name> [options]
  Options are additive — only specified limits are changed.
  --reset removes all limits.
  stdout: one line per change applied.
  exit 0 on success, 1 on failure.

All virsh commands go through libvirtd (blockhost user has libvirt group
access). Limits are applied with --live so they affect only the running
instance — on restart, the monitor re-evaluates and re-applies if needed.

SPECIAL profile: S9 P7 E9 — robustness and reliability paramount.
"""

import argparse
import subprocess
import sys

from blockhost.naming import is_valid_domain_name
from blockhost.provisioner_libvirt.helpers import get_vm_tap_interface


def err(msg):
    """Print to stderr."""
    print(f"[vm-throttle] {msg}", file=sys.stderr)


def fail(msg):
    """Print error to stderr and exit 1."""
    err(msg)
    sys.exit(1)


# --- virsh helpers ---


def _run_virsh(*args, timeout=10):
    """Run a virsh command. Returns (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            ["virsh"] + list(args),
            capture_output=True, text=True, timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except FileNotFoundError:
        return -1, "", "virsh not found"


def _get_vm_state(name):
    """Get VM state string, or None if VM doesn't exist."""
    rc, out, _ = _run_virsh("domstate", name)
    if rc != 0:
        return None
    return out.strip()


# --- Limit application ---


def _apply_cpu_shares(name, shares):
    """Set CPU weight (shares)."""
    rc, _, stderr = _run_virsh(
        "schedinfo", name, "--live", "--set", f"cpu_shares={shares}",
    )
    if rc != 0:
        return False, f"schedinfo cpu_shares failed: {stderr.strip()}"
    print(f"CPU shares set to {shares}")
    return True, None


def _apply_cpu_quota(name, percent):
    """Set CPU hard cap.

    Converts percentage to vcpu_quota in microseconds per 100ms period.
    50% → 50000µs. 0 or negative → -1 (unlimited).
    """
    quota = percent * 1000 if percent > 0 else -1
    rc, _, stderr = _run_virsh(
        "schedinfo", name, "--live", "--set", f"vcpu_quota={quota}",
    )
    if rc != 0:
        return False, f"schedinfo vcpu_quota failed: {stderr.strip()}"
    if quota == -1:
        print("CPU quota removed (unlimited)")
    else:
        print(f"CPU quota set to {percent}%")
    return True, None


def _apply_bandwidth(name, tap, direction, kbps):
    """Set bandwidth limit on the VM's tap interface.

    direction: 'inbound' or 'outbound'
    kbps: kilobits per second (0 = remove limit)
    """
    if kbps == 0:
        rate_arg = "0"
    else:
        avg = max(1, kbps // 8)    # kbps → kB/s
        peak = max(1, avg * 2)     # burst to 2× sustained
        burst = max(1, avg)        # 1 second of data at avg rate
        rate_arg = f"{avg},{peak},{burst}"

    rc, _, stderr = _run_virsh(
        "domiftune", name, tap, "--live",
        f"--{direction}", rate_arg,
    )
    if rc != 0:
        return False, f"domiftune {direction} failed: {stderr.strip()}"
    if kbps == 0:
        print(f"Bandwidth {direction} limit removed (unlimited)")
    else:
        print(f"Bandwidth {direction} set to {kbps} kbps")
    return True, None


def _apply_iops(name, read_iops=None, write_iops=None):
    """Set IOPS limits on vda."""
    args = ["blkdeviotune", name, "vda", "--live"]
    changes = []

    if read_iops is not None:
        args.extend(["--read-iops-sec", str(read_iops)])
        changes.append(("read", read_iops))
    if write_iops is not None:
        args.extend(["--write-iops-sec", str(write_iops)])
        changes.append(("write", write_iops))

    if not changes:
        return True, None

    rc, _, stderr = _run_virsh(*args)
    if rc != 0:
        return False, f"blkdeviotune failed: {stderr.strip()}"
    for direction, value in changes:
        if value == 0:
            print(f"IOPS {direction} limit removed (unlimited)")
        else:
            print(f"IOPS {direction} set to {value}")
    return True, None


def _reset_all(name, tap):
    """Remove all throttling, restore defaults."""
    errors = []

    ok, e = _apply_cpu_shares(name, 1024)
    if not ok:
        errors.append(e)

    ok, e = _apply_cpu_quota(name, 0)  # 0 → -1 = unlimited
    if not ok:
        errors.append(e)

    if tap:
        ok, e = _apply_bandwidth(name, tap, "inbound", 0)
        if not ok:
            errors.append(e)
        ok, e = _apply_bandwidth(name, tap, "outbound", 0)
        if not ok:
            errors.append(e)
    else:
        err("WARNING: No tap interface found, skipping bandwidth reset")

    ok, e = _apply_iops(name, read_iops=0, write_iops=0)
    if not ok:
        errors.append(e)

    if errors:
        return False, "; ".join(errors)
    return True, None


def main():
    parser = argparse.ArgumentParser(
        description="Apply resource limits to a BlockHost VM",
    )
    parser.add_argument("name", help="VM name")
    parser.add_argument("--cpu-shares", type=int,
                        help="CPU weight (1-10000, default 1024)")
    parser.add_argument("--cpu-quota", type=int,
                        help="Hard CPU cap as %% of allocated vCPUs (1-100)")
    parser.add_argument("--bandwidth-in", type=int,
                        help="Inbound bandwidth limit in kbps (0=unlimited)")
    parser.add_argument("--bandwidth-out", type=int,
                        help="Outbound bandwidth limit in kbps (0=unlimited)")
    parser.add_argument("--iops-read", type=int,
                        help="Read IOPS limit (0=unlimited)")
    parser.add_argument("--iops-write", type=int,
                        help="Write IOPS limit (0=unlimited)")
    parser.add_argument("--reset", action="store_true",
                        help="Remove all limits, restore defaults")

    args = parser.parse_args()

    # --- Validate ---

    if not is_valid_domain_name(args.name):
        fail(f"Invalid VM name: {args.name!r}")

    if args.cpu_shares is not None and not 1 <= args.cpu_shares <= 10000:
        fail("--cpu-shares must be 1-10000")
    if args.cpu_quota is not None and not 1 <= args.cpu_quota <= 100:
        fail("--cpu-quota must be 1-100")
    if args.bandwidth_in is not None and args.bandwidth_in < 0:
        fail("--bandwidth-in must be >= 0")
    if args.bandwidth_out is not None and args.bandwidth_out < 0:
        fail("--bandwidth-out must be >= 0")
    if args.iops_read is not None and args.iops_read < 0:
        fail("--iops-read must be >= 0")
    if args.iops_write is not None and args.iops_write < 0:
        fail("--iops-write must be >= 0")

    has_options = any([
        args.cpu_shares is not None,
        args.cpu_quota is not None,
        args.bandwidth_in is not None,
        args.bandwidth_out is not None,
        args.iops_read is not None,
        args.iops_write is not None,
        args.reset,
    ])
    if not has_options:
        fail("No options specified (use --help for usage)")

    # --- Preflight ---

    state = _get_vm_state(args.name)
    if state is None:
        fail(f"VM not found: {args.name}")
    if state != "running":
        fail(f"VM is not running (state: {state})")

    # Discover tap interface (needed for bandwidth and reset)
    tap = None
    needs_tap = (
        args.bandwidth_in is not None
        or args.bandwidth_out is not None
        or args.reset
    )
    if needs_tap:
        tap = get_vm_tap_interface(args.name)
        if not tap and not args.reset:
            fail("Could not determine tap interface for bandwidth limit")

    # --- Apply ---

    if args.reset:
        ok, e = _reset_all(args.name, tap)
        if not ok:
            fail(e)
        sys.exit(0)

    errors = []

    if args.cpu_shares is not None:
        ok, e = _apply_cpu_shares(args.name, args.cpu_shares)
        if not ok:
            errors.append(e)

    if args.cpu_quota is not None:
        ok, e = _apply_cpu_quota(args.name, args.cpu_quota)
        if not ok:
            errors.append(e)

    if args.bandwidth_in is not None:
        if not tap:
            errors.append("No tap interface for inbound bandwidth")
        else:
            ok, e = _apply_bandwidth(args.name, tap, "inbound", args.bandwidth_in)
            if not ok:
                errors.append(e)

    if args.bandwidth_out is not None:
        if not tap:
            errors.append("No tap interface for outbound bandwidth")
        else:
            ok, e = _apply_bandwidth(args.name, tap, "outbound", args.bandwidth_out)
            if not ok:
                errors.append(e)

    if args.iops_read is not None or args.iops_write is not None:
        ok, e = _apply_iops(args.name, args.iops_read, args.iops_write)
        if not ok:
            errors.append(e)

    if errors:
        fail("; ".join(errors))


if __name__ == "__main__":
    main()
