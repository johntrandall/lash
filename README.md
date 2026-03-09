# lash

Manifest-driven symlink installer. Define once, install and uninstall in sync.

## Install lash itself

```bash
cd ~/dev/lash
./lash install
```

This symlinks `lash` → `~/.local/bin/lash` so it's on your PATH.

## Usage

```bash
lash install  [path/to/lash.json]   # Create symlinks, patch JSON, run shell commands
lash uninstall [path/to/lash.json]  # Reverse all operations
lash status   [path/to/lash.json]   # Check what's installed vs missing
```

If no path is given, looks for `lash.json` in the current directory.

## Manifest format

```json
{
  "name": "my-project",
  "description": "Optional description",
  "operations": [
    {
      "type": "symlink",
      "src": "./bin/my-tool",
      "dest": "~/.local/bin/my-tool",
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
        "hooks": [{"type": "command", "command": "~/.claude/hooks/my-hook.sh"}]
      }
    },
    {
      "type": "shell",
      "install": "echo 'post-install'",
      "uninstall": "echo 'post-uninstall'",
      "status": "command -v my-tool"
    }
  ]
}
```

## Operation types

### `symlink`

Creates a symbolic link from `src` → `dest`. On uninstall, removes the symlink.

| Field | Required | Description |
|-------|----------|-------------|
| `src` | yes | Source file (relative to manifest dir, or absolute) |
| `dest` | yes | Destination path (~ expanded) |
| `chmod` | no | `"+x"` to make source executable |

If `dest` already exists as a regular file, it is backed up to `{dest}.lash-backup` before linking.

### `json_merge`

Patches a JSON file. On uninstall, reverses the patch.

| Field | Required | Description |
|-------|----------|-------------|
| `file` | yes | JSON file to modify |
| `path` | yes | Dot-separated path (e.g. `hooks.PreToolUse`) |
| `action` | no | `"set"` (default) or `"append_unique"` |
| `value` | yes | Value to set or append |
| `match_key` | no | For `append_unique`: key to match for idempotency/removal |

### `shell`

Runs arbitrary shell commands. Escape hatch for operations that don't fit symlink/json_merge.

| Field | Required | Description |
|-------|----------|-------------|
| `install` | no | Command to run on install |
| `uninstall` | no | Command to run on uninstall |
| `status` | no | Command to run on status (exit 0 = OK) |

## Design

- **Single manifest** — `lash.json` is the only source of truth
- **Install reads forward**, uninstall reads backward (correct teardown order)
- **Zero dependencies** — Python 3 stdlib only
- **Idempotent** — safe to re-run install
- **Backups** — existing files backed up before overwriting

## Requirements

- Python 3.9+
- No pip packages required
