"""P4-09 (g) — 대화 제목: 자동 제목과 이름 바꾸기(D-93, 이슈 #6)(plans/P4-PLAN-09.md AC-27~32).

새 화면의 대화는 "새 대화" 로 고정돼 있었고 바꿀 방법이 없었다. 이제 첫 논의 응답이 해석 블록에 낸 40자
이하 제목이 대화 제목이 되고(출처 `ai`), 업무 요청 응답의 제목으로 한 번 더 갱신되며, **사람이 정한 제목은
자동 제목이 덮지 않는다.** 사람은 언제든(종료·보관 대화도) 1~200자로 바꾼다. 제목은 판정·권한이 아니다.
"""

from __future__ import annotations

from typing import Any

from domain import conversation as convmod
from tests.conftest import FAKE_COMBINED_VERIFIED, FAKE_PLAN_VERIFIED
from tests.test_work_progressor import WORK_BLOCK, _drive


def _block(kind: str = "discussion", title: str | None = None, profile: str | None = None) -> str:
    body: dict[str, Any] = {"kind": kind}
    if profile:
        body["profile"] = profile
    if title is not None:
        body["title"] = title
    import json

    return "```hads-interpretation\n" + json.dumps(body, ensure_ascii=False) + "\n```"


def _case(h, case_id: str) -> dict[str, Any]:
    return h.client.get(f"/api/cases/{case_id}").json()


def _reply(h, case_id: str, text: str, client_id: str, response: str) -> None:
    h.agent.cli_executor.discussion_response = response
    h.send_message(case_id, text, client_id)
    h.agent.poll_once()


# ================================================== 순수 규칙


def test_the_interpretation_carries_a_title_and_cuts_it_at_forty_characters():
    """AC-27 — 해석 블록의 `title` 은 공백 정리 뒤 40자에서 잘리고, 비면 없다. 형식 오류가 아니다."""
    parsed = convmod.parse_interpretation({"kind": "discussion", "title": "  저장 뒤   목록이 옛 값을 보이는 문제  "})
    assert parsed.title == "저장 뒤 목록이 옛 값을 보이는 문제" and parsed.to_dict()["title"] == parsed.title
    long = convmod.parse_interpretation({"kind": "work_request", "profile": "feature", "title": "가" * 60})
    assert long.title == "가" * 40
    assert convmod.parse_interpretation({"kind": "discussion", "title": "   "}).title is None
    assert convmod.parse_interpretation({"kind": "discussion", "title": 12}).title is None
    assert "title" not in convmod.parse_interpretation({"kind": "discussion"}).to_dict()


# ================================================== AC-27·28·29 자동 제목


def test_the_first_reply_names_the_conversation_and_the_work_request_renames_it_once(processing_harness):
    """AC-27·AC-28 — 첫 응답의 제목(출처 ai:discussion) → 업무 요청 응답의 제목으로 한 번 더 → 그 뒤는 그대로."""
    h = processing_harness
    project = h.create_project()
    view = h.create_conversation(project["id"])
    case_id = view["case_id"]
    assert view["title"] == "새 대화" and view["title_source"] == "default"

    _reply(h, case_id, "저장하면 목록이 옛 값을 보여요", "c-1", "확인해 보겠습니다.\n\n" + _block(title="저장 뒤 목록이 옛 값을 보이는 문제"))
    conv = h.conversation(case_id)
    assert conv["title"] == "저장 뒤 목록이 옛 값을 보이는 문제"
    assert conv["title_source"] == "ai" and conv["title_set_by"] == "ai:discussion" and conv["title_previous"] == "새 대화"
    assert conv["interpretations"][-1]["title"] == "저장 뒤 목록이 옛 값을 보이는 문제"

    # 그 뒤의 논의 응답 제목은 덮지 않는다(첫 응답에서 정해졌다).
    _reply(h, case_id, "왜 그럴까요?", "c-2", "캐시일 수 있습니다.\n\n" + _block(title="캐시 문제 논의"))
    assert h.conversation(case_id)["title"] == "저장 뒤 목록이 옛 값을 보이는 문제"

    # 업무 요청 응답은 한 번 더 갱신한다(업무를 말하는 제목).
    executor = h.agent.cli_executor
    executor.combined_response = FAKE_COMBINED_VERIFIED
    executor.plan_response = FAKE_PLAN_VERIFIED
    _reply(h, case_id, "고쳐줘", "c-3", "알겠습니다.\n\n" + _block("work_request", "저장 뒤 목록 갱신 결함 수정", "defect_fix"))
    conv = h.conversation(case_id)
    assert conv["stage"] == "work"
    assert conv["title"] == "저장 뒤 목록 갱신 결함 수정" and conv["title_set_by"] == "ai:work_start"
    assert conv["title_previous"] == "저장 뒤 목록이 옛 값을 보이는 문제"
    # 목록 행에도 같은 제목이다.
    rows = h.client.get(f"/api/projects/{project['id']}/conversations").json()
    assert next(r for r in rows if r["id"] == case_id)["title"] == "저장 뒤 목록 갱신 결함 수정"


