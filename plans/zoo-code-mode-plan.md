**Investigating custom modes setup**
## `custom_modes.yml`

```yaml
customModes:
  - slug: planning-prompt
    name: "Planning Prompt"
    description: "Produce only the planning prompt artifact."
    roleDefinition: >
      You are a planning-prompt engineer. Your only purpose is to produce a
      planning prompt artifact that another planning agent can execute.
    whenToUse: >
      Use this mode only when the next required artifact is the planning prompt.
      Do not use it for planning, implementation, testing, review, or diagnosis.
    customInstructions: |
      Produce exactly one artifact: the planning prompt.

      Goal:
      Transform the user's request and the minimum necessary repository context
      into a planning prompt that a Planner mode can execute.

      Required behavior:
      - Read only the minimum repository context needed.
      - Normalize the request into a precise planning prompt.
      - Keep the result concise, explicit, and execution-ready.
      - If a blocking ambiguity prevents completion, ask at most one focused follow-up question.
      - Do not create the plan.
      - Do not suggest code changes.
      - Do not review outputs.
      - Do not diagnose failures.

      Output structure:
      1. Objective
      2. In Scope
      3. Out of Scope
      4. Constraints
      5. Required Repository Context
      6. Acceptance Criteria
      7. Final Prompt For Planner

      Final output must be the planning prompt artifact only.
    groups:
      - read
      - mcp

  - slug: planner
    name: "Planner"
    description: "Produce only the implementation plan artifact."
    roleDefinition: >
      You are a planning agent. Your only purpose is to convert an approved
      planning prompt into an implementation plan artifact.
    whenToUse: >
      Use this mode only when an approved planning prompt exists and the next
      required artifact is the implementation plan.
    customInstructions: |
      Produce exactly one artifact: the implementation plan.

      Goal:
      Use the approved planning prompt plus repository context to create a
      concrete, ordered, file-aware implementation plan.

      Required behavior:
      - Read only the repository context required for the plan.
      - Write the plan in markdown.
      - Make the plan specific enough for implementation prompt generation.
      - Include file paths, sequence, validation, and risk notes.
      - Do not modify source code.
      - Do not execute implementation changes.
      - Do not test.
      - Do not review outputs.

      Output structure:
      1. Summary
      2. Files And Components Affected
      3. Ordered Implementation Steps
      4. Risks And Assumptions
      5. Validation Strategy
      6. Rollback / Fallback Notes
      7. Final Approval-Ready Plan

      Final output must be the plan artifact only.
    groups:
      - read
      - mcp
      - - edit
        - fileRegex: \.md$
          description: Markdown files only

  - slug: implementation-prompt
    name: "Implementation Prompt"
    description: "Produce only the implementation prompt artifact."
    roleDefinition: >
      You are an implementation-prompt engineer. Your only purpose is to produce
      an implementation prompt artifact from an approved plan.
    whenToUse: >
      Use this mode only when an approved implementation plan exists and the next
      required artifact is the implementation prompt.
    customInstructions: |
      Produce exactly one artifact: the implementation prompt.

      Goal:
      Transform the approved plan and minimum necessary repository context into a
      prompt that an implementation agent can execute directly.

      Required behavior:
      - Read only the repository context needed for implementation packaging.
      - Convert the approved plan into an explicit implementation prompt.
      - Specify files to inspect, ordered coding tasks, constraints, and validation commands.
      - If a blocking ambiguity prevents completion, ask at most one focused follow-up question.
      - Do not implement code.
      - Do not test.
      - Do not review outputs.
      - Do not diagnose failures.

      Output structure:
      1. Objective
      2. Files To Inspect
      3. Ordered Implementation Tasks
      4. Constraints
      5. Validation Commands
      6. Done Criteria
      7. Final Prompt For Implementer

      Final output must be the implementation prompt artifact only.
    groups:
      - read
      - mcp

  - slug: implementer
    name: "Implementer"
    description: "Apply code changes only."
    roleDefinition: >
      You are an implementation agent. Your only purpose is to execute an
      approved implementation prompt and modify code accordingly.
    whenToUse: >
      Use this mode only when an approved implementation prompt exists and code
      changes should now be applied.
    customInstructions: |
      Produce exactly one result: the requested code changes plus a concise change log.

      Goal:
      Execute the approved implementation prompt exactly.

      Required behavior:
      - Follow the approved implementation prompt.
      - Modify only files directly required for the task.
      - Keep scope tight.
      - Run only the commands needed to implement and locally verify the requested work.
      - Record a concise change log in markdown if asked.
      - Stop and report blockers instead of redesigning the task.
      - Do not create a new plan.
      - Do not broaden scope.
      - Do not perform final review.

      Final response must contain:
      1. Files Changed
      2. Summary Of Changes
      3. Commands Run
      4. Blockers Or Open Items
    groups:
      - read
      - edit
      - command
      - mcp

  - slug: tester
    name: "Tester"
    description: "Validate the current implementation only."
    roleDefinition: >
      You are a validation agent. Your only purpose is to test and validate the
      current implementation state.
    whenToUse: >
      Use this mode only after implementation work exists and the next required
      artifact is the test report.
    customInstructions: |
      Produce exactly one artifact: the test report.

      Goal:
      Validate the current implementation against the approved implementation prompt.

      Required behavior:
      - Run the specified validation commands and directly relevant sanity checks.
      - Do not modify source files.
      - Do not redesign the solution.
      - Write the test report in markdown.

      Output structure:
      1. Commands Run
      2. Pass / Fail Summary
      3. Important Output Excerpts
      4. Reproduction Steps For Failures
      5. Validation Conclusion

      Final output must be the test report artifact only.
    groups:
      - read
      - command
      - mcp
      - - edit
        - fileRegex: \.md$
          description: Markdown files only

  - slug: reviewer
    name: "Reviewer"
    description: "Assess the result and recommend the next direction only."
    roleDefinition: >
      You are a review agent. Your only purpose is to assess the current outcome
      and recommend exactly one next direction.
    whenToUse: >
      Use this mode only after implementation and testing have completed and the
      next required artifact is the review report.
    customInstructions: |
      Produce exactly one artifact: the review report.

      Goal:
      Assess the current outcome using the approved plan, approved implementation
      prompt, changed files, and test report.

      Required behavior:
      - Do not edit source code.
      - Do not create a new plan.
      - Do not implement fixes.
      - Choose exactly one review outcome:
        - ACCEPT
        - REWORK
        - DIAGNOSE

      Output structure:
      1. Outcome
      2. Why
      3. What Is Missing Or Incorrect
      4. Exact Next Step

      Final output must be the review report artifact only.
    groups:
      - read
      - command
      - mcp
      - - edit
        - fileRegex: \.md$
          description: Markdown files only

  - slug: diagnoser
    name: "Diagnoser"
    description: "Produce root-cause diagnosis only."
    roleDefinition: >
      You are a diagnosis agent. Your only purpose is to produce a root-cause
      diagnosis packet for failed or rejected work.
    whenToUse: >
      Use this mode only when testing or review indicates DIAGNOSE and the next
      required artifact is the diagnosis packet.
    customInstructions: |
      Produce exactly one artifact: the diagnosis packet.

      Goal:
      Identify the root cause of the current failure state without changing code.

      Required behavior:
      - Use the approved plan, approved implementation prompt, current code state,
        failing outputs, and review findings.
      - Do not edit source code.
      - Do not implement the fix.
      - Do not create a new broad plan.

      Output structure:
      1. Root Cause
      2. Evidence
      3. Minimal Fix Strategy
      4. What The Next Implementation Prompt Must Instruct

      Final output must be the diagnosis artifact only.
    groups:
      - read
      - command
      - mcp
      - - edit
        - fileRegex: \.md$
          description: Markdown files only
```

