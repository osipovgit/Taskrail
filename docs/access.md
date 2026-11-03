# Access and executor routes

`access.json` and the runtime profile share one input manifest: canonical project,
task, source, recovery and executor paths. Each role writes only its designated
artifact; approved implementers may also edit source. Declared roots grant scope,
not OS privileges or authentication. Native permission errors return to the agent
without stopping the turn or creating a read-grant prompt. The agent corrects its
path or uses an allowed source; it reports a gap if required evidence is inaccessible.

## Protected paths

Protected files are never read or edited by a model: the profile denies them after
every allowance, read-only requests refuse them, and the project map,
source packets and source views leave them out. `.env` and `.env.*` are always
protected. The `protected_paths` setting lists the other patterns; its default is:

```json
[".git/config", "*.pem", "*.key", "id_rsa*", "id_ed25519*", ".vault_pass*",
 "*vault-password*", ".npmrc", ".pypirc", ".netrc"]
```

Patterns apply at every depth; `*` and `?` are wildcards and `*` matches `/`.
A configured list replaces defaults. Continue retains frozen protection and adds new
patterns. Planned edits also exclude VCS metadata, tool state, credentials and
generated dependencies; [deployment](deployment.md) owns configuration details.

| Operation | Route | Boundary |
|---|---|---|
| Source read/search | opencode read/glob/grep (and list in 1.x) | Declared roots; never search their parents |
| Source edit | opencode edit | Exact approved regular files; in an authenticated owned worktree the whole roots except Git metadata and protected files; preserve user edits |
| Git history | `GIT_REQUEST` final response | Controlled executor; read-only for planning/review |
| Git mutation | `GIT_REQUEST` final response | Implementer, approved scope, bounded command grammar |
| Remote inspection/change | `ACTION_REQUEST` final response | Configured SSH targets; exact script root-approved; inspection only before you confirm a change, server checks after it; never the implementer |
| Jenkins | `JENKINS_REQUEST` final response | Configured jobs; reads automatically approved, builds root-approved unless root configured the job with `approval: none` |
| Local checks | Built-in syntax checks; `LOCAL_REQUEST` for tests, linters or Bash. [Deployment](deployment.md) documents available parsers | [Sandbox](#local-commands) without a decision; on the host only after approval |
| HTTP/API/database tools | No direct connector | Approved SSH scripts may use installed remote clients |

Executor JSON responses and turn rules are defined in [contracts](contracts.md#executor-requests).
Requests are not execution proof. Internal indexes are not model inputs; use supplied
source/recovery files and executor snapshots.

The permission profile is not an OS sandbox. Search permissions are pattern-based,
and Git reads can inspect the underlying repository when a root is a subdirectory.
Agents must not use either route to bypass scope or protected-file rules. Hostile
project content and untrusted local users require stronger isolation.

SSH needs separate installation, verified hosts and root approval; it inherits no
SSH agent/config or remote sudo. Stop ends observation, not necessarily remote work.
Git network operations use their separately authorized noninteractive transport.
See [SSH executor](ssh-executor.md) and [Git access](git-access.md).

## Local commands

All roles can request installed linters, tests and diagnostic commands with
`LOCAL_REQUEST`. Where [bubblewrap](deployment.md#local-command-sandbox) works, every
request runs at once in a sandbox, without a decision, and is recorded in the
approval ledger with `"rule": "sandbox"`:

- the host system is read-only; `/tmp`, `/var/tmp` and `/run` are private and empty;
- home is scratch space; only required runtime components and supported tool caches
  are mounted read-only, including language managers, Maven/Gradle/Cargo caches and
  Ansible collections. Package-manager configuration and unrelated home files stay hidden;
- mandatory credential masks apply after all mounts, including roots, tool prefixes
  and aliases. They cover SSH/cloud/provider credentials and package/Git authentication.
  Protected patterns add masks but cannot remove them. Arbitrarily named secrets need
  explicit patterns. Directory identities cache mask discovery between commands;
- a declared project's ordinary `.config` files, including linter configuration,
  remain readable. Credential patterns still apply inside them; aliases into the
  user's `~/.config` and runtime/cache `.config` directories remain private;
- the implementer's roots are writable; a reading stage's roots take writes that
  vanish when the command ends (bubblewrap 0.10 or later), else they are read-only;
  Git metadata is always read-only and [protected files](#protected-paths) are unreadable;
- network isolation uses namespaces or a seccomp fallback; `sandbox_network: true`
  explicitly keeps the network. Credentials stay masked. The fallback permits Unix
  sockets, including host abstract sockets; graphical-session variables are unset.
  [Deployment](deployment.md#local-command-sandbox) describes these limits.


`"sandbox": false` requests host execution. Without working bubblewrap, commands also
use the host route (`rule: host`); `host_commands: "ask"` requires approval there.
`taskrail check` and `local-preflight.json` report the effective boundary and tool paths.
Required tools are checked before model work and again after recipe selection;
missing tools stop before execution. Install and Continue, or fix the check and Restart.
Configured checks share the sandbox and may not change source. Required Linux CI
exercises real isolation and cannot pass by skipping an unavailable sandbox.

### Approval

Reads outside the declared roots wait for a decision; so do host commands under
`host_commands: "ask"`. The exact working directory, argv and reason appear in the UI
before execution.
Allow is single-use; Deny skips execution; Alternative sends your text back to the
agent. Waiting has no expiry and is excluded from active stage time. Stop remains
available. Each decision is bound to a random ticket and retained for audit.

Read-only source requests, Jenkins reads and bounded built-in listings are recorded
without asking. Host listings allow `ls`, `find`, `du`, `stat`, `wc`, `cat`, `head`,
`tail` and `grep` only with the explicit read grammar, canonical in-root operands and
fixed system executables. Options precede operands; `--color=value` is explicit.
Unknown flags, link following, recursive or continuous content reads require approval.
`find` permits only name/path/type/depth tests and printing. The executor rechecks
scope immediately before execution. Remote inspection uses its own bounded grammar.

**Allow all actions** approves local commands, including inline code.
Inline-code cards identify scripts and interpreter wrappers whose effects cannot be
inferred from argv. This grant never authorizes Git pushes or changes root-only remote
approval. The task badge and Stop allowing all actions button expose the durable grant.

Personal **Allow all actions** card grants survive Continue and appear in Restart
drafts. A linked split/delivery child refreshes the family grant before each decision,
including when it was already running when the operator granted it. Parent membership
must match the server's recorded task or phase attempt; a claimed parent in task text
alone grants nothing. Revoking a parent overrides copied child flags. Previously
revoked workers stay revoked until a fresh personal decision restores them.

Host commands use exec and a filtered environment, without implicit shell expansion.
Explicit scripts remain trusted host code. Integrity checks detect unexpected changes
but cannot undo side effects.

### Every local command

Direct Git/SSH/deployment commands use their separate controlled routes.
Planner/reviewer commands must inspect or verify, not fix source: `--fix`, `--write`,
in-place options and `sed -i` are rejected before they run. Files Git ignores (caches,
reports, build output) and common tool cache directories are not source and are never
fingerprinted. Other files a command changes are adopted into the run's source state,
recorded with the action, reported under **Changed by approved commands** and named to
the session; Git metadata changed by a command still stops the run.

Remote execution retains its separate timeout and root-only approval.
