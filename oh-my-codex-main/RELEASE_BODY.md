# oh-my-codex v0.11.12

**Patch release for Windows flicker fixes, team/runtime seam hardening, cross-platform Node test execution, and workflow docs alignment**

`0.11.12` follows `0.11.11` with a focused patch train from `v0.11.11..dev`: it removes more Windows conhost flicker paths, closes additional team/runtime seam gaps, makes Node test execution portable across platforms, and standardizes docs around the current deep-interview → ralplan → team/ralph workflow.

## Highlights

- Windows users get broader flicker prevention from `windowsHide` coverage and filesystem-based git-info reads.
- Team/runtime state handling closes more thin-adapter seam gaps while keeping tmux auto-nudge behavior scoped to OMX-managed sessions.
- Node test execution is now cross-platform, reducing shell-environment assumptions in release verification.
- Workflow docs now consistently point to the current OMX planning/execution path.

## What’s Changed

### Fixes
- remove more Windows terminal flicker paths across child-process launches and git-info reads
- harden team/runtime seam handling across manifest.v2 cwd resolution plus dispatch/mailbox state transitions
- keep tmux readiness + auto-nudge behavior restricted to OMX-managed sessions

### Changed
- add a cross-platform Node test-file runner for release/test portability
- standardize workflow docs around deep-interview → ralplan → team/ralph
- bump release metadata from `0.11.11` to `0.11.12` across the Node and Cargo workspace packages and lockfiles
- refresh `CHANGELOG.md`, `docs/release-notes-0.11.12.md`, and `RELEASE_BODY.md` for the release cut

## Verification

- `cargo check --workspace`
- `npm run build`
- `npm run lint`
- `node --test dist/cli/__tests__/version-sync-contract.test.js`
- release-workflow inline version-sync check from `.github/workflows/release.yml`
- `npm run test:node:cross-platform`
- `npm run smoke:packed-install`

## Remaining risk

- This release is still a targeted patch verification pass, not a full GitHub Actions matrix rerun.
- Future workflow doc edits should preserve the deep-interview → ralplan → team/ralph path as the default onboarding story.

## Contributors

- [@Yeachan-Heo](https://github.com/Yeachan-Heo) (Bellman)

**Full Changelog**: [`v0.11.11...v0.11.12`](https://github.com/Yeachan-Heo/oh-my-codex/compare/v0.11.11...v0.11.12)
