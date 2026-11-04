# CI/CD preparation — №139, APH/1.1

**CD_DISABLED / NO_RUNTIME_MUTATIONS / NO_NEW_SECRETS.**
Application preparation: feature/diploma-ci-cd-fixes-139, parent №137.
Никакого merge в main или первого release этот документ не разрешает.
Текущие ci/VERSION/index.html остаются1.0.0; fixtures1.0.1 меняются только в /tmp.

## Что исправлено после №138

- Version negative fixture берёт актуальную ci/VERSION, меняет ровно один
  существующий marker и отказывает при missing/duplicate/no-op replacement.
  Проверяются good/bad contexts для1.0.0 и временной1.0.1 без Docker daemon.
- PREPARATION/ACTIVATION получили отдельные статические и pure contract tests.
  Снятие false в *временной* ACTIVATION fixture не требует удаления security tests.
  Текущий workflow остаётся PREPARATION и literal false &&.
- Exact approved ref/SHA gates добавлены без конкретных одобренных значений.
  Vars/flags default missing→deny. Нет dispatch для deployment, PR/fork/rerun denied.
- Same-run tag/version/sha/run/digest contract сохранён. Actions закреплены на
  проверенных upstream commit SHAs, а не major tags.
- Один guarded JSON patch вместо set image: UID/resourceVersion/generation,
  replicas2, container name и previous image tests предшествуют replace image.
  Полный approved spec hash и verified previous digest проверяются до генерации.
  Ответ patch должен дать тот же UID, ровно следующую generation и ожидаемый spec;
  final check допускает новый status resourceVersion, но не новую spec generation.
- Named RBAC draft подготовлен отдельно в implementation: get/patch/list/watch,
  resourceNames только diploma-app. Это код, не применённые права.

## Граница между тестом контракта и разрешением execution

`ci/activation.py:validate_activation` проверяет **уже аутентифицированные** observations:
repository/ref/SHA/run/attempt/digest, независимого reviewer, свежесть, branch/tag
protection, environment approval/no bypass, scoped credential/trust/TLS observations,
namespace/resource/verbs, TTL/audience и остаточный job budget. SyntheticVerifier
есть **только в tests/fixtures.py**; он не является источником доверия для CI.

`authorize_execution` — обязательный runtime choke point. PREPARATION всегда denied.
ACTIVATION без отдельно reviewed authenticated verifier тоже всегда BLOCKED.
Штатный CLI **не интегрирует verifier** и не загружает его из env/path/JSON/plugin.
`CD_GATE_VERIFIED=true`, готовый JSON или флаги не могут разрешить deployment.
Даже случайное удаление false && не создаёт работающий путь к credentials/SSH/API.

Это намеренно незавершённый **BLOCKED activation component**, а не заявление о
проверенных GitHub protections или правах. Требуется отдельно согласовать и
реализовать аутентифицированную связь GitHub policy/review metadata и свежих
independent scoped-runtime observations с конкретным run. Нельзя заменить её
`SyntheticVerifier`, словарём true или непроверенным repo artifact. Доступов для
такой runtime проверки №139 не даёт; production verifier не выдумывается.

## Профили

| Профиль | Статические условия | Исполнение |
|---|---|---|
| PREPARATION (текущий) | Leading literal false &&, CD_PROFILE: PREPARATION; все остальные guards сохранены | Безусловный отказ execution до credentials/network |
| ACTIVATION (только offline fixture) | Та же conjunction без false, CD_PROFILE: ACTIVATION; exact ref/SHA, trusted event/attempt, environment/scoped timeout/pinned actions | Только при будущем authenticated verifier и полном runtime gate; сейчас CLI BLOCKED |

Профиль нельзя выбрать input/vars значением: в текущем YAML это literal.
`ci/workflow_policy.py` проверяет канонический набор conjuncts: добавленный OR,
missing condition/approval boundary, unpinned action — fail. Это ограниченный
static checker для данного workflow; полный YAML/workflow syntax проверяет actionlint.
Тесты не заменяют GitHub branch/tag protections и environment configuration.

Prep push в feature/diploma-ci-cd-fixes-139 выполняет только tests. Main и release
push в будущем могут build/publish только после tests. PR/dispatch/prep/fork не
получают registry/CD secrets через эти jobs. Нет pull_request_target/workflow_run,
id-token/write GITHUB_TOKEN permissions. Main workflow сейчас не менялся.

