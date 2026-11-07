# Диплом: один tag → image → rollout → HTTP

Кандидат №189: версия **1.0.3**. Реализация живёт в
`myachmen/netology-diploma-app`; infrastructure/Terraform pipeline находится в
`myachmen/netology-devops-from-zero-homeworks` и этим PR не меняется.
Это подготовка к отдельному решению владельца: PR не означает разрешение merge,
создания тега, запуска CD или текущую готовность Kubernetes.

## Единственный workflow

`.github/workflows/docker-publish.yml`:

| Событие | Offline tests | Registry build/push | Kubernetes deploy |
|---|---|---|---|
| Feature push / PR в main | Да | Нет | Нет |
| Push main | Да | Да, отдельный run-bound tag | Нет |
| Push `vX.Y.Z` | Да | Только exact `ci/VERSION` и commit из main | Да, только digest этой сборки |
| Fork / dispatch / rerun | Нет допуска к публикации | Нет | Нет |

PR workflow не получает secrets. Writer jobs требуют собственный репозиторий,
push, attempt=1; build допускает только main/tag, deploy только tag после test/build.
SHA checkout закреплён на event SHA; Actions закреплены на commit SHA;
GITHUB_TOKEN имеет только contents:read. Проверка ancestry выполняется до login/build.
Неправильный semver или tag/version mismatch останавливает сборку до registry write.

Image repository сохранён: `cr.yandex/crpb1oihnpa2uai8m3mp/netology-diploma-app`.
Единственный image tag — `sha-<40-char-commit>-run-<run_id>`: повторные попытки
публикации запрещены, `latest`/перезаписываемый version alias не создаётся.
Registry-side immutable enforcement не настраивается и не заявляется.
В Deployment передаётся **только `repository@sha256:<digest>`** из этого же run,
не mutable tag. OCI labels и Job Summary связывают version/tag/SHA/run/digest.
Complete tag workflow сериализован через `diploma-app-run-production`; cancel=false.
Дополнительно сохранён прежний deploy job lock `diploma-app-production`
(имя отличается от workflow lock во избежание самоблокировки). Не запускать другие writers вручную.
GitHub concurrency не является durable очередью: более двух параллельных событий
могут вытеснить pending run. Поэтому владелец согласует только один релиз за раз.

## Существующий ограниченный доступ

GitHub-hosted runner → strict SSH `cd-tunnel` на существующем control-plane →
локальный forwarding API `127.0.0.1:6443`. API не открывается наружу.
Отдельные SSH key/known_hosts, IdentitiesOnly, IdentityAgent=none,
StrictHostKeyChecking=yes; глобальное доверие не меняется, accept-new запрещён.
Kubeconfig в mode0600 tempdir использует CA и tls-server-name, без insecure flags.
Существующий SA/Role/RoleBinding `default/github-actions-deployer` ограничен
get/patch/list/watch **Deployment `default/diploma-app`**; новых прав/Secrets нет.
Доступ, identity, актуальность ключей, RBAC и сертификатов — owner prerequisites,
а не текущие подтверждённые факты №189.

Нужны существующие GitHub Repository Secrets **только с такими именами**:

- `YC_SA_KEY_JSON` — существующий registry writer, не создавать IAM credentials;
- `CD_SSH_PRIVATE_KEY`, `CD_SSH_KNOWN_HOSTS` — только restricted cd-tunnel;
- `CD_KUBE_CA_B64`, `CD_KUBE_TOKEN` — доверенный API CA и scoped ServiceAccount token.

Repository Variables: `CD_SSH_HOST`, `CD_SSH_USER` (ровно `cd-tunnel`),
`CD_API_TLS_NAME`, `CD_APP_URL` (существующий публичный ALB root URL).
Значения передаются владельцем через GitHub UI; не помещать их в Git/чат/логи.
Не использовать admin kubeconfig или SSH admin key. Перед будущим запуском
владелец должен обеспечить актуальный scoped token и проверить его фактические
exp/audience/subject и TTL с запасом на build+deploy; старое наличие Secret
не доказывает действительность токена. №189 значений не читает и не меняет.

