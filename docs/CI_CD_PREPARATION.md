# CI/CD preparation — №140, APH/1.1

**CD_DISABLED / NO_RUNTIME_MUTATIONS / NO_NEW_SECRETS.**
Новая ветка feature/diploma-cd-access-gates-140 происходит от подготовки139.
Версия/HTML остаются1.0.0, основных веток и implementation изменений нет.

## Исполнимый admission вместо отсутствующего verifier

`ci/activation.py:authorize_execution` теперь по умолчанию подключает
`GitHubVerifier(GitHubAPI(...))`, а не завершается из-за отсутствующего adapter.
Сначала проверяются PREPARATION/ACTIVATION, trusted push/tag/attempt1 и exact
CD_EXPECTED_REF/SHA. **PREPARATION отказывает до чтения read token/сети**.
Текущий YAML сохраняет literal false && и CD_PROFILE: PREPARATION.

Будущий ACTIVATION получает proof только из authenticated GitHub REST:
repository ID/name, authoritative run/actor/attempt/SHA/ref, main ancestry,
classic branch protection, exact immutable tag ruleset, environment policy и
approved review от настроенного независимого User reviewer. Нет anonymous/token
fallback, input JSON, env observations, custom API origin или CLI test-provider.

`CD_GITHUB_READ_TOKEN` — имя будущего environment Secret; значения/наличие не
читались и не создавались. Нужны Actions:read, Contents:read, Metadata:read и
Administration:read для branch protection, только этот repository. Отдельно нужна
видимость bypass_actors в ruleset API. Если read-only доступ скрывает поле —
BLOCKED, **не выдавать CI write permissions ради обхода**. Подробнее:
[access plan](CD_ACCESS_PLAN.md), [approval format](CD_APPROVAL_FORMAT.md).

## Как проверяется digest

После успешной release build подготовлен шаг создания non-secret cd-release.json
с repository/ref/SHA/run/attempt/version/digest и producer_job. Pinned
actions/upload-artifact v4 публикует immutable artifact cd-release-RUN-ATTEMPT,
overwrite=false. Оба шага доступны только trusted release build job; prep branch
не запускает build/push/upload. Main и tag permissions не расширены до write.

Verifier через GitHub API проверяет completed/success test и build job, successful
manifest steps, artifact ID/name/expiry/run/repository/head SHA и build interval.
Затем проверяет SHA256 ZIP по API digest и единственный allowlisted JSON member.
Manifest обязан полностью соответствовать event и digest из authenticated reviewer
attestation. Job output сам по себе не является допуском. Это доверие к reviewed
build workflow + GitHub artifact integrity, **не SLSA/image signature и не
независимый аудит содержимого registry**. Компрометацию trusted builder это не решает.

Все Actions остаются immutable-pinned. Новый pin upload-artifact v4:
`ea165f8d65b6e75b540449e92b4886f43607fa02`, проверенный официальный Git tag.
Mutable nginx base и registry credential privileges остаются отдельными рисками.

## Runtime attestation: явная граница доверия

Approved environment review должен содержать APH-CD/1 comment. Сервер GitHub
аутентифицирует reviewer ID, состояние approval, environment и принадлежность к run;
verifier проверяет issuer против текущих configured User reviewers и исключает
run actor/trigger actor. Team reviewers сейчас fail-closed без неявного чтения org
membership. Rejection/дубликаты/неполная metadata/HTTP error — deny.

JSON внутри такого review — **утверждение доверенного оператора** о свежем
runtime preflight, scoped identity/TTL/audience/SSH/TLS и baseline. Не выдавать
его за автоматическую проверку Kubernetes. Копия того же JSON в env/file, от
другого автора или без approved review не авторизует ничего. Новых signing keys,
trust service или credentials не создаётся: authority — существующие GitHub
reviewer identity и API authentication после отдельно утверждённой настройки.

GitHub review history не даёт используемого независимого timestamp approval;
issued_at/expires_at — **явные поля reviewer attestation**, не выдуманные API поля.
Verifier ограничивает их run.created_at, текущим временем и сроком≤300s. Сам run
не старше45min, attempt1. Job deadline берётся из API deploy.started_at+600s.
К моменту patch token remaining≥900s и job remaining≥300s; runtime observation
не старше300s. При expiry — STOP; второй patch/rerun не выполняется.

