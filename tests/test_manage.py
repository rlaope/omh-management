from __future__ import annotations

import json
import tempfile
import unittest
import importlib.util
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("manage", ROOT / "scripts" / "manage.py")
assert spec and spec.loader
manage: Any = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manage)


BASE_CANDIDATE = {
    "schema_version": "scout_candidate/v1",
    "candidate_id": "candidate_one",
    "title": "Candidate one",
    "upstream_source": "test",
    "source_date": "2026-08-25",
    "evidence_type": "docs",
    "changed_contract": "A changed upstream contract.",
    "user_facing_intent": "Show a safer operation.",
    "target_surface": "dashboard",
    "prepared_vs_observed_impact": "upstream evidence only",
    "executor_neutrality_impact": "executor-neutral",
    "triage_state": "watch",
    "implementation_status": "none",
    "observed_evidence": [],
    "blocked_by": [],
    "issue_candidate": True,
    "issue_draft": {
        "title": "Candidate issue",
        "body": "Issue body",
        "dedupe_query": "repo:rlaope/omh-management is:issue Candidate issue",
    },
    "claim_boundary": "not locally observed",
}


class ManageBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        data = Path(self.tmp.name)
        self.old_paths = (
            manage.DATA_DIR,
            manage.CANDIDATES_PATH,
            manage.AUDIT_PATH,
            manage.BRIEFING_PATH,
            manage.SOURCE_STATE_PATH,
        )
        manage.DATA_DIR = data
        manage.CANDIDATES_PATH = data / "sample-candidates.json"
        manage.AUDIT_PATH = data / "sample-audit-log.json"
        manage.BRIEFING_PATH = data / "sample-briefing-log.json"
        manage.SOURCE_STATE_PATH = data / "source-state.json"
        self.write_json(manage.CANDIDATES_PATH, [BASE_CANDIDATE.copy()])
        self.write_json(manage.AUDIT_PATH, [])
        self.write_json(manage.BRIEFING_PATH, [])
        self.write_json(manage.SOURCE_STATE_PATH, {})

    def tearDown(self) -> None:
        (
            manage.DATA_DIR,
            manage.CANDIDATES_PATH,
            manage.AUDIT_PATH,
            manage.BRIEFING_PATH,
            manage.SOURCE_STATE_PATH,
        ) = self.old_paths
        self.tmp.cleanup()

    def write_json(self, path: Path, payload) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def test_cron_source_cannot_create_issue(self) -> None:
        with self.assertRaisesRegex(ValueError, "forbidden from cron/scout"):
            manage.issue_create(
                "candidate_one",
                repo="rlaope/omh-management",
                source="cron",
                owner_confirmation=manage.CONFIRMATION,
                dedupe_evidence="no duplicates",
                actor="test",
            )

    def test_create_requires_confirmation_and_dedupe(self) -> None:
        with self.assertRaisesRegex(ValueError, "owner confirmation"):
            manage.issue_create(
                "candidate_one",
                repo="rlaope/omh-management",
                source="dashboard",
                owner_confirmation="",
                dedupe_evidence="no duplicates",
                actor="test",
            )
        with self.assertRaisesRegex(ValueError, "dedupe_evidence"):
            manage.issue_create(
                "candidate_one",
                repo="rlaope/omh-management",
                source="dashboard",
                owner_confirmation=manage.CONFIRMATION,
                dedupe_evidence="",
                actor="test",
            )

    def test_dry_run_create_writes_audit_without_external_write(self) -> None:
        result = manage.issue_create(
            "candidate_one",
            repo="rlaope/omh-management",
            source="dashboard",
            owner_confirmation=manage.CONFIRMATION,
            dedupe_evidence="no duplicates",
            actor="test",
        )
        self.assertFalse(result["created"])
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["audit_event"]["event_type"], "github_issue_blocked")
        self.assertFalse(result["audit_event"]["details"]["external_write"])

    def test_scout_run_records_candidate_audit_and_briefing_without_observed_runtime_claim(self) -> None:
        with mock.patch.object(manage, "fetch_source", return_value=("docs body", "HTTP 200 file://docs")):
            result = manage.scout_run(
                source_url="file://docs",
                source_name="Hermes docs",
                target_surface="dashboard",
                actor="daily-scout",
                title="Docs changed",
                user_facing_intent="Review new Hermes docs.",
                changed_contract="Docs changed and need action mapping.",
                issue_candidate=True,
            )
        self.assertTrue(result["recorded"])
        self.assertEqual(result["audit_event"]["event_type"], "daily_scout_recorded")
        self.assertEqual(result["briefing_event"]["stage"], "daily_scout")
        self.assertEqual(result["candidate"]["observed_evidence"], [])
        self.assertIn("no local Hermes runtime behavior", result["candidate"]["prepared_vs_observed_impact"])


if __name__ == "__main__":
    unittest.main()
