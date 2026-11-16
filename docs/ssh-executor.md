# Isolated SSH and Jenkins executor

The optional executor runs as the dedicated Linux account `taskrail-executor`.
Taskrail can start an SSH script on any selected target using the remote account’s permissions.
The executor authenticates the local application account. Any process with that account’s socket access can submit SSH work.
The model, browser and ticket journal receive public target identities. The task
process opens project inventories as the application user. SSH authentication and
remote execution run under the executor account.

## Install and configure

From a trusted release, run the application installer as your usual account:

```sh
bash deploy/install.sh --with-ssh --autostart=yes
```

The installer uses sudo for the system component, starts the Taskrail user service,
and enables a private socket for that account. Systemd starts the isolated executor
when Taskrail first contacts the socket. No extra group membership or login is
required. Check readiness with `taskrail check --ssh`; an empty default host list
is valid. `systemctl is-active taskrail-executor.socket` reports `active` even
before the executor handles its first request. The system Python needs PyYAML for project inventories (Debian/Ubuntu:
`sudo apt install python3-yaml`). Before the first remote connection, add the
independently verified host keys to `/etc/taskrail-executor/known_hosts` with
`sudoedit`. Project inventories supply their own targets.

Use the same command to update both components. The ordinary installer also works
without SSH. For a separate system installation, use
`sudo bash deploy/install-executor.sh --client="$USER" --autostart=enable`.
Socket enablement controls activation after boot independently of user login.
Updates preserve credentials, host keys and
queued tickets. Installers and resets hold one root-owned lock outside their deletion
targets, so concurrent maintenance is refused. Packages receive explicit directory
and file permissions and must import successfully as the executor account before
the service stops. Updates and resets (`deploy/install.sh --fresh` runs
`deploy/reset-executor.sh`) work in maintenance mode: while
`/etc/taskrail-executor/maintenance` exists the service refuses new submissions and
approvals, and Taskrail waits and asks again. The script then refuses to go on while
an action is RUNNING (a reset also while one is UNKNOWN), stops the service and fails
if it does not stop, checks the journal again, and only then swaps in the package it
prepared beforehand, or deletes the installation. A failed safety check prevents the
package swap or reset; a failure after stopping the service leaves it stopped for
inspection. A reset never deletes the journal of a running or uncertain action.
An existing maintenance marker is preserved and requires inspection of the interrupted
operation before retrying. The socket only accepts the configured application UID and root through its
filesystem permissions and the executor verifies the caller's UID independently.
Installing the socket for a user grants that account the SSH capability. The sudo approval helper handles configured Jenkins builds.

For the default SSH catalog, configure aliases in `hosts.json`.
Use `{}` if tasks will only use selected inventories. Default catalog format:

```json
{
  "qa-node-1": {
    "hostname": "192.0.2.10",
    "port": 22,
    "username": "operator",
    "password": "YOUR_PASSWORD"
  }
}
```

Credentials and host keys belong to `root:taskrail-executor`, mode `0640`, inside a
`0750` directory. Obtain and verify host keys through a trusted channel before
adding them to `known_hosts`; the executor never accepts unknown keys automatically.
For nonstandard ports use OpenSSH's `[hostname]:port` known-hosts notation.
The executor loads `hosts.json` at startup. After editing that default catalog,
restart the executor when no actions are running. Task-selected YAML inventories
are read on demand.
Each host uses either `password` or `identity_file`. For key authentication, replace
`password` with the absolute path of an unencrypted private key inside
`/etc/taskrail-executor/`, owned by `root:taskrail-executor` with mode `0640`:

```sh
sudo install -d -m 0750 -o root -g taskrail-executor /etc/taskrail-executor/keys
sudo install -m 0640 -o root -g taskrail-executor id_ed25519 /etc/taskrail-executor/keys/qa-node-1
```

The key is offered alone (`IdentitiesOnly`, no agent, no password prompt). Remote
sudo password handling is not implemented; choose the remote account's permissions
deliberately.

## Inspect an Ansible group from a task

Name the inventory path in the task. Taskrail opens the project file using the
application account and passes a read-only file descriptor to the executor.
The executor has no general access to the application's home directory. There is
no copy to install, mount or synchronize when inventory files change. Different
directories can have identically named inventories. The planner can select another
file and group in the same task. Each ticket keeps its own selection.

To check discovery manually, use the actual project path:

