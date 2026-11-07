"""Keep the ordinary tag contract unchanged; manual recovery is a separate gate."""
import os
import sys
from ci.release import require, validate_credentials


def validate(env):
    if env.get('CD_RECOVERY') == 'origin-26':
        from ci.recovery import validate as recovery_validate
        return recovery_validate(env)
    require(not env.get('CD_RECOVERY'), 'Unknown contract mode')
    from ci.release import validate as release_validate
    return release_validate(env)


if __name__ == '__main__':
    try:
        require(sys.argv[1:] == ['--credentials'], 'Unsupported contract operation')
        validate(os.environ)
        validate_credentials(os.environ)
        print('Deployment execution contract PASS')
    except Exception:
        raise SystemExit('Deployment execution contract FAIL: STOP') from None
