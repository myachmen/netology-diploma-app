"""Admission contract; production issuer/policy verification is in github_gate.

No local JSON/env observation becomes an authorization. Runtime facts are explicitly
attested by an independent GitHub reviewer, not machine-verified here.
"""
import re
import time
import hashlib
import json
import math

PROFILES = ('PREPARATION', 'ACTIVATION')
MIN_TOKEN_SECONDS = 900
MIN_JOB_SECONDS = 300
MAX_EVIDENCE_AGE = 300
CHECKS = ('branch_protected', 'tag_protected', 'environment_approved',
          'prevent_self_review', 'admin_bypass_disabled', 'scoped_credentials_verified',
          'ssh_identity_verified', 'tls_verified', 'previous_digest_verified')


def credential_commitments(env):
    """Local commitments only; raw values are never passed to the API observer."""
    token = env.get('KUBE_TOKEN')
    require(isinstance(token, str) and bool(token), 'Missing scoped credential for local binding')
    names = ('KUBE_CA_B64', 'SSH_KNOWN_HOSTS', 'SSH_HOST', 'SSH_USER',
             'API_TLS_NAME', 'APP_URL', 'CD_EXPECTED_AUDIENCE')
    trust = {name: env.get(name) for name in names}
    require(all(isinstance(value, str) and value for value in trust.values()), 'Missing trust configuration for binding')
    canonical = json.dumps(trust, sort_keys=True, separators=(',', ':')).encode()
    return {'kube_token_sha256': hashlib.sha256(token.encode()).hexdigest(),
            'trust_config_sha256': hashlib.sha256(canonical).hexdigest()}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_activation(env, evidence, now=None):
    """Validate already authenticated observations; tests use synthetic fixtures only."""
    from ci.release import validate
    validate(env)
    now = time.time() if now is None else now
    require(env.get('CD_PROFILE') == 'ACTIVATION', 'Activation profile not selected')
    require(env.get('CD_ENABLED') == 'true' and env.get('CD_SSH_TUNNEL_APPROVED') == 'true',
            'Flags default to disabled')
    require(bool(env.get('CD_EXPECTED_REF')) and env['CD_EXPECTED_REF'] == env.get('GITHUB_REF'),
            'Unapproved ref')
    require(bool(re.fullmatch('[0-9a-f]{40}', env.get('CD_EXPECTED_SHA', ''))) and
            env['CD_EXPECTED_SHA'] == env.get('GITHUB_SHA'), 'Unapproved commit')
    require(isinstance(evidence, dict) and type(evidence.get('schema')) is int and
            evidence['schema'] == 1, 'Missing gate evidence')
    for key, env_key in [('repository', 'GITHUB_REPOSITORY'), ('ref', 'GITHUB_REF'),
                         ('sha', 'GITHUB_SHA'), ('run_id', 'GITHUB_RUN_ID'),
                         ('digest', 'IMAGE_DIGEST')]:
        require(evidence.get(key) == env.get(env_key) and bool(evidence.get(key)), 'Gate binding mismatch: ' + key)
    require(evidence.get('attempt') == 1 and type(evidence.get('attempt')) is int, 'Wrong gate attempt')
    require(evidence.get('environment') == 'diploma-production', 'Wrong environment')
    observed = evidence.get('observed_at')
    approved = evidence.get('approved_at')
    require(type(observed) in (int, float) and 0 <= now - observed <= MAX_EVIDENCE_AGE,
            'Stale/future gate evidence')
    require(type(approved) in (int, float) and observed <= approved <= now, 'Invalid approval time')
    expires = evidence.get('authorization_expires_at')
    require(type(expires) in (int, float) and now < expires <= approved + 300, 'Expired/overlong admission')
    reviewer, actor = evidence.get('reviewer'), evidence.get('trigger_actor')
    require(isinstance(reviewer, str) and isinstance(actor, str) and bool(reviewer.strip()) and
            bool(actor.strip()) and reviewer.casefold().strip() != actor.casefold().strip(),
            'Independent approval required')
    require(isinstance(evidence.get('checks'), dict), 'Missing protection/trust observations')
    for check in CHECKS:
        require(evidence.get('checks', {}).get(check) is True, 'Unverified gate: ' + check)
    scope = evidence.get('scope', {})
    require(scope == {'namespace': 'default', 'deployment': 'diploma-app',
                       'identity': 'system:serviceaccount:default:github-actions-deployer',
                       'resource': 'deployments.apps', 'resource_names': ['diploma-app'],
                       'verbs': ['get', 'patch', 'list', 'watch']}, 'Unexpected credential scope')
    for key, minimum in [('token_expires_at', MIN_TOKEN_SECONDS), ('job_deadline', MIN_JOB_SECONDS)]:
        value = evidence.get(key)
        require(type(value) in (int, float) and math.isfinite(value) and value - now >= minimum,
                'Insufficient time budget: ' + key)
    require(evidence.get('token_audience') and evidence['token_audience'] == env.get('CD_EXPECTED_AUDIENCE'),
            'Token audience not independently approved')
    require(isinstance(evidence.get('baseline'), dict) and bool(evidence['baseline']), 'Missing approved baseline')
    commitments = evidence.get('credential_commitments')
    require(isinstance(commitments, dict) and set(commitments) == {'kube_token_sha256', 'trust_config_sha256'} and
            all(isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value)
                for value in commitments.values()), 'Missing credential/trust commitments')
    return evidence


def authorize_execution(env, verifier=None, now=None):
    """Runtime choke point; dependency injection exists for offline tests only."""
    from ci.release import validate
    validate(env)
    require(env.get('CD_PROFILE') in PROFILES, 'Unknown execution profile')
    require(env['CD_PROFILE'] != 'PREPARATION', 'CD_DISABLED: preparation profile')
    # Validate allowlist/flags BEFORE any future authenticated verifier is invoked.
    require(env.get('CD_ENABLED') == 'true' and env.get('CD_SSH_TUNNEL_APPROVED') == 'true', 'CD_DISABLED')
    require(env.get('CD_EXPECTED_REF') == env.get('GITHUB_REF') and bool(env.get('CD_EXPECTED_REF')),
            'Unapproved ref')
    require(env.get('CD_EXPECTED_SHA') == env.get('GITHUB_SHA') and bool(env.get('CD_EXPECTED_SHA')),
            'Unapproved SHA')
    if verifier is None:
        from ci.github_gate import GitHubAPI, GitHubVerifier
        verifier = GitHubVerifier(GitHubAPI(env.get('CD_GITHUB_READ_TOKEN')), clock=time.time if now is None else lambda: now)
    # Do not pass credential-bearing process environment to an observer.
    names = ('GITHUB_REPOSITORY', 'GITHUB_EVENT_NAME', 'GITHUB_REF_TYPE', 'GITHUB_REF',
             'GITHUB_SHA', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'APP_VERSION', 'SOURCE_SHA',
             'SOURCE_TAG', 'SOURCE_RUN', 'BUILD_RESULT', 'IMAGE_DIGEST', 'CD_EXPECTED_AUDIENCE')
    context = {key: env.get(key) for key in names}
    proof = validate_activation(env, verifier.observe(context), now)
    require(proof['credential_commitments'] == credential_commitments(env),
            'Credential/trust substitution: reviewer commitment mismatch')
    return proof
