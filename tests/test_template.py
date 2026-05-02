"""Tests for the template operation."""

import os
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


# --- helpers ---------------------------------------------------------------

def _make_template(content: str, suffix: str = ".tmpl") -> Path:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False)
    f.write(content)
    f.close()
    return Path(f.name)


# --- _resolve_template_vars ------------------------------------------------

def test_resolve_literal_var():
    out = lash._resolve_template_vars({"REGION": "us-east-1"})
    assert out == {"REGION": "us-east-1"}


def test_resolve_env_var(monkeypatch=None):
    os.environ["LASH_TEST_VAR"] = "hello"
    try:
        out = lash._resolve_template_vars({"GREETING": "@env:LASH_TEST_VAR"})
        assert out == {"GREETING": "hello"}
    finally:
        del os.environ["LASH_TEST_VAR"]


def test_resolve_env_with_default():
    os.environ.pop("LASH_NONEXISTENT_VAR", None)
    out = lash._resolve_template_vars({"X": "@env:LASH_NONEXISTENT_VAR:fallback"})
    assert out == {"X": "fallback"}


def test_resolve_env_unset_no_default_raises():
    os.environ.pop("LASH_NONEXISTENT_VAR", None)
    try:
        lash._resolve_template_vars({"X": "@env:LASH_NONEXISTENT_VAR"})
        raised = False
    except ValueError:
        raised = True
    assert raised, "expected ValueError for unset env var without default"


def test_resolve_non_string_coerced():
    out = lash._resolve_template_vars({"PORT": 8080})
    assert out == {"PORT": "8080"}


# --- _render_template ------------------------------------------------------

def test_render_basic_substitution():
    out = lash._render_template("hello {{NAME}}", {"NAME": "world"})
    assert out == "hello world"


def test_render_multiple_substitutions():
    text = "user={{USER}} home={{HOME}}"
    out = lash._render_template(text, {"USER": "ada", "HOME": "/Users/ada"})
    assert out == "user=ada home=/Users/ada"


def test_render_repeated_key():
    out = lash._render_template("{{X}}-{{X}}", {"X": "a"})
    assert out == "a-a"


def test_render_unknown_placeholder_left_alone():
    out = lash._render_template("known={{KNOWN}} other={{UNKNOWN}}", {"KNOWN": "k"})
    assert out == "known=k other={{UNKNOWN}}"


# --- install ---------------------------------------------------------------

def test_template_install_basic():
    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        src = base / "config.tmpl"
        src.write_text("home={{HOME}}\nuser={{USER}}\n")
        dest = base / "out" / "config"
        op = {
            "type": "template",
            "src": str(src),
            "dest": str(dest),
            "vars": {"HOME": "/Users/ada", "USER": "ada"},
        }
        assert lash.do_template_install(op, base) is True
        assert dest.read_text() == "home=/Users/ada\nuser=ada\n"


def test_template_install_idempotent():
    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        src = base / "t.tmpl"
        src.write_text("x={{X}}")
        dest = base / "out"
        op = {"type": "template", "src": str(src), "dest": str(dest),
              "vars": {"X": "1"}}
        assert lash.do_template_install(op, base) is True
        first_mtime = dest.stat().st_mtime_ns
        # Re-run — content matches, no rewrite needed.
        assert lash.do_template_install(op, base) is True
        assert dest.read_text() == "x=1"


def test_template_install_backs_up_existing_file():
    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        src = base / "t.tmpl"
        src.write_text("rendered={{X}}")
        dest = base / "out"
        dest.write_text("pre-existing")
        op = {"type": "template", "src": str(src), "dest": str(dest),
              "vars": {"X": "1"}}
        assert lash.do_template_install(op, base) is True
        assert dest.read_text() == "rendered=1"
        backup = dest.with_suffix(dest.suffix + ".lash-backup")
        assert backup.exists()
        assert backup.read_text() == "pre-existing"


def test_template_install_unset_env_no_default_fails():
    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        src = base / "t.tmpl"
        src.write_text("x={{X}}")
        dest = base / "out"
        os.environ.pop("LASH_NONEXISTENT_VAR", None)
        op = {"type": "template", "src": str(src), "dest": str(dest),
              "vars": {"X": "@env:LASH_NONEXISTENT_VAR"}}
        assert lash.do_template_install(op, base) is False
        assert not dest.exists()


# --- uninstall -------------------------------------------------------------

def test_template_uninstall_removes_dest_and_restores_backup():
    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        src = base / "t.tmpl"
        src.write_text("rendered={{X}}")
        dest = base / "out"
        dest.write_text("pre-existing")
        op = {"type": "template", "src": str(src), "dest": str(dest),
              "vars": {"X": "1"}}
        lash.do_template_install(op, base)
        assert lash.do_template_uninstall(op, base) is True
        assert dest.read_text() == "pre-existing"  # backup restored


def test_template_uninstall_skips_symlink():
    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        target = base / "elsewhere"
        target.write_text("data")
        dest = base / "out"
        dest.symlink_to(target.resolve())
        op = {"type": "template", "src": str(base / "t.tmpl"), "dest": str(dest),
              "vars": {}}
        assert lash.do_template_uninstall(op, base) is False
        assert dest.is_symlink()


# --- status / verify -------------------------------------------------------

def test_template_status_dest_exists():
    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        dest = base / "out"
        dest.write_text("anything")
        op = {"type": "template", "src": str(base / "t.tmpl"), "dest": str(dest),
              "vars": {}}
        assert lash.do_template_status(op, base) is True


def test_template_status_dest_missing():
    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        op = {"type": "template", "src": str(base / "t.tmpl"),
              "dest": str(base / "out"), "vars": {}}
        assert lash.do_template_status(op, base) is False


def test_template_verify_exact_match():
    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        src = base / "t.tmpl"
        src.write_text("v={{V}}")
        dest = base / "out"
        op = {"type": "template", "src": str(src), "dest": str(dest),
              "vars": {"V": "yes"}}
        lash.do_template_install(op, base)
        assert lash.do_template_verify(op, base) is True


def test_template_verify_drifted_fails():
    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        src = base / "t.tmpl"
        src.write_text("v={{V}}")
        dest = base / "out"
        dest.write_text("v=stale")  # Manually drifted.
        op = {"type": "template", "src": str(src), "dest": str(dest),
              "vars": {"V": "current"}}
        assert lash.do_template_verify(op, base) is False


if __name__ == "__main__":
    import inspect
    tests = [obj for name, obj in inspect.getmembers(sys.modules[__name__])
             if name.startswith("test_") and callable(obj)]
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
