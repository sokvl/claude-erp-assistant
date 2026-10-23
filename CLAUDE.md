# CLAUDE.md

FastAPI + MongoDB API for a B2B hardware distributor (laptops, servers, data center gear, PC parts)
selling to large companies: a faceted product catalog, invoice listing and analytics, and two
Claude-powered chat assistants that answer only from tool results: a product advisor for
consultants and an invoice analyst for managers. Accounts and roles gate every route. A mini data
lake (Garage S3, bronze/silver/gold) is being built next to it.

## Commands

```bash
./run.sh                                      # docker compose mongo1..3 + uvicorn --reload on :8000
./venv/bin/python -m pytest                   # unit + api (integration and vault excluded by addopts)
./venv/bin/python -m pytest --cov             # branch coverage, fail_under = 85
./venv/bin/python -m pytest -m integration    # needs MONGO_TEST_URI exported (pytest reads no .env)
./venv/bin/python -m pytest -m vault          # needs a Vault dev server, VAULT_TEST_ADDR default :8200
PYTHONPATH=src ./venv/bin/python -m app.cli create-user|issue-api-key|revoke-api-key
python seed/load_to_mongo.py                  # invoices from seed/dataset.csv + every index set (run first)
python seed/generate_invoice_items.py [--products-only]   # catalog; without the flag also rewrites invoices.lines
python seed/fabricate_orders.py [--count --from --to --purge]   # ~1M synthetic invoices, source: "synthetic"
python seed/simulate_orders.py [--once --every --orders --payments]   # ERP stand-in: new orders + bank-import closes
python seed/backfill_updated_at.py            # one-time: updatedAt on invoices that predate it
python seed/backfill_invoice_events.py [--apply]   # one-time: event log for closes made before it; dry run without --apply
python evals/run.py [--level functional|e2e|all] [--case ID]   # live model eval, costs tokens
./venv/bin/python scripts/cap/run_all.py      # CAP lab: partitions the replica set, prints tables (~100 s)
```

One-time bootstrap, each idempotent: `deploy/mongo/init-replica-set.sh` (rs0 with three members),
`deploy/mongo/create-users.sh` (root, `invoices_app` readWrite on `invoices_db`, `invoices_test`),
`deploy/vault/bootstrap.sh` (KV + Transit + AppRole), `deploy/garage/init.sh` (layout, buckets,
keys). None of them runs from `run.sh`.

`.env` (see `.env.example`): `MONGO_URI` and `MONGO_TEST_URI` list all three nodes with
`replicaSet=rs0` and are single-quoted because they contain `&` (the deploy scripts source `.env`
with bash); `MONGO_DB_NAME` (default `invoices_db`); `MONGO_ROOT/APP/TEST_PASSWORD`;
`ANTHROPIC_API_KEY` (without it `/chat` returns 503); `GARAGE_RPC_SECRET`, `GARAGE_ADMIN_TOKEN`
(compose refuses to start any service without them); `LAKE_WRITER_*` / `LAKE_READER_*` (written by
`deploy/garage/init.sh`); `EVALS_API_KEY`. With `VAULT_ADDR` set (plus `VAULT_TOKEN`, or
`VAULT_ROLE_ID`/`VAULT_SECRET_ID` or their `_FILE` forms), `MONGO_URI` and `ANTHROPIC_API_KEY`
come from KV `secret/invoices-app` and access tokens are signed by the Transit key; without it
the env values and a local signing key are used.

## Map (`src/app`)