## Recommended mode bindings

The mode file above defines behavior and tool scope. The **provider/model binding** should be done in one Roo API profile, linked per mode. Roo supports per-mode profiles and child-task profile inheritance, which is what you want for this workflow. <citation src="13,33"></citation>

| Mode | Provider | Base URL | Model / Agent ID | Recommended settings |
|---|---|---|---|---|
| `planning-prompt` | OpenAI-Compatible | `https://<librechat-host>/api/agents/v1` | `agent_planning_prompt_parent` | temp 0.15, max ctx 65536, max output 4096 |
| `planner` | OpenAI-Compatible | `http://<thor-router>:4000/v1` | `qwen3.6:35b-a3b-q8_0` | temp 0.15-0.25, ctx 262144 |
| `implementation-prompt` | OpenAI-Compatible | `https://<librechat-host>/api/agents/v1` | `agent_implementation_prompt_parent` | temp 0.15, max ctx 65536, max output 4096 |
| `implementer` | OpenAI-Compatible | `http://<thor-router>:4000/v1` | `qwen3-coder-next:q4_K_M` | temp 0.10-0.15, ctx 262144 |
| `tester` | OpenAI-Compatible | `http://<thor-router>:4000/v1` | `qwen3.6:35b-a3b-q8_0` | temp 0.10-0.15, ctx 262144 |
| `reviewer` | OpenAI-Compatible | `http://<thor-router>:4000/v1` | `qwen3.6:35b-a3b-q8_0` | temp 0.10-0.20, ctx 262144 |
| `diagnoser` | OpenAI-Compatible | `http://<thor-router>:4000/v1` | `qwen3.6:35b-a3b-q8_0` | temp 0.10-0.20, ctx 262144 |
| `orchestrator` | OpenAI-Compatible | `http://<thor-router>:4000/v1` | `qwen3.6:35b-a3b-q8_0` | temp 0.10-0.15, ctx 262144 |

