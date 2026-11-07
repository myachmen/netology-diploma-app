"""Redacted visibility for the existing bounded Deployment GET gate only.

Categories describe recognizable error patterns, not independently proven causes.
Never emit stderr, endpoints, certificate details or credentials.
"""
import argparse
import os
from pathlib import Path
import subprocess
import time

ATTEMPTS = 10
REQUEST_SECONDS = 5
PROCESS_SECONDS = 7
DELAY_SECONDS = 1
MAX_ERROR_BYTES = 65536
COMMAND = ['kubectl', f'--request-timeout={REQUEST_SECONDS}s', '-n', 'default',
           'get', 'deployment', 'diploma-app', '-o', 'name']


def classify(api_error, ssh_error, tunnel_alive, timed_out=False):
    """Allowlisted categories only. API responses outrank old forwarding errors."""
    api, ssh = api_error.lower(), ssh_error.lower()
    ssh_patterns = (
        ('SSH_HOST_KEY_FAILURE', ('host key verification failed', 'remote host identification has changed')),
        ('SSH_AUTH_FAILURE', ('permission denied (publickey', 'no supported authentication methods',
                              'load key ', 'error in libcrypto', 'invalid format')),
        ('SSH_LOCAL_BIND_FAILURE', ('address already in use', 'cannot listen to port',
                                    'could not request local forwarding')),
        ('SSH_FORWARD_FAILURE', ('open failed: administratively prohibited',
                                 'open failed: connect failed')),
        ('SSH_CONNECT_TIMEOUT', ('connection timed out', 'operation timed out')),
        ('SSH_NETWORK_FAILURE', ('connection refused', 'no route to host', 'could not resolve hostname')),
    )
    ssh_category = next((name for name, patterns in ssh_patterns
                         if any(p in ssh for p in patterns)), None)
    if not tunnel_alive:
        return ssh_category or 'SSH_PROCESS_EXITED'
    api_patterns = (
        ('API_TLS_FAILURE', ('x509:', 'tls: failed to verify certificate', 'tls: bad certificate',
                             'certificate signed by unknown authority', 'unable to read certificate-authority')),
        ('API_AUTH_401', ('(unauthorized)', 'you must be logged in', 'provide credentials', '401 unauthorized')),
        ('API_RBAC_403', ('(forbidden)', ' is forbidden:', '403 forbidden')),
        ('API_NOT_FOUND_404', ('(notfound)', 'deployments.apps "diploma-app" not found', '404 not found')),
    )
    for name, patterns in api_patterns:
        if any(p in api for p in patterns):
            return name
    if ssh_category:
        return ssh_category
    if timed_out or any(p in api for p in ('i/o timeout', 'context deadline exceeded',
                                          'tls handshake timeout', 'client.timeout exceeded')):
        return 'API_TIMEOUT'
    if any(p in api for p in ('connection refused', 'connection reset', 'unexpected eof', 'no route to host')):
        return 'API_CONNECTION_FAILURE'
    return 'API_UNKNOWN'


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def read_tail(path):
    try:
        with path.open('rb') as stream:
            stream.seek(0, os.SEEK_END)
            stream.seek(max(0, stream.tell() - MAX_ERROR_BYTES))
            return stream.read(MAX_ERROR_BYTES).decode('utf-8', errors='replace')
    except OSError:
        return ''


def poll(pid, ssh_error, *, run=subprocess.run, is_alive=alive, sleep=time.sleep,
         read_error=read_tail, emit=print):
    """No probe beyond the old GET, no SSH respawn; <=79s watchdog/delay budget."""
    for attempt in range(1, ATTEMPTS + 1):
        if not is_alive(pid):
            category = classify('', read_error(ssh_error), False)
            emit(f'API_ACCESS FAIL attempt={attempt}/{ATTEMPTS} category={category} process=exited')
            return False
        timed_out = False
        try:
            reply = run(COMMAND, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                        text=True, timeout=PROCESS_SECONDS, check=False)
            code, error = reply.returncode, reply.stderr or ''
        except subprocess.TimeoutExpired:
            code, error, timed_out = 124, '', True
        except OSError:
            emit(f'API_ACCESS FAIL attempt={attempt}/{ATTEMPTS} category=LOCAL_TOOL_ERROR')
            return False
        running = is_alive(pid)
        if code == 0 and running:
            emit(f'API_ACCESS PASS attempt={attempt}/{ATTEMPTS} category=DEPLOYMENT_GET_OK')
            return True
        category = classify(error, read_error(ssh_error), running, timed_out)
        emit(f'API_ACCESS FAIL attempt={attempt}/{ATTEMPTS} category={category} '
             f'process={"running" if running else "exited"} exit={code}')
        # Retry only transient read failures. Trust/auth/RBAC/404/unknown => STOP.
        if not running or category not in ('API_TIMEOUT', 'API_CONNECTION_FAILURE'):
            return False
        if attempt < ATTEMPTS:
            sleep(DELAY_SECONDS)
    emit('API_ACCESS FAIL category=POLL_BUDGET_EXHAUSTED')
    return False


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--tunnel-pid', type=int, required=True)
    parser.add_argument('--ssh-error', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.tunnel_pid <= 0:
            raise ValueError('Invalid PID')
        ok = poll(args.tunnel_pid, args.ssh_error)
    except (OSError, ValueError, TypeError):
        # No exception text/traceback: it may contain a private path or value.
        print('API_ACCESS FAIL category=LOCAL_DIAGNOSTIC_ERROR')
        ok = False
    raise SystemExit(0 if ok else 1)
