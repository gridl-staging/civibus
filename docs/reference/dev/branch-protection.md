# Branch Protection Runbook (`main`)

This runbook defines the manual GitHub branch-protection settings for `main`.
It keeps merge-gate settings aligned with workflow source-of-truth files instead of duplicating CI logic.

## Security Review Findings (2026-03-19)

- `[medium][resolved] workflow-missing-token-permissions`:
  `.github/workflows/ci.yml` and `.github/workflows/integration.yml` previously relied on repository-default token permissions.
  Remediation: set explicit least-privilege `permissions: contents: read` in both workflows and lock it with workflow contract tests.
- `[medium][resolved] missing-branch-protection-runbook`:
  branch-protection settings for `main` were not documented, which risks drift in required-check policy.
  Remediation: this runbook plus `tests/ci/test_branch_protection_doc_contract.py` now define and verify the PR-check vs push-only split.

## Source Of Truth

- PR merge-gate workflow: `.github/workflows/ci.yml`
- Post-merge verification workflow: `.github/workflows/integration.yml`
- Contract guards for stable job names and commands:
  - `tests/ci/test_ci_workflow_contract.py`
  - `tests/ci/test_integration_workflow_contract.py`

Current PR-required checks from `.github/workflows/ci.yml`: `lint`, `unit-tests`, `web`
PR-capable checks from `.github/workflows/integration.yml`: `integration-tests`

`integration-tests` must not be declared required until a mirror PR run establishes its real check context and Stage 4 probes branch protection.

## Required GitHub Rule Settings For `main`

Set these in GitHub Settings -> Branches -> `main`:

1. Require a pull request before merging: enabled.
2. Require status checks to pass before merging: enabled.
3. Required status checks: select the current checks from `.github/workflows/ci.yml` (`lint`, `unit-tests`, `web`).
4. Require branches to be up to date before merging: enabled.
5. Require conversation resolution before merging: enabled.
6. Allow force pushes: disabled unless there is an explicit repository exception.
7. Allow deletions: disabled unless there is an explicit repository exception.

## Manual Application Steps

1. Open GitHub Settings -> Branches.
2. Edit or create the branch-protection rule for `main`.
3. Enable the rule settings listed above.
4. In required status checks, select only checks derived from `.github/workflows/ci.yml`.
5. Confirm `integration-tests` is not selected as a merge blocker yet; the workflow is PR-capable, but the required-check context must be proven by a mirror PR run and Stage 4 protection probes first.

## Repo-Specific Deviations

- 2026-03-19: Live `main` branch-rule comparison completed against repository `gridl-dev/civibus_dev`.
  GitHub currently exposes no branch-protection rule for `main` (`branchProtectionRules` query returns an empty list),
  and branch-protection REST/ruleset endpoints return HTTP 403 `Upgrade to GitHub Pro or make this repository public to enable this feature`.
  Impact: the policy defined in this runbook is the target state, but enforcement in this private repository is blocked by GitHub plan limits until the repository is made public or moved to a plan that supports branch protection.
