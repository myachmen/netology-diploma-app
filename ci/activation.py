"""Offline activation contract. Data validation is NOT evidence authentication.

The execution adapter deliberately fails closed: a future reviewed integration must
authenticate GitHub protection/reviewer and scoped runtime evidence independently.
No env flag, local JSON file, fixture or plugin path can enable that adapter.
"""
import re
import time

PROFILES = ('PREPARATION', 'ACTIVATION')
MIN_TOKEN_SECONDS = 900
MIN_JOB_SECONDS = 300
MAX_EVIDENCE_AGE = 300
CHECKS = ('branch_protected', 'tag_protected', 'environment_approved',
          'prevent_self_review', 'admin_bypass_disabled', 'scoped_credentials_verified',
          'ssh_identity_verified', 'tls_verified', 'previous_digest_verified')


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
        require(type(value) in (int, float) and value - now >= minimum, 'Insufficient time budget: ' + key)
    require(evidence.get('token_audience') and evidence['token_audience'] == env.get('CD_EXPECTED_AUDIENCE'),
            'Token audience not independently approved')
    require(isinstance(evidence.get('baseline'), dict) and bool(evidence['baseline']), 'Missing approved baseline')
    return evidence


def authorize_execution(env, verifier=None, now=None):
    """Runtime choke point: the shipped CLI never supplies a verifier."""
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
    require(verifier is not None, 'BLOCKED: authenticated activation verifier is not integrated')
    return validate_activation(env, verifier.observe(env), now)
