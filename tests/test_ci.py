import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from ci.release import validate
from ci.smoke import check_context

ROOT = Path(__file__).resolve().parents[1]


class ApplicationContract(unittest.TestCase):
    def test_real_application(self):
        self.assertEqual(check_context(ROOT), (ROOT / "ci/VERSION").read_text().strip())

    def test_broken_fixtures_fail_cli(self):
        mutations = {
            "version": ("index.html", "Version: 1.0.0", "Version: 99.0.0"),
            "heading": ("index.html", "<h1>Netology DevOps Diploma</h1>", "<h1>Wrong application</h1>"),
            "success": ("index.html", "Application is running successfully!", "Application failed!"),
            "copy": ("Dockerfile", "COPY index.html", "COPY ."),
            "secret-context": (".dockerignore", "**", "# no exclusions"),
        }
        for label, (file, old, new) in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                fixture = Path(tmp)
                (fixture / "ci").mkdir()
                for name in ("index.html", "Dockerfile", ".dockerignore", "ci/VERSION"):
                    shutil.copyfile(ROOT / name, fixture / name)
                path = fixture / file
                path.write_text(path.read_text().replace(old, new))
                run = subprocess.run([sys.executable, str(ROOT / "ci/smoke.py"), tmp],
                                     capture_output=True, text=True, timeout=10)
                self.assertEqual(run.returncode, 1)
                self.assertIn("smoke FAIL", run.stderr)


class ReleaseContract(unittest.TestCase):
    def setUp(self):
        self.good = dict(GITHUB_REPOSITORY="myachmen/netology-diploma-app", GITHUB_EVENT_NAME="push",
                         GITHUB_REF_TYPE="tag", GITHUB_REF="refs/tags/v1.0.0", APP_VERSION="1.0.0",
                         GITHUB_SHA="a" * 40, SOURCE_SHA="a" * 40, SOURCE_TAG="v1.0.0",
                         GITHUB_RUN_ID="123", SOURCE_RUN="123", GITHUB_RUN_ATTEMPT="1",
                         BUILD_RESULT="success", IMAGE_DIGEST="sha256:" + "b" * 64)

    def test_matching_same_run(self):
        self.assertEqual(validate(self.good), "1.0.0")

    def test_reject_untrusted_or_mismatched_provenance(self):
        for key, value in [("GITHUB_EVENT_NAME", "pull_request"), ("GITHUB_EVENT_NAME", "pull_request_target"),
                           ("GITHUB_EVENT_NAME", "workflow_dispatch"), ("GITHUB_REPOSITORY", "fork/app"),
                           ("GITHUB_REF_TYPE", "branch"), ("GITHUB_REF", "refs/heads/main"),
                           ("SOURCE_SHA", "c" * 40), ("SOURCE_TAG", "v9.9.9"), ("SOURCE_RUN", "456"),
                           ("GITHUB_RUN_ATTEMPT", "2"), ("BUILD_RESULT", "failure"),
                           ("IMAGE_DIGEST", "latest"), ("IMAGE_DIGEST", "sha256:bad"),
                           ("IMAGE_DIGEST", "sha256:" + "b" * 64 + ";sh"), ("APP_VERSION", "1.0.1")]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                validate(dict(self.good, **{key: value}))

    def test_missing_values_fail(self):
        for key in self.good:
            env = self.good.copy()
            del env[key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate(env)

    def test_deploy_script_rejects_before_any_external_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "called"
            for name in ("ssh", "kubectl", "curl"):
                path = Path(tmp) / name
                path.write_text(f"#!/bin/sh\necho forbidden >> '{marker}'\nexit 99\n")
                path.chmod(0o700)
            env = dict(os.environ, PATH=tmp + os.pathsep + os.environ["PATH"], **self.good)
            env["GITHUB_EVENT_NAME"] = "pull_request"
            run = subprocess.run(["bash", str(ROOT / "ci/deploy.sh")], env=env,
                                 cwd=ROOT, capture_output=True, text=True, timeout=10)
            self.assertNotEqual(run.returncode, 0)
            self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
