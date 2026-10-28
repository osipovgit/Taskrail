# Access and executor routes

The current attempt's `access.json` is the model input manifest. It is generated
from the same input list as the runtime profile. Read canonical absolute paths:
project roots, listed task/history/preimages/results/recovery inputs and executor snapshots.
Only the approved implementer paths with the implementer's `progress.md`, and the
planner's `plan.md`, are editable by their respective roles. Source roots are declarations of
scope, not OS privileges; Unix permissions, network routing and authentication still apply.

## Protected paths

Protected files are never read or edited by a model: the profile denies them after
every allowance, read-only requests and read grants refuse them, and the project map,
source packets and source views leave them out. `.env` and `.env.*` are always
protected. The `protected_paths` setting lists the other patterns; its default is:

```json
[".git/config", "*.pem", "*.key", "id_rsa*", "id_ed25519*", ".vault_pass*",
 "*vault-password*", ".npmrc", ".pypirc", ".netrc"]
```

An entry matches that path at a root and below any directory. `*` and `?` are the
only wildcards, and `*` also matches `/`, as in opencode rules. Setting the key
replaces the default list, so copy the entries you want to keep. The effective list
is frozen in `00-input/settings.json`; Continue keeps it and adds entries configured
since. The same patterns apply to planned edits. Plans also never edit `.git`,
`.hg`, `.svn`, `.opencode`, `.ssh`, `.kube`, `.env*` or generated dependency
folders.

