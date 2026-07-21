# Copilot Instructions — Jetson AGX Orin LLM Serving Node

## Project Overview

This repository runs **only the LLM serving node** for a Jetson AGX Orin,
intended for LAN access by a LibreChat instance hosted elsewhere. The stack
consists of:

- **Ollama** — primary LLM runtime.
- **FastAPI router** (optional `proxy` profile) — OpenAI-compatible endpoint
  that applies model policy (e.g. `keep_alive`) and a `think` control policy
  before forwarding to Ollama's native `/api/chat`.
- **`router/model_policy.yml`** — per-model defaults and policy rules.
- **`docker-compose.yml`** + **`.env.example`** — deployment surface.

Target hardware: **NVIDIA Jetson AGX Orin / Thor**.

## Source of Truth: `README.md`

**`README.md` is the canonical, living description of this service.**
Models, ports, env vars, policy rules, defaults, profiles, and operational
behavior are all expected to evolve — this instructions file deliberately does
**not** pin any of those values.

When working in this repo, Copilot must:

1. **Read `README.md` first** to determine the current state — current model
   IDs, current ports, current `keep_alive` and `think` defaults, current
   policy tool lists, current env var names, etc. Do not rely on memory of
   prior versions or on examples in this file.
2. **Treat `README.md` as a deliverable that ships with every change.** Any PR
   that adds, removes, renames, or changes the behavior of:
   - a model
   - an env var
   - a port or bind address
   - a compose service or profile
   - a routing/policy rule (e.g. `think`, `keep_alive`, tool matching)
   - an HTTP route, header, or request/response shape

   **must update `README.md` in the same commit/PR.** If the README is not
   updated alongside such a change, flag it explicitly in suggestions and PR
   descriptions.
3. **Do not invent values.** If a setting is needed but not documented in
   `README.md`, ask or propose it as a new documented setting rather than
   silently choosing one.
4. **Do not assume stability.** Models, capabilities, defaults, and policies
   are expected to change. Avoid suggestions whose only justification is
   "this is how it currently works" — instead, justify by what `README.md`
   and `router/model_policy.yml` say *now*.

## Configuration Layout

- **`router/model_policy.yml`** is the single source of truth for per-model
  defaults and policy rules. Code should read from it; do not hardcode model
  names, `keep_alive` values, tool lists, or thresholds in Python.
- **`.env.example`** must list every env var the stack reads, with a short
  comment. Add new vars here in the same change that introduces them.
- **`docker-compose.yml`** owns ports, profiles, and service wiring. Keep
  service and profile names aligned with whatever `README.md` documents.

## Network and Security

- Bind addresses, exposed ports, and the LAN-vs-loopback posture are
  decisions documented in `README.md`. Match the README; do not change the
  posture unilaterally.
- Access control is delegated to the host firewall / router ACLs unless
  `README.md` says otherwise. Do not silently add auth middleware — any auth
  must be an opt-in, documented feature.

## Policy & Routing Behavior

The router applies policy (e.g. `think`, `keep_alive`, tool-based rules,
size/summarization heuristics, and header overrides such as
`X-Ollama-Think`). The exact rule set, precedence, env vars, and header
names are described in `README.md` and encoded in
`router/model_policy.yml`.

When editing policy code:

- Keep precedence order **identical** to what `README.md` documents.
- Keep policy logic **pure and unit-testable**: separate decision functions
  from transport (httpx) code.
- Drive matching (tool names, thresholds, model IDs) from
  `router/model_policy.yml`, not from literals in `.py` files.
- If you change precedence, add a rule type, or change a header/env var
  name, update `README.md` and `.env.example` in the same change.

## Coding Conventions

### Python (router)

- Target **Python 3.11+**.
- Use `fastapi` + `pydantic v2` + `httpx.AsyncClient`. No `requests`, no
  blocking I/O in request paths.
- Type-hint all public functions; prefer `from __future__ import annotations`.
- Format with **black** (line length 100); lint with **ruff**.
- Log via stdlib `logging` (`logger = logging.getLogger(__name__)`); never
  `print()` in request handlers.
- Surface upstream Ollama errors with their original status code where
  reasonable; wrap unexpected errors as HTTP 502 with a structured body.
- Keep cold-start light — avoid heavy optional dependencies.

### YAML / Compose / env

- Keep `docker-compose.yml`, `.env.example`, `router/model_policy.yml`, and
  `README.md` mutually consistent in every change.
- Inline-comment non-obvious defaults in `.env.example`.

### Shell / curl examples in docs

- Use `127.0.0.1` (not `localhost`) for consistency with existing examples.
- Pipe JSON through `| jq .`.

## Testing

- Tests live under `router/tests/` using `pytest` + `pytest-asyncio` +
  `respx` for mocking httpx calls to Ollama.
- New policy branches must cover both the triggered and non-triggered case,
  plus any override path (e.g. header overrides).
- Tests must not hit a real Ollama instance.
- When tests encode expected model IDs or defaults, source them from
  `router/model_policy.yml` (fixtures), not from hardcoded literals — so
  that policy changes don't silently break tests for the wrong reason.

## Commit Messages

Follow **Conventional Commits**. See `.github/commit-style.md` for the full
style guide used in this repo.

## Pull Requests

Use the template at `.github/PULL_REQUEST_TEMPLATE.md`. Every PR that
changes runtime behavior must also update `README.md`.
