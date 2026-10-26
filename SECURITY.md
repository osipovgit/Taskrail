# Security policy

Taskrail runs coding agents against local projects and can relay approved
commands to remote hosts, so security reports are welcome and handled privately.

## Reporting a vulnerability

Report suspected vulnerabilities through GitHub's private vulnerability reporting
(**Security → Report a vulnerability** on the repository). Never open a public
issue, pull request or discussion for a suspected vulnerability. Include the
affected version or commit, the configuration involved, reproduction steps and the
impact you observed. Redact secrets, tokens and private source from logs.

You will get an acknowledgement within seven days. Confirmed issues are fixed on
the main branch and disclosed in the release notes once a fixed release exists.

## Supported versions

Only the latest release and the main branch receive security fixes.

## Scope and trust model

Read [access routes](docs/access.md) before deployment. In short:

- The web UI binds to `127.0.0.1` and is not a public or multi-user service.
- opencode permission profiles are policy, not an operating-system sandbox. Project
  code you approve to run is trusted code.
- Agents and approved local commands receive no secret-shaped environment
  variables; only opencode keeps provider keys that it needs.
- Remote actions run only through the separate SSH executor after root approval of
  the exact request digest.

Reports that depend on running hostile project content, granting an untrusted local
user access to your account, or approving a malicious command are outside this
model, but documentation improvements for them are still welcome.
