# APH-CD/1 — допуск одного будущего run

Подготовка140. Этот документ не создаёт approval. В140 никто не отправлял review
или комментарий GitHub и не выпускал credentials. Никаких новых signing keys:
trust issuer — configured independent GitHub User reviewer, а источник — только
authenticated REST review history конкретного run.

## Envelope, который нельзя заменить входным JSON

Verifier читает GET /repos/myachmen/netology-diploma-app/actions/runs/RUN/approvals.
Должен быть **ровно один** target-environment record со state=approved; иной/
повторный/rejected/ambiguous record отказывает. User ID должен быть в текущем
required-reviewer списке environment и отличаться от actor/trigger_actor run.
Environment обязан иметь prevent_self_review, no admin bypass и exact selected tag.

Comment этого authenticated record начинается строго `APH-CD/1` + newline;
оставшийся текст — один JSON object без повторных ключей/NaN, размер≤32768 chars.
Тот же JSON в env, workspace, job output, artifact или чужом comment **не допуск**.
Transport не принимает custom API origin, Secret endpoints или anonymous fallback.
API errors/невидимая policy metadata означают BLOCKED, не «assume approved».

## Поля JSON (все обязательны, иных полей нет)

| Поле | Тип / смысл |
|---|---|
| schema | Строка APH-CD/1 |
| repository_id | Integer1440700475, immutable ID этого application repo |
| ref | Полный refs/tags/vX.Y.Z, exact approved tag |
| sha | Exact reviewed40hex commit, совпадает с tag, event и main ancestry |
| run_id / attempt | Integer GitHub run ID / ровно1 |
| actor_id | Integer authoritative run actor ID; triggering actor должен совпасть |
| digest | sha256:64hex, согласованный immutable image digest |
| artifact_id / artifact_digest | Integer ID и SHA256 ZIP digest из GitHub API immutable same-run artifact |
| issued_at / expires_at | Integer UTC epoch, reviewer-declared issue/expiry, срок≤300s |
| runtime | Объект ниже: утверждение уполномоченного reviewer о preflight |

Runtime поля — также точный allowlist:

- baseline: uid, resource_version, generation, spec_sha256, previous_image,
  previous_digest. Не помещать туда raw Deployment/Pod spec, env, kubeconfig или URL.
  spec_sha256 — SHA256 UTF-8 canonical json.dumps(spec,sort_keys=True,separators=(',',':')).
  previous image только существующий app YCR URI; digest подтверждается по runtime,
  а не предположением из tag.
- scope: namespace=default, deployment=diploma-app,
  identity=system:serviceaccount:default:github-actions-deployer,
  resource=deployments.apps, resource_names=[diploma-app],
  verbs=[get,patch,list,watch] в этом порядке, без иных grants.
- observed_at: UTC epoch preflight baseline, не старше300s, до issued_at.
- token_expires_at: фактическое server expiration TokenRequest, не сам token.
- token_audience_sha256: SHA256 approved audience, **не private API URL/value**.
  Audience проверяется локально против protected CD_EXPECTED_AUDIENCE и не
  отправляется GitHub. Hash commitment не является шифрованием/секретным storage.
- credential_commitments: ровно kube_token_sha256 и trust_config_sha256.
  Первый — SHA256 UTF-8 конкретного scoped token; второй — SHA256 canonical JSON
  dict с именами KUBE_CA_B64, SSH_KNOWN_HOSTS, SSH_HOST, SSH_USER, API_TLS_NAME,
  APP_URL, CD_EXPECTED_AUDIENCE и их точными строковыми значениями. Формат canonical
  JSON тот же sort_keys/separators выше. Public record содержит **только hashes**,
  без самих values. Verifier сравнивает их локально после authenticated API checks;
  raw values не передаются API observer/в сеть. Private key не хешируется/не публикуется.
- checks: строго true для scoped_credentials_verified, ssh_identity_verified,
  tls_verified, previous_digest_verified; это явно **reviewer attestations**.
  GitHub protection/review checks в payload не задаются: их вычисляет API verifier.

