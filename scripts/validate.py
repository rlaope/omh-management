#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CANDIDATE_REQUIRED = {
    "schema_version",
    "candidate_id",
    "title",
    "upstream_source",
    "source_date",
    "evidence_type",
    "changed_contract",
    "user_facing_intent",
    "target_surface",
    "prepared_vs_observed_impact",
    "executor_neutrality_impact",
    "triage_state",
    "implementation_status",
    "observed_evidence",
    "blocked_by",
    "issue_candidate",
    "issue_draft",
    "claim_boundary",
}
AUDIT_REQUIRED = {"schema_version", "event_id", "event_type", "actor", "candidate_id", "recorded_at", "details"}


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def validate_candidate(item: dict) -> list[str]:
    errors: list[str] = []
    missing = sorted(CANDIDATE_REQUIRED - set(item))
    if missing:
        errors.append(f"{item.get('candidate_id', 'unknown')}: missing {', '.join(missing)}")
    if item.get("schema_version") != "scout_candidate/v1":
        errors.append(f"{item.get('candidate_id', 'unknown')}: invalid schema_version")
    if item.get("triage_state") not in {"adopt", "watch", "ignore"}:
        errors.append(f"{item.get('candidate_id', 'unknown')}: invalid triage_state")
    if item.get("implementation_status") not in {"none", "prepared", "applied", "locally_verified"}:
        errors.append(f"{item.get('candidate_id', 'unknown')}: invalid implementation_status")
    for evidence in item.get("observed_evidence", []):
        missing_evidence = {"command", "source", "result", "timestamp"} - set(evidence)
        if missing_evidence:
            errors.append(f"{item.get('candidate_id', 'unknown')}: observed_evidence missing {', '.join(sorted(missing_evidence))}")
    if item.get("issue_candidate") and not item.get("issue_draft", {}).get("dedupe_query"):
        errors.append(f"{item.get('candidate_id', 'unknown')}: issue candidate missing dedupe_query")
    return errors


def validate_audit_event(item: dict) -> list[str]:
    errors: list[str] = []
    missing = sorted(AUDIT_REQUIRED - set(item))
    if missing:
        errors.append(f"{item.get('event_id', 'unknown')}: missing {', '.join(missing)}")
    if item.get("schema_version") != "audit_event/v1":
        errors.append(f"{item.get('event_id', 'unknown')}: invalid schema_version")
    return errors


def main() -> int:
    errors: list[str] = []
    candidates = load_json(ROOT / "data" / "sample-candidates.json")
    audit = load_json(ROOT / "data" / "sample-audit-log.json")
    for item in candidates:
        errors.extend(validate_candidate(item))
    for item in audit:
        errors.extend(validate_audit_event(item))

    required_files = [
        ROOT / "PRODUCT_CONTRACT.md",
        ROOT / "README.md",
        ROOT / "dashboard" / "index.html",
        ROOT / "dashboard" / "styles.css",
        ROOT / "dashboard" / "app.js",
    ]
    for path in required_files:
        if not path.exists():
            errors.append(f"missing file: {path.relative_to(ROOT)}")

    if errors:
        print(json.dumps({"ok": False, "errors": errors}, indent=2))
        return 1
    print(json.dumps({"ok": True, "candidate_count": len(candidates), "audit_event_count": len(audit)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
