"""Synthetic authenticated-API responses for offline tests, never live evidence."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import io
import json
import zipfile

from ci.build_manifest import build_manifest
from ci.github_gate import ENVIRONMENT, PREFIX, REPOSITORY, REPOSITORY_ID, ROOT, WORKFLOW
from fixtures import NOW, environment, evidence


def iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat().replace('+00:00', 'Z')


def archive(value, filename='cd-release.json'):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr(filename, json.dumps(value))
    return output.getvalue()


class APIStub:
    def __init__(self):
        self.calls = []
        env, proof = environment(), evidence()
        self.run_path = ROOT + '/actions/runs/123'
        self.manifest = build_manifest(dict(env, GITHUB_JOB='build-and-push'))
        self.raw = archive(self.manifest)
        self.artifact = {'id': 55, 'name': 'cd-release-123-1', 'expired': False,
                         'size_in_bytes': len(self.raw), 'digest': 'sha256:' + hashlib.sha256(self.raw).hexdigest(),
                         'created_at': iso(NOW - 20),
                         'workflow_run': {'id': 123, 'repository_id': REPOSITORY_ID,
                                          'head_repository_id': REPOSITORY_ID, 'head_sha': env['GITHUB_SHA']}}
        runtime = {k: deepcopy(proof[k]) for k in ('baseline', 'scope', 'observed_at', 'token_expires_at', 'credential_commitments')}
        runtime['token_audience_sha256'] = hashlib.sha256(env['CD_EXPECTED_AUDIENCE'].encode()).hexdigest()
        runtime['checks'] = {k: True for k in ('scoped_credentials_verified', 'ssh_identity_verified',
                                              'tls_verified', 'previous_digest_verified')}
        self.attestation = {'schema': 'APH-CD/1', 'repository_id': REPOSITORY_ID, 'ref': env['GITHUB_REF'],
                            'sha': env['GITHUB_SHA'], 'run_id': 123, 'attempt': 1, 'actor_id': 11,
                            'digest': env['IMAGE_DIGEST'], 'artifact_id': 55,
                            'artifact_digest': self.artifact['digest'], 'issued_at': NOW - 2,
                            'expires_at': NOW + 240, 'runtime': runtime}
        self.approval = {'state': 'approved', 'user': {'id': 22, 'login': 'synthetic-reviewer'},
                         'environments': [{'id': 33, 'name': ENVIRONMENT}]}
        self.data = {
            ROOT: {'id': REPOSITORY_ID, 'full_name': REPOSITORY, 'fork': False},
            self.run_path: {'id': 123, 'event': 'push', 'run_attempt': 1, 'head_sha': env['GITHUB_SHA'],
                            'head_branch': 'v1.0.2', 'repository': {'id': REPOSITORY_ID},
                            'head_repository': {'id': REPOSITORY_ID}, 'path': WORKFLOW,
                            'status': 'in_progress', 'created_at': iso(NOW - 100),
                            'actor': {'id': 11, 'login': 'synthetic-author'},
                            'triggering_actor': {'id': 11, 'login': 'synthetic-author'}},
            ROOT + '/git/ref/tags/v1.0.2': {'ref': env['GITHUB_REF'], 'object': {'type': 'commit', 'sha': env['GITHUB_SHA']}},
            ROOT + '/compare/' + env['GITHUB_SHA'] + '...main': {'status': 'ahead',
                                                               'merge_base_commit': {'sha': env['GITHUB_SHA']}},
            ROOT + '/branches/main/protection': {
                'enforce_admins': {'enabled': True}, 'allow_force_pushes': {'enabled': False},
                'allow_deletions': {'enabled': False}, 'required_status_checks': {'strict': True,
                  'checks': [{'context': 'test', 'app_id': 15368}]},
                'required_pull_request_reviews': {'required_approving_review_count': 1,
                  'dismiss_stale_reviews': True, 'require_last_push_approval': True,
                  'bypass_pull_request_allowances': {'users': [], 'teams': [], 'apps': []}}},
            ROOT + '/rulesets?includes_parents=true&per_page=100': [{'id': 1, 'target': 'tag', 'enforcement': 'active'}],
            ROOT + '/rulesets/1': {'target': 'tag', 'enforcement': 'active', 'bypass_actors': [],
              'conditions': {'ref_name': {'include': [env['GITHUB_REF']], 'exclude': []}},
              'rules': [{'type': 'update'}, {'type': 'deletion'}]},
            ROOT + '/environments/' + ENVIRONMENT: {'id': 33, 'name': ENVIRONMENT,
              'can_admins_bypass': False, 'deployment_branch_policy': {'protected_branches': False, 'custom_branch_policies': True},
              'protection_rules': [{'type': 'required_reviewers', 'prevent_self_review': True,
                                   'reviewers': [{'type': 'User', 'reviewer': {'id': 22}}]}]},
            ROOT + '/environments/' + ENVIRONMENT + '/deployment-branch-policies?per_page=100':
                {'total_count': 1, 'branch_policies': [{'id': 44, 'name': 'v1.0.2', 'type': 'tag'}]},
            self.run_path + '/approvals': [self.approval],
            self.run_path + '/attempts/1/jobs?per_page=100': {'total_count': 3, 'jobs': [
                {'name': 'test', 'status': 'completed', 'conclusion': 'success'},
                {'name': 'build-and-push', 'status': 'completed', 'conclusion': 'success',
                 'started_at': iso(NOW - 60), 'completed_at': iso(NOW - 10), 'steps': [
                   {'name': 'Record immutable release manifest', 'conclusion': 'success'},
                   {'name': 'Upload immutable release manifest', 'conclusion': 'success'}]},
                {'name': 'deploy', 'status': 'in_progress', 'started_at': iso(NOW - 10)}]},
            self.run_path + '/artifacts?per_page=100': {'total_count': 1, 'artifacts': [self.artifact]}}
        self.refresh_comment()

    def refresh_comment(self):
        self.approval['comment'] = PREFIX + json.dumps(self.attestation)

    def replace_archive(self, value, filename='cd-release.json'):
        self.raw = archive(value, filename)
        self.artifact['digest'] = 'sha256:' + hashlib.sha256(self.raw).hexdigest()
        self.artifact['size_in_bytes'] = len(self.raw)
        self.attestation['artifact_digest'] = self.artifact['digest']
        self.refresh_comment()

    def get(self, path):
        self.calls.append(path)
        result = self.data[path]
        if isinstance(result, Exception):
            raise result
        return deepcopy(result)

    def archive(self, artifact_id):
        self.calls.append(('archive', artifact_id))
        if artifact_id != 55:
            raise AssertionError('Unexpected artifact request')
        return self.raw
