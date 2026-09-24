"""UI-04d — 보관 포함 프로젝트 대화 검색(D-84)(plans/UI-PLAN-04d.md 4·5절).

현재 프로젝트의 대화를 보관된 것까지 제목·요약·결정·규칙(서버)과 본문(소유 PC)에서 찾는다. PC 가 미연결이면
서버 필드만 검색하고 **일부 제외를 값으로** 보인다. 본문·발췌는 서버에 저장되지 않는다.

이 파일이 지키는 것:

    서버는 검색어·발췌를 저장하지 않는다   검색 뒤 DB 의 어느 표에도 그 글이 없다(SQL 로 전부 읽는다)
    범위를 지어내지 않는다                  미연결 PC 의 본문 수가 `excluded` 로 오고 서버 요약은 본문이 아니다
    본문은 소유 PC 만 읽는다                Runner 는 후보 원문만 읽고 후보 밖 일치는 받지 않는다
    사라진 것은 사라졌다고 말한다           만료·재시작은 404·`expired` 이지 빈 결과가 아니다

시험 이름 옆의 AC 번호는 UI-PLAN-04d 4절이다.
"""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from controller import search as searchmod
from domain import search as rules
from tests.conftest import RUNNER_ID
from tests.test_knowledge import _register
from tests.test_workspace import _agreed_git_case


# ================================================== 순수 규칙 (domain.search)


def test_words_match_all_case_insensitively_and_the_snippet_sits_on_the_first_hit():
    """AC-1(순수) — 낱말은 공백 분리·소문자·중복 제거·상한, 일치는 전부(AND), 발췌는 첫 일치 주변에 일치 수를 단다."""
    assert rules.tokens("  Reader  오류 reader ") == ("reader", "오류")
    assert rules.tokens("") == ()
    assert len(rules.tokens(" ".join(str(i) for i in range(20)))) == rules.MAX_TOKENS
    words = rules.tokens("reader 오류")
    assert rules.matches("Reader 에서 오류가 났다", words) is True
    assert rules.matches("reader 만 있다", words) is False
    assert rules.matches("아무거나", ()) is False and rules.matches(None, words) is False
    long = "앞부분 " * 40 + "여기서 Reader 의 오류를 봤다 " + "뒷부분 " * 40
    excerpt = rules.snippet(long, words)
    assert "Reader" in excerpt["snippet"] and "오류" in excerpt["snippet"]
    assert excerpt["snippet"].startswith("…") and excerpt["snippet"].endswith("…")
    assert len(excerpt["snippet"]) <= rules.SNIPPET_WIDTH + 2
    assert excerpt["match_count"] == 2
    assert rules.snippet("짧은\n글", ("없음",)) == {"snippet": "짧은 글", "match_count": 0}


# ================================================== 도우미


def _db_has(harness, needle: str) -> bool:
    conn = sqlite3.connect(harness.controller_config.db_path)
    try:
        for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall():
            for row in conn.execute(f'SELECT * FROM "{table}"'):
                for value in row:
                    if isinstance(value, str) and needle in value:
                        return True
                    if isinstance(value, bytes) and needle.encode("utf-8") in value:
                        return True
        return False
    finally:
        conn.close()


def _search(harness, project_id: str, query: str):
    return harness.client.post(
        f"/api/projects/{project_id}/conversation-searches", json={"query": query, "requested_by": "owner"}
    )


def _view(harness, search_id: str) -> dict[str, Any]:
    response = harness.client.get(f"/api/conversation-searches/{search_id}")
    assert response.status_code == 200, response.text
    return response.json()


def _reply(harness, case_id: str, text: str, run_id: str) -> None:
    """이 대화의 현재 요청에 **AI 응답**(본문은 Runner 저장)을 붙이고 요청을 끝낸다."""
    conv = harness.conversation(case_id)
    request = conv["current_request"]
    harness.agent.cli_executor.discussion_response = text
    assert harness.discussion_reply(case_id, request["id"], run_id).status_code == 201
    harness.settle(case_id, request["id"])


