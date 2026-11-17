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
before the executor handles its first request. Install Ansible Core in the controller
environment used by the Taskrail application (Debian/Ubuntu: `sudo apt install ansible-core`).
The executor's private static YAML catalog uses system PyYAML. Project inventories
supply their own targets. SSH remembers new hosts automatically on first use.

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

The first SSH action uses `ssh-keyscan` to obtain a new destination's public
keys and saves them under `/var/lib/taskrail-executor/host-keys/`. OpenSSH
verifies the server against these keys before sending credentials or commands.
Aliases and logins for the same address and port share the record. Later
connections use the saved keys. A different server key blocks the connection.
The initial scan trusts the network path to the destination.

Administrator pins in `/etc/taskrail-executor/known_hosts` take precedence
and skip first-use enrollment. To preconfigure an identity or authorize a
legitimate rotation, verify the new fingerprint through a trusted channel
and update this file with `sudoedit`. Match the resolved address for port 22
or `[address]:port` for other ports. Private configuration files belong to
`root:taskrail-executor`, mode `0640`, inside a `0750` directory.

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

Name the inventory file or directory and group in the task. Use an absolute path
or a path relative to the project root; quote names containing spaces. For example:

```sh
taskrail submit --mode discussion --root project=/path/to/repo \
  --goal "Inspect the workers group in /path/to/repo/inventory/cluster.yaml. Report disk usage, CPU load and running services on each host."
```

Taskrail runs `ansible-inventory -i SOURCE --list` as the application
user in the source directory (the parent for a file) and selects the exact group
from the resolved membership graph. The installed Ansible
handles YAML, INI, directories, host ranges, group and host variables, executable
inventories and installed inventory plugins. Dynamic sources can execute project
code and contact their providers during discovery. Use trusted inventory sources
and provide their dependencies and credentials in the application environment.
Taskrail maps an agent's worktree path back to the original checkout before
running Ansible. Child tasks inherit the operator's source selections. For YAML
files found during research that the operator did not name, the executor can
inspect static groups and literal inline variables without executing project code.

Ansible discovers a colocated `ansible.cfg` or uses `ANSIBLE_CONFIG` from the
application environment. The explicit source takes precedence over the default
inventory. If your playbook script already exports these variables, check the
same source from that shell:

```sh
taskrail check --ssh --inventory-file "$ANSIBLE_INVENTORY" --inventory-group k8s
```

This prints selected aliases. Taskrail tests SSH connectivity on the first SSH
action. Login-shell exports apply to the CLI invocation; a running systemd user
service has its own environment.

The application sends only SSH connection variables over the private executor
socket. The executor validates them and keeps the resolved targets in memory.
The model receives aliases and recorded action results. Ansible stdout, stderr
and connection passwords stay out of run files and tickets. A missing field or
unsupported SSH option is reported by name. The transport uses direct OpenSSH
with first-use or administrator-pinned host keys and requires a resolved username and password. Host
variables override configured `remote_user` and `remote_port` defaults; port
defaults to 22. A connection field still containing a template after inventory
resolution cannot be used. Ansible connection plugins, proxy commands and project
key files are outside the direct password transport.

A fresh inventory lookup refreshes the selection. Catalog reads and SSH actions
reuse the frozen targets without invoking the dynamic source again. A changed
source file, a replaced binding or an executor restart can require another lookup
before a new action. An existing ticket remains observable by its original key.
Directory sources and external variables take effect on the next explicit lookup.

Taskrail masks recognized inventory credential files before capturing the
worktree, including staged and committed versions, and protects adjacent
`host_vars` and `group_vars` directories. Use `protected_paths` for additional
project-specific secrets. Administrators can also publish static YAML files with
inline SSH variables in `/etc/taskrail-executor/inventories` for checks by filename.

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
