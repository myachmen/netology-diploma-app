#!/usr/bin/env bash
# FUTURE ONLY: workflow job remains literal false &&. No automatic retry/rollback.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 ci/release.py
[[ "${CD_ENABLED:-}" == true && "${CD_SSH_TUNNEL_APPROVED:-}" == true ]] || exit 1
[[ "${SSH_HOST:-}" =~ ^[a-zA-Z0-9][a-zA-Z0-9.-]*$ ]] || exit 1
[[ "${SSH_USER:-}" == cd-tunnel ]] || exit 1
[[ "${API_TLS_NAME:-}" =~ ^[a-zA-Z0-9][a-zA-Z0-9.-]*$ ]] || exit 1
# Validate URL without shell interpolation or credentials, redirects or proxy bypass of trust.
python3 - <<'PY'
import os
from urllib.parse import urlsplit
url = urlsplit(os.environ.get('APP_URL', ''))
if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.query or url.fragment or url.path != '/':
    raise SystemExit('Invalid application URL; expected an approved root URL without credentials')
PY
for name in SSH_PRIVATE_KEY SSH_KNOWN_HOSTS KUBE_CA_B64 KUBE_TOKEN; do
  [[ -n "${!name:-}" ]] || { echo "Missing credential: $name"; exit 1; }
done
umask 077
work_dir="$(mktemp -d)"
tunnel_pid=''
cleanup() {
  if [[ -n "$tunnel_pid" ]]; then
    kill "$tunnel_pid" 2>/dev/null || true
    wait "$tunnel_pid" 2>/dev/null || true
  fi
  rm -rf -- "$work_dir"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
export CD_WORK_DIR="$work_dir" KUBECONFIG="$work_dir/kubeconfig"
python3 - <<'PY'
import base64, json, os, socket
from pathlib import Path
with socket.socket() as s:
    s.bind(('127.0.0.1', 17643))
root = Path(os.environ['CD_WORK_DIR'])
base64.b64decode(os.environ['KUBE_CA_B64'], validate=True)
(root / 'key').write_text(os.environ['SSH_PRIVATE_KEY'] + '\n')
(root / 'known_hosts').write_text(os.environ['SSH_KNOWN_HOSTS'] + '\n')
config = {'apiVersion':'v1','kind':'Config',
 'clusters':[{'name':'cd','cluster':{'server':'https://127.0.0.1:17643',
 'certificate-authority-data':os.environ['KUBE_CA_B64'],'tls-server-name':os.environ['API_TLS_NAME']}}],
 'users':[{'name':'deployer','user':{'token':os.environ['KUBE_TOKEN']}}],
 'contexts':[{'name':'cd','context':{'cluster':'cd','user':'deployer','namespace':'default'}}],
 'current-context':'cd'}
(root / 'kubeconfig').write_text(json.dumps(config))
PY
unset SSH_PRIVATE_KEY SSH_KNOWN_HOSTS KUBE_CA_B64 KUBE_TOKEN
export NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost
ssh -F /dev/null -N -T -i "$work_dir/key" \
  -o BatchMode=yes -o IdentitiesOnly=yes -o IdentityAgent=none \
  -o ForwardAgent=no -o StrictHostKeyChecking=yes \
  -o "UserKnownHostsFile=$work_dir/known_hosts" -o GlobalKnownHostsFile=/dev/null \
  -o ExitOnForwardFailure=yes -o ConnectTimeout=15 \
  -o ServerAliveInterval=15 -o ServerAliveCountMax=3 \
  -L 127.0.0.1:17643:127.0.0.1:6443 "$SSH_USER@$SSH_HOST" &
tunnel_pid=$!
# Bounded connection readiness only; never repeat a mutation.
ready=false
for attempt in {1..10}; do
  kill -0 "$tunnel_pid" 2>/dev/null || { echo 'Tunnel exited'; exit 1; }
  if kubectl --request-timeout=5s -n default get deployment diploma-app -o name >/dev/null 2>&1; then
    ready=true
    break
  fi
  sleep 1
done
[[ "$ready" == true ]] || { echo 'API identity/access gate failed'; exit 1; }
image="cr.yandex/crpb1oihnpa2uai8m3mp/netology-diploma-app@$IMAGE_DIGEST"
kubectl --request-timeout=30s -n default set image deployment/diploma-app "diploma-app=$image"
kubectl --request-timeout=30s -n default rollout status deployment/diploma-app --timeout=180s
kubectl --request-timeout=15s -n default get deployment diploma-app -o json > "$work_dir/deployment.json"
python3 - <<'PY'
import json, os
from pathlib import Path
d = json.loads((Path(os.environ['CD_WORK_DIR']) / 'deployment.json').read_text())
expected = 'cr.yandex/crpb1oihnpa2uai8m3mp/netology-diploma-app@' + os.environ['IMAGE_DIGEST']
c = [c for c in d['spec']['template']['spec']['containers'] if c['name'] == 'diploma-app']
s = d.get('status', {})
n = d['spec'].get('replicas', 1)
if len(c) != 1 or c[0]['image'] != expected or n < 1 or s.get('observedGeneration', 0) < d['metadata']['generation'] or any(s.get(k, 0) != n for k in ('updatedReplicas', 'readyReplicas', 'availableReplicas', 'replicas')):
    raise SystemExit('Deployment digest/readiness verification failed')
PY
curl --fail --silent --show-error --noproxy '*' --proto '=http,https' --tlsv1.2 \
  --connect-timeout 5 --max-time 15 --max-filesize 65536 \
  --output "$work_dir/body.html" --write-out '%{http_code}' "$APP_URL" > "$work_dir/status"
[[ "$(cat "$work_dir/status")" == 200 ]] || { echo 'HTTP status mismatch'; exit 1; }
python3 - <<'PY'
import os
from pathlib import Path
from ci.smoke import check_html
check_html((Path(os.environ['CD_WORK_DIR']) / 'body.html').read_text(), os.environ['APP_VERSION'])
print('Rollout/digest/HTTP/version PASS')
PY
