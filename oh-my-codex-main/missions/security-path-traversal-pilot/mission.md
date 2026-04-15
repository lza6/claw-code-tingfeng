# Mission: MCP path-traversal hardening

Strengthen path-validation and traversal defenses around MCP/state-facing surfaces without expanding scope into unrelated security work.

## Goal
Improve confidence that unsafe paths and traversal attempts are rejected deterministically with actionable errors.

## Focus areas
- `src/mcp/__tests__/path-traversal.test.ts`
- `src/mcp/__tests__/state-paths.test.ts`
- adjacent MCP/state validation code touched by those tests

## Desired output
Produce the smallest safe hardening diff that:
1. preserves existing allowed-path behavior
2. tightens traversal rejection where needed
3. keeps the targeted security regression slice green

## Success hints
- prefer boundary checks and validation tightening over broad refactors
- preserve current CLI/MCP contracts unless the change is necessary to block unsafe input
- document any intentionally unsupported path patterns if surfaced by the work
