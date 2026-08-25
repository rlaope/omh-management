#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
CANDIDATES_PATH = DATA_DIR / "sample-candidates.json"
AUDIT_PATH = DATA_DIR / "sample-audit-log.json"
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


def dashboard_state() -> dict[str, Any]:
    candidates = load_candidates()
    audit = load_audit()
    return {
        "schema_version": "dashboard_state/v1",
        "candidate_count": len(candidates),
        "triage": {state: sum(1 for item in candidates if item.get("triage_state") == state) for state in sorted(TRIAGE_STATES)},
        "issue_candidates": sum(1 for item in candidates if item.get("issue_candidate")),
        "locally_observed": sum(1 for item in candidates if item.get("observed_evidence")),
        "audit_event_count": len(audit),
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
    if execute:
        issue_url = run_gh_issue_create(repo, preview["title"], preview["body"])
    event = append_audit("github_issue_created" if execute else "github_issue_blocked", candidate_id, actor=actor, details=details)
    return {"dry_run": not execute, "created": bool(execute), "issue_url": issue_url, "preview": preview, "audit_event": event}


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
