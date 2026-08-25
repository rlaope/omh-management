#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("OMH_MANAGEMENT_DATA_DIR", ROOT / "data"))
CANDIDATES_PATH = DATA_DIR / "sample-candidates.json"
AUDIT_PATH = DATA_DIR / "sample-audit-log.json"
BRIEFING_PATH = DATA_DIR / "sample-briefing-log.json"
SOURCE_STATE_PATH = DATA_DIR / "source-state.json"
TRIAGE_STATES = {"adopt", "watch", "ignore"}
FORBIDDEN_CREATE_SOURCES = {"cron", "scout", "daily_scout", "automation"}
CONFIRMATION = "CONFIRM_CREATE_GITHUB_ISSUE"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> Any:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_candidates() -> list[dict[str, Any]]:
    data = load_json(CANDIDATES_PATH)
    if not isinstance(data, list):
        raise ValueError("candidate store must be a JSON list")
    return data


def load_audit() -> list[dict[str, Any]]:
    data = load_json(AUDIT_PATH)
    if not isinstance(data, list):
        raise ValueError("audit store must be a JSON list")
    return data


def load_briefing() -> list[dict[str, Any]]:
    data = load_json(BRIEFING_PATH)
    if not isinstance(data, list):
        raise ValueError("briefing store must be a JSON list")
    return data


