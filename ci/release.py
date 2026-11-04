"""Fail-closed same-run release contract; no network or credential handling."""
import os
import re


def validate(env):
    def require(condition, message):
        if not condition:
            raise ValueError(message)
    require(env.get("GITHUB_REPOSITORY") == "myachmen/netology-diploma-app", "Wrong repository")
    require(env.get("GITHUB_EVENT_NAME") == "push", "Only a release tag push is eligible")
    require(env.get("GITHUB_REF_TYPE") == "tag", "Not a tag")
    version = env.get("APP_VERSION", "")
    require(bool(re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version)), "Invalid application version")
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
    try:
        validate(os.environ)
        print("Same-run release contract PASS")
    except ValueError as exc:
        raise SystemExit("Release gate FAIL: " + str(exc)) from None