В public comment нет token/key/CA/kubeconfig/private endpoint. Для audience
публикуется только SHA256 commitment; настоящее значение остаётся в защищённой
конфигурации и private temporary proof. Hash не является шифрованием. UID/RV/
spec hash/digests — несекретная операционная metadata; её публикация тоже входит
в будущее отдельное разрешение владельца.

Отдельные commitments связывают допуск с actual injected KUBE_TOKEN и canonical
trust configuration (CA, known_hosts, endpoints/user/TLS/app/audience). Они
сравниваются локально **после** authenticated API checks, raw values не отправляются
observer/в API и не логируются. Substitution Secret/endpoint → deny. На повторной
проверке значения передаются только gate subprocess из неэкспортируемых shell
variables, затем удаляются; SSH/kubectl/curl их через env не наследуют. xtrace
принудительно выключен. Это связывание с attested материалом, не доказательство
прав token; их предварительно проверяет уполномоченный оператор.

## До единственной mutation

Первый API gate предшествует credential files/SSH. Policy read token убирается
из экспортированного окружения SSH/kubectl/curl; только в отдельный subprocess
recheck он передаётся через env без argv/log. Перед patch заново читаются
authoritative GitHub policy/review/artifact; proof должен точно совпасть с первым
и оставаться действительным. Это две проверки во времени, не непрерывная блокировка
GitHub settings: другие app/settings writes в первом окне запрещаются организационно.

Сохраняется guarded JSON patch139: test UID/RV/generation/replicas/container/old
image, then один replace YCR@sha256. Проверяются approved spec hash, verified
previous runtime digest, exact reply/final generation/spec/UID и readiness2.
Status RV может изменяться. Конфликт/неизвестный outcome → STOP/read-only reconcile,
не auto-refresh/retry/rollback. Server RBAC patch риск не исчезает: он не image-only.

SSH только dedicated cd-tunnel, pinned host key, agent off, loopback forward,
CA/SAN TLS, scoped temporary kubeconfig; admin fallback и insecure flags запрещены.
Cleanup только своего tunnel/tempdir; SIGKILL не гарантирует trap. HTTP200+HTML/
version дополняют digest/rollout evidence, не доказывая imageID каждого Pod.

## Offline checks и limits

```bash
PYTHONDONTWRITEBYTECODE=1 python3 ci/smoke.py
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
actionlint .github/workflows/docker-publish.yml
bash -n ci/deploy.sh
```

Tests подменяют только transport/clock внутри процесса; production CLI не имеет
test switch. Никаких network calls/Secret values в fixtures. Проверяются целый
factory→API verifier→admission path, fake/rejected/self approvals, API errors,
run/tag/SHA/digest mismatch, hidden policy fields, attestation expiry, artifact
tampering/foreign provenance, unsafe ZIP/redirect, scoped time budget, Deployment
drift и current/temporary1.0.1 version suites. API bearer передаётся только fixed
api.github.com GET allowlist; artifact redirect идёт без bearer. Нет retries,
proxy inheritance, sensitive endpoints или логирования HTTP bodies/headers.

Positive stub не доказывает live policy/access. Реальная API visibility,
CD_GITHUB_READ_TOKEN, environment, SSH/TLS/RBAC и current health — UNKNOWN/BLOCKED
до отдельного preflight. Missing can_admins_bypass/type/bypass fields не получают
безопасных default values. Unsupported inherited/team/partial metadata — STOP,
не выдача широких прав. Версия API зафиксирована2026-03-10; live compatibility
проверяется в будущем без ослабления условий.

История:137 добавила tests;138 выявила gaps;139 исправила fixtures/RBAC/JSON guard,
но оставляла adapter unavailable.140 подключает реальный API path и формализует
trusted reviewer attestation; **production CD не включён**. Следующее действие —
утверждение exact access/settings/credential scope из плана, а не снятие false
без проверок. Никакого автоматического перехода к следующему заданию.