Workflow использует существующие repository secrets, без обязательного нового
Environment или второго пользователя. Settings/branch/tag protections не меняются.
Если владелец вводит Environment, до тега нужно отдельно согласовать workflow
`environment` и соответствующую область secrets/vars, ограничить deployment tags;
просто создать Environment и считать jobs защищёнными им нельзя. По текущему
варианту контроль — отдельно одобренный merge и один release tag на согласованном
main SHA, плюс неизменные guards. Владельцу не следует выдавать untrusted authors
право менять workflow или создавать production tags.

## Что именно делает deployment

1. Проверяет same-run SHA/tag/version/digest и обязательную конфигурацию до SSH.
2. Создаёт защищённые временные файлы и один forwarding; GET named Deployment
   до 10 попыток с request timeout5s и sleep1s, без мутаций.
3. Читает baseline: правильные namespace/name/container/repository, ровно 2 готовые
   реплики, актуальный observedGeneration; no-op digest прекращает запуск.
4. Выполняет **один** atomic JSON patch с тестами UID/resourceVersion/generation/
   replicas/container/old image; меняет только image. Конфликт/timeout → STOP.
5. Проверяет ответ, `rollout status --timeout=180s`, затем final generation,
   неизменность остального spec, exact digest и 2 updated/ready/available replicas.
6. С runner делает реальный GET `CD_APP_URL`: 5 попыток максимум, curl connect5s /
   total15s, subprocess17s, sleep5s между попытками. HTTP200 **и HTML exact version**
   обязательны; redirects не следуются; body ограничен64KiB. Retry только чтения,
   не patch/build/release. Лимит helper <=105s с учётом subprocess watchdog.
7. Всегда закрывает свой SSH forwarding и удаляет temp key/kubeconfig/body.
   При ошибке сообщает этап/exit и STOP без deployment retry или rollback.

Успешный rollout при failed HTTP smoke — **failed CD**, а не повод повторять patch.
При неизвестном результате мутации сначала отдельная read-only reconciliation
после согласования; никаких rerun/undo/reset/repair/force.

## Границы доказательств

Исторический tag v1.0.2 на cc81c800d84b995aef26eb99e31bdac3bacd331c:
[run41910789234](https://github.com/myachmen/netology-diploma-app/actions/runs/41910789234)
build/push/rollout состоялись, HTTP runner timeout дал итог FAILURE. Отчёт №147
подтвердил HTTP200 из management/control-plane, но не из runner; причина timeout
осталась UNKNOWN. Bounded retries помогают только временному сбою, не устраняют
неподтверждённую сетевую причину и не обходят проверку. В №148 новая диагностика
была остановлена из-за branch-push registry side effects; №189 устраняет этот
подтверждённый дефект маршрутизации workflow.

№189 не вызывает SSH, Cloud API, Kubernetes или registry. worker-2 по owner UI
остановлена как preemptible VM; её запуск не разрешён. Capacity/Ready/ALB health,
runner reachability, current credentials и успешный end-to-end остаются UNKNOWN.
Terraform automation считается завершённым по существующим evidence №188;
не запускать дополнительную Terraform диагностику для app release.

## Один следующий шаг владельца

Рассмотреть этот draft PR и отдельно разрешить merge **его точного head SHA**.
Merge сам запускает main image build/push: это тоже требует разрешения.
После merge и успешного CI — отдельное разрешение **одного** нового тега `v1.0.3`
на точном итоговом main SHA (squash SHA отличается от feature SHA), без tag movement.
Перед этим ограниченная актуальная проверка существующих identity/trust,
Nodes/capacity/app2Ready/ALB и restricted access/RBAC/token TTL; если требуются
запуск VM, изменение сети или credentials — отдельное разрешение, не обход.
Не создавать уже существующий тег; при неожиданном состоянии STOP.

Ожидаемые acceptance evidence первого разрешённого tag run:
exact tag/ref/SHA/run attempt1 → successful tests → build/push → run-bound image tag
и sha256digest → единственный patch → Ready rollout2/2 → runner HTTP200 и Version1.0.3
→ зелёный run + Job Summary и обезличенные screenshots. Не выдавать offline tests
за live evidence. Возможны обычные Actions/registry traffic/storage расходы;
новых облачных ресурсов нет. После failed tag run — STOP, без автоматического
повторного релиза или отката. Следующий runtime/monitoring/сдаваемый README milestone
не входит в №189.
