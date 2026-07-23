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

## Automatic reapply after CT152's nightly update (separate from this role)

CT152 runs a daily `hermes update` (n8n workflow "Hermes Auto-Update
(CT152, Daily)", id `9JG2OZAtAHFTjmrR`, 3am kick-off / 3:15am check)
that does a `git pull` inside `/usr/local/lib/hermes-agent` -- the ONLY
thing that touches is `_parser.py`. The fire script, assert script, and
`config.yaml` all live under `/root/.hermes/` (HERMES_HOME), which the
update never goes near.

Because of that, keeping CT152's `_parser.py` patch alive after every
update does NOT go through this role or Ansible at all. Instead:
`files/patch_hermes_parser.py` (the same script this role uses) is ALSO
deployed permanently and directly to CT152 at
`/root/.hermes/handover/patch_hermes_parser.py` (deployed by hand,
2026-07-23 -- not tracked by any Ansible run, so if this role's copy of
patch_hermes_parser.py is ever changed, CT152's standalone copy needs
updating separately, by hand or via the ad hoc playbook below). The
n8n workflow's post-update check now runs it automatically, before
restarting the dashboard: if the patch survived, it's a no-op
(`UNCHANGED`); if the update wiped it, it's silently reapplied
(`CHANGED`) and a privilege-assertion sanity check runs afterward, with
the outcome reported to Telegram either way. Verified for real
2026-07-23 by deliberately reverting CT152's `_parser.py` to its
pre-patch state, simulating a successful update, and confirming the
workflow's exact stored command detected and repaired it.

This means: **the fire script / assert script / config.yaml never need
reapplying** (they're never touched by the update), and **`_parser.py`
reapplies itself automatically** (via the n8n step, not this role).
The only reason to actually run this Ansible role against CT152 again
is a genuine config change (e.g. widening/narrowing the allowlist) or
suspected drift outside the update path -- for that, see the ad hoc
playbook below.

## Re-running the full role against CT152 by hand

CT152 still isn't in this repo's inventory (see Known gaps). For a
full manual re-apply (all five deployed pieces, not just the
`_parser.py` patch the n8n step handles), use the dedicated ad hoc
playbook, which targets CT152 by IP directly and needs no inventory
entry:

```
cd /opt/ansible
ansible-playbook -i "192.168.55.152," playbooks/hermes_reviewer_hardening_ct152_adhoc.yml
```

This is also how the role itself was verified idempotent against
CT152 in the first place (`changed=0` on a second run). Delete this
playbook and fold CT152 into `hermes_reviewer_hardening.yml` properly
once backlog #342 lands.

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
