# Repository administration

Use this checklist after the authorized history migration. These settings must be
saved in GitHub; committing this document does not enable them. Keep the repository
private until historical GitHub data has been checked as well as Git branches.

## 1. Set the merge method

Open the repository's **Settings > General > Pull Requests**.

| Setting | Value | Effect |
|---|---|---|
| Allow squash merging | On | Each accepted PR adds one commit to master; the PR retains the discussion and individual commits. |
| Allow merge commits | Off | Prevents two-parent commits and keeps the main history linear. |
| Allow rebase merging | Off initially | Keeps one predictable merge method; enable only if preserving every feature commit becomes a deliberate policy. |
| Allow auto-merge | Off | A green pipeline cannot merge a PR without the owner's final action. |
| Automatically delete head branches | On | Removes merged feature branches, reducing stale branch clutter. |

Before squash merging, edit the resulting commit title and description to explain
the final change. Keep PRs focused, include tests and documentation with their code,
and update the branch after master changes. Do not add release narratives to guides.

## 2. Protect master

Open **Settings > Rules > Rulesets > New ruleset > New branch ruleset**.
Name it `master-protection`, set enforcement to **Active**, and target the exact
branch `master`. Leave the bypass list empty, including for administrators and bots.
Rulesets for a private personal repository require an eligible paid plan; public
repositories support them on GitHub Free.

| Rule | Value | Meaning and trade-off |
|---|---|---|
| Require a pull request | On | Every code, documentation and dependency change has a reviewable PR; direct pushes are rejected. |
| Require conversation resolution | On | Outstanding review threads must be resolved before merging. Resolution alone is not approval. |
| Require linear history | On | Rejects merge commits; squash merging remains available. |
| Restrict deletions | On | Protects master from accidental deletion. |
| Block force pushes | On | Prevents replacing published history during normal development. |
| Require status checks | On | Select `CI gate` and `Security gate`, with GitHub Actions as their expected source. |
| Require branches to be up to date | On | Checks must cover the current base; concurrent changes may require updating the PR and running CI again. |
| Restrict updates | Off | Turning this on would reserve all updates for bypass actors, including ordinary PR merges. |
| Require deployments | Off | There is no deployment gate for this source repository. An absent required deployment would block every PR. |
| Require merge queue | Off | Not needed for the current scale; enabling it also requires workflows handling `merge_group`. |
| Require signed commits | Optional, later | Enable only after every contributor and bot can produce accepted signatures. It verifies identity, not correctness or review. |
| Require coverage results | Off | Coverage remains an explicitly requested diagnostic; no automatic threshold is configured. |

Select the check names only after they have appeared on a real GitHub run.
`CI gate` combines lint/format, all supported Python versions, UI regressions and
the real CLI permission check. `Security gate` requires both CodeQL languages in a
public repository. It explicitly permits unavailable scanning while private.
A successful upload does not prove there are no findings: once CodeQL is available,
also configure **Require code scanning results**, select CodeQL, and block security
findings of high or critical severity; review lower severities separately.

Do not make skipped scenario acceptance, coverage or live-provider runs required:
they are optional and run only when explicitly requested. Never substitute a green
run on an older commit for the current revision.

## 3. Make the owner's review enforceable

`.github/CODEOWNERS` names `@osipovgit` for every file. The owner must keep write
access for code-owner requirements to work. Review workflow and CODEOWNERS edits
especially carefully: they can change what future checks and reviews mean.

For PRs authored by another account, including a separate automation account:

| Review setting | Value | Effect |
|---|---|---|
| Required approvals | 1 | A PR cannot merge without an accepted review. |
| Require code-owner review | On | An unrelated reviewer cannot replace the owner's approval. |
| Dismiss stale approvals | On | A new diff invalidates an earlier approval. |
| Require approval of the most recent push | On when authors and owner are separate | Prevents the last pusher from being the sole approver; the owner must not push the final change and then approve it alone. |
| Review dismissal restrictions | Owner only, where available | Other writers cannot erase a blocking review. |

GitHub does not let an author approve their own PR. If the owner also authors PRs,
choose one explicit operating model:

- Preferred for enforced owner approval: a separate account authors the PR; the
  owner reviews it using the settings above, then merges manually.
- Single-account maintenance: keep the owner as the only human with write access,
  use zero required approvals and no required code-owner approval, keep all CI
  gates and PR requirements, and merge manually after inspection. CODEOWNERS still
  documents ownership. This model relies on the owner's discipline for review.

The second model does not cryptographically distinguish the owner from an agent
using the owner's credential. Do not give agents merge-capable credentials, and
do not add other writers while relying on that model. A separate GitHub App with
narrow permissions is preferable to sharing a personal token. Repository rules
cannot prevent their administrator from deliberately changing the rules.

## 4. Limit Actions permissions and storage

