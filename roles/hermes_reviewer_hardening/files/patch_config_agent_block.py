#!/usr/bin/env python3
"""
patch_config_agent_block.py -- idempotently add agent.disabled_toolsets to
a hermes profile's config.yaml (backlog #347 WS1.3).

Usage: patch_config_agent_block.py <config.yaml path> <has_existing_agent_block: true|false> <comma-separated toolset list>

Prints CHANGED or UNCHANGED on the first line of stdout. Refuses (exits
non-zero, no write) rather than guess if has_existing_agent_block=true but
no "agent:" line is actually found -- that mismatch means the config
drifted from what the caller expected, and blind insertion risks
duplicating or misplacing the key.

Hardened 2026-07-23 per the comprehensive final Kimi sweep
(backlog-346-everything-final-sweep, medium finding): writes were
previously a bare open(path, "w") -- an interrupted process or storage
failure mid-write could leave config.yaml truncated. Now writes to a
temp file in the same directory and os.replace()s it into place, atomic
on the same filesystem, matching the same fix applied to
patch_hermes_parser.py.
"""
import os
import re
import sys


def _atomic_write(path: str, content: str) -> None:
    tmp_path = f"{path}.tmp.{os.getpid()}"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(tmp_path, path)

DISABLED_TOOLSETS_COMMENT = (
    "  # disabled_toolsets composes unconditionally as a subtraction step --\n"
    "  # it is NOT inert when enabled_toolsets/-t is set elsewhere. Two\n"
    "  # independent layers are live for this profile: the -t todo pin at the\n"
    "  # fire script call site, and this list. Removing the -t pin does not\n"
    "  # disable this layer. See backlog #347.\n"
)


def build_block(toolsets: list[str], indent: str) -> str:
    lines = [f"{indent}disabled_toolsets:"]
    for t in toolsets:
        lines.append(f"{indent}  - {t}")
    return "\n".join(lines) + "\n" + DISABLED_TOOLSETS_COMMENT


def main() -> int:
    if len(sys.argv) != 4:
        print("usage: patch_config_agent_block.py <config.yaml> <true|false> <toolset,list>",
              file=sys.stderr)
        return 2
    path, has_agent_block_str, toolsets_csv = sys.argv[1], sys.argv[2], sys.argv[3]
    has_agent_block = has_agent_block_str.strip().lower() == "true"
    toolsets = [t.strip() for t in toolsets_csv.split(",") if t.strip()]

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    if "disabled_toolsets:" in content:
        print("UNCHANGED")
        return 0

    if has_agent_block:
        m = re.search(r"^agent:\n", content, re.MULTILINE)
        if not m:
            print(f"UNSAFE: has_existing_agent_block=true but no top-level "
                  f"'agent:' line found in {path!r} -- config has drifted "
                  f"from what was expected. Refusing to patch blindly.",
                  file=sys.stderr)
            return 1
        insert_at = m.end()
        block = build_block(toolsets, "  ")
        content = content[:insert_at] + block + content[insert_at:]
    else:
        if re.search(r"^agent:\n", content, re.MULTILINE):
            print(f"UNSAFE: has_existing_agent_block=false but an 'agent:' "
                  f"line already exists in {path!r} -- config has drifted "
                  f"from what was expected (someone/something added an "
                  f"agent: block since this role's vars were last set). "
                  f"Refusing to patch blindly -- fix the role var or "
                  f"reconcile the config by hand.", file=sys.stderr)
            return 1
        block = build_block(toolsets, "  ")
        content = content.rstrip("\n") + "\n\nagent:\n" + block

    _atomic_write(path, content)
    print("CHANGED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
