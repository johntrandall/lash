#!/usr/bin/env python3
"""lash — manifest-driven symlink installer.

Reads a per-project lash.json manifest and executes operations forward
(install) or backward (uninstall), keeping them perfectly in sync.

Usage:
    lash install   [path/to/lash.json]
    lash uninstall [path/to/lash.json]
    lash status    [path/to/lash.json]
    lash verify    [path/to/lash.json]
    lash list      [search-dir]

If no manifest path is given, looks for lash.json in the current directory.
`lash list` scans ~/dev/*/lash.json (or a custom dir) for all managed projects.
"""

import json
import os
import shutil
import stat
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def expand(p: str, base: Path, follow_symlinks: bool = False) -> Path:
    """Expand ~ and resolve relative paths against the manifest's directory."""
    p = os.path.expanduser(p)
    path = Path(p)
    if not path.is_absolute():
        path = base / path
    if follow_symlinks:
        return path.resolve()
    # Make absolute without following symlinks
    return Path(os.path.normpath(path))


def colour(code: str, text: str) -> str:
    if sys.stdout.isatty():
        return f"\033[{code}m{text}\033[0m"
    return text

green  = lambda t: colour("32", t)
yellow = lambda t: colour("33", t)
red    = lambda t: colour("31", t)
dim    = lambda t: colour("2", t)
bold   = lambda t: colour("1", t)

# ---------------------------------------------------------------------------
# JSON deep-path helpers
# ---------------------------------------------------------------------------

def json_get(data: dict, path: str):
    """Walk a dot-separated path into a dict, returning (parent, key, value)."""
    keys = path.strip(".").split(".")
    node = data
    for k in keys[:-1]:
        if k not in node or not isinstance(node[k], dict):
            return None, keys[-1], None
        node = node[k]
    return node, keys[-1], node.get(keys[-1])


def json_ensure_path(data: dict, path: str):
    """Ensure all intermediate dicts exist, return (parent_dict, final_key)."""
    keys = path.strip(".").split(".")
    node = data
    for k in keys[:-1]:
        node = node.setdefault(k, {})
    return node, keys[-1]

# ---------------------------------------------------------------------------
# Operation handlers
# ---------------------------------------------------------------------------

