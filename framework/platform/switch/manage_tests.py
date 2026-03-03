#!/usr/bin/env python3
"""
dEQP-GLES2 test list manager for SwitchGLES.

Commands:
  init                          Create pending.txt from baseline minus pass/skip
  next-batch N [category,...]   Move N tests from pending -> current
  generate-caselist MODE        Convert current|pass to trie -> romfs/caselist.txt
  parse FILE                    Parse nxlink stdout for test results
  promote FILE                  Move Pass->pass, NotSupported->skip, keep Fail in current
  status                        Print counts: pass / skip / current / pending / total
  categories                    List pending test categories with counts
"""

import sys
import os
import re
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
LISTS_DIR = SCRIPT_DIR / "lists"
ROMFS_DIR = SCRIPT_DIR / "romfs"
BASELINE_PATH = (
    SCRIPT_DIR.parent.parent.parent
    / "external" / "openglcts" / "data" / "gl_cts" / "data"
    / "mustpass" / "gles" / "aosp_mustpass" / "3.2.6.x" / "gles2-main.txt"
)

PASS_FILE = LISTS_DIR / "pass.txt"
SKIP_FILE = LISTS_DIR / "skip.txt"
CURRENT_FILE = LISTS_DIR / "current.txt"
PENDING_FILE = LISTS_DIR / "pending.txt"
CASELIST_FILE = ROMFS_DIR / "caselist.txt"

# Maximum tests per sub-batch (Switch memory limit: ~500 tests per App instance)
MAX_BATCH_SIZE = 500


# ---------------------------------------------------------------------------
# File I/O helpers
# ---------------------------------------------------------------------------

def read_test_list(path):
    """Read a test list file, ignoring comments and blanks. Returns sorted set."""
    tests = set()
    if not path.exists():
        return tests
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip().replace("\r", "")
            if line and not line.startswith("#"):
                tests.add(line)
    return tests


def write_test_list(path, tests):
    """Write a sorted test list to file."""
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for t in sorted(tests):
            f.write(t + "\n")


# ---------------------------------------------------------------------------
# Trie conversion: flat test names <-> brace/trie notation
# ---------------------------------------------------------------------------

def flat_to_trie(test_names):
    """Convert a list of dotted test names to dEQP brace/trie notation.

    Example input:
      ["dEQP-GLES2.info.vendor", "dEQP-GLES2.info.renderer"]
    Output:
      "{dEQP-GLES2{info{vendor,renderer}}}"
    """
    # Build a nested dict representing the trie
    root = {}
    for name in sorted(test_names):
        parts = re.split(r"[.]", name)
        node = root
        for part in parts:
            if part not in node:
                node[part] = {}
            node = node[part]

    def serialize(node):
        if not node:
            return ""
        items = []
        for key in sorted(node.keys()):
            child = serialize(node[key])
            if child:
                items.append(key + "{" + child + "}")
            else:
                items.append(key)
        return ",".join(items)

    return "{" + serialize(root) + "}"


def trie_to_flat(trie_str):
    """Convert brace/trie notation back to flat dotted test names.

    Input: "{dEQP-GLES2{info{vendor,renderer}}}"
    Output: ["dEQP-GLES2.info.vendor", "dEQP-GLES2.info.renderer"]
    """
    results = []
    stack = []
    current = ""
    i = 0
    s = trie_str.strip()

    while i < len(s):
        c = s[i]
        if c == "{":
            stack.append(current)
            current = ""
        elif c == "}":
            if current:
                path = ".".join(p for p in stack + [current] if p)
                results.append(path)
                current = ""
            stack.pop()
        elif c == ",":
            if current:
                path = ".".join(p for p in stack + [current] if p)
                results.append(path)
                current = ""
        else:
            current += c
        i += 1

    return sorted(results)


# ---------------------------------------------------------------------------
# nxlink output parser
# ---------------------------------------------------------------------------

# dEQP output format:
#   Test case 'dEQP-GLES2.info.vendor'..
#     Pass (some description)
# OR:
#   Test case 'dEQP-GLES2.functional.clipping.point.wide_point_clip'..
#     NotSupported (some description)

RESULT_STATUSES = (
    "Pass", "Fail", "QualityWarning", "CompatibilityWarning",
    "NotSupported", "ResourceError", "InternalError", "Crash", "Timeout", "Waiver",
)

TEST_CASE_PATTERN = re.compile(r"Test case '([^']+)'\.\.")
RESULT_LINE_PATTERN = re.compile(
    r"^\s+(" + "|".join(RESULT_STATUSES) + r")\b", re.MULTILINE,
)


def parse_results(filepath):
    """Parse nxlink output file for test results.

    Handles multi-iteration tests where [dEQP] debug lines appear between
    the test case line and the result line. Uses a line-by-line state machine:
    remember the last test case seen, then assign the next result to it.

    Returns dict: { test_name: result_status }
    """
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    results = {}
    current_test = None

    for line in lines:
        # Check for a new test case
        m = TEST_CASE_PATTERN.search(line)
        if m:
            current_test = m.group(1)
            continue

        # Check for a result line (only if we have a pending test)
        if current_test:
            m = RESULT_LINE_PATTERN.match(line)
            if m:
                results[current_test] = m.group(1)
                current_test = None

    return results


