"""AC-6 — 원문이 제어부에 남지 않는지 파일 바이트 수준에서 확인한다.

D-51, NFR-12, data-boundary-review.md 1·3절.

방법: 알아볼 수 있는 표식 문자열을 **본문에만** 넣어 제출한 뒤
  - 제어부 SQLite 파일(+ WAL/SHM) 전체 바이트에서 표식을 찾는다 → 없어야 한다
  - 제어부 로그 파일에서 표식을 찾는다 → 없어야 한다
  - Runner 원문 저장소에서 표식을 찾는다 → **있어야 한다**

마지막 확인이 중요하다. 셋 다 없으면 원문이 아예 저장되지 않은 것이므로
경계를 지킨 증거가 되지 않는다.
"""

from __future__ import annotations

from pathlib import Path

MARKER = "MARKER-7f3a9c-원문본문-DO-NOT-PERSIST-ON-CONTROLLER"


def _controller_bytes(harness) -> bytes:
    data = b""
    db = Path(harness.controller_config.db_path)
    for path in (db, Path(str(db) + "-wal"), Path(str(db) + "-shm")):
        if path.exists():
            data += path.read_bytes()
    return data


def _runner_bytes(harness) -> bytes:
    data = b""
    for path in Path(harness.runner_config.data_root).rglob("*"):
        if path.is_file():
            data += path.read_bytes()
    return data


def test_raw_body_is_not_persisted_on_the_controller(harness):
    project = harness.create_project()
    case = harness.create_case(project["id"])
    content = f"목표: 무언가\n{MARKER}\n제약: 없음\n"

    # summary 는 호출자가 주는 짧은 표시 문구다. 본문 표식을 넣지 않는다.
    harness.submit_artifact(case["id"], content, kind="intent", summary="의도 초안 v1")

    marker = MARKER.encode("utf-8")
    assert marker not in _controller_bytes(harness), "원문이 제어부 DB에 남았다"

    log = Path(harness.controller_config.log_path)
    assert log.exists()
    assert marker not in log.read_bytes(), "원문이 제어부 로그에 남았다"

    assert marker in _runner_bytes(harness), "원문이 Runner에도 없다 — 경계 확인이 무의미하다"


def test_controller_keeps_only_the_reference_fields(harness):
    project = harness.create_project()
    case = harness.create_case(project["id"])
    accepted = harness.submit_artifact(case["id"], f"본문 {MARKER}", summary="지시")

    detail = harness.client.get(f"/api/cases/{case['id']}").json()
    ref = detail["artifacts"][0]
    assert set(ref) == {
        "artifact_id",
        "revision",
        "case_id",
        "kind",
        "content_hash",
        "byte_size",
        "owner_runner_id",
        "availability",
        "summary",
        "created_at",
    }
    assert ref["content_hash"] == accepted["content_hash"]
    assert MARKER not in ref["summary"]


def test_relay_buffer_is_emptied_after_the_runner_stores_the_body(harness):
    """중계 본문은 Runner 저장 보고 직후 버린다."""
    project = harness.create_project()
    case = harness.create_case(project["id"])

    harness.client.post(
        f"/api/cases/{case['id']}/artifacts",
        json={
            "kind": "instruction",
            "content": f"본문 {MARKER}",
            "summary": "지시",
            "target_runner_id": harness.runner_config.runner_id,
        },
    )
    assert harness.client.get("/api/health").json()["relay_buffered"] == 1

    harness.agent.persist_pending_intakes()
    assert harness.client.get("/api/health").json()["relay_buffered"] == 0


