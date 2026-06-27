## Unified Orin + Thor Ollama/LibreChat Uplift Plan

### 1. Objective

Keep **one shared Docker stack** for both:

- **Jetson AGX Orin 64GB**
- **Jetson AGX Thor 128GB**

The stack must remain the same across both boards:

- same Docker/Compose structure
- same Ollama version
- same LibreChat version
- same runtime shape
- same API shape

The only intended differences are:

- **board profile**
- **model selection**
- **warmup / residency policy**
- **per-model options**
- **LibreChat preset-to-model mapping**

Primary product goal:

- expose exactly **two first-class LibreChat contexts**
  - **Coding**
  - **Chat**
- use **Thor aggressively** so those two contexts are materially stronger than Orin
- keep Orin practical and stable within 64GB
- keep Thor optimized for **two resident large contexts**

---

### 2. Shared software baseline

Use one current stack for both boards:

| Layer | Target |
|---|---|
| JetPack / OS line | JetPack 7.2 / Jetson Linux 39.2 / Ubuntu 24.04 |
| Ollama | 0.30.10 |
| LibreChat | 0.8.6 |
| Compose / Docker stack | single shared stack |
| Ollama runtime knobs | shared defaults |
| Board-specific behavior | profile-driven |

Rationale:

- Orin is now on the same JetPack generation as Thor, so there is no need to split the serving stack.
- Old Thor example versions are not the target.
- Version fallback is only allowed after reproducible failure. <citation src="13,18,20,24"></citation>

---

### 3. Hard constraints

1. **One shared Docker stack**
2. **No board-specific image fork unless absolutely required**
3. **No separate Thor-only serving architecture**
4. **Orin remains supported in the same repo**
5. **Thor must use more memory and context than Orin**
6. **LibreChat must present stable user-facing presets: `Coding` and `Chat`**
7. **If a planned model tag is unavailable, fail explicitly and document it**
8. **Do not silently substitute a weaker model**

---

### 4. Board memory budgets

Do not plan to consume 100% of unified memory.

| Board | Physical memory | Reserved for OS / Docker / overhead | Planning budget for model weights + KV |
|---|---:|---:|---:|
| Orin | 64 GB | 8–10 GB | 54–56 GB |
| Thor | 128 GB | 14–16 GB | 112–114 GB |

These are planning budgets, not peak theoretical limits.

---

### 5. Model sizing inputs

Current published or existing working tags:

| Model | Size | Notes |
|---|---:|---|
| `qwen3-coder:30b` | 19 GB | official Ollama coding model |
| `qwen3.6:35b-a3b` | 24 GB | official Ollama q4/default-style chat/reasoning model |
| `qwen3.6:35b-a3b-q8_0` | 39 GB | official Ollama higher-quality chat model |
| `qwen3-coder-next:q4_K_M` | ~49 GB | aggressive Thor coding target; validate exact pulled size in repo |
| `qwen3:4b` | 2.5 GB | small utility model |
| `qwen3-coder:480b` | 290 GB | excluded; local minimum memory listed at 250GB |
| `qwen3:235b` | 142 GB | excluded; too large for practical Thor serving |

<citation src="2,3,4,8,9,6"></citation>

---

### 6. Long-context planning math

#### 6.1 KV cache planning rule

For `q8_0` KV cache, use this approximation:

\[
\text{KV bytes/token} \approx 2 \times L_{attn} \times H_{kv} \times D_{head}
\]

Where:

- \(L_{attn}\) = number of attention layers that store KV
- \(H_{kv}\) = KV heads
- \(D_{head}\) = head dimension
- factor 2 = keys + values
- `q8_0` is treated as ~1 byte/value for planning

#### 6.2 Derived planning estimates

| Model | Architecture input used | Approx KV / token | 64K | 128K | 256K |
|---|---|---:|---:|---:|---:|
| `qwen3-coder:30b` | 48 layers, 4 KV heads, head dim 128 | ~48 KiB | ~3.0 GB | ~6.0 GB | ~12.0 GB |
| `qwen3.6:35b-a3b` | 10 gated-attention layers, 2 KV heads, head dim 256 | ~10 KiB | ~0.625 GB | ~1.25 GB | ~2.5 GB |
| `qwen3-coder-next` | 12 gated-attention layers, 2 KV heads, head dim 256 | ~12 KiB | ~0.75 GB | ~1.5 GB | ~3.0 GB |

The important conclusion:

- `qwen3-coder:30b` is excellent for Orin, but its KV growth gets expensive at very large contexts.
- `qwen3.6:35b-a3b` and `qwen3-coder-next` are better long-context residents for Thor because their hybrid layouts keep KV growth much lower. <citation src="40,10,44"></citation>