```
main.py          app assembly; global PyMongoError -> 503 handler; GET / serves static/chat.html
config.py db.py  load_dotenv + secrets; module-level MongoClient behind get_database() (DI seam)
vault.py         vault_client (token or AppRole), app_secrets from KV, secret(name, default)
security.py      current_principal: Bearer access token first, else X-API-Key; require_role(role) (cached);
                 get_signer: VaultTransitSigner when VAULT_ADDR is set, else LocalSigner
cli.py           create-user (prompts for the password), issue-api-key (printed once), revoke-api-key
limits.py        ALL numeric bounds (BSON-safe caps, page sizes, chat, auth, TTLs). Never inline a bound.
auth/
  roles.py       Role (consultant, manager, admin), GRANTS, Principal(username, role), allows()
  passwords.py   argon2id hash/verify; users.py: accounts keyed by username
  tokens.py      EdDSA JWT access tokens (algorithms pinned); signer.py / vault_signer.py sign them
  sessions.py    rotating refresh tokens stored as sha256, familyId revokes a replayed session
  throttle.py    login lockout after MAX_LOGIN_ATTEMPTS; api_keys.py: per-account keys stored as sha256
  service.py     login / refresh / logout, AuthError, Session
catalog/
  enums.py       Category/Brand/Architecture/MemoryType/UseCase (the search vocabulary),
                 SortField/SortOrder + SORT_PATHS (API name -> Mongo dotted path)
  schemas.py     ProductSearchParams: enum-typed filters, bounds, extra="forbid", inverted-range validator
  query.py       PURE dict builders: build_product_filter -> $match, build_search_pipeline
  vocab.py       facets only: live distinct() per field, no cache, never used for validation
  service.py     search_catalog(params) = filter -> search_products(criteria)
invoices/
  enums.py       InvoiceStatus, InvoiceSortField (+ SORT_PATHS), GroupBy (+ LINE_ITEM_FIELDS, PERIOD_UNITS)
  schemas.py     InvoiceFilter -> InvoiceListParams / InvoiceAnalyticsParams, extra="forbid"
  query.py       PURE builders: build_invoice_filter, build_list_query (find kwargs), build_analytics_pipeline
  service.py     list_invoices / analyze_invoices / close_invoice: the controller the API and the analyst call
  pending_actions.py  a close the analyst requested and a manager approves or rejects (TTL, decided once)
  closing.py     decide_close: preview the request, check the payment date, then one transaction
                 for the decision, the close, the outcome and the event
  events.py      PURE: the append-only invoice_events log (actor user|system), history reads
charts/
  enums.py       ChartType (line/bar/stacked), ChartMetric (+ METRIC_FIELDS: metric -> analytics row key)
  schemas.py     ChartParams(InvoiceAnalyticsParams): chart_type, metric, rejects unplottable combinations
  render.py      PURE: analytics rows -> PNG bytes. Figure + FigureCanvasAgg, never pyplot
  storage.py     charts collection: save_chart/get_chart/recent_charts, PNG as Binary, TTL expiry
  service.py     chart_analytics() = analyze_invoices -> render -> store, returns the rows plus chartId
assistant/
  profiles.py    AssistantName, Profile (model, role, prompt, max_tokens, request options), ADVISOR, ANALYST
  prompts.py     SYSTEM_PROMPT + OUT_OF_SCOPE_REPLY (advisor), ANALYST_PROMPT + ANALYST_OUT_OF_SCOPE_REPLY
  tools.py       tool defs, all static; TOOLS[assistant] is the assistant's set
  dispatch.py    run_tool(): name -> handler, re-validates input, strips _id/tier, JSON out; returns
                 ToolOutput(content, chart id, pending action) so a tool can announce side results
  chat.py        build_request(profile), agent loop, streaming, retries, ChatError codes, tracing
  conversations.py  ConversationStore on the conversations collection, one owner per chat, TTL
  usage.py       token/cost rollup -> chat_usage collection (PRICE table keyed by model id)
utils/           dates.py (today in the business timezone), mongo.py (range_filter)
routers/         auth.py (/auth/login, /refresh, /logout, /me), products.py (+ /facets), invoices.py
                 (+ /analytics), chat.py (SSE), charts.py, pending_actions.py (/{id}/approve, /reject),
                 audit.py (/audit/invoices/{id}/events, admin only)
```