def test_a_human_title_is_never_overwritten_by_replies_or_work_start(processing_harness):
    """AC-29·AC-30 — 사람이 바꾼 제목은 이후 응답·업무화가 덮지 않는다. PUT 은 1~200자, 이력이 남는다."""
    h = processing_harness
    project = h.create_project()
    case_id = h.create_conversation(project["id"])["case_id"]
    renamed = h.client.put(f"/api/cases/{case_id}/title", json={"title": "  내가 정한   제목 ", "actor": "owner"})
    assert renamed.status_code == 200, renamed.text
    body = renamed.json()
    assert body["title"] == "내가 정한 제목" and body["title_source"] == "user"
    assert body["title_set_by"] == "owner" and body["title_previous"] == "새 대화" and body["title_set_at"]
    for bad in ("", "   ", "x" * 201):
        assert h.client.put(f"/api/cases/{case_id}/title", json={"title": bad, "actor": "owner"}).status_code in (409, 422)

    _reply(h, case_id, "저장하면 목록이 옛 값을 보여요", "c-1", "확인해 보겠습니다.\n\n" + _block(title="AI 가 붙인 제목"))
    assert h.conversation(case_id)["title"] == "내가 정한 제목"
    executor = h.agent.cli_executor
    executor.combined_response = FAKE_COMBINED_VERIFIED
    executor.plan_response = FAKE_PLAN_VERIFIED
    _reply(h, case_id, "고쳐줘", "c-2", "알겠습니다.\n\n" + _block("work_request", "AI 업무 제목", "defect_fix"))
    conv = h.conversation(case_id)
    assert conv["stage"] == "work" and conv["title"] == "내가 정한 제목" and conv["title_source"] == "user"


# ================================================== AC-30·31 종료·보관 대화, 검색·규칙 화면 출처


