"""Bounded real HTTP/version verification; transport output never enters the log."""
import os
from pathlib import Path
import subprocess
import time

from ci.smoke import check_html

ATTEMPTS = 5
DELAY = 5


def probe(url, version, root, *, run=subprocess.run, sleep=time.sleep):
    """At most 5 GETs (15s each), four 5s delays: <=95s curl budget."""
    body = root / 'http-body.html'
    for attempt in range(1, ATTEMPTS + 1):
        category = 'TRANSPORT'
        try:
            reply = run(['curl', '--fail', '--silent', '--show-error', '--noproxy', '*',
                         '--proto', '=http,https', '--tlsv1.2', '--connect-timeout', '5',
                         '--max-time', '15', '--max-filesize', '65536',
                         '--output', str(body), '--write-out', '%{http_code}', url],
                        capture_output=True, text=True, timeout=17, check=False)
            if reply.returncode == 0:
                category = 'HTTP_STATUS'
                if reply.stdout == '200':
                    category = 'HTML_VERSION'
                    check_html(body.read_text(encoding='utf-8'), version)
                    print(f'HTTP smoke PASS attempt={attempt} status=200 exact_version={version}')
                    return
            elif reply.returncode == 28:
                category = 'TIMEOUT'
        except subprocess.TimeoutExpired:
            category = 'TIMEOUT'
        except (ValueError, OSError, UnicodeError):
            # Never include body, URL, raw curl stderr or exception text.
            pass
        print(f'HTTP smoke attempt={attempt}/{ATTEMPTS} category={category}')
        if attempt < ATTEMPTS:
            sleep(DELAY)
    raise ValueError('HTTP_SMOKE_EXHAUSTED: STOP; rollout may already have succeeded')


if __name__ == '__main__':
    try:
        probe(os.environ['APP_URL'], os.environ['APP_VERSION'], Path(os.environ['CD_WORK_DIR']))
    except (KeyError, ValueError, OSError):
        raise SystemExit('HTTP smoke FAIL: bounded checks exhausted/invalid configuration; no deployment retry') from None
