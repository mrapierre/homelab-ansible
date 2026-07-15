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
#                      core.hooksPath for.
set -eu -o pipefail

: "${GITLEAKS_VERSION:?GITLEAKS_VERSION not set}"
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

  # Hermes finding (CRITICAL): the previous `grep ... | sha256sum -c -`
  # pipeline could silently "pass" if grep found no matching line -- under
  # plain `set -e` (no pipefail), a pipeline's exit status is only the LAST
  # command's. `set -o pipefail` above plus separating the grep out makes
  # the failure mode explicit either way.
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
    # Hermes finding (CRITICAL): embedding $REPO inside a double-quoted
    # `su -c "... '$REPO' ..."` string is injectable via an embedded single
    # quote. A first fix attempt (passing REPO as a positional arg to the
    # inner shell via `su ... -c '...' -- "$REPO"`) turned out to be
    # unreliable -- `su`'s handling of extra args after -c isn't consistent
    # enough to trust $1 actually arrives. Using `printf %q` instead:
    # produces a properly shell-escaped token that's safe to interpolate
    # back into a command string regardless of REPO's content, and this
    # mechanism is well-established/portable (this was live-tested and
    # confirmed working, unlike the positional-arg approach).
    REPO_Q=$(printf '%q' "$REPO")
    # --replace-all (not --add) so re-running doesn't accumulate duplicate
    # safe.directory entries (Hermes MEDIUM finding).
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