```sh
taskrail check --ssh --inventory-file "/path/to/repo/inventory/cluster.yaml" --inventory-group workers
```

This queries the local executor. SSH connectivity and host keys are tested on the
first SSH connection. To start a task, describe the project inventory path,
group and measurements in the goal. Choose **Discussion** for a report. The same
goal works in the dashboard and CLI:

```sh
taskrail submit --mode discussion --root project=/path/to/repo \
  --goal "Inspect the workers group in /path/to/repo/inventory/cluster.yaml. Report disk usage, CPU load and running services on each host."
```

During planning, the model sends the path and group in an `INVENTORY_REQUEST`.
Taskrail checks the path against the task's roots and authenticated source checkout.
The executor resolves the group and returns public target information. Discovery runs
locally and contacts no hosts. Checkpoints keep the selected path, group and content
digest. On a new SSH request, Taskrail supplies the file again. The executor checks
the digest, expands the selected aliases and records the request before opening a connection.
If the file changed or disappeared, the agent receives a discovery error and can repeat the lookup.
The SSH route returns public identities and removes known inventory passwords
from captured command output before recording it.

Before capturing the project, Taskrail checks the working file, the staged
version and the current commit for Ansible password fields in each task-named
YAML file. It checks both the source checkout and the task worktree, even when
the executor is offline. For example, protecting `inventory/main.yaml` leaves
`roles/web/tasks/main.yaml` available. Child tasks and continuations inherit
these protections. Use `protected_paths` for other credential files in the
repository. Administrators can still publish
private inventories in `/etc/taskrail-executor/inventories` for catalog checks
by filename.

Use an ordinary YAML file with explicit host aliases, group
`hosts`, `children` and inline `vars`. Connections use literal SSH username,
password, host (defaults to the alias), and port (defaults to 22). Nested groups
inherit variables, with host settings taking precedence. Dynamic inventory
plugins, host ranges, external variable files, Vault, templated credentials and
SSH proxy options are outside this static format.

## Run commands

The planner, implementer and reviewers can send an `ACTION_REQUEST` in their existing
session. Use `"targets": "all"` for every host in the selected group or default catalog.
An array selects particular aliases. Large group lists are saved in a readable file
referenced by the stage prompt. One request covers the whole group regardless of size.

```json
{"schema_version":1,"status":"ACTION_REQUEST","action":{"targets":"all","script":"df -PT; uptime; vmstat 1 2","files":{},"reason":"Collect disk usage, load averages and sampled CPU utilization"}}
```

The agent chooses the remote shell commands, pipelines and text files according to
the user's task. For diagnostics, ask it to collect measurements without changing the hosts.
The remote account’s permissions determine what its commands can actually do. Use a
read-only account when the infrastructure must enforce that property.

The executor starts immediately, records each host’s output and exit status, and
continues to the remaining hosts after failures or disconnections. A disconnect gives
`UNKNOWN` for that host. Any uncertain host makes the overall result uncertain. Each
request may specify a positive `timeout_seconds` per host. Omitting it leaves the
remote command without a Taskrail execution deadline. SSH still times out failed
connection attempts. Very long-running commands delay subsequent hosts in the same group.

