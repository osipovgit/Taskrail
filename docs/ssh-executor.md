# Isolated SSH executor

The optional executor runs as the dedicated Linux account `countersign-executor`.
Countersign can submit an exact action and observe its result. Only root can approve it.
The web application and model never receive SSH passwords or the approval right.

## Install and configure

Use a trusted extracted release. Install the normal application as your usual user,
then install the executor separately:

```sh
bash deploy/install.sh --wait=3600 --autostart=keep
sudo bash deploy/install-executor.sh --client="$USER" --autostart=enable
sudoedit /etc/countersign-executor/hosts.json
sudoedit /etc/countersign-executor/known_hosts
sudo systemctl start countersign-executor.service
```

`--autostart=enable|disable|keep` is explicit and never prompts. Enabled means system
boot, independently of user login. Updates preserve credentials, host keys and
queued tickets. The installer refuses to update while a ticket is RUNNING, stops
the service, installs trusted code and leaves startup to the explicit command above.

Log out and back in after first installation so your account inherits the
`countersign-executor-clients` group, then restart the user application service.
If the user systemd manager remains alive through logout (lingering), reboot once
to refresh its groups. Never add the Countersign account to the private
`countersign-executor` group or give it passwordless sudo.

Inventory format (replace the example before starting):

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

Credentials and host keys belong to `root:countersign-executor`, mode `0640`, inside a
`0750` directory. Obtain and verify host keys through a trusted channel before
adding them to `known_hosts`; the executor never accepts unknown keys automatically.
For nonstandard ports use OpenSSH's `[hostname]:port` known-hosts notation.
After editing an existing inventory, restart the executor when no actions are
running; inventory changes are loaded at service startup.
Password authentication is supported; key authentication and remote sudo password
handling are not implemented. Choose the remote account's permissions deliberately.

## Use from a task

Specify target **aliases**, the goal, expected checks and constraints. Do not put
passwords in task text or project files. With the service installed, stage prompts
include the available aliases and the `ACTION_REQUEST` contract. The agent can
request a script plus a text-file bundle. Every remote action, including inspection,
waits for personal approval. Direct shell tools remain disabled.

The UI shows the exact script, bundled files, connection targets and ticket ID.
Review them, then run the command displayed by the UI:

```sh
sudo -k /usr/local/bin/countersign-executor-approve TICKET_ID
# To reject an incorrect request:
sudo -k /usr/local/bin/countersign-executor-approve --reject TICKET_ID
```

The helper displays the immutable request and requires its full digest. There is
no `--yes` option and no approval endpoint usable by the application account.
Approval covers one exact script, bundle and set of SSH targets. Changing them
requires a new ticket and approval. This protects executor-owned credentials;
it does not sandbox your local account or override any other SSH/root access it
already has. Protection depends on the OS account separation and your sudo policy.

Once approved, targets execute sequentially. On the first failure, remaining targets
are not executed. Results return to the same stage, which may request a separate
verification action or finish its report. Each additional action needs approval.
Continuation turns remain inside one stage and session; waiting itself does
not consume model tokens. This executor adds controlled **remote** execution; local
commands use the separate `LOCAL_REQUEST` approval in the UI.

## Scripts and Ansible

The action's `files` object snapshots UTF-8 files, including playbooks, roles,
inventories and included files. Paths must be relative and cannot escape the bundle.
Review all dependencies; do not rely on unreviewed downloads or mutable remote files.
The executor creates a private temporary directory on each SSH target, writes that
bundle, runs its script with `/bin/sh`, then removes that directory. Creation and
cleanup are part of the displayed, approved transport script. No bundle means the
script is passed directly to the remote shell.

Ansible can run **on a configured remote controller** where Ansible and its managed
host credentials already exist. Include the playbook and its non-secret dependencies
in the bundle and use an explicit inventory and arguments in the approved script.
Ansible is not run locally under the credential-owning executor account. The SSH
inventory covers the controller connection, not every host reached by a playbook.
Review Ansible inventory, includes, roles, delegation and local actions together:
`--limit` is not a security boundary. An approved script can affect other resources
reachable from its remote account; the executor is not a remote network sandbox.

## Interruption and evidence

A timeout, transport failure or daemon restart during execution yields `UNKNOWN`:
the remote process may still be running. No automatic replay or rollback occurs.
Inspect the server before a new request. Stopping a task saves its workflow checkpoint;
it does **not** cancel an already approved remote command. Continue observes the
same ticket instead of submitting it again. Rejection stops the workflow for revision.

Run artifacts contain `execution.json`, UI action cards and a report section. They
record targets, payload, approval digest, statuses and bounded output. Captured known
passwords are redacted, but arbitrary remote output can still contain other secrets:
do not request secret dumps. Server tickets remain in `/var/lib/countersign-executor`, owned
by the executor; application history deletion does not delete them.

Action success means that the submitted command exited successfully; it does not
prove every acceptance criterion. A runtime criterion may be marked satisfied only
when a quoted, observed output snapshot of a successful action establishes it and
independent review agrees; otherwise it stays deferred.

Diagnostics:

```sh
sudo systemctl status countersign-executor.service
sudo journalctl -u countersign-executor.service
cd ~/.local/share/countersign/current
python3 -m countersign.executor catalog
python3 -m countersign.executor status TICKET_ID
```

Run these from the installed release (as shown) or a source checkout so Python
finds the package. For a manual request use
`python3 -m countersign.executor submit ACTION.json --key=UNIQUE_KEY`. Repeating the
same key and payload returns the same job without replay. Limits: 16 targets, 200
text files, 512 KiB request, 3600 seconds per target, and the last 32,000 bytes of
output per target. Binary bundles are not supported.