| Operation | Route | Boundary |
|---|---|---|
| Source read/search | opencode read/glob/grep (and list in 1.x) | Declared roots; never search their parents |
| Source edit | opencode edit | Exact approved regular files; on a `taskrail/` branch the whole roots except Git metadata and protected files; preserve user edits |
| Git history | `GIT_REQUEST` final response | Controlled executor; read-only for planning/review |
| Git mutation | `GIT_REQUEST` final response | Implementer, approved scope, bounded command grammar |
| Remote inspection/change | `ACTION_REQUEST` final response | Configured SSH targets; exact script root-approved; inspection only before you confirm a change, server checks after it; never the implementer |
| Jenkins | `JENKINS_REQUEST` final response | Configured jobs; reads automatically approved, builds root-approved unless root configured the job with `approval: none` |
| Local checks | Built-in syntax checks (`.py`, `.json`, `.sh`; `.yml`/`.yaml` with PyYAML from the service's Python, a system `python3` or Taskrail's own package directory, safe composer only; `taskrail check` names which); `LOCAL_REQUEST` for tests, linters or explicit Bash | [Sandbox](#local-commands) without a decision; on the host only after approval |
| HTTP/API/database tools | No direct connector | Approved SSH scripts may use installed remote clients |

Executor requests are JSON **assistant responses**, not function calls. End the
turn after emitting one. Their absence from the model's tool list is normal. The
server executes the request or waits for approval, then resumes the same opencode
session with `--session`. The UI records these as tool calls inside one stage, not
as additional stages. The advertised contracts include executor requests and the
role's final result: a Markdown plan followed by `DONE` for the planner, JSON for
other roles. Continuations and result repair retain that role's format.

Internal `evidence.json`, `observations.json` and `00-input/git-metadata.json` are
not model inputs. The latter contains integrity hashes, not commit history. Reuse
the supplied recovery input instead of opening indexes/logs. Git outputs are in
`00-input/git/`; SSH ticket snapshots are in `00-input/ssh/`. Read a snapshot before
citing its lines. A request is not execution proof; UNKNOWN cannot be retried blindly.

An exploratory missing file or invalid line offset is a warning, not proof of a
source fact. Correct the path/range. Final evidence validation still rejects invented
or unobserved quotations. Required unresolved evidence remains BLOCKED. Permission
denials open a decision card. Allow grants only read/search access inside declared
roots; Deny or Alternative returns feedback in the same session. Protected scopes
and edit grants are never broadened automatically.

The permission profile is not an OS sandbox; only local commands run in one. Search tools have pattern permissions,
not a per-file content filter; do not use them to access protected files. Git read
commands currently operate on the underlying repository, including when a declared
root is a subdirectory. Do not use Git to bypass source scope or protected-file
rules. These instruction constraints are not equivalent to a filesystem/network
sandbox. Do not treat it as safe for hostile project content or untrusted local users.
Mechanically identical content restrictions across these routes would require one
broker for all source, search and Git operations.

The SSH executor requires its separate installation, socket access, configured
inventory, password or key authentication and verified host keys. It does not inherit SSH
agents/config or grant remote sudo. Stop pauses observation; it does not prove the
remote process stopped. Git network operations use their separate noninteractive
transport and do not use the SSH ticket approval flow. Only request them when the
task explicitly authorizes them. See Git and SSH documentation for supported syntax.

## Local commands

All roles can request installed linters, tests and diagnostic commands with
`LOCAL_REQUEST`. Where [bubblewrap](deployment.md#local-command-sandbox) works, every
request runs at once in a sandbox, without a decision, and is recorded in the
approval ledger with `"rule": "sandbox"`:

- the host system is read-only; `/tmp`, `/var/tmp` and `/run` are private and empty;
- home is an empty scratch directory showing, read-only, only its visible entries,
  known toolchain directories (`~/.local/bin`, `~/.local/lib`, pipx, uv, pyenv, nvm,
  cargo, rustup, SDKMAN, Maven, Gradle, Ansible collections and roles, and the like)
  and the prefix of the requested program, such as its virtual environment; hidden
  credentials such as `~/.ssh`, `~/.config` or `~/.local/share` stay out of reach;
- the implementer's roots are writable; a reading stage's roots take writes that
  vanish when the command ends (bubblewrap 0.10 or later), else they are read-only;
  Git metadata is always read-only and [protected files](#protected-paths) are unreadable;
- there is no network: a private network namespace where the host allows one, else a
  seccomp filter that refuses every socket but Unix and netlink ones. Abstract Unix
  sockets of the host, such as an X server's, stay reachable in that case;
  `DISPLAY`, `WAYLAND_DISPLAY`, `XAUTHORITY` and `DBUS_SESSION_BUS_ADDRESS` are unset.

A command that needs the network or host files outside the sandbox adds
`"sandbox": false` and says why in its reason. It then goes through the approval below,
as does every command on a host without a working bubblewrap and a program that is
not installed, so you can install it and allow the command. `taskrail check` names
the sandbox in use. Configured checks from settings run in the same sandbox with
writable roots; the source guard still stops a check that changes source.

### Approval

The exact working directory, argv and reason appear in the UI before execution.
Allow is single-use; Deny skips execution; Alternative sends your text back to the
agent. Waiting has no expiry and is excluded from active stage time. Stop remains
available. Each decision is bound to a random ticket and retained for audit.

Read-only requests are approved without asking and recorded in the same ledger with
`"rule": "read_only"`:

- reads and searches of canonical paths inside the declared roots, except
  [protected files](#protected-paths);
- Jenkins status, console and test reads;
- `ls`, `find`, `du`, `stat`, `wc`, `cat`, `head`, `tail` and `grep` when the program is
  named without a path, its working directory and path operands resolve inside a
  declared root and are not protected files, and every option belongs to its explicit
  read grammar. Pattern and option values are parsed separately from paths. Unknown
  flags, link following, recursive content reads and continuous reads require approval.
  Local options must precede operands, so environment-dependent option permutation
  cannot hide a path. Optional `--color` values use the `--color=value` form.
  Automatically approved listings resolve executables from the fixed system search
  path and recheck the read scope immediately before execution.
  `find` accepts only name/path/type/depth tests and printing; `--` does not bypass
  predicate validation. The same bounded grammar protects remote inspection before
  change confirmation, with additional explicit remote diagnostic options.

Everything else is asked. **Allow all actions** ([task controls](task-controls.md))
approves this run's local commands, read access and change limit automatically; it
trusts every command the agents choose, so use it only where you would allow them
anyway, inline shell or Python code included. Without it, the card of inline code that
an agent requests (`bash -c`, `sh -c`, `python -c` and the like, also behind `env`,
`timeout` or `xargs`, with unknown interpreter options or `env --split-string`) says so:
its code is not checked by the command routes above, so read the whole script.

Commands run on the host use exec without implicit shell expansion and a host
environment without secret-shaped variables, provider keys included. Explicit Bash
and project code are trusted code there, not sandboxed: they can have effects beyond
their argv text. Review scripts before allowing them. Source and Git integrity checks
detect unexpected changes but cannot undo side effects.

### Every local command

Direct Git/SSH/deployment commands use their separate controlled routes.
Planner/reviewer commands must inspect or verify, not fix source: `--fix`, `--write`,
in-place options and `sed -i` are rejected before they run. Files Git ignores (caches,
reports, build output) and common tool cache directories are not source and are never
fingerprinted. Other files a command changes are adopted into the run's source state,
recorded with the action, reported under **Changed by approved commands** and named to
the session; Git metadata changed by a command still stops the run.

SSH approval remains the separate root-only command; the web Allow button does not
authorize SSH tickets. Remote execution has its own timeout.