---

### 7. Primary model strategy by board

## Orin strategy

Orin remains conservative.

### Orin primary contexts

| Context | Model | Residency | Target context |
|---|---|---|---:|
| Coding | `qwen3-coder:30b` | always warm | 65536 |
| Chat | `qwen3.6:35b-a3b` | opportunistic / short keep_alive | 32768 initially, 65536 if stable |

Why:

- `qwen3-coder:30b` at 64K is roughly:
  - 19 GB weights
  - ~3 GB KV
  - total ~22 GB
- `qwen3.6:35b-a3b` at 32K is roughly:
  - 24 GB weights
  - ~0.3 GB KV
  - total ~24.3 GB

Combined resident footprint is already around **46+ GB**, which is near the Orin working budget after reserve. So Orin should **not** keep both large models permanently warm at aggressive contexts.

## Thor strategy

Thor is intentionally aggressive.

### Thor primary contexts

| Context | Model | Residency | Target context |
|---|---|---|---:|
| Coding | `qwen3-coder-next:q4_K_M` | always warm | 262144 |
| Chat | `qwen3.6:35b-a3b-q8_0` | always warm | 262144 |

Why:

- `qwen3-coder-next:q4_K_M` is the correct Thor coding uplift because it materially uses Thor memory and is purpose-built for coding agents with native 256K context.
- `qwen3.6:35b-a3b-q8_0` is the correct Thor chat uplift because it improves chat/reasoning quality over the 24GB q4-style build while still fitting comfortably as a resident second model. <citation src="44,8,9"></citation>

### Thor dual-residency estimate

| Model | Weights | KV at target ctx | Total |
|---|---:|---:|---:|
| `qwen3-coder-next:q4_K_M` @ 256K | ~49 GB | ~3.0 GB | ~52.0 GB |
| `qwen3.6:35b-a3b-q8_0` @ 256K | 39 GB | ~2.5 GB | ~41.5 GB |
| **Combined** |  |  | **~93.5 GB** |

That leaves roughly:

\[
128 - 93.5 - 16 \approx 18.5 \text{ GB}
\]

of remaining headroom after reserve, which is enough for the shared service overhead plus a few small opportunistic models.

This is why Thor should **not** stay on the Orin primary pair.

---

### 8. Final approved primary profile recommendation

| Board | LibreChat `Coding` | LibreChat `Chat` |
|---|---|---|
| Orin | `qwen3-coder:30b` | `qwen3.6:35b-a3b` |
| Thor | `qwen3-coder-next:q4_K_M` | `qwen3.6:35b-a3b-q8_0` |

This is the core plan.

---

### 9. Shared Ollama runtime defaults

Keep these shared across both boards unless validation proves otherwise:

| Variable | Value |
|---|---|
| `OLLAMA_FLASH_ATTENTION` | `1` |
| `OLLAMA_KV_CACHE_TYPE` | `q8_0` |
| `OLLAMA_NUM_PARALLEL` | `1` |
| `OLLAMA_MAX_LOADED_MODELS` | `2` |
| `OLLAMA_KEEP_ALIVE` | base default only; primary control remains per-model |

Notes:

- `q8_0` is the default planning choice because it materially reduces KV memory while keeping quality loss small.
- Keep `MAX_LOADED_MODELS=2` because the design target is exactly **two large first-class contexts**. <citation src="34,38"></citation>

---

### 10. Profile structure

Use **board profiles**, not separate stacks.

| Path / concept | Purpose |
|---|---|
| `PROFILE=orin` | selects Orin model profile |
| `PROFILE=thor` | selects Thor model profile |
| shared compose | same stack on both boards |
| shared image | same image on both boards |
| shared env baseline | same runtime defaults |
| `profiles/orin/models.yaml` | Orin model inventory |
| `profiles/thor/models.yaml` | Thor model inventory |
| `profiles/orin/librechat-modelspecs.yaml` | Orin LibreChat preset mapping |
| `profiles/thor/librechat-modelspecs.yaml` | Thor LibreChat preset mapping |

User-facing LibreChat names should remain stable:

- `Coding`
- `Chat`

Only the underlying board-specific model mapping changes.

---

### 11. Proposed Orin model profile

