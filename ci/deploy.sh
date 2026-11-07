#!/usr/bin/env bash
# Release tags only; one mutation, bounded read-only checks, no rollback.
set +x
set -euo pipefail
cd "$(dirname "$0")/.."
umask 077
# Fail before key/config files, SSH or kubectl when provenance/config is missing.
stage=release_gate
trap 'rc=$?; printf "CD FAIL stage=%s exit=%s; STOP, no retry/rollback\n" "$stage" "$rc" >&2' ERR
python3 -m ci.release --credentials
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
python3 - <<'PYCONFIG'
import json, os, socket
from pathlib import Path
with socket.socket() as s:
    s.bind(('127.0.0.1', 17643))
root = Path(os.environ['CD_WORK_DIR'])
(root / 'key').write_text(os.environ['SSH_PRIVATE_KEY'] + '\n')
(root / 'known_hosts').write_text(os.environ['SSH_KNOWN_HOSTS'] + '\n')
config = {'apiVersion':'v1','kind':'Config',
 'clusters':[{'name':'cd','cluster':{'server':'https://127.0.0.1:17643',
 'certificate-authority-data':os.environ['KUBE_CA_B64'],'tls-server-name':os.environ['API_TLS_NAME']}}],
 'users':[{'name':'deployer','user':{'token':os.environ['KUBE_TOKEN']}}],
 'contexts':[{'name':'cd','context':{'cluster':'cd','user':'deployer','namespace':'default'}}],
 'current-context':'cd'}
(root / 'kubeconfig').write_text(json.dumps(config))
PYCONFIG
unset SSH_PRIVATE_KEY SSH_KNOWN_HOSTS KUBE_CA_B64 KUBE_TOKEN
export NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost
stage=ssh_api_access
ssh -F /dev/null -N -T -i "$work_dir/key" \
  -o BatchMode=yes -o IdentitiesOnly=yes -o IdentityAgent=none \
  -o ForwardAgent=no -o StrictHostKeyChecking=yes \
  -o "UserKnownHostsFile=$work_dir/known_hosts" -o GlobalKnownHostsFile=/dev/null \
  -o ExitOnForwardFailure=yes -o ConnectTimeout=15 \
  -o ServerAliveInterval=15 -o ServerAliveCountMax=3 \
  -L 127.0.0.1:17643:127.0.0.1:6443 "$SSH_USER@$SSH_HOST" 2> "$work_dir/ssh-error" &
tunnel_pid=$!
# Bounded read-only readiness polling, never repeat a mutation.
ready=false
for attempt in {1..10}; do
  kill -0 "$tunnel_pid" 2>/dev/null || { echo 'Tunnel exited'; exit 1; }
  if kubectl --request-timeout=5s -n default get deployment diploma-app -o name >/dev/null 2>&1; then
    ready=true
    break
  fi
  sleep 1
done
[[ "$ready" == true ]] || { echo 'API access failed'; exit 1; }
stage=baseline
kubectl --request-timeout=15s -n default get deployment diploma-app -o json > "$work_dir/baseline.json" 2> "$work_dir/api-error"
python3 -m ci.deployment patch "$work_dir/baseline.json" "$work_dir/expectation.json" \
  --digest "$IMAGE_DIGEST" --patch-output "$work_dir/patch.json"
stage=guarded_patch
# One atomic mutation with UID/RV/generation/image tests. Unknown outcome => STOP.
kubectl --request-timeout=30s -n default patch deployment diploma-app --type=json \
  --patch-file "$work_dir/patch.json" -o json > "$work_dir/reply.json" 2> "$work_dir/api-error"
python3 -m ci.deployment reply "$work_dir/reply.json" "$work_dir/expectation.json"
stage=rollout
kubectl --request-timeout=30s -n default rollout status deployment/diploma-app --timeout=180s > "$work_dir/rollout" 2> "$work_dir/api-error"
kubectl --request-timeout=15s -n default get deployment diploma-app -o json > "$work_dir/deployment.json" 2> "$work_dir/api-error"
python3 -m ci.deployment final "$work_dir/deployment.json" "$work_dir/expectation.json"
stage=http_smoke
python3 -m ci.http_smoke
printf 'CD PASS tag=%s sha=%s digest=%s version=%s; rollout=ready HTTP=200\n' \
  "$SOURCE_TAG" "$SOURCE_SHA" "$IMAGE_DIGEST" "$APP_VERSION"
if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  printf 'Tag `%s` / commit `%s` / digest `%s` / version `%s`\n\nRollout Ready; public HTTP 200 and exact HTML version verified.\n' \
    "$SOURCE_TAG" "$SOURCE_SHA" "$IMAGE_DIGEST" "$APP_VERSION" >> "$GITHUB_STEP_SUMMARY"
fi
