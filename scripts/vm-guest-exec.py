#!/usr/bin/env python3
"""
blockhost-vm-guest-exec — Run a shell command inside a running VM.

Contract:
  blockhost-vm-guest-exec <name> <command...>
  Prints the command's stdout to stdout, its stderr to stderr.
  Exits with the command's exit code.

Generic primitive over the QEMU guest agent. The command is run as
`/bin/sh -c <command>` inside the VM. Used by the network hook (push
.onion into /etc/hosts, update signing URL) and by update-gecos (sed
or usermod the GECOS field on /etc/passwd).

The VM must be running with a responsive QEMU guest agent. If the
guest agent is unresponsive or the command cannot be started, exits
with a non-zero status and a message on stderr.
"""

import argparse
import sys


def err(msg):
    """Print to stderr with a consistent prefix."""
    print(f"[vm-guest-exec] {msg}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        description="Run a shell command inside a running VM via QEMU guest agent",
    )
    parser.add_argument("name", help="VM name (libvirt domain name)")
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Shell command to run inside the VM (remaining args)",
    )

    args = parser.parse_args()

    if not args.command:
        parser.error("command is required")

    # argparse.REMAINDER preserves tokens — join back into a single sh -c string.
    # Callers pass a quoted string as one arg ("echo hello") or multiple tokens
    # (echo hello); both collapse to the same shell command.
    command = " ".join(args.command)

    try:
        from blockhost.root_agent import call, RootAgentError
    except ImportError:
        err("blockhost-common not installed (cannot import blockhost.root_agent)")
        sys.exit(1)

    try:
        result = call(
            'virsh-guest-exec',
            domain=args.name,
            command=command,
        )
    except RootAgentError as exc:
        err(f"Root agent error: {exc}")
        sys.exit(1)

    stdout = result.get('stdout', '')
    stderr = result.get('stderr', '')
    exitcode = int(result.get('exitcode', 1))

    if stdout:
        sys.stdout.write(stdout)
        sys.stdout.flush()
    if stderr:
        sys.stderr.write(stderr)
        sys.stderr.flush()

    sys.exit(exitcode)


if __name__ == "__main__":
    main()
