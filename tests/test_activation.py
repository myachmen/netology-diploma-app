from copy import deepcopy
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from ci.activation import CHECKS, authorize_execution, validate_activation
from fixtures import NOW, SyntheticVerifier, environment, evidence

ROOT = Path(__file__).resolve().parents[1]


class ActivationContract(unittest.TestCase):
    def test_synthetic_contract_and_explicit_test_verifier(self):
        env, proof = environment(), evidence()
        self.assertEqual(validate_activation(env, proof, NOW), proof)
        verifier = SyntheticVerifier()
        self.assertEqual(authorize_execution(env, verifier, NOW), proof)
        self.assertEqual(verifier.calls, 1)

    def test_no_provider_means_blocked_even_with_true_flags(self):
        with self.assertRaisesRegex(ValueError, 'authenticated activation verifier'):
            authorize_execution(environment(), now=NOW)

    def test_preparation_unknown_profiles_flags_and_allowlist_fail_before_provider(self):
        for key, value in [('CD_PROFILE', 'PREPARATION'), ('CD_PROFILE', ''),
                           ('CD_ENABLED', ''), ('CD_ENABLED', 'false'),
                           ('CD_SSH_TUNNEL_APPROVED', ''), ('CD_EXPECTED_REF', ''),
                           ('CD_EXPECTED_REF', 'refs/tags/v9.0.0'), ('CD_EXPECTED_SHA', ''),
                           ('CD_EXPECTED_SHA', 'c' * 40), ('GITHUB_EVENT_NAME', 'pull_request'),
                           ('GITHUB_EVENT_NAME', 'pull_request_target'),
                           ('GITHUB_EVENT_NAME', 'workflow_dispatch'), ('GITHUB_EVENT_NAME', 'workflow_run'),
                           ('GITHUB_REPOSITORY', 'fork/app'), ('GITHUB_RUN_ATTEMPT', '2'),
                           ('SOURCE_RUN', '456'), ('SOURCE_SHA', 'c' * 40), ('IMAGE_DIGEST', 'latest')]:
            verifier = SyntheticVerifier()
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                authorize_execution(dict(environment(), **{key: value}), verifier, NOW)
            self.assertEqual(verifier.calls, 0)

    def test_all_protection_and_trust_observations_required(self):
        for key in CHECKS:
            for value in [False, None, 'true', 1]:
                proof = evidence()
                proof['checks'][key] = value
                with self.subTest(check=key, value=value), self.assertRaises(ValueError):
                    validate_activation(environment(), proof, NOW)

    def test_bindings_approval_time_scope_and_ttl(self):
        mutations = [('schema', True), ('checks', None), ('repository', 'fork/app'), ('ref', 'refs/tags/v2.0.0'), ('sha', 'c' * 40),
                     ('run_id', '456'), ('attempt', 2), ('attempt', True), ('digest', 'latest'),
                     ('environment', 'unprotected'), ('observed_at', NOW - 301),
                     ('observed_at', NOW + 1), ('approved_at', NOW - 10), ('approved_at', NOW + 1),
                     ('reviewer', 'synthetic-author'), ('reviewer', 'SYNTHETIC-AUTHOR'), ('reviewer', ''), ('token_audience', 'other'),
                     ('token_expires_at', NOW + 899), ('job_deadline', NOW + 299)]
        for key, value in mutations:
            proof = evidence()
            proof[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_activation(environment(), proof, NOW)
        for key in evidence():
            proof = evidence()
            del proof[key]
            with self.subTest(missing=key), self.assertRaises(ValueError):
                validate_activation(environment(), proof, NOW)
        for key in ['namespace', 'deployment', 'identity', 'resource']:
            proof = evidence()
            proof['scope'][key] = 'other'
            with self.subTest(scope=key), self.assertRaises(ValueError):
                validate_activation(environment(), proof, NOW)
        for key, value in [('verbs', ['*']), ('resource_names', []), ('verbs', ['get', 'patch', 'list', 'watch', 'update'])]:
            proof = evidence()
            proof['scope'][key] = value
            with self.subTest(scope=key), self.assertRaises(ValueError):
                validate_activation(environment(), proof, NOW)

    def test_shipped_script_never_calls_external_tools_in_either_profile(self):
        for profile in ('PREPARATION', 'ACTIVATION'):
            with self.subTest(profile=profile), tempfile.TemporaryDirectory() as tmp:
                marker = Path(tmp) / 'external-command'
                for name in ('ssh', 'kubectl', 'curl'):
                    tool = Path(tmp) / name
                    tool.write_text(f"#!/bin/sh\necho forbidden >> '{marker}'\nexit 99\n")
                    tool.chmod(0o700)
                env = dict(os.environ, **environment())
                env['CD_PROFILE'] = profile
                env['PATH'] = tmp + os.pathsep + os.environ['PATH']
                # Neither evidence JSON nor this flag is consumed as authorization.
                env['CD_GATE_VERIFIED'] = 'true'
                env['CD_GATE_EVIDENCE'] = '{}'
                run = subprocess.run(['bash', 'ci/deploy.sh'], cwd=ROOT, env=env,
                                     capture_output=True, text=True, timeout=10)
                self.assertNotEqual(run.returncode, 0)
                self.assertIn('CD_DISABLED' if profile == 'PREPARATION' else 'BLOCKED', run.stderr)
                self.assertFalse(marker.exists())
