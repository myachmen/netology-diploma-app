"""Regression checks on privileged job boundaries, independent of GitHub secrets."""
import itertools
from pathlib import Path
import re
import unittest

from ci.workflow_policy import TERMS, check_workflow, job as policy_job

TEXT = (Path(__file__).resolve().parents[1] / '.github/workflows/docker-publish.yml').read_text()


def job(name):
    match = re.search(r'^  ' + re.escape(name) + r':\n(.*?)(?=^  [a-zA-Z][\w-]*:|\Z)', TEXT, re.M | re.S)
    if not match:
        raise AssertionError('Missing job ' + name)
    return match[1]


class WorkflowSecurity(unittest.TestCase):
    def test_deploy_cannot_run_even_with_all_approvals(self):
        self.assertTrue(check_workflow(TEXT, 'PREPARATION'))
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

    def test_future_activation_fixture_retains_every_security_conjunct(self):
        fixture = TEXT.replace('      false &&\n', '', 1).replace('CD_PROFILE: PREPARATION', 'CD_PROFILE: ACTIVATION')
        self.assertTrue(check_workflow(fixture, 'ACTIVATION'))
        with self.assertRaises(ValueError):
            check_workflow(fixture, 'PREPARATION')
        with self.assertRaises(ValueError):
            check_workflow(TEXT, 'ACTIVATION')
        for term in TERMS:
            block = policy_job(fixture, 'deploy')
            with self.subTest(missing=term), self.assertRaises(ValueError):
                check_workflow(fixture.replace(block, block.replace(term, 'true', 1), 1), 'ACTIVATION')
        for old, new in [('environment: diploma-production', 'environment: other'),
                         ('cancel-in-progress: false', 'cancel-in-progress: true'),
                         ('timeout-minutes: 10', 'timeout-minutes: 0')]:
            with self.subTest(boundary=old), self.assertRaises(ValueError):
                check_workflow(fixture.replace(old, new), 'ACTIVATION')

    def test_unpinned_action_is_rejected_in_both_profiles(self):
        action = re.search(r'uses: ([^\s#]+)', TEXT)[1]
        with self.assertRaises(ValueError):
            check_workflow(TEXT.replace(action, 'actions/checkout@v4'), 'PREPARATION')

    def test_untrusted_and_preparation_events_cannot_publish(self):
        condition = re.search(r'^    if: >-\n((?:      .*\n)+)', job('build-and-push'), re.M)[1]
        # Evaluate this small, fixed grammar as a truth table, not a hand-copied policy.
        expression = ' '.join(condition.split()).replace('&&', ' and ').replace('||', ' or ')
        for repo, event, ref in itertools.product(
                ['myachmen/netology-diploma-app', 'untrusted/fork'],
                ['push', 'pull_request', 'pull_request_target', 'workflow_dispatch', 'workflow_run'],
                ['refs/heads/main', 'refs/heads/feature/diploma-ci-cd-prep-137',
                 'refs/heads/feature/diploma-ci-cd-fixes-139', 'refs/tags/v1.0.0']):
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
