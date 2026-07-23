#!/usr/bin/env python3
"""
patch_hermes_parser.py -- idempotently apply the backlog #346 oneshot-file-
indirection patch to a hermes-agent editable install's _parser.py.

Usage: patch_hermes_parser.py <path-to-_parser.py>

Prints CHANGED or UNCHANGED on the first line of stdout so the calling
Ansible task can set changed_when accordingly. Exits non-zero (without
modifying anything) if the file doesn't match the expected pre-patch shape
closely enough to patch safely -- a hermes upgrade that restructured this
file needs a human to re-verify ground truth (exactly the caution the
original WS2 changeset itself required), not a script guessing.

This is the SAME patch applied by hand to CT152 on 2026-07-22 (backlog-346-
ws2-ct152, cold-reviewed and gate-approved), with the Kimi second-opinion
symlink/regular-file hardening (backlog-346-final-kimi-review, finding 3)
folded in from the start rather than applied as a second pass.
"""
import sys

PATCH_MARKER = "HERMES-LOCALPATCH: oneshot-file-indirection v1"

PATCH_SNIPPET = '''# HERMES-LOCALPATCH: oneshot-file-indirection v1
# Local divergence from upstream hermes-agent. Submitted upstream as a PR
# to Nous Research's hermes-agent (not yet opened -- needs Anthony's GitHub
# involvement, tracked separately, not blocking this local patch). If this
# marker comment is absent, the patch has been reverted (almost certainly
# by an auto-update) and callers that rely on it MUST fail closed rather
# than silently fall back to argv delivery. See backlog #346.
#
# Invariant for maintainers (Hermes cold review, backlog-346-ws2-ct152,
# finding 7): the pre-argparse flag-scanning loops elsewhere in this CLI
# (main.py's value_flags set and the has_oneshot presence check) only
# test for the PRESENCE of -z/--oneshot; they never extract or interpret
# its value. If either loop is ever changed to inspect the value, it will
# see the literal "@/path" string, not the resolved file content, since
# resolution only happens here, at argparse parse time, via this type=
# callable. Do not let those scanners start interpreting the value
# without updating this invariant.
_ONESHOT_FILE_MAX_BYTES = 8 * 1024 * 1024


def _oneshot_prompt(value: str) -> str:
    """Resolve the -z/--oneshot value, optionally reading it from a file.

    A prompt passed as a literal argv element is published in
    /proc/<pid>/cmdline for the lifetime of the process, readable by
    anything that can see the PID. Callers handling sensitive prompts
    (source under review, pasted credentials) need a way to keep the
    content out of argv:

        -z @/abs/path/to/prompt.txt   read the prompt from that file
        -z @@literal                  a literal prompt that starts with '@'
        -z anything-else              used verbatim, unchanged

    Only an absolute path ('@/') is treated as a file reference, so an
    ordinary chat prompt beginning with '@' (an @mention, an email
    address, '@here') is never silently reinterpreted as a path.
    """
    if value.startswith("@@"):
        return value[1:]
    if not value.startswith("@/"):
        return value

    path = value[1:]
    # TOCTOU-safe (Hermes finding 1, backlog-346-ws2-ct152): size check
    # and read happen against the SAME open fd, not a separate stat().
    # Symlink/regular-file-safe (Kimi finding 3, backlog-346-final-kimi-
    # review): O_NOFOLLOW + S_ISREG on that same fd, no new TOCTOU window.
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        raise argparse.ArgumentTypeError(
            f"--oneshot: cannot read prompt file {path!r}: {exc}"
        )
    fh = os.fdopen(fd, "rb")
    try:
        st = os.fstat(fh.fileno())
        if not stat.S_ISREG(st.st_mode):
            raise argparse.ArgumentTypeError(
                f"--oneshot: prompt file {path!r} is not a regular file "
                f"(refusing symlinks, FIFOs, device nodes, etc.)"
            )
        size = st.st_size
        if size > _ONESHOT_FILE_MAX_BYTES:
            raise argparse.ArgumentTypeError(
                f"--oneshot: prompt file {path!r} is {size} bytes, over the "
                f"{_ONESHOT_FILE_MAX_BYTES}-byte limit"
            )
        raw = fh.read()
    finally:
        fh.close()

    # Strict UTF-8 (Hermes finding 2, backlog-346-ws2-ct152): surrogateescape
    # would let invalid UTF-8 through and crash a later strict re-encode
    # somewhere less diagnosable. This is a code-review pipeline where
    # source is expected to be valid UTF-8 -- reject loudly here instead.
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise argparse.ArgumentTypeError(
            f"--oneshot: prompt file {path!r} is not valid UTF-8: {exc}"
        )

    if not text:
        # Zero-byte check only (Hermes finding 5): whitespace-only content
        # (e.g. a lone trailing newline) is NOT rejected -- it's truthy, so
        # the `if getattr(args, "oneshot", None)` check at both call sites
        # still takes the oneshot branch correctly.
        raise argparse.ArgumentTypeError(
            f"--oneshot: prompt file {path!r} is empty (zero bytes)"
        )
    return text


'''