def test_a_closed_or_archived_conversation_can_still_be_renamed_and_the_name_reaches_search_and_rules(processing_harness):
    """AC-30·AC-31 — 종료·보관 대화도 이름을 바꾼다. 검색 결과·규칙 화면 출처·후속 대화 제목에 반영된다."""
    h = processing_harness
    project, _path = h.create_git_project("title-flow")
    case_id = h.create_conversation(project["id"])["case_id"]
    executor = h.agent.cli_executor
    executor.combined_response = FAKE_COMBINED_VERIFIED
    executor.plan_response = FAKE_PLAN_VERIFIED
    executor.write_files = {"reader.py": "def read(path):\n    return [l for l in open(path) if l.startswith('ERROR')]\n"}
    executor.residual_activity = "none"
    executor.residual_basis = "in_process"
    _reply(h, case_id, "이 프로젝트에서는 앞으로 로그에 비밀값을 남기지 마", "c-0",
           "등록합니다.\n\n```hads-knowledge\n{\"items\": [{\"kind\": \"constraint\", \"obligation\": \"required\","
           " \"summary\": \"비밀값 금지\", \"content\": \"로그에 비밀값을 남기지 않는다\", \"repository\": null,"
           " \"paths\": [], \"activities\": [], \"supersedes\": null}]}\n```\n\n" + _block(title="비밀값 규칙"))
    assert h.conversation(case_id)["title"] == "비밀값 규칙"
    _reply(h, case_id, "오류 줄 필터를 구현해줘", "c-1", f"알겠습니다.\n\n{WORK_BLOCK.format(profile='feature')}")
    _drive(h, case_id)
    from tests.test_work_progressor import _agree

    _agree(h, case_id)
    _drive(h, case_id)
    assert _case(h, case_id)["status"] == "closed"

    # 종료 뒤·보관 뒤에도 이름을 바꾼다.
    assert h.client.post(f"/api/cases/{case_id}/archive", json={"actor": "owner"}).status_code == 200
    renamed = h.client.put(f"/api/cases/{case_id}/title", json={"title": "필터 업무(완료)", "actor": "owner"})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["status"] == "closed" and renamed.json()["visibility"]["archived"] is True

    # 검색(서버 필드)과 규칙 화면 출처가 새 제목을 보인다.
    search = h.client.post(
        f"/api/projects/{project['id']}/conversation-searches", json={"query": "필터 업무", "requested_by": "owner"}
    )
    assert search.status_code in (200, 201), search.text
    result = h.client.get(f"/api/conversation-searches/{search.json()['id']}").json()
    assert any(m["case_id"] == case_id and m["case_title"] == "필터 업무(완료)" for m in result["matches"])
    knowledge = h.client.get(f"/api/projects/{project['id']}/knowledge").json()
    item = next(i for i in knowledge["items"] if i["knowledge_key"] == "K-001")
    assert item["current"]["source_case_title"] == "필터 업무(완료)"

    # 후속 대화의 기본 제목은 "… · 후속" 이고 출처는 기본값이라 첫 응답이 제목을 낼 수 있다.
    h.client.post(f"/api/cases/{case_id}/restore", json={"actor": "owner"})
    _reply(h, case_id, "대소문자 무시도 넣어줘", "c-9", "새 대화로 옮깁니다.\n\n" + _block("work_request", "대소문자 무시 추가", "feature"))
    successor = next(r for r in h.conversation(case_id)["relations"] if r["direction"] == "successor")
    follow = h.conversation(successor["case_id"])
    assert follow["title"] in ("필터 업무(완료) · 후속", "대소문자 무시 추가")
    assert follow["title_source"] in ("default", "ai")


# ================================================== AC-32 옛 행


def test_an_old_row_without_a_source_gets_an_auto_title_only_when_it_still_has_the_default_text(processing_harness):
    """AC-32 — 출처 미기록(NULL) 행: 기본 문구면 자동 제목을 받고, 다른 제목이면 받지 않는다(지어 판단하지 않는다)."""
    h = processing_harness
    project = h.create_project()
    from tests.test_work_progressor import _repo

    repo = _repo(h)
    a = h.create_conversation(project["id"])["case_id"]
    b = h.create_conversation(project["id"], "옛 사람 제목")["case_id"]
    repo.conn.execute('UPDATE "case" SET title_source = NULL WHERE id IN (?, ?)', (a, b))
    repo.conn.commit()
    _reply(h, a, "안녕", "c-a", "안녕하세요.\n\n" + _block(title="첫 인사"))
    _reply(h, b, "안녕", "c-b", "안녕하세요.\n\n" + _block(title="첫 인사"))
    assert h.conversation(a)["title"] == "첫 인사" and h.conversation(a)["title_source"] == "ai"
    assert h.conversation(b)["title"] == "옛 사람 제목" and h.conversation(b)["title_source"] is None
