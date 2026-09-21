# CLAUDE.md

FastAPI + MongoDB API for a B2B hardware distributor: a faceted product catalog, invoice listing
and analytics, and two Claude-powered chat assistants that answer only from tool results: a
customer-facing product advisor and an internal invoice analyst.

## Commands

```bash
./run.sh                                      # docker compose mongo + uvicorn --reload on :8000
./venv/bin/python -m pytest                   # unit + api (integration excluded by addopts)
./venv/bin/python -m pytest -m integration    # needs mongo on :27017, skips if unreachable
./venv/bin/python -m pytest --cov             # branch coverage, fail_under = 85
python seed/load_to_mongo.py                  # invoices from seed/dataset.csv, invoice indexes (run first)
python seed/generate_invoice_items.py         # invoices.lines, products, product indexes
python evals/run.py [--level functional|e2e|all] [--case ID]   # live model eval, costs tokens
```

The `.env` file needs `API_KEY` (read at import, so the app won't start without it). It also takes
`MONGO_URI`, `MONGO_DB_NAME` (default `invoices_db`) and `ANTHROPIC_API_KEY` (without it, `/chat`
returns 503).

## Map (`src/app`)

```
main.py          app assembly; global PyMongoError -> 503 handler; GET / serves static/chat.html
config.py db.py  env; module-level MongoClient behind get_database() (DI seam)
security.py      X-API-Key header, secrets.compare_digest; every router depends on it
limits.py        ALL numeric bounds (BSON-safe caps, page sizes, chat caps). Never inline a bound.
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
  service.py     list_invoices / analyze_invoices: the controller both the API and the analyst call
charts/
  enums.py       ChartType (line/bar/stacked), ChartMetric (+ METRIC_FIELDS: metric -> analytics row key)
  schemas.py     ChartParams(InvoiceAnalyticsParams): chart_type, metric, rejects unplottable combinations
  render.py      PURE: analytics rows -> PNG bytes. Figure + FigureCanvasAgg, never pyplot
  storage.py     charts collection: save_chart/get_chart/recent_charts, PNG as Binary, TTL expiry
  service.py     chart_analytics() = analyze_invoices -> render -> store, returns the rows plus chartId
assistant/
  profiles.py    AssistantName, Profile (model, prompt, max_tokens, request options), ADVISOR, ANALYST
  prompts.py     SYSTEM_PROMPT + OUT_OF_SCOPE_REPLY (advisor), ANALYST_PROMPT + ANALYST_OUT_OF_SCOPE_REPLY
  tools.py       tool defs, all static; TOOLS[assistant] is the assistant's set
  dispatch.py    run_tool(): name -> handler, re-validates input, strips _id/tier, JSON out;
                 returns ToolOutput(content, artifact) so a tool can announce a stored chart
  chat.py        build_request(profile), agent loop, streaming, retries, ChatError codes, tracing
  memory.py      in-process LRU ConversationStore, one per assistant
  usage.py       token/cost rollup -> chat_usage collection (PRICE table keyed by model id)
routers/         products.py (+ /facets), invoices.py (+ /analytics), chat.py (SSE),
                 charts.py (GET /charts?conversation_id, GET /charts/{id}/image)
```

Outside `src/app`: `tests/{unit,api,integration}`, `evals/` (cases + graders comparing the
model's tool calls and answers with gold queries), `seed/` (dataset and loaders; `products.py`
holds the catalog and `USE_CASE_TAGS`, `indexes.py` the complete index set). Empty or placeholder: `src/app/utils/`, `README.md`.

## Design decisions that matter

- **One validation path, two entry points.** `SearchProductsInput` subclasses `ProductSearchParams`
  and changes only the page-size default and cap. HTTP requests and model tool calls go through the
  same Pydantic model, `search_catalog`, and filter builder. The model is an untrusted caller.
- **Static vocabulary, live facets.** Filter values are `StrEnum`s in `catalog/enums.py`, not
  `distinct()`: the tool schema is deterministic (prompt-cache stable, exactly unit-testable), and
  a typo in the data can't become a valid value. Pydantic rejects unknown values (HTTP 422, tool
  `is_error` listing the allowed values). `/products/facets` and `get_product_facets` still read
  `distinct()` live, to report what the catalog actually holds. The app never writes products;
  the catalog is `seed/products.py`. Adding a value = enum + seed product;
  `tests/unit/test_seed_catalog.py` requires seed values == enum values, and the integration
  `test_vocab_hygiene` requires every value in the served `invoices_db` to be an enum value. If
  products ever arrive at runtime, load the vocabulary once at startup into a frozen snapshot
  instead of going back to per-request `distinct()`.
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
  embedded in each invoice and count invoices, not lines. Periods sort chronologically and default to `MAX_ANALYTICS_ROWS`, so a trend
  isn't cut. `coverage` always spans the whole collection, so an empty period can still name the
  data range. Query dates must be `datetime` (BSON can't encode `date`); `overdue` means open and
  due before midnight of `as_of` (default today).
- **Charts are drawn from a query, never from the model's numbers.** `chart_invoices` takes the
  same filters as `analyze_invoices`, runs that controller, and renders its rows; the model never
  supplies a data point, so the cardinal rule above still holds. It returns the rows *and* a
  `chartId`, so one call feeds both the table and the picture (the analyst may also call
  `analyze_invoices` first, or chart twice to compare views). The PNG is never sent back to the
  model. `render.py` uses `Figure` + `FigureCanvasAgg` directly, never `pyplot`: the handlers run
  in FastAPI's threadpool and pyplot's global figure registry is not thread-safe. One subplot per
  currency, never a shared y-axis. `stacked` derives its segments server-side
  (`cleared = total - open`, `current = open - overdue`, `overdue`), clamping cent-rounding to 0,
  because open is part of total and overdue part of open. No rows -> `chartId` is null, not an
  error. Charts live in the `charts` collection as `bson.Binary` (tens of KB, far under the 16 MB
  doc cap) with a TTL index; `ChartParams` rejects combinations the rows cannot produce (a line
  over customers, `units` without a line-grain grouping) so the model gets a correctable
  `is_error`. `GET /charts/{id}/image` is behind `require_api_key` like every other route, so the
  page fetches it with the header and renders a blob URL rather than a plain `<img src>`.
- **Two assistants, routed explicitly.** `ChatRequest.assistant` (default `advisor`) picks a frozen
  `Profile`; each assistant has its own conversation store, so a conversation never changes model,
  prompt or tools, and invoice figures never reach the customer-facing advisor's context. No
  classifier hop. The analyst runs Sonnet 5 with adaptive thinking, `effort: medium`, a 90 s read
  timeout and today's date in a second, uncached system block after the cached prompt.
  `eager_input_streaming` stays off (inputs are tiny and strict validation is kept); refusal
  `fallbacks` are not used (not a Sonnet 5 default; `refused` handles it).
- **Pure modules.** `catalog.enums/query/schemas`, `invoices.enums/query/schemas` and
  `charts.enums/schemas/render` must not import `app.config` or `app.db` (enforced by a
  subprocess test).
- **MongoDB layout.** `seed/indexes.py` is the whole index set; both loaders run `sync_indexes`,
  which drops anything undeclared. Invoice indexes follow equality → sort → range with an `_id`
  tiebreaker; products keep only `(category, listPrice)` (52 docs fit in one page). A new query
  shape needs a row in `tests/integration/test_query_plans.py`, which explains it and asserts its
  index, a key count bounded by the page, and no index intersection. Invoice lists are `find` +
  `count_documents`, not `$facet` (the facet read every match to count it). Line items are
  embedded as `invoices.lines` (≤ 5, immutable), so there is no `invoice_items` collection. The
  `charts` collection is the one thing the app writes besides `chat_usage`; its TTL index is what
  prunes it, so every chart must carry `expiresAt`. The
  customer filter is `customer.number` or a left-anchored prefix on `customer.nameLower`: an
  unanchored or `/i` regex can't be index-bounded. No sparse indexes on fields stored as explicit
  `null`. Long field names stay (block compression is `zstd`, set in `docker-compose.yml`).
  Standalone mongod: `w:1`, `readConcern local`, `primary` are the driver defaults and the only
  meaningful values, so none are set. On a replica set, pin `chat_usage` inserts to `w:1` (5.0+
  defaults to majority) and consider `secondaryPreferred` for analytics.

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

SSE events from `POST /chat`: `conversation` → (`text` | `tool` | `chart`)* → `done {truncated}` | `error {code,message}`.
A `chart {chart_id}` event is emitted when a tool returns a `ToolOutput.artifact`; charts are not
saved to memory. Only the user's text and the final answer text are saved to memory, never tool blocks.
`append_turn(expected_length)` is an optimistic concurrency check; a mismatch produces `conflict`.
Usage is always recorded in `finally`, even on failure.

## Conventions

- Production code has almost no comments; the reasons behind the code are written in the tests.
- Tests: `test_<unit>_<scenario>_<expected>`, `# Arrange / # Act / # Assert` comments,
  `pytest.mark.parametrize` tables with `ids=`, and a small hand-written fake collection per test
  file (no mongomock).
- Change `app.dependency_overrides` only inside `yield` fixtures, so a failing assert can't leak
  overrides into later tests. The root `tests/conftest.py` sets `API_KEY`.
- Integration tests create throwaway `test_catalog_<hex>` / `test_invoices_<hex>` databases and
  drop them afterwards; they never write to `invoices_db` (only `test_vocab_hygiene` reads it).
- Commits: `type: sentence` (`refactor:`, `test:`, `chore:`, ...).

## Don't "fix"

`httpx2` and `fastapi.sse` (`EventSourceResponse`, `ServerSentEvent`) are real modules in this
environment (FastAPI 0.141, anthropic 1.6.0).
