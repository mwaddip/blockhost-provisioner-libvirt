#!/usr/bin/env python3
"""
blockhost-vm-metrics — Collect VM resource usage metrics.

Contract:
  blockhost-vm-metrics <name>
  stdout: JSON with cpu, memory, disk, network metrics
  exit 0 on success, 1 if VM not found or not queryable.

Must be cheap — called at regular intervals for every active VM.
Cumulative counters are delta'd against a previous sample stored in
/var/lib/blockhost/metrics/<name>.json.

SPECIAL profile: S9 P7 E9 — robustness and reliability paramount.
"""

import base64
import json
import re
import subprocess
import sys
import time
from pathlib import Path


VM_NAME_RE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$')
STATE_DIR = Path("/var/lib/blockhost/metrics")

# virsh domstats state.state → contract state string
STATE_MAP = {
    1: "running",   # VIR_DOMAIN_RUNNING
    2: "running",   # VIR_DOMAIN_BLOCKED (waiting for I/O)
    3: "paused",    # VIR_DOMAIN_PAUSED
    4: "running",   # VIR_DOMAIN_SHUTDOWN (in progress)
    5: "stopped",   # VIR_DOMAIN_SHUTOFF
    6: "stopped",   # VIR_DOMAIN_CRASHED
    7: "paused",    # VIR_DOMAIN_PMSUSPENDED
}


def err(msg):
    """Print to stderr."""
    print(f"[vm-metrics] {msg}", file=sys.stderr)


def fail(msg):
    """Print error to stderr and exit 1."""
    err(msg)
    sys.exit(1)


# --- virsh helpers ---


def _run_virsh(*args, timeout=5):
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


def _parse_domstats(output):
    """Parse virsh domstats output into a flat dict of key=value pairs."""
    stats = {}
    for line in output.strip().splitlines():
        line = line.strip()
        if "=" in line:
            key, _, value = line.partition("=")
            stats[key.strip()] = value.strip()
    return stats


# --- Guest agent helpers ---


def _guest_agent_cmd(name, cmd_dict, timeout=2):
    """Run a QEMU guest agent command. Returns parsed JSON or None."""
    try:
        result = subprocess.run(
            ["virsh", "qemu-agent-command", name,
             json.dumps(cmd_dict), "--timeout", str(timeout)],
            capture_output=True, text=True, timeout=timeout + 3,
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError):
        pass
    return None


def _guest_exec(name, shell_cmd, timeout=3):
    """Run a shell command inside the VM via guest agent. Returns stdout or None."""
    response = _guest_agent_cmd(name, {
        "execute": "guest-exec",
        "arguments": {
            "path": "/bin/sh",
            "arg": ["-c", shell_cmd],
            "capture-output": True,
        },
    }, timeout=timeout)
    if not response:
        return None
    try:
        pid = response["return"]["pid"]
    except (KeyError, TypeError):
        return None

    # Poll for result — simple commands finish in < 1s
    for _ in range(6):
        time.sleep(0.3)
        resp = _guest_agent_cmd(name, {
            "execute": "guest-exec-status",
            "arguments": {"pid": pid},
        }, timeout=2)
        if not resp:
            continue
        try:
            result = resp["return"]
            if result.get("exited"):
                if result.get("exitcode", -1) == 0:
                    return base64.b64decode(
                        result.get("out-data", "")
                    ).decode("utf-8", errors="replace")
                return None
        except (KeyError, TypeError):
            continue
    return None


# --- State file for delta calculation ---


