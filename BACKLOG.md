# Backlog

Ideas that are agreed in principle but not scheduled. Each entry says why it is not
done yet.

## Read-only server inspection without approval

Collecting data from servers without changing their state is safe for the services,
so it could run without a root approval, like Jenkins builds of jobs configured with
`"approval": "none"`. It is not done because reading can still leak secrets into the
model context and the provider (`sudo cat` of credential files, container environment
variables, configuration with tokens).

A safe version needs the executor itself, not the application, to enforce it:

- only one command from the existing read-only list, with literal arguments;
- a root-configured deny list of secret paths and commands (for example `/etc/shadow`,
  `*.env`, `docker inspect` of environment variables), refused before a ticket exists;
- optional redaction of secret-shaped values in returned output;
- a per-host opt-in in `hosts.json`, so root decides which servers allow it.

Until then every SSH action, including inspection, waits for root approval.