The task shows the script, files, ticket and observed outcomes. The same agent can
investigate a failed host or request a new measurement. Local tools use the
[local command policy](access.md#local-commands).

## Jenkins

The same executor can read Jenkins builds and start builds of configured jobs. Its
API token stays in the executor configuration; the application and models see only
server and job aliases, URLs, the account name and allowed parameter names.

```sh
sudo cp /etc/taskrail-executor/jenkins.json.example /etc/taskrail-executor/jenkins.json
sudoedit /etc/taskrail-executor/jenkins.json
sudo systemctl restart taskrail-executor.service
```

```json
{
  "ci": {
    "url": "https://jenkins.example.com",
    "username": "taskrail-bot",
    "token": "REPLACE_WITH_JENKINS_API_TOKEN",
    "jobs": {
      "shop-tests": {"path": "shop/tests", "parameters": ["BRANCH", "SUITE"]}
    }
  }
}
```

- `url`: the Jenkins base URL, `http` or `https`, without credentials.
- `username` and `token`: a Jenkins account and its API token (user menu, Security,
  API Token). Give that account only the permissions the listed jobs need.
- `jobs`: aliases agents use. `path` is the job's folder path as shown in its URL
  (`/job/shop/job/tests` is `shop/tests`). `parameters` lists the build parameters
  agents may set; an empty list means none. `approval` (optional) is `"root"` (the
  default: every build waits for your root approval) or `"none"`: you allow the job's
  builds in advance, so they start as soon as a stage requests them. Use `"none"` only
  for jobs that change nothing outside CI, such as test or lint jobs; keep deploy jobs
  on `"root"`.
- `ca_file` (optional): an absolute path under `/etc/taskrail-executor/` to the CA
  certificate of an internal Jenkins.

Keep the file `root:taskrail-executor`, mode `0640`; the installer enforces this.
Without `jenkins.json` Jenkins is not offered. If you use only Jenkins, set
`hosts.json` to `{}`.

Agents return `JENKINS_REQUEST` ([contract](contracts.md#executor-requests)):

| Operation | What it returns | Approval |
|---|---|---|
| `status` | Number, result, running state and timing of `"last"` or a numbered build | UI (covered by Allow all actions) |
| `console` | The last 32,000 bytes of the console log | UI (covered by Allow all actions) |
| `tests` | Pass, fail and skip counts with up to 100 failed cases | UI (covered by Allow all actions) |
| `build` | Starts one build, waits up to `timeout_seconds` for its result and console tail | Root; automatic for a job with `"approval": "none"` |

A job with `"approval": "none"` gets an executor ticket like any build, and the
executor approves it on submission against the same digest and identity checks; the
journal records it. Approve any other build in a terminal with the command the UI shows:
`sudo -k /usr/local/bin/taskrail-executor-approve TICKET_ID`. The helper shows
the server, job path, account and parameters. Requests never follow HTTP redirects
or use proxies, so the token is sent only to the configured URL. The application
account can ask the executor for reads directly; reads change nothing in Jenkins.
A build that is still queued at its timeout is `UNKNOWN` (Jenkins may still run it);
one still running is reported as failed with its current state. Builds are never
retried automatically.

## Scripts and Ansible

The action's `files` object snapshots UTF-8 files, including playbooks, roles,
inventories and included files. Paths must be relative and cannot escape the bundle.
Include the dependencies needed to reproduce the script.
The executor creates a private temporary directory on each SSH target, writes that
bundle, runs its script with `/bin/sh`, then removes that directory. Creation and
cleanup are part of the SSH transport. No bundle means the
script is passed directly to the remote shell.

Ansible can run **on a configured remote controller** where Ansible and its managed
host credentials already exist. Include the playbook and its non-secret dependencies
in the bundle and use an explicit inventory and arguments in the submitted script.
Ansible is not run locally under the credential-owning executor account. The SSH
inventory covers the controller connection, not every host reached by a playbook.
Review Ansible inventory, includes, roles, delegation and local actions together:
`--limit` is not a security boundary. A submitted script can affect other resources
reachable from its remote account; the executor is not a remote network sandbox.

## Interruption and evidence

A timeout, transport failure or daemon restart during execution yields `UNKNOWN`:
the remote process may still be running. No automatic replay or rollback occurs.
Inspect the server before a new request. Stopping a task saves its workflow checkpoint;
remote commands can continue running. Continue observes the same ticket and returns
any completed host results to the agent.

Run artifacts contain `remote-execution.json`, UI action cards and a report section. They
record targets, payload, statuses, exit codes and SSH output. Captured known
passwords are redacted, but arbitrary remote output can still contain other secrets:
do not request secret dumps. Server tickets remain in `/var/lib/taskrail-executor`, owned
by the executor; application history deletion does not delete them.

Action success means that the submitted command exited successfully; it does not
prove every acceptance criterion. A runtime criterion may be marked satisfied only
when a cited, observed output snapshot of a successful action establishes it and
independent review agrees; otherwise it stays deferred.

Diagnostics:

```sh
systemctl status taskrail-executor.socket taskrail-executor.service
sudo journalctl -u taskrail-executor.service
cd ~/.local/share/taskrail/current
python3 -m taskrail.executor catalog
python3 -m taskrail.executor status TICKET_ID
```

Run these from the installed release (as shown) or a source checkout so Python
finds the package. The command line only shows the catalog and ticket status; it has
no `submit`. Each workflow request has its own durable key. Resending it after a
lost response returns the existing ticket. A new agent message can request a fresh
measurement. The task receives a bounded preview with a path to the full evidence.