## Immutable Actions refs

Проверены GitHub Git refs официальных repositories на дату подготовки; это pinning,
не независимый security audit самих Actions. Полные commit URLs:

- [checkout v4](https://github.com/actions/checkout/commit/11d5960a326750d5838078e36cf38b85af677262)
- [setup-buildx v3](https://github.com/docker/setup-buildx-action/commit/8d2750c68a42422c14e847fe6c8ac0403b4cbd6f)
- [login v3](https://github.com/docker/login-action/commit/c94ce9fb468520275223c153574b00df6fe4bcc9)
- [metadata v5](https://github.com/docker/metadata-action/commit/c299e40c65443455700f0fdfc63efafe5b349051)
- [build-push v6](https://github.com/docker/build-push-action/commit/10e90e3645eae34f1e60eeb005ba3a3d33f178e8)

Base nginx tag остаётся mutable; registry contents/OCI labels/signatures в139 не
проверялись. Same-run digest provenance не является подписанной attestation.

## Guarded deployment contract

`ci/deployment.py` — pure functions + offline JSON CLI, без kubectl/network.
Защищённые authorization observations должен создать только будущий verifier.
Они связывают конкретные repository/ref/SHA/run/attempt/digest с approvals,
scope и свежим baseline UID/RV/generation/spec hash/previous image+digest.

Current template может содержать tag1.0.0. Тогда previous_digest_verified должен
доказать прежний **runtime digest**, а не предположить его из текста tag. Его
получает отдельно разрешённый оператор через узкий read scope/registry checks;
deployer не получает pods права только ради этого. Для digest template совпадение
с previous digest проверяется непосредственно. Same digest/no-op release denied.

Перед одним patch: named Deployment имеет правильные namespace/name/kind, один
ожидаемый container, replicas2, stable readiness и approved spec hash. Baseline
UID/RV/generation/image должны совпасть с независимыми observations. При stale
RV/status/concurrent rollout — STOP, не автоматический refresh/retry мутации.
API JSON tests закрывают race между GET и patch. Они не уменьшают серверные права
украденного токена: patch по RBAC всё ещё позволяет другие Pod-template changes.

После patch: exact UID, generation baseline+1, новый RV, полный ожидаемый spec.
После rollout: те же UID/generation/spec, observedGeneration и все replica counts2.
Чужой rollout, scale, recreate или side effect admission — STOP. Readiness status
может обновлять RV, поэтому final RV не обязан равняться patch response RV.
Rollout status по умолчанию следит за latest revision, но guard не принимает
чужую generation как успешный результат нашего deployment.

`ci/deploy.sh` сначала проходит execution gate; только затем читает credential env,
создаёт private temp files и SSH forwarding. Сохраняются StrictHostKeyChecking,
dedicated cd-tunnel, pinned known_hosts, loopback bind, CA/SAN verification,
отказ от admin kubeconfig/agent/TLS bypass. Authorization token expiry/audience,
approvals freshness и budget повторно проверяются непосредственно перед patch.

Budgets: observations не старше300s; token remaining≥900s; перед patch job
remaining≥300s. Это параметры будущего согласования, не доказанные реальные TTL.
Job10min, patch30s, rollout180s, named GET15s, HTTP connect5/total15s; downloads
имеют ограниченные read retries. Read/watch reconnect ≠ повтор deployment.
В script одна logical patch, без retry/repair/rollout undo. HTTP200+expected
HTML/version через существующий URL дополняет digest/UID/generation evidence;
это не криптографическое доказательство imageID каждого Pod.

Timeout/неизвестный patch outcome → EXIT и cleanup; CI cancellation не откатывает
Deployment controller. Не посылать вторую patch по предположению, что первая
не прошла. Cleanup завершает/ожидает только свой SSH и удаляет свой tempdir;
SIGKILL не гарантирует trap, поэтому future runner должен быть ephemeral.
Private JSON output files создаются exclusive0600; нет env/kubeconfig debug/artifacts.

## Проверки №139

```bash
PYTHONDONTWRITEBYTECODE=1 python3 ci/smoke.py
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
actionlint .github/workflows/docker-publish.yml
bash -n ci/deploy.sh
```

Tests используют только stdlib и временные файлы: positive/negative contexts,
PREPARATION/ACTIVATION policy fixtures, untrusted/missing/expired approvals и
allowlist, pure JSON patch API stub, concurrency conflict, wrong generation,
unready baseline/final, remaining budget. Полный script с обоими профилями и
всеми true flags блокируется до stub ssh/kubectl/curl. Background SSH не создаётся.
Нет Docker daemon, production/registry calls или credential values в fixtures.
Offline ACTIVATION pass означает валидность synthetic model, не право активации.

## Checklist будущего предметного разрешения

1. Утвердить code diff/main merge и side effect: каждый main push запускает
   test/build/push latest/sha в существующих registries. В139 main не меняется.
2. Настроить GitHub main/release protections, reviewer/check enforcement, запрет
   force/delete и bypass; environment diploma-production с независимым reviewer,
   prevent self-review и exact selected tag. Имя environment в YAML этого не делает.
3. Согласовать authenticated verifier integration и реальные источники policy/
   approval/runtime evidence. До этого runtime gate остаётся BLOCKED.
4. Согласовать restricted SSH OS/access changes: отдельный user/key без sudo/exec/
   PTY/SFTP/agent/reverse/other destinations, sshd -t/-T, сохранение ubuntu admin,
   reviewed один reload и channel tests. Роль cd_tunnel сейчас review-only.
   Ни широкого ключа, ни новой SG/API exposure/платной VM как shortcut.
5. Применять только отдельно утверждённый минимальный RBAC draft после review
   existing bindings; positive filtered list/watch и negative matrix из
   implementation kubernetes/cd/README.md. Принять patch residual risk либо
   отдельно утвердить admission guard. Effective permissions пока UNKNOWN.
6. Утвердить current VM/independent host-key/TLS CA/SAN и scoped TokenRequest
   audience/TTL/rotation. Не читать Terraform/YCR admin credentials ради CD.
7. Environment secrets (только имена): CD_SSH_PRIVATE_KEY, CD_SSH_KNOWN_HOSTS,
   CD_KUBE_CA_B64, CD_KUBE_TOKEN. Variables: CD_SSH_HOST, CD_SSH_USER,
   CD_API_TLS_NAME, CD_APP_URL. Repository gate vars: CD_ENABLED,
   CD_SSH_TUNNEL_APPROVED, CD_EXPECTED_REF, CD_EXPECTED_SHA, CD_EXPECTED_AUDIENCE.
   Environment variables ещё недоступны job.if. Отсутствующие значения → deny.
   Secret placement/values/effective roles/rotation не проверялись и не менялись.
8. Выбрать свободные Git/registry version names и reviewed activation SHA. Tags
   v1.0.0/v1.0.1 уже существовали в138; не двигать их. Кандидат v1.0.2 — НЕ approval.
   Version bump только в будущем утверждённом release diff, не в139.
9. Сначала approved activation commit (при выключенных flags), затем exact ref/SHA
   allowlist и один новый tag/run. Старый tag сохраняет старый workflow; rerun
   запрещён attempt1 guard. Tests→build/publish→review конкретных SHA/run/digest→
   scoped activation→одна patch→rollout→HTTP, без удаления security tests.
10. Issue короткий token непосредственно перед environment approval после build;
    проверить actual expiry и окно10min job+skew. Не создавать legacy SA-token
    Secret и не выдавать deployer право выпускать себе токены. При нехватке TTL,
    time budget, metadata drift/host-key/TLS/RBAC mismatch — STOP.
11. Freeze других app writes в первом окне; save previous verified runtime digest
    и baseline. Никакого automatic job rerun/repair/reset/rollback. После unknown
    outcome только read-only reconcile; rollback — отдельное разрешение на одну
    targeted patch прежнего digest и проверки. Cleanup/disarm/revoke и cancel
    только approved run также входят в отдельно согласованный scope.

Остаются UNKNOWN: actual GitHub-hosted reachability, SSH user/trust, TLS, bindings,
credentials/environment, runtime previous digest, новый registry build и rollout.
Ни live health, ни end-to-end CD не объявлены выполненными.

История: подготовка137 дала CI tests и disabled deploy; read-only138 уточнила
list/watch, version/activation fixtures и missing protections. №139 исправляет
код подготовки; инфраструктурные/credential gates остаются отдельными.