Нельзя публиковать token/SSH key/CA material/Secret data/private endpoints/State.
UID/RV/digests — public operational metadata в comment; её публикация требует
согласования владельца. Если нужные факты нельзя безопасно подтвердить и выразить
в этом allowlist, STOP, не расширять payload произвольным sensitive JSON.

## Как выдаётся допуск — в будущем, после отдельного разрешения

1. Reviewer получает trusted commit diff и run link, проверяет current branch/tag/
   environment policies и independent identity. Не подтверждает собственный run.
2. Test и build завершены success. Через GitHub metadata/immutable artifact видны
   actual run/attempt/head SHA, artifact ID/archive hash и cd-release.json. В нём
   repository/ref/SHA/run/version/digest/producer_job. Проверяется exact subject,
   а не копируется произвольный digest input.
3. Уполномоченный оператор выполняет отдельно разрешённый fresh read-only runtime
   preflight из access plan, используя существующий trusted доступ. Необходимые
   auth changes/TokenRequest/Secret placement также требуют нового scope.
   Commitments вычисляются при явно разрешённой выдаче scoped token/подготовке
   конфигурации в защищённой памяти, не через извлечение Secret values из GitHub.
   Неподтверждённое соответствие actual injected credentials — STOP.
4. Reviewer формирует allowlisted payload с конкретными run/artifact/digest/expiry
   и свежим non-secret runtime statement. Через GitHub environment review UI/API
   утверждает именно этот run с comment `APH-CD/1` newline JSON. Сейчас не делать.
5. GitHub actor/approval record аутентифицируются платформой, verifier заново
   проверяет live metadata и ZIP. Разрешение ограничено этим run/attempt/ref/SHA/
   digest и short expiry. Перед patch API перечитывается, proof не должен измениться.

Review history endpoint не предоставляет используемого здесь независимого
approval timestamp. issued_at — сознательное утверждение trusted issuer,
а не выдуманное поле ответа GitHub. Run.created_at ограничивает начало окна,
job.started_at — job budget; future/expired/overlong timestamp отказывает.

Доверие имеет предел: сервер GitHub доказывает **кто и какой run одобрил**, а не
правдивость вручную attest-нутого Kubernetes preflight. Verifier не объявляет
effective RBAC/SSH/TLS машинно проверенными; ошибочный/скомпрометированный reviewer
может выдать ложный statement. Остаточный риск нужно принять либо отдельно
спроектировать machine-observer с иным scope; bool/env-флагом это не исправить.

## Artifact provenance и transport

Только reviewed release build записывает manifest и immutable-pinned upload-artifact
публикует cd-release-RUN-1, overwrite=false. Verifier требует success producer steps,
creation внутри build interval, API workflow_run IDs/repository/head SHA, expected
name/ID/expiry, archive SHA256 и единственный cd-release.json без zip traversal/
лишних members. Payload должен соответствовать run и reviewer-approved digest.

API bearer используется только api.github.com metadata GET allowlist. ZIP redirect
разрешён лишь HTTPS к ожидаемым GitHub/Azure storage suffixes, без bearer/proxy
inheritance; archive≤1MiB, JSON≤32KiB. Ничего не извлекается в файловую систему.
Никаких автоматических API retries. Unknown outcome/metadata/schema → deny.

Это same-run provenance через trusted workflow и platform artifact integrity,
не image signature/SLSA и не независимая проверка registry contents. Требуются
reviewed producer code, branch protection, pinned Actions и trusted runner.
Build outputs без API artifact/issuer-binding недостаточны.

Первичные источники: [review history API](https://docs.github.com/en/rest/actions/workflow-runs#get-the-review-history-for-a-workflow-run),
[artifact API](https://docs.github.com/en/rest/actions/artifacts),
[environment API](https://docs.github.com/en/rest/deployments/environments),
[tag rules](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets).
Положительные examples в tests/github_fixtures.py — **synthetic only**, не реальные
разрешения. Их SHA/actor/UID нельзя копировать в production approval.
