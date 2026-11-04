from copy import deepcopy
import io
import json
import unittest
from urllib.error import HTTPError, URLError

from ci.activation import authorize_execution
from ci.build_manifest import build_manifest
from ci.github_gate import ENVIRONMENT, GitHubAPI, GitHubVerifier, PREFIX, ROOT, strict_json
from fixtures import NOW, environment
from github_fixtures import APIStub, iso


class TrustedGitHubGate(unittest.TestCase):
    def admit(self, api=None):
        return authorize_execution(environment(), GitHubVerifier(api or APIStub(), clock=lambda: NOW), NOW)

    def test_real_verifier_pipeline_with_offline_authenticated_api_responses(self):
        api = APIStub()
        proof = self.admit(api)
        self.assertEqual(proof['github_source']['reviewer_id'], 22)
        self.assertEqual(proof['github_source']['artifact_id'], 55)
        self.assertEqual(proof['digest'], environment()['IMAGE_DIGEST'])
        self.assertEqual(proof['job_deadline'], NOW + 590)
        self.assertIn(api.run_path + '/approvals', api.calls)
        self.assertIn(('archive', 55), api.calls)
        self.assertNotIn('token_audience', api.attestation['runtime'])

    def test_production_factory_is_wired_and_not_a_missing_verifier_stub(self):
        from unittest.mock import patch
        api = APIStub()
        # Substitute transport/clock in-process; no CLI/env test-provider bypass.
        with patch('ci.github_gate.GitHubAPI', return_value=api) as factory:
            proof = authorize_execution(dict(environment(), CD_GITHUB_READ_TOKEN='synthetic-not-a-credential'), now=NOW)
        factory.assert_called_once_with('synthetic-not-a-credential')
        self.assertEqual(proof['github_source']['reviewer_id'], 22)

    def test_api_run_ref_actor_and_source_mismatches(self):
        cases = [('event', 'pull_request'), ('event', 'workflow_dispatch'), ('run_attempt', 2),
                 ('run_attempt', True), ('head_sha', 'c' * 40), ('head_branch', 'main'),
                 ('path', '.github/workflows/untrusted.yml'), ('status', 'completed'),
                 ('created_at', iso(NOW - 2701)), ('head_repository', {'id': 999}),
                 ('triggering_actor', {'id': 12, 'login': 'other'})]
        for key, value in cases:
            api = APIStub()
            api.data[api.run_path][key] = value
            with self.subTest(field=key), self.assertRaises(ValueError):
                self.admit(api)
        for key, value in [('ref', 'refs/tags/v9.9.9'), ('object', {'type': 'commit', 'sha': 'c' * 40})]:
            api = APIStub()
            api.data[ROOT + '/git/ref/tags/v1.0.2'][key] = value
            with self.subTest(tag=key), self.assertRaises(ValueError):
                self.admit(api)

    def test_annotated_tag_is_peeled_to_the_event_commit(self):
        api = APIStub()
        api.data[ROOT + '/git/ref/tags/v1.0.2']['object'] = {'type': 'tag', 'sha': 'd' * 40}
        api.data[ROOT + '/git/tags/' + 'd' * 40] = {'object': {'type': 'commit', 'sha': environment()['GITHUB_SHA']}}
        self.admit(api)

    def test_ruleset_summary_does_not_need_detail_only_fields(self):
        api = APIStub()
        api.data[ROOT + '/rulesets?includes_parents=true&per_page=100'] = [{'id': 1}]
        self.admit(api)

    def test_branch_tag_protection_and_hidden_bypass_are_not_assumed(self):
        mutations = [
            ('enforce_admins', {'enabled': False}), ('allow_force_pushes', {'enabled': True}),
            ('allow_deletions', {'enabled': True}), ('required_status_checks', {'strict': False}),
            ('required_pull_request_reviews', {'required_approving_review_count': 0})]
        for key, value in mutations:
            api = APIStub()
            api.data[ROOT + '/branches/main/protection'][key] = value
            with self.subTest(branch=key), self.assertRaises(ValueError):
                self.admit(api)
        for key, value in [('bypass_actors', [{'actor_id': 1}]), ('enforcement', 'evaluate'),
                           ('rules', [{'type': 'deletion'}]), ('conditions', {'ref_name': {'include': ['~ALL'], 'exclude': []}})]:
            api = APIStub()
            api.data[ROOT + '/rulesets/1'][key] = value
            with self.subTest(tag=key), self.assertRaises(ValueError):
                self.admit(api)
        api = APIStub()
        del api.data[ROOT + '/rulesets/1']['bypass_actors']
        with self.assertRaisesRegex(ValueError, 'hides.*bypass_actors'):
            self.admit(api)

    def test_missing_reviewer_environment_or_exact_policy_denies(self):
        for key, value in [('can_admins_bypass', True), ('can_admins_bypass', None),
                           ('protection_rules', []), ('deployment_branch_policy', None)]:
            api = APIStub()
            api.data[ROOT + '/environments/' + ENVIRONMENT][key] = value
            with self.subTest(environment=key), self.assertRaises(ValueError):
                self.admit(api)
        api = APIStub()
        api.data[ROOT + '/environments/' + ENVIRONMENT]['protection_rules'][0]['reviewers'] = [
            {'type': 'Team', 'reviewer': {'id': 22}}]
        with self.assertRaisesRegex(ValueError, 'Team membership unsupported'):
            self.admit(api)
        for key, value in [('name', 'v*'), ('type', 'branch')]:
            api = APIStub()
            api.data[ROOT + '/environments/' + ENVIRONMENT + '/deployment-branch-policies?per_page=100']['branch_policies'][0][key] = value
            with self.subTest(policy=key), self.assertRaises(ValueError):
                self.admit(api)

    def test_fake_rejected_self_or_ambiguous_approval(self):
        for change in ('missing', 'rejected', 'unknown-user', 'duplicate', 'raw-json', 'duplicate-json-field'):
            api = APIStub()
            if change == 'missing': api.data[api.run_path + '/approvals'] = []
            if change == 'rejected': api.approval['state'] = 'rejected'
            if change == 'unknown-user': api.approval['user']['id'] = 999
            if change == 'duplicate': api.data[api.run_path + '/approvals'].append(deepcopy(api.approval))
            if change == 'raw-json': api.approval['comment'] = json.dumps(api.attestation)
            if change == 'duplicate-json-field': api.approval['comment'] = PREFIX + '{"schema":1,"schema":2}'
            with self.subTest(approval=change), self.assertRaises(ValueError):
                self.admit(api)
        api = APIStub()
        api.approval['user'] = {'id': 11, 'login': 'synthetic-author'}
        api.data[ROOT + '/environments/' + ENVIRONMENT]['protection_rules'][0]['reviewers'] = [
            {'type': 'User', 'reviewer': {'id': 11}}]
        with self.assertRaisesRegex(ValueError, 'self reviewer'):
            self.admit(api)

    def test_local_observations_or_job_output_cannot_replace_github_approval(self):
        api = APIStub()
        api.data[api.run_path + '/approvals'] = []
        env = dict(environment(), CD_GATE_VERIFIED='true', CD_GATE_EVIDENCE=json.dumps(api.attestation))
        with self.assertRaises(ValueError):
            authorize_execution(env, GitHubVerifier(api, clock=lambda: NOW), NOW)

    def test_runtime_secret_or_trust_substitution_breaks_authenticated_commitment(self):
        for name in ('KUBE_TOKEN', 'KUBE_CA_B64', 'SSH_KNOWN_HOSTS', 'SSH_HOST', 'API_TLS_NAME', 'APP_URL'):
            api = APIStub()
            env = dict(environment(), **{name: 'different-synthetic-value'})
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'commitment mismatch'):
                authorize_execution(env, GitHubVerifier(api, clock=lambda: NOW), NOW)
        api = APIStub()
        env = dict(environment(), IMAGE_DIGEST='sha256:' + 'd' * 64)
        with self.assertRaisesRegex(ValueError, 'digest mismatch'):
            authorize_execution(env, GitHubVerifier(api, clock=lambda: NOW), NOW)

    def test_expired_or_mismatched_reviewer_attestation(self):
        for key, value in [('run_id', 124), ('sha', 'c' * 40), ('ref', 'refs/tags/v2.0.0'),
                           ('actor_id', 12), ('digest', 'sha256:' + 'c' * 64), ('artifact_id', 99),
                           ('artifact_digest', 'sha256:' + 'c' * 64), ('expires_at', NOW - 1),
                           ('issued_at', NOW + 1), ('expires_at', NOW + 301)]:
            api = APIStub()
            api.attestation[key] = value
            api.refresh_comment()
            with self.subTest(attestation=key), self.assertRaises(ValueError):
                self.admit(api)
        for key, value in [('token_audience_sha256', '0' * 64), ('token_expires_at', NOW + 899)]:
            api = APIStub()
            api.attestation['runtime'][key] = value
            api.refresh_comment()
            with self.subTest(runtime=key), self.assertRaises(ValueError):
                self.admit(api)
        api = APIStub()
        api.attestation['runtime']['checks']['tls_verified'] = False
        api.refresh_comment()
        with self.assertRaises(ValueError): self.admit(api)

    def test_artifact_provenance_hash_zip_and_build_outcome(self):
        for key, value in [('expired', True), ('created_at', iso(NOW + 1)),
                           ('workflow_run', {'id': 999}), ('name', 'other-run'), ('digest', None)]:
            api = APIStub()
            api.artifact[key] = value
            with self.subTest(artifact=key), self.assertRaises(ValueError): self.admit(api)
        api = APIStub()
        api.raw += b'tampered'
        with self.assertRaisesRegex(ValueError, 'Artifact digest mismatch'): self.admit(api)
        for filename in ('../cd-release.json', 'untrusted.json'):
            api = APIStub()
            api.replace_archive(api.manifest, filename)
            with self.subTest(filename=filename), self.assertRaises(ValueError): self.admit(api)
        for key, value in [('sha', 'c' * 40), ('run_id', 999), ('digest', 'latest'), ('attempt', True)]:
            api = APIStub()
            api.manifest[key] = value
            api.replace_archive(api.manifest)
            with self.subTest(manifest=key), self.assertRaises(ValueError): self.admit(api)
        api = APIStub()
        api.data[api.run_path + '/attempts/1/jobs?per_page=100']['jobs'][1]['conclusion'] = 'failure'
        with self.assertRaises(ValueError): self.admit(api)

    def test_api_unavailable_incomplete_collection_budget_or_malformed_denies(self):
        api = APIStub()
        api.data[ROOT + '/branches/main/protection'] = ValueError('BLOCKED: GitHub HTTP 403')
        with self.assertRaisesRegex(ValueError, '403'): self.admit(api)
        api = APIStub()
        api.data[api.run_path + '/attempts/1/jobs?per_page=100']['total_count'] = 101
        with self.assertRaisesRegex(ValueError, 'incomplete'): self.admit(api)
        api = APIStub()
        api.data[api.run_path + '/attempts/1/jobs?per_page=100']['jobs'][2]['started_at'] = iso(NOW - 400)
        with self.assertRaisesRegex(ValueError, 'budget'): self.admit(api)
        api = APIStub()
        api.data[ROOT] = None
        with self.assertRaisesRegex(ValueError, 'malformed'): self.admit(api)

    def test_manifest_producer_rejects_untrusted_jobs_events_and_reruns(self):
        valid = dict(environment(), GITHUB_JOB='build-and-push')
        self.assertEqual(build_manifest(valid)['digest'], valid['IMAGE_DIGEST'])
        for key, value in [('GITHUB_JOB', 'test'), ('GITHUB_RUN_ATTEMPT', '2'),
                           ('GITHUB_EVENT_NAME', 'pull_request'), ('IMAGE_DIGEST', 'latest')]:
            with self.subTest(key=key), self.assertRaises(ValueError): build_manifest(dict(valid, **{key: value}))