def test_pending_intake_is_not_reported_as_saved(harness):
    """Runner가 저장하기 전에는 저장 완료가 아니다(NFR-01)."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    response = harness.client.post(
        f"/api/cases/{case['id']}/artifacts",
        json={
            "kind": "intent",
            "content": "아직 저장되지 않은 의도",
            "summary": "의도",
            "target_runner_id": harness.runner_config.runner_id,
        },
    )
    assert response.status_code == 202  # 201/200 이 아니다: 저장 완료가 아니다
    accepted = response.json()
    assert accepted["availability"] == "pending"

    detail = harness.client.get(f"/api/cases/{case['id']}").json()
    assert detail["artifacts"][0]["availability"] == "pending"


def test_artifact_store_rejects_path_traversal(harness):
    """원문 조회를 임의 경로 열람 기능으로 만들지 않는다(NFR-12)."""
    import pytest

    for bad in ("../escape", "a/b", "C:\\Windows\\system32", ""):
        with pytest.raises(ValueError):
            harness.agent.store.put(bad, 1, b"x")


# ===================================================================== P2-02
#
# 새로 생긴 본문 경로가 세 개다. 각각 표식을 달리해 어디로 갔는지 구별한다.
#   - 의도 초안 본문(정규 문서로 묶여 중계)
#   - 피드백 본문 · 질문 답변 본문
#   - **열람**: 원문이 Runner → 제어부 메모리 → 브라우저로 한 번 더 지나간다

INTENT_MARKER = "MARKER-i1-의도본문-DO-NOT-PERSIST"
FEEDBACK_MARKER = "MARKER-f1-피드백본문-DO-NOT-PERSIST"
ANSWER_MARKER = "MARKER-a1-답변본문-DO-NOT-PERSIST"


def test_intent_feedback_answer_and_read_bodies_never_persist_on_the_controller(harness):
    """AC-9 — 의도·피드백·답변·열람 본문이 제어부에 남지 않는다.

    열람까지 수행하는 것이 중요하다. 열람은 본문이 제어부를 **한 번 더** 지나는
    경로이고, 그 때 DB나 로그에 흘리기 가장 쉽다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])

    accepted = harness.submit_intent_draft(
        case["id"],
        {
            "goal": {
                "text": f"목표 본문 {INTENT_MARKER}",
                "state": "proposed",
                "origin": "user_requirement",
            }
        },
        questions=[
            {
                "key": "q1",
                "text": f"질문 본문 {INTENT_MARKER}-q",
                "summary": "행 범위 결정",
                "decide_at": "intent",
            }
        ],
        summary="의도 초안 v1",
    )
    intent = harness.latest_intent(case["id"])

    harness.submit_feedback(
        case["id"], intent["id"], f"피드백 본문 {FEEDBACK_MARKER}", summary="피드백"
    )
    question = intent["questions"][0]
    harness.client.post(
        f"/api/cases/{case['id']}/questions/{question['id']}/answer",
        json={
            "content": f"답변 본문 {ANSWER_MARKER}",
            "summary": "답변",
            "target_runner_id": "runner-test-1",
        },
    )
    harness.agent.persist_pending_intakes()

    # 열람 한 바퀴 — 본문이 제어부를 한 번 더 지난다.
    _request, content = harness.read_original(accepted["artifact_id"], accepted["revision"])
    assert content is not None and INTENT_MARKER in content

    controller_bytes = _controller_bytes(harness)
    log_bytes = Path(harness.controller_config.log_path).read_bytes()
    runner_bytes = _runner_bytes(harness)

    for marker in (INTENT_MARKER, FEEDBACK_MARKER, ANSWER_MARKER):
        raw = marker.encode("utf-8")
        assert raw not in controller_bytes, f"{marker} 가 제어부 DB에 남았다"
        assert raw not in log_bytes, f"{marker} 가 제어부 로그에 남았다"
        # 셋 다 없으면 애초에 저장되지 않은 것이므로 경계 확인이 무의미하다.
        assert raw in runner_bytes, f"{marker} 가 Runner에도 없다"

    # 질문 요약은 제어부에 있어도 되지만(intent-artifacts 3절) 본문 표식은 아니다.
    stored_question = harness.latest_intent(case["id"])["questions"][0]
    assert stored_question["summary"]
    assert INTENT_MARKER not in stored_question["summary"]


def test_new_p2_02_tables_have_no_body_columns(harness):
    """상태 표에 본문 컬럼이 생기지 않았는지 스키마로 확인한다.

    "요약 컬럼에 본문을 밀어 넣는" 우회를 막기 위해 길이 제한도 함께 본다.
    """
    import sqlite3

    conn = sqlite3.connect(harness.controller_config.db_path)
    conn.row_factory = sqlite3.Row
    body_like = {"content", "body", "text", "raw", "payload", "content_text", "full_text"}
    for table in (
        "intent_field",
        "intent_question",
        "feedback",
        "intent_view",
        "artifact_read_request",
    ):
        columns = {r["name"] for r in conn.execute(f'PRAGMA table_info("{table}")')}
        assert columns, f"{table} 이 없다"
        assert not (columns & body_like), f"{table} 에 본문 컬럼이 있다: {columns & body_like}"

    sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name IN ('intent_question','feedback')"
    ).fetchall()
    for row in sql:
        assert "length(summary) <= 200" in row["sql"]
    conn.close()


