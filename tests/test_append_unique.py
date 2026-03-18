"""Tests for append_unique deep equality comparison (M6 fix)."""

import json
import sys
import tempfile
from pathlib import Path

# Add parent dir so we can import lash functions
sys.path.insert(0, str(Path(__file__).parent.parent))

import importlib.util
import importlib.machinery
lash_path = Path(__file__).parent.parent / "lash"
loader = importlib.machinery.SourceFileLoader("lash_mod", str(lash_path))
spec = importlib.util.spec_from_loader("lash_mod", loader)
lash = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lash)


def _make_json_file(data: dict) -> Path:
    """Create a temp JSON file with the given data."""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(data, f)
    f.close()
    return Path(f.name)


def test_same_match_key_different_hooks_both_added():
    """Two entries with same matcher but different hook commands → both should be added."""
    existing = {
        "hooks": {
            "Stop": [
                {"matcher": "", "hooks": [{"type": "command", "command": "engram-hook.sh"}]}
            ]
        }
    }
    filepath = _make_json_file(existing)
    try:
        op = {
            "type": "json_merge",
            "file": str(filepath),
            "path": "hooks.Stop",
            "action": "append_unique",
            "match_key": "matcher",
            "value": {"matcher": "", "hooks": [{"type": "command", "command": "iterm-color-hook.sh"}]},
        }
        result = lash.do_json_merge_install(op, filepath.parent)
        assert result is True

        data = json.loads(filepath.read_text())
        stop_hooks = data["hooks"]["Stop"]
        assert len(stop_hooks) == 2, f"Expected 2 entries, got {len(stop_hooks)}"
        commands = [e["hooks"][0]["command"] for e in stop_hooks]
        assert "engram-hook.sh" in commands
        assert "iterm-color-hook.sh" in commands
    finally:
        filepath.unlink()


def test_exact_duplicate_skipped():
    """Exact duplicate entry → should be skipped (idempotent)."""
    entry = {"matcher": "SendMessage", "hooks": [{"type": "command", "command": "my-hook.sh"}]}
    existing = {"hooks": {"PreToolUse": [entry.copy()]}}
    filepath = _make_json_file(existing)
    try:
        op = {
            "type": "json_merge",
            "file": str(filepath),
            "path": "hooks.PreToolUse",
            "action": "append_unique",
            "match_key": "matcher",
            "value": entry.copy(),
        }
        result = lash.do_json_merge_install(op, filepath.parent)
        assert result is True

        data = json.loads(filepath.read_text())
        assert len(data["hooks"]["PreToolUse"]) == 1, "Duplicate should not be added"
    finally:
        filepath.unlink()


def test_no_existing_match_appended():
    """Entry with no existing matches → should be appended."""
    existing = {"hooks": {"PreToolUse": []}}
    filepath = _make_json_file(existing)
    try:
        new_entry = {"matcher": "Bash", "hooks": [{"type": "command", "command": "bash-hook.sh"}]}
        op = {
            "type": "json_merge",
            "file": str(filepath),
            "path": "hooks.PreToolUse",
            "action": "append_unique",
            "match_key": "matcher",
            "value": new_entry,
        }
        result = lash.do_json_merge_install(op, filepath.parent)
        assert result is True

        data = json.loads(filepath.read_text())
        assert len(data["hooks"]["PreToolUse"]) == 1
        assert data["hooks"]["PreToolUse"][0] == new_entry
    finally:
        filepath.unlink()


def test_uninstall_removes_exact_match_only():
    """Uninstall removes only the exact matching entry, not entries sharing match_key."""
    entry_a = {"matcher": "", "hooks": [{"type": "command", "command": "engram-hook.sh"}]}
    entry_b = {"matcher": "", "hooks": [{"type": "command", "command": "iterm-color-hook.sh"}]}
    existing = {"hooks": {"Stop": [entry_a, entry_b]}}
    filepath = _make_json_file(existing)
    try:
        op = {
            "type": "json_merge",
            "file": str(filepath),
            "path": "hooks.Stop",
            "action": "append_unique",
            "match_key": "matcher",
            "value": entry_b,
        }
        result = lash.do_json_merge_uninstall(op, filepath.parent)
        assert result is True

        data = json.loads(filepath.read_text())
        assert len(data["hooks"]["Stop"]) == 1
        assert data["hooks"]["Stop"][0] == entry_a
    finally:
        filepath.unlink()


def test_status_checks_deep_equality():
    """Status should check deep equality, not just match_key."""
    entry_a = {"matcher": "", "hooks": [{"type": "command", "command": "engram-hook.sh"}]}
    existing = {"hooks": {"Stop": [entry_a]}}
    filepath = _make_json_file(existing)
    try:
        # Status for entry_a → should pass
        op_a = {
            "type": "json_merge",
            "file": str(filepath),
            "path": "hooks.Stop",
            "action": "append_unique",
            "match_key": "matcher",
            "value": entry_a,
        }
        assert lash.do_json_merge_status(op_a, filepath.parent) is True

        # Status for a different entry with same matcher → should fail
        entry_b = {"matcher": "", "hooks": [{"type": "command", "command": "iterm-color-hook.sh"}]}
        op_b = {
            "type": "json_merge",
            "file": str(filepath),
            "path": "hooks.Stop",
            "action": "append_unique",
            "match_key": "matcher",
            "value": entry_b,
        }
        assert lash.do_json_merge_status(op_b, filepath.parent) is False
    finally:
        filepath.unlink()


if __name__ == "__main__":
    tests = [
        test_same_match_key_different_hooks_both_added,
        test_exact_duplicate_skipped,
        test_no_existing_match_appended,
        test_uninstall_removes_exact_match_only,
        test_status_checks_deep_equality,
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