class Response:
    def __init__(self, body, status=200): self.body, self.status = body, status
    def __enter__(self): return self
    def __exit__(self, *args): return None
    def read(self, size): return self.body[:size]


class GitHubTransport(unittest.TestCase):
    def test_fixed_origin_get_and_bearer_and_no_sensitive_endpoints(self):
        class Opener:
            def open(inner, req, timeout):
                self.assertEqual(req.full_url, 'https://api.github.com' + ROOT)
                self.assertEqual(req.get_method(), 'GET')
                self.assertEqual(req.get_header('Authorization'), 'Bearer synthetic-test-token')
                self.assertEqual(timeout, 15)
                return Response(b'{"id":1}')
        api = GitHubAPI('synthetic-test-token', opener=Opener())
        self.assertEqual(api.get(ROOT), {'id': 1})
        for path in ('https://evil.test', ROOT + '/secrets', ROOT + '/../secrets', ROOT + '/variables'):
            with self.subTest(path=path), self.assertRaises(ValueError): api.get(path)
        for token in (None, '', 'bad\nheader', 'bad\x00header', 'token with spaces'):
            with self.subTest(token=token), self.assertRaises(ValueError): GitHubAPI(token, opener=Opener())

    def test_artifact_redirect_never_receives_api_authorization(self):
        calls = []
        class Opener:
            def open(inner, req, timeout):
                calls.append(req)
                if len(calls) == 1:
                    raise HTTPError(req.full_url, 302, 'redirect', {'Location': 'https://fixture.blob.core.windows.net/artifact?sig=synthetic'}, None)
                self.assertIsNone(req.get_header('Authorization'))
                return Response(b'offline-archive')
        self.assertEqual(GitHubAPI('synthetic-token', opener=Opener()).archive(55), b'offline-archive')
        self.assertEqual(len(calls), 2)

    def test_unapproved_redirect_is_rejected_without_second_request(self):
        for location in ('http://fixture.blob.core.windows.net/x', 'https://evil.test/x',
                         'https://user@fixture.blob.core.windows.net/x'):
            calls = []
            class Opener:
                def open(inner, req, timeout):
                    calls.append(req)
                    raise HTTPError(req.full_url, 302, 'redirect', {'Location': location}, None)
            with self.subTest(location=location), self.assertRaises(ValueError):
                GitHubAPI('synthetic-token', opener=Opener()).archive(55)
            self.assertEqual(len(calls), 1)

    def test_api_errors_are_sanitized_and_never_retried(self):
        for error in (HTTPError('https://api.github.com', 403, 'private-body', {}, io.BytesIO(b'private-body')),
                      URLError('private-transport-details'), TimeoutError('private-details')):
            calls = []
            class Opener:
                def open(inner, req, timeout):
                    calls.append(req)
                    raise error
            with self.subTest(error=type(error).__name__), self.assertRaises(ValueError) as result:
                GitHubAPI('synthetic-token', opener=Opener()).get(ROOT)
            self.assertIn('BLOCKED', str(result.exception))
            self.assertNotIn('private', str(result.exception))
            self.assertEqual(len(calls), 1)

    def test_duplicate_or_nonfinite_json_is_never_accepted(self):
        for raw in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":1e10000}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError): strict_json(raw)
