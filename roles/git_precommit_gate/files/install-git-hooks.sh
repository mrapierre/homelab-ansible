#!/usr/bin/env bash
# Canonical installer for the universal gitleaks pre-commit/pre-push gate
# (backlog #305/#306). Single source of truth for both deployment paths:
# VM151 runs this directly over SSH; LXC containers get it pushed in via
# `pct push` and run via `pct exec ... bash install-git-hooks.sh`
# (backlog #308 -- previously these were two separate implementations).
#
# Required env vars:
#   GITLEAKS_VERSION        e.g. 8.30.1
#   GITLEAKS_CHECKSUMS_SHA256  the SHA256 of gitleaks' own published
#                            checksums.txt for this version, pinned in our
#                            own Ansible config (not fetched from GitHub) --
#                            see backlog #305 follow-up F3. gitleaks doesn't
#                            GPG-sign or cosign-attest their release
#                            checksums file, so this pin is the practical
#                            substitute: an attacker would need to
#                            compromise the GitHub release asset AND get us
#                            to deliberately re-pin a new hash, not just one
#                            or the other.
#   TARGET_USER              user to run `git config` as (root, anthony, ...)
#   FILES_DIR                directory on THIS host containing gitleaks.toml,
#                            pre-commit-gitleaks.sh, pre-push-gitleaks.sh,
#                            pre-commit, pre-push (already staged before this
#                            runs)
# Optional:
#   REPOS                    space-separated absolute repo paths to wire
#                            core.hooksPath for.
set -eu -o pipefail

: "${GITLEAKS_VERSION:?GITLEAKS_VERSION not set}"
: "${GITLEAKS_CHECKSUMS_SHA256:?GITLEAKS_CHECKSUMS_SHA256 not set}"
: "${TARGET_USER:?TARGET_USER not set}"
: "${FILES_DIR:?FILES_DIR not set}"
REPOS="${REPOS:-}"

mkdir -p /opt/git-hooks/bin /opt/git-hooks/lib /opt/git-hooks/hooks /opt/git-hooks/template/hooks

# Exact, trimmed version comparison -- not a substring match.
INSTALLED=$(/opt/git-hooks/bin/gitleaks version 2>/dev/null | tr -d '[:space:]' || true)
if [ "$INSTALLED" != "$GITLEAKS_VERSION" ]; then
  cd /tmp
  TARBALL="gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz"
  CHECKSUMS="gitleaks_${GITLEAKS_VERSION}_checksums.txt"
  cleanup() { rm -f "$TARBALL" "$CHECKSUMS"; }
  trap cleanup EXIT

  curl -fsSL -o "$TARBALL" \
    "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/${TARBALL}"
  curl -fsSL -o "$CHECKSUMS" \
    "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/${CHECKSUMS}"

  # Hermes finding (MEDIUM, ansible-unify-lxc-vm review F3): verify the
  # checksums FILE ITSELF against a hash pinned in our own Ansible config
  # before trusting it to verify the tarball. gitleaks doesn't publish a
  # signature for this file, so this pin is the practical substitute --
  # closes the gap where an attacker compromising the GitHub release could
  # otherwise swap the tarball and the checksums file together.
  ACTUAL_CHECKSUMS_SHA256=$(sha256sum "$CHECKSUMS" | awk '{print $1}')
  if [ "$ACTUAL_CHECKSUMS_SHA256" != "$GITLEAKS_CHECKSUMS_SHA256" ]; then
    echo "FATAL: gitleaks_${GITLEAKS_VERSION}_checksums.txt does not match the pinned hash." >&2
    echo "  expected: $GITLEAKS_CHECKSUMS_SHA256" >&2
    echo "  got:      $ACTUAL_CHECKSUMS_SHA256" >&2
    echo "If you deliberately bumped GITLEAKS_VERSION, re-pin GITLEAKS_CHECKSUMS_SHA256 in the Ansible config to match -- don't just accept whatever's on GitHub right now." >&2
    exit 1
  fi

  # Now verify the tarball against the (now-trusted) checksums file.
  CHECKSUM_LINE=$(grep "$TARBALL" "$CHECKSUMS")
  echo "$CHECKSUM_LINE" | sha256sum -c -

  tar xzf "$TARBALL" gitleaks
  mv gitleaks /opt/git-hooks/bin/gitleaks
  chmod +x /opt/git-hooks/bin/gitleaks
  trap - EXIT
  cleanup
  echo "gitleaks installed and checksum-verified ($GITLEAKS_VERSION)"
else
  echo "gitleaks already at $GITLEAKS_VERSION"
fi

cp "$FILES_DIR/gitleaks.toml" /opt/git-hooks/gitleaks.toml
cp "$FILES_DIR/pre-commit-gitleaks.sh" /opt/git-hooks/lib/pre-commit-gitleaks.sh
cp "$FILES_DIR/pre-push-gitleaks.sh" /opt/git-hooks/lib/pre-push-gitleaks.sh
cp "$FILES_DIR/pre-commit" /opt/git-hooks/hooks/pre-commit
cp "$FILES_DIR/pre-push" /opt/git-hooks/hooks/pre-push
cp "$FILES_DIR/pre-commit" /opt/git-hooks/template/hooks/pre-commit
cp "$FILES_DIR/pre-push" /opt/git-hooks/template/hooks/pre-push

chmod +x /opt/git-hooks/lib/pre-commit-gitleaks.sh /opt/git-hooks/lib/pre-push-gitleaks.sh \
  /opt/git-hooks/hooks/pre-commit /opt/git-hooks/hooks/pre-push \
  /opt/git-hooks/template/hooks/pre-commit /opt/git-hooks/template/hooks/pre-push
chmod -R a+rX /opt/git-hooks

su "$TARGET_USER" -c 'git config --global init.templateDir /opt/git-hooks/template'

if [ -n "$REPOS" ]; then
  for REPO in $REPOS; do
    REPO_Q=$(printf '%q' "$REPO")
    su "$TARGET_USER" -c "git config --global --replace-all safe.directory $REPO_Q"
    if su "$TARGET_USER" -c "git -C $REPO_Q config core.hooksPath /opt/git-hooks/hooks"; then
      echo "$REPO wired"
    else
      echo "$REPO FAILED -- repo missing or $TARGET_USER lacks access" >&2
      exit 1
    fi
  done
fi

echo "done"
