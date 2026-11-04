"""Record non-secret release provenance for a same-run immutable Actions artifact."""
import argparse
import json
import os
from pathlib import Path

from ci.activation import require
from ci.github_gate import REPOSITORY_ID
from ci.release import validate


def build_manifest(env):
    validate(env)
    require(env.get('GITHUB_JOB') == 'build-and-push', 'Not the trusted producer job')
    require(env.get('GITHUB_RUN_ATTEMPT') == '1', 'Release reruns are not admitted')
    return {'schema': 1, 'repository_id': REPOSITORY_ID, 'repository': env['GITHUB_REPOSITORY'],
            'ref': env['GITHUB_REF'], 'sha': env['GITHUB_SHA'], 'run_id': int(env['GITHUB_RUN_ID']),
            'attempt': 1, 'digest': env['IMAGE_DIGEST'], 'version': env['APP_VERSION'],
            'producer_job': 'build-and-push'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    try:
        manifest = build_manifest(os.environ)
        fd = os.open(args.destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'w') as output:
            json.dump(manifest, output, sort_keys=True)
    except (ValueError, OSError):
        raise SystemExit('Release manifest FAIL; no retry') from None
