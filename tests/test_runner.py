from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("runner", ROOT / "scripts" / "runner.py")
assert spec and spec.loader
runner: Any = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class RunnerLoopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name)
        self.old_paths = (runner.DATA_DIR, runner.RUNNER_STATE_PATH)
        runner.DATA_DIR = self.data_dir
        runner.RUNNER_STATE_PATH = self.data_dir / "runner-state.json"
        runner.init_goal("Deliver the OMH Management shared loop.", next_action="run next safe step")

    def tearDown(self) -> None:
        runner.DATA_DIR, runner.RUNNER_STATE_PATH = self.old_paths
        self.tmp.cleanup()

    def load(self) -> dict[str, Any]:
        return json.loads(runner.RUNNER_STATE_PATH.read_text(encoding="utf-8"))

    def test_two_workers_cannot_claim_same_next_action_before_lease_expires(self) -> None:
        first = runner.claim_next_action("bipani", lease_seconds=900)
        second = runner.claim_next_action("codingi", lease_seconds=900)

        self.assertTrue(first["claimed"])
        self.assertEqual(first["status"], "claimed")
        self.assertFalse(second["claimed"])
        self.assertEqual(second["status"], "leased")
        self.assertEqual(second["state"]["claimed_by"], "bipani")

    def test_lease_expiry_allows_next_worker_to_claim(self) -> None:
        runner.claim_next_action("bipani", lease_seconds=900)
        state = self.load()
        state["lease_expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        runner.write_state(state)

        second = runner.claim_next_action("codingi", lease_seconds=900)

        self.assertTrue(second["claimed"])
        self.assertEqual(second["state"]["claimed_by"], "codingi")

    def test_owner_approval_required_blocks_repeat_destructive_claim(self) -> None:
        claim = runner.claim_next_action("bipani", lease_seconds=900)
        runner.block_action(
            "bipani",
            lease_id=claim["lease_id"],
            blocked_by=runner.OWNER_APPROVAL_REQUIRED,
            observed_result="Hermes safety card reported user has NOT consented.",
        )

        retry = runner.claim_next_action("codingi", lease_seconds=900)

        self.assertFalse(retry["claimed"])
        self.assertEqual(retry["status"], "blocked")
        self.assertEqual(retry["reason"], runner.OWNER_APPROVAL_REQUIRED)
        self.assertEqual(retry["state"]["claimed_by"], "")

    def test_only_lease_owner_can_complete_action(self) -> None:
        claim = runner.claim_next_action("bipani", lease_seconds=900)

        with self.assertRaisesRegex(ValueError, "does not own"):
            runner.complete_action("codingi", lease_id=claim["lease_id"], observed_result="tried to complete")

        state = runner.complete_action(
            "bipani",
            lease_id=claim["lease_id"],
            observed_result="verified next safe step",
            next_action="brief room",
        )
        self.assertEqual(state["next_action"], "brief room")
        self.assertEqual(state["claimed_by"], "")
        self.assertEqual(len(state["completed_actions"]), 1)


if __name__ == "__main__":
    unittest.main()