def test_the_controller_never_parses_the_intent_document(harness):
    """제어부는 의도 본문을 **해석하지 않는다.**

    항목별 상태는 Runner의 보고로만 들어온다. Runner가 보고하기 전에는
    제어부가 본문을 갖고 있었더라도 항목 상태를 만들어 내지 못한다.
    이것이 "제어부는 compose 만 하고 parse/structure 는 부르지 않는다"의 관측 가능한 형태다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.submit_intent_draft(
        case["id"],
        {"goal": {"text": "목표", "state": "proposed", "origin": "user_requirement"}},
        persist=False,  # Runner가 저장·보고하지 않은 상태
    )
    intent = harness.latest_intent(case["id"])
    assert intent["fields"] == [], "제어부가 본문에서 항목을 만들어 냈다"
    assert intent["questions"] == []
    assert intent["availability"] == "pending"


# ===================================================================== P2-03


def test_the_gate_review_body_never_reaches_the_controller(harness):
    """AC-12: 게이트 검토 지시와 검토 서술 본문이 제어부에 남지 않는다.

    게이트는 새로운 종류의 본문을 만든다 — 검토 지시문과 AI가 쓴 지적 내용이다.
    지적 **요약**은 화면에 필요하므로 제어부에 올라가지만(다른 요약과 같은 규칙),
    검토가 읽은 초안 본문과 지시문 전체는 Runner에만 있어야 한다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])

    draft_marker = "ZZMARKER-DRAFT-BODY-P203"
    harness.agent.cli_executor.draft_response = (
        '{"fields": {"goal": {"text": "%s 오류 줄만 뽑기", "origin": "user_requirement"}},'
        ' "questions": []}' % draft_marker
    )
    harness.ai_draft(case["id"])
    intent = harness.latest_intent(case["id"])
    harness.ai_gate_review(case["id"], intent)

    gate = harness.gate(case["id"])
    assert gate["verdict"] == "pass"

    # 검토가 읽은 초안 본문은 Runner에 있다.
    body = harness.agent.store.get(intent["artifact_id"], intent["artifact_rev"])
    assert draft_marker.encode("utf-8") in body

    # 제어부의 어떤 파일에도 없다. 검토 지시문(프롬프트)도 마찬가지다.
    prompt_marker = "당신은 **다른 세션이 작성한** 의도 초안을 검토한다"
    root = harness.controller_config.data_root
    checked = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        checked += 1
        raw = path.read_bytes()
        assert draft_marker.encode("utf-8") not in raw, f"초안 본문이 {path} 에 남았다"
        assert prompt_marker.encode("utf-8") not in raw, f"검토 지시문이 {path} 에 남았다"
    assert checked > 0


def test_gate_findings_only_carry_short_summaries(harness):
    """AC-12: AI 검토가 본문을 요약 칸에 밀어 넣지 못한다.

    `gate_finding.summary` 에 길이 상한이 스키마 수준으로 걸려 있고, 넘치는 내용은
    잘린다. 요약은 원문을 대체하지 않으며 근거는 Runner의 실행 결과 원문에 있다.
    """
    import sqlite3

    project = harness.create_project()
    case = harness.create_case(project["id"])
    long_text = "A" * 900
    harness.agent.cli_executor.review_response = (
        '{"findings": [{"criterion": "unverifiable_success_criteria", "severity": "required",'
        ' "certainty": "suspected", "target": "expected_outcome", "summary": "%s"}]}' % long_text
    )
    harness.ai_draft(case["id"])
    intent = harness.latest_intent(case["id"])
    harness.ai_gate_review(case["id"], intent)

    finding = harness.gate(case["id"])["findings"]
    ai = [f for f in finding if f["source"] == "ai"]
    assert len(ai) == 1
    assert len(ai[0]["summary"]) <= 200

    conn = sqlite3.connect(harness.controller_config.db_path)
    conn.row_factory = sqlite3.Row
    sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name = 'gate_finding'"
    ).fetchone()["sql"]
    assert "length(summary) <= 200" in sql
    # 본문 컬럼이 없다는 것을 컬럼 이름으로 확인한다.
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(gate_finding)")}
    assert not columns & {"content", "body", "text", "detail", "raw"}
    conn.close()


