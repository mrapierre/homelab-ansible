# Disaster Recovery Runbook — Sevenbirches Homelab

Plain-English steps for what to actually type, in order, when something needs
rebuilding. This is the companion to `README.md` — that file lists what each
playbook does, this one tells you the exact sequence to run.

**Golden rule, every time, no exceptions:** dry-run first, review the diff,
get explicit go-ahead, then run live. Never run a playbook live against
working infrastructure without confirming scope first.

---

## 0. Before you do anything

```bash
ssh root@192.168.55.104          # or: pct exec 104 -- bash, from the Proxmox host
cd /opt/ansible
git pull                         # make sure you're on the latest committed playbooks
```

Decide which scenario below matches what actually broke. Don't run `site.yml`
for a single dead container — that's the full bare-metal scenario.

---

## Scenario A — Full rebuild after bare-metal Proxmox reinstall

Everything is gone. Proxmox itself has just been reinstalled.

```bash
# 1. Dry run the whole thing first
ansible-playbook site.yml --check --diff

# 2. Read the diff. Confirm scope out loud (with Claude or on your own) before continuing.

# 3. Run it live, stage by stage rather than all at once
ansible-playbook site.yml --tags containers
ansible-playbook site.yml --tags services
ansible-playbook site.yml --tags vps

# 4. Verify
ansible-playbook smoke_test.yml
```

If you want it all in one go instead of stage by stage: `ansible-playbook site.yml`
(still dry-run it first as in step 1).

---

## Scenario B — One container is dead or corrupted (e.g. CT120 gone)

```bash
# 1. Dry run against just that host
ansible-playbook rebuild_containers.yml --check --diff --limit ct120

# 2. Confirm scope, then run live
ansible-playbook rebuild_containers.yml --limit ct120

# 3. Bring its services back
ansible-playbook rebuild_services.yml --check --diff --limit ct120
ansible-playbook rebuild_services.yml --limit ct120

# 4. Verify
ansible-playbook smoke_test.yml --limit ct120
```

Valid host names for `--limit` are in `inventory/hosts.yml`: ct100–ct148,
vm151, ihostart, oracle. (ct148 is normally kept stopped — run
`pct start 148` on the Proxmox host first if you need it.)

---

## Scenario C — A service is broken but the container itself is fine

Same as Scenario B but skip the container step, go straight to services:

```bash
ansible-playbook rebuild_services.yml --check --diff --limit <host>
ansible-playbook rebuild_services.yml --limit <host>
ansible-playbook smoke_test.yml --limit <host>
```

---

## Scenario D — A remote VPS is gone (ihostart or oracle)

```bash
ansible-playbook rebuild_vps.yml --check --diff --limit ihostart   # or: --limit oracle
ansible-playbook rebuild_vps.yml --limit ihostart
ansible-playbook smoke_test.yml --limit ihostart
```

---

## Scenario E — Just need to re-harden something (SSH/UFW/fail2ban)

Not disaster recovery exactly, but the same muscle memory:

```bash
ansible-playbook harden_servers.yml --check --diff --limit <host>     # VPS/VMs
ansible-playbook harden_containers.yml --check --diff --limit <host>  # LXC containers
```

---

## After any live run

1. `ansible-playbook smoke_test.yml` (scoped with `--limit` if it was a
   partial rebuild) — checks gateway reachability, DNS, Proxmox API, and
   remote access.
2. Spot-check the actual service in a browser / SSH session, don't just trust
   the smoke test.
3. Commit and push if anything in the repo changed:
   ```bash
   cd /opt/ansible && git add -A && git commit -m "post-DR run: <what happened>" && git push
   ```

## If you're not sure which scenario applies

Stop and ask Claude before running anything live. Paste what's actually
broken (container name, error, what you last changed) and get the scenario
and `--limit` confirmed before the first live command.
