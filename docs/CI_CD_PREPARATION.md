# Подготовка CI/CD — задание №137, APH/1.1

Это подготовительный профиль, **CD отключён литералом `false &&`**. Наличие этого
файла, environment name или переменных не разрешает deployment. Ветка
`feature/diploma-ci-cd-prep-137` не должна сливаться в main без отдельного решения.
Implementation остаётся `6c80ea5f1e099c3199c2896562c23bebda04117b`.

## Проверяемый результат подготовки

Локально: `PYTHONDONTWRITEBYTECODE=1 python3 ci/smoke.py`, затем
`PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v`,
`actionlint .github/workflows/docker-publish.yml`, `bash -n ci/deploy.sh`.
Тесты не обращаются к Docker daemon, registry, production или облаку. Проверяются
HTML title/h1/readiness/version, три разрешённые Dockerfile инструкции и узкий
build context. `.dockerignore` разрешает только Dockerfile/index.html: tests,
workflow, Git и потенциальные локальные credentials в образ не копируются.
Изменение версии требует согласованной правки `ci/VERSION`, HTML и release tag.

Negative fixtures: неверные version/h1/readiness, `COPY .`, раскрытый build context
обязательно завершают CLI кодом1. Release contract отвергает чужой repository,
PR/dispatch/branch, несовпадение sha/tag/run/version, rerun, failed build,
отсутствующие поля и tag вместо digest. Stub ssh/kubectl/curl подтверждают, что
недоверенное событие отклоняется до внешних команд и credential handling.
Workflow regression проверяет privileged gates и 30 сочетаний repository/event/ref.
Это не доказательство работоспособности SSH/Kubernetes/HTTP в runtime.

Подготовительный push запускает только test job без secrets/environment. PR на
main также выполняет только tests. `pull_request_target`/`workflow_run` отсутствуют.
Build/push зависит от tests и допускает только push в main или tag этого repository;
dispatch теперь только тестовый. Registry login не выполняется на prep branch/PR.
В main ничего не меняется до отдельного merge. Прежний workflow main сохраняется.

## Архитектура будущего deployment и границы доверия

Путь: GitHub-hosted ephemeral runner → существующий SSH TCP22 control-plane →
loopback forwarding → Kubernetes API, TLS с CA/SAN → namespace default,
Deployment diploma-app. Публично открывать API6443, добавлять SG/IP rules,
платные VM/bastion или постоянный self-hosted runner не предлагается.
Pinned implementation `terraform/infrastructure/security.tf` описывает публичный
SSH22; это существующий риск, не разрешение расширять правила. Actual runtime
доступность/соответствие SG не проверялись в137. При невозможности доступа по
существующему маршруту STOP: не открывать новые порты/диапазоны автоматически.
Вариант с меньшим blast radius для отдельного решения — ограниченный ручной
deployment с уже доверенной управляющей машины; это не доказанный автоматический CD.

На сервере потребуется отдельно согласованный dedicated `cd-tunnel`: без sudo,
пароля, shell/exec/PTY/SFTP, agent/X11, reverse forwarding; только local forwarding
к loopback6443. Нужны эффективные sshd -t/-T и отрицательные тесты реальных каналов,
без изменений ubuntu/его административного доступа. Существующая роль
`ansible/roles/cd_tunnel` готовит лишь review candidates, НЕ активирует доступ.
Не выдавать CI административный SSH ключ. Server account/key activation — отдельные
разрешённые операции, не часть137. Фоновый SSH в скрипте — только будущий runner;
локально в137 этот путь не исполняется.

Runner слушает только loopback17643, SSH -N -T с BatchMode, IdentitiesOnly,
IdentityAgent=none, ForwardAgent=no, StrictHostKeyChecking=yes; отдельный
проверенный known_hosts, без ssh-keyscan как доверия и без global known_hosts.
Host keys/VM identity подтверждаются отдельно из независимого baseline перед
активацией; реальный mismatch — STOP, не удаление записи/StrictHostKeyChecking=no.

