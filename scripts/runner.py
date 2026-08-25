#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - non-Unix fallback
    fcntl = None

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("OMH_MANAGEMENT_DATA_DIR", ROOT / "data"))
RUNNER_STATE_PATH = DATA_DIR / "runner-state.json"
OWNER_APPROVAL_REQUIRED = "owner_approval_required"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_time(value: str) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def default_state() -> dict[str, Any]:
    return {
        "schema_version": "runner_state/v1",
        "goal": "Keep OMH Management running until candidate review, safe issue raising, and loop briefing are operational.",
        "stage": "initialized",
        "next_action": "review dashboard state and claim next safe action",
        "claimed_by": "",
        "lease_id": "",
        "lease_expires_at": "",
        "observed_result": "",
        "blocked_by": [],
        "briefing_due": True,
        "completed_actions": [],
        "updated_at": utc_now(),
        "claim_boundary": "Runner state coordinates workers; it is not implementation, verification, GitHub write, or OMH repo cleanup evidence by itself.",
    }


def load_state() -> dict[str, Any]:
    if not RUNNER_STATE_PATH.exists():
        return default_state()
    state = json.loads(RUNNER_STATE_PATH.read_text(encoding="utf-8"))
    if not isinstance(state, dict):
        raise ValueError("runner state must be a JSON object")
    return state