Outside `src/app`: `tests/{unit,api,integration}`, `evals/` (cases + graders comparing the
model's tool calls and answers with gold queries), `seed/` (dataset and loaders; `products.py`
holds the catalog and `USE_CASE_TAGS`, `indexes.py` the complete index set), `deploy/` (bootstrap
scripts and configs for Mongo, Vault, Garage), `scripts/cap/` (the CAP lab, dev tooling), `lake/`
(the data lake: storage, bronze, silver, Dagster definitions). The
Docker image copies only `requirements.txt` and `src/`, so none of these ship.

## Design decisions that matter

- **One validation path, two entry points.** `SearchProductsInput` subclasses `ProductSearchParams`
  and changes only the page-size default and cap. HTTP requests and model tool calls go through the
  same Pydantic model, `search_catalog`, and filter builder. The model is an untrusted caller.
- **Static vocabulary, live facets.** Filter values are `StrEnum`s in `catalog/enums.py`, not
  `distinct()`: the tool schema is deterministic (prompt-cache stable, exactly unit-testable), and
  a typo in the data can't become a valid value. Pydantic rejects unknown values (HTTP 422, tool
  `is_error` listing the allowed values). `/products/facets` and `get_product_facets` still read
  `distinct()` live, to report what the catalog actually holds. The app never writes products;
  the catalog is `seed/products.py` (97 products, 15 categories). Adding a value = enum + seed
  product; nothing checks the seed against the enums in CI any more, only the integration
  `test_vocab_hygiene` checks the served `invoices_db`. Every category has its own `specs` keys;
  a non-GPU product must never use a key a GPU filter, sort or facet reads (`architecture`,
  `memoryType`, `useCases`, `vramGb`, `fp16TensorTflopsDense`, `releaseYear`, `multiGpuScaling`),
  because the tool promises those filters restrict results to GPUs. Laptops, servers, UPS units and
  rack gear have no typed filters: the advisor filters by category, brand and price and compares
  specs from the results.
- **Strict tool schemas.** `"strict": true` does not allow `minimum/maximum/maxLength/maxItems/...`
  in tool schemas, so bounds live only in Pydantic and descriptions mention them in prose, using
  values interpolated from `limits.py`. Tests require the tool properties to match the Pydantic
  fields exactly, in the same order. **The invoice tools are deliberately not strict**: strict
  decoding emits optional properties only in schema order, so a filter the model reaches for after
  a later property is silently dropped (measured live: Q1 dates vanished, all-time totals came
  back). Making everything required+nullable needs 22 union-typed parameters; the API caps them at
  16. Pydantic validation is the guard, and `analyze_invoices` echoes the `filters` it applied.
- **Search pipeline.** `$match` comes first so it can use an index. A single `$facet` returns both
  the page and the filtered total, and `$ifNull` turns an empty total into 0. Sorts add an `_id`
  tiebreaker so pagination stays stable. Sorting by a `specs.*` field injects `{$type: "number"}`
  (a positive predicate, not `$ne: null`) so non-GPU products drop out instead of leading (unless
  the caller already filters on that path).
  Queries run with `maxTimeMS=QUERY_TIMEOUT_MS`. `build_search_pipeline` rejects raw strings for
  sort fields; only the enums can become `$sort` keys.
- **Invoice numbers come from MongoDB, never from the model.** `analyze_invoices` computes totals,
  averages, open/overdue amounts, days to pay, units and average unit price in one pipeline and
  rounds money to cents in the DB. Rows are grouped and ranked **per currency** (USD and CAD are
  never added or compared). Line-grain groupings (product, brand, category) `$unwind` the `lines`
  embedded in each invoice and count invoices, not lines. Periods sort chronologically and default
  to `MAX_ANALYTICS_ROWS`, so a trend isn't cut. `coverage` always spans the whole collection, so
  an empty period can still name the data range. Query dates must be `datetime` (BSON can't encode
  `date`); `overdue` means open and due before midnight of `as_of` (default today). With ~1M
  invoices, all-time category/brand/product groupings exceed the 5 s `maxTimeMS` and surface as
  `database_unavailable`; moving the analyst onto the lake's gold layer is the planned fix.