Kubeconfig собирается в ephemeral0700 каталоге при umask077 из CA+короткоживущего
scoped token. Только loopback URL с `tls-server-name`, обязательная CA/SAN TLS
проверка. Не использовать admin.conf, существующий административный project
kubeconfig, skip TLS, client private key или exec auth plugin. API proxy subresources
не нужны. Cleanup убивает/ожидает свой SSH процесс и удаляет только свой каталог;
при SIGKILL cleanup не гарантирован, поэтому нужен ephemeral runner.

## Минимальные Kubernetes права и остаточный blast radius

Планируемая ServiceAccount github-actions-deployer в default: только
`get`, `patch`, `watch` на apps/deployments с resourceNames=[diploma-app].
`kubectl set image` читает/patch-ит один Deployment; rollout status использует get/watch
того же имени; HTTP проверяется через существующий ALB, без pods/exec/portforward,
services/proxy, Secrets и Node access. Точная совместимость kubectl watch с
resourceNames требует будущего positive/negative RBAC test; нельзя молча расширить
namespace-wide list/watch при отказе. API readiness здесь проверяет get Deployment,
а не cluster-wide /readyz.

Существующий draft `kubernetes/cd/rbac.yaml` шире: update Deployment и list/watch
всех deployments, replicasets/pods namespace. Его НЕ применять как есть. До активации
нужен согласованный минимальный Role/Binding и проверка effective rights/отсутствия
дополнительных bindings. В137 draft не менялся. Даже named Deployment patch может
менять другие поля Pod template, а не только image: обычный RBAC не ограничивает
JSON fields. Риск включает полномочия приложения, mount/Pod-template изменения.
Требуется предметное принятие этого риска либо отдельно согласованная admission
политика; нельзя называть это строго image-only identity без такой политики.

## Provenance и последовательность будущего запуска

1. Только доверенный push SemVer tag vX.Y.Z в основном repository. Tag/version
   обязаны совпасть с ci/VERSION/HTML. Commit должен входить в историю origin/main.
   Это ancestry check, не доказательство code review; branch/tag protections пока
   не настроены этим заданием. Мутации tag и конкурентные релизы должны запрещаться
   организационно/правилами до активации, а не только шаблоном v*.
2. Тот же run: tests → build/push; outputs digest/sha/tag/run/version поступают
   только от build job, а не пользовательского digest input или внешнего artifact.
   OCI labels revision/version/source/run-id и sha tag помогают расследованию.
   Это same-run provenance, НЕ подписанная attestation/SLSA; build action и registry
   остаются trust boundary. Base image mutable; action major tags унаследованы.
   До активации рассмотреть pinning action SHAs и registry/base-image provenance.
3. Environment diploma-production: required reviewers, prevent self-review,
   запрет admin bypass и только согласованные release tags. После отдельного
   разрешения и настройки approvals — минимальный доступ и свежие credentials.
   Проверить доступность этих функций для плана/visibility repository. Само
   имя environment в YAML не создаёт reviewer policy и не является защитой.
4. Только после review убрать literal false в отдельном согласованном изменении;
   разрешить CD_ENABLED/CD_SSH_TUNNEL_APPROVED и один конкретный run. Не использовать
   workflow_dispatch для deployment. run_attempt>1 отклоняется; никаких автоматических
   повторов всего job/playbook, rollback/repair или альтернативных путей.
5. Установить проверенный kubectl1.33.7 (HTTPS+SHA256), проверить release contract
   до чтения credential env; создать временный SSH listener/проверить get Deployment.
   До мутации проверить актуальные identity/trust, Pod template/RBAC и существующий
   app rollback digest отдельным утверждённым preflight.
6. Ровно один `kubectl set image` с YCR@sha256; затем rollout status timeout180s,
   get exact template image + observedGeneration + updated/ready/available/total
   replicas, HTTP200 и expected HTML/version через согласованный existing root URL.
   Polling/readiness не является повторной мутацией. Job timeout10min; запросыAPI
   ограничены5/15/30s, HTTP connect5/total15s, без redirect/retry/TLS bypass. HTTP
   допустим по заданию диплома, но сам не удостоверяет сервер криптографически;
   при HTTPS выполняется обычная CA/hostname проверка. Version HTTP + image template
   вместе сильнее старого HTTP200, но это не проверка фактического runtime imageID
   каждого Pod; она потребует отдельно согласованного узкого read scope.
