# Sevenbirches Homelab — Ansible

Infrastructure as Code for the Sevenbirches homelab.

## Structure
- `inventory/` — hosts and groups
- `playbooks/` — runbooks
- `roles/` — reusable roles
- `host_vars/` — per-host variables
- `group_vars/` — per-group variables

## Playbooks
- `harden_servers.yml` — SSH, UFW, fail2ban for VPS/VMs

## Usage
```bash
# Dry run
ansible-playbook playbooks/harden_servers.yml --check

# Run against specific host
ansible-playbook playbooks/harden_servers.yml --limit oracle

# Run all
ansible-playbook playbooks/harden_servers.yml
```