- **Charts are drawn from a query, never from the model's numbers.** `chart_invoices` takes the
  same filters as `analyze_invoices`, runs that controller, and renders its rows; the model never
  supplies a data point. It returns the rows *and* a `chartId`, so one call feeds both the table
  and the picture. The PNG is never sent back to the model. `render.py` uses `Figure` +
  `FigureCanvasAgg` directly, never `pyplot`: the handlers run in FastAPI's threadpool and pyplot's
  global figure registry is not thread-safe. One subplot per currency, never a shared y-axis.
  `stacked` derives its segments server-side (`cleared = total - open`, `current = open - overdue`,
  `overdue`), clamping cent-rounding to 0. No rows -> `chartId` is null, not an error. Charts live
  in the `charts` collection as `bson.Binary` with a TTL index and belong to the user who asked;
  `ChartParams` rejects combinations the rows cannot produce so the model gets a correctable
  `is_error`. `GET /charts/{id}/image` needs the manager role like the rest, so the page fetches
  it with the access token and renders a blob URL rather than a plain `<img src>`.
- **Closing an invoice needs a human.** In a real ERP most invoices close themselves when a bank
  statement payment matches; a manual close is the exception path, so a person approves it. The
  analyst's `close_invoice` tool takes a required, nullable `paid_on` (only a suggestion), stores a
  pending action (TTL `PENDING_ACTION_TTL_MINUTES`) and a `close_requested` event, and the chat
  emits `confirmation_required`. The card shows a date field (min posting date, max today, empty =
  write-off); the manager who asked approves or rejects through `/pending-actions/{id}/approve|reject`.
  `decide_close` previews the request (409 if not decidable), checks the date against the posting
  date and today in the business timezone (422, the request stays pending), then runs one
  transaction: decide the request, `close_invoice` (`isOpen`, `closedAt`, `updatedAt`,
  `dates.clearDate`, filtered on `isOpen: true`), record the outcome and write a `closed` or
  `close_rejected` event. **The invoice holds state, the event holds circumstances**: who, why,
  the suggested and approved dates and the conversation live only in `invoice_events`, which is
  append-only, never expires, and is read by admins (`/audit`), not by the analyst or the lake.
- **Auth.** Passwords are argon2id; access tokens are short EdDSA JWTs (algorithm pinned on
  verify); refresh tokens rotate, live in an HttpOnly, Secure, SameSite=Strict cookie on `/auth`,
  are stored only as sha256, and a replayed one revokes its whole `familyId`. Scripts use
  per-account API keys (`X-API-Key`, stored as sha256, act as their owner). Roles: `consultant`
  (catalog, advisor) ⊂ `manager` (also invoices, analytics, charts, pending actions, analyst);
  `admin` is a separate branch that grants neither and reads the audit log. Charts, pending actions
  and conversations are scoped to their owner. The model never learns who is asking.
- **Two assistants, routed explicitly.** `ChatRequest.assistant` (default `advisor`) picks a frozen
  `Profile` whose `role` the caller must hold (`chat_principal`); each assistant has its own
  conversation store, so a conversation never changes model, prompt or tools, and invoice figures
  never reach the advisor's context. No classifier hop. The analyst runs Sonnet 5 with adaptive
  thinking, `effort: medium`, a 90 s read timeout and today's date in a second, uncached system
  block after the cached prompt. `eager_input_streaming` stays off; refusal `fallbacks` are not
  used (`refused` handles it).
- **Pure modules.** `catalog.enums/query/schemas`, `invoices.enums/query/schemas`,
  `charts.enums/schemas/render`, `utils.mongo` and `auth.roles/passwords/signer/tokens` must not
  import `app.config` or `app.db` (enforced by a subprocess test).
