# OMH Management

![Oh My Hermes special force bots managing OMH](assets/oh-my-hermes-special-force.png)

**오마이헤르메스 특공대 봇들이 관리해요.**

Separate ops console for Hermes/OMH ecosystem intelligence.

## Current artifact

This repository starts with a local persisted dashboard MVP. It can review sample scout candidates, persist triage changes, show blocked cleanup state, preview issue drafts, dry-run the confirmed issue gate, and display audit events. It does not modify OMH.

The second pass adds the first operating loop: a no-write `scout-run` command records upstream evidence as candidate cards, briefing events are stored separately from audit/evidence events, and the dashboard exposes both dry-run and explicit confirmed GitHub issue paths behind dedupe + owner confirmation gates.

## Run locally

```sh
python3 scripts/server.py
# open http://127.0.0.1:4174/dashboard/index.html
```

Opening `dashboard/index.html` directly still works as static preview mode, but persisted triage and API-backed issue previews require `scripts/server.py`.

## Validate

```sh
python3 scripts/validate.py
```

## Exercise the local issue gate

```sh
python3 scripts/manage.py dashboard
python3 scripts/manage.py scout-run \
  --source-url https://hermes-agent.nousresearch.com/docs \
  --source-name "Hermes docs" \
  --target-surface dashboard \
  --title "Review Hermes docs changes for OMH Management" \
  --changed-contract "Scout fetched upstream docs and recorded a source hash for operator review." \
  --user-facing-intent "Show daily Hermes learning candidates in the management console." \
  --issue-candidate
python3 scripts/manage.py triage scout_cron_no_writes --state adopt
python3 scripts/manage.py issue-preview scout_hermes_delegate_resume
python3 scripts/manage.py issue-create scout_hermes_delegate_resume --repo rlaope/oh-my-hermes --source dashboard
python3 scripts/manage.py issue-create scout_hermes_delegate_resume \
  --repo rlaope/oh-my-hermes \
  --source dashboard \
  --owner-confirmation CONFIRM_CREATE_GITHUB_ISSUE \
  --dedupe-evidence "gh issue list found no duplicate"
```

The first `issue-create` call must reject. The second remains a dry run unless `--execute` is added.

The dashboard's `Confirmed GitHub create` button still requires persisted API mode, dedupe evidence, the exact `CONFIRM_CREATE_GITHUB_ISSUE` phrase, and a final browser confirmation before the backend can call `gh issue create`.

## Safety boundary

- Cron/scout paths have no external writes.
- Dashboard issue raising dry-runs by default.
- Real issue creation must require preview, dedupe evidence, owner confirmation, audit logging, and an explicit backend `execute` path.
- OMH repo cleanup remains a separate blocked status until destructive cleanup approval is observed.
