"""Minimal same-run release and build metadata; no GitHub policy API/admission."""
import argparse
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

REPOSITORY = 'myachmen/netology-diploma-app'
IMAGE = 'cr.yandex/crpb1oihnpa2uai8m3mp/netology-diploma-app'
VERSION = r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def build_metadata(env, version):
    """Own main/tag pushes once; feature branches cannot publish."""
    require(env.get('GITHUB_REPOSITORY') == REPOSITORY and env.get('GITHUB_EVENT_NAME') == 'push',
            'Only own-repository push may publish')
    require(re.fullmatch(VERSION, version), 'Invalid application version')
    sha, ref = env.get('GITHUB_SHA', ''), env.get('GITHUB_REF', '')
    require(re.fullmatch('[0-9a-f]{40}', sha), 'Invalid commit')
    run = env.get('GITHUB_RUN_ID', '')
    require(re.fullmatch('[1-9][0-9]*', run), 'Invalid run')
    require(env.get('GITHUB_RUN_ATTEMPT') == '1', 'Rerun publication forbidden')
    release = env.get('GITHUB_REF_TYPE') == 'tag'
    if release:
        require(ref == 'refs/tags/v' + version, 'Tag/version mismatch')
    else:
        require(env.get('GITHUB_REF_TYPE') == 'branch' and ref == 'refs/heads/main',
                'Feature branches are test-only')
    # Unique run-bound tag; no mutable latest/version alias. Deploy only by digest.
    tags = [IMAGE + ':sha-' + sha + '-run-' + run]
    return {'valid': str(release).lower(), 'sha': sha, 'tag': 'v' + version if release else '',
            'run': run, 'version': version, 'tags': '\n'.join(tags)}


def validate_credentials(env):
    """Check presence/shape before external commands; never print values."""
    import base64
    names = ('SSH_PRIVATE_KEY', 'SSH_KNOWN_HOSTS', 'KUBE_CA_B64', 'KUBE_TOKEN',
             'SSH_HOST', 'SSH_USER', 'API_TLS_NAME', 'APP_URL')
    for name in names:
        value = env.get(name)
        require(isinstance(value, str) and bool(value.strip()) and '\0' not in value,
                'Missing/invalid credential or configuration: ' + name)
    require(env['SSH_USER'] == 'cd-tunnel', 'Dedicated cd-tunnel identity required')
    for name in ('SSH_HOST', 'API_TLS_NAME'):
        require(re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9.-]*', env[name]), 'Invalid endpoint configuration')
    require(re.fullmatch(r'[A-Za-z0-9_.-]+', env['KUBE_TOKEN']), 'Invalid scoped token format')
    try:
        require(bool(base64.b64decode(env['KUBE_CA_B64'], validate=True)), 'Empty CA')
        url = urlsplit(env['APP_URL'])
        require(url.scheme in ('http', 'https') and url.hostname and not url.username and
                not url.password and not url.query and not url.fragment and url.path == '/',
                'Invalid application URL')
        _ = url.port
    except (ValueError, UnicodeError):
        raise ValueError('Invalid CA or application URL configuration') from None


def validate(env):
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
    parser = argparse.ArgumentParser()
    parser.add_argument('--build-output', type=Path)
    parser.add_argument('--credentials', action='store_true')
    args = parser.parse_args()
    try:
        if args.build_output:
            require(not args.credentials, 'Conflicting options')
            version = (Path(__file__).resolve().parent / 'VERSION').read_text().strip()
            metadata = build_metadata(os.environ, version)
            with args.build_output.open('a') as output:
                for key, value in metadata.items():
                    if key == 'tags':
                        output.write('tags<<IMAGES\n' + value + '\nIMAGES\n')
                    else:
                        output.write(key + '=' + value + '\n')
            print('Build metadata PASS')
        else:
            validate(os.environ)
            if args.credentials:
                validate_credentials(os.environ)
            print('Same-run release contract PASS')
    except ValueError as exc:
        raise SystemExit("Release gate FAIL: " + str(exc)) from None
    except (KeyError, TypeError, UnicodeError, OSError):
        raise SystemExit('Release gate FAIL: invalid/unavailable configuration; no retry') from None
