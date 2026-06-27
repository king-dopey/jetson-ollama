# LibreChat Agent Creation Guide

Create these persisted agents in this order so parent agents can reference child agents:

1. Planning Prompt Drafter
2. Planning Prompt Refiner
3. Implementation Prompt Drafter
4. Implementation Prompt Refiner
5. Planning Prompt Parent
6. Implementation Prompt Parent

For each agent:
- Name: use the blueprint name
- Description: use the blueprint description
- Model: use the blueprint model
- Instructions: paste the full `instructions` block from `librechat_agent_blueprints.yml`
- Skills: enable skills and assign the listed skill IDs
- Tools: enable the listed tools
- Web Search: enable for every prompt agent
- Subagents:
  - for child agents: disabled
  - for parent agents: enabled, allowSelf=false
  - add the exact child agent IDs after the child agents are created

After creating them, update:
- `librechat_model_specs.yml`
- `mode_model_bindings.yml`

Replace:
- REPLACE_WITH_AGENT_PLANNING_PROMPT_PARENT_ID
- REPLACE_WITH_AGENT_IMPLEMENTATION_PROMPT_PARENT_ID
- etc.

Zoo/Roo side:
- put `custom_modes.yml` into the global modes location
- bind `planning-prompt` to the LibreChat parent agent `agent_planning_prompt_parent`
- bind `implementation-prompt` to the LibreChat parent agent `agent_implementation_prompt_parent`
- bind the remaining modes to Thor router models using `mode_model_bindings.yml`