def find_candidate(candidate_id: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    candidates = load_candidates()
    for candidate in candidates:
        if candidate.get("candidate_id") == candidate_id:
            return candidates, candidate
    raise ValueError(f"candidate not found: {candidate_id}")


def append_audit(event_type: str, candidate_id: str, *, actor: str, details: dict[str, Any]) -> dict[str, Any]:
    audit = load_audit()
    event = {
        "schema_version": "audit_event/v1",
        "event_id": f"audit_{event_type}_{hashlib.sha256((candidate_id + utc_now()).encode()).hexdigest()[:12]}",
        "event_type": event_type,
        "actor": actor,
        "candidate_id": candidate_id,
        "recorded_at": utc_now(),
        "details": details,
    }
    audit.append(event)
    write_json(AUDIT_PATH, audit)
    return event


def append_briefing(
    stage: str,
    status: str,
    *,
    actor: str,
    next_action: str,
    blocked_by: list[str] | None = None,
    observed_result: str = "",
    candidate_id: str = "",
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    briefing = load_briefing()
    recorded_at = utc_now()
    event = {
        "schema_version": "briefing_event/v1",
        "event_id": f"briefing_{hashlib.sha256((stage + candidate_id + recorded_at).encode()).hexdigest()[:12]}",
        "stage": stage,
        "status": status,
        "actor": actor,
        "candidate_id": candidate_id,
        "recorded_at": recorded_at,
        "next_action": next_action,
        "blocked_by": blocked_by or [],
        "observed_result": observed_result,
        "details": details or {},
    }
    briefing.append(event)
    write_json(BRIEFING_PATH, briefing)
    return event


def dashboard_state() -> dict[str, Any]:
    candidates = load_candidates()
    audit = load_audit()
    briefing = load_briefing()
    last_briefing = briefing[-1] if briefing else {}
    return {
        "schema_version": "dashboard_state/v1",
        "candidate_count": len(candidates),
        "triage": {state: sum(1 for item in candidates if item.get("triage_state") == state) for state in sorted(TRIAGE_STATES)},
        "issue_candidates": sum(1 for item in candidates if item.get("issue_candidate")),
        "locally_observed": sum(1 for item in candidates if item.get("observed_evidence")),
        "audit_event_count": len(audit),
        "briefing_event_count": len(briefing),
        "current_stage": last_briefing.get("stage", "not_briefed"),
        "next_action": last_briefing.get("next_action", "run daily scout or review candidates"),
        "last_briefed_at": last_briefing.get("recorded_at", ""),
        "cleanup_status": "OMH repo cleanup: blocked_by destructive approval",
        "github_write_default": "disabled",
    }


def cmd_dashboard(_args: argparse.Namespace) -> int:
    payload = dashboard_state()
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def set_triage(candidate_id: str, state: str, *, actor: str) -> dict[str, Any]:
    if state not in TRIAGE_STATES:
        raise ValueError("invalid triage state")
    candidates, candidate = find_candidate(candidate_id)
    previous = str(candidate.get("triage_state", ""))
    candidate["triage_state"] = state
    write_json(CANDIDATES_PATH, candidates)
    event = append_audit(
        "triage_changed",
        candidate_id,
        actor=actor,
        details={"previous": previous, "next": state, "external_write": False},
    )
    return {"candidate": candidate, "audit_event": event}


def cmd_triage(args: argparse.Namespace) -> int:
    print(json.dumps({"ok": True, **set_triage(args.candidate_id, args.state, actor=args.actor)}, indent=2, sort_keys=True))
    return 0


def build_issue_preview(candidate: dict[str, Any]) -> dict[str, Any]:
    if not candidate.get("issue_candidate"):
        raise ValueError("candidate is not marked issue_candidate")
    draft_value = candidate.get("issue_draft")
    draft = draft_value if isinstance(draft_value, dict) else {}
    return {
        "schema_version": "issue_preview/v1",
        "candidate_id": candidate["candidate_id"],
        "title": draft.get("title", ""),
        "body": draft.get("body", ""),
        "dedupe_query": draft.get("dedupe_query", ""),
        "write_enabled": False,
        "required_before_create": ["dedupe_evidence", "owner_confirmation", "audit_event"],
    }


def issue_preview(candidate_id: str, *, actor: str) -> dict[str, Any]:
    _, candidate = find_candidate(candidate_id)
    preview = build_issue_preview(candidate)
    event = append_audit(
        "issue_previewed",
        candidate_id,
        actor=actor,
        details={"external_write": False, "dedupe_query": preview["dedupe_query"]},
    )
    return {"preview": preview, "audit_event": event}


def cmd_issue_preview(args: argparse.Namespace) -> int:
    print(json.dumps({"ok": True, **issue_preview(args.candidate_id, actor=args.actor)}, indent=2, sort_keys=True))
    return 0


def fetch_source(url: str) -> tuple[str, str]:
    request = Request(url, headers={"user-agent": "omh-management-scout/1.0"})
    with urlopen(request, timeout=20) as response:  # noqa: S310 - operator-supplied scout URL
        body = response.read(256_000).decode("utf-8", errors="replace")
        status = getattr(response, "status", 200)
    return body, f"HTTP {status} {url}"


def make_candidate_id(source_url: str, content_hash: str) -> str:
    digest = hashlib.sha256(f"{source_url}:{content_hash}".encode("utf-8")).hexdigest()[:12]
    return f"scout_{digest}"


def scout_run(
    *,
    source_url: str,
    source_name: str,
    target_surface: str,
    actor: str,
    title: str,
    user_facing_intent: str,
    changed_contract: str,
    issue_candidate: bool = False,
) -> dict[str, Any]:
    body, observed_result = fetch_source(source_url)
    content_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
    state = load_json(SOURCE_STATE_PATH)
    if not isinstance(state, dict):
        raise ValueError("source-state store must be a JSON object")
    previous_hash = state.get(source_url, {}).get("content_hash")
    state[source_url] = {"content_hash": content_hash, "checked_at": utc_now(), "source_name": source_name}
    write_json(SOURCE_STATE_PATH, state)

    changed = previous_hash != content_hash
    candidates = load_candidates()
    candidate_id = make_candidate_id(source_url, content_hash)
    card = {
        "schema_version": "scout_candidate/v1",
        "candidate_id": candidate_id,
        "title": title,
        "upstream_source": f"{source_name}: {source_url}",
        "source_date": utc_now()[:10],
        "evidence_type": "docs",
        "changed_contract": changed_contract,
        "user_facing_intent": user_facing_intent,
        "target_surface": target_surface,
        "prepared_vs_observed_impact": "Scout fetched upstream evidence and recorded a source hash; no local Hermes runtime behavior was observed.",
        "executor_neutrality_impact": "Candidate is executor-neutral until a specific OMH surface owner accepts implementation.",
        "triage_state": "watch",
        "implementation_status": "none",
        "observed_evidence": [],
        "blocked_by": [] if changed else ["source unchanged since last scout run"],
        "issue_candidate": issue_candidate,
        "issue_draft": {
            "title": title if issue_candidate else "",
            "body": f"## Upstream evidence\n- Source: {source_name}\n- URL: {source_url}\n- Content hash: {content_hash}\n\n## OMH Management mapping\n{changed_contract}\n\n## Boundary\nUpstream evidence only; not locally observed.",
            "dedupe_query": f"repo:rlaope/omh-management is:issue {title}",
        }
        if issue_candidate
        else {"title": "", "body": "", "dedupe_query": ""},
        "claim_boundary": "Daily scout evidence only; this is not implementation, review, CI, merge, or local runtime observation evidence.",
    }

    existing_index = next((index for index, item in enumerate(candidates) if item.get("candidate_id") == candidate_id), None)
    if existing_index is None:
        candidates.append(card)
        recorded = True
    else:
        candidates[existing_index] = card
        recorded = False
    write_json(CANDIDATES_PATH, candidates)
    audit_event = append_audit(
        "daily_scout_recorded",
        candidate_id,
        actor=actor,
        details={"external_write": False, "source_url": source_url, "content_hash": content_hash, "changed": changed, "recorded": recorded},
    )
    briefing_event = append_briefing(
        "daily_scout",
        "changed" if changed else "unchanged",
        actor=actor,
        candidate_id=candidate_id,
        next_action="review candidate in dashboard" if changed else "watch source until content changes",
        blocked_by=[] if changed else ["source unchanged since last scout run"],
        observed_result=observed_result,
        details={"briefing_events_are_not_evidence_events": True, "content_hash": content_hash},
    )
    return {"changed": changed, "recorded": recorded, "candidate": card, "audit_event": audit_event, "briefing_event": briefing_event}


def cmd_scout_run(args: argparse.Namespace) -> int:
    print(
        json.dumps(
            {
                "ok": True,
                **scout_run(
                    source_url=args.source_url,
                    source_name=args.source_name,
                    target_surface=args.target_surface,
                    actor=args.actor,
                    title=args.title,
                    user_facing_intent=args.user_facing_intent,
                    changed_contract=args.changed_contract,
                    issue_candidate=args.issue_candidate,
                ),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def run_gh_issue_create(repo: str, title: str, body: str) -> str:
    result = subprocess.run(
        ["gh", "issue", "create", "--repo", repo, "--title", title, "--body", body],
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip().splitlines()[-1]


def issue_create(
    candidate_id: str,
    *,
    repo: str,
    source: str,
    owner_confirmation: str,
    dedupe_evidence: str,
    actor: str,
    execute: bool = False,
) -> dict[str, Any]:
    normalized_source = source.strip().lower().replace("-", "_")
    if normalized_source in FORBIDDEN_CREATE_SOURCES:
        raise ValueError("GitHub issue creation is forbidden from cron/scout sources")
    if owner_confirmation != CONFIRMATION:
        raise ValueError(f"owner confirmation must be {CONFIRMATION}")
    if not dedupe_evidence.strip():
        raise ValueError("dedupe_evidence is required")
    if "/" not in repo:
        raise ValueError("repo must be OWNER/REPO")
    _, candidate = find_candidate(candidate_id)
    preview = build_issue_preview(candidate)
    details = {
        "repo": repo,
        "source": source,
        "dedupe_evidence_sha256": hashlib.sha256(dedupe_evidence.encode("utf-8")).hexdigest(),
        "external_write": bool(execute),
    }
    issue_url = ""
    attempt_event = append_audit(
        "github_issue_create_attempted" if execute else "github_issue_blocked",
        candidate_id,
        actor=actor,
        details={**details, "attempt_recorded_before_write": True},
    )
    if execute:
        issue_url = run_gh_issue_create(repo, preview["title"], preview["body"])
        event = append_audit("github_issue_created", candidate_id, actor=actor, details={**details, "issue_url": issue_url})
    else:
        event = attempt_event
    return {
        "dry_run": not execute,
        "created": bool(execute),
        "issue_url": issue_url,
        "preview": preview,
        "audit_event": event,
        "attempt_audit_event": attempt_event,
    }


def cmd_issue_create(args: argparse.Namespace) -> int:
    print(
        json.dumps(
            {
                "ok": True,
                **issue_create(
                    args.candidate_id,
                    repo=args.repo,
                    source=args.source,
                    owner_confirmation=args.owner_confirmation,
                    dedupe_evidence=args.dedupe_evidence,
                    actor=args.actor,
                    execute=args.execute,
                ),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage local OMH Management scout candidates.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("dashboard").set_defaults(func=cmd_dashboard)

    scout = sub.add_parser("scout-run", help="Fetch one upstream source and record a no-write candidate plus briefing event.")
    scout.add_argument("--source-url", required=True)
    scout.add_argument("--source-name", default="Hermes upstream")
    scout.add_argument("--target-surface", default="dashboard")
    scout.add_argument("--title", required=True)
    scout.add_argument("--changed-contract", required=True)
    scout.add_argument("--user-facing-intent", required=True)
    scout.add_argument("--issue-candidate", action="store_true")
    scout.add_argument("--actor", default="daily-scout")
    scout.set_defaults(func=cmd_scout_run)

    triage = sub.add_parser("triage")
    triage.add_argument("candidate_id")
    triage.add_argument("--state", choices=sorted(TRIAGE_STATES), required=True)
    triage.add_argument("--actor", default="operator")
    triage.set_defaults(func=cmd_triage)

    preview = sub.add_parser("issue-preview")
    preview.add_argument("candidate_id")
    preview.add_argument("--actor", default="operator")
    preview.set_defaults(func=cmd_issue_preview)

    create = sub.add_parser("issue-create")
    create.add_argument("candidate_id")
    create.add_argument("--repo", required=True)
    create.add_argument("--source", choices=("dashboard", "operator_cli", "cron", "scout"), default="operator_cli")
    create.add_argument("--owner-confirmation", default="")
    create.add_argument("--dedupe-evidence", default="")
    create.add_argument("--actor", default="operator")
    create.add_argument("--execute", action="store_true")
    create.set_defaults(func=cmd_issue_create)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
