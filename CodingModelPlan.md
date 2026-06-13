#Coding Model Plan

## Summary Table

| Phase | Concern | What it accomplishes | Dependencies |
|---|---|---|---|
| **Phase 0** | Zoo Code + Backups | Validate the current Zoo Code config end‑to‑end on a real task, then snapshot everything that's about to change. | None |
| **Phase 1a** | Orin (background) | Pull Q6 coder, embedder, FIM model into Ollama. | Phase 0 backups |
| **Phase 1b** | Orin (parallel with 1a) | Refactor the warmup script and FastAPI router into a profile model (`chat` vs `roo`), add a `/profile` endpoint. | Phase 0 backups |
| **Phase 2** | Orin | Switch hot path to Q6, raise `num_ctx` on `qwen3-coder:30b` to the real ceiling, stand up `/v1/embeddings` and `/v1/verify`, update `model_policy.yml`. | Phase 1a, 1b |
| **Phase 3** | LibreChat | Drop and recreate the pgvector schema, repoint RAG to the Orin embedder, upgrade Whisper, pin LibreChat to a digest so the `OpenAIImageToolsWrapper.js` mount survives updates, stand up the MCP bridge for Firecrawl + SearXNG. | Phase 2 endpoints |
| **Phase 4** | Zoo Code | Bump Zoo Code's context window to the new ceiling, add reasoner + verifier providers, create the `Verify` custom mode, wire MCP servers, install Continue.dev for autocomplete, define the disabled OpenAI fallback. | Phase 2 verifier, Phase 3 MCP bridge |
| **Phase 5** | Hardening (deferred) | Bearer auth on Orin router + MCP bridge, HTTPS via the existing nginx, OpenAI spend caps, monitoring. | All previous phases stable |

The summary deliberately mirrors the original structure. The detail below fills in the gaps the v2 plan left open: backups, `num_ctx` ceiling discovery, `model_policy.yml` updates, pgvector dimension change, image‑tool wrapper survival, MCP transport choice, acceptance tests, and rollback paths per phase.

---

## Phase 0 — Zoo Code baseline + backups

**Concern:** Zoo Code (validation), Cross‑cutting (backups).

Zoo Code is already installed with the conservative profile you posted (`orin-coder`, ctx 4096, `X-Ollama-Think: false`, tools/images/reasoning off). Before we touch anything, prove it actually works end‑to‑end, then snapshot everything that's about to change.

### Steps

1. **Validate the current Zoo Code profile on a real task.** Open a small repo. In Code mode, ask Zoo to "rename function X to Y and update all callers." Confirm:
   - The diff renders
   - `apply_diff` succeeds
   - Streaming works without truncation at 4096
   - No `400 context window exceeded` errors from the router
   
   If you hit context‑exceeded errors at 4096, that means your *system prompt + first user turn* already overflows. That's the symptom that motivates Phase 2's `num_ctx` work — don't fix it yet, just record it.

2. **Snapshot the Orin repo.** On the Orin: `git checkout -b pre-v3-baseline && git commit -am "snapshot before v3"` in the Model‑Server‑Orin‑64GB clone. Also copy the active `warmup.sh`, the router source tree, and `model_policy.yml` to `~/pre-v3-backup/`.

3. **Record the current `model_policy.yml` ceilings.** `cat model_policy.yml > ~/pre-v3-backup/policy.snapshot.yml`. This is the file Zoo Code's "Model ID must match exactly" rule is enforcing against — we'll be editing it in Phase 2.

4. **Backup LibreChat persistent volumes.** From the LibreChat host:
   ```
   tar -czf /home/SharedData/backup/ask/pre-v3-mongo.tgz /home/SharedData/ask/data-node
   tar -czf /home/SharedData/backup/ask/pre-v3-pgdata2.tgz /home/SharedData/ask/pgdata2
   tar -czf /home/SharedData/backup/ask/pre-v3-meili.tgz /home/SharedData/ask/meili_data_v1.12
   cp /home/docker-config/ask/OpenAIImageToolsWrapper.js /home/SharedData/backup/ask/
   cp /home/docker-config/ask/librechat.yaml /home/SharedData/backup/ask/
   cp /home/docker-config/ask/.env /home/SharedData/backup/ask/.env.pre-v3
   ```
   The `pgdata2` snapshot is the critical one — Phase 3 drops the RAG schema because embedding dimensions change.

5. **Pin LibreChat to a digest.** Your `OpenAIImageToolsWrapper.js` bind‑mounts over an internal path inside the LibreChat image. If `:latest` updates and that internal path moves, the mount silently no‑ops and image gen breaks. Lock the image:
   - `docker inspect registry.librechat.ai/danny-avila/librechat-dev:latest | jq -r '.[0].RepoDigests'`
   - Edit your override compose: `image: registry.librechat.ai/danny-avila/librechat-dev@sha256:<digest>`
   - `docker compose up -d` and verify nothing changed.