ANCHOR = "\ndef build_top_level_parser():"

OLD_ARG_BLOCK = '''    parser.add_argument(
        "-z",
        "--oneshot",
        metavar="PROMPT",
        default=None,
        help=(
            "One-shot mode: send a single prompt and print ONLY the final "
            "response text to stdout. No banner, no spinner, no tool "
            "previews, no session_id line. Tools, memory, rules, and "
            "AGENTS.md in the CWD are loaded as normal; approvals are "
            "auto-bypassed. Intended for scripts / pipes."
        ),
    )'''

NEW_ARG_BLOCK = '''    parser.add_argument(
        "-z",
        "--oneshot",
        metavar="PROMPT",
        default=None,
        type=_oneshot_prompt,
        help=(
            "One-shot mode: send a single prompt and print ONLY the final "
            "response text to stdout. No banner, no spinner, no tool "
            "previews, no session_id line. Tools, memory, rules, and "
            "AGENTS.md in the CWD are loaded as normal; approvals are "
            "auto-bypassed. Intended for scripts / pipes. PROMPT may be "
            "'@/absolute/path' to read the prompt from a file instead of "
            "argv (keeps sensitive content out of /proc/<pid>/cmdline); "
            "use '@@literal' to send a literal prompt that itself starts "
            "with '@'."
        ),
    )'''


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch_hermes_parser.py <path-to-_parser.py>", file=sys.stderr)
        return 2
    path = sys.argv[1]

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    if PATCH_MARKER in content:
        print("UNCHANGED")
        return 0

    if content.count(ANCHOR) != 1:
        print(f"UNSAFE: expected exactly 1 occurrence of the insertion anchor, "
              f"found {content.count(ANCHOR)} -- hermes-agent's _parser.py has "
              f"likely been restructured by an update. Refusing to patch "
              f"blindly; re-verify ground truth by hand (see backlog #346 "
              f"WS2's own re-verification note about this exact scenario) "
              f"before adapting this script.", file=sys.stderr)
        return 1

    if content.count(OLD_ARG_BLOCK) != 1:
        print(f"UNSAFE: expected exactly 1 occurrence of the original -z "
              f"argument block, found {content.count(OLD_ARG_BLOCK)} -- "
              f"refusing to patch blindly, same reasoning as above.",
              file=sys.stderr)
        return 1

    content = content.replace(ANCHOR, "\n" + PATCH_SNIPPET + "def build_top_level_parser():", 1)
    content = content.replace(OLD_ARG_BLOCK, NEW_ARG_BLOCK, 1)

    # Fresh/unpatched hermes-agent installs have only "import argparse" here
    # (no "import os" yet -- that's part of what this patch adds). Insert
    # both new imports together, anchored on the original single import.
    if content.count("import argparse\n") != 1:
        print(f"UNSAFE: expected exactly 1 occurrence of 'import argparse', "
              f"found {content.count('import argparse' + chr(10))} -- "
              f"refusing to patch blindly.", file=sys.stderr)
        return 1
    content = content.replace("import argparse\n", "import argparse\nimport os\nimport stat\n", 1)

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("CHANGED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