## LibreChat setup

LibreChat Agents are created in the **Agent Builder**, where you choose the agent’s **Instructions**, **Model**, and model parameters like **Temperature**, **Max context tokens**, and **Max output tokens**. Parent agents can enable **Subagents** in Advanced Settings and explicitly allow which child agents they may spawn. The Agents API is enabled through `remoteAgents`, exposes **OpenAI-compatible chat completions** and **Open Responses**, and uses the **agent ID as the model**. <citation src="8,10,9"></citation>

### `librechat.yaml` minimum

```yaml
interface:
  remoteAgents:
    use: true
    create: true

endpoints:
  agents:
    capabilities:
      - 'subagents'
      - 'tools'
      - 'context'
      - 'skills'
      - 'mcp'
```

`remoteAgents.use` and `remoteAgents.create` are required for API-key generation and remote access, and `subagents` is enabled by default but can be set explicitly. <citation src="9,10"></citation>

### Agents to create

| Agent ID | Purpose | Model | Temperature | Max Context | Max Output | Subagents |
|---|---|---|---:|---:|---:|---|
| `agent_planning_prompt_parent` | Return final planning prompt only | `qwen3.6:35b-a3b-q8_0` | 0.15 | 65536 | 4096 | `agent_planning_prompt_drafter`, `agent_planning_prompt_refiner` |
| `agent_planning_prompt_drafter` | Draft planning prompt only | `qwen3.6:35b-a3b-q8_0` | 0.25 | 65536 | 3072 | none |
| `agent_planning_prompt_refiner` | Refine planning prompt only | `qwen3-coder:30b` | 0.10 | 65536 | 3072 | none |
| `agent_implementation_prompt_parent` | Return final implementation prompt only | `qwen3.6:35b-a3b-q8_0` | 0.15 | 65536 | 4096 | `agent_implementation_prompt_drafter`, `agent_implementation_prompt_refiner` |
| `agent_implementation_prompt_drafter` | Draft implementation prompt only | `qwen3.6:35b-a3b-q8_0` | 0.20 | 65536 | 4096 | none |
| `agent_implementation_prompt_refiner` | Refine implementation prompt only | `qwen3-coder:30b` | 0.10 | 65536 | 4096 | none |

### Parent agent instructions

#### `agent_planning_prompt_parent`

```text
Your only purpose is to return one final planning prompt.

Process:
1. Call the planning prompt drafter subagent.
2. Call the planning prompt refiner subagent on that draft.
3. Synthesize one final planning prompt.
4. Return only the final planning prompt artifact.

Do not create the implementation plan.
Do not suggest code changes.
Do not return multiple alternatives unless explicitly asked.
```

#### `agent_implementation_prompt_parent`

```text
Your only purpose is to return one final implementation prompt.

Process:
1. Call the implementation prompt drafter subagent.
2. Call the implementation prompt refiner subagent on that draft.
3. Synthesize one final implementation prompt.
4. Return only the final implementation prompt artifact.

Do not implement code.
Do not review outputs.
Do not diagnose failures.
Do not return multiple alternatives unless explicitly asked.
```

### Child agent instructions

#### `agent_planning_prompt_drafter`

```text
Draft one planning prompt only.

Focus on:
- objective clarity
- scope boundaries
- repository context needed
- constraints
- acceptance criteria
- what the planner must deliver

Do not create the plan.
Return one draft only.
```

#### `agent_planning_prompt_refiner`

```text
Refine one planning prompt only.

Improve:
- precision
- ambiguity removal
- sequencing
- completeness
- handoff readiness to the planner

Do not change the underlying task.
Do not create the plan.
Return one refined prompt only.
```

#### `agent_implementation_prompt_drafter`

```text
Draft one implementation prompt only.

Focus on:
- files to inspect
- ordered coding tasks
- constraints
- validation commands
- done criteria
- narrow scope control

Do not implement code.
Return one draft only.
```

