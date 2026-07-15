#!/usr/bin/env bash
set -eu

GITLEAKS_BIN="/opt/git-hooks/bin/gitleaks"
GITLEAKS_CONFIG="/opt/git-hooks/gitleaks.toml"
REMOTE="$1"
URL="$2"

if [ ! -x "$GITLEAKS_BIN" ]; then
  echo "pre-push: gitleaks binary not found at $GITLEAKS_BIN -- blocking push rather than skipping the scan. Ask Anthony to check /opt/git-hooks/bin." >&2
  exit 1
fi

if [ ! -f "$GITLEAKS_CONFIG" ]; then
  echo "pre-push: gitleaks config not found at $GITLEAKS_CONFIG -- blocking push rather than scanning with no config." >&2
  exit 1
fi

found_any=0
while read -r local_ref local_sha remote_ref remote_sha; do
  case "$local_sha" in
    0000000000000000000000000000000000000000) continue ;;
  esac

  if [ "$remote_sha" = "0000000000000000000000000000000000000000" ]; then
    range="$local_sha"
    scan_args="--log-opts=$range"
  else
    range="$remote_sha..$local_sha"
    scan_args="--log-opts=$range"
  fi

  set +e
  output=$("$GITLEAKS_BIN" git --config "$GITLEAKS_CONFIG" --redact --verbose --no-banner "$scan_args" 2>&1)
  status=$?
  set -e

  if [ "$status" -ne 0 ]; then
    echo "$output" >&2
    echo "" >&2
    echo "pre-push BLOCKED ($local_ref -> $remote_ref): gitleaks found what looks like a secret in the commits being pushed." >&2
    echo "This means it slipped past pre-commit -- likely via --no-verify. Fix the offending commit(s) (e.g. git rebase / filter-repo) rather than pushing anyway." >&2
    found_any=1
  fi
done

if [ "$found_any" -ne 0 ]; then
  exit 1
fi

exit 0
