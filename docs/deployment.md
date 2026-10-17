# Deployment and operations

Run as your normal Linux user with working opencode credentials. Requirements: user
systemd, Python 3.10+ with venv, bash, tar and flock. No runtime pip/npm download is
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

Updates acquire installation/execution locks, validate an offline venv, switch
`current` and restart. They preserve history, settings, custom roles and original
project edits. They never execute Git, rewrite run artifacts or roll back source
or application changes. If startup fails, inspect the journal. The update
script uses a trusted local release, not an automatic Internet download feed.

## File locations

| Content | Default path |
|---|---|
| Releases / active symlink | `~/.local/share/countersign/releases/` / `current` |
| Settings | `~/.config/countersign/settings.json` |
| Imported custom roles | `~/.config/countersign/agents/` |
| Service environment | `~/.config/countersign/service.env` |
| Systemd unit | `~/.config/systemd/user/countersign.service` |
| CLI | `~/.local/bin/countersign` |
| History and trash | `~/.local/state/countersign/runs/` |
| Global workflow lock | `~/.local/state/countersign/live.lock` |

Sources remain in their declared roots. The application does not copy entire
projects. `run_base` may override history storage; relative paths resolve from the
settings directory. Settings precedence: explicit CLI path, `COUNTERSIGN_SETTINGS`, installed
user settings, source defaults. See [budgets](monitoring.md) for timeout controls.

To switch from imported custom roles to the maintained bundled roles:

```sh
bash deploy/install.sh --wait=3600 --autostart=keep --agents=bundled
```

This backs up `settings.json`, changes only `agent_source`, and leaves custom role
files untouched. Subsequent releases update bundled roles through `current`.
The default `--agents=keep` preserves the existing selection. Role changes apply
to new tasks; Continue keeps the frozen roles of its run.

Bundled roles follow `current/countersign/agents`. Imported custom roles are copied once and
preserved on update: merge their instructions deliberately or point `agent_source`
to bundled roles. Generated opencode profiles are temporary permissions, not editable
source templates. See [instruction contracts](contracts.md).

## opencode

| Setting | Default | Meaning |
|---|---|---|
| `command` | `["opencode"]` | opencode argv prefix; the installer resolves it to an absolute path. A wrapper for a compatible build also works |
| `opencode_version` | `auto` | `1.x` or `2.x`; `auto` selects `2.x` only for an exact `--version` line of 2.0.0 or later |
| `models` | `{}` | Role to `provider/model`; a missing role uses opencode's configured default model |
| `agent_directory` | opencode agent directory | Where managed role profiles are written; relative to the settings file |
| `agent_env_allow` | `[]` | Extra environment variables opencode may receive despite their secret-shaped names; common provider keys are always allowed |
| `format_repair_tools` | `none` | `read` keeps read-only tools in format repair passes, for providers that reject tool-less requests |
| `permission_worktree` | inferred | Base directory for relative permission names (Git worktree for 1.x, first root for 2.x); required when `.git` is a file or symlink |

opencode 1.x is called as `opencode run --session --dir --agent --format json --file`
and `opencode agent list`. For 2.x, each stage starts one private `opencode serve`,
waits until the managed agent is loaded, lists its effective rules through
`opencode api` and runs every turn of the stage with `opencode run --server`; the
shared background service is never used. The adapter writes 1.x-shaped events to `events.jsonl` and keeps the
untouched 2.x stream in `events.raw.jsonl`. Every call sets
`OPENCODE_DISABLE_AUTOUPDATE=true`. opencode and approved local commands never receive
secret-shaped variables (`*_TOKEN`, `*_KEY`, `*_SECRET`, `*_PASSWORD`, their `*_FILE`
locators, `SSH_AUTH_SOCK`, `GIT_ASKPASS` and similar); opencode alone keeps common
provider keys and the names in `agent_env_allow`.

Managed profiles default to `$OPENCODE_CONFIG_DIR/agent`, else
`$XDG_CONFIG_HOME/opencode/agent`. opencode names a file either absolutely or relative
to one base directory: the Git worktree for 1.x, the first root (the run directory)
for 2.x. Profiles allow every declared path in both forms and deny everything else.

