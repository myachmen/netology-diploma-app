"""Synthetic offline observations; NOT approval for any real ref or credentials."""
from copy import deepcopy

from ci.activation import CHECKS
from ci.deployment import REPOSITORY, spec_hash

NOW = 1800000000


def environment():
    return dict(GITHUB_REPOSITORY='myachmen/netology-diploma-app', GITHUB_EVENT_NAME='push',
                GITHUB_REF_TYPE='tag', GITHUB_REF='refs/tags/v1.0.2', APP_VERSION='1.0.2',
                GITHUB_SHA='a' * 40, SOURCE_SHA='a' * 40, SOURCE_TAG='v1.0.2',
                GITHUB_RUN_ID='123', SOURCE_RUN='123', GITHUB_RUN_ATTEMPT='1',
                BUILD_RESULT='success', IMAGE_DIGEST='sha256:' + 'b' * 64,
                CD_PROFILE='ACTIVATION', CD_ENABLED='true', CD_SSH_TUNNEL_APPROVED='true',
                CD_EXPECTED_REF='refs/tags/v1.0.2', CD_EXPECTED_SHA='a' * 40,
                CD_EXPECTED_AUDIENCE='synthetic-api-audience')


def deployment():
    return {'apiVersion': 'apps/v1', 'kind': 'Deployment',
            'metadata': {'name': 'diploma-app', 'namespace': 'default', 'uid': 'synthetic-uid',
                         'resourceVersion': '10', 'generation': 7},
            'spec': {'replicas': 2, 'template': {'spec': {'containers': [
                {'name': 'diploma-app', 'image': REPOSITORY + ':1.0.0'}]}}},
            'status': {'observedGeneration': 7, 'replicas': 2, 'updatedReplicas': 2,
                       'readyReplicas': 2, 'availableReplicas': 2}}


def evidence(now=NOW):
    env = environment()
    document = deployment()
    return {'schema': 1, 'repository': env['GITHUB_REPOSITORY'], 'ref': env['GITHUB_REF'],
            'sha': env['GITHUB_SHA'], 'run_id': env['GITHUB_RUN_ID'], 'attempt': 1,
            'digest': env['IMAGE_DIGEST'], 'environment': 'diploma-production',
            'observed_at': now - 5, 'approved_at': now - 2,
            'reviewer': 'synthetic-reviewer', 'trigger_actor': 'synthetic-author',
            'checks': {key: True for key in CHECKS},
            'scope': {'namespace': 'default', 'deployment': 'diploma-app',
                      'identity': 'system:serviceaccount:default:github-actions-deployer',
                      'resource': 'deployments.apps', 'resource_names': ['diploma-app'],
                      'verbs': ['get', 'patch', 'list', 'watch']},
            'token_expires_at': now + 1200, 'job_deadline': now + 600,
            'token_audience': env['CD_EXPECTED_AUDIENCE'],
            'baseline': {'uid': document['metadata']['uid'], 'resource_version': '10',
                         'generation': 7, 'spec_sha256': spec_hash(document['spec']),
                         'previous_image': REPOSITORY + ':1.0.0',
                         'previous_digest': 'sha256:' + 'c' * 64}}


class SyntheticVerifier:
    def __init__(self, observations=None):
        self.observations = observations or evidence()
        self.calls = 0

    def observe(self, env):
        self.calls += 1
        return deepcopy(self.observations)