### Acceptance
- Zoo Code completes a small multi‑file rename against the current Orin endpoint without errors.
- All five backup artifacts exist on disk.
- LibreChat is now pinned by digest; `docker compose ps` confirms it's the same digest after restart.

### Rollback
- None needed at this phase — nothing destructive happened.

---

## Phase 1a — Orin model pulls (background)

**Concern:** Orin.

### Steps

1. Verify disk headroom on the Orin: `df -h` — need ~80 GB free.
2. In a tmux/nohup session, run:
   ```
   ollama pull qwen3-coder:30b-a3b-q6_K
   ollama pull qwen3-embedding:4b
   ollama pull qwen2.5-coder:3b-base
   # optional, only if you want a hard-mode coder:
   ollama pull qwen3-coder:30b-a3b-q8_0
   ```
3. After completion, run `ollama list` and record exact tag names. You'll need these strings verbatim in `model_policy.yml` and in Zoo Code's Model ID field.

### Acceptance
- All requested tags appear in `ollama list`.
- Disk still has >20 GB free.

### Rollback
- `ollama rm <tag>` for any model that pulled corrupted (rare).

---

## Phase 1b — Orin warmup profile refactor

**Concern:** Orin. Runs in parallel with 1a — pure scripting against the existing Q4 setup.

This is the first place you should drive work using Zoo Code from Phase 0.

### Steps

1. **Design the profile YAML schema.** Each profile lists models with: `tag`, `keep_alive`, `num_ctx`, `think` default, and a `role` field (`coder`, `reasoner`, `verifier`, `embedder`, `fim`, `chat`). Example `profiles/chat.yaml`:
   ```yaml
   profile: chat
   models:
     - tag: qwen3.6:35b-a3b
       role: reasoner
       keep_alive: -1
       num_ctx: 16384         # to be tuned in Phase 2
       think: true
     - tag: qwen3-coder:30b
       role: coder
       keep_alive: -1
       num_ctx: 4096          # current conservative ceiling
       think: false
   ```
   And `profiles/roo.yaml`:
   ```yaml
   profile: roo
   models:
     - tag: qwen3-coder:30b   # bumped to q6_K in Phase 2
       role: coder
       keep_alive: -1
       num_ctx: 4096
       think: false
     - tag: qwen3.6:35b-a3b
       role: reasoner
       keep_alive: -1
       num_ctx: 16384
       think: true
   ```
   Both profiles will gain the embedder in Phase 2 because LibreChat needs it regardless of profile.

2. **Refactor `warmup.sh`** into `warmup.sh <profile>`. It should:
   - Read the YAML
   - For every model currently running that's *not* in the new profile: `ollama stop <tag>`
   - For every model in the new profile: `ollama generate` with `keep_alive`, `num_ctx`, and the right `think` policy to warm it
   - Write `/var/run/model-server/active_profile` containing the profile name

3. **Wrap it with `switch_profile.sh <profile>`** that validates the argument, calls `warmup.sh`, and prints the new active profile after a 5‑second settle.

4. **Update the FastAPI router** to:
   - Read `/var/run/model-server/active_profile` on each request (or cache with short TTL)
   - Add `GET /profile` returning `{"profile": "chat"|"roo", "models": [...from yaml...]}`
   - Optionally 503 chat completions to a model not in the active profile, rather than silently cold‑loading it

5. **Update the systemd unit** so on boot the warmup script runs the `chat` profile by default. Add `After=ollama.service` and `Requires=ollama.service`.

6. **Smoke test:** `switch_profile.sh roo`, hit `GET /profile`, confirm. Switch back. Reboot the Orin; confirm `chat` profile auto‑loads.

### Acceptance
- `/profile` returns correct JSON in both states.
- `ollama ps` matches what `/profile` claims.
- Reboot recovers to `chat` profile without manual intervention.

### Rollback
- `git checkout pre-v3-baseline` in the model‑server repo.
- Restore the old systemd unit from `~/pre-v3-backup/`.

---

## Phase 2 — Orin Q6 cutover, embedder + verifier endpoints, `num_ctx` lift

**Concern:** Orin. The foundation that both LibreChat (Phase 3) and Zoo Code (Phase 4) consume. **This phase contains the most important correctness fix in the entire plan.**

## Why this phase is now larger than before

Your analysis surfaced a silent-truncation footgun that v3 missed entirely:

- The Ollama runtime keys its loaded model instance on `num_ctx`. If a request arrives with a different `num_ctx` than the loaded instance — *including absent*, which Ollama treats as the default 4096 — Ollama unloads and reloads the model at the new size. The warm 16384 cache is evicted and the prompt is silently truncated to 4096.
- The FastAPI router translates OpenAI requests to Ollama and forwards a small allow-list of options (temperature, top_p, max_tokens, …). **`num_ctx` is not in the OpenAI schema, so the router never sends it.**
- Result: Roo sends a standard OpenAI request → router forwards without `num_ctx` → Ollama reloads at 4096 → warm cache gone, prompt truncated. This happens on the **first real Roo request** after warmup.

