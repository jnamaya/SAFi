# SAFi Automatic SSH Key Setup

How SAFi adds your SSH public key to a target machine automatically, so the
sysadmin agent can run `sys-exec <target> <command>` passwordless.

## How it works (summary)

1. Ensure a local Ed25519 key pair exists (`~/.ssh/id_ed25519[.pub]`).
2. Resolve the target (inventory alias, `user@host`, or bare host).
3. If passwordless SSH already works, do nothing (idempotent).
4. Otherwise install the public key — via `ssh-copy-id` on Linux, or a
   base64-encoded PowerShell script (with `icacls` ACL hardening) on Windows.
5. Verify passwordless connectivity.

You are prompted for the target's password **once** during installation.

## Entry points

All of these reach the same native implementation, `deploy_key_native()` in
`safi_cli/ssh_keys.py`:

| Invocation | Where wired |
|---|---|
| `safi setup-key [target]` (also `push-key`, `ssh-key`) | `safi_cli/main.py:56-58` |
| `safi --setup-key [target]` | `safi_cli/main.py:108-121` |
| In-chat `/setup-key [target]`, `/ssh-key`, `/push-key` | `safi_cli/repl.py:448, 788` |
| `safi-setup-key` standalone binary | `safi_cli/ssh_keys.py:359` `main()` |
| Agent tool "Deploy SSH Key" | `safi_cli/agent_registry.py:447` |

With no target, the command is **interactive**: it lists your inventory
aliases in a numbered table and prompts you to pick one (or type a custom
`user@host`).

## The canonical implementation: `safi_cli/ssh_keys.py`

`run_setup_key()` (`ssh_keys.py:271`) parses args, then calls
`deploy_key_native()` (`ssh_keys.py:103`). The steps:

### 1. Local key — `ensure_local_ssh_key()` (`ssh_keys.py:46`)
- Uses `~/.ssh/id_ed25519` / `id_ed25519.pub` (`get_default_key_paths`, L15).
- If the public key is missing it generates a fresh pair with
  `ssh-keygen -t ed25519 -N ""` and comment `safi-agent@<hostname>`.
- Returns the public key content; errors if the file is empty.

### 2. Target resolution (`deploy_key_native`, L121-160)
- **Inventory alias:** looked up in `config.load_inventory()`
  (`~/.config/safi/inventory.json`). Reads `host` (strips a leading
  `ssh `), `user`, `port` (default 22), and infers OS: `windows` if
  `win` appears in `os`, `description`, or the alias name; else `linux`.
- **`user@host`:** split on the first `@`; OS defaults to `linux`.
- **bare host:** used as host; user defaults to `$USER`/`$USERNAME`/`root`.
- CLI overrides `--user`, `--port`, `--win/--linux` take precedence.

### 3. Idempotency check (L164-186)
Runs `ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new
-o ConnectTimeout=4 -p <port> user@host "echo OK"`. If it succeeds the
target is already configured and the function returns 0 without installing.

### 4. Deployment (L188-238)
- **Linux:** prefer `ssh-copy-id -i <pub> -p <port> user@host`. If
  `ssh-copy-id` is unavailable, fall back to a remote shell that creates
  `~/.ssh` (chmod 700), appends the key to `authorized_keys` only if not
  already present (dedup via `grep -qF`), and chmods `authorized_keys` 600.
- **Windows:** `build_windows_ps_script()` (L71) builds a PowerShell snippet
  that:
  - for an **administrator**, writes to
    `%ProgramData%\ssh\administrators_authorized_keys`;
  - otherwise writes to `%USERPROFILE%\.ssh\authorized_keys`;
  - dedups with a regex-escaped match, then applies strict ACLs via
    `icacls.exe ... /inheritance:r /grant <Account>:F SYSTEM:F`.
  The script is UTF-16LE + base64-encoded and run as
  `powershell.exe -EncodedCommand ...` over SSH, so the key never appears on
  the command line.

### 5. Verification (L240-268)
Re-runs the BatchMode `echo OK` probe. On success it prints a success banner
and, for inventory targets, reminds you to use `sys-exec <target> "..."`.
On failure it returns 1.

## The bash script: `scripts/setup_ssh_key.sh`

`scripts/setup_ssh_key.sh` and `safi_cli/setup_ssh_key.sh` are byte-identical
copies of the same logic expressed in bash (`set -eo pipefail`):

- keygen of `~/.ssh/id_ed25519` if absent (L78-85);
- inventory resolution via `jq` against `~/.config/safi/inventory.json`
  (L103-123), with the same `win`-in-name/description heuristic;
- BatchMode idempotency probe (L147-155);
- Linux: `ssh-copy-id` with a manual `authorized_keys` fallback (L215-221);
- Windows: the same PowerShell/`icacls` payload, base64-encoded via
  `iconv`/`base64` and sent as `-EncodedCommand` (L169-207);
- final verification (L226-242).

### Which one actually runs?
`deploy_key_native()` does **not** shell out to this script — the native
Python path is authoritative. `find_setup_script()` (`ssh_keys.py:21`) exists
to locate a script/binary in this preference order:
1. `safi_cli/setup_ssh_key.sh` (packaged, executable)
2. `<repo>/scripts/setup_ssh_key.sh`
3. `~/.local/share/safi-cli/setup_ssh_key.sh`
4. `~/.local/bin/safi-setup-key`
5. `which safi-setup-key`

Treat `scripts/setup_ssh_key.sh` as a standalone/fallback artifact (and the
source of the `safi-setup-key` binary); the in-process CLI always uses the
Python implementation.

## Downstream use
Once the key is installed, the sysadmin agent runs remote commands without
prompts via `sys-exec <target-alias> <command>` (see `MANAGED_OPERATOR.md`).

## Files
- `safi_cli/ssh_keys.py` — canonical native implementation + CLI/REPL wiring
- `safi_cli/main.py` — `safi setup-key` / `--setup-key` entry points, plus `safi keygen` / `safi gen-key` (local key only, no deployment)
- `safi_cli/repl.py` — in-chat `/setup-key`, `/ssh-key`, `/push-key`
- `safi_cli/agent_registry.py:447` — agent-facing "Deploy SSH Key" tool
- `scripts/setup_ssh_key.sh`, `safi_cli/setup_ssh_key.sh` — bash fallback
- `~/.config/safi/inventory.json` — target definitions (host/user/port/os)
