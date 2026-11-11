# Deployment and operations

Run as your normal Linux user with working opencode credentials. Requirements: user
systemd, Python 3.10+ with venv, bash and flock; bubblewrap is recommended (see
[local command sandbox](#local-command-sandbox)). No runtime pip/npm download is
required. The UI binds to `127.0.0.1:8787`; it is not a public multi-user service.

## Install and update

```sh
# From a trusted extracted release:
bash deploy/install.sh
# Import settings/custom roles on first installation:
# bash deploy/install.sh /absolute/path/settings.json

# Update, preserve configuration, wait for active work, restart automatically:
bash deploy/install.sh --wait=3600 --autostart=keep
```

To select the opencode executable when the service starts, pass
`--opencode=/absolute/path/to/opencode-myfork` to the installer. This replaces
the entire `command` argv in the installed settings, including on update.
For a fixed argv prefix with extra arguments, set `command` in settings.
To replace the complete settings of an existing installation while keeping history,
use `bash deploy/install.sh /path/settings.json --apply-settings`. Relative
paths in the replacement refer to the installed configuration directory.

On first install, after a CLI configuration change, and on either clean reinstall, the installer
queries the CLI version, checks the effective rules of a temporary agent profile
and verifies write access to the run directory. The probe runs in a transient
systemd user service. Both units load `service.env`. Drop-ins for `taskrail.service`
apply only to the installed service, so place CLI environment overrides in
`service.env` to include them in the probe. A failed check reports the cause
before the service stops or history is cleared. After the service starts, Taskrail
saves a fingerprint in `~/.config/taskrail/cli-check.sha256`. Updates with the
same CLI and connection settings reuse it. Run `taskrail check` under the service
account to repeat the diagnostics at any time. Each workflow still verifies its
own permission profile before using a model.

Interactive installation asks about startup at login only when `--autostart` is
omitted (and boot startup was not requested). Explicit `--autostart=keep` skips the startup question. Unattended installs need
`--autostart=yes` to enable it; `keep` preserves an existing choice. The service
starts immediately either way. Boot startup without login is explicit:

```sh
bash deploy/install.sh --autostart=yes --boot=yes
loginctl show-user "$USER" -p Linger
```

`--boot=yes` asks the host to enable user lingering. Host policy may require an
administrator; a denial is reported without sudo or a workaround. `--boot=no`
leaves lingering unchanged and does not disable other user services.

An ordinary update waits for the workflow lock, prepares an offline venv and configuration
in a private staging directory, and validates the incoming package with isolated Python
imports before stopping the service. The installer switches `current` and restarts.
History, settings, custom roles and project edits survive the update. If startup fails,
inspect the journal. The update
script uses a trusted local release, not an automatic Internet download feed. An
installed release contains the public Python packages, named runtime assets,
deployment scripts, README and license. Python modules placed directly in a public
package directory ship as application code, so install from a trusted release tree.
The separate SSH executor receives only its listed modules, configuration validator,
and shared schema and storage code. Configuration imports use the explicit installer
argument.

Failed preparation removes only its own staging directory. After successful startup,
the installer retains the current and previous successful release and any older release
explicitly used by `agent_source`. Older successful releases are pruned only when they
carry this installer's exact success marker. Unrecognized directories remain
for manual inspection. A failed startup keeps the switched release for diagnosis.

### Foreground installation

For a local session without systemd, install from the checkout or extracted release:

```sh
pipx install .
taskrail init
taskrail check
taskrail serve
```

Use `taskrail init --opencode /absolute/path/to/opencode-myfork` to select the
executable for a foreground installation. Run `taskrail check` under the same
account to verify the CLI version, permissions and profile location.

## Run on a remote server

Taskrail can run on a Linux server while you use the browser on your workstation:

1. Install on the server as the account that owns the projects, with opencode
   and its model credentials configured for that account.
   Use `--autostart=yes --boot=yes` so the service runs without an open login session.
2. Keep the UI on the server's loopback address and reach it through SSH:

   ```sh
   ssh -N -L 8787:127.0.0.1:8787 user@server
   ```

   Then open `http://localhost:8787`. Another local port also works, for example
   `-L 9000:127.0.0.1:8787` with `http://localhost:9000`.
3. Project paths in the task form are paths on the server.

Do not publish the port through `0.0.0.0`, a reverse proxy or a firewall rule: the UI
has no user accounts, and its session token only protects against other websites
open in your browser. Closing the tunnel or the browser does not stop running tasks.
Root approval of SSH actions happens in a terminal on the server.

## File locations

| Content | Default path |
|---|---|
| Releases / active symlink | `~/.local/share/taskrail/releases/` / `current` |
| Settings | `~/.config/taskrail/settings.json` |
| Imported custom roles | `~/.config/taskrail/agents/` |
| Service environment | `~/.config/taskrail/service.env` |
| Systemd unit | `~/.config/systemd/user/taskrail.service` |
| CLI | `~/.local/bin/taskrail` |
| History and trash | `~/.local/state/taskrail/runs/` |
| Isolated project worktrees | `~/.local/share/taskrail-worktrees/` |
| Installation lock (shared by runs) | `~/.local/state/taskrail/live.lock` |
| Active project, run and epic locks | `~/.local/state/taskrail/locks/` |

The dashboard header, `taskrail --version` and each run’s `software_version`
identify the running build by its content hash. The installer uses the same
prefix in the release directory name. Identical runtime files produce the same
build ID from a checkout, a wheel or an installed release. Checkpoint continuation
checks the full digest. The service readiness probe checks the responding build.

Taskrail keeps the installation lock between runs. Resource locks disappear
when their last holder exits normally. A process crash releases the OS lock;
the next holder can reuse and remove the empty file.

Sources remain in their declared roots. The application does not copy entire
projects. `run_base` may override history storage; relative paths resolve from the
settings directory. Settings precedence: explicit CLI path, `TASKRAIL_SETTINGS`, installed
user settings, source defaults. The workflow creates history storage on demand. Run
`taskrail check` to see and verify the configured directory. See [recovery settings](monitoring.md#recovery-settings) for stage timeouts.

To switch from imported custom roles to the maintained bundled roles:

```sh
bash deploy/install.sh --wait=3600 --autostart=keep --agents=bundled
```

Switching an existing custom source backs up `settings.json` once per distinct input,
changes only `agent_source`, and leaves custom role
files untouched. Subsequent releases update bundled roles through `current`.
On ordinary updates the default `--agents=keep` preserves the existing selection.
New tasks use the updated roles. Continue uses the frozen roles of its run.

Bundled roles follow `current/taskrail/agents`. An import copies only the four role Markdown
files consumed by the workflow. Imported roles are copied once and
preserved on ordinary updates. To change them, edit their instructions or point
`agent_source` to bundled roles. Generated opencode profiles are temporary permissions, not editable
source templates. See [instruction contracts](contracts.md).

An imported settings file without `agent_source` selects bundled roles, as in
`taskrail init`. Only an explicit `agent_source` imports a custom directory; relative
paths resolve beside the supplied settings file. An explicit imported stage timeout is
preserved. Before either clean reinstall, the installer
checks runtime settings, the agent executable/version, service environment and every
custom role contract, then prepares their installable copies. Invalid or incomplete
roles stop the update; `--agents=bundled` explicitly selects the incoming bundled roles.
Keep supplied settings, imported roles and their symlink targets outside all
reset directories.

## opencode

| Setting | Default | Meaning |
|---|---|---|
| `command` | `["opencode"]` | opencode argv prefix; the installer resolves the executable to an absolute path |
| `opencode_version` | `auto` | `1.x` or `2.x`; `auto` accepts an exact bare or single-name-prefixed semantic version of either supported major; failed, timed-out or ambiguous probes stop instead of guessing |
| `models` | `{}` | Role to `provider/model`; a missing role uses opencode's configured default model |
| `agent_directory` | opencode agent directory | Where managed role profiles are written; relative to the settings file |
| `agent_env_allow` | `[]` | Extra environment variables opencode may receive despite their secret-shaped names; common provider keys are always allowed |
| `permission_worktree` | inferred | Base directory for relative permission names (Git worktree for 1.x, first root for 2.x). Server-owned isolation supplies it automatically for every task |
| `tool_output_dir` | opencode location | Absolute directory (`~` allowed) where the CLI keeps truncated tool output; its automatic `external_directory` allow rule is accepted only for this directory |
| `opencode_server` | `true` | `false` runs each 1.x turn as its own process instead of on the stage's private server |
| `sandbox_network` | `false` | `true` keeps the network for agents' sandboxed commands (package installs, collection downloads); every credential mask stays |
| `host_commands` | `auto` | `auto` runs local commands outside the sandbox at once, highlighted in the stage log; `ask` makes each wait for your approval |

| `protected_paths` | credentials list | Patterns models never read or edit, besides `.env` files; setting it replaces the defaults ([access](access.md#protected-paths)) |

opencode 1.x is called as `opencode run --session --dir --agent --format json --file`
and `opencode agent list`. Where its `run --help` offers `--attach` (opencode 1.0.26 and
later), each stage starts one private `opencode serve --hostname 127.0.0.1 --port 0`
behind a random `OPENCODE_SERVER_PASSWORD`, and every turn runs with `run --attach`:
the session remembers its reads across turns and turns start warm. The server stops
with the stage; `"opencode_server": false` keeps one process per turn. For 2.x, each
stage starts one private `opencode serve`,
waits until the managed agent is loaded, lists its effective rules through
`opencode api` and runs every turn of the stage with `opencode run --server`; the
shared background service is never used. The adapter writes 1.x-shaped events to `events.jsonl` and keeps the
untouched 2.x stream in `events.raw.jsonl`. Every call sets
`OPENCODE_DISABLE_AUTOUPDATE=true`. opencode and approved local commands never receive
secret-shaped variables (`*_TOKEN`, `*_KEY`, `*_SECRET`, `*_PASSWORD`, their `*_FILE`
locators, `SSH_AUTH_SOCK`, `GIT_ASKPASS` and similar); opencode alone keeps common
provider keys and the names in `agent_env_allow`.
The configured argv prefix is preserved for version detection, permission checks, capability probes, servers and
clients. All these calls use the same credential allowlist. A successful help
response without `--attach` selects separate 1.x processes; a failed or timed-out
probe stops explicitly. It never silently disables the shared session server.

The 2.x readiness announcement has a bounded timeout within the stage's remaining
budget and responds to Stop, including when no complete line arrives. Malformed
announcements close the private process before reporting failure. Unknown major
versions are unsupported; select an explicit interface only after verifying the
CLI supports it.

Managed profiles default to `$OPENCODE_CONFIG_DIR/agent`, else
`$XDG_CONFIG_HOME/opencode/agent`. opencode names a file either absolutely or relative
to one base directory: the Git worktree for 1.x, the first declared project root
for 2.x. Profiles allow every declared path in both forms and deny everything else.

## Context limits

Automatic compaction is disabled for every role, including the implementer.
`model_context_tokens` (default `94208`) is one window for every model, or an object
with a window per `provider/model` name and an optional `default` for unlisted
models (a missing `default` is `94208`):

```json
"model_context_tokens": {
  "provider/fast-model": 100000,
  "provider/review-model": 200000,
  "default": 65536
}
```

Each stage uses the window of its role's model from `models`. Keep each window no
higher than the model's real context window. `context_reserve_tokens` (default `8192`)
must be positive and smaller than every window. The handoff boundary is the window minus the reserve, constrained to 90–95%
of the model window. Keep the provider's own
model limits accurate.

The server records request, frozen role and attachment sizes in bytes
for diagnostics. These counts never block a turn: file bytes are not model tokens,
and an approved source file may be read only in small ranges. Repeated prompts,
provider framing and future tool output also prevent byte totals from measuring
context occupancy.

When reported input reaches the reserved boundary, an active process may finish
its work. A completed plan or review still goes through full validation. If the
session needs another turn, Taskrail asks the same session for a final public
handoff, saves it, then opens a fresh session. An explicit provider overflow or
compaction ends the session immediately. Source reads, partial edits, public
messages and saved artifacts remain available for recovery. Handoff text is working
context; citations still require evidence. A repeated overflow on unchanged work
pauses for steering. Model-specific window settings govern each fresh session.

## Local command sandbox

With bubblewrap (`bwrap` on `/bin` or `/usr/bin`; on Debian and Ubuntu
`sudo apt install bubblewrap`), agents' local commands and configured checks run at
once in a sandbox without network, host writes or hidden home files
([access](access.md#local-commands)). The installer reports when it is missing.
`taskrail check` names the network isolation in use: a private network namespace, or
a seccomp socket filter on hosts that forbid configuring one (x86-64 and ARM64).
Without a working bubblewrap, and for a request with `"sandbox": false`, a local
command runs on the host at once and is highlighted in the stage log. Set
`"host_commands": "ask"` to make these commands wait for your approval instead.

## Worktree isolation

`worktree_base` (absolute; default `~/.local/share/taskrail-worktrees`) holds the linked
worktrees of every top-level task; it must lie outside every declared
root. Worktrees are created with hooks and repository filters disabled and are never
removed automatically. See [task format](task-format.md#worktree-isolation).

## Verification commands

For criterion-bound recipes, structured reports and model-free check batches, see
[deterministic verification](checks.md).

Changed `.yml` and `.yaml` files are syntax-checked with PyYAML (safe composer, no tag
construction) from the service's Python, a system `python3` or
`~/.local/state/taskrail/python`. When no Python has it, the check stage asks once per
run: with pip or uv (on the service's `PATH` or in `~/.local/bin`), **Allow** installs
PyYAML into that directory (Allow all actions covers it) and later runs use it;
without either, install it yourself (for example `sudo apt install python3-yaml`) and
Allow; that card runs nothing and is always a personal decision. The files are checked
at once after Allow; after Deny they stay `SKIPPED` as not checked.

The managed installer pins PyYAML 6.0.3 and runs from the server's run directory.
Python uses isolated imports (`-I`), and uv disables configuration discovery
(`--no-config`), so project modules and `uv.toml` cannot alter that installation.
Corporate package indexes and proxies belong in the service's trusted environment
(or pip's operator-owned configuration), not in target-project configuration.

Before any command, the check stage compares each approved file with its preimage and
scans only the added lines. A private key, a GitHub, AWS, Slack or `sk-` style API key
fails the check, so the implementer removes it before review; a literal assigned to a
secret-like name (templated values such as `{{ vault_pw }}` excepted) and leftover
debugging (`console.log`, `debugger`, `breakpoint()`, `pdb`) are warnings the review
sees. A finding names the line and the kind, never the matched text.

`verify_commands` lists project checks that run in the check stage after every
implementation whose changed files pass the built-in syntax checks and the added-line
scan:

```json
{
  "verify_commands": [
    {"cwd": "/home/me/src/shop", "argv": ["python3", "-m", "unittest"], "timeout_seconds": 600}
  ]
}
```

Settings own the exact commands in this list. Agents can also request task-specific
diagnostics through `LOCAL_REQUEST`. Both routes follow the
[local command policy](access.md#local-commands). A verification command
runs only for runs whose declared roots include its `cwd`; in a
[worktree-isolated](task-format.md#worktree-isolation) run it runs in that root's worktree. It runs without a shell,
as the service user, with the filtered environment and the local command policy (no
Git, SSH or privilege commands). `timeout_seconds` defaults to 600 (at most 3600).
Output is kept in `verify-NN.log` of the check stage; a nonzero exit is a failed
check whose output tail goes back to the implementer, with every unresolved check. Unchanged source and repeated failures trigger a
different repair strategy, then a no-progress pause. Commands
must not write inside declared roots (generated folders such as `__pycache__`,
`node_modules` or `.pytest_cache` are ignored): any other change stops the run.

## Configuration changes

New tasks read current settings and roles. Continue retains frozen task, role and
policy snapshots. The service watches the settings file and the four active role
files in `agent_source`, using bundled roles when that setting is omitted. It logs
changes without revealing file contents. A change
to `run_base`, the port or environment requires a service restart.

Systemd does not source shell startup files. Add required proxy/runtime variables
to the existing mode-0600 `service.env`, preserving its PATH. Use `KEY=value`, not
`export` or shell commands. `TASKRAIL_WEB_PORT` controls the port. Credentials stay in
your opencode installation; do not copy them into tasks or logs.

```sh
taskrail check        # settings, opencode, permission enforcement, run storage
systemctl --user status taskrail
systemctl --user restart taskrail
journalctl --user -u taskrail -n 100 --no-pager
taskrail resume /absolute/path/run
```

Closing the browser does not stop work. Service shutdown requests an interruption
checkpoint and waits for cleanup; forced shutdown can leave a stale checkpoint.
Tasks never resume silently. Continue checks source/Git metadata, task, role and
preimage integrity. A standalone UI restart creates a fresh baseline. A split child
restarts with its approved assignment from the current files and reports the files
changed outside the split.

Back up config/state while workflows are stopped; project source needs its own
backup. `systemctl --user disable --now taskrail` disables startup without
deleting configuration, history or code.

## Optional SSH service

The SSH executor is a separate system service with its own user and root-owned
installation. It is not installed or granted privileges by the ordinary UI updater.
See [SSH executor](ssh-executor.md) for installation, host keys and approvals.

## Clean reinstall of the managed application

**`--force-update` erases installed configuration and run history**, including
trash and checkpoints. Run the installer from a checkout or extracted release
outside the managed installation, configuration and history directories.

```sh
# Install the incoming release with its bundled settings and roles
bash deploy/install.sh --force-update --autostart=keep
# Or install a new settings file, including its selected models and role sources
bash deploy/install.sh /path/to/settings.json --force-update --autostart=keep
```

The settings file you supply is imported as on first installation. Relative
`agent_source`, `agent_directory` and `run_base` paths resolve beside that file.
Keep the file and its role sources outside the directories being erased.
The installer removes old releases, the entire Taskrail configuration directory
(including settings backups and imported roles), runtime state, generated
profiles, the user unit and its drop-ins, and the launcher. It regenerates
`service.env` with the installer's PATH and the default port. For generated
profiles, cleanup uses the previously installed `agent_directory` or the CLI
profile directory selected by the old service environment. Use
`--autostart=keep` to retain the service's login startup choice.

The installer validates the replacement and probes its CLI before stopping the
managed service and its workers. If an independent CLI worker holds the workflow
lock, use `--wait=SECONDS` to allow time for it to finish. If the lock stays busy,
the installer restores the previously active service and keeps the installation.

Both clean reinstall modes check the ownership of custom history and protect
project checkouts, linked worktrees, the selected CLI and external provider
credentials. Mixed history or a deletion path that overlaps a protected input
blocks the reset. Held locks retain their inodes throughout installation.
The separate SSH executor keeps its installation and configuration on `--force-update`.

## Reinstall the application and its SSH executor

```sh
bash deploy/install.sh --fresh --wait=3600 --autostart=keep --agents=bundled
```

`--fresh` performs the same clean application reinstall. It waits for the workflow
lock before stopping the service. If the isolated SSH executor is installed, this flag
also requires `sudo` and resets
its service, code, tickets, inventory/passwords and known host keys. Failure to stop
the application leaves the executor untouched; failure to stop the executor preserves
both installations and their data. RUNNING or UNKNOWN
remote tickets must first be reconciled. The executor is reinstalled disabled;
configure its inventory and verified host keys again before starting it. Dedicated
system account/group identities are retained.

## Run storage updates

The dashboard lists current-format runs. Ordinary updates leave existing run directories in
place. Use `--force-update` for a clean application reinstall. Continue requires the
same build. Runs from another build can Restart if their format is current.
The installer removes known retired settings from its staged configuration and prints
the removed keys. Settings cleanup does not create a backup.
Configured commands and operator extension keys are retained during ordinary updates.
