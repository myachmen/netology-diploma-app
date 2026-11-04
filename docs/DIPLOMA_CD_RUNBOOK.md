# Минимальный CI/CD диплома — подготовка №142

**Сейчас: CODE READY / CD DISABLED.** Ветка `feature/diploma-minimal-cd-142`
происходит от prep140 `c67945fcda701d188c1e42d5a856b51cf9d7773d`.
В №142 разрешены только код, offline checks, test-only CI и публикация ветки.
Никаких registry/SSH/Kubernetes/cloud/settings/credential действий и merge.
Описанные ниже действия с работающей системой — проект следующего согласования.

## Что делает workflow

| Событие после интеграции | Действие |
|---|---|
| Push обычной ветки приложения | Tests → Docker build/push в существующий YCR: `sha-<40hex commit>`; для main также `latest` |
| Push именно подготовительной ветки №142 | Только tests, **без build/push/deploy** — исключение для безопасной публикации этого задания |
| Pull request в main | Только tests, без Secrets и deployment |
| Новый tag `vX.Y.Z` | Tests → проверить tag=ci/VERSION, HTML version, checkout SHA и ancestry main → build/push `X.Y.Z` и `sha-SHA` с OCI version/revision labels → deploy digest **этого же run** → rollout/HTTP smoke |

Deploy пока содержит **один эффективный выключатель `false &&`**.
После отдельного разрешения activation diff удаляет только этот literal;
tests принимают как disabled, так и корректный release profile. Нет обязательных
CD flags, environment/reviewer, APH-CD/1, policy token/observer, GitHub policy API
reads или artifact admission. APH/1.1 для обмена заданиями остаётся неизменным.
Старый механизм140 удалён из текущего кода, но сохраняется в Git history.
Workflow не имеет dispatch и не развёртывает branch/PR; attempt>1 не deploy.

Тесты — offline HTML/Docker-context contract и release/security tests, не реальная
сборка контейнера. При будущем разрешённом push Docker Buildx выполняет настоящий
build/push. Registry выбран один: **Yandex Container Registry**; он уже используется
работающим приложением. Дополнительный Docker Hub login/publish для диплома не нужен.

## Существующие ресурсы и точный scope

- App repo: `myachmen/netology-diploma-app`, целевой main; подготовка только новая
  feature-ветка. Main сейчас прежний; реальная интеграция ещё не выполнена.
- Image: `cr.yandex/crpb1oihnpa2uai8m3mp/netology-diploma-app`.
  Registry и pull access уже использовались исторически; текущая работоспособность
  и права publisher/puller в142 не проверялись. IAM и pull Secret не менять.
- Existing Kubernetes v1.33.7: namespace `default`, Deployment/container
  `diploma-app`, две реплики. Service/Ingress/Traefik/ALB остаются существующими.
  CD меняет только image одного контейнера; не выполняет apply Helm/manifests.
- Existing control-plane `k8s-control-1`: SSH22 → только `127.0.0.1:6443` API.
  Runner слушает только `127.0.0.1:17643`. Public endpoints и SAN здесь не публикуются.