def write_state(state: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = utc_now()
    RUNNER_STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


@contextmanager
def locked_state() -> Iterator[dict[str, Any]]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = RUNNER_STATE_PATH.with_suffix(".lock")
    with lock_path.open("a+", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield load_state()
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def init_goal(goal: str, *, next_action: str, stage: str = "goal_set") -> dict[str, Any]:
    if not goal.strip():
        raise ValueError("goal is required")
    if not next_action.strip():
        raise ValueError("next_action is required")
    state = default_state()
    state["goal"] = goal.strip()
    state["next_action"] = next_action.strip()
    state["stage"] = stage.strip() or "goal_set"
    write_state(state)
    return state


def is_lease_active(state: dict[str, Any], *, now: datetime | None = None) -> bool:
    expires = parse_time(str(state.get("lease_expires_at", "")))
    return bool(state.get("claimed_by") and expires and expires > (now or datetime.now(timezone.utc)))


def claim_next_action(worker: str, *, lease_seconds: int = 900, now: datetime | None = None) -> dict[str, Any]:
    if not worker.strip():
        raise ValueError("worker is required")
    current_time = now or datetime.now(timezone.utc)
    with locked_state() as state:
        blocked_by = list(state.get("blocked_by", []))
        if OWNER_APPROVAL_REQUIRED in blocked_by:
            return {"claimed": False, "status": "blocked", "reason": OWNER_APPROVAL_REQUIRED, "state": state}
        if not str(state.get("next_action", "")).strip():
            return {"claimed": False, "status": "complete", "reason": "no_next_action", "state": state}
        if is_lease_active(state, now=current_time):
            return {"claimed": False, "status": "leased", "reason": "lease_active", "state": state}
        lease_id = hashlib.sha256(f"{worker}:{state.get('next_action')}:{utc_now()}".encode()).hexdigest()[:16]
        state["claimed_by"] = worker.strip()
        state["lease_id"] = lease_id
        state["lease_expires_at"] = (current_time + timedelta(seconds=max(1, lease_seconds))).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        state["briefing_due"] = True
        write_state(state)
        return {"claimed": True, "status": "claimed", "lease_id": lease_id, "state": state}


def complete_action(worker: str, *, observed_result: str, next_action: str = "", stage: str = "", lease_id: str = "") -> dict[str, Any]:
    if not observed_result.strip():
        raise ValueError("observed_result is required")
    with locked_state() as state:
        _require_claim_owner(state, worker=worker, lease_id=lease_id)
        completed = list(state.get("completed_actions", []))
        completed.append(
            {
                "worker": worker,
                "lease_id": state.get("lease_id", ""),
                "action": state.get("next_action", ""),
                "observed_result": observed_result.strip(),
                "completed_at": utc_now(),
            }
        )
        state["completed_actions"] = completed
        state["observed_result"] = observed_result.strip()
        state["next_action"] = next_action.strip()
        state["stage"] = stage.strip() or ("completed" if not next_action.strip() else "next_action_ready")
        state["claimed_by"] = ""
        state["lease_id"] = ""
        state["lease_expires_at"] = ""
        state["blocked_by"] = []
        state["briefing_due"] = True
        write_state(state)
        return state


def block_action(worker: str, *, blocked_by: str, observed_result: str = "", lease_id: str = "") -> dict[str, Any]:
    if not blocked_by.strip():
        raise ValueError("blocked_by is required")
    with locked_state() as state:
        _require_claim_owner(state, worker=worker, lease_id=lease_id)
        blockers = list(state.get("blocked_by", []))
        if blocked_by not in blockers:
            blockers.append(blocked_by.strip())
        state["blocked_by"] = blockers
        state["observed_result"] = observed_result.strip()
        state["stage"] = "blocked"
        state["claimed_by"] = ""
        state["lease_id"] = ""
        state["lease_expires_at"] = ""
        state["briefing_due"] = True
        write_state(state)
        return state


def _require_claim_owner(state: dict[str, Any], *, worker: str, lease_id: str = "") -> None:
    if state.get("claimed_by") != worker:
        raise ValueError("worker does not own the current lease")
    if lease_id and state.get("lease_id") != lease_id:
        raise ValueError("lease_id does not match current lease")


def cmd_status(_args: argparse.Namespace) -> int:
    print(json.dumps({"ok": True, "state": load_state()}, indent=2, sort_keys=True))
    return 0


def cmd_goal(args: argparse.Namespace) -> int:
    print(json.dumps({"ok": True, "state": init_goal(args.goal, next_action=args.next_action, stage=args.stage)}, indent=2, sort_keys=True))
    return 0


def cmd_claim(args: argparse.Namespace) -> int:
    print(json.dumps({"ok": True, **claim_next_action(args.worker, lease_seconds=args.lease_seconds)}, indent=2, sort_keys=True))
    return 0


def cmd_complete(args: argparse.Namespace) -> int:
    print(
        json.dumps(
            {"ok": True, "state": complete_action(args.worker, observed_result=args.observed_result, next_action=args.next_action, stage=args.stage, lease_id=args.lease_id)},
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def cmd_block(args: argparse.Namespace) -> int:
    print(json.dumps({"ok": True, "state": block_action(args.worker, blocked_by=args.blocked_by, observed_result=args.observed_result, lease_id=args.lease_id)}, indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the OMH Management shared goal loop state.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status").set_defaults(func=cmd_status)
    goal = sub.add_parser("goal")
    goal.add_argument("goal")
    goal.add_argument("--next-action", required=True)
    goal.add_argument("--stage", default="goal_set")
    goal.set_defaults(func=cmd_goal)
    claim = sub.add_parser("claim")
    claim.add_argument("--worker", required=True)
    claim.add_argument("--lease-seconds", type=int, default=900)
    claim.set_defaults(func=cmd_claim)
    complete = sub.add_parser("complete")
    complete.add_argument("--worker", required=True)
    complete.add_argument("--lease-id", default="")
    complete.add_argument("--observed-result", required=True)
    complete.add_argument("--next-action", default="")
    complete.add_argument("--stage", default="")
    complete.set_defaults(func=cmd_complete)
    block = sub.add_parser("block")
    block.add_argument("--worker", required=True)
    block.add_argument("--lease-id", default="")
    block.add_argument("--blocked-by", required=True)
    block.add_argument("--observed-result", default="")
    block.set_defaults(func=cmd_block)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except (OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
