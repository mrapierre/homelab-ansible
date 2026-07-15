#!/usr/bin/env bash
set -eu

GITLEAKS_BIN="/opt/git-hooks/bin/gitleaks"
GITLEAKS_CONFIG="/opt/git-hooks/gitleaks.toml"

if [ ! -x "$GITLEAKS_BIN" ]; then
  echo "pre-commit: gitleaks binary not found at $GITLEAKS_BIN -- the universal scan cannot run, so this commit is being blocked rather than silently skipped. Ask Anthony to check /opt/git-hooks/bin." >&2
  exit 1
fi

if [ ! -f "$GITLEAKS_CONFIG" ]; then
  echo "pre-commit: gitleaks config not found at $GITLEAKS_CONFIG -- blocking rather than scanning with no config. Ask Anthony to check /opt/git-hooks/gitleaks.toml." >&2
  exit 1
fi

if git diff --cached --name-only | grep -qxF '.gitleaksignore'; then
  echo "pre-commit BLOCKED: .gitleaksignore is staged in this commit. Remove it -- allowlist exceptions go in the central config at /opt/git-hooks/gitleaks.toml instead." >&2
  exit 1
fi

set +e
output=$("$GITLEAKS_BIN" protect --staged --config "$GITLEAKS_CONFIG" --redact --verbose --no-banner 2>&1)
status=$?
set -e

echo "$output"

if [ "$status" -ne 0 ]; then
  echo "" >&2
  echo "pre-commit BLOCKED: gitleaks found what looks like a secret in the staged changes (see above)." >&2
  echo "If this is a genuine false positive, flag it to Anthony to add an allowlist entry to the central config at /opt/git-hooks/gitleaks.toml -- don't bypass with --no-verify." >&2
  exit "$status"
fi

if echo "$output" | grep -qE '(WARN|ERROR|FATA)'; then
  echo "pre-commit: gitleaks exited 0 but printed warnings above -- worth a look. Commit is proceeding." >&2
fi

exit 0
