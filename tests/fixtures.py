"""Synthetic offline inputs, never real credentials or release authorizations."""
from ci.deployment import REPOSITORY


def environment():
    return dict(GITHUB_REPOSITORY='myachmen/netology-diploma-app', GITHUB_EVENT_NAME='push',
                GITHUB_REF_TYPE='tag', GITHUB_REF='refs/tags/v1.0.2', APP_VERSION='1.0.2',
                GITHUB_SHA='a' * 40, SOURCE_SHA='a' * 40, SOURCE_TAG='v1.0.2',
                GITHUB_RUN_ID='123', SOURCE_RUN='123', GITHUB_RUN_ATTEMPT='1',
                BUILD_RESULT='success', IMAGE_DIGEST='sha256:' + 'b' * 64,
                KUBE_TOKEN='synthetic-unit-token-not-a-credential', KUBE_CA_B64='U1lOVEhFVElDLUNB',
                SSH_PRIVATE_KEY='synthetic-unit-key-not-a-credential',
                SSH_KNOWN_HOSTS='synthetic-unit-host-key', SSH_HOST='synthetic-ssh.invalid',
                SSH_USER='cd-tunnel', API_TLS_NAME='synthetic-api.invalid', APP_URL='https://synthetic-app.invalid/')


def deployment():
    return {'apiVersion': 'apps/v1', 'kind': 'Deployment',
            'metadata': {'name': 'diploma-app', 'namespace': 'default', 'uid': 'synthetic-uid',
                         'resourceVersion': '10', 'generation': 7},
            'spec': {'replicas': 2, 'template': {'spec': {'containers': [
                {'name': 'diploma-app', 'image': REPOSITORY + ':1.0.0'}]}}},
            'status': {'observedGeneration': 7, 'replicas': 2, 'updatedReplicas': 2,
                       'readyReplicas': 2, 'availableReplicas': 2}}
