"""Authenticated GitHub admission. No local observation file or anonymous fallback.

Runtime statements are attestations by the configured independent environment
reviewer, attached to this run's approved review. They are not machine observations
of Kubernetes. API policy, run, issuer and immutable artifact bindings are verified.
"""
from copy import deepcopy
from datetime import datetime
import hashlib
import io
import json
import math
import re
import ssl
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener
import zipfile

from ci.activation import require

REPOSITORY = 'myachmen/netology-diploma-app'
REPOSITORY_ID = 1440700475
ROOT = '/repos/' + REPOSITORY
ENVIRONMENT = 'diploma-production'
WORKFLOW = '.github/workflows/docker-publish.yml'
MAX_ARCHIVE = 1024 * 1024
MAX_DOCUMENT = 32768
PREFIX = 'APH-CD/1\n'


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate JSON field')
            result[key] = value
        return result
    def invalid_constant(value):
        raise ValueError('Non-finite JSON number')
    def finite_float(value):
        result = float(value)
        require(math.isfinite(result), 'Non-finite JSON number')
        return result
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant, parse_float=finite_float)


def timestamp(value):
    require(isinstance(value, str) and value.endswith('Z'), 'Missing authoritative API timestamp')
    return datetime.fromisoformat(value[:-1] + '+00:00').timestamp()


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GitHubAPI:
    """Fixed HTTPS origin, GET only, bounded, no retries or credential redirects."""
    def __init__(self, token, opener=None):
        require(isinstance(token, str) and bool(re.fullmatch(r'[A-Za-z0-9_.-]{1,4096}', token)),
                'BLOCKED: CD_GITHUB_READ_TOKEN is required; no credentials fallback')
        self._token = token
        self._opener = opener or build_opener(ProxyHandler({}), NoRedirect(),
                                               HTTPSHandler(context=ssl.create_default_context()))

    def _request(self, path):
        require(path.startswith(ROOT + '/') or path == ROOT, 'Unexpected repository endpoint')
        require('#' not in path and '\\' not in path and
                all(part not in ('.', '..') for part in path.split('/')), 'Invalid API path')
        relative = path.removeprefix(ROOT).split('?')[0]
        allowed = (r'', r'/branches/main/protection', r'/rulesets(?:/[1-9][0-9]*)?',
                   r'/environments/diploma-production(?:/deployment-branch-policies)?',
                   r'/actions/runs/[1-9][0-9]*(?:/approvals|/artifacts|/attempts/1/jobs)?',
                   r'/actions/artifacts/[1-9][0-9]*/zip', r'/git/ref/tags/v[0-9]+\.[0-9]+\.[0-9]+',
                   r'/git/tags/[0-9a-f]{40}', r'/compare/[0-9a-f]{40}\.\.\.main')
        require(any(re.fullmatch(pattern, relative) for pattern in allowed), 'Unexpected metadata endpoint')
        return Request('https://api.github.com' + path, method='GET', headers={
            'Authorization': 'Bearer ' + self._token, 'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2026-03-10', 'User-Agent': 'diploma-cd-gate'})

    def _read(self, request, maximum):
        with self._opener.open(request, timeout=15) as response:
            require(response.status == 200, 'BLOCKED: unexpected GitHub response')
            data = response.read(maximum + 1)
        require(len(data) <= maximum, 'BLOCKED: oversized GitHub response')
        return data

    def get(self, path):
        try:
            return strict_json(self._read(self._request(path), 2 * MAX_ARCHIVE))
        except HTTPError as exc:
            raise ValueError('BLOCKED: GitHub HTTP ' + str(exc.code) +
                             '; check Actions/Contents/Administration read and policy visibility') from None
        except (URLError, TimeoutError, OSError):
            raise ValueError('BLOCKED: GitHub transport unavailable; no retry') from None

    def archive(self, artifact_id):
        require(type(artifact_id) is int and artifact_id > 0, 'Invalid artifact ID')
        try:
            # Only this endpoint may redirect; never forward the API bearer token.
            try:
                return self._read(self._request(ROOT + '/actions/artifacts/' + str(artifact_id) + '/zip'), MAX_ARCHIVE)
            except HTTPError as exc:
                require(exc.code == 302, 'BLOCKED: artifact API HTTP ' + str(exc.code))
                location = exc.headers.get('Location', '')
            url = urlsplit(location)
            require(url.scheme == 'https' and url.hostname and not url.username and not url.password and
                    url.port in (None, 443) and not url.fragment and
                    any(url.hostname.endswith(suffix) for suffix in
                        ('.blob.core.windows.net', '.actions.githubusercontent.com', '.githubusercontent.com')),
                    'BLOCKED: unapproved artifact redirect origin')
            return self._read(Request(location, method='GET', headers={'User-Agent': 'diploma-cd-gate'}), MAX_ARCHIVE)
        except (HTTPError, URLError, TimeoutError, OSError):
            raise ValueError('BLOCKED: artifact transport unavailable; no retry') from None