So Phase 2 is no longer just "switch to Q6, add two endpoints." It's "make the router and the warmup script agree on `num_ctx`, atomically, for every model in every profile, on every request."

## Interim safety note

Before starting Phase 2 work, update the Zoo Code `orin-coder` profile from Context window 4096 → **8192**. This is the conservative-but-usable interim value until the router fix below lands. Do **not** bump to 16384 yet; until the router injects `num_ctx`, any request whose prompt exceeds 4096 tokens will be silently chopped.

## Steps

### 1. Discover the real `num_ctx` ceiling per model per profile

With the `roo` profile active, test progressively to find the highest `num_ctx` that fits without OOM and leaves ≥1 GB headroom. Repeat for the `chat` profile (tighter VRAM budget because two large models coexist warm).

```bash
for ctx in 4096 8192 12288 16384 24576 32768; do
  ollama stop qwen3-coder:30b-a3b-q6_K 2>/dev/null
  curl -s http://localhost:11434/api/generate \
    -d "{\"model\":\"qwen3-coder:30b-a3b-q6_K\",\"prompt\":\"hi\",\"options\":{\"num_ctx\":$ctx},\"keep_alive\":\"5m\",\"stream\":false}" \
    -o /dev/null -w "ctx=$ctx http=%{http_code} "
  nvidia-smi --query-gpu=memory.used,memory.free --format=csv,noheader
done
```

Record the ceiling per `(profile, model)` pair. Likely outcomes: `qwen3-coder:30b-a3b-q6_K` at 16384 in `roo`, possibly 8192–12288 in `chat`. `qwen3.6:35b-a3b` at 32768 in both. `qwen3-embedding:4b` at 2048 is plenty (embedding chunks are short).

### 2. Extend `model_policy.yml` with per-profile `num_ctx` and an `options` block

Make the policy file the **single source of truth** that both the warmup script and the router read. The invariant: the `num_ctx` warmup uses for a model must equal the `num_ctx` the router sends for that model. If they differ by even one token, Ollama reloads.

Proposed schema (per-profile, per-model):

```yaml
profiles:
  roo:
    models:
      - model: qwen3-coder:30b-a3b-q6_K
        keep_alive: -1
        think: false
        num_ctx: 16384
        options:
          temperature: 0.1
          top_p: 0.9
          top_k: 40
          repeat_penalty: 1.05
      - model: qwen3.6:35b-a3b
        keep_alive: -1
        think: true
        num_ctx: 32768
        options:
          temperature: 0.3
          top_p: 0.9
          top_k: 40
      - model: qwen3-embedding:4b
        keep_alive: -1
        num_ctx: 2048
      - model: qwen2.5-coder:3b-base
        keep_alive: 5m
        think: false
        num_ctx: 4096
        options:
          temperature: 0.2
  chat:
    models:
      - model: qwen3.6:35b-a3b
        keep_alive: -1
        think: true
        num_ctx: 32768
        options: { temperature: 0.3, top_p: 0.9, top_k: 40 }
      - model: qwen3-coder:30b
        keep_alive: -1
        think: false
        num_ctx: 8192          # tighter than roo, two-warm budget
        options: { temperature: 0.1, top_p: 0.9, top_k: 40, repeat_penalty: 1.05 }
      - model: qwen3-embedding:4b
        keep_alive: -1
        num_ctx: 2048

# Fallback for any model not listed above; used by warmup and router alike.
defaults:
  num_ctx: 4096
  options:
    temperature: 0.7
    top_p: 0.9
```

The Modelfile defaults (temp 0.7, top_p 0.8, top_k 20) are tuned for chat, not code. Putting code-friendly sampling into the policy is the right place because it stays attached to the deployment, not the model itself.

### 3. Router change: inject `options.num_ctx` (and the rest of `options`) on every forwarded request

In `app.py` / `policy.py`, in the Ollama call builder, after profile + policy lookup:

```python
def build_ollama_options(client_request: dict, policy_entry: dict) -> dict:
    # Policy options are DEFAULTS. Client wins on conflict.
    policy_opts = dict(policy_entry.get("options") or {})
    policy_opts["num_ctx"] = policy_entry.get("num_ctx") or DEFAULTS["num_ctx"]

    client_opts = client_request.get("options") or {}
    # Merge: policy defaults first, client overrides last.
    merged = {**policy_opts, **client_opts}

    # Hard invariant: num_ctx ALWAYS comes from policy, never from client.
    # Otherwise Roo could accidentally trigger a reload.
    merged["num_ctx"] = policy_opts["num_ctx"]
    return merged
```

The two non-obvious bits:

- **Policy values are defaults that client requests override** — so if Roo sends `temperature: 0.1` explicitly, that wins over policy. Standard merge order.
- **`num_ctx` is the exception**: it must always come from policy, never from the client. The Ollama instance is keyed on this value; letting the client set it defeats the whole point of warmup.

