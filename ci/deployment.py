"""Pure guarded Deployment patch/postcheck; CLI uses protected temporary JSON only."""
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re

from ci.activation import require, validate_activation

REPOSITORY = 'cr.yandex/crpb1oihnpa2uai8m3mp/netology-diploma-app'
DIGEST = r'sha256:[0-9a-f]{64}'


def spec_hash(spec):
    return hashlib.sha256(json.dumps(spec, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def target(document):
    require(document.get('apiVersion') == 'apps/v1' and document.get('kind') == 'Deployment', 'Wrong kind')
    metadata = document.get('metadata', {})
    require(metadata.get('namespace') == 'default' and metadata.get('name') == 'diploma-app', 'Wrong target')
    require(isinstance(metadata.get('uid'), str) and bool(metadata['uid']) and
            isinstance(metadata.get('resourceVersion'), str) and bool(metadata['resourceVersion']), 'Missing UID/RV')
    generation = metadata.get('generation')
    require(type(generation) is int and generation > 0, 'Invalid generation')
    require(document.get('spec', {}).get('replicas') == 2, 'Expected two replicas')
    containers = document['spec']['template']['spec']['containers']
    require(len(containers) == 1 and containers[0]['name'] == 'diploma-app', 'Unexpected container layout')
    return metadata, containers[0]


def ready(document, generation):
    status = document.get('status', {})
    require(status.get('observedGeneration') == generation, 'Controller has not observed exact generation')
    require(all(status.get(key, 0) == 2 for key in
                ('replicas', 'updatedReplicas', 'readyReplicas', 'availableReplicas')), 'Replicas not ready')


def build_patch(document, proof):
    metadata, container = target(document)
    baseline = proof.get('baseline', {})
    require(metadata['uid'] == baseline.get('uid'), 'UID drift')
    require(metadata['resourceVersion'] == baseline.get('resource_version'), 'ResourceVersion drift')
    require(metadata['generation'] == baseline.get('generation'), 'Generation drift')
    require(spec_hash(document['spec']) == baseline.get('spec_sha256'), 'Unapproved spec')
    ready(document, metadata['generation'])
    previous = baseline.get('previous_image', '')
    previous_digest = baseline.get('previous_digest', '')
    require(bool(re.fullmatch(DIGEST, previous_digest)), 'Unverified previous digest')
    require(proof.get('checks', {}).get('previous_digest_verified') is True, 'Missing previous image observation')
    require(container['image'] == previous, 'Previous image drift')
    require(bool(re.fullmatch(re.escape(REPOSITORY) + r'(?::[0-9]+\.[0-9]+\.[0-9]+|@' + DIGEST + ')', previous)),
            'Unexpected previous image repository')
    if '@' in previous:
        require(previous.split('@')[1] == previous_digest, 'Previous digest mismatch')
    digest = proof.get('digest', '')
    require(bool(re.fullmatch(DIGEST, digest)) and digest != previous_digest, 'Invalid/unchanged release digest')
    image = REPOSITORY + '@' + digest
    patch = [{'op': 'test', 'path': path, 'value': value} for path, value in [
        ('/metadata/uid', metadata['uid']), ('/metadata/resourceVersion', metadata['resourceVersion']),
        ('/metadata/generation', metadata['generation']), ('/spec/replicas', 2),
        ('/spec/template/spec/containers/0/name', 'diploma-app'),
        ('/spec/template/spec/containers/0/image', previous)]]
    patch.append({'op': 'replace', 'path': '/spec/template/spec/containers/0/image', 'value': image})
    expected_spec = deepcopy(document['spec'])
    expected_spec['template']['spec']['containers'][0]['image'] = image
    expectation = {'uid': metadata['uid'], 'generation': metadata['generation'] + 1,
                   'spec': expected_spec, 'previous_resource_version': metadata['resourceVersion']}
    return patch, expectation


def verify(document, expectation, final=False):
    metadata, _ = target(document)
    require(metadata['uid'] == expectation['uid'], 'Recreated Deployment')
    require(metadata['generation'] == expectation['generation'], 'Unexpected rollout generation')
    require(metadata['resourceVersion'] != expectation['previous_resource_version'], 'Mutation not observed')
    require(document['spec'] == expectation['spec'], 'Unexpected spec/image mutation')
    if final:
        ready(document, expectation['generation'])


def write_json(path, value):
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'w') as output:
        json.dump(value, output)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['patch', 'reply', 'final'])
    parser.add_argument('document', type=Path)
    parser.add_argument('authorization', type=Path)
    parser.add_argument('expectation', type=Path)
    parser.add_argument('--patch-output', type=Path)
    args = parser.parse_args()
    proof = json.loads(args.authorization.read_text())
    # Refresh TTL/time/approval checks just BEFORE mutation, not after rollout.
    if args.command == 'patch':
        from ci.release import validate
        validate(os.environ)
        validate_activation(os.environ, proof)
        require(args.patch_output is not None, 'Missing patch output')
        patch, expected = build_patch(json.loads(args.document.read_text()), proof)
        write_json(args.patch_output, patch)
        write_json(args.expectation, expected)
    else:
        verify(json.loads(args.document.read_text()), json.loads(args.expectation.read_text()),
               final=args.command == 'final')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError) as exc:
        raise SystemExit('Deployment guard FAIL: ' + str(exc)) from None
