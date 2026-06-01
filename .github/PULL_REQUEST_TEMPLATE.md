## Summary

<!-- One short paragraph: what does this PR do and why? -->

## Type of Change

- [ ] feat — new capability
- [ ] fix — bug fix
- [ ] docs — documentation only
- [ ] refactor / perf — no behavior change
- [ ] test
- [ ] chore / build / ci
- [ ] BREAKING CHANGE

## Operational Impact

Check all that apply and describe briefly. If none, state "none".

- [ ] Exposed ports / bind addresses changed
- [ ] Env var added / removed / renamed / default changed
- [ ] Compose service or profile added / removed / renamed
- [ ] Model added / removed / renamed / capability changed
- [ ] `keep_alive` defaults changed
- [ ] `think` policy or precedence changed
- [ ] Tool matching list changed
- [ ] OpenAI-compatible request/response contract changed
- [ ] Header name added / removed / semantics changed

Details:

<!-- Explain the impact in plain language. What will an operator or a
     LibreChat admin need to know or do? -->

## README.md Updated?

`README.md` is the source of truth for this service's current state.

- [ ] `README.md` updated in this PR to reflect the change
- [ ] Not applicable (no user-visible / operator-visible behavior change)

If not applicable, explain:

<!-- e.g. "internal refactor of policy decision function, no behavior
     change, covered by existing tests" -->

## Configuration Surface

- [ ] `.env.example` updated (if env vars changed)
- [ ] `router/model_policy.yml` updated (if policy/model defaults changed)
- [ ] `docker-compose.yml` updated (if services/ports/profiles changed)

## Tests

- [ ] Unit tests added or updated
- [ ] Existing tests pass locally (`pytest`)
- [ ] Manual verification performed (paste relevant `curl` output below)

<details>
<summary>Test evidence</summary>

```
<!-- pytest output and/or curl examples -->
```

</details>

## LibreChat / Client Compatibility

- [ ] Existing LibreChat base URL still works
- [ ] Existing configured model IDs still resolve
- [ ] Existing headers / request shapes still accepted
- [ ] BREAKING — clients must reconfigure (describe migration below)

Migration notes (if breaking):

<!-- What exactly must a client change? -->

## Additional Notes

<!-- Anything else reviewers should know: follow-ups, known limitations,
     links to related issues, benchmark numbers, etc. -->