If you want belt-and-suspenders, also strip `num_ctx` from the client request before the merge so it can't sneak in.

### 4. Router change: propagate sampling defaults for code use

The merge above covers this automatically — once policy `options` are populated, every code-targeted request gets temp 0.1 / top_p 0.9 / top_k 40 / repeat_penalty 1.05 unless the client overrides. No extra wiring needed.

### 5. Router change: startup self-check against `/api/show`

On router boot, after loading the active profile, call `POST /api/show` against Ollama for each model and compare the live Modelfile parameters against the policy. Log a clear warning if anything material disagrees, especially around `num_ctx` defaults. This catches the next person who edits one file without the other.

```python
async def selfcheck_on_boot():
    active = load_active_profile()
    for entry in active["models"]:
        show = await ollama.show(entry["model"])
        live_num_ctx = show.get("parameters", {}).get("num_ctx")
        if live_num_ctx and int(live_num_ctx) != entry["num_ctx"]:
            log.warning(
                "policy/modelfile num_ctx mismatch: model=%s policy=%s modelfile=%s — "
                "router will force policy value on every request",
                entry["model"], entry["num_ctx"], live_num_ctx,
            )
```

This is informational, not fatal. The router's `num_ctx` injection takes precedence regardless.

### 6. Router change: expose `num_ctx` in `/profile`

Already in v3 — extend the response shape so Zoo Code (and any preflight rule) can see the canonical ceiling:

```json
{
  "profile": "roo",
  "models": [
    {"model": "qwen3-coder:30b-a3b-q6_K", "num_ctx": 16384, "role": "coder"},
    {"model": "qwen3.6:35b-a3b",          "num_ctx": 32768, "role": "reasoner"},
    {"model": "qwen3-embedding:4b",       "num_ctx": 2048,  "role": "embedder"}
  ]
}
```

A `.roorules` preflight in Phase 4 can hit this endpoint and refuse to start if Zoo Code's configured window exceeds the active profile's `num_ctx` for the selected model.

### 7. Update `warmup.sh` to read the same policy file

The script should warm each model in the active profile by sending an `/api/generate` with the exact `options.num_ctx` from `model_policy.yml`. No hardcoded values anywhere else.

```bash
for entry in $(yq ".profiles.${PROFILE}.models[]" model_policy.yml -o=json -I=0); do
  model=$(echo "$entry" | jq -r .model)
  num_ctx=$(echo "$entry" | jq -r .num_ctx)
  keep_alive=$(echo "$entry" | jq -r .keep_alive)
  curl -s http://localhost:11434/api/generate -d "$(jq -nc \
    --arg m "$model" --argjson c "$num_ctx" --arg k "$keep_alive" \
    '{model:$m, prompt:"warm", options:{num_ctx:$c}, keep_alive:$k, stream:false}')" \
    > /dev/null
done
```

This guarantees warmup `num_ctx` == router-sent `num_ctx`. The single source of truth invariant holds.

### 8. Switch the `roo` profile to Q6

Edit `profiles/roo.yaml` (or the equivalent section of the unified `model_policy.yml`) to reference `qwen3-coder:30b-a3b-q6_K` with `num_ctx: 16384` and the code-tuned `options` block. Add `qwen2.5-coder:3b-base` with `keep_alive: 5m` for Continue.dev's FIM in Phase 4. `switch_profile.sh roo`. Confirm VRAM stays within budget.

### 9. Add `qwen3-embedding:4b` to both profiles with `num_ctx: 2048`

LibreChat needs the embedder regardless of which profile is active. Record the embedding dimension by inspecting a sample response — you'll need it for Phase 3's pgvector schema:

```bash
curl http://orin:4000/v1/embeddings \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen3-embedding:4b","input":"hello"}' | jq '.data[0].embedding | length'
```

### 10. Add `/v1/embeddings` to the router

Pass through to Ollama. Hard-code the model to `qwen3-embedding:4b` regardless of what the caller sends, so LibreChat can't accidentally request a different embedder and corrupt the vector store. The same policy merge logic from step 3 applies — embedder gets its `num_ctx: 2048` from policy automatically.

### 11. Add `/v1/verify` to the router

