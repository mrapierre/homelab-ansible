#!/usr/bin/env bash
# Canonical installer for the universal gitleaks pre-commit/pre-push gate
# (backlog #305/#306). Single source of truth for both deployment paths:
# VM151 runs this directly over SSH; LXC containers get it pushed in via
# `pct push` and run via `pct exec ... bash install-git-hooks.sh`
# (backlog #308 -- previously these were two separate implementations).
#
# Required env vars:
#   GITLEAKS_VERSION   e.g. 8.30.1
#   TARGET_USER        user to run `git config` as (root, anthony, ...)
#   FILES_DIR          directory on THIS host containing gitleaks.toml,
#                      pre-commit-gitleaks.sh, pre-push-gitleaks.sh,
#                      pre-commit, pre-push (already staged before this runs)
# Optional:
#   REPOS              space-separated absolute repo paths to wire
#                      core.hooksPath for. None of the current repo paths
#                      contain spaces; this script assumes that stays true.
set -eu

: "${GITLEAKS_VERSION:?GITLEAKS_VERSION not set}"
: "${TARGET_USER:?TARGET_USER not set}"
: "${FILES_DIR:?FILES_DIR not set}"
REPOS="${REPOS:-}"

mkdir -p /opt/git-hooks/bin /opt/git-hooks/lib /opt/git-hooks/hooks /opt/git-hooks/template/hooks

# Exact, trimmed version comparison -- NOT a substring match (Hermes F4 from
# the original review: "8.30.1" is a substring of "8.30.10", which would
# falsely pass as already-installed under a naive `in` check).
INSTALLED=$(/opt/git-hooks/bin/gitleaks version 2>/dev/null | tr -d '[:space:]' || true)
if [ "$INSTALLED" != "$GITLEAKS_VERSION" ]; then
  cd /tmp
  TARBALL="gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz"
  CHECKSUMS="gitleaks_${GITLEAKS_VERSION}_checksums.txt"

  curl -fsSL -o "$TARBALL" \
    "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/${TARBALL}"
  curl -fsSL -o "$CHECKSUMS" \
    "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/${CHECKSUMS}"

  # Integrity verification (Hermes F3 from the original review) -- a
  # compromised release asset or MITM'd download would otherwise install a
  # binary that then runs on every commit/push across every wired repo.
  grep "$TARBALL" "$CHECKSUMS" | sha256sum -c -

  tar xzf "$TARBALL" gitleaks
  mv gitleaks /opt/git-hooks/bin/gitleaks
  chmod +x /opt/git-hooks/bin/gitleaks
  rm -f "$TARBALL" "$CHECKSUMS"
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

su "$TARGET_USER" -c "git config --global init.templateDir /opt/git-hooks/template"

# Repo wiring fails loudly (Hermes F5 from the original review) -- a repo
# that can't be wired exits this script non-zero rather than silently
# reporting success.
if [ -n "$REPOS" ]; then
  for REPO in $REPOS; do
    su "$TARGET_USER" -c "git config --global --add safe.directory '$REPO'"
    if su "$TARGET_USER" -c "cd '$REPO' && git config core.hooksPath /opt/git-hooks/hooks"; then
      echo "$REPO wired"
    else
      echo "$REPO FAILED -- repo missing or $TARGET_USER lacks access" >&2
      exit 1
    fi
  done
fi

echo "done"
