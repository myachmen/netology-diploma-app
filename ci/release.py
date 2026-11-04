"""Fail-closed same-run release contract; no network or credential handling."""
import argparse
import json
import os
from pathlib import Path
import re


def validate(env):
    def require(condition, message):
        if not condition:
            raise ValueError(message)
    require(env.get("GITHUB_REPOSITORY") == "myachmen/netology-diploma-app", "Wrong repository")
    require(env.get("GITHUB_EVENT_NAME") == "push", "Only a release tag push is eligible")
    require(env.get("GITHUB_REF_TYPE") == "tag", "Not a tag")
    version = env.get("APP_VERSION", "")
    require(bool(re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", version)), "Invalid application version")
    require(env.get("GITHUB_REF") == "refs/tags/v" + version, "Tag/version mismatch")
    sha = env.get("GITHUB_SHA", "")
    require(bool(re.fullmatch(r"[0-9a-f]{40}", sha)), "Invalid commit")
    require(env.get("SOURCE_SHA") == sha, "Build/event commit mismatch")
    require(env.get("SOURCE_TAG") == "v" + version, "Build/event tag mismatch")
    require(env.get("SOURCE_RUN") == env.get("GITHUB_RUN_ID") and
            bool(re.fullmatch(r"[1-9][0-9]*", env.get("SOURCE_RUN", ""))), "Build/run mismatch")
    require(env.get("GITHUB_RUN_ATTEMPT") == "1", "Reruns require a separately reviewed policy")
    require(env.get("BUILD_RESULT") == "success", "Build did not succeed")
    require(bool(re.fullmatch(r"sha256:[0-9a-f]{64}", env.get("IMAGE_DIGEST", ""))), "Invalid immutable digest")
    return version


if __name__ == "__main__":
    # Direct script execution needs the repository root for the ci namespace.
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ci.activation import authorize_execution
    parser = argparse.ArgumentParser()
    parser.add_argument('--authorization-output', required=True, type=Path)
    args = parser.parse_args()
    try:
        proof = authorize_execution(os.environ)
        # No production verifier is wired in this preparation. Env/file fixtures
        # cannot reach this write; a future reviewed implementation must supply it.
        fd = os.open(args.authorization_output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'w') as output:
            json.dump(proof, output)
        print("Authenticated activation contract PASS")
    except ValueError as exc:
        raise SystemExit("Release gate FAIL: " + str(exc)) from None
