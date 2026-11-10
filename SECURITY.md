# Security policy

Taskrail runs coding agents against local projects and can relay approved
commands to remote hosts, so security reports are welcome and handled privately.

## Reporting a vulnerability

Report suspected vulnerabilities through GitHub's private vulnerability reporting
(**Security → Report a vulnerability** on the repository). Never open a public
issue, pull request or discussion for a suspected vulnerability. Include the
affected version or commit, the configuration involved, reproduction steps and the
impact you observed. Redact secrets, tokens and private source from logs.

The maintainer reviews reports privately. Confirmed issues are fixed on
`master` and disclosed once a fixed release is available.

## Supported versions

Only the latest release and `master` receive security fixes.

## Scope and trust model

Read [access routes](docs/access.md) before deployment. In short:

- The web UI binds to `127.0.0.1` and is not a public or multi-user service.
- opencode permission profiles are policy, not an operating-system sandbox. Project
  code executed by local commands runs under the configured sandbox or host policy.
- Local commands receive a filtered environment. The opencode process also receives
  the allowlisted provider variables and any explicit `agent_env_allow` additions.
- SSH actions require root approval of the exact request digest. Jenkins uses
  the same executor and its per-job build approval settings.

Reports that depend on running hostile project content, granting an untrusted local
user access to your account, or approving a malicious command are outside this
model, but documentation improvements for them are still welcome.
