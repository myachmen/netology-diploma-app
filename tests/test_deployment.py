from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

from ci.deployment import REPOSITORY, build_patch, verify
from fixtures import deployment, environment, evidence


def apply_stub(original, patch):
    """Offline JSON patch interpreter, no kubectl/API or partial commit on failure."""
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
    def test_one_image_write_then_exact_generation_postcheck(self):
        original, proof = deployment(), evidence()
        before = deepcopy(original)
        patch, expected = build_patch(original, proof)
        self.assertEqual(original, before)
        self.assertEqual([p['op'] for p in patch], ['test'] * 6 + ['replace'])
        self.assertEqual(patch[-1]['path'], '/spec/template/spec/containers/0/image')
        self.assertEqual(patch[-1]['value'], REPOSITORY + '@' + environment()['IMAGE_DIGEST'])
        reply = apply_stub(original, patch)
        verify(reply, expected)
        final = deepcopy(reply)
        final['metadata']['resourceVersion'] = '12'  # Status updates may advance RV.
        final['status']['observedGeneration'] = expected['generation']
        verify(final, expected, final=True)

    def test_guard_rejects_drift_unready_baseline_and_unverified_previous_digest(self):
        for field, value in [('uid', 'recreated'), ('resourceVersion', '999'), ('generation', 8)]:
            doc = deployment()
            doc['metadata'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                build_patch(doc, evidence())
        for key, value in [('previous_image', REPOSITORY + ':9.9.9'),
                           ('previous_digest', 'latest'), ('spec_sha256', 'unapproved')]:
            proof = evidence()
            proof['baseline'][key] = value
            with self.subTest(baseline=key), self.assertRaises(ValueError):
                build_patch(deployment(), proof)
        proof = evidence()
        proof['checks']['previous_digest_verified'] = False
        with self.assertRaises(ValueError):
            build_patch(deployment(), proof)
        doc = deployment()
        doc['status']['readyReplicas'] = 1
        with self.assertRaises(ValueError):
            build_patch(doc, evidence())
        doc = deployment()
        doc['spec']['replicas'] = 3
        with self.assertRaises(ValueError):
            build_patch(doc, evidence())

    def test_conflicting_patch_is_not_retried_and_changes_nothing(self):
        patch, _ = build_patch(deployment(), evidence())
        concurrent = deployment()
        concurrent['metadata']['resourceVersion'] = '11'
        before = deepcopy(concurrent)
        calls = 0
        with self.assertRaises(ValueError):
            calls += 1
            apply_stub(concurrent, patch)
        self.assertEqual(calls, 1)
        self.assertEqual(concurrent, before)

    def test_postcheck_rejects_recreated_or_newer_or_modified_rollout(self):
        patch, expected = build_patch(deployment(), evidence())
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

    def test_cli_generates_only_local_patch_and_rechecks_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proof = evidence(int(time.time()))
            (root / 'baseline.json').write_text(json.dumps(deployment()))
            (root / 'proof.json').write_text(json.dumps(proof))
            command = ['python3', '-m', 'ci.deployment', 'patch', str(root / 'baseline.json'),
                       str(root / 'proof.json'), str(root / 'expected.json'), '--patch-output', str(root / 'patch.json')]
            env = dict(os.environ, **environment(), PYTHONDONTWRITEBYTECODE='1')
            run = subprocess.run(command, env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(len(json.loads((root / 'patch.json').read_text())), 7)
            self.assertEqual((root / 'patch.json').stat().st_mode & 0o777, 0o600)
            self.assertEqual((root / 'expected.json').stat().st_mode & 0o777, 0o600)
            proof['job_deadline'] = time.time() + 1
            (root / 'proof.json').write_text(json.dumps(proof))
            run = subprocess.run(command, env=env, capture_output=True, text=True, timeout=10)
            self.assertNotEqual(run.returncode, 0)
            self.assertIn('time budget', run.stderr)
