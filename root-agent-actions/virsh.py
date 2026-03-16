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

from _common import (
    log,
    run,
)

# Domain name validation: alphanumeric, hyphens, underscores, dots
DOMAIN_RE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$')

# Linux username: starts with lowercase letter or underscore, then alnum/hyphen/underscore
USERNAME_RE = re.compile(r'^[a-z_][a-z0-9_-]{0,31}$')

# GECOS for update-gecos: wallet=<addr>,nft=<id> — safe chars only, no shell/JSON injection
GECOS_RE = re.compile(r'^[a-zA-Z0-9=,._:-]{10,200}$')


def validate_domain(params):
    """Extract and validate domain name from params."""
    domain = params.get('domain', '')
    if not isinstance(domain, str) or not DOMAIN_RE.match(domain):
        raise ValueError(f'Invalid domain name: {domain}')
    return domain


def _handle_virsh_simple(params, subcommand, extra_args=(), timeout=120):
    """Run a simple virsh subcommand that only takes a domain name."""
    domain = validate_domain(params)
    rc, out, err = run(
        ['virsh', subcommand, domain] + list(extra_args),
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


def handle_virsh_update_gecos(params):
    """Update a user's GECOS field inside a running VM via QEMU guest agent.

    Purpose-built action — only runs usermod -c, nothing else.

    params:
        domain (str):   VM domain name
        username (str): Linux username to modify
        gecos (str):    New GECOS value (format: wallet=<addr>,nft=<id>)
    """
    domain = validate_domain(params)

    username = params.get('username', '')
    if not isinstance(username, str) or not USERNAME_RE.match(username):
        return {'ok': False, 'error': f'Invalid username: {username!r}'}

    gecos = params.get('gecos', '')
    if not isinstance(gecos, str) or not GECOS_RE.match(gecos):
        return {'ok': False, 'error': f'Invalid GECOS value: {gecos!r}'}

    # guest-exec: run usermod -c "<gecos>" <username> inside the VM
    exec_cmd = json.dumps({
        'execute': 'guest-exec',
        'arguments': {
            'path': '/usr/sbin/usermod',
            'arg': ['-c', gecos, username],
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

    # Poll for completion — usermod is near-instant, but be thorough
    status_cmd = json.dumps({
        'execute': 'guest-exec-status',
        'arguments': {'pid': pid},
    })

    for _ in range(10):
        time.sleep(0.5)
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

        if result.get('exited', False):
            exitcode = result.get('exitcode', -1)
            if exitcode == 0:
                return {'ok': True, 'output': 'GECOS updated'}
            err_data = result.get('err-data', '')
            if err_data:
                err_msg = base64.b64decode(err_data).decode('utf-8', errors='replace')
            else:
                err_msg = f'exitcode={exitcode}'
            return {'ok': False, 'error': f'usermod failed: {err_msg}'}

    return {'ok': False, 'error': 'guest-exec timed out waiting for usermod'}


ACTIONS = {
    'virsh-start':    lambda p: _handle_virsh_simple(p, 'start'),
    'virsh-destroy':  lambda p: _handle_virsh_simple(p, 'destroy'),        # force stop (confusing, blame libvirt)
    'virsh-shutdown': lambda p: _handle_virsh_simple(p, 'shutdown', timeout=300),  # graceful ACPI
    'virsh-reboot':   lambda p: _handle_virsh_simple(p, 'reboot'),
    'virsh-define':   handle_virsh_define,
    'virsh-undefine': handle_virsh_undefine,
    'virsh-update-gecos': handle_virsh_update_gecos,
}