def do_symlink_install(op: dict, base: Path) -> bool:
    src = expand(op["src"], base, follow_symlinks=True)
    dest = expand(op["dest"], base)

    if not src.exists():
        print(f"  {red('✗')} Source does not exist: {src}")
        return False

    dest.parent.mkdir(parents=True, exist_ok=True)

    if dest.is_symlink():
        if dest.resolve() == src:
            print(f"  {green('✓')} Already linked: {dest}")
            return True
        dest.unlink()
    elif dest.exists():
        backup = dest.with_suffix(dest.suffix + ".lash-backup")
        shutil.move(str(dest), str(backup))
        print(f"  {yellow('⚠')} Backed up existing file: {backup}")

    dest.symlink_to(src)
    print(f"  {green('✓')} Linked: {dest} → {src}")

    if "chmod" in op:
        mode = op["chmod"]
        if mode == "+x":
            src.chmod(src.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return True


def do_symlink_uninstall(op: dict, base: Path) -> bool:
    dest = expand(op["dest"], base)

    if dest.is_symlink():
        dest.unlink()
        print(f"  {green('✓')} Removed symlink: {dest}")
        # Restore backup if present
        backup = dest.with_suffix(dest.suffix + ".lash-backup")
        if backup.exists():
            shutil.move(str(backup), str(dest))
            print(f"  {yellow('↩')} Restored backup: {backup.name}")
        return True
    elif dest.exists():
        print(f"  {yellow('⚠')} {dest} exists but is not a symlink — skipping")
        return False
    else:
        print(f"  {dim('-')} {dest} not found (already removed)")
        return True


def do_symlink_status(op: dict, base: Path) -> bool:
    src = expand(op["src"], base, follow_symlinks=True)
    dest = expand(op["dest"], base)

    if dest.is_symlink() and dest.resolve() == src:
        print(f"  {green('✓')} {dest}")
        return True
    elif dest.is_symlink():
        print(f"  {yellow('⚠')} {dest} → {dest.resolve()} (expected {src})")
        return False
    elif dest.exists():
        print(f"  {yellow('⚠')} {dest} exists but is not a symlink")
        return False
    else:
        print(f"  {red('✗')} {dest} missing")
        return False


def do_json_merge_install(op: dict, base: Path) -> bool:
    filepath = expand(op["file"], base)
    if not filepath.exists():
        print(f"  {red('✗')} JSON file not found: {filepath}")
        return False

    data = json.loads(filepath.read_text())
    action = op.get("action", "set")
    path = op["path"]

    if action == "append_unique":
        parent, key = json_ensure_path(data, path)
        arr = parent.setdefault(key, [])
        if not isinstance(arr, list):
            print(f"  {red('✗')} {path} is not an array in {filepath}")
            return False
        value = op["value"]
        # Deep equality: skip only if the exact same entry already exists
        if any(item == value for item in arr):
            print(f"  {green('✓')} JSON entry already present at {path}")
            return True
        arr.append(value)
    elif action == "set":
        parent, key = json_ensure_path(data, path)
        parent[key] = op["value"]
    else:
        print(f"  {red('✗')} Unknown json_merge action: {action}")
        return False

    filepath.write_text(json.dumps(data, indent=2) + "\n")
    print(f"  {green('✓')} JSON patched: {filepath} at {path}")
    return True


def do_json_merge_uninstall(op: dict, base: Path) -> bool:
    filepath = expand(op["file"], base)
    if not filepath.exists():
        print(f"  {dim('-')} JSON file not found: {filepath}")
        return True

    data = json.loads(filepath.read_text())
    action = op.get("action", "set")
    path = op["path"]

    if action == "append_unique":
        parent, key, arr = json_get(data, path)
        if arr is None or not isinstance(arr, list):
            print(f"  {dim('-')} {path} not found or not an array")
            return True
        value = op["value"]
        original_len = len(arr)
        arr[:] = [item for item in arr if item != value]
        if len(arr) < original_len:
            parent[key] = arr
            # Clean up empty arrays
            if len(arr) == 0:
                del parent[key]
            filepath.write_text(json.dumps(data, indent=2) + "\n")
            print(f"  {green('✓')} JSON entry removed from {path}")
            return True
        else:
            print(f"  {dim('-')} No matching entry at {path}")
            return True
    elif action == "set":
        parent, key, val = json_get(data, path)
        if parent is not None and key in parent:
            del parent[key]
            filepath.write_text(json.dumps(data, indent=2) + "\n")
            print(f"  {green('✓')} JSON key removed: {path}")
            return True
        else:
            print(f"  {dim('-')} {path} not found (already removed)")
            return True
    else:
        return False


def do_json_merge_status(op: dict, base: Path) -> bool:
    filepath = expand(op["file"], base)
    if not filepath.exists():
        print(f"  {red('✗')} JSON file missing: {filepath}")
        return False

    data = json.loads(filepath.read_text())
    action = op.get("action", "set")
    path = op["path"]

    if action == "append_unique":
        _, _, arr = json_get(data, path)
        if arr is None or not isinstance(arr, list):
            print(f"  {red('✗')} {filepath.name}: {path} missing")
            return False
        value = op["value"]
        if any(item == value for item in arr):
            print(f"  {green('✓')} {filepath.name}: {path} entry present")
            return True
        print(f"  {red('✗')} {filepath.name}: {path} entry missing")
        return False
    elif action == "set":
        _, _, val = json_get(data, path)
        if val == op["value"]:
            print(f"  {green('✓')} {filepath.name}: {path}")
            return True
        elif val is not None:
            print(f"  {yellow('⚠')} {filepath.name}: {path} has different value")
            return False
        else:
            print(f"  {red('✗')} {filepath.name}: {path} missing")
            return False
    return False


def do_shell_install(op: dict, base: Path) -> bool:
    cmd = op.get("install")
    if not cmd:
        return True
    print(f"  {dim('$')} {cmd}")
    ret = os.system(f"cd {base} && {cmd}")
    if ret == 0:
        print(f"  {green('✓')} Shell command succeeded")
        return True
    else:
        print(f"  {red('✗')} Shell command failed (exit {ret})")
        return False


def do_shell_uninstall(op: dict, base: Path) -> bool:
    cmd = op.get("uninstall")
    if not cmd:
        return True
    print(f"  {dim('$')} {cmd}")
    ret = os.system(f"cd {base} && {cmd}")
    if ret == 0:
        print(f"  {green('✓')} Shell command succeeded")
        return True
    else:
        print(f"  {red('✗')} Shell command failed (exit {ret})")
        return False


def do_shell_status(op: dict, base: Path) -> bool:
    cmd = op.get("status")
    if not cmd:
        print(f"  {dim('-')} Shell op (no status check)")
        return True
    ret = os.system(f"cd {base} && {cmd}")
    return ret == 0


# ---------------------------------------------------------------------------
# Verify handlers — stricter than status, checks executable bits etc.
# ---------------------------------------------------------------------------

def do_symlink_verify(op: dict, base: Path) -> bool:
    src = expand(op["src"], base, follow_symlinks=True)
    dest = expand(op["dest"], base)
    ok = True

    if not dest.is_symlink():
        if dest.exists():
            print(f"  {red('FAIL')} {dest} exists but is not a symlink")
        else:
            print(f"  {red('FAIL')} {dest} missing")
        return False

    if dest.resolve() != src:
        print(f"  {red('FAIL')} {dest} → {dest.resolve()} (expected {src})")
        return False

    if not src.exists():
        print(f"  {red('FAIL')} symlink target does not exist: {src}")
        return False

    # Check executable bit if chmod was specified
    if op.get("chmod") == "+x":
        if not os.access(src, os.X_OK):
            print(f"  {red('FAIL')} {src} is not executable")
            return False
        print(f"  {green('PASS')} {dest} → {src} (executable)")
    else:
        print(f"  {green('PASS')} {dest} → {src}")
    return True


def do_json_merge_verify(op: dict, base: Path) -> bool:
    filepath = expand(op["file"], base)
    if not filepath.exists():
        print(f"  {red('FAIL')} JSON file missing: {filepath}")
        return False

    data = json.loads(filepath.read_text())
    action = op.get("action", "set")
    path = op["path"]

    if action == "append_unique":
        _, _, arr = json_get(data, path)
        if arr is None or not isinstance(arr, list):
            print(f"  {red('FAIL')} {filepath.name}: {path} missing or not an array")
            return False
        value = op["value"]
        if any(item == value for item in arr):
            print(f"  {green('PASS')} {filepath.name}: {path} entry present")
            return True
        print(f"  {red('FAIL')} {filepath.name}: {path} entry not found")
        return False
    elif action == "set":
        _, _, val = json_get(data, path)
        if val == op["value"]:
            print(f"  {green('PASS')} {filepath.name}: {path}")
            return True
        elif val is not None:
            print(f"  {red('FAIL')} {filepath.name}: {path} has different value")
            return False
        else:
            print(f"  {red('FAIL')} {filepath.name}: {path} missing")
            return False
    else:
        print(f"  {red('FAIL')} Unknown json_merge action: {action}")
        return False


def do_shell_verify(op: dict, base: Path) -> bool:
    cmd = op.get("status")
    if not cmd:
        print(f"  {dim('SKIP')} shell op (no status check)")
        return True
    ret = os.system(f"cd {base} && {cmd}")
    if ret == 0:
        print(f"  {green('PASS')} shell: {cmd}")
        return True
    else:
        print(f"  {red('FAIL')} shell: {cmd}")
        return False


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Template operation
#
# Renders a source file with `{{KEY}}` placeholders into a destination file,
# substituting values from the `vars` map. Useful when launchd plists or
# similar files need absolute paths that can't be expressed via $HOME or ~
# (launchd does not interpolate those in plist string values).
#
# Manifest shape:
#   {
#     "type": "template",
#     "src":  "./path/to/template.plist.tmpl",
#     "dest": "~/Library/LaunchAgents/foo.plist",
#     "vars": {
#       "HOME": "@env:HOME",          # read from environment
#       "USER": "@env:USER:fallback", # env with default if unset
#       "REGION": "us-east-1"         # literal value
#     }
#   }
#
# Substitution is a literal string replace of `{{KEY}}` for each var. No
# expressions, no nested braces. Vars are resolved at install/uninstall/
# status time, so a re-run picks up environment changes.
# ---------------------------------------------------------------------------

def _resolve_template_vars(vars_spec: dict) -> dict:
    """Resolve a `vars` map to concrete strings.

    Strings starting with `@env:` are read from os.environ. The form
    `@env:NAME:default` uses `default` if NAME is unset. Plain strings
    are passed through.

    Raises ValueError for an unset env var with no default.
    """
    resolved = {}
    for key, raw in vars_spec.items():
        if not isinstance(raw, str):
            resolved[key] = str(raw)
            continue
        if raw.startswith("@env:"):
            spec = raw[len("@env:"):]
            if ":" in spec:
                name, default = spec.split(":", 1)
                resolved[key] = os.environ.get(name, default)
            else:
                value = os.environ.get(spec)
                if value is None:
                    raise ValueError(
                        f"template var '{key}' references unset env var '{spec}' "
                        f"(use '@env:{spec}:fallback' to provide a default)"
                    )
                resolved[key] = value
        else:
            resolved[key] = raw
    return resolved


def _render_template(src_text: str, vars_resolved: dict) -> str:
    out = src_text
    for key, value in vars_resolved.items():
        out = out.replace("{{" + key + "}}", value)
    return out


def do_template_install(op: dict, base: Path) -> bool:
    src = expand(op["src"], base, follow_symlinks=True)
    dest = expand(op["dest"], base)

    if not src.exists():
        print(f"  {red('✗')} Template source does not exist: {src}")
        return False

    try:
        vars_resolved = _resolve_template_vars(op.get("vars", {}))
    except ValueError as e:
        print(f"  {red('✗')} {e}")
        return False

    rendered = _render_template(src.read_text(), vars_resolved)

    dest.parent.mkdir(parents=True, exist_ok=True)

    if dest.exists():
        if dest.is_symlink():
            dest.unlink()
        else:
            existing = dest.read_text()
            if existing == rendered:
                print(f"  {green('✓')} Already rendered: {dest}")
                return True
            backup = dest.with_suffix(dest.suffix + ".lash-backup")
            shutil.move(str(dest), str(backup))
            print(f"  {yellow('⚠')} Backed up existing file: {backup}")

    dest.write_text(rendered)
    print(f"  {green('✓')} Rendered: {dest} ← {src}")
    return True


def do_template_uninstall(op: dict, base: Path) -> bool:
    dest = expand(op["dest"], base)

    if dest.exists():
        if dest.is_symlink():
            print(f"  {yellow('⚠')} {dest} is a symlink, not a rendered template — skipping")
            return False
        dest.unlink()
        print(f"  {green('✓')} Removed: {dest}")
        backup = dest.with_suffix(dest.suffix + ".lash-backup")
        if backup.exists():
            shutil.move(str(backup), str(dest))
            print(f"  {yellow('↩')} Restored backup: {backup.name}")
        return True
    print(f"  {dim('-')} {dest} not found (already removed)")
    return True


def do_template_status(op: dict, base: Path) -> bool:
    dest = expand(op["dest"], base)
    if dest.exists() and not dest.is_symlink():
        print(f"  {green('✓')} {dest}")
        return True
    print(f"  {red('✗')} {dest} missing")
    return False


def do_template_verify(op: dict, base: Path) -> bool:
    src = expand(op["src"], base, follow_symlinks=True)
    dest = expand(op["dest"], base)

    if not dest.exists():
        print(f"  {red('FAIL')} {dest} missing")
        return False
    if dest.is_symlink():
        print(f"  {red('FAIL')} {dest} is a symlink (expected rendered file)")
        return False
    if not src.exists():
        print(f"  {red('FAIL')} template source missing: {src}")
        return False

    try:
        vars_resolved = _resolve_template_vars(op.get("vars", {}))
    except ValueError as e:
        print(f"  {red('FAIL')} {e}")
        return False

    expected = _render_template(src.read_text(), vars_resolved)
    actual = dest.read_text()
    if actual != expected:
        print(f"  {red('FAIL')} {dest} content does not match freshly-rendered template")
        return False

    print(f"  {green('PASS')} {dest} ← {src}")
    return True


# ---------------------------------------------------------------------------
# Dispatch tables
# ---------------------------------------------------------------------------

INSTALL_HANDLERS = {
    "symlink":    do_symlink_install,
    "json_merge": do_json_merge_install,
    "shell":      do_shell_install,
    "template":   do_template_install,
}

UNINSTALL_HANDLERS = {
    "symlink":    do_symlink_uninstall,
    "json_merge": do_json_merge_uninstall,
    "shell":      do_shell_uninstall,
    "template":   do_template_uninstall,
}

STATUS_HANDLERS = {
    "symlink":    do_symlink_status,
    "json_merge": do_json_merge_status,
    "shell":      do_shell_status,
    "template":   do_template_status,
}

VERIFY_HANDLERS = {
    "symlink":    do_symlink_verify,
    "json_merge": do_json_merge_verify,
    "shell":      do_shell_verify,
    "template":   do_template_verify,
}

# ---------------------------------------------------------------------------
# Main commands
# ---------------------------------------------------------------------------

def load_manifest(path: str | None) -> tuple[dict, Path]:
    if path is None:
        path = "lash.json"
    p = Path(path)
    if p.is_dir():
        p = p / "lash.json"
    if not p.exists():
        print(f"{red('Error:')} Manifest not found: {p}", file=sys.stderr)
        sys.exit(1)
    manifest = json.loads(p.read_text())
    return manifest, p.parent.resolve()


def cmd_install(manifest: dict, base: Path) -> int:
    name = manifest.get("name", "unnamed")
    ops = manifest.get("operations", [])
    print(f"{bold('Installing')} {name} ({len(ops)} operations)")
    print()
    failures = 0
    for op in ops:
        handler = INSTALL_HANDLERS.get(op["type"])
        if handler is None:
            print(f"  {red('✗')} Unknown operation type: {op['type']}")
            failures += 1
            continue
        if not handler(op, base):
            failures += 1
    print()
    if failures:
        print(f"{yellow('Done with')} {failures} {'failure' if failures == 1 else 'failures'}.")
        return 1
    print(f"{green('✓')} {name} installed successfully.")
    return 0


def cmd_uninstall(manifest: dict, base: Path) -> int:
    name = manifest.get("name", "unnamed")
    ops = manifest.get("operations", [])
    print(f"{bold('Uninstalling')} {name} ({len(ops)} operations)")
    print()
    failures = 0
    for op in reversed(ops):
        handler = UNINSTALL_HANDLERS.get(op["type"])
        if handler is None:
            print(f"  {red('✗')} Unknown operation type: {op['type']}")
            failures += 1
            continue
        if not handler(op, base):
            failures += 1
    print()
    if failures:
        print(f"{yellow('Done with')} {failures} {'failure' if failures == 1 else 'failures'}.")
        return 1
    print(f"{green('✓')} {name} uninstalled successfully.")
    return 0


def cmd_status(manifest: dict, base: Path) -> int:
    name = manifest.get("name", "unnamed")
    ops = manifest.get("operations", [])
    print(f"{bold('Status:')} {name}")
    print()
    ok = 0
    total = len(ops)
    for op in ops:
        handler = STATUS_HANDLERS.get(op["type"])
        if handler is None:
            print(f"  {red('✗')} Unknown operation type: {op['type']}")
            continue
        if handler(op, base):
            ok += 1
    print()
    if ok == total:
        print(f"{green('✓')} Fully installed ({ok}/{total})")
        return 0
    elif ok == 0:
        print(f"{dim('○')} Not installed (0/{total})")
        return 1
    else:
        print(f"{yellow('◐')} Partially installed ({ok}/{total})")
        return 1


def cmd_verify(manifest: dict, base: Path) -> int:
    name = manifest.get("name", "unnamed")
    ops = manifest.get("operations", [])
    print(f"{bold('Verifying')} {name} ({len(ops)} operations)")
    print()
    passed = 0
    failed = 0
    for op in ops:
        handler = VERIFY_HANDLERS.get(op["type"])
        if handler is None:
            print(f"  {red('FAIL')} Unknown operation type: {op['type']}")
            failed += 1
            continue
        if handler(op, base):
            passed += 1
        else:
            failed += 1
    print()
    total = passed + failed
    if failed == 0:
        print(f"{green('✓')} All {total} operations verified.")
        return 0
    else:
        print(f"{red('✗')} {failed} of {total} operations failed verification.")
        return 1


def cmd_list(args: list[str]) -> int:
    """Discover lash.json manifests and show a summary table."""
    search_dir = Path(os.path.expanduser(args[0])) if args else Path.home() / "dev"
    if not search_dir.is_dir():
        print(f"{red('Error:')} Directory not found: {search_dir}", file=sys.stderr)
        return 1

    manifests = sorted(search_dir.glob("*/lash.json"))
    if not manifests:
        print(f"No lash.json manifests found in {search_dir}/*/")
        return 0

    # Collect data
    rows = []
    for mpath in manifests:
        try:
            manifest = json.loads(mpath.read_text())
        except (json.JSONDecodeError, OSError):
            rows.append((mpath.parent.name, "?", "?", red("invalid manifest")))
            continue

        base = mpath.parent.resolve()
        name = manifest.get("name", mpath.parent.name)
        ops = manifest.get("operations", [])
        total = len(ops)

        # Silent status check
        ok = 0
        for op in ops:
            handler = STATUS_HANDLERS.get(op.get("type"))
            if handler and _silent_check(handler, op, base):
                ok += 1

        # Summarise operations
        counts = {}
        for op in ops:
            t = op.get("type", "?")
            counts[t] = counts.get(t, 0) + 1
        op_summary = ", ".join(f"{v} {k}" for k, v in counts.items())

        if ok == total:
            status = green(f"installed ({ok}/{total})")
        elif ok == 0:
            status = dim(f"not installed (0/{total})")
        else:
            status = yellow(f"partial ({ok}/{total})")

        rows.append((name, mpath.parent.name, op_summary, status))

    # Calculate column widths (strip ANSI for width calculation)
    import re
    ansi_re = re.compile(r'\033\[[0-9;]*m')
    def visible_len(s): return len(ansi_re.sub('', s))

    headers = ("Name", "Directory", "Operations", "Status")
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], visible_len(cell))

    def fmt_row(cells):
        parts = []
        for i, cell in enumerate(cells):
            pad = widths[i] - visible_len(cell)
            parts.append(cell + " " * pad)
        return "  ".join(parts)

    print(fmt_row(headers))
    print("  ".join("─" * w for w in widths))
    for row in rows:
        print(fmt_row(row))

    return 0


def _silent_check(handler, op: dict, base: Path) -> bool:
    """Run a status handler with stdout suppressed."""
    import io
    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        return handler(op, base)
    finally:
        sys.stdout = old_stdout


COMMANDS = {
    "install":   cmd_install,
    "uninstall": cmd_uninstall,
    "status":    cmd_status,
    "verify":    cmd_verify,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print(__doc__.strip())
        sys.exit(0)

    command = sys.argv[1]

    # `list` is special — doesn't need a manifest
    if command == "list":
        sys.exit(cmd_list(sys.argv[2:]))

    if command not in COMMANDS:
        print(f"{red('Error:')} Unknown command: {command}", file=sys.stderr)
        print(f"Commands: {', '.join(list(COMMANDS) + ['list'])}", file=sys.stderr)
        sys.exit(2)

    manifest_path = sys.argv[2] if len(sys.argv) > 2 else None
    manifest, base = load_manifest(manifest_path)
    sys.exit(COMMANDS[command](manifest, base))


if __name__ == "__main__":
    main()
