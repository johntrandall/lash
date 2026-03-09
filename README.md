# lash

A manifest-driven symlink installer. Define your project's install operations once in a `lash.json` file, and `lash` handles both install and uninstall — perfectly in sync, every time.

Born out of frustration with paired `install.sh` / `uninstall.sh` scripts that inevitably drift apart. With lash, the manifest is the single source of truth.

## Why lash?

Most developer tools need to place files in specific locations — CLI binaries in `~/.local/bin/`, config snippets in `~/.config/`, hooks in `~/.claude/hooks/`. The typical approach is a shell script that creates symlinks, patches config files, and runs setup commands. Then you need a matching uninstall script that reverses everything. These scripts always drift.

lash replaces both with a single JSON manifest. Install reads forward, uninstall reads backward. One file, zero drift.

**Key properties:**

- **Single source of truth** — `lash.json` defines both install and uninstall
- **Zero dependencies** — Python 3 stdlib only, single file, no pip
- **Idempotent** — safe to re-run install at any time
- **Reversible** — uninstall perfectly undoes what install did
- **Discoverable** — `lash list` finds all managed projects at a glance

## Quick start

```bash
# Clone and bootstrap lash itself
git clone https://github.com/johntrandall/lash.git ~/dev/lash
cd ~/dev/lash
./lash install

# Now 'lash' is on your PATH via ~/.local/bin/lash
# Create a manifest for your own project
cd ~/dev/my-project
cat > lash.json << 'EOF'
{
  "name": "my-project",
  "description": "My awesome tool",
  "operations": [
    {
      "type": "symlink",
      "src": "./bin/my-tool",
      "dest": "~/.local/bin/my-tool",
      "chmod": "+x"
    }
  ]
}
EOF

lash install
```

## Commands

```
lash install   [path]   Create symlinks, patch JSON files, run shell commands
lash uninstall [path]   Reverse all operations (in reverse order)
lash status    [path]   Check what's installed vs missing
lash list      [dir]    Discover all lash.json manifests and show status
```

If no path is given, `lash` looks for `lash.json` in the current directory.

### `lash install`

Reads the manifest forward and executes each operation. Existing files at destination paths are backed up to `{path}.lash-backup` before being replaced.

```
$ lash install
Installing my-project (3 operations)

  ✓ Linked: ~/.local/bin/my-tool → ~/dev/my-project/bin/my-tool
  ✓ JSON patched: ~/.config/app/settings.json at plugins.my-plugin
  ✓ Shell command succeeded

✓ my-project installed successfully.
```

### `lash uninstall`

Reads the manifest **backward** (correct teardown order) and reverses each operation. Symlinks are removed. JSON patches are reverted. Shell uninstall commands run.

```
$ lash uninstall
Uninstalling my-project (3 operations)

  ✓ Shell command succeeded
  ✓ JSON key removed: plugins.my-plugin
  ✓ Removed symlink: ~/.local/bin/my-tool

✓ my-project uninstalled successfully.
```

### `lash status`

Shows the current state of each operation without making changes.

```
$ lash status
Status: my-project

  ✓ ~/.local/bin/my-tool
  ✗ ~/.config/app/settings.json: plugins.my-plugin missing
  - Shell op (no status check)

◐ Partially installed (1/3)
```

Status indicators:
- `✓` Fully installed — all operations green
- `◐` Partially installed — some operations missing
- `○` Not installed — nothing is set up

### `lash list`

Discovers all `lash.json` manifests under `~/dev/*/` (or a custom directory) and displays a summary table.

```
$ lash list
Name        Directory    Operations               Status
──────────  ──────────   ───────────────────────   ─────────────────
my-project  my-project   2 symlink, 1 json_merge   installed (3/3)
other-tool  other-tool   1 symlink                  not installed (0/1)
```

Pass a custom search directory: `lash list ~/projects`

## Manifest format

A `lash.json` file lives in the root of each managed project:

