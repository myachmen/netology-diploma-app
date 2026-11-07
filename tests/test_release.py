"""Offline release routing, metadata and fail-closed credential configuration."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from ci.release import IMAGE, build_metadata, validate_credentials
from fixtures import environment

ROOT = Path(__file__).resolve().parents[1]


class BuildMetadata(unittest.TestCase):
    def test_main_feature_and_release_publish_correct_tags(self):
        for version in ('1.0.0', '1.0.1', '1.0.2'):
            env = environment()
            env.update(APP_VERSION=version, GITHUB_REF='refs/tags/v' + version, SOURCE_TAG='v' + version)
            tag = build_metadata(env, version)
            self.assertEqual(tag['valid'], 'true')
            self.assertEqual(tag['tags'].splitlines(), [IMAGE + ':sha-' + 'a' * 40 + '-run-' + env['GITHUB_RUN_ID']])
            self.assertEqual(tag['sha'], env['GITHUB_SHA'])
            self.assertEqual(tag['run'], env['GITHUB_RUN_ID'])
            main = build_metadata(dict(env, GITHUB_REF_TYPE='branch', GITHUB_REF='refs/heads/main'), version)
            self.assertEqual(main['valid'], 'false')
            self.assertEqual(main['tags'].splitlines(), [IMAGE + ':sha-' + 'a' * 40 + '-run-' + env['GITHUB_RUN_ID']])
            with self.assertRaisesRegex(ValueError, 'test-only'):
                build_metadata(dict(env, GITHUB_REF_TYPE='branch', GITHUB_REF='refs/heads/normal-feature'), version)

    def test_untrusted_invalid_and_preparation_cannot_publish(self):
        for key, value in [('GITHUB_REPOSITORY','fork/app'), ('GITHUB_EVENT_NAME','pull_request'),
                           ('GITHUB_EVENT_NAME','workflow_dispatch'), ('GITHUB_SHA','invalid'),
                           ('GITHUB_RUN_ID',''), ('GITHUB_RUN_ATTEMPT','2'), ('GITHUB_REF','refs/tags/v9.0.0'),
                           ('GITHUB_REF','refs/tags/v01.0.2')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                build_metadata(dict(environment(), **{key:value}), '1.0.2')
        with self.assertRaisesRegex(ValueError, 'test-only'):
            build_metadata(dict(environment(), GITHUB_REF_TYPE='branch',
                                GITHUB_REF='refs/heads/feature/diploma-minimal-cd-142'), '1.0.2')
        for version in ('1.0', '01.0.0', '1.0.0\nINJECT=bad'):
            with self.subTest(version=version), self.assertRaises(ValueError):
                build_metadata(environment(), version)

    def test_cli_writes_source_version_and_image_tags(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'output'
            env = dict(os.environ, **environment())
            env.update(GITHUB_REF_TYPE='branch', GITHUB_REF='refs/heads/main')
            run = subprocess.run(['python3','-m','ci.release','--build-output',str(path)], cwd=ROOT,
                                 env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 0, run.stderr)
            output = path.read_text()
            version = (ROOT / 'ci/VERSION').read_text().strip()
            self.assertIn('version=' + version + '\n', output)
            self.assertIn('valid=false\n', output)
            self.assertIn('tags<<IMAGES\n' + IMAGE + ':sha-' + 'a' * 40, output)
            self.assertIn('sha=' + 'a' * 40 + '\n', output)
            self.assertNotIn('synthetic-unit', output)


class CredentialContract(unittest.TestCase):
    def test_shape_only_fake_configuration_is_accepted_offline(self):
        validate_credentials(environment())
        for key, value in [('SSH_USER','ubuntu'), ('SSH_USER','root'), ('SSH_HOST','-oProxyCommand=bad'),
                           ('API_TLS_NAME','name;command'), ('KUBE_CA_B64','not-base64'),
                           ('KUBE_TOKEN','token\nextra'), ('APP_URL','https://user:password@example.invalid/'),
                           ('APP_URL','https://example.invalid/?secret=value'), ('APP_URL','ftp://example.invalid/')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_credentials(dict(environment(), **{key:value}))

    def test_each_missing_credential_denies_before_external_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / 'external-called'
            for name in ('ssh','kubectl','curl'):
                p = Path(tmp) / name
                p.write_text('#!/bin/sh\necho forbidden >> "' + str(marker) + '"\nexit 99\n')
                p.chmod(0o700)
            for missing in ('SSH_PRIVATE_KEY','SSH_KNOWN_HOSTS','KUBE_CA_B64','KUBE_TOKEN',
                            'SSH_HOST','SSH_USER','API_TLS_NAME','APP_URL'):
                env = dict(os.environ, **environment())
                env['PATH'] = tmp + os.pathsep + os.environ['PATH']
                env[missing] = ''  # Never fall back to a credential in the calling environment.
                run = subprocess.run(['bash','ci/deploy.sh'], cwd=ROOT, env=env,
                                     capture_output=True, text=True, timeout=10)
                with self.subTest(missing=missing):
                    self.assertNotEqual(run.returncode, 0)
                    self.assertIn(missing, run.stderr)
                    self.assertNotIn('synthetic-unit', run.stdout + run.stderr)
                    self.assertFalse(marker.exists())