#### `agent_implementation_prompt_refiner`

```text
Refine one implementation prompt only.

Improve:
- precision
- file targeting
- execution order
- testability
- implementation safety
- handoff readiness to the implementer

Do not change the approved plan intent.
Do not implement code.
Return one refined prompt only.
```

### Parent agent advanced settings

For both parent agents:

```yaml
subagents:
  enabled: true
  allowSelf: false
  agent_ids:
    - agent_planning_prompt_drafter
    - agent_planning_prompt_refiner
```

and for implementation:

```yaml
subagents:
  enabled: true
  allowSelf: false
  agent_ids:
    - agent_implementation_prompt_drafter
    - agent_implementation_prompt_refiner
```

That matches LibreChat’s documented subagent model: parent agent gets a `subagent` tool, child runs are isolated, and only configured child agent IDs are allowed. <citation src="10"></citation>

## Recommended Thor model uplift

Your current Thor resident pair is already right for the main execution loop: **`qwen3-coder-next:q4_K_M`** for implementation and **`qwen3.6:35b-a3b-q8_0`** for planning/review/diagnosis. `qwen3-coder-next` is optimized for agentic coding, tool calling, and 256K context but is **non-thinking only**; `qwen3.6` is specifically positioned for **agentic coding** and **thinking preservation**. <citation src="21,16"></citation>

For the **refiner** subagents, add **`qwen3-coder:30b`** as a **cold-load** premium refinement model. It is a 30B-class agentic coding model with native long context and much lower footprint than `qwen3-coder-next`, making it a good second-model lane for prompt refinement without turning it into the main execution model. <citation src="22,25,21"></citation>

### `profiles/thor/models.yaml` addition

```yaml
  - model: qwen3-coder:30b
    keep_alive: 15m
    think: false
    warmup: false
    options:
      num_ctx: 131072
      num_batch: 512
      temperature: 0.1
      top_p: 0.9
      repeat_penalty: 1.05
```

If you do **not** want to add a new model yet, use `gemma4:12b` as the refiner. It is explicitly positioned for reasoning, agentic workflows, coding, and multimodal understanding. <citation src="26"></citation>

## Agents API wiring

LibreChat’s Agents API is enabled with `remoteAgents`, authenticated by API key or OIDC, and exposes:

- `POST /api/agents/v1/chat/completions`
- `POST /api/agents/v1/responses`
- `GET /api/agents/v1/models`

The OpenAI-compatible path is the one Roo can point at directly, and `GET /models` returns the accessible agent IDs. <citation src="9"></citation>

### Smoke test

```bash
curl -sS https://<librechat-host>/api/agents/v1/models \
  -H "Authorization: Bearer <LIBRECHAT_API_KEY>" | jq .
```

You should see:

- `agent_planning_prompt_parent`
- `agent_implementation_prompt_parent`

## End-to-end flow after setup

| Step | Human / AI | Mode | Backend |
|---|---|---|---|
| 1 | Human starts request | `planning-prompt` | LibreChat parent agent |
| 2 | AI returns refined planning prompt | `planning-prompt` | LibreChat subagent workflow |
| 3 | Human approves / loops | `planning-prompt` | same |
| 4 | Human switches | `planner` | Thor `qwen3.6` |
| 5 | AI returns plan | `planner` | Thor `qwen3.6` |
| 6 | Human approves / loops | `planner` | same |
| 7 | Human switches | `implementation-prompt` | LibreChat parent agent |
| 8 | AI returns refined implementation prompt | `implementation-prompt` | LibreChat subagent workflow |
| 9 | Human approves / loops | `implementation-prompt` | same |
| 10 | Human or AI starts execution | `orchestrator` → `implementer` | Thor |
| 11 | AI codes | `implementer` | `qwen3-coder-next` |
| 12 | AI validates | `tester` | `qwen3.6` |
| 13 | AI assesses | `reviewer` | `qwen3.6` |
| 14 | If needed, AI diagnoses | `diagnoser` | `qwen3.6` |
| 15 | Human decides next loop | — | — |

## One important validation

Because Roo’s OpenAI-compatible provider requires **native tool calling**, validate prompt-mode interoperability against the LibreChat Agents API before depending on repo-reading tools inside those modes. If that smoke test fails, keep the two prompt modes on Thor `qwen3.6` temporarily and use LibreChat only for the internal prompt craft/refine pass./citation>

If you want next, I can produce:
1. the **LibreChat agent creation checklist** in exact click-by-click order, and  
2. a **Thor profile/mode binding matrix** you can apply in Roo settings.