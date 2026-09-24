"""대화 검색(UI-04d, D-84) — 서버 필드는 즉시, 본문은 소유 PC 가 읽어 **메모리로만** 중계한다.

이 모듈이 지키는 것:

    **서버는 검색어·발췌를 저장하지 않는다.** 요청·후보·결과는 `TransientStore`(프로세스 메모리)에만 있고
    TTL 이 지나거나 제어부가 재시작하면 사라진다(`expired`). DB 에 검색 표가 없다(data-boundary 1·3절).
    **본문은 소유 PC 만 읽는다.** 후보는 원문 참조(`artifact_id/revision`)이며 Runner 는 자기 저장소에서
    그것만 읽는다 — 경로를 주지 않는다(열람 중계와 같은 원칙).
    **범위를 값으로 말한다.** 미연결 PC 가 가진 메시지 수를 세어 `excluded` 로 드러내고, 후보 상한을 넘으면
    `truncated` 다. 오프라인에서 본문을 찾았다고 말하지 않는다.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

from controller.transient import TransientStore
from domain import ids
from domain import run_control as runctl
from domain import search as rules

#: 검색 요청이 메모리에 남는 시간(초). 그 뒤 조회는 404 다(사라진 것을 빈 결과로 보이지 않는다).
SEARCH_TTL_SECONDS = 600.0
#: PC 에 전달된 뒤 결과가 오지 않으면 본문 검색을 `expired` 로 닫는 시간(초).
RUNNER_TIMEOUT_SECONDS = 60.0

_KEY = "search:"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _seconds_since(stamp: str | None) -> float:
    if not stamp:
        return 0.0
    try:
        then = datetime.fromisoformat(stamp)
    except ValueError:
        return 0.0
    return (datetime.now(timezone.utc) - then).total_seconds()


class SearchRegistry:
    """검색 요청·후보·결과의 메모리 등록부. 한 검색은 소유 PC 마다 **부분**(`parts`) 하나를 가진다."""

    def __init__(self, store: TransientStore) -> None:
        self.store = store
        self._lock = threading.RLock()

    # ------------------------------------------------------------- 만들기

    def create(self, repo: Any, project_id: str, query: str, requested_by: str) -> dict[str, Any]:
        words = rules.tokens(query)
        if not words:
            raise ValueError("the query has no words")
        data = repo.search_candidates(project_id, rules.MAX_CANDIDATES)
        cases = {c["case_id"]: c for c in data["cases"]}
        matches = [
            self._server_match(field, cases[field["case_id"]], words)
            for field in data["fields"]
            if rules.matches(field.get("text"), words)
        ]
        parts: dict[str, dict[str, Any]] = {}
        for body in data["bodies"]:
            runner_id = body["owner_runner_id"]
            part = parts.get(runner_id)
            if part is None:
                connection = repo.runner_connection_state(runner_id, "search")
                runner = repo.get_runner(runner_id) if runner_id else {}
                part = parts[runner_id] = {
                    "runner_id": runner_id,
                    "host": runner.get("host"),
                    "connection": connection.get("state"),
                    "state": "excluded" if runctl.connection_refuses(connection) else "pending",
                    "message_count": 0,
                    "unreadable_pending": 0,
                    "candidates": [],
                    "matches": [],
                    "scanned": 0,
                    "unreadable": 0,
                    "claimed_at": None,
                    "relayed_at": None,
                }
            part["message_count"] += 1
            if body["availability"] != "available":
                # 저장되지 않은(접수 대기·유실) 원문은 PC 에 없다 — 후보에 넣지 않고 세기만 한다.
                part["unreadable_pending"] += 1
                continue
            if part["state"] == "pending":
                part["candidates"].append(
                    {k: body[k] for k in ("case_id", "seq", "author", "artifact_id", "revision")}
                )
        entry = {
            "id": ids.new_id("search"),
            "project_id": project_id,
            "requested_by": requested_by,
            "requested_at": _utc_now(),
            "query": query,
            "words": list(words),
            "cases": cases,
            "matches": matches,
            "parts": parts,
            "truncated": bool(data["truncated"]),
        }
        with self._lock:
            self.store.put(_KEY + entry["id"], entry, SEARCH_TTL_SECONDS)
            return self._view_of(entry)

    @staticmethod
    def _server_match(field: dict[str, Any], case: dict[str, Any], words: tuple[str, ...]) -> dict[str, Any]:
        excerpt = rules.snippet(field["text"] or "", words)
        return {
            "kind": field["kind"],
            "case_id": case["case_id"],
            "case_title": case["title"],
            "archived": case["archived"],
            "status": case["status"],
            "seq": field.get("seq"),
            "text": excerpt["snippet"],
            "match_count": excerpt["match_count"],
            "item_key": field.get("item_key"),
            "target": field["target"],
            "source": "server",
        }

    # ------------------------------------------------------------- 조회

    def _get(self, search_id: str) -> dict[str, Any] | None:
        return self.store.get(_KEY + search_id)

    def _expire_parts(self, entry: dict[str, Any]) -> None:
        for part in entry["parts"].values():
            if part["state"] == "claimed" and _seconds_since(part["claimed_at"]) > RUNNER_TIMEOUT_SECONDS:
                part["state"] = "expired"

    def view(self, search_id: str) -> dict[str, Any] | None:
        """검색 한 벌. 서버 일치는 즉시, 본문 일치는 PC 가 올린 뒤에. 없으면(만료·재시작) `None`."""
        with self._lock:
            entry = self._get(search_id)
            if entry is None:
                return None
            return self._view_of(entry)

    def _view_of(self, entry: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._expire_parts(entry)
            parts = list(entry["parts"].values())
            body_matches = [m for part in parts for m in part["matches"]]
            states = {p["state"] for p in parts}
            if not parts:
                body_state = "none"
            elif states <= {"relayed", "excluded"} and "relayed" in states:
                body_state = "relayed"
            elif states == {"excluded"}:
                body_state = "excluded"
            elif "relayed" in states:
                body_state = "partial"
            elif states & {"pending", "claimed"}:
                body_state = "pending"
            else:
                body_state = "expired"
            excluded = sum(p["message_count"] for p in parts if p["state"] == "excluded")
            expired = sum(p["message_count"] for p in parts if p["state"] == "expired")
            unreadable = sum(p["unreadable"] + p["unreadable_pending"] for p in parts)
            return {
                "id": entry["id"],
                "project_id": entry["project_id"],
                "requested_by": entry["requested_by"],
                "requested_at": entry["requested_at"],
                "query_length": len(entry["query"]),
                "words": list(entry["words"]),
                "scope": {
                    "archived_included": True,
                    "server_fields": [
                        "title", "message_summary", "work_request", "decision", "profile_revision", "rule",
                    ],
                    "bodies": body_state,
                    "candidate_message_count": sum(len(p["candidates"]) for p in parts),
                    "excluded_message_count": excluded,
                    "expired_message_count": expired,
                    "unreadable_message_count": unreadable,
                    "truncated": entry["truncated"],
                    "runners": [
                        {
                            "runner_id": p["runner_id"],
                            "host": p["host"],
                            "connection": p["connection"],
                            "state": p["state"],
                            "message_count": p["message_count"],
                        }
                        for p in parts
                    ],
                    "note": _scope_note(body_state, excluded, expired, entry["truncated"]),
                },
                "matches": [*entry["matches"], *body_matches],
                "body": {
                    "state": body_state,
                    "matches": body_matches,
                    "scanned": sum(p["scanned"] for p in parts),
                    "unreadable": unreadable,
                },
                "not_stored": True,
            }

    # ------------------------------------------------------------- Runner

    def pending_for(self, runner_id: str) -> list[dict[str, Any]]:
        """이 PC 가 맡을 본문 검색(검색어·후보). 내려보내면 `claimed` — 두 번 주지 않는다."""
        out: list[dict[str, Any]] = []
        with self._lock:
            for _key, entry in self.store.items(_KEY):
                part = entry["parts"].get(runner_id)
                if part is None or part["state"] != "pending":
                    continue
                part["state"] = "claimed"
                part["claimed_at"] = _utc_now()
                out.append(
                    {
                        "id": entry["id"],
                        "query": entry["query"],
                        "candidates": list(part["candidates"]),
                    }
                )
        return out

    def record_results(
        self,
        search_id: str,
        runner_id: str,
        matches: list[dict[str, Any]],
        *,
        scanned: int,
        unreadable: int,
    ) -> dict[str, Any]:
        """PC 가 올린 본문 일치. 다른 PC·모르는 검색·이미 끝난 부분은 거부한다."""
        with self._lock:
            entry = self._get(search_id)
            if entry is None:
                raise KeyError(search_id)
            part = entry["parts"].get(runner_id)
            if part is None:
                raise PermissionError(runner_id)
            self._expire_parts(entry)
            if part["state"] not in ("claimed", "pending"):
                raise ValueError(part["state"])
            allowed = {(c["artifact_id"], c["revision"]): c for c in part["candidates"]}
            accepted = []
            for match in matches:
                key = (str(match.get("artifact_id")), int(match.get("revision") or 0))
                candidate = allowed.get(key)
                if candidate is None:
                    continue  # 후보 밖의 일치는 받지 않는다
                case = entry["cases"].get(candidate["case_id"]) or {}
                accepted.append(
                    {
                        "kind": "body",
                        "case_id": candidate["case_id"],
                        "case_title": case.get("title"),
                        "archived": case.get("archived", False),
                        "status": case.get("status"),
                        "seq": candidate["seq"],
                        "author": candidate["author"],
                        "artifact_id": candidate["artifact_id"],
                        "revision": candidate["revision"],
                        "text": str(match.get("snippet") or "")[: rules.SNIPPET_WIDTH + 2],
                        "match_count": int(match.get("match_count") or 0),
                        "item_key": None,
                        "target": "message",
                        "source": "runner",
                    }
                )
            part["matches"] = accepted
            part["scanned"] = int(scanned)
            part["unreadable"] = int(unreadable)
            part["state"] = "relayed"
            part["relayed_at"] = _utc_now()
            self.store.touch(_KEY + search_id, SEARCH_TTL_SECONDS)
        return {"id": search_id, "runner_id": runner_id, "accepted": len(accepted), "state": "relayed"}


def _scope_note(body_state: str, excluded: int, expired: int, truncated: bool) -> str:
    parts: list[str] = []
    if body_state == "none":
        parts.append("이 프로젝트에 검색할 본문이 없다 — 제목·요약·결정만 봤다")
    elif body_state == "excluded":
        parts.append(f"PC 미연결로 본문 {excluded}건 검색 제외 — 제목·요약·결정만 봤다")
    elif body_state == "partial":
        parts.append(f"일부 PC 만 본문을 검색했다 — 미연결 PC 의 본문 {excluded}건은 제외")
    elif body_state == "pending":
        parts.append("본문은 작업 PC 가 검색하는 중이다")
    elif body_state == "expired":
        parts.append(f"작업 PC 가 제한 시간 안에 본문 검색 결과를 보내지 않았다({expired}건) — 다시 검색한다")
    else:
        parts.append("제목·요약·결정과 본문(PC)을 검색했다")
        if excluded:
            parts.append(f"미연결 PC 의 본문 {excluded}건은 제외")
    if truncated:
        parts.append(f"본문 후보가 상한({rules.MAX_CANDIDATES}건, 최신순)을 넘어 오래된 메시지는 보지 않았다")
    return " · ".join(parts)
