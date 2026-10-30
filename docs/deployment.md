# Deployment and operations

Run as your normal Linux user with working opencode credentials. Requirements: user
systemd, Python 3.10+ with venv, bash, tar and flock; bubblewrap is recommended (see
[local command sandbox](#local-command-sandbox)). No runtime pip/npm download is
required. The UI binds to `127.0.0.1:8787`; it is not a public multi-user service.

## Install and update

```sh
# From a trusted extracted release:
bash deploy/install.sh
# Import existing settings/custom roles on FIRST installation only:
# bash deploy/install.sh /absolute/path/settings.json

# Update, preserve configuration, wait for active work, restart automatically:
bash deploy/install.sh --wait=3600 --autostart=keep
```

Interactive installation asks about startup at login only when `--autostart` is
omitted (and boot startup was not requested). Explicit `--autostart=keep` never
prompts, including in a terminal. Unattended installs need
`--autostart=yes` to enable it; `keep` preserves an existing choice. The service
starts immediately either way. Boot startup without login is explicit:

```sh
bash deploy/install.sh --autostart=yes --boot=yes
loginctl show-user "$USER" -p Linger
```

`--boot=yes` asks the host to enable user lingering. Host policy may require an
administrator; a denial is reported without sudo or a workaround. `--boot=no`
leaves lingering unchanged and does not disable other user services.

Updates wait for every active run (runs share the installation lock), prepare an offline
venv and configuration in a private staging directory, and validate the incoming package
with isolated Python imports before stopping the service. The installer then switches
`current` and restarts. It preserves history, settings, custom roles and original
project edits. They never execute Git, rewrite run artifacts or roll back source
or application changes. If startup fails, inspect the journal. The update
script uses a trusted local release, not an automatic Internet download feed. An
installed release holds the application, deployment scripts, README and license;
documentation stays in the source tree.

Failed preparation removes only its own staging directory. After successful startup,
the installer retains the current and previous successful release and any older release
explicitly used by `agent_source`. Older successful releases are pruned only when they
carry this installer's exact success marker; legacy or unrecognized directories remain
for manual inspection. A failed startup keeps the switched release for diagnosis.

## Run on a remote server

Taskrail can run on a Linux server while you use the browser on your workstation:

1. Install on the server as the account that owns the projects, with opencode (or a
   compatible wrapper) and its model credentials configured for that account.
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
| Project and run locks | `~/.local/state/taskrail/locks/` |

Sources remain in their declared roots. The application does not copy entire
projects. `run_base` may override history storage; relative paths resolve from the
settings directory. Settings precedence: explicit CLI path, `TASKRAIL_SETTINGS`, installed
user settings, source defaults. See [budgets](monitoring.md) for timeout controls.

To switch from imported custom roles to the maintained bundled roles:

```sh
bash deploy/install.sh --wait=3600 --autostart=keep --agents=bundled
```

This backs up `settings.json`, changes only `agent_source`, and leaves custom role
files untouched. Subsequent releases update bundled roles through `current`.
The default `--agents=keep` preserves the existing selection. Role changes apply
to new tasks; Continue keeps the frozen roles of its run.

Bundled roles follow `current/taskrail/agents`. Imported custom roles are copied once and
preserved on update: merge their instructions deliberately or point `agent_source`
to bundled roles. Generated opencode profiles are temporary permissions, not editable
source templates. See [instruction contracts](contracts.md).

An imported settings file without `agent_source` selects bundled roles, as in
`taskrail init`. Only an explicit `agent_source` imports a custom directory; relative
paths resolve beside the supplied settings file. Before a fresh reset, the installer
checks runtime settings, the agent executable/version, service environment and all three
custom role contracts, then prepares their installable copies. Invalid or incomplete
roles stop the update; `--agents=bundled` explicitly selects the incoming bundled roles.
Keep supplied settings, imported roles and their symlink targets outside all
reset directories.

## opencode

| Setting | Default | Meaning |
|---|---|---|
| `command` | `["opencode"]` | opencode argv prefix; the installer resolves it to an absolute path. A wrapper for a compatible build also works |
| `opencode_version` | `auto` | `1.x` or `2.x`; `auto` accepts an exact bare or single-name-prefixed semantic version of either supported major; failed, timed-out or ambiguous probes stop instead of guessing |
| `models` | `{}` | Role to `provider/model`; a missing role uses opencode's configured default model |
| `agent_directory` | opencode agent directory | Where managed role profiles are written; relative to the settings file |
| `agent_env_allow` | `[]` | Extra environment variables opencode may receive despite their secret-shaped names; common provider keys are always allowed |
| `permission_worktree` | inferred | Base directory for relative permission names (Git worktree for 1.x, first root for 2.x). Server-owned isolation supplies it automatically; unowned/in-place 1.x roots with a `.git` file or symlink require an explicit value |
| `tool_output_dir` | opencode location | Absolute directory (`~` allowed) where a compatible CLI keeps truncated tool output; its automatic `external_directory` allow rule is accepted only for this directory |
| `opencode_server` | `true` | `false` runs each 1.x turn as its own process instead of on the stage's private server |
| `stop_on_provider_limit` | `false` | `true` stops a stage at the first exhausted provider quota or billing limit instead of spending its retries ([contracts](contracts.md)) |
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
The configured argv prefix, including an nga wrapper's profile arguments, is
preserved for version detection, permission checks, capability probes, servers and
clients. All these calls use the same credential allowlist. A successful help
response without `--attach` selects separate 1.x processes; a failed or timed-out
probe stops explicitly. It never silently disables the shared session server.

The 2.x readiness announcement has a bounded timeout within the stage's remaining
budget and responds to Stop, including when no complete line arrives. Malformed
announcements close the private process before reporting failure. Unknown major
versions are unsupported; set an explicit interface only after establishing wrapper
compatibility with that interface.

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
must be positive and smaller than every window. A session ends at the window minus
the reserve, kept between 90 and 95 percent of the window. Keep the provider's own
model limits accurate.

The server records request, frozen role and attachment sizes in bytes
for diagnostics. These counts never block a turn: file bytes are not model tokens,
and an approved source file may be read only in small ranges. Repeated prompts,
provider framing and future tool output also prevent byte totals from measuring
context occupancy.

Runtime monitoring stops only when the latest provider-reported input, including cache
read/write tokens, reaches the reserved capacity, the provider reports an explicit
context overflow, or a compaction marker appears. Missing usage is unknown and does
not imply that capacity was exceeded. These checks also cover continuation startup
and the final event drain. Reports may arrive after the provider has consumed tokens;
the configured reserve cannot guarantee that every later tool result will fit.

An observed boundary or overflow is `CONTEXT_EXCEEDED`. A session that reaches the
boundary is not compacted: the stage continues in a fresh session, up to `read_retries`
times. A reading stage starts it from recorded evidence; the implementer keeps its edits
and continues from `progress.md` (Done, Remaining), told to read the files it already
changed before editing them. Nothing is rolled back, and a writer interrupted any other
way is never replayed. Before a fresh session starts, its attached progress notes are
bounded to 8 KiB. Growth during an active session never itself exhausts context.
Oversized notes are preserved verbatim under `00-input/progress-archive/`, and the next session receives
bounded beginning/end excerpts with an exact archive reference. Only those archive
files become readable. Another overflow without changed source or working notes
stops instead of repeating the same handoff. When fresh sessions do not suffice, replan into smaller atomic
tasks or deliberately correct the model limit. `max_observed_tokens` remains a separate cumulative cost cap.

After a planner context stop, the server first validates its saved `plan.md` against
the same source evidence, requirement coverage, scope and dependency contracts.
A valid ready proposal proceeds to independent plan review without another planner
call; the original context-stop diagnostics remain recorded. An invalid proposal
gets exact validation errors in its bounded recovery attempt. Permission failures,
source violations and interrupted writers never use this path.

## Local command sandbox

With bubblewrap (`bwrap` on `/bin` or `/usr/bin`; on Debian and Ubuntu
`sudo apt install bubblewrap`), agents' local commands and configured checks run at
once in a sandbox without network, host writes or hidden home files
([access](access.md#local-commands)). The installer reports when it is missing.
`taskrail check` names the network isolation in use: a private network namespace, or
a seccomp socket filter on hosts that forbid configuring one (x86-64 and ARM64).
Without a working bubblewrap every local command waits for approval, as does a
request for the host with `"sandbox": false`.

## Worktree isolation

`worktree_base` (absolute; default `~/.local/share/taskrail-worktrees`) holds the linked
worktrees of isolated runs, the default for code changes; it must lie outside every declared
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

Settings define the exact argv; task files, imported drafts and models cannot add
commands. Execution follows the [local command policy](access.md#local-commands):
sandboxed commands run at once; commands outside the sandbox require personal
approval per command or the operator's Allow all actions for the run. A command
runs only for runs whose declared roots include its `cwd`; in a
[worktree-isolated](task-format.md#worktree-isolation) run it runs in that root's worktree. It runs without a shell,
as the service user, with the filtered environment and the local command policy (no
Git, SSH or privilege commands). `timeout_seconds` defaults to 600 (at most 3600).
Output is kept in `verify-NN.log` of the check stage; a nonzero exit is a failed
check whose output tail goes back to the implementer, within `max_repairs`. When a
repair leaves exactly the same checks failing (run-specific evidence paths and
durations aside), the run stops with `CHECK_FAILED` instead of repeating it; a timed-out
check is always repaired again. Commands
must not write inside declared roots (generated folders such as `__pycache__`,
`node_modules` or `.pytest_cache` are ignored): any other change stops the run.

## Change size limit

`max_change_lines` (default 400 added or removed diff lines) and `max_change_files`
(default 15 changed files) bound an implementation, not how work is split into tasks;
`0` disables a limit. A larger
change waits before checks and review: **Allow** continues (a later repair may grow
up to the allowed size without asking again), **Deny** stops the run as
`CHANGE_LIMIT_EXCEEDED` with the changes preserved (Continue asks again), and an
alternative returns the work to the implementer with your note.

## Configuration changes

New tasks read current settings and roles. Continue retains frozen task, role and
policy snapshots; explicit allowance increases are recorded separately. The service
watches settings/role changes and logs them without revealing contents. A change
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

## Full reinstallation

From an extracted release **outside** the managed installation/config/history paths:

```sh
bash deploy/install.sh --fresh --wait=3600 --autostart=keep --agents=bundled
```

`--fresh` is destructive and opt-in. It waits for the workflow lock, completely prepares
and validates the replacement application/configuration, then stops the user
service and any installed executor before deleting anything. It removes installed releases, settings, imported roles, history/trash,
managed profiles, cache, the unit/drop-ins and launcher, then installs fresh defaults.
A configured custom history directory is removed only after its contents and
recorded project roots pass ownership checks. Live runs, archived runs and launcher
records all protect their declared roots. The same inventory covers cache, unit
drop-ins, launcher and generated profile files; mixed, redirected or overlapping
paths abort before deletion. Keep source projects and the extracted release outside
those paths.
Legacy `~/.local/state/taskrail/worktrees` is preserved in place, including uncommitted
edits and its Git links. New worktrees live outside resettable application storage.
A custom `worktree_base` overlapping a deletion target refuses the reset; move that
storage deliberately before retrying. Worktrees are never pruned with old releases.
Locked files retain their inodes during installation to prevent concurrent writers.
The underlying opencode application, provider credentials and unrelated profiles
are not owned by this application and are preserved. Old unmanaged directories that
are not recorded in configuration are never guessed or recursively searched for deletion.

If the isolated SSH executor is installed, the same flag requires `sudo` and resets
its service, code, tickets, inventory/passwords and known host keys. Failure to stop
the application leaves the executor untouched; failure to stop the executor preserves
both installations and their data. RUNNING or UNKNOWN
remote tickets must first be reconciled. The executor is reinstalled disabled;
configure its inventory and verified host keys again before starting it. Dedicated
system account/group identities are retained. Application source edits are never
reverted. `--autostart=keep` retains the previous user-service enablement choice.
Without `--fresh`, installation remains a history/config-preserving update.