```json
{
  "name": "my-project",
  "description": "Optional human-readable description",
  "operations": [
    { "type": "symlink",    "...": "..." },
    { "type": "json_merge", "...": "..." },
    { "type": "shell",      "...": "..." }
  ]
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `name` | no | Display name (defaults to directory name) |
| `description` | no | What this project does |
| `operations` | yes | Array of operations to execute |

Operations execute in array order on install, and in **reverse** order on uninstall.

## Operation types

### `symlink`

Creates a symbolic link from `src` to `dest`.

```json
{
  "type": "symlink",
  "src": "./bin/my-tool",
  "dest": "~/.local/bin/my-tool",
  "chmod": "+x"
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `src` | yes | Source file (relative to manifest dir, or absolute) |
| `dest` | yes | Destination path (`~` is expanded) |
| `chmod` | no | `"+x"` to make source executable |

**Behavior:**
- Parent directories for `dest` are created automatically
- If `dest` exists as a regular file, it's backed up to `{dest}.lash-backup`
- If `dest` is already a symlink to the correct target, it's left alone (idempotent)
- If `dest` is a symlink to a different target, it's replaced
- On uninstall, the symlink is removed and any `.lash-backup` file is restored

### `json_merge`

Patches a JSON file at a dot-separated key path. Supports setting values and appending to arrays.

#### Action: `set` (default)

```json
{
  "type": "json_merge",
  "file": "~/.config/app/settings.json",
  "path": "plugins.my-plugin.enabled",
  "value": true
}
```

Sets the value at the given path, creating intermediate objects as needed. On uninstall, the key is deleted.

#### Action: `append_unique`

```json
{
  "type": "json_merge",
  "file": "~/.claude/settings.json",
  "path": "hooks.PreToolUse",
  "action": "append_unique",
  "match_key": "matcher",
  "value": {
    "matcher": "SendMessage",
    "hooks": [{"type": "command", "command": "~/.claude/hooks/my-hook.sh"}]
  }
}
```

Appends an object to an array, but only if no existing element matches on `match_key`. On uninstall, the matching element is removed. If the array becomes empty, it's cleaned up.

| Field | Required | Description |
|-------|----------|-------------|
| `file` | yes | Path to the JSON file (`~` expanded) |
| `path` | yes | Dot-separated key path (e.g. `hooks.PreToolUse`) |
| `action` | no | `"set"` (default) or `"append_unique"` |
| `value` | yes | Value to set or append |
| `match_key` | no | For `append_unique`: key used for idempotent matching and removal |

### `shell`

Runs arbitrary shell commands. An escape hatch for operations that don't fit symlink or json_merge.

```json
{
  "type": "shell",
  "install": "launchctl load ~/Library/LaunchAgents/com.example.plist",
  "uninstall": "launchctl unload ~/Library/LaunchAgents/com.example.plist",
  "status": "launchctl list | grep com.example"
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `install` | no | Command to run on `lash install` |
| `uninstall` | no | Command to run on `lash uninstall` |
| `status` | no | Command to run on `lash status` (exit 0 = installed) |

All commands run with the manifest directory as the working directory. If a field is omitted, that phase is a no-op.

## Real-world examples

### Self-installing CLI tool

lash dogfoods itself — here's its own manifest:

```json
{
  "name": "lash",
  "description": "Manifest-driven symlink installer — installs itself and its skill",
  "operations": [
    {
      "type": "symlink",
      "src": "./lash",
      "dest": "~/.local/bin/lash",
      "chmod": "+x"
    },
    {
      "type": "symlink",
      "src": "./skill",
      "dest": "~/.claude/skills/lash-installer"
    }
  ]
}
```

### Claude Code extension with hooks

A project that installs commands, hooks, and registers them in Claude's settings:

```json
{
  "name": "claude-iterm-color",
  "description": "Dynamic iTerm2 tab coloring for Claude Code",
  "operations": [
    {
      "type": "symlink",
      "src": "./hooks/iterm-color-hook.sh",
      "dest": "~/.claude/hooks/iterm-color-hook.sh",
      "chmod": "+x"
    },
    {
      "type": "json_merge",
      "file": "~/.claude/settings.json",
      "path": "hooks.PreToolUse",
      "action": "append_unique",
      "match_key": "matcher",
      "value": {
        "matcher": "SendMessage",
        "hooks": [{"type": "command", "command": "~/.claude/hooks/iterm-color-hook.sh"}]
      }
    }
  ]
}
```

### LaunchAgent with shell operations

```json
{
  "name": "auto-render",
  "description": "Auto-renders diagrams on file change",
  "operations": [
    {
      "type": "symlink",
      "src": "./bin/render-diagrams",
      "dest": "~/.local/bin/render-diagrams",
      "chmod": "+x"
    },
    {
      "type": "symlink",
      "src": "./com.user.auto-render.plist",
      "dest": "~/Library/LaunchAgents/com.user.auto-render.plist"
    },
    {
      "type": "shell",
      "install": "launchctl load ~/Library/LaunchAgents/com.user.auto-render.plist",
      "uninstall": "launchctl unload ~/Library/LaunchAgents/com.user.auto-render.plist",
      "status": "launchctl list | grep -q com.user.auto-render"
    }
  ]
}
```

## Design decisions

**Why JSON, not YAML/TOML?** Python's stdlib includes `json`. No dependencies means lash is a single file you can copy anywhere.

**Why reverse order on uninstall?** If operation A creates a directory and operation B places a file in it, uninstall must remove B before A. Reversing the array handles this naturally.

**Why not GNU Stow?** Stow maps directory trees to target trees 1:1. lash handles heterogeneous operations — symlinks to scattered destinations, JSON config patching, and arbitrary shell commands — all in one manifest.

**Why not a Makefile?** Makefiles are great for builds but awkward for declarative install/uninstall symmetry. lash guarantees that every install operation has a matching uninstall, with no manual bookkeeping.

## Requirements

- Python 3.9+
- No pip packages required
- Works on macOS and Linux

## License

MIT