def _load_prev(name):
    """Load previous sample from state file. Returns dict or None."""
    path = STATE_DIR / f"{name}.json"
    try:
        with open(path) as f:
            data = json.load(f)
        if not isinstance(data, dict) or "timestamp" not in data:
            return None
        return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _save_sample(name, sample):
    """Save current sample to state file (atomic write)."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = STATE_DIR / f"{name}.json"
    tmp = path.with_suffix(".tmp")
    try:
        with open(tmp, "w") as f:
            json.dump(sample, f)
        tmp.replace(path)
    except OSError:
        pass


def _delta_rate(current, previous, dt):
    """Compute rate from counter delta. Returns 0 on wrap/reset."""
    if current < previous or dt <= 0:
        return 0
    return int((current - previous) / dt)


# --- Output templates ---


def _zeroed_metrics(state):
    """Return zeroed metrics for a non-running VM."""
    return {
        "cpu_percent": 0.0,
        "cpu_count": 0,
        "memory_used_mb": 0,
        "memory_total_mb": 0,
        "disk_used_mb": -1,
        "disk_total_mb": 0,
        "disk_read_iops": 0,
        "disk_write_iops": 0,
        "disk_read_bytes_sec": 0,
        "disk_write_bytes_sec": 0,
        "net_rx_bytes_sec": 0,
        "net_tx_bytes_sec": 0,
        "net_connections": -1,
        "guest_agent_responsive": False,
        "uptime_seconds": 0,
        "state": state,
    }


def main():
    if len(sys.argv) != 2:
        err("Usage: blockhost-vm-metrics <name>")
        sys.exit(1)

    name = sys.argv[1]
    if not VM_NAME_RE.match(name):
        fail(f"Invalid VM name: {name!r}")

    # --- Collect domstats (single call: CPU, memory, disk, network, state) ---

    rc, out, _ = _run_virsh("domstats", name)
    if rc != 0:
        fail(f"VM not found or not queryable: {name}")

    stats = _parse_domstats(out)
    if not stats:
        fail(f"Empty domstats for VM: {name}")

    # --- State ---

    state_num = int(stats.get("state.state", 0))
    state = STATE_MAP.get(state_num, "unknown")

    if state in ("stopped", "unknown"):
        print(json.dumps(_zeroed_metrics(state)))
        sys.exit(0)

    # --- Delta setup ---

    now = time.time()
    prev = _load_prev(name)
    dt = (now - prev["timestamp"]) if prev else 0
    # Need at least 0.5s between samples for meaningful deltas
    use_deltas = prev is not None and dt > 0.5

    # --- CPU ---

    cpu_count = int(stats.get("vcpu.current", stats.get("vcpu.maximum", 1)))
    cpu_time_ns = int(stats.get("cpu.time", 0))

    cpu_percent = 0.0
    if use_deltas:
        d_cpu = cpu_time_ns - prev.get("cpu_time_ns", 0)
        if d_cpu >= 0 and dt > 0:
            cpu_percent = (d_cpu / (dt * 1e9)) * 100
            cpu_percent = round(max(0.0, min(cpu_percent, cpu_count * 100.0)), 1)

    # --- Memory ---

    mem_max_kb = int(stats.get("balloon.maximum", 0))
    mem_rss_kb = int(stats.get("balloon.rss", 0))
    memory_total_mb = mem_max_kb // 1024
    memory_used_mb = mem_rss_kb // 1024 if mem_rss_kb else memory_total_mb

    # --- Disk I/O (block.0 = vda, the main disk) ---

    blk_rd_reqs = int(stats.get("block.0.rd.reqs", 0))
    blk_wr_reqs = int(stats.get("block.0.wr.reqs", 0))
    blk_rd_bytes = int(stats.get("block.0.rd.bytes", 0))
    blk_wr_bytes = int(stats.get("block.0.wr.bytes", 0))
    blk_capacity = int(stats.get("block.0.capacity", 0))

    disk_total_mb = blk_capacity // (1024 * 1024) if blk_capacity else 0

    if use_deltas:
        disk_read_iops = _delta_rate(blk_rd_reqs, prev.get("blk_rd_reqs", 0), dt)
        disk_write_iops = _delta_rate(blk_wr_reqs, prev.get("blk_wr_reqs", 0), dt)
        disk_read_bytes_sec = _delta_rate(blk_rd_bytes, prev.get("blk_rd_bytes", 0), dt)
        disk_write_bytes_sec = _delta_rate(blk_wr_bytes, prev.get("blk_wr_bytes", 0), dt)
    else:
        disk_read_iops = 0
        disk_write_iops = 0
        disk_read_bytes_sec = 0
        disk_write_bytes_sec = 0

    # --- Network I/O ---

    net_rx = int(stats.get("net.0.rx.bytes", 0))
    net_tx = int(stats.get("net.0.tx.bytes", 0))

    if use_deltas:
        net_rx_bytes_sec = _delta_rate(net_rx, prev.get("net_rx", 0), dt)
        net_tx_bytes_sec = _delta_rate(net_tx, prev.get("net_tx", 0), dt)
    else:
        net_rx_bytes_sec = 0
        net_tx_bytes_sec = 0

    # --- Guest agent (all skipped if ping fails) ---

    guest_agent_responsive = False
    disk_used_mb = -1
    net_connections = -1
    uptime_seconds = -1

    ping = _guest_agent_cmd(name, {"execute": "guest-ping"}, timeout=2)
    if ping is not None:
        guest_agent_responsive = True

        # Filesystem info → disk_used_mb (root partition)
        fsinfo = _guest_agent_cmd(name, {"execute": "guest-get-fsinfo"}, timeout=3)
        if fsinfo:
            try:
                for fs in fsinfo["return"]:
                    if fs.get("mountpoint") == "/":
                        used = fs.get("used-bytes")
                        if used is not None:
                            disk_used_mb = int(used) // (1024 * 1024)
                        break
            except (KeyError, TypeError):
                pass

        # Uptime + connection count in one guest-exec call
        combo = _guest_exec(
            name,
            "head -1 /proc/uptime; ss -tH 2>/dev/null | wc -l",
            timeout=3,
        )
        if combo:
            lines = combo.strip().split("\n")
            if len(lines) >= 1:
                try:
                    uptime_seconds = int(float(lines[0].split()[0]))
                except (ValueError, IndexError):
                    pass
            if len(lines) >= 2:
                try:
                    net_connections = int(lines[1].strip())
                except ValueError:
                    pass

    # --- Save sample for next delta ---

    _save_sample(name, {
        "timestamp": now,
        "cpu_time_ns": cpu_time_ns,
        "blk_rd_reqs": blk_rd_reqs,
        "blk_wr_reqs": blk_wr_reqs,
        "blk_rd_bytes": blk_rd_bytes,
        "blk_wr_bytes": blk_wr_bytes,
        "net_rx": net_rx,
        "net_tx": net_tx,
    })

    # --- Output ---

    print(json.dumps({
        "cpu_percent": cpu_percent,
        "cpu_count": cpu_count,
        "memory_used_mb": memory_used_mb,
        "memory_total_mb": memory_total_mb,
        "disk_used_mb": disk_used_mb,
        "disk_total_mb": disk_total_mb,
        "disk_read_iops": disk_read_iops,
        "disk_write_iops": disk_write_iops,
        "disk_read_bytes_sec": disk_read_bytes_sec,
        "disk_write_bytes_sec": disk_write_bytes_sec,
        "net_rx_bytes_sec": net_rx_bytes_sec,
        "net_tx_bytes_sec": net_tx_bytes_sec,
        "net_connections": net_connections,
        "guest_agent_responsive": guest_agent_responsive,
        "uptime_seconds": uptime_seconds,
        "state": state,
    }))


if __name__ == "__main__":
    main()
