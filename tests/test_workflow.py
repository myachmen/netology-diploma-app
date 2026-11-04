"""Regression checks on privileged job boundaries, independent of GitHub secrets."""
import itertools
from pathlib import Path
import re
import unittest

TEXT = (Path(__file__).resolve().parents[1] / '.github/workflows/docker-publish.yml').read_text()


def job(name):
    match = re.search(r'^  ' + re.escape(name) + r':\n(.*?)(?=^  [a-zA-Z][\w-]*:|\Z)', TEXT, re.M | re.S)
    if not match:
        raise AssertionError('Missing job ' + name)
    return match[1]


class WorkflowSecurity(unittest.TestCase):
    def test_deploy_cannot_run_even_with_all_approvals(self):
        deploy = job('deploy')
        condition = re.search(r'^    if: >-\n((?:      .*\n)+)', deploy, re.M)[1]
        # A literal false joined only by AND is false for EVERY runtime context.
        # Reject OR or a moved/missing kill switch, even with all other gates true.
        self.assertTrue(condition.lstrip().startswith('false &&'))
        self.assertNotIn('||', condition)
        self.assertNotIn('always()', condition)
        self.assertIn('github.event_name == \'push\'', condition)
        self.assertIn('github.ref_type == \'tag\'', condition)
        self.assertIn('environment: diploma-production', deploy)
        self.assertIn('cancel-in-progress: false', deploy)

    def test_untrusted_and_preparation_events_cannot_publish(self):
        condition = re.search(r'^    if: >-\n((?:      .*\n)+)', job('build-and-push'), re.M)[1]
        # Evaluate this small, fixed grammar as a truth table, not a hand-copied policy.
        expression = ' '.join(condition.split()).replace('&&', ' and ').replace('||', ' or ')
        for repo, event, ref in itertools.product(
                ['myachmen/netology-diploma-app', 'untrusted/fork'],
                ['push', 'pull_request', 'pull_request_target', 'workflow_dispatch', 'workflow_run'],
                ['refs/heads/main', 'refs/heads/feature/diploma-ci-cd-prep-137', 'refs/tags/v1.0.0']):
            values = {'github.repository': repo, 'github.event_name': event, 'github.ref': ref}
            rendered = expression
            for key, value in values.items():
                rendered = rendered.replace(key, repr(value))
            actual = eval(rendered, {'__builtins__': {}, 'startsWith': lambda s, p: s.startswith(p)}, {})
            expected = repo == 'myachmen/netology-diploma-app' and event == 'push' and ref in ('refs/heads/main', 'refs/tags/v1.0.0')
            with self.subTest(repo=repo, event=event, ref=ref):
                self.assertEqual(actual, expected)

    def test_test_gate_has_no_privileged_access(self):
        test = job('test')
        self.assertNotIn('secrets.', test)
        self.assertNotIn('environment:', test)
        self.assertNotIn('write', test)
        self.assertIn('needs: test', job('build-and-push'))
        self.assertNotIn('pull_request_target:', TEXT)
        self.assertNotIn('workflow_run:', TEXT)
        self.assertNotIn('id-token:', TEXT)
        self.assertIn('permissions:\n  contents: read', TEXT)
        self.assertIn('persist-credentials: false', test)
        self.assertNotIn('--insecure', TEXT)


if __name__ == '__main__':
    unittest.main()
