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
| Source edit | opencode edit | Exact approved regular files; preserve user edits |
| Git history | `GIT_REQUEST` final response | Controlled executor; read-only for planning/review |
| Git mutation | `GIT_REQUEST` final response | Implementer, approved scope, bounded command grammar |
| Remote inspection/change | `ACTION_REQUEST` final response | Configured SSH targets; exact script root-approved; inspection only before you confirm a change, server checks after it; never the implementer |
| Jenkins | `JENKINS_REQUEST` final response | Configured jobs; reads approved in the UI, builds root-approved |
| Local checks | Built-in syntax checks (`.py`, `.json`, `.sh`; `.yml`/`.yaml` when PyYAML is importable); `LOCAL_REQUEST` for tests, linters or explicit Bash | Exact argv personally approved; runs as the application user |
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

The permission profile is not an OS sandbox. Search tools have pattern permissions,
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

## Local approval

All roles can request installed linters, tests and diagnostic commands. The exact
working directory, argv and reason appear in the UI before execution. Allow is
single-use; Deny skips execution; Alternative sends your text back to the agent.
Waiting has no expiry and is excluded from active stage time. Stop remains available.
Each decision is bound to a random ticket and retained for audit.

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

Everything else is asked as before. **Allow all
actions** ([task controls](task-controls.md)) approves this run's local commands, read
access and change limit automatically; it trusts every command the agents choose, so
use it only where you would allow them anyway. Inline shell or Python code that an
agent requests (`bash -c`, `sh -c`, `python -c` and the like, also behind `env`,
`timeout` or `xargs`) always waits for your personal decision: its code is not
checked by the command routes above. Configured checks from settings are not agent
requests and keep the normal rules.

Local commands use exec without implicit shell expansion and a host environment
without secret-shaped variables, provider keys included. Explicit Bash and project
code are trusted code, not sandboxed: they can have effects beyond their argv text.
Review scripts before allowing them. Direct Git/SSH/deployment commands use their
separate controlled routes. Source and Git integrity checks detect unexpected
changes but cannot undo side effects or enforce a sandbox around arbitrary code.
Planner/reviewer commands must inspect or verify, not fix source: `--fix`, `--write`,
in-place options and `sed -i` are rejected before approval. Files Git ignores (caches,
reports, build output) and common tool cache directories are not source and are never
fingerprinted. Other files a command changes are adopted into the run's source state,
recorded with the action, reported under **Changed by approved commands** and named to
the session; Git metadata changed by a command still stops the run.

SSH approval remains the separate root-only command; the web Allow button does not
authorize SSH tickets. Remote execution has its own timeout.