- **MongoDB layout.** `seed/indexes.py` is the whole index set; the loaders run `sync_indexes`,
  which drops anything undeclared. Invoice indexes follow equality → sort → range with an `_id`
  tiebreaker, plus `(updatedAt, _id)` for the lake's incremental extract; every write to an
  invoice must set `updatedAt`. Products keep only `(category, listPrice)` (under a hundred docs).
  A new query shape needs a row in `tests/integration/test_query_plans.py`, which explains it and
  asserts its index, a key count bounded by the page, and no index intersection. Invoice lists are
  `find` + `count_documents`, not `$facet`. Line items are embedded as `invoices.lines` (≤ 5), so
  there is no `invoice_items` collection. Collections the app writes: `invoices` (closes only),
  `pending_actions`, `invoice_events`, `charts`, `conversations`, `chat_usage`, `users`,
  `refresh_tokens`, `login_attempts`, `api_keys`; the ones that expire have TTL indexes on
  `expiresAt`, which is what prunes them. Writes that must land together go through
  `get_transaction_runner` (`with_transaction`, so a transient error retries the whole callback:
  keep side effects such as e-mail outside it). The unique `(actionId, type)` index on
  `invoice_events` is partial on `actionId` being a string, because system events store `null`. The customer filter is `customer.number` or a left-anchored prefix on
  `customer.nameLower`: an unanchored or `/i` regex can't be index-bounded. No sparse indexes on
  fields stored as explicit `null`. Long field names stay (block compression is `zstd`).
  `seed/load_to_mongo.py` still `$set`s `isOpen` from the CSV, so rerunning it reopens invoices
  the app closed; run only `sync_indexes` against a live database until that is fixed.
