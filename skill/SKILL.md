---
name: lash-installer
description: Use lash for manifest-driven install/uninstall of symlink-based CLI tools. Auto-invoke when creating install.sh/uninstall.sh scripts, setting up symlinks into ~/.claude/ or ~/.local/bin/, or when a project needs an install manifest.
---

# lash — Manifest-Driven Symlink Installer

**Auto-invoke when:**
- Creating or modifying install.sh / uninstall.sh scripts for ~/dev/ projects
- Setting up symlinks into ~/.claude/commands/, ~/.claude/hooks/, or ~/.local/bin/
- Patching ~/.claude/settings.json with hook entries
- User asks about installing or uninstalling a Claude Code extension/plugin

## What is lash?

lash is a single Python 3 script (zero dependencies) that reads a per-project `lash.json` manifest and executes operations forward (install) or backward (uninstall). The manifest is the single source of truth — no drift between install and uninstall.

**Full documentation:** `~/dev/lash/README.md`

## Commands

```bash
lash install   [path/to/lash.json]   # Create symlinks, patch JSON, run shell commands
lash uninstall [path/to/lash.json]   # Reverse all operations in reverse order
lash status    [path/to/lash.json]   # Check what's installed vs missing
lash list      [search-dir]          # Discover all lash.json in ~/dev/*/
```

If no manifest path is given, looks for `lash.json` in the current directory.

## Creating a lash.json for a new project

Every `~/dev/claude-{x}/` project should have a `lash.json` in its root. Example:

```json
{
  "name": "my-project",
  "description": "What this project does",
  "operations": [
    {
      "type": "symlink",
      "src": "./commands/my-cmd.md",
      "dest": "~/.claude/commands/my-cmd.md"
    },
    {
      "type": "symlink",
      "src": "./hooks/my-hook.sh",
      "dest": "~/.claude/hooks/my-hook.sh",
      "chmod": "+x"
    },
    {
      "type": "json_merge",
      "file": "~/.claude/settings.json",
      "path": "hooks.PreToolUse",
      "action": "append_unique",
      "match_key": "matcher",
      "value": {
        "matcher": "ToolName",
        "hooks": [{"type": "command", "command": "~/.claude/hooks/my-hook.sh"}]
      }
    }
  ]
}
```

## Operation types

### symlink
- `src`: source file (relative to manifest dir or absolute)
- `dest`: destination path (~ expanded)
- `chmod` (optional): `"+x"` to make source executable
- Backs up existing non-symlink files to `{dest}.lash-backup`

### json_merge
- `file`: JSON file to modify
- `path`: dot-separated key path (e.g. `hooks.PreToolUse`)
- `action`: `"set"` (default) or `"append_unique"`
- `value`: value to set or append
- `match_key` (for `append_unique`): key for idempotent matching and removal

### shell
- `install`: command to run on install
- `uninstall`: command to run on uninstall
- `status`: command to run on status (exit 0 = OK)

## Key rules

1. **Never create paired install.sh/uninstall.sh** — use lash.json instead
2. **One manifest per project** — lash.json lives in the project root
3. **lash is a dependency, not a manager** — each project owns its own manifest
4. **Install reads forward, uninstall reads backward** — correct teardown order
5. **All operations are idempotent** — safe to re-run
