# План ограниченного CD-доступа — только для отдельного согласования

№140 разрешает подготовку кода и этого плана, **не выполнение шагов**.
CD остаётся false && / PREPARATION. Ни одного live SSH/Kubernetes/Cloud запроса,
settings/Secret/credential write, merge или tag этот документ не разрешает.

## Архитектура и trust boundary

Основной кандидат: GitHub-hosted ephemeral runner → existing SSH22 control-plane
→ restricted user cd-tunnel → loopback API с существующей CA/SAN → scoped SA
default/github-actions-deployer → named Deployment diploma-app. Никаких новых
VM/SG/public API/портов/платных ресурсов. Tracked HCL раньше допускал публичныйSSH22;
это HISTORICAL/code evidence, не доказательство current reachability.

Без публичного SSH: отдельно согласованный оператор на уже доверенной управляющей
машине может выполнить controlled deploy после admission. Это меньше внешних
principals, но не автоматический GitHub CD. Альтернатива CI — изолированный
ephemeral runner на существующей private connectivity; требует отдельного
OS/изоляционного scope. Не ставить persistent PR runner рядом с admin credentials
как shortcut. При недоступности существующего маршрута — STOP/выбор архитектуры,
не открытие новой сети.

Trusted computing base: GitHub API/TLS, configured reviewer и repository admin,
reviewed workflow/ci/tests в approved main commit, immutable-pinned Actions,
trusted builder, ephemeral runner, независимый runtime preflight. Механизм не
защищает от злонамеренного reviewer/admin/скомпрометированного builder. Secrets
и workflow код должны быть изолированы от PR/untrusted jobs.

## Чтение GitHub policy — минимальные permissions

Verifier GET-only; policy token ограничен одним repository1440700475.

| API family | Данные | Fine-grained read permission |
|---|---|---|
| repository/ref/tag/compare | Repository ID, tag→SHA, main ancestry | Metadata:read / Contents:read |
| actions/runs, attempt jobs, approvals | Event/attempt/actors, test/build success, reviewer record | Actions:read |
| actions/artifacts | Same-run manifest metadata и ZIP | Actions:read |
| environments/branch policies | Reviewer IDs, prevent-self-review, exact tag policy | Actions:read |
| branches/main/protection | Required review/check, admins/force/delete/bypass policy | Administration:read |
| repository rulesets | Active exact-tag update/delete restriction | Metadata:read; отдельно проверить bypass visibility |

GITHUB_TOKEN обычного job contents:read **не считается** достаточным для всех
policy endpoints. Будущий environment Secret CD_GITHUB_READ_TOKEN — узкий
GitHub App installation/user token с согласованным TTL, только read scopes;
его issuance/placement требуют отдельного согласования. На runner не нужен App
private key или право mint себе token. Не использовать classic repo/admin-write
PAT как fallback. Текущий workflow GITHUB_TOKEN permissions не расширяет.

GitHub документирует, что bypass_actors может быть скрыт без write access к
ruleset. Если approved read-only token не видит поле, production gate BLOCKED.
Не предполагать [] и не выдавать Administration:write. Нужна отдельная проверка
API visibility/роли или пересмотр способа policy evidence с пользователем.
can_admins_bypass и policy type также должны реально присутствовать; если API
версия/права не дают достоверный ответ — STOP с конкретным missing field.