- Method: `POST`
- Input schema: `{spec: string, diff: string, files_context?: string}`
- Output schema: `{accept: bool, reasons: string[], severity: "low"|"medium"|"high"}`
- Model: hard-coded to `nemotron-cascade-2:30b`
- `think: true` regardless of header
- Inherits the policy merge from step 3, so `num_ctx` is correct on every call (this matters here too — the verifier is cold-loaded on demand, and you don't want its first invocation to load at 4096 when warmup would have used a higher value).
- System prompt template:
  ```
  You are a code verifier. You receive a SPEC describing intent and a DIFF
  of proposed code changes. Return STRICT JSON only, no prose, matching
  {"accept": boolean, "reasons": [string], "severity": "low"|"medium"|"high"}.
  - "accept" is true only if the diff fulfills the spec, introduces no
    obvious bugs, and changes nothing unrelated.
  - "reasons" lists concrete issues; empty array if accept is true.
  - "severity" reflects the worst issue found; "low" if accept is true.
  ```
- 120 s timeout. On timeout, return a structured error so Zoo Code can handle it gracefully.

### 12. Bump Zoo Code's context window — **only after steps 3 and 7 are merged together**

In the `orin-coder` profile:

- **Before router PR lands**: Context window stays at 8192 (the interim value from the top of this phase).
- **After router PR lands and warmup is rerun**: Context window → 16384.
- Max output tokens stays at 4096 throughout. That leaves ~12 K for prompt + history, which matches how `qwen3-coder` is typically benchmarked and avoids the model degrading near the top of its window.
- Model ID updates from `qwen3-coder:30b` → `qwen3-coder:30b-a3b-q6_K` (must match `model_policy.yml` exactly).

## Acceptance

This phase is the most failure-prone in the plan, so the acceptance bar is correspondingly higher:

1. `GET /profile` returns the new schema including `num_ctx` per model.
2. `model_policy.yml` and `warmup.sh` agree on `num_ctx` for every model — confirmed by running the warmup, then hitting `/api/ps` and checking the loaded `num_ctx`.
3. **No-reload test (critical):** With the `roo` profile freshly warmed, send a request through the router *without* `options.num_ctx` in the client payload. Then check `ollama ps` — the model's `last_used` should advance but `loaded_at` should not. If `loaded_at` changes, the model was reloaded and the router fix isn't working.
   ```bash
   ollama ps  # note loaded_at timestamp
   curl http://orin:4000/v1/ch

---

## Phase 3 — LibreChat: pgvector reset, RAG repoint, peripherals, MCP bridge

**Concern:** LibreChat. Consumes the Phase 2 embedder and prepares MCP tooling that Phase 4 will register into Zoo Code.

⚠️ Destructive on the RAG vector store. Phase 0 backups must exist.

### Steps

1. **Stop services that hold the vector DB open.**
   ```
   docker compose stop rag_api api
   ```
   Leave `vectordb` running — you need to issue SQL against it.

2. **Drop the RAG schema in pgvector.** Embedding dimension is changing (whatever your previous embedder produced → the 2560 from `qwen3-embedding:4b` you recorded in Phase 2). pgvector pins dimension at column creation, so you cannot just re‑embed — you must DROP and let the RAG API recreate.
   ```
   docker exec -it vectordb psql -U <user> -d <ragdb>
   \dt           -- list tables; identify the langchain_pg_embedding and langchain_pg_collection tables
   DROP TABLE langchain_pg_embedding CASCADE;
   DROP TABLE langchain_pg_collection CASCADE;
   \q
   ```
   (Exact table names may differ for your LibreChat version — list them first. Don't drop the database itself; just these tables.)

3. **Update `/home/docker-config/ask/.env`** to repoint embeddings at the Orin:
   ```
   RAG_EMBEDDINGS_PROVIDER=ollama
   RAG_OLLAMA_BASE_URL=http://ORIN_IP:11434
   EMBEDDINGS_MODEL=qwen3-embedding:4b
   ```
   Note: this points at Ollama directly (`:11434`), not the FastAPI router (`:4000`), because `librechat-rag-api-dev-lite` speaks the Ollama embed API natively. If you want all traffic to flow through the router for consistency, change to `RAG_EMBEDDINGS_PROVIDER=openai` + `OPENAI_API_BASE=http://ORIN_IP:4000/v1` + `EMBEDDINGS_MODEL=qwen3-embedding:4b` and verify the RAG API speaks the OpenAI embeddings format too. Pick one path and document it in `/home/docker-config/ask/README.md`.

4. **Bring services back.**
   ```
   docker compose up -d rag_api api
   ```
   Tail logs: `docker compose logs -f rag_api`. On first request you should see the new tables get created with the correct dimension.

5. **Validation re‑embed.** Through the LibreChat UI, upload a small text file. Confirm:
   - Upload succeeds.
   - A retrieval query against that file returns content.
   - `psql` against vectordb shows rows in `langchain_pg_embedding` with `vector(N)` matching your embedder dimension.

6. **Decide on pre‑existing corpora.** Any documents users uploaded under the old embedder are now orphaned (dropped in step 2). Either:
   - Accept the loss and re‑upload anything critical.
   - Script a re‑embed by reading the original files from `/home/SharedData/ask/uploads` and re‑posting them through LibreChat's RAG API.

7. **Upgrade Whisper for quality.** In `docker-compose.override.yml`:
   ```yaml
   whisper-full:
     environment:
       ASR_MODEL: large-v3
       ASR_ENGINE: faster_whisper
   ```
   `docker compose up -d whisper-full`. Test STT through the LibreChat UI with a real audio clip.

8. **Verify `OpenAIImageToolsWrapper.js` still loads.** Because LibreChat is pinned by digest (Phase 0 step 5), the internal path the file overrides hasn't moved. Confirm:
   ```
   docker exec -it LibreChat ls -la /app/api/app/clients/tools/structured/OpenAIImageToolsWrapper.js
   ```
   Generate an image through the UI to confirm the wrapper is functioning. If image gen calls OpenAI's DALL‑E, this is one of your few remaining OpenAI cost sources — review whether it's worth switching to a local image generator later (out of scope for this plan, just flagged).

9. **Reranker decision.** Your `local-reranker` (`dheaps/local-reranker:latest`) is wrapping a small cross‑encoder. For now leave it alone — swapping to a Qwen3‑Reranker is a Phase 5 hardening item, not part of getting things working. Just note it in `/home/docker-config/ask/README.md` as a known upgrade target.

10. **Stand up the MCP bridge for Firecrawl + SearXNG.** This is a new lightweight container in your existing stack that exposes Firecrawl and SearXNG as MCP servers reachable from outside the LibreChat docker network (because Zoo Code, on your dev box, will consume them).
    - Use a community MCP wrapper for Firecrawl (`firecrawl-mcp` exists as an npm package) and one for SearXNG (`mcp-searxng` exists similarly), or write a thin Node/Python service that proxies both behind one HTTP endpoint with SSE transport.
    - Recommended layout: one container, two routes, e.g., `http://librechat-host:7333/mcp/firecrawl/sse` and `/mcp/searxng/sse`.
    - Add the container to `docker-compose.override.yml`, on the `ask_librechat-net` network, with internal hostnames for `firecrawl:8080` and `searxng:8080`.
    - Publish port `7333` on the host so the dev box can reach it.
    - Do **not** add bearer auth yet — Phase 5 handles that. LAN‑only exposure for now.

11. **Profile awareness in `librechat.yaml`.** Add a comment block at the top noting which model entries are only available in the Orin's `chat` profile (`qwen3-coder:30b`, `nemotron-cascade-2:30b`, `qwen3-coder:30b`), and which work in both (`qwen3.6:35b-a3b`, embedder). This is documentation, not a guard — the guard is Phase 5.

12. **Document the new dataflow in `/home/docker-config/ask/README.md`:**
    - RAG embeddings now resolve to `http://ORIN_IP:11434` via the rag_api.
    - Embedding dimension is `<value>` (your recorded number).
    - Whisper is on `large-v3` / `faster_whisper`.
    - MCP bridge is at `http://librechat-host:7333` for Firecrawl and SearXNG.
    - When the Orin is in `roo` profile, LibreChat chat completions to `qwen3-coder` and `nemotron-cascade-2` will fail; RAG embeddings still work because the embedder is in both profiles.

### Acceptance
- A fresh upload + retrieval cycle works end‑to‑end in LibreChat.
- `psql` shows new rows with the correct vector dimension.
- STT and image gen still work through the UI.
- From the dev box: `curl http://librechat-host:7333/mcp/firecrawl/sse` returns an SSE handshake.

### Rollback
- `docker compose down rag_api api`
- Restore `pgdata2.tgz` from Phase 0 backup over `/home/SharedData/ask/pgdata2`.
- Revert `/home/docker-config/ask/.env` and `/home/docker-config/ask/docker-compose.override.yml` to the pre‑v3 copies.
- `docker compose up -d`. You're back to the pre‑v3 LibreChat.

---

## Phase 4 — Zoo Code: multi‑model, Verify mode, MCP, autocomplete

**Concern:** Zoo Code. Consumes Phase 2's verifier + embedder and Phase 3's MCP bridge.

Your existing `orin-coder` profile becomes the Code mode endpoint. You'll add two more providers and wire everything together.

### Steps

1. **Confirm the bumped context window from Phase 2.** Your `orin-coder` profile should now have Context window matching the `num_ctx` ceiling you established for `qwen3-coder:30b-a3b-q6_K` in `model_policy.yml` (likely 16384). Max output tokens raised to ~8192. Update the Model ID if you renamed the tag (e.g., to `qwen3-coder:30b-a3b-q6_K`).

2. **Add the reasoner provider** — call it `orin-reasoner`:
   - Profile name: `orin-reasoner`
   - Base URL: `http://ORIN_IP:4000/v1`
   - API Key: `sk-noauth`
   - Model ID: `qwen3.6:35b-a3b` (or whatever your exact tag is — must match `model_policy.yml`)
   - Use custom model info: on
   - Context window: ceiling from `model_policy.yml` for this model (likely 32768)
   - Max output tokens: 8192
   - Temperature: 0.3 (reasoner benefits from slightly more variance than the coder)
   - Supports images/tools/prompt caching/reasoning: all off
   - Custom header: `X-Ollama-Think: true`
   - Streaming: on

3. **Add the verifier provider** — call it `orin-verifier`:
   - Profile name: `orin-verifier`
   - Base URL: `http://ORIN_IP:4000/v1`
   - API Key: `sk-noauth`
   - Model ID: `nemotron-cascade-2:30b`
   - Use custom model info: on
   - Context window: per `model_policy.yml`
   - Max output tokens: 2048 (the verifier emits short JSON; no need for more)
   - Temperature: 0.0 (deterministic verification)
   - Supports tools: off (verifier shouldn't be tool‑using)
   - Custom header: `X-Ollama-Think: true`
   - Streaming: on

4. **Assign providers to built‑in modes:**
   - Code mode → `orin-coder`
   - Architect mode → `orin-reasoner`
   - Ask mode → `orin-reasoner`
   - Debug mode → `orin-reasoner`

5. **Create the `Verify` custom mode.** In Zoo Code → Modes → New (or by hand‑editing `.roomodes` in your repo root):
   ```yaml
   - slug: verify
     name: Verify
     provider: orin-verifier
     tools:
       - read_file
       - list_files
       - search_files
     # explicitly NO apply_diff, NO execute_command, NO write_to_file
     roleDefinition: |
       You are a code verifier. Given the user's SPEC and a DIFF of proposed
       changes, return STRICT JSON only matching:
         {"accept": boolean, "reasons": [string], "severity": "low"|"medium"|"high"}
       You may use read_file, list_files, and search_files to gather context.
       You never propose edits.
     customInstructions: |
       Prefer the Orin /v1/verify endpoint when the diff is self-contained.
       Use file-reading tools only when the diff references symbols whose
       definitions are not in the diff itself.
   ```

6. **Add per‑mode rules.** Create:
   - `.roo/rules-verify/policy.md` — "Verify must return only JSON. If you cannot decide, return `{accept: false, reasons: ['insufficient context'], severity: 'medium'}`."
   - `.roo/rules-code/policy.md` — "After any code edit, hand off to Verify mode before reporting completion."
   - `.roorules` at repo root — global rules: "Use Firecrawl MCP for any URL the user pastes; never assume page contents."

7. **Wire the MCP servers.** Edit `.roo/mcp.json` (or the equivalent global Zoo Code MCP config):
   ```json
   {
     "mcpServers": {
       "filesystem": {
         "command": "npx",
         "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/your/repo"]
       },
       "git": {
         "command": "npx",
         "args": ["-y", "@modelcontextprotocol/server-git", "--repository", "/path/to/your/repo"]
       },
       "firecrawl": {
         "transport": "sse",
         "url": "http://librechat-host:7333/mcp/firecrawl/sse"
       },
       "searxng": {
         "transport": "sse",
         "url": "http://librechat-host:7333/mcp/searxng/sse"
       },
       "verify": {
         "transport": "sse",
         "url": "http://ORIN_IP:4000/mcp/verify/sse"
       }
     }
   }
   ```
   For `verify` to work as an MCP server (rather than just a REST endpoint), add a small MCP wrapper to the FastAPI router that exposes `/v1/verify` as an MCP tool. If that's too much scope for now, skip the `verify` MCP entry and rely on the Verify mode making a direct HTTP call via a `customInstructions` snippet that constructs the curl. Either is fine; the MCP route is cleaner.

8. **Install Continue.dev for autocomplete only.** From the VS Code marketplace. Then in `~/.continue/config.json`:
   ```json
   {
     "tabAutocompleteModel": {
       "title": "FIM",
       "provider": "ollama",
       "model": "qwen2.5-coder:3b-base",
       "apiBase": "http://ORIN_IP:11434"
     },
     "embeddingsProvider": {
       "provider": "ollama",
       "model": "qwen3-embedding:4b",
       "apiBase": "http://ORIN_IP:11434"
     },
     "models": [],
     "tabAutocompleteOptions": {
       "useCopyBuffer": false,
       "useFileSuffix": true,
       "maxPromptTokens": 1024,
       "debounceDelay": 250
     }
   }
   ```
   - Empty `models: []` array disables the chat panel — Zoo Code owns chat, Continue owns autocomplete only.
   - Disable GitHub Copilot's inline suggestions to avoid two autocompletes fighting: VS Code settings → `"github.copilot.editor.enableAutoCompletions": false`.

9. **Define the OpenAI fallback provider in Zoo Code but leave it un‑assigned:**
   - Profile name: `openai-emergency`
   - Provider type: OpenAI
   - Model: `gpt-5-mini` (or whatever's cheapest in your tier)
   - Do **not** assign it to any mode. It exists only so that, when a task fails repeatedly locally, you can manually flip a mode's provider for one turn.

10. **Commit `.roomodes`, `.roorules`, and `.roo/` to your repo.** Add a section to your repo's README documenting the modes and what each one is for, so future‑you (or collaborators) doesn't have to reverse‑engineer the setup.

11. **End‑to‑end test.** With the Orin in `roo` profile:
    - Ask Code mode to implement a small feature with a deliberate ambiguity.
    - Confirm Code mode produces a diff.
    - Confirm Verify mode (or your Code→Verify handoff) is invoked.
    - Confirm Verify returns structured JSON.
    - Force a "fail" by introducing an obvious bug in the spec; confirm Verify rejects.
    - Ask Architect mode a design question; confirm it routes to `qwen3.6:35b-a3b` with `think=true`.
    - In the editor, type a partial function signature; confirm Continue.dev's autocomplete from `qwen2.5-coder:3b-base` populates.

### Acceptance
- All three providers in Zoo Code resolve and respond.
- Verify mode returns valid JSON on both accept and reject cases.
- Architect mode visibly uses the reasoner (longer thinking, different style than Code).
- Tab autocomplete works in the editor without lag and without Copilot interfering.
- `firecrawl` and `searxng` MCP tools are listable and callable from Zoo Code.
- `.roomodes`, `.roorules`, `.roo/` are committed.

### Rollback
- Remove the new providers and the Verify mode in Zoo Code.
- Delete `.roomodes` / `.roo/` from the repo (or just check out the pre‑v3 commit).
- Disable Continue.dev. Re‑enable Copilot autocomplete.
- You're back to the Phase 0 baseline (a working Zoo Code on the coder only).

---

## Phase 5 — Hardening (deferred until everything else works)

**Concern:** Cross‑cutting. Only attempt this after Phases 0–4 have been stable for at least a few days of real use, so you have a working baseline to compare against if something breaks.

### Steps

1. **Bearer auth on the FastAPI router.** Generate `INTERNAL_AI_TOKEN`. Add a FastAPI dependency that requires `Authorization: Bearer <token>` on all routes. Update:
   - LibreChat: pass the token via `RAG_OLLAMA_*` configuration or by switching the embed path through the router with `OPENAI_API_KEY=<token>`.
   - Zoo Code: change all three provider API Keys from `sk-noauth` to the token.
   - Continue.dev: add `apiKey` to its config blocks.

2. **Bearer auth on the MCP bridge.** Same token. Update Zoo Code's `.roo/mcp.json` SSE entries with `headers: {"Authorization": "Bearer <token>"}`.

3. **HTTPS via the existing nginx reverse‑proxy.** You already terminate TLS at nginx for LibreChat. Extend the same proxy to front:
   - The Orin FastAPI router (`https://orin.yourdomain/v1/...`) — needs the Orin to be reachable from the nginx host, or run a second nginx on the Orin and trust internally.
   - The MCP bridge (`https://mcp.yourdomain/...`).
   - Update Zoo Code / LibreChat / Continue.dev base URLs to the `https://` versions.

4. **Spend caps and monitoring.**
   - OpenAI dashboard: hard monthly limit (e.g., $10) and soft alert at $2.
   - Add a tiny request counter to the FastAPI router (`/metrics` Prometheus endpoint) so you can see hits per model, per profile, per consumer.
   - If you want full observability, run a small Grafana + Prometheus alongside LibreChat; otherwise tail logs.

5. **Optional: Qwen3‑Reranker upgrade.** Swap `dheaps/local-reranker` for `ghcr.io/huggingface/text-embeddings-inference` serving `Qwen/Qwen3-Reranker-4B` on the same `:8010` alias. Only do this if you've observed retrieval quality issues; otherwise leave the existing reranker alone.

6. **Optional: profile‑aware guard in `librechat.yaml`.** Implement the small guard that pings `http://ORIN/profile` and 503s the model list when the wrong profile is active, so users get a clear error instead of a confusing timeout.

### Acceptance
- All three consumers (LibreChat, Zoo Code, Continue.dev) authenticate successfully against tokenized endpoints.
- HTTPS URLs work; no certificate warnings.
- OpenAI dashboard shows the spend cap is in effect.
- Phases 0–4 functionality unchanged after hardening.

### Rollback
- For each tokenized endpoint: comment out the auth dependency, revert clients to `sk-noauth`. Hardening is incremental and each piece can be reverted independently without affecting the rest.

---

## What this plan deliberately leaves out

- **Hardware purchases.** You're right that with corrected 2026 pricing the ROI on a 5090 isn't strong enough this year. The Orin stays.
- **DNS / hostname setup.** Already in place.
- **Initial LibreChat install.** Already in place.
- **Initial Orin model server install.** Already in place.
- **Zoo Code install.** Already done with your conservative settings.
- **Vendor risk hedging (Cline migration).** Documented in v2, no action this cycle.

## Order of operations recap

`Phase 0 → Phase 1a + 1b (parallel) → Phase 2 → Phase 3 → Phase 4 → (stabilize) → Phase 5`

Phases 1a and 1b are the only parallel ones. Everything else is strictly sequential because each phase consumes endpoints, schemas, or configurations from the previous one.