def test_the_controller_stores_no_prompt_text(harness):
    """지시문 조립은 Runner의 일이다.

    목적별 지시문이 제어부 코드에 있으면 본문이 제어부를 지나간다. 이 시험은
    제어부 패키지에 지시문 템플릿이 없다는 것을 코드 수준에서 고정한다.
    """
    from pathlib import Path

    controller_dir = Path(__file__).resolve().parent.parent / "controller"
    for path in controller_dir.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "당신은" not in text, f"{path} 에 CLI 지시문으로 보이는 문구가 있다"
        assert "prompts" not in text.replace("# ", ""), f"{path} 가 지시문 모듈을 쓴다"


# --------------------------------------------------------------------- P2-04


def test_success_criteria_and_acceptance_bodies_stay_on_the_runner(harness):
    """AC-13 — 성공 기준의 본문과 인수·예외의 문구가 제어부 바이트에 남지 않는다.

    기준의 본문(기대값·확인 방법)은 의도 원문 안에 있고, 인수 문구는 제어부가
    판단에만 쓰고 버린다. 제어부에는 짧은 요약과 판정만 남아야 한다.
    """
    criterion_marker = f"{MARKER}-CRITERION-TEXT"
    method_marker = f"{MARKER}-METHOD-TEXT"
    statement_marker = f"{MARKER}-ACCEPTANCE-STATEMENT"

    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.submit_intent_draft(
        case["id"],
        {
            "goal": {"text": "목표", "origin": "user_requirement"},
            "expected_outcome": {"text": "기대 결과", "origin": "ai_proposal"},
        },
        criteria=[
            {
                "key": "C-01",
                "relates_to": "expected_outcome",
                "text": criterion_marker,
                "method": method_marker,
                # 요약에는 표식을 넣지 않는다. 요약은 제어부에 남는 것이 정상이다.
                "summary": "기준 한 줄 요약",
                "method_summary": "확인 방법 한 줄 요약",
            }
        ],
    )
    intent = harness.latest_intent(case["id"])
    harness.ai_gate_review(case["id"], intent)
    harness.read_intent_original(intent)
    assert harness.agree(case["id"], intent).status_code == 201

    criterion = harness.criteria(case["id"])[0]
    assert (
        harness.record_result(
            case["id"], criterion["id"], "met", evidence_kind="human_judgement"
        ).status_code
        == 200
    )
    candidate = harness.build_candidate(case["id"])
    accepted = harness.accept(
        case["id"],
        candidate["id"],
        statement=f"이 결과를 인수합니다. {statement_marker}",
    )
    assert accepted.status_code == 201, accepted.text

    controller = _controller_bytes(harness)
    log = Path(harness.controller_config.log_path).read_bytes()
    for marker in (criterion_marker, method_marker, statement_marker):
        encoded = marker.encode("utf-8")
        assert encoded not in controller, f"{marker} 가 제어부 DB에 남았다"
        assert encoded not in log, f"{marker} 가 제어부 로그에 남았다"

    # 기준 본문은 Runner의 의도 원문 안에 있다. 셋 다 없으면 경계 확인이 무의미하다.
    runner = _runner_bytes(harness)
    assert criterion_marker.encode("utf-8") in runner
    assert method_marker.encode("utf-8") in runner
    # 인수 문구는 **어디에도 저장되지 않는다.** 제어부가 판단에만 쓰고 버린다.
    # 남겨야 한다면 원문 참조(statement_artifact_id)로 Runner에 저장해야 한다.
    assert statement_marker.encode("utf-8") not in runner


