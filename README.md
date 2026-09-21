# Claude ERP Assistant

A small **ERP** (Enterprise Resource Planning) slice for a B2B computer hardware distributor,
covering the two things such a company spends its day on: what we sell (a faceted product
catalog) and who owes us money (accounts receivable, analytics and charts).

On top of the REST API sit two Claude assistants. An **Advisor** (Haiku 4.5) helps staff serving a customer; an **Analyst** (Sonnet 5)
answers finance questions with figures and charts.

Built while working toward the **Claude Certified Developer** certification. The domain is a
vehicle; the point was tool use, prompt caching, streaming, evals and a real error taxonomy
instead of a toy chat wrapper.

## Demo

The advisor searches the catalog and quotes SKUs and list prices exactly as returned, never
naming a product it did not just retrieve.

![Product lookup](media/lookup.gif)

One `chart_invoices` call returns the rows *and* a rendered PNG, so the answer carries a table and
a picture. USD and CAD get separate panels on separate scales; they are never added or compared.

![Chart and table analysis](media/chart.gif)

The advisor estimates the memory a workload needs, states the estimate, then proposes a
configuration inside the budget and totals it from returned prices.

![Recommended setup](media/propose_a_build.gif)


```mermaid
flowchart TB
    UI["Browser · static/chat.html"]

    subgraph APP["FastAPI · X-API-Key on every router"]
        direction TB
        RT["routers/<br/>products · invoices · chat · charts"]

        subgraph AST["assistant/"]
            direction LR
            LOOP["chat.py<br/><i>agent loop · streaming · retries<br/>ChatError taxonomy</i>"]
            DISP["dispatch.py<br/><i>re-validates model input</i>"]
            BOOK["memory.py · usage.py<br/><i>LRU history · token and cost</i>"]
        end

        subgraph DOM["domain · pure query builders"]
            direction LR
            CAT["catalog/"]
            INV["invoices/"]
            CHT["charts/<br/><i>render (Agg) · storage</i>"]
        end
    end

    DB[("MongoDB 7 · zstd<br/>products · invoices.lines<br/>chat_usage · charts (PNG + TTL)")]
    API["Anthropic API<br/>Sonnet 5 · Haiku 4.5<br/><i>prompt caching · adaptive thinking</i>"]

    UI -- "SSE: conversation → text / tool / chart → done" --> RT
    RT --> AST
    RT --> DOM
    LOOP <--> API
    LOOP --> DISP
    LOOP --> BOOK
    DISP --> DOM
    CHT -- "renders the rows analyze_invoices returned" --> INV
    DOM --> DB
    BOOK --> DB

    classDef store fill:#0072B2,stroke:#04395e,color:#fff
    classDef ext fill:#D55E00,stroke:#7a3600,color:#fff
    class DB store
    class API ext
```


## Features

* **Tool use with one validation path.** `SearchProductsInput` subclasses the HTTP
  `ProductSearchParams`, so model calls and REST requests share one Pydantic model. The model is
  treated as an untrusted caller and its input is re-validated on every call.
* **Strict *and* non-strict tool schemas, deliberately.** Product tools are `strict: true`.
  Invoice tools are not: strict decoding emits optional properties in schema order, and a filter
  the model reached for after a later one was silently dropped (measured live, Q1 dates vanished
  and all time totals came back). Pydantic is the guard instead.
* **Static vocabulary.** Filter values are `StrEnum`s rather than a live `distinct()`, so the tool
  schema stays prompt cache stable and a typo in the data can never become a valid filter value.
* **Prompt caching.** `cache_control` on the system block and at request top level; the analyst's
  volatile "today's date" sits in a second, uncached block so the cached prefix never shifts.
* **Streaming agent loop.** SSE `conversation → (text | tool | chart)* → done | error`, bounded at
  six model calls per turn.
* **An error taxonomy that respects what was already sent.** The SDK retries what is safely
  repeatable; the app handles the rest. Mid stream failures retry *only if no text has streamed
  yet*, because text already sent cannot be taken back. Every `stop_reason` maps to an outcome,
  and a truncated `tool_use` is never executed.
* **Self correcting tool errors.** Bad model input becomes an `is_error` tool_result describing
  the problem, so the model fixes itself instead of the turn dying.
* **Adaptive thinking** on the analyst (`effort: medium`, 90 s read timeout).
* **Token and cost tracking** into `chat_usage` with a per model price table, recorded in
  `finally` even when the turn fails.
* **Server rendered charts** from DB rows via `Figure` + `FigureCanvasAgg`, never `pyplot`, whose
  global figure registry is not thread safe under FastAPI's threadpool. Stored as PNG in MongoDB
  with a 30 day TTL.

## Tests and evals

618 tests at 98.95% branch coverage (gate 85%): pure query builders and schemas, the agent loop and its failure modes.

Evals are the part that matters for an LLM feature, because a passing test suite says nothing
about whether the model *behaves*. `evals/` holds 31 cases (21 advisor, 10 analyst) graded
programmatically rather than by vibes:

* **Retrieval** graders re-run the model's own tool calls against MongoDB and compare the returned
  ids with a gold query, either exactly or as a superset.
* **Grounding** graders extract every SKU and price from the answer and fail it if the product was
  never returned by a search in that turn, or if the stated price differs from the catalog. This
  is what catches a hallucinated product that reads perfectly.
* **Figure** graders check the analyst actually stated the number the database produced.
* **Chart** graders assert the requested `chart_type` was the one drawn.
* **Refusal** cases require the exact out of scope sentence and zero tool calls.
* Two levels: `functional` grades the first model call, `e2e` drives the whole SSE flow including
  multi turn conversations.

```bash
python evals/run.py [--level functional|e2e|all] [--case ID]
```

They call the live API and cost tokens, so they stay out of CI and are run deliberately.

## Tech stack

| | |
|---|---|
| Language | Python 3.14 |
| API | FastAPI 0.141 · Pydantic 2.13 · Uvicorn · SSE |
| Database | MongoDB 7 (zstd block compression) · PyMongo 4.18 |
| AI | Anthropic SDK 1.6 · Claude Sonnet 5 · Claude Haiku 4.5 |
| Charts | Matplotlib 3.11 (Agg backend) |
| Data prep | pandas |
| Tests, CI | pytest · branch coverage · GitHub Actions |
| Infra | Docker Compose |

## Data

Neither dataset is proprietary and neither is real. The invoices come from an accounts receivable
dataset on **Kaggle**: 48,839 invoices in USD and CAD, posted between 2018-12-30 and 2020-05-22.
The 52 product hardware catalog was **generated with an LLM**, plausible GPUs, CPUs, RAM and
storage with consistent specs and list prices, and invoice line items are then synthesised against
it and reconciled to each invoice's existing total.

Because the invoice data ends in May 2020, "overdue" as of today means everything is overdue, so
pass an explicit `as_of` date when demoing that.

## In development

Still being built. Next up:

* **Automatic model routing.** The assistant is currently chosen explicitly. The plan is to route
  per question, keeping cheap lookups on Haiku and escalating to Sonnet only when the question
  actually needs the reasoning, without losing the guarantee that a conversation never changes
  model, prompt or tool set halfway through.
* **Warranty and technical detail RAG.** Retrieval over product manuals, spec sheets and warranty
  terms, so the advisor can answer "how long is the warranty on this card" or a question about a
  spec the catalog does not carry, still grounded in a retrieved source rather than model memory.