Format repair runs with every tool denied by default. opencode's free Zen models
reject such tool-less requests (`FreeTierError`); for them set `format_repair_tools`
to `read`, which keeps read-only tools in format passes (edits stay denied) and
instructs the model to re-read only evidence it already cites.

## Worktree isolation

`worktree_base` (absolute; default `worktrees` beside `run_base`) holds the linked
worktrees of runs with `"isolation": "worktree"`; it must lie outside every declared
root. Worktrees are created with hooks and repository filters disabled and are never
removed automatically. See [task format](task-format.md#worktree-isolation).

## Verification commands

`verify_commands` lists project checks that run in the check stage after every
implementation whose changed files pass the built-in syntax checks:

```json
{
  "verify_commands": [
    {"cwd": "/home/me/src/shop", "argv": ["python3", "-m", "unittest"], "timeout_seconds": 600}
  ]
}
```

Writing a command into server settings is the operator's personal approval of that
exact argv; task files, imported drafts and models cannot add commands. A command
runs only for runs whose declared roots include its `cwd`; in a
[worktree-isolated](task-format.md#worktree-isolation) run it runs in that root's worktree. It runs without a shell,
as the service user, with the filtered environment and the local command policy (no
Git, SSH or privilege commands). `timeout_seconds` defaults to 600 (at most 3600).
Output is kept in `verify-NN.log` of the check stage; a nonzero exit is a failed
check whose output tail goes back to the implementer, within `max_repairs`. Commands
must not write inside declared roots (generated folders such as `__pycache__`,
`node_modules` or `.pytest_cache` are ignored): any other change stops the run.

## Configuration changes

New tasks read current settings and roles. Continue retains frozen task, role and
policy snapshots; explicit allowance increases are recorded separately. The service
watches settings/role changes and logs them without revealing contents. A change
to `run_base`, the port or environment requires a service restart.

Systemd does not source shell startup files. Add required proxy/runtime variables
to the existing mode-0600 `service.env`, preserving its PATH. Use `KEY=value`, not
`export` or shell commands. `COUNTERSIGN_WEB_PORT` controls the port. Credentials stay in
your opencode installation; do not copy them into tasks or logs.

```sh
countersign check        # settings, opencode, permission enforcement, run storage
systemctl --user status countersign
systemctl --user restart countersign
journalctl --user -u countersign -n 100 --no-pager
countersign resume /absolute/path/run
```

Closing the browser does not stop work. Service shutdown requests an interruption
checkpoint and waits for cleanup; forced shutdown can leave a stale checkpoint.
Tasks never resume silently. Continue checks source/Git metadata, task, role and
preimage integrity. Restart from the UI creates a fresh baseline if these changed.

Back up config/state while workflows are stopped; project source needs its own
backup. `systemctl --user disable --now countersign` disables startup without
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

`--fresh` is destructive and opt-in. It waits for the workflow lock, stops the user
service, removes installed releases, settings, imported roles, history/trash,
managed profiles, cache, the unit/drop-ins and launcher, then installs fresh defaults.
A configured custom history directory is removed only after its contents and
recorded project roots pass ownership checks; mixed or unsafe directories abort
before deletion. Keep source projects and the extracted release outside those paths.
Locked files retain their inodes during installation to prevent concurrent writers.
The underlying opencode application, provider credentials and unrelated profiles
are not owned by this application and are preserved. Old unmanaged directories that
are not recorded in configuration are never guessed or recursively searched for deletion.

If the isolated SSH executor is installed, the same flag requires `sudo` and resets
its service, code, tickets, inventory/passwords and known host keys. RUNNING or UNKNOWN
remote tickets must first be reconciled. The executor is reinstalled disabled;
configure its inventory and verified host keys again before starting it. Dedicated
system account/group identities are retained. Application source edits are never
reverted. `--autostart=keep` retains the previous user-service enablement choice.
Without `--fresh`, installation remains a history/config-preserving update.
