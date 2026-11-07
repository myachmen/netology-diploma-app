"""Small offline checker for the diploma workflow's privileged boundaries."""
import re

BUILD_TERMS = {
    "github.repository == 'myachmen/netology-diploma-app'",
    "github.event_name == 'push'",
    "github.run_attempt == 1",
    "(github.ref == 'refs/heads/main' || github.ref_type == 'tag')"}
TERMS = {
    "github.repository == 'myachmen/netology-diploma-app'",
    "github.event_name == 'push'", "github.ref_type == 'tag'", "github.run_attempt == 1",
    "needs.test.result == 'success'", "needs['build-and-push'].result == 'success'",
    "needs['build-and-push'].outputs.release == 'true'"}


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


def conjuncts(expression, expected):
    terms = expression.split(' && ')
    if set(terms) != expected or len(terms) != len(expected):
        raise ValueError('Unsafe job condition')


def check_workflow(text):
    deploy, build, test = (job(text, name) for name in ('deploy', 'build-and-push', 'test'))
    expression = condition(deploy)
    preparation = expression.startswith('false && ')
    conjuncts(expression, TERMS | ({'false'} if preparation else set()))
    conjuncts(condition(build), BUILD_TERMS)
    if not all(item in deploy for item in ('timeout-minutes: 10', 'cancel-in-progress: false',
                                          'run: bash ci/deploy.sh', 'contents: read')):
        raise ValueError('Missing bounded deployment boundary')
    if 'needs: [test, build-and-push]' not in deploy or 'needs: test' not in build:
        raise ValueError('Missing test/build dependency')
    if 'secrets.' in test or 'environment:' in test or 'write' in test:
        raise ValueError('Privileged test job')
    if any(item in text for item in ('pull_request_target:', 'workflow_run:', 'workflow_dispatch:',
                                    'id-token:', 'contents: write')):
        raise ValueError('Untrusted trigger or excess permission')
    if any(item in text for item in ('APH-CD/1', 'CD_EXPECTED_', 'CD_GITHUB_READ_TOKEN',
                                    'CD_PROFILE', 'CD_ENABLED', 'environment:')):
        raise ValueError('Obsolete mandatory admission dependency')
    if "branches: ['**']" not in text or "tags: ['v*.*.*']" not in text:
        raise ValueError('Push/tag coverage missing')
    if "group: diploma-app-run-${{ github.ref_type == 'tag' && 'production' || github.ref }}" not in text:
        raise ValueError('Missing complete release serialization')
    actions = re.findall(r'uses: ([^\s#]+)', text)
    if not actions or any(not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[0-9a-f]{40}', action)
                          for action in actions):
        raise ValueError('Action is not pinned to a commit')
    return 'PREPARATION' if preparation else 'RELEASE'
