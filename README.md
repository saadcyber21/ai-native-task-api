# AI-Native Task API

A beginner-friendly REST API that turns plain-English requests into structured tasks and recurring schedules. It runs without an LLM using a deterministic parser; set `OPENAI_API_KEY` to enable structured-output generation and AI-assisted task breakdown.

## Features

- Create, validate, list, retrieve, and delete tasks.
- Natural-language task parsing with optional LLM structured outputs.
- Validated recurrence rules (`daily`, `weekly`, `monthly`).
- `Idempotency-Key` support on task creation and breakdown.
- Break large tasks into actionable subtasks.
- Stable validation/error contract and generated OpenAPI docs.
- SQLite persistence for local development.

## Quick start

Requires Python 3.11+.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

OpenAPI UI: <http://127.0.0.1:8000/docs>  
Health check: <http://127.0.0.1:8000/health>

## API examples

```bash
curl -X POST http://127.0.0.1:8000/v1/tasks/from-text -H "Content-Type: application/json" -H "Idempotency-Key: create-report-001" -d '{"text":"Remind me to send the weekly project report every Friday"}'
```

```bash
curl -X POST http://127.0.0.1:8000/v1/tasks/breakdown -H "Content-Type: application/json" -H "Idempotency-Key: plan-launch-001" -d '{"text":"Prepare a product launch"}'
```

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./tasks.db` | SQLAlchemy database URL |
| `OPENAI_API_KEY` | unset | Enable LLM structured outputs |
| `OPENAI_MODEL` | `gpt-4o-mini` | Model with structured-output support |

Do not commit credentials. Copy `.env.example` to `.env` for local configuration.

## Error contract

Errors use `{"error":{"code":"...","message":"...","details":[]}}`. Invalid input returns 422, missing tasks return 404, conflicting reuse of an idempotency key returns 409, and unexpected errors return a generic 500 without leaking internals.

## Tests

```bash
pytest
```

## Scope

This is a learning-oriented starter, not a production task-management platform. Before production, add authentication/authorization, migrations, distributed idempotency storage, rate limiting, observability, and a managed database. Idempotency currently persists in the same database as tasks.
