#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import manage
import runner

ROOT = Path(__file__).resolve().parents[1]


class ManagementHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            if path == "/api/dashboard":
                return self._json(manage.dashboard_state())
            if path == "/api/candidates":
                return self._json({"ok": True, "candidates": manage.load_candidates()})
            if path == "/api/audit":
                return self._json({"ok": True, "audit": manage.load_audit()})
            if path == "/api/briefing":
                return self._json({"ok": True, "briefing": manage.load_briefing()})
            if path == "/api/runner":
                return self._json({"ok": True, "state": runner.load_state()})
            return super().do_GET()
        except Exception as exc:  # pragma: no cover - network error surface
            return self._json({"ok": False, "error": str(exc)}, status=500)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            payload = self._read_payload()
            if path == "/api/triage":
                result = manage.set_triage(
                    str(payload.get("candidate_id", "")),
                    str(payload.get("state", "")),
                    actor=str(payload.get("actor", "dashboard")),
                )
                return self._json({"ok": True, **result})
            if path == "/api/issue-preview":
                result = manage.issue_preview(str(payload.get("candidate_id", "")), actor=str(payload.get("actor", "dashboard")))
                return self._json({"ok": True, **result})
            if path == "/api/issue-create":
                result = manage.issue_create(
                    str(payload.get("candidate_id", "")),
                    repo=str(payload.get("repo", "")),
                    source=str(payload.get("source", "dashboard")),
                    owner_confirmation=str(payload.get("owner_confirmation", "")),
                    dedupe_evidence=str(payload.get("dedupe_evidence", "")),
                    actor=str(payload.get("actor", "dashboard")),
                    execute=bool(payload.get("execute", False)),
                )
                return self._json({"ok": True, **result})
            if path == "/api/runner/goal":
                state = runner.init_goal(
                    str(payload.get("goal", "")),
                    next_action=str(payload.get("next_action", "")),
                    stage=str(payload.get("stage", "goal_set")),
                )
                return self._json({"ok": True, "state": state})
            if path == "/api/runner/claim":
                result = runner.claim_next_action(
                    str(payload.get("worker", "")),
                    lease_seconds=int(payload.get("lease_seconds", 900) or 900),
                )
                return self._json({"ok": True, **result})
            if path == "/api/runner/complete":
                state = runner.complete_action(
                    str(payload.get("worker", "")),
                    lease_id=str(payload.get("lease_id", "")),
                    observed_result=str(payload.get("observed_result", "")),
                    next_action=str(payload.get("next_action", "")),
                    stage=str(payload.get("stage", "")),
                )
                return self._json({"ok": True, "state": state})
            if path == "/api/runner/block":
                state = runner.block_action(
                    str(payload.get("worker", "")),
                    lease_id=str(payload.get("lease_id", "")),
                    blocked_by=str(payload.get("blocked_by", "")),
                    observed_result=str(payload.get("observed_result", "")),
                )
                return self._json({"ok": True, "state": state})
            return self._json({"ok": False, "error": f"unknown API path: {path}"}, status=404)
        except Exception as exc:
            return self._json({"ok": False, "error": str(exc)}, status=400)

    def _read_payload(self) -> dict[str, Any]:
        length = int(self.headers.get("content-length", "0") or "0")
        if length <= 0:
            return {}
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("request payload must be an object")
        return payload

    def _json(self, payload: dict[str, Any], *, status: int = 200) -> None:
        body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    port = int(os.environ.get("OMH_MANAGEMENT_PORT", "4174"))
    server = ThreadingHTTPServer(("127.0.0.1", port), ManagementHandler)
    print(f"OMH Management server: http://127.0.0.1:{port}/dashboard/index.html", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