def collection(api, path, key):
    obj = api.get(path + ('&' if '?' in path else '?') + 'per_page=100')
    items = obj.get(key)
    require(isinstance(items, list) and type(obj.get('total_count')) is int and
            obj['total_count'] == len(items) and len(items) < 100, 'BLOCKED: incomplete API collection')
    return items


def manifest_from_archive(raw, artifact):
    require(isinstance(raw, bytes) and len(raw) <= MAX_ARCHIVE, 'Invalid artifact size')
    require(artifact.get('digest') == 'sha256:' + hashlib.sha256(raw).hexdigest(), 'Artifact digest mismatch')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            require(len(entries) == 1 and entries[0].filename == 'cd-release.json' and
                    not entries[0].is_dir() and entries[0].file_size <= MAX_DOCUMENT and
                    not entries[0].flag_bits & 1, 'Unexpected artifact members')
            with archive.open(entries[0]) as content:
                data = content.read(MAX_DOCUMENT + 1)
            require(len(data) <= MAX_DOCUMENT, 'Manifest too large')
            return strict_json(data)
    except (zipfile.BadZipFile, UnicodeError, RuntimeError):
        raise ValueError('Invalid artifact archive') from None


class GitHubVerifier:
    def __init__(self, api, clock=time.time):
        self.api, self.clock = api, clock

    def _branch(self):
        protection = self.api.get(ROOT + '/branches/main/protection')
        require(protection.get('enforce_admins', {}).get('enabled') is True, 'Main admin enforcement missing')
        reviews = protection.get('required_pull_request_reviews') or {}
        require(type(reviews.get('required_approving_review_count')) is int and
                reviews['required_approving_review_count'] >= 1 and reviews.get('dismiss_stale_reviews') is True and
                reviews.get('require_last_push_approval') is True, 'Main independent review protection missing')
        require(reviews.get('bypass_pull_request_allowances') == {'users': [], 'teams': [], 'apps': []},
                'Main bypass policy unavailable/not empty')
        status = protection.get('required_status_checks') or {}
        require(status.get('strict') is True and any(c.get('context') == 'test' and c.get('app_id') == 15368
                for c in status.get('checks', [])), 'Trusted test check enforcement missing')
        for name in ('allow_force_pushes', 'allow_deletions'):
            require(protection.get(name, {}).get('enabled') is False, 'Main destructive write protection missing')

    def _tag(self, ref):
        summaries = self.api.get(ROOT + '/rulesets?includes_parents=true&per_page=100')
        require(isinstance(summaries, list) and len(summaries) < 100, 'Incomplete rulesets')
        found = False
        for item in summaries:
            require(type(item.get('id')) is int, 'Invalid ruleset ID')
            rule = self.api.get(ROOT + '/rulesets/' + str(item['id']))
            if rule.get('target') != 'tag' or rule.get('enforcement') != 'active':
                continue
            condition = rule.get('conditions', {}).get('ref_name', {})
            if condition != {'include': [ref], 'exclude': []}:
                continue  # First release deliberately requires an exact, non-glob policy.
            require('bypass_actors' in rule, 'BLOCKED: API hides tag ruleset bypass_actors; policy visibility required')
            require(rule['bypass_actors'] == [] and rule.get('enforcement') == 'active' and rule.get('target') == 'tag',
                    'Tag bypass/enforcement invalid')
            types = {r.get('type') for r in rule.get('rules', [])}
            require({'deletion', 'update'} <= types, 'Tag immutability rules missing')
            found = True
        require(found, 'Exact active tag protection missing')

    def observe(self, env):
        try:
            return self._observe(env)
        except (KeyError, TypeError, AttributeError, IndexError, OverflowError):
            raise ValueError('BLOCKED: malformed/ambiguous GitHub metadata') from None

    def _observe(self, env):
        # The public entry point rechecks event/provenance too, not just its caller.
        from ci.release import validate
        validate(env)
        now = self.clock()
        repo = self.api.get(ROOT)
        require(repo.get('id') == REPOSITORY_ID and repo.get('full_name') == REPOSITORY and
                repo.get('fork') is False, 'Wrong authoritative repository')
        run_id = env['GITHUB_RUN_ID']
        run_path = ROOT + '/actions/runs/' + run_id
        run = self.api.get(run_path)
        tag = env['GITHUB_REF'].removeprefix('refs/tags/')
        require(type(run.get('id')) is int and type(run.get('run_attempt')) is int and
                run.get('id') == int(run_id) and run.get('event') == 'push' and run.get('run_attempt') == 1 and
                run.get('head_sha') == env['GITHUB_SHA'] and run.get('head_branch') == tag and
                run.get('repository', {}).get('id') == REPOSITORY_ID and
                run.get('head_repository', {}).get('id') == REPOSITORY_ID and
                run.get('path') == WORKFLOW and run.get('status') == 'in_progress', 'Run metadata mismatch')
        run_created = timestamp(run.get('created_at'))
        require(0 <= now - run_created <= 2700, 'Run outside the approved release window')
        actor, trigger = run.get('actor', {}), run.get('triggering_actor', {})
        require(type(actor.get('id')) is int and type(trigger.get('id')) is int and
                actor['id'] == trigger['id'] and actor.get('login') == trigger.get('login'), 'Ambiguous run actor')
        ref = self.api.get(ROOT + '/git/ref/tags/' + quote(tag, safe=''))
        require(ref.get('ref') == env['GITHUB_REF'], 'Wrong tag ref')
        obj = ref.get('object', {})
        if obj.get('type') == 'tag':
            require(bool(re.fullmatch('[0-9a-f]{40}', obj.get('sha', ''))), 'Invalid annotated tag')
            obj = self.api.get(ROOT + '/git/tags/' + obj['sha']).get('object', {})
        require(obj.get('type') == 'commit' and obj.get('sha') == env['GITHUB_SHA'], 'Tag/commit mismatch')
        comparison = self.api.get(ROOT + '/compare/' + env['GITHUB_SHA'] + '...main')
        require(comparison.get('merge_base_commit', {}).get('sha') == env['GITHUB_SHA'] and
                comparison.get('status') in ('ahead', 'identical'), 'Release commit is not on main')
        self._branch()
        self._tag(env['GITHUB_REF'])
        environment = self.api.get(ROOT + '/environments/' + ENVIRONMENT)
        require(environment.get('name') == ENVIRONMENT and type(environment.get('id')) is int,
                'Wrong environment')
        require(environment.get('can_admins_bypass') is False,
                'BLOCKED: environment no-bypass metadata missing or bypass enabled')
        require(environment.get('deployment_branch_policy') ==
                {'protected_branches': False, 'custom_branch_policies': True}, 'Environment tag policy missing')
        policies = collection(self.api, ROOT + '/environments/' + ENVIRONMENT + '/deployment-branch-policies',
                              'branch_policies')
        require(len(policies) == 1 and policies[0].get('name') == tag and policies[0].get('type') == 'tag',
                'Exact environment tag policy unavailable')
        rules = [r for r in environment.get('protection_rules', []) if r.get('type') == 'required_reviewers']
        require(len(rules) == 1 and rules[0].get('prevent_self_review') is True, 'Reviewer policy missing')
        configured = rules[0].get('reviewers', [])
        require(configured and all(r.get('type') == 'User' and type(r.get('reviewer', {}).get('id')) is int
                for r in configured), 'BLOCKED: explicit User reviewers required; Team membership unsupported')
        allowed = {r['reviewer']['id'] for r in configured}
        history = self.api.get(run_path + '/approvals')
        require(isinstance(history, list) and len(history) < 100, 'Invalid approval history')
        relevant = [r for r in history if any(e.get('id') == environment['id'] for e in r.get('environments', []))]
        require(len(relevant) == 1 and relevant[0].get('state') == 'approved', 'Missing/rejected/ambiguous approval')
        approval = relevant[0]
        user = approval.get('user', {})
        require(type(user.get('id')) is int and user.get('id') in allowed and user['id'] not in (actor['id'], trigger['id']) and
                isinstance(user.get('login'), str), 'Untrusted/self reviewer')
        comment = approval.get('comment', '')
        require(isinstance(comment, str) and comment.startswith(PREFIX) and len(comment) <= MAX_DOCUMENT,
                'Authenticated APH-CD/1 reviewer attestation missing')
        attestation = strict_json(comment[len(PREFIX):])
        expected_fields = {'schema', 'repository_id', 'ref', 'sha', 'run_id', 'attempt', 'actor_id',
                           'digest', 'artifact_id', 'artifact_digest', 'issued_at', 'expires_at', 'runtime'}
        require(isinstance(attestation, dict) and set(attestation) == expected_fields and
                attestation['schema'] == 'APH-CD/1', 'Invalid approval attestation schema')
        bindings = {'repository_id': REPOSITORY_ID, 'ref': env['GITHUB_REF'], 'sha': env['GITHUB_SHA'],
                    'run_id': int(run_id), 'attempt': 1, 'actor_id': actor['id'], 'digest': env['IMAGE_DIGEST']}
        require(all(type(attestation.get(k)) is type(v) and attestation[k] == v for k, v in bindings.items()),
                'Approval subject/run/digest mismatch')
        issued, expires = attestation['issued_at'], attestation['expires_at']
        require(type(issued) is int and type(expires) is int and run_created <= issued <= now < expires and
                0 < expires - issued <= 300, 'Expired/future/overlong reviewer attestation')
        jobs = collection(self.api, run_path + '/attempts/1/jobs', 'jobs')
        selected = {}
        for name in ('test', 'build-and-push', 'deploy'):
            matched = [j for j in jobs if j.get('name') == name]
            require(len(matched) == 1, 'Missing/ambiguous job metadata')
            selected[name] = matched[0]
        require(all(selected[name].get('conclusion') == 'success' and selected[name].get('status') == 'completed'
                    for name in ('test', 'build-and-push')) and selected['deploy'].get('status') == 'in_progress',
                'Test/build/deploy state not eligible')
        build = selected['build-and-push']
        for step_name in ('Record immutable release manifest', 'Upload immutable release manifest'):
            steps = [s for s in build.get('steps', []) if s.get('name') == step_name]
            require(len(steps) == 1 and steps[0].get('conclusion') == 'success', 'Build evidence steps missing')
        artifacts = collection(self.api, run_path + '/artifacts', 'artifacts')
        artifacts = [a for a in artifacts if a.get('name') == 'cd-release-' + run_id + '-1']
        require(len(artifacts) == 1, 'Missing/ambiguous immutable artifact')
        artifact = artifacts[0]
        require(type(artifact.get('id')) is int and artifact['id'] == attestation['artifact_id'] and
                artifact.get('digest') == attestation['artifact_digest'] and artifact.get('expired') is False and
                type(artifact.get('size_in_bytes')) is int and
                0 < artifact.get('size_in_bytes', 0) <= MAX_ARCHIVE, 'Artifact identity/expiry/digest mismatch')
        source = artifact.get('workflow_run', {})
        require(source.get('id') == int(run_id) and source.get('repository_id') == REPOSITORY_ID and
                source.get('head_repository_id') == REPOSITORY_ID and source.get('head_sha') == env['GITHUB_SHA'],
                'Artifact from another run/repository/commit')
        require(timestamp(build.get('started_at')) <= timestamp(artifact.get('created_at')) <=
                timestamp(build.get('completed_at')), 'Artifact outside trusted build interval')
        manifest = manifest_from_archive(self.api.archive(artifact['id']), artifact)
        expected_manifest = {'schema': 1, 'repository_id': REPOSITORY_ID, 'repository': REPOSITORY,
                'ref': env['GITHUB_REF'], 'sha': env['GITHUB_SHA'], 'run_id': int(run_id), 'attempt': 1,
                'digest': env['IMAGE_DIGEST'], 'version': env['APP_VERSION'], 'producer_job': 'build-and-push'}
        require(isinstance(manifest, dict) and set(manifest) == set(expected_manifest) and
                all(type(manifest[k]) is type(v) and manifest[k] == v for k, v in expected_manifest.items()),
                'Same-run build manifest mismatch')
        runtime = attestation['runtime']
        require(isinstance(runtime, dict) and set(runtime) ==
                {'baseline', 'scope', 'observed_at', 'token_expires_at', 'token_audience_sha256',
                 'credential_commitments', 'checks'},
                'Invalid reviewer runtime statement')
        audience = env.get('CD_EXPECTED_AUDIENCE')
        require(isinstance(audience, str) and audience and runtime['token_audience_sha256'] ==
                hashlib.sha256(audience.encode()).hexdigest(), 'Attested audience hash mismatch')
        require(set(runtime.get('checks', {})) == {'scoped_credentials_verified', 'ssh_identity_verified',
                'tls_verified', 'previous_digest_verified'}, 'Invalid runtime attestation checks')
        proof = deepcopy(runtime)
        del proof['token_audience_sha256']
        proof['token_audience'] = audience
        proof.update({'schema': 1, 'repository': REPOSITORY, 'ref': env['GITHUB_REF'], 'sha': env['GITHUB_SHA'],
                      'run_id': run_id, 'attempt': 1, 'digest': env['IMAGE_DIGEST'], 'environment': ENVIRONMENT,
                      'reviewer': user['login'], 'trigger_actor': actor['login'], 'approved_at': issued,
                      'authorization_expires_at': expires,
                      'job_deadline': timestamp(selected['deploy'].get('started_at')) + 600,
                      'github_source': {'repository_id': REPOSITORY_ID, 'reviewer_id': user['id'],
                                        'environment_id': environment['id'], 'artifact_id': artifact['id']}})
        proof['checks'].update({k: True for k in ('branch_protected', 'tag_protected', 'environment_approved',
                                                 'prevent_self_review', 'admin_bypass_disabled')})
        return proof
