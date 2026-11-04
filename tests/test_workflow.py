"""Workflow routing and security checks, no network or credentials."""
import itertools
from pathlib import Path
import re
import unittest

from ci.workflow_policy import BUILD_TERMS, TERMS, check_workflow, condition, job

ROOT = Path(__file__).resolve().parents[1]
TEXT = (ROOT / '.github/workflows/docker-publish.yml').read_text()


def evaluate(expression, values):
    expression = expression.replace('&&', ' and ').replace('||', ' or ')
    for key, value in sorted(values.items(), key=lambda p: -len(p[0])):
        expression = expression.replace(key, repr(value))
    return eval(expression, {'__builtins__': {}, 'false': False}, {})


class WorkflowSecurity(unittest.TestCase):
    def test_current_and_future_release_profile(self):
        # Removing ONE documented preparation switch must not break the tests.
        self.assertIn(check_workflow(TEXT), ('PREPARATION', 'RELEASE'))
        active = TEXT.replace('      false &&\n', '', 1)
        self.assertEqual(check_workflow(active), 'RELEASE')
        prep = active.replace("      github.repository ==", "      false &&\n      github.repository ==", 1)
        # A false in the build condition is not the deploy preparation switch.
        with self.assertRaises(ValueError):
            check_workflow(prep)
        for term in TERMS:
            block = job(active, 'deploy')
            with self.subTest(missing=term), self.assertRaises(ValueError):
                check_workflow(active.replace(block, block.replace(term, 'true', 1), 1))
        for term in BUILD_TERMS:
            block = job(active, 'build-and-push')
            with self.subTest(build_missing=term), self.assertRaises(ValueError):
                check_workflow(active.replace(block, block.replace(term, 'true', 1), 1))

    def test_push_and_tag_paths_and_untrusted_events(self):
        active = TEXT.replace('      false &&\n', '', 1)
        for repo, event, ref, attempt, success in itertools.product(
                ['myachmen/netology-diploma-app', 'fork/app'],
                ['push', 'pull_request', 'pull_request_target', 'workflow_dispatch', 'workflow_run'],
                ['refs/heads/main', 'refs/heads/ordinary-feature',
                 'refs/heads/feature/diploma-minimal-cd-142', 'refs/tags/v1.0.2'],
                [1, 2], [True, False]):
            publish = repo == 'myachmen/netology-diploma-app' and event == 'push' and ref != 'refs/heads/feature/diploma-minimal-cd-142'
            values = {'github.repository': repo, 'github.event_name': event,
                      'github.ref_type': 'tag' if ref.startswith('refs/tags/') else 'branch',
                      'github.ref': ref, 'github.run_attempt': attempt,
                      'needs.test.result': 'success' if success else 'failure',
                      "needs['build-and-push'].result": 'success' if success else 'failure',
                      "needs['build-and-push'].outputs.release": 'true' if ref.startswith('refs/tags/') else 'false'}
            with self.subTest(repo=repo, event=event, ref=ref, attempt=attempt, success=success):
                self.assertEqual(evaluate(condition(job(TEXT, 'build-and-push')), values), publish)
                expected = publish and success and ref.startswith('refs/tags/') and attempt == 1
                self.assertEqual(evaluate(condition(job(active, 'deploy')), values), expected)
                if check_workflow(TEXT) == 'PREPARATION':
                    self.assertFalse(evaluate(condition(job(TEXT, 'deploy')), values))

    def test_permissions_pins_and_source_digest_binding(self):
        self.assertIn('permissions:\n  contents: read', TEXT)
        test = job(TEXT, 'test')
        self.assertNotIn('secrets.', test)
        self.assertIn('persist-credentials: false', test)
        self.assertIn('ref: ${{ github.sha }}', job(TEXT, 'deploy'))
        self.assertIn("IMAGE_DIGEST: ${{ needs['build-and-push'].outputs.digest }}", TEXT)
        self.assertIn('org.opencontainers.image.revision=${{ steps.release.outputs.sha }}', TEXT)
        self.assertIn('org.opencontainers.image.version=${{ steps.release.outputs.version }}', TEXT)
        self.assertIn('git merge-base --is-ancestor', TEXT)
        action = re.search(r'uses: ([^\s#]+)', TEXT)[1]
        with self.assertRaises(ValueError):
            check_workflow(TEXT.replace(action, 'actions/checkout@v4'))
        block = job(TEXT, 'deploy')
        with self.assertRaises(ValueError):
            check_workflow(TEXT.replace(block, block.replace(' &&', ' ||', 1), 1))

    def test_script_has_one_guarded_mutation_and_strict_connection(self):
        text = (ROOT / 'ci/deploy.sh').read_text()
        self.assertEqual(len(re.findall(r'^kubectl .* patch deployment', text, re.M)), 1)
        self.assertLess(text.index('python3 -m ci.release --credentials'), text.index('ssh -F'))
        self.assertLess(text.index('python3 -m ci.deployment patch'), text.index('kubectl --request-timeout=30s -n default patch'))
        for required in ('StrictHostKeyChecking=yes', 'IdentityAgent=none', 'GlobalKnownHostsFile=/dev/null',
                         '127.0.0.1:17643:127.0.0.1:6443', "'tls-server-name'", '--timeout=180s',
                         'python3 -m ci.deployment reply', 'python3 -m ci.deployment final',
                         'unset SSH_PRIVATE_KEY SSH_KNOWN_HOSTS KUBE_CA_B64 KUBE_TOKEN', 'trap cleanup EXIT'):
            self.assertIn(required, text)
        for forbidden in ('--insecure', 'skip-tls-verify', 'rollout undo', 'helm ', 'set image', '--retry'):
            self.assertNotIn(forbidden, text)