HTTP401/403/404/429/5xx/timeout/malformed/truncated collections — fail-closed,
без retries и anonymous fallback. Подробнее — [GitHub branch protection](https://docs.github.com/en/rest/branches/branch-protection),
[rules](https://docs.github.com/en/rest/repos/rules), [workflow reviews](https://docs.github.com/en/rest/actions/workflow-runs#get-the-review-history-for-a-workflow-run),
[environments](https://docs.github.com/en/rest/deployments/environments).

## Exact будущие writes: owner, риск, gate

| Ресурс / write | Owner approval и precondition | Blast radius / проверка |
|---|---|---|
| App main protection: PR review≥1, stale review dismissal, last push independent approval, required test от GitHub Actions app15368 strict, admins enforced, force/delete off, explicit empty bypass allowances | Repository owner+пользователь, независимый reviewer назначен | Меняет merge authority; independently GET policy, без bypass для быстрого merge |
| Exact first-tag ruleset: target tag, include только approved refs/tags/vX.Y.Z, exclude[], active, update+deletion restriction, bypass[] | Repo owner+пользователь; tag creation остаётся отдельно контролируемой операцией | Не двигать/не удалять tags; API должен показать enforcement/conditions/bypass; read visibility иначе BLOCKED |
| Environment diploma-production: User reviewer, prevent_self_review, no admin bypass, custom selected policy ровно один tag | Repo owner+пользователь и независимый reviewer; не Team без дополнительного дизайна | Release authority; GET env/policies и future review history; отсутствует field→deny |
| Dedicated cd-tunnel OS account, root-owned /etc/ssh/authorized_keys/cd-tunnel и reviewed sshd Match integration | VM admin+пользователь, retained ubuntu access/консоль, current identity/host key known | Guest auth surface; без sudo/password/exec/PTY/SFTP/agent/X11/reverse/other destinations; полные sshd -t/-T до одного разрешённого reload |
| Только default/SA, Role, RoleBinding github-actions-deployer из draft139 | K8s admin+пользователь, review existing objects/bindings, принять patch residual risk | get/patch/list/watch только deployments.apps/diploma-app; actual positive/negative matrix до live mutation |
| Scoped TokenRequest для указанной SA/audience/TTL | K8s admin+пользователь, существующий доверенный TLS; CI не получает token-create permission | Короткий lifetime, actual server expiry; нет legacy permanent token Secret; revoke/expiry cleanup согласован |
| Environment secrets: CD_GITHUB_READ_TOKEN, CD_SSH_PRIVATE_KEY, CD_SSH_KNOWN_HOSTS, CD_KUBE_CA_B64, CD_KUBE_TOKEN | Владелец credentials+repo owner+пользователь; dedicated scope, rotation, no repository-level copies | Не выводить values, не admin key/kubeconfig/CA creation. Нужный отсутствующий key/token не создавать без отдельного scope |
| Endpoint/user/TLS/app variables; repository flags CD_ENABLED/CD_SSH_TUNNEL_APPROVED/CD_EXPECTED_REF/SHA/AUDIENCE | Repo owner+пользователь, exact approved release only; flags пока false | Job.if читает repo variables до env startup; флаги не являются proof и не заменяют API admission |
| Reviewed merge подготовительного workflow в main | Пользователь+repo owner после tests/review/protection | Main CI реально build/push latest/sha в registries; нужно разрешить этот side effect, не считать read-only |
| Version/HTML bump и reviewed ACTIVATION diff; затем один новый tag на exact SHA | Пользователь+repo owner, все предыдущие gates PASS; имя Git/registry свободно | Не менять существующие tags; старый tag сохраняет старый workflow; attempt>1 denied |
| Environment approval APH-CD/1 для exact run/artifact/digest | Настроенный независимый User reviewer после fresh runtime preflight и build evidence | [Формат](CD_APPROVAL_FORMAT.md); это новая разрешаемая запись review, сейчас не выполняется |
| Одна app JSON patch→rollout→HTTP; cleanup/disarm/revoke и cancel только approved run | Пользователь явно разрешает runtime phase и budgets/cleanup | Unknown outcome — STOP/read-only reconcile; no automatic rollback/repair/reset |

Implementation140 read-only. Изменять/применять draft139 или дорабатывать SSH роль
в140 запрещено. Если будущий plan требует нового кода implementation, получить
новый scope; не копировать review candidates прямо в effective sshd.

## SSH / trust / TLS

Не менять глобальный known_hosts. Публичный ключ для cd-tunnel — root-owned file,
пользователь не пишет его; режим/traversal должны действительно читаться sshd
(не копировать review0600 автоматически). Match placement зависит от действующих
Include/Match/PAM/AllowUsers; Match all не возвращает global context. До reload
проверить effective настройки для cd-tunnel **и ubuntu** с реальным peer context.
Ни nologin, ни ForceCommand сами по себе не доказывают правильный forwarding.

Effective restrictions: AuthenticationMethods publickey, password/keyboard-interactive
off, AllowTcpForwarding local, PermitOpen только127.0.0.1:6443, MaxSessions0,
AllowStreamLocalForwarding/PermitTunnel/PTY/X11/agent/userRC off; key restrict +
port-forwarding + permitopen + command=/bin/false. Реальные negative channel tests
должны проверять запрет назначения, не только наличие local listener.

Runner -N -T, -F /dev/null, BatchMode/IdentitiesOnly/IdentityAgent=none,
StrictHostKeyChecking=yes, отдельный known_hosts, loopback17643 bind. Host key
независимо связан с current control-plane identity/project baseline; mismatch
не лечить accept-new/удалением trust. Не исследовать090 logs без причины.

API существующей CA и SAN; loopback server + tls-server-name, без admin.conf,
client key, exec plugin, skip TLS. Credentials не извлекать вGit/argv/logs.
Public CA/known_hosts integrity защищается environment controls; ключи/сертификаты
не перевыпускать как shortcut. Точный SAN/current identity и доступность SSH
в140 UNKNOWN: нужны отдельно разрешённые probes.

## Kubernetes minimum и read-only preflight

SA default/github-actions-deployer, automount=false; Role+Binding только namespace
default, apps/deployments, resourceNames=[diploma-app], verbs get/patch/list/watch.
List/watch **с metadata.name=diploma-app**; unfiltered/другое имя/namespace deny.
Никаких pods/exec/proxy, Secrets, nodes, RBAC/token writes. can-i/SSAR для negative
Secret tests, не чтение реального Secret. API discovery/SSAR доступ проверить,
а не добавлять cluster-admin. [Draft139](https://github.com/myachmen/netology-devops-from-zero-homeworks/blob/8f57aebf85b088279a9314735d5fb31474c58cb8/kubernetes/cd/rbac.yaml).

При явно разрешённой issuance/placement оператор вычисляет commitments именно
того scoped token и trust configuration, которые попадут в environment. GitHub
Secret values обратно не извлекаются. В public approval попадают только hashes;
локальный verifier исключает незамеченную подмену injected Secret/endpoint.
Maximal permissions/TTL read-token GitHub API не интроспектирует универсально:
их audit остаётся обязанностью владельца при provisioning, не доказанным фактом140.

Patch одного Deployment может менять все Pod-template fields и косвенно использовать
другую SA/mounts/securityContext. Наш JSON patch меняет лишь image, но не снижает
серверные права украденного token. Явно принять риск учебного стенда или отдельно
утвердить admission control; не объявлять RBAC image-only.

Будущий operator preflight: current identity/strict host trust; existing TLS/SAN;
healthy cluster/app baseline; effective SA/bindings/positive get/filtered list/watch;
negative other resource/namespace/Secret/exec/token rights; actual TokenRequest
expiry/audience; stable Deployment UID/RV/generation/spec hash/replicas2 и previous
**runtime image digest**. Если template tagged, registry tag сам не доказывает Pod
imageID при IfNotPresent. Узкое чтение Pods выполняет отдельно разрешённый оператор,
не расширять для этого deployer Role. Результаты attests reviewer, не данный verifier.

## Первое окно, STOP, rollback

После access/configuration readiness отдельно утвердить одно release окно≤45min:
tests≤5, build≤20, review≤5, job≤10, cleanup≤5. Queue time включается в общее окно.
Issue short-lived token непосредственно перед review после build; минимум900s
remaining перед patch. GitHub attestation validity≤300s, baseline age≤300s,
job remaining≥300s из authoritative job.started_at. Просрочка→STOP, не auto-refresh
attestation, не повтор approval/rerun/patch без решения.

Freeze других app/settings writes. Два authenticated API reads (до SSH и перед
patch), одинаковый proof, atomic UID/RV/generation/image tests, one replace,
exact reply/final spec/readiness, HTTP200+new version. Evidence связывает
commit/tag/run/attempt/artifact/digest/UID/generation, без secrets/endpoints.

При mismatch/unknown write result/API error/новом network или privilege requirement
STOP. CI cancellation не откатывает Kubernetes controller. Только read-only reconcile;
automatic repair/reset/Helm rollback/повтор patch запрещены. Previous immutable digest
сохранить заранее; targeted rollback patch+postchecks — новое отдельное разрешение.
Cleanup своего tunnel/tempdir, disarm flags и revoke temporary access/cancel approved
run требуют заранее определённого scope; чужие ресурсы не удалять.

В140 все эти live/configuration gates **PLANNED/UNKNOWN/BLOCKED**, не выполненные
операции. Следующий шаг — отдельно утвердить этот точный scope и проверить policy
API visibility, а не просто удалить false.
