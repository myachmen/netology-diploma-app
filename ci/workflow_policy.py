"""Static PREPARATION/ACTIVATION policy; no network, YAML dependency or execution."""
import re

TERMS = {
    "github.repository == 'myachmen/netology-diploma-app'",
    "github.event_name == 'push'", "github.ref_type == 'tag'", "github.run_attempt == 1",
    'github.ref == vars.CD_EXPECTED_REF', 'github.sha == vars.CD_EXPECTED_SHA',
    "needs.test.result == 'success'", "needs['build-and-push'].result == 'success'",
    "needs['build-and-push'].outputs.release == 'true'",
    "vars.CD_ENABLED == 'true'", "vars.CD_SSH_TUNNEL_APPROVED == 'true'"}


def job(text, name):
    match = re.search(r'^  ' + re.escape(name) + r':\n(.*?)(?=^  [a-zA-Z][\w-]*:|\Z)', text, re.M | re.S)
    if not match:
        raise ValueError('Missing job ' + name)
    return match[1]


def condition(block):
    match = re.search(r'^    if: >-\n((?:      .*\n)+)', block, re.M)
    if not match:
        raise ValueError('Missing canonical conditional')
    return ' '.join(match[1].split())


def check_workflow(text, profile):
    if profile not in ('PREPARATION', 'ACTIVATION'):
        raise ValueError('Unknown policy profile')
    deploy = job(text, 'deploy')
    expression = condition(deploy)
    expected = TERMS | ({'false'} if profile == 'PREPARATION' else set())
    terms = expression.split(' && ')
    if set(terms) != expected or len(terms) != len(expected):
        raise ValueError('Deployment condition violates fail-closed policy')
    if profile == 'PREPARATION' and not expression.startswith('false && '):
        raise ValueError('Preparation kill switch is missing')
    required = ('environment: diploma-production', 'timeout-minutes: 10',
                'cancel-in-progress: false', 'CD_PROFILE: ' + profile,
                'run: bash ci/deploy.sh', 'contents: read')
    if not all(item in deploy for item in required):
        raise ValueError('Missing deployment scope/approval/profile boundary')
    if 'pull_request_target:' in text or 'workflow_run:' in text or 'id-token:' in text:
        raise ValueError('Untrusted trigger/permission')
    test = job(text, 'test')
    if 'secrets.' in test or 'environment:' in test or 'write' in test:
        raise ValueError('Privileged test job')
    if 'needs: test' not in job(text, 'build-and-push'):
        raise ValueError('Test gate bypass')
    actions = re.findall(r'uses: ([^\s#]+)', text)
    if not actions or any(not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[0-9a-f]{40}', action)
                          for action in actions):
        raise ValueError('Action is not pinned to a commit')
    return True