- Dedicated identity: SSH `cd-tunnel`, Kubernetes SA/Role/RoleBinding
  `default/github-actions-deployer` из
  [RBAC139](https://github.com/myachmen/netology-devops-from-zero-homeworks/blob/8f57aebf85b088279a9314735d5fb31474c58cb8/kubernetes/cd/rbac.yaml).
  Это **draft**, его наличие в Git не доказывает effective cluster grants.
- [SSH role](https://github.com/myachmen/netology-devops-from-zero-homeworks/blob/6c80ea5f1e099c3199c2896562c23bebda04117b/ansible/roles/cd_tunnel/README.md)
  — review-only, не activation playbook. Не применять её как готовый account setup.

GitHub-hosted ephemeral runner через существующий SSH — минимальный кандидат,
но current identity/trust/route/CA/RBAC UNKNOWN. Admin kubeconfig, ключ ubuntu,
Terraform/IAM identity не используются как shortcut. Если имеющийся маршрут
небезопасен/недоступен — STOP. Один простой альтернативный вариант: доверенный
оператор на существующей management машине выполняет тот же scoped digest deploy.
Это не доказывает автоматический tag CD; автоматизацию через private ephemeral
runner нужно согласовать отдельно, а не устанавливать постоянный admin runner.

## Минимальные GitHub Secrets и variables — значения не читать в логи

Для этого учебного workflow достаточно repository scope; environment/required
reviewers/branch protection — желательные controls, **не обязательные gates**.
Владельцы repo write считаются доверенными: они могут менять privileged workflow.
Токены/SSH ключи не передаются PR job, checkout не сохраняет credentials.

| Имя | Назначение / минимальные права |
|---|---|
| Secret `YC_SA_KEY_JSON` | Уже используемое имя build credential, доступность/права UNKNOWN. Только publish в существующий app registry (`container-registry.images.pusher` на нужном registry либо эквивалентный достаточный existing scope), не cloud admin. Ничего не выпускать и не менять IAM в142 |
| Secret `CD_SSH_PRIVATE_KEY` | Dedicated key только пользователя cd-tunnel; не ключ администратора. Если его нет — отдельное явное согласие на создание/хранение/ротацию |
| Secret `CD_SSH_KNOWN_HOSTS` | Только подтверждённая привязка current control-plane host→host key; StrictHostKeyChecking=yes, не accept-new, не global known_hosts |
| Secret `CD_KUBE_CA_B64` | Existing доверенная CA API, base64; integrity важна, не создавать новую CA или отключать TLS |
| Secret `CD_KUBE_TOKEN` | Short-lived scoped SA token; не admin client certificate/kubeconfig, не вечный legacy token Secret |
| Variable `CD_SSH_HOST` | Подтверждённый control-plane SSH endpoint, не новая VM/порт/SG |
| Variable `CD_SSH_USER` | Ровно `cd-tunnel` |
| Variable `CD_API_TLS_NAME` | Existing подтверждённый API SAN; при loopback connection сохраняется проверка CA/имени |
| Variable `CD_APP_URL` | Existing ALB URL `http(s)://host[:port]/`, без credentials/query/fragment. HTTP допустим оригиналом диплома; HTTPS не отключает TLS verification |

`GITHUB_TOKEN` — только `contents: read`. GitHub read-policy token, App private
key, Secrets write permissions или IAM credentials deploy job не нужны.
Значения не извлекать из GitHub для проверки; owner выполняет provisioning по
отдельному разрешению. Не выводить env, raw kubeconfig/Deployment, `set -x`/SSH debug.
Не upload рабочий каталог deploy job: он содержит credential files/runtime data.

## Минимальный SSH и Kubernetes доступ — на отдельное согласование

SSH: отдельный непривилегированный cd-tunnel, без sudo/password/exec/PTY/SFTP,
agent/X11/reverse/streamlocal/tunnel forwarding. Разрешён local TCP forwarding
только `PermitOpen 127.0.0.1:6443`, `MaxSessions 0`, publickey-only, root-owned
keyfile без user write; ограничение также на самом key. Перед одним разрешённым
sshd reload проверить **полную** конфигурацию `sshd -t/-T` с Include/Match/PAM и
сохранением ubuntu access. Наличие шаблона или local listener не заменяет
effective config и negative channel tests. SG/firewall/public API не расширять.

Kubernetes: SA automount=false, Role/Binding только default, единственное правило:
`apps/deployments`, `resourceNames: [diploma-app]`, `get,patch,list,watch`.
Для list/watch нужен field-selector `metadata.name=diploma-app`; закреплённый
kubectl rollout status использует его. Нет Secrets/Pods/exec/proxy/nodes/RBAC/token
write permissions. Перед release отдельно подтвердить actual get/filtered
list/watch, can-i patch и отрицательную authorization matrix для другого
имени/namespace/Secret/exec/token. Для deny тестов использовать can-i/SSAR,
не читать настоящий Secret. Не давать CI impersonation/cluster-admin для теста.

RBAC patch не ограничивает JSON поля: украденный token может изменить весь
Pod template named Deployment. Для учебного проекта требуется принятие этого
остаточного риска, а не заявление «image-only RBAC». Наш клиент делает один
image replace с atomic preconditions, но это не серверный admission controller.

Scoped TokenRequest выполняет уполномоченный operator, не сам deployer. Практично
одно release окно≤45min и token с actual server TTL порядка60min, выданный перед
окном; проверить audience/API authentication и достаточный остаток на build+deploy
с запасом. Requested TTL не гарантирует server TTL. Значение хранить защищённо и
не логировать. Истёкший credential → FAIL/STOP, не admin fallback/auto reissue.
Отзыв временного доступа/Secret cleanup согласовать заранее; token expiration
не откатывает уже принятый image patch.

## Как получить первый live release — минимальное следующее согласование

**В142 ни один из этих runtime/credential/settings/merge/tag шагов не выполняется.**

| Необходимое действие | Сейчас | Оператор / разрешение | Риск и verification |
|---|---|---|---|
| Короткий current identity/strict host-key/TLS и scoped access gate | UNKNOWN, historical health134 не current | Infrastructure owner; bounded read-only probes и, если нужен, один собственный временный forwarding | Mismatch/новый network scope → STOP; existing API readyz/get, отрицательные auth tests, cleanup |
| Только restricted SSH account/key + SA/Role/RoleBinding выше, если ещё отсутствуют | Git drafts, effective UNKNOWN | VM/K8s owner; явно согласованные guest/RBAC writes и dedicated credential issuance; без cloud/IAM writes | Сохранить admin recovery; sshd validation/negative channel tests; effective RBAC без extra grants |
| Названные Secrets/vars и scoped token | UNKNOWN; имена не значения | Repo/credential owners; explicit provisioning и cleanup scope | Не reuse admin material, actual authentication/TTL, no logs |
| Reviewed main integration + version HTML/ci/VERSION, например1.0.2 | Main старый, source prep1.0.0 | Maintainer + пользователь разрешают merge и registry build/push side effect | Offline tests и разрешённый main CI success; новый commit SHA, labels/tags/digest |
| Activation + один новый release tag | Literal false сейчас; v1.0.0/v1.0.1 уже существовали по141 | Пользователь утверждает удаление только false, exact main SHA/version и ОДИН tag/run; maintainer обычный tag push, no force | Непосредственно проверить свободное имя Git/registry, не перемещать старые tags. Tag SHA/version/main ancestry → test/build/digest/deploy |

Branch protection/environment/reviewer/APh policy observer не добавлять как
обязательные препятствия. При неопределённом результате mutation не rerun job
или весь workflow. Разрешение на повтор/repair/rollback — отдельное решение.
Доступ и один release можно согласовать в одном функциональном задании с этими
точными scope/STOP/cleanup; не требуется отдельная цепочка production-grade задач.

## Исполнение release и проверки

1. До tag: существующие кластер/app/route healthy, scoped auth/strict SSH/TLS PASS,
   две app replicas, предыдущий image и для возможного rollback **реальный прежний
   immutable digest** зафиксирован уполномоченным оператором без secrets. При
   старом tagged image не считать registry tag доказательством Pod imageID.
2. Version в ci/VERSION и HTML должны совпадать, candidate v1.0.2 не создавать
   до отдельного разрешения. Reviewed activation commit должен быть в main.
3. Обычный push commit выполняет test/build/push; tag vVERSION выполняет то же
   с version tag/OCI labels. Digest берётся из build outputs этого же run, а не
   input/mutable tag. Pipeline не имеет произвольного deploy dispatch.
4. Скрипт проверяет event/repo/tag/version/SHA/run/attempt/build/digest и наличие
   конфигурации до network/credential files. Проверка формата не подтверждает
   реальные права/TTL; это делает короткий разрешённый access gate.
5. После strict SSH forwarding — bounded readiness GET; fresh Deployment GET,
   valid existing image repo/container/replicas/ready; JSON patch: tests UID/RV/
   generation/replicas/container/old image, **один replace immutable digest**.
   Drift между GET/patch даёт конфликт, не автоматический второй patch.
6. Проверяются exact reply UID/generation/spec, rollout≤180s, final generation
   и2 updated/ready/available replicas. Затем public app HTTP200 и exact expected
   HTML/version. HTTP endpoint не получает kube credentials. Никаких automatic
   restart/rollback/repair. Job≤10min, API/SSH/HTTP timeouts ограничены.
7. При FAIL/timeout/unknown outcome остановиться, read-only выяснить фактический
   результат. Перед повтором/rollback необходимо решение пользователя.
   EXIT/TERM cleanup закрывает только собственный tunnel/tempdir; SIGKILL/runner
   loss не гарантирует trap. Подтвердить освобождение17643 и expiry/revoke
   временных credentials по согласованному плану.

### Rollback — только вручную после отдельного разрешения

Не выполнять `rollout undo` вслепую и не выбирать mutable tag. Сначала read-only
проверить actual current UID/generation/spec; подготовить guarded patch на
сохранённый `YCR_IMAGE@sha256:PREVIOUS_DIGEST`, затем один согласованный patch и
тот же rollout/HTTP-version postcheck. Если прежний digest или write outcome
UNKNOWN — STOP, не угадывать. RBAC grant/credential cleanup отдельно от rollback
приложения; не удалять app, Secrets/SA/Binding автоматически.

## Offline checks и evidence диплома

```bash
PYTHONDONTWRITEBYTECODE=1 python3 ci/smoke.py
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
actionlint .github/workflows/docker-publish.yml
bash -n ci/deploy.sh
```

Тесты проверяют current/next version, main/feature/tag metadata, event/job routing,
PR/fork/dispatch denial, отсутствие credentials до external commands, exact digest,
atomic conflict и postchecks. Synthetic credentials не годятся для реального
подключения. Offline checks не заявлять как live build/deploy.

Для сдачи сохранить ссылки/скриншоты **реальных** main build и tag run: immutable
commit/tag, tests/build success, YCR version/revision labels и digest, successful
deploy/rollout/HTTP+new version. Не публиковать private endpoints/keys/tokens/
raw runtime JSON. CI UI доступен по HTTPS GitHub Actions. В142 test-only run
закрывает лишь подготовку кода; end-to-end CD остаётся LIVE UNVERIFIED.

Оригинал: [диплом Нетологии](https://github.com/netology-code/devops-diplom-yandexcloud/blob/cd2a878c96cf9852c5226be6f9bba4d221cfe634/README.md).
Terraform pipeline/Atlantis/Terraform Cloud и итоговые evidence сдачи — отдельные
обязательные этапы, этим приложением не реализованы. Никакого автоматического №143.