```yaml
models:
  - model: qwen3-coder:30b
    keep_alive: -1
    think: false
    warmup: true
    options:
      num_ctx: 65536
      num_batch: 512
      temperature: 0.1
      top_p: 0.9
      repeat_penalty: 1.05

  - model: qwen3.6:35b-a3b
    keep_alive: 10m
    think: true
    warmup: false
    options:
      num_ctx: 32768
      num_batch: 512
      temperature: 0.6
      top_p: 0.95

  - model: qwen3:4b
    keep_alive: 10m
    think: true
    warmup: false
    options:
      num_ctx: 65536
      num_batch: 512
      temperature: 0.2
      top_p: 0.9
      repeat_penalty: 1.05

  - model: qwen3-vl:4b
    keep_alive: 10m
    think: true
    warmup: false
    options:
      num_ctx: 32768
      num_batch: 256
      temperature: 0.2
      top_p: 0.9
      repeat_penalty: 1.05

  - model: gemma4:12b
    keep_alive: 10m
    think: true
    warmup: false
    options:
      num_ctx: 32768
      num_batch: 256
      temperature: 0.3
      top_p: 0.95
      repeat_penalty: 1.05
```

---

### 12. Proposed Thor model profile

```yaml
models:
  - model: qwen3-coder-next:q4_K_M
    keep_alive: -1
    think: false
    warmup: true
    options:
      num_ctx: 262144
      num_batch: 512
      temperature: 0.15
      top_p: 0.95
      repeat_penalty: 1.05

  - model: qwen3.6:35b-a3b-q8_0
    keep_alive: -1
    think: true
    warmup: true
    options:
      num_ctx: 262144
      num_batch: 512
      temperature: 0.6
      top_p: 0.95

  - model: qwen3:4b
    keep_alive: 30m
    think: true
    warmup: false
    options:
      num_ctx: 65536
      num_batch: 512
      temperature: 0.2
      top_p: 0.9
      repeat_penalty: 1.05

  - model: qwen3-vl:4b
    keep_alive: 30m
    think: true
    warmup: false
    options:
      num_ctx: 65536
      num_batch: 256
      temperature: 0.2
      top_p: 0.9
      repeat_penalty: 1.05

  - model: gemma4:12b
    keep_alive: 30m
    think: true
    warmup: false
    options:
      num_ctx: 65536
      num_batch: 256
      temperature: 0.3
      top_p: 0.95
      repeat_penalty: 1.05

  - model: reader-lm:1.5b
    keep_alive: 30m
    think: false
    warmup: false
    options:
      num_ctx: 65536
      num_batch: 256
      temperature: 0.0
      top_p: 0.9
```

---

### 13. LibreChat preset plan

LibreChat should expose exactly two obvious presets.

| Preset | Orin model | Thor model | Purpose |
|---|---|---|---|
| `Coding` | `qwen3-coder:30b` | `qwen3-coder-next:q4_K_M` | code edits, tool use, repo reasoning |
| `Chat` | `qwen3.6:35b-a3b` | `qwen3.6:35b-a3b-q8_0` | planning, Q&A, discussion, reasoning |

Requirements:

- same preset names on both boards
- different underlying models by board profile
- model selection hidden or simplified in LibreChat so users start from `Coding` and `Chat`

---

### 14. Validation gates

## Shared-stack validation

These must pass on both boards:

1. same compose file
2. same image tag
3. same Ollama version
4. same LibreChat version
5. health checks pass
6. correct board profile file is mounted / loaded

## Orin validation

1. `qwen3-coder:30b` warms successfully
2. `qwen3.6:35b-a3b` loads on demand
3. no swap during startup + first real inference
4. no repeated model eviction during normal use

## Thor validation

1. `qwen3-coder-next:q4_K_M` warms successfully
2. `qwen3.6:35b-a3b-q8_0` warms successfully
3. both remain resident after startup
4. `/api/ps` confirms both loaded
5. no swap during startup and dual-context testing
6. long-context smoke test passes for both presets
7. LibreChat `Coding` routes to coder-next
8. LibreChat `Chat` routes to qwen3.6 q8

---

### 15. Non-goals for phase 1

Do **not** make these part of the initial uplift:

- MIG partitioning
- Thor-only serving fork
- TensorRT-LLM migration
- FP4-specific serving path
- third large always-warm model
- giant models like `qwen3:235b` or `qwen3-coder:480b`

These can be future experiments only after the baseline works.

---

### 16. Final decision summary

Approved direction:

- one shared stack
- board-specific model profiles
- stable LibreChat presets: `Coding`, `Chat`
- Orin keeps `qwen3-coder:30b` as primary coder
- Thor upgrades `Coding` to `qwen3-coder-next:q4_K_M`
- Thor upgrades `Chat` to `qwen3.6:35b-a3b-q8_0`
- Thor keeps both large contexts warm
- Thor targets 256K context for both primary contexts
- `OLLAMA_MAX_LOADED_MODELS=2`
- `OLLAMA_KV_CACHE_TYPE=q8_0`
- validate with real warmup and `/api/ps`, not assumptions