# ---------------------------------------------------------------------------
# Category helpers
# ---------------------------------------------------------------------------

def get_category(test_name, depth=2):
    """Extract category from test name at given depth.

    dEQP-GLES2.functional.color_clear.single_rgb -> functional.color_clear
    dEQP-GLES2.info.vendor -> info
    """
    parts = test_name.split(".")
    # Skip "dEQP-GLES2" prefix
    remaining = parts[1:]
    return ".".join(remaining[:depth]) if len(remaining) >= depth else ".".join(remaining)


def categorize_tests(tests, depth=2):
    """Group tests by category. Returns dict: { category: [test_names] }"""
    cats = defaultdict(list)
    for t in sorted(tests):
        cats[get_category(t, depth)].append(t)
    return cats


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_init():
    """Create pending.txt from baseline minus pass/skip."""
    if not BASELINE_PATH.exists():
        print(f"ERROR: Baseline not found: {BASELINE_PATH}")
        sys.exit(1)

    baseline = read_test_list(BASELINE_PATH)
    passed = read_test_list(PASS_FILE)
    skipped = read_test_list(SKIP_FILE)

    pending = baseline - passed - skipped
    write_test_list(PENDING_FILE, pending)

    print(f"Baseline:  {len(baseline)}")
    print(f"Pass:      {len(passed)}")
    print(f"Skip:      {len(skipped)}")
    print(f"Pending:   {len(pending)}")


def cmd_next_batch(n, categories=None):
    """Move N tests from pending -> current."""
    pending = read_test_list(PENDING_FILE)
    if not pending:
        print("No pending tests remaining!")
        return

    # Filter by category if specified
    if categories:
        cat_list = [c.strip() for c in categories.split(",")]
        candidates = []
        for t in sorted(pending):
            cat = get_category(t)
            # Match if the test category starts with any of the specified categories
            if any(cat.startswith(c) or cat == c for c in cat_list):
                candidates.append(t)
    else:
        candidates = sorted(pending)

    if not candidates:
        print(f"No pending tests matching categories: {categories}")
        return

    # Take first N
    batch = candidates[:n]
    remaining = pending - set(batch)

    # Load existing current and append
    current = read_test_list(CURRENT_FILE)
    current.update(batch)

    write_test_list(CURRENT_FILE, current)
    write_test_list(PENDING_FILE, remaining)

    print(f"Moved {len(batch)} tests to current.txt")
    print(f"Current:   {len(current)}")
    print(f"Pending:   {len(remaining)}")

    # Show category breakdown of batch
    cats = categorize_tests(batch)
    for cat, tests in sorted(cats.items()):
        print(f"  {cat}: {len(tests)}")


def cmd_generate_caselist(mode):
    """Convert current.txt or pass.txt to sub-batch caselist files.

    Splits tests into sub-batches of MAX_BATCH_SIZE to fit in Switch memory.
    Generates: caselist_000.txt, caselist_001.txt, ... + caselist_meta.txt
    """
    if mode == "current":
        source = CURRENT_FILE
    elif mode == "pass":
        source = PASS_FILE
    else:
        print(f"ERROR: Unknown mode '{mode}'. Use 'current' or 'pass'.")
        sys.exit(1)

    tests = read_test_list(source)
    ROMFS_DIR.mkdir(parents=True, exist_ok=True)

    if not tests:
        print(f"WARNING: {source.name} is empty!")
        with open(ROMFS_DIR / "caselist_meta.txt", "w", encoding="utf-8", newline="\n") as f:
            f.write("0\n")
        return

    # Split into sub-batches
    sorted_tests = sorted(tests)
    batches = []
    for i in range(0, len(sorted_tests), MAX_BATCH_SIZE):
        batches.append(sorted_tests[i:i + MAX_BATCH_SIZE])

    # Write meta file with batch count
    with open(ROMFS_DIR / "caselist_meta.txt", "w", encoding="utf-8", newline="\n") as f:
        f.write(f"{len(batches)}\n")

    # Write each sub-batch as trie
    total_verified = 0
    for idx, batch in enumerate(batches):
        trie = flat_to_trie(batch)
        filename = f"caselist_{idx:03d}.txt"
        filepath = ROMFS_DIR / filename
        with open(filepath, "w", encoding="utf-8", newline="\n") as f:
            f.write(trie + "\n")

        # Verify roundtrip
        expanded = trie_to_flat(trie)
        if set(expanded) != set(batch):
            print(f"  WARNING: {filename} roundtrip mismatch!")
        else:
            total_verified += len(batch)

        print(f"  {filename}: {len(batch)} tests")

    # Clean up old files from previous larger runs
    for old_file in ROMFS_DIR.glob("caselist_*.txt"):
        name = old_file.stem
        if name == "caselist_meta":
            continue
        idx_str = name.replace("caselist_", "")
        if idx_str.isdigit() and int(idx_str) >= len(batches):
            old_file.unlink()

    # Also remove old single caselist.txt if present
    if CASELIST_FILE.exists():
        CASELIST_FILE.unlink()

    print(f"Generated {len(batches)} sub-batches from {source.name} "
          f"({len(tests)} tests, {total_verified} verified)")


