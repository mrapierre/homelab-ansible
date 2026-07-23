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

Hardened again 2026-07-23 per the comprehensive final Kimi sweep
(backlog-346-everything-final-sweep):
- HIGH: the "already patched" check previously only looked for the marker
  comment. A partially reverted file (marker kept, wiring/function/imports
  removed by a manual edit) would report UNCHANGED -- "nothing to do,
  all good" -- to every caller (the n8n auto-reapply step, the Ansible
  role), while the actual argv leak fix was silently gone. Now verifies
  the marker AND the wiring AND the function definition AND both new
  imports before ever reporting UNCHANGED; a partial state is refused
  (UNSAFE exit) rather than silently accepted or blindly "fixed" by
  guessing what's missing.
- MEDIUM: writes were previously a bare open(path, "w") -- an interrupted
  process or storage failure mid-write could leave the file truncated.
  Now writes to a temp file in the same directory and os.replace()s it
  into place, which is atomic on the same filesystem.
"""
import os
import re
import sys

PATCH_MARKER = "HERMES-LOCALPATCH: oneshot-file-indirection v1"

# Anchored specifically to the -z/--oneshot parser.add_argument(...) block,
# not a bare substring search anywhere in the file (Kimi finding, medium:
# the previous unanchored regex could match a stray comment elsewhere and
# falsely conclude the patch was wired in).
WIRING_RE = re.compile(
    r'parser\.add_argument\(\s*\n\s*"-z"\s*,\s*\n\s*"--oneshot"\s*,'
    r'.*?type\s*=\s*_oneshot_prompt\s*,',
    re.DOTALL,
)
FUNCTION_DEF_RE = re.compile(r"^def _oneshot_prompt\(value: str\) -> str:", re.MULTILINE)

# DeepSeek cold review finding 2 (backlog-346-final-deepseek-crosscheck):
# the substring checks in _fully_wired() below used to check for
# "\nimport os\n" / "\nimport stat\n" literally, which assumed a
# specific byte-level layout -- would break on CRLF line endings, on
# the import being the very first line in the file, or on a combined
# "import os, stat". Anchored regexes match "import os"/"import stat"
# at the start of any line regardless of surrounding whitespace.
IMPORT_OS_RE = re.compile(r"^import os\b", re.MULTILINE)
IMPORT_STAT_RE = re.compile(r"^import stat\b", re.MULTILINE)

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
    # Hermes cold review finding 1 (backlog-346-ws2-ct152): the previous
    # version called os.path.getsize() then open() separately, leaving a
    # TOCTOU window where the file could be swapped between the size
    # check and the read. Fixed by opening once and doing both the size
    # check and the read against the SAME open file description, via
    # os.fstat() on the live fd rather than a fresh stat() on the path.
    #
    # Kimi cold review finding 3 (backlog-346-final-kimi-review): opening
    # the path with no symlink/file-type guard meant a swapped symlink
    # could redirect the prompt source, and a FIFO or device node could
    # hang the parser or return unbounded content. O_NOFOLLOW closes the
    # symlink path; the S_ISREG check after fstat rejects anything that
    # isn't a plain file, on the same open fd (no new TOCTOU window).
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        raise argparse.ArgumentTypeError(
            f"--oneshot: cannot read prompt file {path!r}: {exc}"
        )
    # DeepSeek cold review finding 3 (backlog-346-final-deepseek-crosscheck):
    # if os.fdopen() itself were to raise after os.open() already
    # succeeded, fd would leak (never closed). Not practically
    # attacker-triggerable -- os.fdopen() after a successful os.open()
    # is essentially infallible in CPython -- but cheap to close properly.
    try:
        fh = os.fdopen(fd, "rb")
    except Exception:
        os.close(fd)
        raise
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

    # Hermes cold review finding 2 (backlog-346-ws2-ct152): surrogateescape
    # was previously used to decode, which maps invalid UTF-8 bytes to lone
    # surrogates that crash any later strict-UTF-8 re-encode (JSON, HTTP
    # body, logging) with an unhandled UnicodeEncodeError deep downstream.
    # This is a code-review pipeline where source files are expected to be
    # valid UTF-8 -- reject invalid encoding loudly HERE, at parse time,
    # rather than let a mangled string travel further and fail somewhere
    # less diagnosable.
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise argparse.ArgumentTypeError(
            f"--oneshot: prompt file {path!r} is not valid UTF-8: {exc}"
        )

    if not text:
        # Hermes cold review finding 5 (backlog-346-ws2-ct152): message
        # corrected -- this guard rejects empty-of-bytes content only.
        # Whitespace-only files (e.g. a lone trailing newline) are NOT
        # rejected here; they are falsy-safe because a non-empty string
        # (even "\\n") is truthy, so the `if getattr(args, "oneshot", None)`
        # check at both call sites still takes the oneshot branch correctly.
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


def _fully_wired(content: str) -> bool:
    """True only if the marker, the wiring, the function definition, and
    both new imports are ALL present. Anything less is a partial state
    that must not be silently accepted."""
    return bool(
        PATCH_MARKER in content
        and WIRING_RE.search(content)
        and FUNCTION_DEF_RE.search(content)
        and IMPORT_OS_RE.search(content)
        and IMPORT_STAT_RE.search(content)
    )


def _atomic_write(path: str, content: str) -> None:
    """Write via a same-directory temp file + os.replace(), so an
    interrupted write can never leave the target truncated or corrupt."""
    tmp_path = f"{path}.tmp.{os.getpid()}"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(tmp_path, path)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch_hermes_parser.py <path-to-_parser.py>", file=sys.stderr)
        return 2
    path = sys.argv[1]

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    if _fully_wired(content):
        print("UNCHANGED")
        return 0

    if PATCH_MARKER in content:
        # Marker present but something else (wiring/function/imports) is
        # missing -- a partial, unexpected state. Do not guess at what to
        # fix; refuse and let a human re-verify ground truth, same as an
        # anchor mismatch below.
        print(f"UNSAFE: {PATCH_MARKER!r} is present in {path!r} but the "
              f"wiring/function/imports are not all intact -- this is a "
              f"partially reverted or hand-edited state, not the clean "
              f"unpatched state this script knows how to patch from. "
              f"Refusing to guess at what to fix.", file=sys.stderr)
        return 1

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

    if content.count("import argparse\n") != 1:
        print("UNSAFE: expected exactly 1 occurrence of 'import argparse', "
              "refusing to patch blindly.", file=sys.stderr)
        return 1
    content = content.replace("import argparse\n", "import argparse\nimport os\nimport stat\n", 1)

    if not _fully_wired(content):
        print("UNSAFE: patch was applied but self-verification failed -- "
              "the resulting file doesn't pass the same completeness check "
              "used to detect an already-patched file. Not writing anything.",
              file=sys.stderr)
        return 1

    _atomic_write(path, content)
    print("CHANGED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