def _project_with_conversations(harness) -> dict[str, Any]:
    """대화 셋(둘째는 보관), 규칙 하나, 동의 결정이 있는 업무 Case 하나, 다른 프로젝트의 대화 하나."""
    project = harness.create_project("검색 프로젝트")
    first = harness.create_conversation(project["id"], "quokka 필터 이야기")["case_id"]
    harness.send_message(first, "첫 대화의 본문에는 wombat 낱말이 있다", "c-1")
    _reply(harness, first, "AI 응답에는 numbat 낱말이 있다", "run-search-reply-1")
    second = harness.create_conversation(project["id"], "보관될 대화")["case_id"]
    harness.send_message(second, "보관된 대화의 본문에도 wombat 가 있다", "c-2")
    assert harness.client.post(f"/api/cases/{second}/archive", json={"actor": "owner"}).status_code == 200
    third = harness.create_conversation(project["id"], "규칙 대화")["case_id"]
    harness.send_message(third, "규칙을 정하자", "c-3")
    _register(harness, third, "배포 전에 lint 를 돌린다", summary="배포 전 lint 규칙")
    work, _repo = _agreed_git_case(harness, name="search-work")  # 자기 프로젝트(실제 git)의 업무 Case
    other = harness.create_project("다른 프로젝트")
    elsewhere = harness.create_conversation(other["id"], "quokka 는 다른 프로젝트에도")["case_id"]
    harness.send_message(elsewhere, "다른 프로젝트의 wombat", "c-4")
    return {
        "project": project, "first": first, "second": second, "third": third,
        "work": work["id"], "work_project": work["project_id"], "other": other,
    }


# ================================================== AC-1·2·4 서버 필드·범위·경계


def test_server_fields_are_searched_at_once_and_a_disconnected_pc_is_excluded_by_count(harness):
    """AC-1·2·4 — 제목·규칙 요약·결정이 즉시 일치하고 보관된 대화도 든다. 다른 프로젝트는 없다. 메시지 요약은 본문이
    아니므로 본문 낱말로는 일치하지 않는다. PC 가 미연결이면 `body.state = excluded` 와 제외 수가 온다. 검색어는 DB 에
    남지 않고 검색 표도 없다."""
    ids = _project_with_conversations(harness)
    project_id = ids["project"]["id"]
    harness.age_heartbeat(3600 * 2)

    response = _search(harness, project_id, "quokka")
    assert response.status_code == 201, response.text
    view = response.json()
    assert view["not_stored"] is True and view["query_length"] == 6 and "query" not in view
    kinds = {(m["kind"], m["case_id"]) for m in view["matches"]}
    assert kinds == {("title", ids["first"])}  # 다른 프로젝트의 quokka 제목은 없다
    assert view["scope"]["archived_included"] is True
    assert view["body"]["state"] == "excluded" and view["scope"]["bodies"] == "excluded"
    # 세 대화의 메시지(사용자 3 + AI 응답 1) — 전부 미연결 PC 의 것이다.
    assert view["scope"]["excluded_message_count"] == 4 and view["scope"]["candidate_message_count"] == 0
    assert view["scope"]["runners"] == [
        {"runner_id": RUNNER_ID, "host": "test-host", "connection": "disconnected", "state": "excluded", "message_count": 4}
    ]
    assert "PC 미연결로 본문 4건 검색 제외" in view["scope"]["note"]

    # 본문 낱말은 서버에서 잡히지 않는다 — 요약은 본문이 아니다(오프라인에서 본문을 찾았다고 말하지 않는다).
    assert _search(harness, project_id, "wombat").json()["matches"] == []
    # 규칙·결정·보관.
    rule = _search(harness, project_id, "lint 규칙").json()["matches"]
    assert [(m["kind"], m["case_id"], m["item_key"], m["target"]) for m in rule] == [("rule", ids["third"], "K-001", "rule")]
    archived = _search(harness, project_id, "보관될").json()["matches"]
    assert [(m["kind"], m["archived"]) for m in archived] == [("title", True)]
    # 결정(의도 동의)은 업무 Case 의 프로젝트에서 — 결정 종류의 사람 말로 찾히고 결정 사항 패널로 간다.
    decision = _search(harness, ids["work_project"], "의도 동의").json()["matches"]
    assert ("decision", ids["work"]) in {(m["kind"], m["case_id"]) for m in decision}
    assert all(m["target"] == "decisions" for m in decision if m["kind"] == "decision")
    assert _search(harness, project_id, "의도 동의").json()["matches"] == []  # 다른 프로젝트의 결정은 없다
    # 낱말 전부가 있어야 한다.
    assert _search(harness, project_id, "quokka 없는낱말").json()["matches"] == []
    assert _search(harness, project_id, "   ").status_code == 422
    assert _search(harness, "prj-none", "x").status_code == 404

    # **검색어는 DB 어디에도 없다.** 검색 표도 없다.
    assert not _db_has(harness, "quokka 없는낱말") and not _db_has(harness, "lint 규칙\n")
    conn = sqlite3.connect(harness.controller_config.db_path)
    try:
        names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
    finally:
        conn.close()
    assert not any("search" in n for n in names)