Open **Settings > Actions > General**.

| Setting | Recommended value | Effect |
|---|---|---|
| Allowed actions | Selected actions; allow the GitHub-owned actions used here | Limits third-party workflow code. Keep `actions/checkout`, `actions/setup-python`, `actions/setup-node` and `github/codeql-action` available. |
| Require full-length action SHAs | On | Keeps action code immutable until a reviewed pin update; the workflows already use verified SHAs. |
| Default workflow permissions | Read repository contents and packages | Reduces the token's default authority. Explicit job permissions still need review; CodeQL needs security-events write. |
| Allow Actions to create and approve PRs | Off | Prevents workflow-generated approvals and unneeded PR automation. |
| Outside collaborator workflow approval | Require approval for all outside collaborators | An untrusted fork cannot immediately spend runner resources or execute submitted workflow code. Inspect changes before approving. |
| Retention | 30 days | Bounds future check/run/log/artifact retention; old objects need separate cleanup. |
| Cache retention and size | Keep defaults initially | Avoid increasing storage or cost without measured need. |

Use GitHub-hosted runners for public contributions. Never expose a personal
self-hosted runner, provider credentials or deployment secrets to untrusted code.
Do not use `pull_request_target` to check out and execute an untrusted PR.
Pin updates remain reviewable Dependabot PRs, grouped by ecosystem.

## 5. Enable security features

In **Settings > Code security** (or **Security > Settings**, depending on the UI),
enable the dependency graph, Dependabot alerts/security updates, secret scanning,
push protection and private vulnerability reporting where the account supports them.
The repository already has a custom CodeQL workflow; use advanced setup rather than
creating a duplicate default analysis.

Secret scanning detects supported credential patterns, not every private project
name or business detail. Inspect diffs, sample configuration, test fixtures and
uploaded logs before publication. Keep machine-specific settings outside Git or in
an untracked exclude file. Do not place private names in tracked ignore rules.

## 6. Remove obsolete Actions runs

In **Actions**, inspect all workflows, including retired ones. Keep queued/running
jobs, the latest master runs and the latest runs of open PRs. For an obsolete
completed run, open its menu, choose **Delete workflow run**, and confirm only after
checking its revision. Deletion permanently removes its logs and associated artifacts.

For a confidentiality cleanup, an old run is not safe merely because it belongs to
an open PR. If it contains private material or references the removed history,
close/recreate the affected PR against clean history, delete the contaminated
run, and obtain fresh validation on the clean revision before publication.

For larger inventories, authenticate GitHub CLI locally; do not paste a token into
chat. These read-only commands include every page:

```sh
gh auth status
gh api --paginate 'repos/osipovgit/Taskrail/actions/runs?per_page=100' \
  --jq '.workflow_runs[] | [.id, .name, .status, .conclusion, .head_sha, .html_url] | @tsv'
gh api --paginate 'repos/osipovgit/Taskrail/pulls?state=open&per_page=100' \
  --jq '.[] | [.number, .head.sha, .base.ref] | @tsv'
gh api --paginate 'repos/osipovgit/Taskrail/actions/artifacts?per_page=100' \
  --jq '.artifacts[] | [.id, .name, .workflow_run.head_sha, .expired] | @tsv'
```

After selecting and rechecking one obsolete run, delete only its exact ID with
`gh run delete RUN_ID --repo osipovgit/Taskrail`. Do not pipe the unfiltered inventory
into a deletion loop. Re-list runs and artifacts afterward. Inspect **Actions >
Caches** separately; deleting runs does not constitute a cache audit.

## 7. Verify publication readiness

History rewriting does not erase GitHub's read-only PR refs, cached commit pages,
old workflow data, releases or other clones. Inspect these while still private.
For eligible sensitive data, request removal of affected PR refs and cached views
through GitHub Support. Support can decline removal of non-sensitive material; if
those references cannot be cleared, keep the original private and publish the
verified clean history in a new repository. Do not expose the old repository by
changing its visibility prematurely.

After rewriting, use a fresh clone for normal development. Never merge an old clone
back into the cleaned history. Before enabling public access, verify:

1. All published branch and tag histories contain no private material or merge commits.
2. Current required GitHub checks pass and the owner has inspected the final diff.
3. Master rejects direct writes, failed checks and stale reviews under the chosen review model.
4. Historic PR data, Actions artifacts/logs/caches and releases have been handled.
5. The new clone has no private working files or credentials staged for publication.

## References

- [Ruleset creation and availability](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/creating-rulesets-for-a-repository)
- [Rule behavior](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets)
- [Required reviews and self-review](https://docs.github.com/en/pull-requests/how-tos/review-pull-requests/approving-a-pull-request-with-required-reviews)
- [Actions settings](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository)
- [Workflow deletion](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/delete-a-workflow-run)
- [Sensitive history removal](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)