def test_the_result_view_carries_references_not_bodies(harness):
    """AC-13 — 결과 화면에 내려가는 것은 판정·요약·참조뿐이다."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.submit_intent_draft(
        case["id"], {"goal": {"text": "목표", "origin": "user_requirement"}}
    )
    view = harness.result(case["id"])
    criterion = view["criteria"][0]
    assert set(criterion) == {
        "id",
        "case_id",
        "intent_version_id",
        "criterion_key",
        "summary",
        "method_summary",
        "relates_to",
        "state",
        "created_at",
        "verdict",
        "evidence_kind",
        "evidence_run_id",
        "evidence_artifact_id",
        "evidence_artifact_rev",
        "result_summary",
        "recorded_by",
        "recorded_at",
    }, sorted(criterion)


# ===================================================================== P3-01


def test_sizing_and_preparation_bodies_stay_on_the_runner(harness):
    """AC-13: 축별 근거의 서술과 설계·계획 본문이 제어부 바이트에 없다.

    표식을 **본문에만** 넣는다. 축의 `evidence` 와 설계 항목의 본문이 대상이다.
    제어부에는 영향·짧은 판단 한 줄·항목 상태만 남아야 한다.
    """
    from tests.conftest import DEFAULT_SIZING, fake_preparation_response

    axis_marker = "AXIS-EVIDENCE-9b21e-원문본문"
    design_marker = "DESIGN-BODY-4c7f1-원문본문"

    project = harness.create_project()
    case = harness.create_case(project["id"])

    sizing = {
        "recommended_level": "simple",
        "axes": [
            {**axis, "evidence": f"{axis_marker} / {axis['axis']}"}
            for axis in DEFAULT_SIZING["axes"]
        ],
    }
    harness.submit_intent_draft(
        case["id"],
        {
            "goal": {"text": "목표", "origin": "user_requirement"},
            "expected_outcome": {"text": "결과", "origin": "ai_proposal"},
            "scope": {"text": "범위", "origin": "ai_proposal"},
            "exclusions": {"text": "제외", "origin": "ai_proposal"},
            "constraints": {"text": "제약", "origin": "observation"},
            "open_questions": {"text": "미정", "origin": "ai_assumption"},
        },
        sizing=sizing,
    )
    intent = harness.latest_intent(case["id"])
    assert harness.ai_gate_review(case["id"], intent).status_code == 201
    harness.read_intent_original(intent)
    assert harness.agree(case["id"], intent).status_code == 201

    harness.agent.cli_executor.design_response = fake_preparation_response(
        "설계",
        {
            "change_summary": f"{design_marker} 필터 함수를 더한다",
            "verifiability": f"{design_marker} 표본 파일로 확인한다",
        },
    )
    assert harness.ai_prepare(case["id"], "design").status_code == 201

    controller = _controller_bytes(harness)
    log = Path(harness.controller_config.log_path).read_bytes()
    for marker in (axis_marker, design_marker):
        encoded = marker.encode("utf-8")
        assert encoded not in controller, f"{marker} 가 제어부 DB에 남았다"
        assert encoded not in log, f"{marker} 가 제어부 로그에 남았다"
        # 셋 다 없으면 애초에 저장되지 않은 것이므로 경계 확인이 무의미하다.
        assert encoded in _runner_bytes(harness), f"{marker} 가 Runner에도 없다"


def test_new_p3_01_tables_have_no_body_columns(harness):
    """AC-13: P3-01이 더한 표에도 본문 컬럼이 없다. 요약 길이 제한도 함께 본다."""
    import sqlite3

    conn = sqlite3.connect(harness.controller_config.db_path)
    conn.row_factory = sqlite3.Row
    body_like = {"content", "body", "text", "raw", "payload", "content_text", "full_text",
                 "evidence", "judgement", "sections"}
    for table in (
        "sizing_assessment",
        "sizing_axis",
        "preparation_artifact",
        "preparation_section",
        "stage_review_setting",
        "stage_review",
        "run_context_ref",
    ):
        columns = {r["name"] for r in conn.execute(f'PRAGMA table_info("{table}")')}
        assert columns, f"{table} 이 없다"
        assert not (columns & body_like), f"{table} 에 본문 컬럼이 있다: {columns & body_like}"

    rows = conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE name IN"
        " ('sizing_assessment','sizing_axis','preparation_artifact','stage_review')"
    ).fetchall()
    limits = {r["name"]: r["sql"] for r in rows}
    assert "length(reason_summary) <= 200" in limits["sizing_assessment"]
    assert "length(judgement_summary) <= 200" in limits["sizing_axis"]
    assert "length(summary) <= 200" in limits["preparation_artifact"]
    assert "length(note_summary) <= 200" in limits["stage_review"]
    conn.close()


def test_the_controller_never_parses_the_preparation_document(harness):
    """AC-13: 제어부는 설계·계획 본문을 **해석하지 않는다.**

    항목 상태는 Runner의 보고로만 들어온다. 보고 전에는 필수 항목이 전부
    빠진 것으로 보이며, 그것이 올바른 상태다 — 보지 않은 것을 채워진 것으로
    읽으면 빈 산출물이 선행 조건을 통과한다.
    """
    import inspect

    from controller import api, repository

    for module in (api, repository):
        source = inspect.getsource(module)
        assert "prep_doc.parse(" not in source, f"{module.__name__} 이 산출물 본문을 해석한다"
        assert "prep_doc.structure(" not in source


def test_task_bodies_stay_on_the_runner(harness):
    """AC-15: Task 의 목적·산출물·완료 조건 **서술**이 제어부 바이트에 없다.

    제어부에는 작성자가 따로 쓴 짧은 요약만 온다. 본문을 잘라 쓰면 서술의
    앞부분이 제어부에 남는다 — P2-02에서 질문 요약이 본문 발췌였던 것을 고친
    것과 같은 규칙이다.
    """
    from tests.conftest import fake_preparation_response
    from tests.test_preparation import _agreed_case

    marker = "TASK-BODY-7d4e2-원문본문"
    case, _intent = _agreed_case(harness)
    harness.agent.cli_executor.plan_response = fake_preparation_response(
        "계획",
        {"tasks": "작업 목록은 tasks 에 있다", "verification": "표본 파일 시험"},
        tasks=[
            {
                "key": "T1",
                "purpose": f"{marker} 목적 서술",
                "purpose_summary": "필터 구현",
                "deliverable": f"{marker} 산출물 서술",
                "deliverable_summary": "filter_errors",
                "completion": f"{marker} 완료 조건 서술",
                "completion_summary": "표본 파일에서 기대한 줄만 남는다",
            }
        ],
    )
    assert harness.ai_prepare(case["id"], "design").status_code == 201
    assert harness.review_stage(case["id"], "design").status_code == 201
    assert harness.ai_prepare(case["id"], "plan").status_code == 201

    encoded = marker.encode("utf-8")
    assert encoded not in _controller_bytes(harness), "Task 본문이 제어부 DB에 남았다"
    assert encoded not in Path(harness.controller_config.log_path).read_bytes()
    # 없으면 애초에 저장되지 않은 것이므로 경계 확인이 무의미하다.
    assert encoded in _runner_bytes(harness), "Task 본문이 Runner에도 없다"


def test_new_p3_02_tables_have_no_body_columns(harness):
    """AC-15: P3-02가 더한 표에도 본문 컬럼이 없다. 요약 길이 제한도 함께 본다."""
    import sqlite3

    conn = sqlite3.connect(harness.controller_config.db_path)
    conn.row_factory = sqlite3.Row
    body_like = {"content", "body", "text", "raw", "payload", "content_text", "full_text",
                 "purpose", "deliverable", "completion", "evidence"}
    for table in (
        "work_graph_revision",
        "task",
        "task_dependency",
        "task_criterion",
        "task_question_block",
        "task_block_unresolved",
        "question_block_ref",
    ):
        columns = {r["name"] for r in conn.execute(f'PRAGMA table_info("{table}")')}
        assert columns, f"{table} 이 없다"
        assert not (columns & body_like), f"{table} 에 본문 컬럼이 있다: {columns & body_like}"

    rows = conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE name IN"
        " ('work_graph_revision','task','task_block_unresolved')"
    ).fetchall()
    limits = {r["name"]: r["sql"] for r in rows}
    assert "length(reason_summary) <= 200" in limits["work_graph_revision"]
    assert "length(completion_summary) <= 200" in limits["task"]
    # `raw_ref` 는 Task 키를 가리키는 **식별자**다. 길이 상한으로 본문을 밀어
    # 넣지 못하게 한다.
    assert "length(raw_ref) <= 200" in limits["task_block_unresolved"]
    conn.close()
