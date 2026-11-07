"""One approved origin only. No deploy, registry, SSH or credential operation here."""
import argparse
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

from ci.release import require

REPO = 'myachmen/netology-diploma-app'
ORIGIN = 42372499463
SHA = 'fc62b598de874c2d3c95b8963e73cc7392696f67'
TAG = 'v1.0.4'
VERSION = '1.0.4'
DIGEST = 'sha256:a5bf2975580120f2ffdf8a848e425d38d96b2d572dee3e999914189a80e00764'
JOBS = {'test': 128403328541, 'build-and-push': 128403357868, 'deploy': 128403446744}
WORKFLOW = '.github/workflows/docker-publish.yml'
RECOVERY_WORKFLOW = '.github/workflows/recover-diploma-193.yml'
CONFIRM = 'RECOVER_42372499463_v1.0.4'
LIMIT = 1024 * 1024


def execution(env):
    require(env.get('GITHUB_REPOSITORY') == REPO, 'Wrong recovery repository')
    require(env.get('GITHUB_EVENT_NAME') == 'workflow_dispatch' and
            env.get('GITHUB_REF') == 'refs/heads/main', 'Manual main recovery only')
    require(env.get('GITHUB_ACTOR') == env.get('GITHUB_TRIGGERING_ACTOR') == 'myachmen',
            'Owner invocation required')
    require(env.get('GITHUB_RUN_ATTEMPT') == '1', 'No recovery reruns')
    require(env.get('RECOVERY_CONFIRMATION') == CONFIRM, 'Explicit origin confirmation required')
    run = env.get('GITHUB_RUN_ID', '')
    require(re.fullmatch('[1-9][0-9]*', run) and run != str(ORIGIN), 'Invalid execution run')
    sha = env.get('GITHUB_SHA', '')
    require(re.fullmatch('[0-9a-f]{40}', sha) is not None, 'Invalid control SHA')
    require(env.get('GITHUB_WORKFLOW_REF') == REPO + '/' + RECOVERY_WORKFLOW + '@refs/heads/main'
            and env.get('GITHUB_WORKFLOW_SHA') == sha, 'Untrusted control workflow')
    return {'execution_run_id': run, 'execution_sha': sha}


def evidence(run, jobs, build_log, deploy_log, tag):
    require(run.get('id') == ORIGIN and run.get('run_number') == 26 and run.get('run_attempt') == 1,
            'Wrong origin run/attempt')
    require(run.get('repository', {}).get('full_name') == REPO and run.get('event') == 'push'
            and run.get('head_sha') == SHA and run.get('head_branch') == TAG
            and run.get('path') == WORKFLOW and run.get('conclusion') == 'failure'
            and run.get('status') == 'completed', 'Wrong origin identity/status')
    require(tag.get('ref') == 'refs/tags/' + TAG and
            tag.get('object') == {'type': 'commit', 'sha': SHA,
                                 'url': 'https://api.github.com/repos/' + REPO + '/git/commits/' + SHA},
            'Tag changed')
    items = jobs.get('jobs', [])
    require(jobs.get('total_count') == len(items) == 3, 'Incomplete/ambiguous jobs')
    for name, job_id in JOBS.items():
        matches = [j for j in items if j.get('name') == name]
        require(len(matches) == 1, 'Ambiguous job')
        j = matches[0]
        require(j.get('id') == job_id and j.get('run_id') == ORIGIN and j.get('run_attempt') == 1
                and j.get('head_sha') == SHA and j.get('status') == 'completed'
                and j.get('conclusion') == ('failure' if name == 'deploy' else 'success'),
                'Wrong original job/status')
        if name != 'test':
            step = 'Deploy this run digest and verify application' if name == 'deploy' else 'Build and push exact source'
            steps = [s for s in j.get('steps', []) if s.get('name') == step]
            require(len(steps) == 1 and steps[0].get('conclusion') == j['conclusion']
                    and steps[0].get('status') == 'completed', 'Wrong original step')
    digests = re.findall(r'"containerimage\.digest"\s*:\s*"([^"\n]+)"', build_log)
    require(digests == [DIGEST], 'Missing/masked/ambiguous original build digest')
    # Only the one actual deploy step: never trust an arbitrary occurrence in the job log.
    starts = [m.end() for m in re.finditer(r'##\[group\]Run bash ci/deploy\.sh\r?\n', deploy_log)]
    require(len(starts) == 1, 'Ambiguous deploy step log')
    block = deploy_log[starts[0]:].split('Post job cleanup', 1)[0]
    expected = {'BUILD_RESULT': 'success', 'IMAGE_DIGEST': DIGEST, 'SOURCE_SHA': SHA,
                'SOURCE_TAG': TAG, 'SOURCE_RUN': str(ORIGIN), 'APP_VERSION': VERSION}
    lines = [re.sub(r'^\ufeff?\d{4}-\d\d-\d\dT[0-9:.]+Z ', '', l).lstrip()
             for l in block.splitlines()]
    for key, value in expected.items():
        require([l[len(key) + 2:].strip() for l in lines if l.startswith(key + ': ')] == [value],
                'Missing/masked/mismatched original deploy output')
    trace = re.findall(r'API_ACCESS FAIL attempt=\d+/10 category=[A-Z0-9_]+ process=[a-z]+ exit=\d+', block)
    expected_trace = [
        'API_ACCESS FAIL attempt=1/10 category=API_CONNECTION_FAILURE process=running exit=1',
        'API_ACCESS FAIL attempt=2/10 category=API_CONNECTION_FAILURE process=running exit=1',
        'API_ACCESS FAIL attempt=3/10 category=API_AUTH_401 process=running exit=1',
    ]
    require(trace == expected_trace, 'Unexpected original API failure trace')
    ordered = ['Same-run release contract PASS', *trace,
               'CD FAIL stage=ssh_api_access exit=1; STOP, no retry/rollback',
               'Process completed with exit code 1']
    positions = [block.find(marker) for marker in ordered]
    require(all(p >= 0 for p in positions) and positions == sorted(positions), 'Unordered failure boundary')
    require(block.count('Same-run release contract PASS') == 1
            and block.count('CD FAIL stage=ssh_api_access exit=1; STOP, no retry/rollback') == 1
            and 'Process completed with exit code 1' in block, 'Pre-patch boundary unproven')
    require(not any(x in block for x in ('CD PASS', 'API_ACCESS PASS', 'stage=guarded_patch',
                                        'stage=rollout', 'stage=http_smoke')), 'Unexpected later execution')
    return expected


class NoCredentialRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        url = urlsplit(newurl)
        require(url.scheme == 'https' and url.hostname and not url.username and not url.password,
                'Unsafe API log redirect')
        # Signed log URLs must NOT receive the GitHub Authorization header.
        return Request(newurl, method='GET', headers={'User-Agent': 'diploma-recovery-193'})


def fetch(path, token, *, as_json=True):
    url = 'https://api.github.com/repos/' + REPO + '/' + path
    req = Request(url, headers={'Authorization': 'Bearer ' + token,
                               'Accept': 'application/vnd.github+json',
                               'User-Agent': 'diploma-recovery-193', 'X-GitHub-Api-Version': '2022-11-28'})
    with build_opener(NoCredentialRedirect()).open(req, timeout=20) as reply:
        data = reply.read(LIMIT + 1)
    require(len(data) <= LIMIT, 'Provenance response too large')
    text = data.decode('utf-8-sig')
    return json.loads(text) if as_json else text


def manifest_path(env):
    return Path(env['RUNNER_TEMP']) / 'diploma-recovery-193.json'


def verify_and_write(env, *, get=fetch):
    control = execution(env)
    token = env.get('GH_TOKEN', '')
    require(bool(token), 'Missing Actions read token')
    base = f'actions/runs/{ORIGIN}/attempts/1'
    expected = evidence(get(base, token), get(base + '/jobs?per_page=20', token),
                        get(f'actions/jobs/{JOBS["build-and-push"]}/logs', token, as_json=False),
                        get(f'actions/jobs/{JOBS["deploy"]}/logs', token, as_json=False),
                        get('git/ref/tags/' + TAG, token))
    doc = dict(control, origin_build_run_id=str(ORIGIN), original_attempt=1,
               source=expected, boundary='API_AUTH_401_BEFORE_PATCH')
    fd = os.open(manifest_path(env), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(doc, stream)
    return doc


def validate(env):
    control = execution(env)
    path = manifest_path(env)
    require(path.is_file() and not path.is_symlink() and path.stat().st_mode & 0o777 == 0o600,
            'Missing/private provenance manifest required')
    doc = json.loads(path.read_text())
    source = {'BUILD_RESULT': 'success', 'IMAGE_DIGEST': DIGEST, 'SOURCE_SHA': SHA,
              'SOURCE_TAG': TAG, 'SOURCE_RUN': str(ORIGIN), 'APP_VERSION': VERSION}
    require(doc == dict(control, origin_build_run_id=str(ORIGIN), original_attempt=1,
                        source=source, boundary='API_AUTH_401_BEFORE_PATCH'), 'Wrong provenance manifest')
    require(all(env.get(k) == v for k, v in source.items()), 'Recovery output substitution')
    require(env.get('ORIGIN_BUILD_RUN_ID') == str(ORIGIN)
            and env.get('EXECUTION_RUN_ID') == control['execution_run_id'], 'Cross-run substitution')
    return VERSION


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--verify', action='store_true')
    parser.add_argument('--cleanup', action='store_true')
    args = parser.parse_args()
    try:
        require(args.verify != args.cleanup, 'Choose one operation')
        if args.cleanup:
            manifest_path(os.environ).unlink(missing_ok=True)
        else:
            verify_and_write(os.environ)
            print('Recovery provenance PASS origin_run=42372499463 attempt=1; pre-patch boundary verified')
    except Exception:
        # HTTP/JSON/path exceptions can contain tokens, signed URLs or raw log data.
        raise SystemExit('Recovery provenance FAIL: STOP; no deployment allowed') from None
