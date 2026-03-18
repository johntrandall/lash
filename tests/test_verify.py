"""Tests for lash verify command (M8)."""

import json
import os
import stat
import sys
import tempfile
from pathlib import Path

import importlib.util
import importlib.machinery

lash_path = Path(__file__).parent.parent / "lash"
loader = importlib.machinery.SourceFileLoader("lash_mod", str(lash_path))
spec = importlib.util.spec_from_loader("lash_mod", loader)
lash = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lash)


def _make_json_file(data: dict) -> Path:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(data, f)
    f.close()
    return Path(f.name)


def test_verify_symlink_pass():
    """Verify passes for correct symlink."""
    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        src = base / "tool.sh"
        src.write_text("#!/bin/sh\necho hi\n")
        src.chmod(src.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        dest = base / "link"
        dest.symlink_to(src.resolve())
        op = {"type": "symlink", "src": str(src), "dest": str(dest), "chmod": "+x"}
        assert lash.do_symlink_verify(op, base) is True


def test_verify_symlink_missing():
    """Verify fails for missing symlink."""
    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        src = base / "tool.sh"
        src.write_text("#!/bin/sh\n")
        op = {"type": "symlink", "src": str(src), "dest": str(base / "missing")}
        assert lash.do_symlink_verify(op, base) is False


def test_verify_symlink_not_executable():
    """Verify fails when chmod +x required but target not executable."""
    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        src = base / "tool.sh"
        src.write_text("#!/bin/sh\n")
        src.chmod(0o644)  # Not executable
        dest = base / "link"
        dest.symlink_to(src.resolve())
        op = {"type": "symlink", "src": str(src), "dest": str(dest), "chmod": "+x"}
        assert lash.do_symlink_verify(op, base) is False


def test_verify_json_merge_present():
    """Verify passes when JSON entry is present."""
    entry = {"matcher": "Bash", "hooks": [{"type": "command", "command": "test.sh"}]}
    filepath = _make_json_file({"hooks": {"PreToolUse": [entry]}})
    try:
        op = {
            "type": "json_merge",
            "file": str(filepath),
            "path": "hooks.PreToolUse",
            "action": "append_unique",
            "match_key": "matcher",
            "value": entry,
        }
        assert lash.do_json_merge_verify(op, filepath.parent) is True
    finally:
        filepath.unlink()


def test_verify_json_merge_missing():
    """Verify fails when JSON entry is absent."""
    filepath = _make_json_file({"hooks": {"PreToolUse": []}})
    try:
        op = {
            "type": "json_merge",
            "file": str(filepath),
            "path": "hooks.PreToolUse",
            "action": "append_unique",
            "match_key": "matcher",
            "value": {"matcher": "Bash", "hooks": []},
        }
        assert lash.do_json_merge_verify(op, filepath.parent) is False
    finally:
        filepath.unlink()


def test_cmd_verify_exit_codes():
    """cmd_verify returns 0 on all pass, 1 on any fail."""
    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        src = base / "tool"
        src.write_text("#!/bin/sh\n")
        src.chmod(0o755)
        dest = base / "link"
        dest.symlink_to(src.resolve())

        manifest_pass = {
            "name": "test",
            "operations": [
                {"type": "symlink", "src": str(src), "dest": str(dest), "chmod": "+x"}
            ],
        }
        assert lash.cmd_verify(manifest_pass, base) == 0

        manifest_fail = {
            "name": "test",
            "operations": [
                {"type": "symlink", "src": str(src), "dest": str(base / "nope")}
            ],
        }
        assert lash.cmd_verify(manifest_fail, base) == 1


if __name__ == "__main__":
    tests = [
        test_verify_symlink_pass,
        test_verify_symlink_missing,
        test_verify_symlink_not_executable,
        test_verify_json_merge_present,
        test_verify_json_merge_missing,
        test_cmd_verify_exit_codes,
    ]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {t.__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed")
    sys.exit(0 if passed == len(tests) else 1)
