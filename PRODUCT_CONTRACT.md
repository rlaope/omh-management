# OMH Management Product Contract

## Product Identity

`omh-management` is a separate ops console for managing Hermes and OMH ecosystem intelligence. It observes Hermes Agent and OMH upstream/project signals, turns them into candidate cards, supports operator briefings, and gates approved GitHub issue raising.

It is not an OMH core feature and must not patch, fork, or silently extend OMH.

## Name

The canonical repository and product name is `omh-management`.

## Operating Boundary

- Observes: Hermes Agent docs/releases/repo changes, OMH repo state, local investigation results, candidate queues, briefing/audit events.
- Does not patch: OMH repository source, Hermes Agent core, Hermes transport/runtime internals, user profile configuration.
- Does not execute hidden work: no coding dispatch, no external writes, and no GitHub issue creation from cron/scout paths.
- Default mode: local, metadata-first, reviewable, and safe to inspect.

## Core Workflow

1. Daily scout cron reads upstream evidence and emits action-mapping candidates.
2. Operators review candidates in the dashboard.
3. Candidates move through `adopt`, `watch`, or `ignore` triage states.
4. Issue candidates can render a GitHub issue preview and dedupe query.
5. GitHub issue creation is allowed only after preview, dedupe evidence, owner confirmation, and audit logging.
6. Briefing/status views summarize scout freshness, blocked items, investigation state, and issue-raising readiness.

## Data Contracts

### Scout Candidate

Required fields:

- `schema_version: scout_candidate/v1`
- `candidate_id`
- `upstream_source`
- `source_date`
- `evidence_type: docs | code | release | runtime_observed`
- `changed_contract`
- `user_facing_intent`
- `target_surface`
- `prepared_vs_observed_impact`
- `executor_neutrality_impact`
- `triage_state: adopt | watch | ignore`
- `implementation_status: none | prepared | applied | locally_verified`
- `observed_evidence[]`
- `blocked_by[]`
- `issue_candidate: true | false`
- `issue_draft`
- `claim_boundary`

Empty `observed_evidence` means upstream evidence only / not locally observed.

### Observed Evidence

Observed evidence entries must be structured:

- `command`
- `source`
- `result`
- `timestamp`

A briefing note is not observed evidence unless it cites a concrete observed evidence entry.

### Briefing Event

Briefing events report progress to users/operators. They may summarize work but must not imply verification or external writes.

Required distinction:

- `briefing_events != evidence_events`
- `status_message != verified_result`

### Audit Event

Audit events record operator actions and write attempts.

Required for:

- triage state changes
- issue preview creation
- dedupe checks
- owner confirmations
- GitHub issue creation attempts and results

## GitHub Write Policy

Default:

- `no_external_writes: true`
- `github_write_intent: forbidden`

Allowed GitHub issue path:

1. `issue_preview` is generated.
2. `dedupe_query` is run or supplied.
3. `dedupe_evidence` is attached.
4. Owner confirms the write explicitly.
5. `audit_event` is persisted.
6. Only then may `gh issue create` run.

Forbidden paths:

- cron-triggered issue creation
- scout-triggered issue creation
- issue creation without dedupe evidence
- issue creation without owner confirmation
- issue creation without audit logging

## Dashboard Acceptance Bar

The first usable dashboard must show:

- scout freshness
- candidate list
- triage state controls
- blocked-by reasons
- observed/not-observed boundary
- issue preview readiness
- dedupe/confirmation gate state
- audit log summary

## Cron Acceptance Bar

The daily cron must:

- collect or accept upstream evidence references
- produce action-mapping candidates only
- never create GitHub issues
- never modify OMH source
- never claim local runtime observation without structured evidence
- emit a short briefing event after each run

## Non-goals

- Building an OMH internal dashboard command inside `oh-my-hermes`.
- Automatically raising GitHub issues from daily scout output.
- Treating upstream docs/code changes as locally observed Hermes runtime behavior.
- Replacing Hermes Agent, OMH, or GitHub project management.

## Current Cleanup Note

An earlier implementation attempt placed upstream scout code in the OMH repo. That work is out of scope for OMH core and must be removed after destructive cleanup approval. Until cleanup is observed, reports must keep these states separate:

- `OMH repo cleanup: blocked_by destructive approval`
- `omh-management contract: initialized`
