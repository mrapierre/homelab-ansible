# hermes_reviewer_hardening

Backlog #346 (reviewer prompt leaking via `/proc/<pid>/cmdline`), #347
(reviewer profiles over-privileged), #348/#349 (prompt snapshot lifecycle),
plus a Kimi second-opinion hardening pass (symlink-overwrite protection,
umask windows, patch-wiring verification, and more) folded in from the
start rather than applied as a separate pass.

## What it deploys

- **`_parser.py` patch** (idempotent, marker-gated): adds `-z @/path`
  file-indirection to hermes' `--oneshot` argument, so a reviewed prompt
  never has to travel through argv (and therefore never appears in
  `/proc/<pid>/cmdline`). Symlink- and non-regular-file-safe
  (`O_NOFOLLOW` + `S_ISREG` on the same open fd, no TOCTOU window).
- **Fire script** (`fire_local_reviewer.py` / `fire_reviewer_agent.py`,
  templated): launches the reviewer with the prompt passed as a file
  reference, not content. Output/`.err` files created `O_NOFOLLOW` +
  `0600`-from-birth (temporary `umask(0o077)` around creation, not just
  an after-the-fact `fchmod`). Fail-closed preflight: refuses to spawn
  if the `_parser.py` patch is missing OR only partially present (marker
  kept but wiring removed), or if the privilege assertion fails.
- **`assert_reviewer_privileges.py`** (templated): regression guard.
  Fails if the profile has anything enabled outside the allowlist
  (widening) OR if a required toolset from the allowlist has gone
  missing (narrowing — e.g. `todo` disappearing would hang the reviewer
  in interactive-chat fallback).
- **`config.yaml` `agent.disabled_toolsets`** (idempotent, key-gated):
  second independent layer alongside the fire script's `-t todo` pin.
- **Stale-file cron sweeper** (optional, `hermes_reviewer_hardening_install_sweeper`):
  hourly cleanup of `/tmp/rr_prompt_*`/`rr_out_*` older than 24h, as
  defence in depth for the case the orchestrator (`run_review.py` on
  VM151) dies hard mid-review and its own `try/finally` cleanup never
  runs.

## What it does NOT deploy

`run_review.py` itself (WS3: snapshot 0600-from-birth, try/finally
cleanup, `shlex.quote()` hardening) — that's a single shared file on
VM151 with no per-host variation, so there's nothing here to templatize.
Deploying it is out of scope for this role.

## Idempotency

Every patcher script checks its own marker/key before writing and
prints `UNCHANGED` if already applied — the `command` tasks that wrap
them use `changed_when: stdout | trim == 'CHANGED'` (an exact match,
not substring containment — a first attempt at this used `'CHANGED' in
stdout`, which also matches the literal string `"UNCHANGED"` and had to
be corrected). Verified 2026-07-23 via a throwaway ad-hoc inventory
against CT152 (never touched this repo's committed inventory): first
run correctly reported `UNCHANGED` on both patchers since CT152 already
had everything hand-applied and gate-approved; second run reported
`changed=0` across the board.

## Known gaps

- **CT152 isn't in this repo's inventory yet** (backlog #342 — its own
  dedicated session by design). The role and its patcher scripts are
  ready for it; only the inventory entry and a host-specific play are
  missing.
- **VPS-side vars are unverified.** `hermes_reviewer_hardening.yml`
  targets `vps_ihostart`, but every value for it (profile names, wrapper
  paths, `_parser.py` layout) is carried over from the original
  pre-hardening design sheet, not confirmed live — ihostart was down
  for the entire session this role was built in. The patcher scripts
  refuse to write blind if their anchors don't match (`UNSAFE` exit,
  no changes made), but "refuses safely" isn't the same as "verified
  correct" — a profile-name or path mismatch would just silently do
  nothing useful rather than error. Re-verify ground truth on ihostart
  before the first real run there.