# ================================================== AC-3·4 본문 — 소유 PC 가 읽는다


def test_the_owning_pc_searches_the_bodies_and_the_excerpt_stays_out_of_the_db(harness):
    """AC-3·4 — 연결된 소유 PC 가 제어 루프에서 후보 원문만 읽어 일치(대화·순번·발췌·수)를 올린다; 조회에 `relayed` 로
    온다; 보관된 대화의 본문도 든다; 이 PC 에 없는 원문은 `unreadable` 이고 일치가 아니다; 후보 밖·다른 PC·모르는 검색은
    받지 않는다; 발췌·검색어는 DB 에 없다."""
    ids = _project_with_conversations(harness)
    project_id = ids["project"]["id"]

    view = _search(harness, project_id, "WOMBAT").json()
    assert view["body"]["state"] == "pending" and view["matches"] == []
    assert view["scope"]["candidate_message_count"] == 4 and view["scope"]["excluded_message_count"] == 0
    assert view["scope"]["runners"][0]["state"] == "pending"
    # 아직 도착 전 — 조회는 같은 상태다.
    assert _view(harness, view["id"])["body"]["state"] == "pending"

    tick = harness.agent.control_tick()
    assert tick["served_searches"] == [{"id": view["id"], "matches": 2, "scanned": 4, "unreadable": 0}]
    done = _view(harness, view["id"])
    assert done["body"]["state"] == "relayed" and done["scope"]["bodies"] == "relayed"
    hits = {(m["case_id"], m["seq"], m["author"], m["archived"]) for m in done["body"]["matches"]}
    assert hits == {(ids["first"], 1, "user", False), (ids["second"], 1, "user", True)}
    first = next(m for m in done["body"]["matches"] if m["case_id"] == ids["first"])
    assert first["kind"] == "body" and first["target"] == "message" and first["source"] == "runner"
    assert "wombat" in first["text"] and first["match_count"] == 1
    assert done["matches"] == done["body"]["matches"]  # 서버 일치 없음 + 본문 둘
    assert "제목·요약·결정과 본문(PC)을 검색했다" in done["scope"]["note"]
    # 두 번째 제어 루프는 같은 검색을 다시 하지 않는다.
    assert harness.agent.control_tick()["served_searches"] == []

    # **발췌·검색어는 DB 에 없다** — 메모리로만 중계됐다.
    assert not _db_has(harness, "첫 대화의 본문에는 wombat")
    assert not _db_has(harness, "WOMBAT")

    # AI 응답 본문도 검색된다(제목·본문이 한 대화에서 함께 잡힌다).
    both = _search(harness, project_id, "numbat").json()
    harness.agent.control_tick()
    both = _view(harness, both["id"])
    assert [(m["kind"], m["seq"], m["author"]) for m in both["matches"]] == [("body", 2, "assistant")]

    # 후보 밖·다른 PC·모르는 검색은 받지 않는다.
    pending = _search(harness, project_id, "quokka").json()
    claimed = harness.client.get(f"/api/runner/{RUNNER_ID}/search-requests").json()
    assert [c["id"] for c in claimed] == [pending["id"]] and claimed[0]["query"] == "quokka"
    assert all(set(c) == {"case_id", "seq", "author", "artifact_id", "revision"} for c in claimed[0]["candidates"])
    foreign = harness.client.post(
        f"/api/runner/search-requests/{pending['id']}/results",
        json={"runner_id": "runner-x", "matches": [], "scanned": 0, "unreadable": 0},
    )
    assert foreign.status_code == 409
    outside = harness.client.post(
        f"/api/runner/search-requests/{pending['id']}/results",
        json={
            "runner_id": RUNNER_ID,
            "matches": [{"artifact_id": "art-not-a-candidate", "revision": 1, "snippet": "지어낸 발췌", "match_count": 1}],
            "scanned": 4,
            "unreadable": 0,
        },
    )
    assert outside.status_code == 200 and outside.json()["accepted"] == 0
    result = _view(harness, pending["id"])
    assert result["body"]["matches"] == [] and [m["kind"] for m in result["matches"]] == ["title"]
    assert harness.client.post(
        f"/api/runner/search-requests/{pending['id']}/results",
        json={"runner_id": RUNNER_ID, "matches": [], "scanned": 0, "unreadable": 0},
    ).status_code == 409  # 이미 끝난 부분
    assert harness.client.get("/api/conversation-searches/search-nope").status_code == 404
    assert harness.client.post(
        "/api/runner/search-requests/search-nope/results",
        json={"runner_id": RUNNER_ID, "matches": [], "scanned": 0, "unreadable": 0},
    ).status_code == 404