def cmd_parse(filepath):
    """Parse nxlink output for test results and print summary."""
    results = parse_results(filepath)
    if not results:
        print(f"No test results found in {filepath}")
        return

    # Count by status
    counts = defaultdict(int)
    by_status = defaultdict(list)
    for name, status in sorted(results.items()):
        counts[status] += 1
        by_status[status].append(name)

    print(f"Total: {len(results)} tests")
    for status in ["Pass", "Fail", "NotSupported", "QualityWarning",
                    "CompatibilityWarning", "Crash", "Timeout",
                    "ResourceError", "InternalError", "Waiver"]:
        if counts[status]:
            print(f"  {status}: {counts[status]}")

    # Print failures in detail
    for status in ["Fail", "Crash", "Timeout", "ResourceError", "InternalError"]:
        if by_status[status]:
            print(f"\n--- {status} ---")
            for name in by_status[status]:
                print(f"  {name}")


def cmd_promote(filepath):
    """Parse results and move Pass->pass, NotSupported->skip, keep Fail in current."""
    results = parse_results(filepath)
    if not results:
        print(f"No test results found in {filepath}")
        return

    passed = read_test_list(PASS_FILE)
    skipped = read_test_list(SKIP_FILE)
    current = read_test_list(CURRENT_FILE)

    promoted_pass = 0
    promoted_skip = 0
    kept_fail = 0
    quality_pass = 0

    for name, status in results.items():
        if status in ("Pass", "QualityWarning", "CompatibilityWarning", "Waiver"):
            passed.add(name)
            current.discard(name)
            promoted_pass += 1
            if status != "Pass":
                quality_pass += 1
        elif status == "NotSupported":
            skipped.add(name)
            current.discard(name)
            promoted_skip += 1
        else:
            # Fail, Crash, Timeout, etc. — keep in current for investigation
            kept_fail += 1

    write_test_list(PASS_FILE, passed)
    write_test_list(SKIP_FILE, skipped)
    write_test_list(CURRENT_FILE, current)

    print(f"Promoted:  {promoted_pass} -> pass.txt" +
          (f" ({quality_pass} QualityWarning/CompatibilityWarning)" if quality_pass else ""))
    print(f"Skipped:   {promoted_skip} -> skip.txt")
    print(f"Remaining: {kept_fail} in current.txt (need investigation)")
    print(f"Totals:    pass={len(passed)} skip={len(skipped)} current={len(current)}")


def cmd_status():
    """Print counts of all list files."""
    passed = read_test_list(PASS_FILE)
    skipped = read_test_list(SKIP_FILE)
    current = read_test_list(CURRENT_FILE)
    pending = read_test_list(PENDING_FILE)

    # Check baseline
    if BASELINE_PATH.exists():
        baseline = read_test_list(BASELINE_PATH)
        total = len(baseline)
    else:
        total = len(passed) + len(skipped) + len(current) + len(pending)

    tested = len(passed) + len(skipped)
    pct = (tested / total * 100) if total else 0

    print(f"Pass:      {len(passed)}")
    print(f"Skip:      {len(skipped)}")
    print(f"Current:   {len(current)}")
    print(f"Pending:   {len(pending)}")
    print(f"Baseline:  {total}")
    print(f"Progress:  {tested}/{total} ({pct:.1f}%)")

    if current:
        cats = categorize_tests(current)
        print(f"\nCurrent batch categories:")
        for cat, tests in sorted(cats.items()):
            print(f"  {cat}: {len(tests)}")


def cmd_categories():
    """List pending test categories with counts."""
    pending = read_test_list(PENDING_FILE)
    if not pending:
        print("No pending tests.")
        return

    cats = categorize_tests(pending)
    print(f"Pending categories ({len(pending)} tests total):")
    for cat, tests in sorted(cats.items(), key=lambda x: -len(x[1])):
        print(f"  {cat:50s} {len(tests):6d}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "init":
        cmd_init()
    elif cmd == "next-batch":
        if len(sys.argv) < 3:
            print("Usage: manage_tests.py next-batch N [category,...]")
            sys.exit(1)
        n = int(sys.argv[2])
        categories = sys.argv[3] if len(sys.argv) > 3 else None
        cmd_next_batch(n, categories)
    elif cmd == "generate-caselist":
        if len(sys.argv) < 3:
            print("Usage: manage_tests.py generate-caselist current|pass")
            sys.exit(1)
        cmd_generate_caselist(sys.argv[2])
    elif cmd == "parse":
        if len(sys.argv) < 3:
            print("Usage: manage_tests.py parse <nxlink_output.txt>")
            sys.exit(1)
        cmd_parse(sys.argv[2])
    elif cmd == "promote":
        if len(sys.argv) < 3:
            print("Usage: manage_tests.py promote <nxlink_output.txt>")
            sys.exit(1)
        cmd_promote(sys.argv[2])
    elif cmd == "status":
        cmd_status()
    elif cmd == "categories":
        cmd_categories()
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
