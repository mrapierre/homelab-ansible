# Sevenbirches Homelab — Ansible

Infrastructure as Code for the Sevenbirches homelab.

## Structure
- `inventory/` — hosts and groups
- `playbooks/` — runbooks
- `roles/` — reusable roles
- `host_vars/` — per-host variables
- `group_vars/` — per-group variables

## Playbooks

- `site.yml` — top-level entry point
- `harden_servers.yml` — SSH, UFW, fail2ban for VPS/VMs
- `harden_containers.yml` — baseline hardening for LXC containers via `pct exec`
- `rebuild_containers.yml` — disaster-recovery rebuild for LXC containers
- `rebuild_services.yml` — disaster-recovery rebuild for services running on those containers
- `rebuild_vps.yml` — disaster-recovery rebuild for the remote VPS hosts
- `vm151_homelab_agent.yml` — provisions VM151 (Homelab Agent: Flask API + knowledge base)
- `ct100_plex.yml` — provisions CT100 (Plex)
- `smoke_test.yml` — post-rebuild sanity checks
- `git_precommit_gate.yml` — deploys the universal git pre-commit/pre-push
  secret-scanning gate (gitleaks) to every host that has one or more git repos
  on it. Idempotent, credential-free. Targets the `git_hooks_hosts` inventory
  group. CT148 is normally stopped between sessions -- `pct start 148` first if
  it needs (re-)provisioning there.

## Usage
```bash
# Dry run
ansible-playbook playbooks/harden_servers.yml --check

# Run against specific host
ansible-playbook playbooks/harden_servers.yml --limit oracle

# Run all
ansible-playbook playbooks/harden_servers.yml
```
