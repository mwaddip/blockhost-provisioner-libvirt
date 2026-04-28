"""
libvirt/virsh actions for the BlockHost root agent.

Shipped by blockhost-provisioner-libvirt, loaded by the root agent daemon from
/usr/share/blockhost/root-agent-actions/.

Equivalent to qm.py in the Proxmox provisioner, but uses virsh instead of qm.
"""

import base64
import json
import os
import re
import time

from _common import run

# Domain name validation: alphanumeric, hyphens, underscores, dots
DOMAIN_RE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$')

# guest-exec command: qemu-guest-agent rejects payloads over ~4KB. The command
# itself is evaluated by /bin/sh inside the VM, so shell metacharacters are
# expected and not filtered here — the boundary is VM-internal, not host.
GUEST_EXEC_MAX_LEN = 4000
GUEST_EXEC_POLL_TIMEOUT = 120  # seconds — covers network hook ops (sed, echo, curl)
GUEST_EXEC_POLL_INTERVAL = 0.3


def validate_domain(params):
    """Extract and validate domain name from params."""
    domain = params.get('domain', '')
    if not isinstance(domain, str) or not DOMAIN_RE.match(domain):
        raise ValueError(f'Invalid domain name: {domain}')
    return domain


def _handle_virsh_simple(params, subcommand, timeout=120):
    """Run a simple virsh subcommand that only takes a domain name."""
    domain = validate_domain(params)
    rc, out, err = run(
        ['virsh', subcommand, domain],
        timeout=timeout,
    )
    if rc != 0:
        return {'ok': False, 'error': err or out}
    return {'ok': True, 'output': out}


def handle_virsh_define(params):
    """Define a domain from an XML file.

    params:
        xml_path (str): Path to domain XML (must be under /var/lib/blockhost/)
    """
    xml_path = params.get('xml_path', '')
    if not isinstance(xml_path, str) or not xml_path:
        return {'ok': False, 'error': 'xml_path is required'}
    real_path = os.path.realpath(xml_path)
    if not real_path.startswith('/var/lib/blockhost/'):
        return {'ok': False, 'error': 'xml_path must be under /var/lib/blockhost/'}
    if not os.path.isfile(xml_path):
        return {'ok': False, 'error': f'XML file not found: {xml_path}'}

    rc, out, err = run(['virsh', 'define', xml_path], timeout=30)
    if rc != 0:
        return {'ok': False, 'error': err or out}
    return {'ok': True, 'output': out}


def handle_virsh_undefine(params):
    """Undefine a domain and optionally remove storage.

    params:
        domain (str): Domain name
        remove_storage (bool): Also remove associated storage volumes
    """
    domain = validate_domain(params)
    cmd = ['virsh', 'undefine', domain]
    if params.get('remove_storage', False):
        cmd.append('--remove-all-storage')

    rc, out, err = run(cmd, timeout=60)
    if rc != 0:
        return {'ok': False, 'error': err or out}
    return {'ok': True, 'output': out}


def handle_virsh_guest_exec(params):
    """Execute a shell command inside a running VM via QEMU guest agent.

    Generic guest-exec primitive. The command string is run as `/bin/sh -c
    <command>` inside the VM — shell metacharacters are expected, not
    filtered (the boundary is inside the guest, not on the host).

    params:
        domain (str):  VM domain name
        command (str): Shell command to execute inside the VM

    Returns on success:
        {'ok': True, 'exitcode': int, 'stdout': str, 'stderr': str}

    Returns on guest-agent failure:
        {'ok': False, 'error': str}
    """
    domain = validate_domain(params)

    command = params.get('command', '')
    if not isinstance(command, str) or not command:
        return {'ok': False, 'error': 'command is required'}
    if len(command) > GUEST_EXEC_MAX_LEN:
        return {'ok': False, 'error': f'command too long (>{GUEST_EXEC_MAX_LEN} bytes)'}

    exec_cmd = json.dumps({
        'execute': 'guest-exec',
        'arguments': {
            'path': '/bin/sh',
            'arg': ['-c', command],
            'capture-output': True,
        },
    })

    rc, out, err = run(
        ['virsh', 'qemu-agent-command', domain, exec_cmd],
        timeout=30,
    )
    if rc != 0:
        return {'ok': False, 'error': err or out}

    try:
        pid = json.loads(out)['return']['pid']
    except (json.JSONDecodeError, KeyError) as exc:
        return {'ok': False, 'error': f'Failed to parse guest-exec response: {exc}'}

    status_cmd = json.dumps({
        'execute': 'guest-exec-status',
        'arguments': {'pid': pid},
    })

    deadline = time.monotonic() + GUEST_EXEC_POLL_TIMEOUT
    while time.monotonic() < deadline:
        time.sleep(GUEST_EXEC_POLL_INTERVAL)
        rc, out, err = run(
            ['virsh', 'qemu-agent-command', domain, status_cmd],
            timeout=10,
        )
        if rc != 0:
            return {'ok': False, 'error': err or out}

        try:
            result = json.loads(out)['return']
        except (json.JSONDecodeError, KeyError):
            continue

        if not result.get('exited', False):
            continue

        stdout = ''
        stderr = ''
        if result.get('out-data'):
            stdout = base64.b64decode(result['out-data']).decode('utf-8', errors='replace')
        if result.get('err-data'):
            stderr = base64.b64decode(result['err-data']).decode('utf-8', errors='replace')
        return {
            'ok': True,
            'exitcode': int(result.get('exitcode', 0)),
            'stdout': stdout,
            'stderr': stderr,
        }

    return {'ok': False, 'error': f'guest-exec timed out after {GUEST_EXEC_POLL_TIMEOUT}s'}


ACTIONS = {
    'virsh-start':    lambda p: _handle_virsh_simple(p, 'start'),
    'virsh-destroy':  lambda p: _handle_virsh_simple(p, 'destroy'),        # force stop (confusing, blame libvirt)
    'virsh-shutdown': lambda p: _handle_virsh_simple(p, 'shutdown', timeout=300),  # graceful ACPI
    'virsh-define':   handle_virsh_define,
    'virsh-undefine': handle_virsh_undefine,
    'virsh-guest-exec':   handle_virsh_guest_exec,
}
