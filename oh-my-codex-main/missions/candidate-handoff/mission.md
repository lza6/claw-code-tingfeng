# Mission
Implement and validate repo-root `candidate.json` handoff for the thin-supervisor autoresearch cycle.

Primary target:
- per-run candidate artifact contract
- keep/discard/reset decision entrypoint

Success means:
1. candidate handoff artifact is explicit and test-covered
2. runtime can distinguish candidate / noop / abort / interrupted states
3. parity runtime tests pass