def test_missing_originals_are_counted_and_late_or_expired_searches_say_so(harness, monkeypatch):
    """AC-3·4 — 이 PC 에 없는 원문은 `unreadable` 로 세고 일치로 적지 않는다; PC 가 제한 시간 안에 답하지 않으면
    `expired`; TTL 이 지난 검색의 조회는 404(빈 결과가 아니다)."""
    ids = _project_with_conversations(harness)
    project_id = ids["project"]["id"]
    conv = harness.conversation(ids["second"])
    message = conv["messages"][0]
    harness.agent.store.path_for(message["artifact_id"], message["artifact_rev"]).unlink()

    view = _search(harness, project_id, "wombat").json()
    tick = harness.agent.control_tick()
    assert tick["served_searches"] == [{"id": view["id"], "matches": 1, "scanned": 3, "unreadable": 1}]
    done = _view(harness, view["id"])
    assert done["body"]["unreadable"] == 1 and done["scope"]["unreadable_message_count"] == 1
    assert [m["case_id"] for m in done["body"]["matches"]] == [ids["first"]]

    # PC 에 전달됐는데 답이 없다 — 제한 시간이 지나면 `expired` 다.
    monkeypatch.setattr(searchmod, "RUNNER_TIMEOUT_SECONDS", -1.0)
    late = _search(harness, project_id, "wombat").json()
    assert harness.client.get(f"/api/runner/{RUNNER_ID}/search-requests").json()[0]["id"] == late["id"]
    expired = _view(harness, late["id"])
    assert expired["body"]["state"] == "expired" and expired["scope"]["expired_message_count"] == 4
    assert "제한 시간 안에" in expired["scope"]["note"]
    assert harness.client.post(
        f"/api/runner/search-requests/{late['id']}/results",
        json={"runner_id": RUNNER_ID, "matches": [], "scanned": 0, "unreadable": 0},
    ).status_code == 409

    # 검색 자체의 수명이 지나면 없다 — 404.
    monkeypatch.setattr(searchmod, "SEARCH_TTL_SECONDS", -1.0)
    gone = _search(harness, project_id, "wombat")
    assert gone.status_code == 201
    assert harness.client.get(f"/api/conversation-searches/{gone.json()['id']}").status_code == 404


def test_a_project_without_bodies_says_none_and_the_candidate_cap_is_reported(harness, monkeypatch):
    """AC-2 — 후보가 없으면 `none`; 후보 상한을 넘으면 `truncated` 로 드러낸다(전부 찾았다고 말하지 않는다)."""
    project = harness.create_project("빈 프로젝트")
    harness.create_conversation(project["id"], "quokka 만 있는 제목")
    view = _search(harness, project["id"], "quokka").json()
    assert view["body"]["state"] == "none" and [m["kind"] for m in view["matches"]] == ["title"]
    assert "검색할 본문이 없다" in view["scope"]["note"]

    ids = _project_with_conversations(harness)
    monkeypatch.setattr(rules, "MAX_CANDIDATES", 2)
    capped = _search(harness, ids["project"]["id"], "wombat").json()
    assert capped["scope"]["truncated"] is True and capped["scope"]["candidate_message_count"] == 2
    assert "상한" in capped["scope"]["note"]