- **Replica set, CP.** Three mongod nodes `rs0` (`mongo1..3.localhost:27017..27019`, shared
  keyfile, `--auth`, 60 s stop grace for the 15 s quiesce). `*.localhost` resolves to loopback on
  the host and to Docker network aliases inside containers, so one URI works everywhere without
  `/etc/hosts`; distinct ports keep a node whose alias vanished from talking to itself. Writes use
  the server default `w: majority`; `chat_usage` alone is written with `w: 1` (bookkeeping, a
  rollback only undercounts cost). Reads use the default `readConcern: local`; anything that must
  never see a rolled-back write (the lake's bronze extract) reads with `majority`. Measured by the
  CAP lab: a cut-off primary keeps acknowledging `w: 1` writes for ~10 s and loses them on
  rollback (198 per run), `majority` loses none, and a set-wide client is without writes for ~10 s
  before it moves to the new primary on its own. Transactions exist only on a replica set, so CI
  starts `mongo:7 --replSet rs0` with `rs.initiate()` (a service container takes no arguments) and
  the transaction tests fail rather than skip when `REQUIRE_MONGO` is set.
- **Data lake storage.** Garage v2 (MinIO no longer publishes a public image) serves S3 on
  `127.0.0.1:3900`. Garage grants per bucket, not per prefix, so each layer is a bucket:
  `lake-bronze`, `lake-silver`, `lake-gold`. `lake-writer` reads and writes all three;
  `analyst-reader` only reads `lake-gold`. Endpoint, region, keys and bucket names must come from
  configuration so the same code can run against AWS S3.

## Chat error handling (`assistant/chat.py`)

Follows the Anthropic SDK guidance: the SDK handles retries that can safely be repeated, and the
app handles what the SDK can't.

- Client: `max_retries=2`, `Timeout(60, connect=5, read=30)`. `RateLimitError`, `OverloadedError`,
  `InternalServerError` and `APIConnectionError` reach the app only after the SDK's own retries
  are used up, and map to `assistant_busy` with no further retry.
- Mid-stream errors arrive as `APIStatusError` with `exc.type`. Types in
  `RETRYABLE_ERROR_TYPES` (overloaded, api, rate_limit) and `httpx2.TransportError` are retried up
  to `MID_STREAM_RETRIES=2`, with backoff `0.5*2^n` s and 25% jitter, **only if no text has been
  streamed yet** (text already sent can't be taken back). Other errors map to
  `assistant_unavailable`.
- `stop_reason`: `end_turn` or `max_tokens` with no `tool_use` produces an `Answer` (`truncated`
  flag set on `max_tokens`). `tool_use` runs the tools and loops. `refusal` produces `refused`
  and logs `stop_details.category`. `None`, or `max_tokens` with a `tool_use` block, produces
  `interrupted`, and **a truncated `tool_use` is never executed**. Anything else produces
  `assistant_unavailable`. More than `MAX_MODEL_CALLS=6` calls produces `too_many_steps`.
- Tool failures: `ToolInputError` becomes an `is_error` tool_result so the model can correct
  itself. `PyMongoError` aborts the turn with `database_unavailable`. Any other exception becomes
  an `is_error` result with the generic `TOOL_FAILURE_MESSAGE`, and the internals are logged, not
  shown to the model.
- Every `ChatError(code)` maps to a user-facing text in `ERROR_MESSAGES`. The router streams it
  as an SSE `error` event, and unexpected exceptions become `unexpected_error`.
- Prompt caching: `cache_control` is set on the system block and at the top level of the request.
  Models are pinned in `profiles.py` (`claude-haiku-4-5-20251001`, `claude-sonnet-5`, which is the
  canonical snapshot id); changing one also means updating `usage.PRICE_PER_MILLION_TOKENS` (a test
  requires a price row for every profile's model).

SSE events from `POST /chat`: `conversation` → (`text` | `tool` | `chart` | `confirmation_required`)*
→ `done {truncated}` | `error {code,message}`. `chart` is emitted when a tool returns a chart id and
`confirmation_required {pending_action_id, invoice_id, ...}` when the analyst requested a close.
Conversations live in MongoDB (`conversations.py`): only the user's text, the final answer and the
turn's chart ids are stored, never tool blocks, capped at `MAX_STORED_TURNS`, expiring
`CONVERSATION_TTL_DAYS` after the last turn. `append_turn(expected_turns)` is an optimistic
concurrency check; a mismatch produces `conflict`. Usage is always recorded in `finally`, even on
failure.

## Conventions

- Production code has no comments; the reasons behind the code are written in the tests.
- Tests: `test_<unit>_<scenario>_<expected>`, `# Arrange / # Act / # Assert` comments,
  `pytest.mark.parametrize` tables with `ids=`, and a small hand-written fake per test file (no
  mongomock). Fake databases are plain dicts accessed as `db[name]`, so production code reaches
  collections with `db[name]` (and `.with_options(...)`), never `db.get_collection(...)`.
- Change `app.dependency_overrides` only inside `yield` fixtures, so a failing assert can't leak
  overrides into later tests. API tests override `get_database` and `current_principal`, and
  routes that write in a transaction also `get_transaction_runner` (`lambda callback: callback(None)`).
- Integration tests create throwaway `test_catalog_<hex>` / `test_invoices_<hex>` databases and
  drop them afterwards; they never write to `invoices_db` (only `test_vocab_hygiene` reads it).
  The CAP lab writes only to `cap_lab_<run>` databases and removes them and its rollback files.
- `seed/`, `deploy/` and `scripts/` are deliberately not unit-tested: they are verified by running
  them against a live stack.
- Commits: `type(scope): sentence` (`feat(mongo):`, `fix:`, `chore:`, ...).

## Don't "fix"

`httpx2` and `fastapi.sse` (`EventSourceResponse`, `ServerSentEvent`) are real modules in this
environment (FastAPI 0.141, anthropic 1.6.0). The single quotes around the Mongo URIs in `.env`
are required.
