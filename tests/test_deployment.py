from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from ci.deployment import REPOSITORY, build_patch, verify
from fixtures import deployment, environment


def apply_stub(original, patch):
    """Offline atomic JSON patch interpreter, not a Kubernetes API."""
    candidate = deepcopy(original)
    for operation in patch:
        keys = operation['path'].strip('/').split('/')
        obj = candidate
        for key in keys[:-1]:
            obj = obj[int(key)] if isinstance(obj, list) else obj[key]
        key = int(keys[-1]) if isinstance(obj, list) else keys[-1]
        if operation['op'] == 'test':
            if obj[key] != operation['value']:
                raise ValueError('API precondition conflict')
        elif operation['op'] == 'replace':
            obj[key] = operation['value']
        else:
            raise AssertionError('Unexpected operation')
    candidate['metadata']['generation'] += 1
    candidate['metadata']['resourceVersion'] = '11'
    return candidate


class DeploymentContract(unittest.TestCase):
    def test_one_digest_write_and_exact_final_spec(self):
        original = deployment()
        before = deepcopy(original)
        patch, expected = build_patch(original, environment()['IMAGE_DIGEST'])
        self.assertEqual(original, before)
        self.assertEqual([p['op'] for p in patch], ['test'] * 6 + ['replace'])
        self.assertEqual(patch[-1]['path'], '/spec/template/spec/containers/0/image')
        self.assertEqual(patch[-1]['value'], REPOSITORY + '@' + environment()['IMAGE_DIGEST'])
        reply = apply_stub(original, patch)
        verify(reply, expected)
        final = deepcopy(reply)
        final['metadata']['resourceVersion'] = '12'
        final['status']['observedGeneration'] = expected['generation']
        verify(final, expected, final=True)

    def test_reject_unready_or_wrong_layout_repository_and_digest(self):
        for change in ('namespace', 'replicas', 'ready', 'name', 'image', 'layout'):
            doc = deployment()
            if change == 'namespace': doc['metadata']['namespace'] = 'other'
            if change == 'replicas': doc['spec']['replicas'] = 3
            if change == 'ready': doc['status']['readyReplicas'] = 1
            if change == 'name': doc['metadata']['name'] = 'other'
            if change == 'image': doc['spec']['template']['spec']['containers'][0]['image'] = 'untrusted/image:1.0.0'
            if change == 'layout': doc['spec']['template']['spec']['containers'].append({'name':'other'})
            with self.subTest(change=change), self.assertRaises(ValueError):
                build_patch(doc, environment()['IMAGE_DIGEST'])
        for digest in ('latest', 'sha256:bad', 'sha256:' + 'b' * 64 + ';sh'):
            with self.subTest(digest=digest), self.assertRaises(ValueError):
                build_patch(deployment(), digest)
        doc = deployment()
        doc['spec']['template']['spec']['containers'][0]['image'] = REPOSITORY + '@' + environment()['IMAGE_DIGEST']
        with self.assertRaises(ValueError):
            build_patch(doc, environment()['IMAGE_DIGEST'])

    def test_atomic_drift_conflict_no_retry_or_partial_write(self):
        patch, _ = build_patch(deployment(), environment()['IMAGE_DIGEST'])
        for field, value in [('uid', 'other'), ('resourceVersion', '11'), ('generation', 9)]:
            doc = deployment()
            doc['metadata'][field] = value
            before = deepcopy(doc)
            calls = 0
            with self.subTest(field=field), self.assertRaises(ValueError):
                calls += 1
                apply_stub(doc, patch)
            self.assertEqual(calls, 1)
            self.assertEqual(doc, before)

    def test_postcheck_rejects_recreate_new_generation_and_bad_rollout(self):
        patch, expected = build_patch(deployment(), environment()['IMAGE_DIGEST'])
        good = apply_stub(deployment(), patch)
        good['status']['observedGeneration'] = expected['generation']
        for field, value in [('uid', 'other'), ('generation', 9), ('resourceVersion', '10')]:
            doc = deepcopy(good)
            doc['metadata'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                verify(doc, expected, final=True)
        for key in ('replicas', 'readyReplicas', 'availableReplicas', 'updatedReplicas', 'observedGeneration'):
            doc = deepcopy(good)
            doc['status'][key] = 0
            with self.subTest(status=key), self.assertRaises(ValueError):
                verify(doc, expected, final=True)
        doc = deepcopy(good)
        doc['spec']['template']['spec']['containers'][0]['image'] = REPOSITORY + ':latest'
        with self.assertRaises(ValueError):
            verify(doc, expected, final=True)

    def test_cli_generates_private_local_patch_and_rejects_digest_substitution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'baseline.json').write_text(json.dumps(deployment()))
            command = ['python3', '-m', 'ci.deployment', 'patch', str(root / 'baseline.json'),
                       str(root / 'expected.json'), '--digest', environment()['IMAGE_DIGEST'],
                       '--patch-output', str(root / 'patch.json')]
            env = dict(os.environ, **environment(), PYTHONDONTWRITEBYTECODE='1')
            run = subprocess.run(command, env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(len(json.loads((root / 'patch.json').read_text())), 7)
            for name in ('patch.json', 'expected.json'):
                self.assertEqual((root / name).stat().st_mode & 0o777, 0o600)
            env['IMAGE_DIGEST'] = 'sha256:' + 'c' * 64
            run = subprocess.run(command, env=env, capture_output=True, text=True, timeout=10)
            self.assertNotEqual(run.returncode, 0)
            self.assertIn('Digest/build mismatch', run.stderr)