7. Зафиксировать tag/commit/run/attempt, build result/digest, Deployment generation,
   rollout/HTTP result, sanitized timings и cleanup. Ни токенов/ключей, ни raw
   kubeconfig/env/SSH debug. Ошибка/timeout/неопределённый outcome — STOP и read-only
   reconciliation, никаких повторных mutation/rollback по умолчанию.

## Checklist отдельного разрешения и credentials lifecycle

- Владелец repository/user утверждает diff/merge, branch иtag protections, pinned
  actions, конкретный release commit/tag и отсутствие unreviewed workflow code.
  Только contents:read GITHUB_TOKEN; id-token/packages-write/admin permissions
  не запрашиваются. PR не получает deployment/registry secrets.
- Администратор Kubernetes отдельно утверждает минимальные Role/Binding/SA,
  отрицательные проверки Secret/других Deployment/namespace и принятый patch risk.
- Администратор SSH отдельно утверждает dedicated user/restricted key/sshd checks,
  independent host-key pinning и сохранение admin access. Ни admin key reuse,
  ни sudo для CD. Если требуется SG/API/public-network change — STOP/новый дизайн.
- Secrets environment (только имена): CD_SSH_PRIVATE_KEY, CD_SSH_KNOWN_HOSTS,
  CD_KUBE_CA_B64, CD_KUBE_TOKEN. CA/known_hosts не секреты криптографически, но их
  целостность критична. Variables: CD_SSH_HOST, CD_SSH_USER=cd-tunnel,
  CD_API_TLS_NAME, CD_APP_URL. CD_ENABLED/CD_SSH_TUNNEL_APPROVED задаются отдельно
  как repository variables для job-level if (environment variables ещё недоступны
  на этой стадии); сами флаги не являются approval. Значений вGit нет.
  Существующие build secrets DOCKERHUB_USERNAME/DOCKERHUB_TOKEN/YC_SA_KEY_JSON
  не читались/не менялись; их privilege/rotation — отдельная проверка перед merge.
- TokenRequest с коротким согласованным TTL, audience API server; не создавать
  постоянный legacy SA-token Secret. Выдачу/запись secret разрешает пользователь
  отдельно; TTL покрывает approval delay+10min job+skew. При истечении STOP, не
  использовать admin fallback. SSH key иregistry token требуют ротации/revocation
  владельцем, окружение/runner не должно сохранять caches/artifacts сcredentials.
- После одного approved run удалить/отозвать временный token/SSH доступ по
  согласованному cleanup scope, закрыть tunnel и проверить локальный listener.
  GitHub masking не заменяет запрет set -x/env dumps/debug logs.
- Минимальный rollback plan: заранее записать доверенный previous immutable digest
  и readiness baseline. При сбое автоматического rollback НЕТ; сначала остановиться,
  сохранить sanitized evidence, отдельно получить согласие на одну targeted image
  patch и проверку. Не делать reset/Helm rollback/Kubespray/cloud changes.

## Что остаётся UNKNOWN

Фактические effective SSH/RBAC, текущие identity/SG/TLS, environment reviewers,
credential availability/TTL, GitHub-hosted reachability, build/tag run новой версии,
реальный deployment/HTTP и digest каждого runtime Pod в137 не проверялись.
CD end-to-end не работает и не заявляется работающим. Подготовительные checks
не заменяют будущего отдельного разрешения на runtime mutations.

Официальные источники security policy:
[GitHub environments](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments),
[environment management](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments),
[untrusted workflow security](https://docs.github.com/en/actions/reference/security/secure-use).
Действующие live facts — только исторические отчёты128/130–135 в приватном контексте;
ссылки на приватные endpoints/credentials здесь не публикуются.
