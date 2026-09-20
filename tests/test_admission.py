"""AC-6~8: FR-29 진입 조건 검사.

**이 시험들은 화면을 거치지 않는다.** 전부 API 직접 호출이다. 그것이 핵심이다 —
버튼을 없애는 것은 조건이 아니고, 서버가 거부해야 조건이다.

확인하는 것:

  조건을 못 갖추면 사유 코드로 구별해 거부하고 **Run을 만들지 않는다**
  하위 작업·재시작·유형·권한 확대 중 어느 것도 조건을 면제하지 않는다
  **없는 선행 조건을 통과로 처리하지 않는다** — 거부로 드러낸다
  통과도 거부도 기록에 남는다
"""

from __future__ import annotations

from tests.conftest import FAKE_TOOL_ID, FAKE_TOOL_MODE, RUNNER_ID

GOOD_FIELDS = {
    "goal": {"text": "로그에서 오류 줄만 뽑는다", "origin": "user_requirement"},
    "expected_outcome": {"text": "ERROR 로 시작하는 줄만 출력", "origin": "ai_proposal"},
    "scope": {"text": "읽기 전용", "origin": "ai_proposal"},
    "exclusions": {"text": "로그 회전 제외", "origin": "ai_proposal"},
    "constraints": {"text": "Windows 로컬", "origin": "observation"},
    "open_questions": {"text": "대소문자 구분 미정", "origin": "ai_assumption"},
}


def _run(harness, case_id, artifact_id, run_id, **overrides):
    """진입 검사를 거치는 Run 생성 요청. 화면을 거치지 않는 직접 호출이다."""
    body = {
        "run_id": run_id,
        "instruction_artifact_id": artifact_id,
        "purpose": "limited_analysis",
        "role": "author",
        "tool_id": FAKE_TOOL_ID,
        "mode": FAKE_TOOL_MODE,
        "permission": "read_only",
    }
    body.update(overrides)
    return harness.client.post(f"/api/cases/{case_id}/runs", json=body)


def _refusals(response):
    return response.json()["detail"]["admission"]["refusals"]


def _ready_feature_case(harness, agree: bool = True):
    """실행을 열 수 있는 상태까지 만든 기능 Case.

    AI 초안 → 별도 세션 QG-01 검토 통과 → 사람의 열람과 명시 동의.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.ai_draft(case["id"])
    intent = harness.latest_intent(case["id"])
    harness.ai_gate_review(case["id"], intent)
    if agree:
        harness.read_intent_original(intent)
        assert harness.agree(case["id"], intent).status_code == 201
    instruction = harness.submit_artifact(case["id"], "오류 줄을 세어 주세요.")
    return case, intent, instruction


# ------------------------------------------------------------------ 기본 거부


def test_a_feature_run_is_refused_without_an_agreed_intent(harness):
    """AC-6: 의도 동의가 없으면 실행을 배정하지 않는다."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    instruction = harness.submit_artifact(case["id"], "그냥 실행해 주세요.")

    response = _run(harness, case["id"], instruction["artifact_id"], "run-x1")
    assert response.status_code == 409
    refusals = _refusals(response)
    assert "intent_not_agreed" in refusals
    assert "intent_gate_not_passed" in refusals

    # Run이 만들어지지 않았다. 거부가 곧 "만들었지만 멈춤"이 아니다.
    assert harness.client.get("/api/runs/run-x1").status_code == 404
    assert harness.client.get(f"/api/cases/{case['id']}").json()["runs"] == []


def test_a_run_is_refused_while_the_gate_has_not_been_reviewed(harness):
    """AC-6: 규칙만 통과한 상태(`not_run`)로는 실행이 열리지 않는다.

    **필수 게이트는 끌 수 없다.** 검토를 건너뛴 것을 통과로 취급하지 않는다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.submit_intent_draft(case["id"], GOOD_FIELDS)
    intent = harness.latest_intent(case["id"])
    harness.read_intent_original(intent)
    assert harness.agree(case["id"], intent).status_code == 201

    instruction = harness.submit_artifact(case["id"], "실행해 주세요.")
    response = _run(harness, case["id"], instruction["artifact_id"], "run-x2")

    assert response.status_code == 409
    assert _refusals(response) == ["intent_gate_not_passed"]
    assert harness.gate(case["id"])["verdict"] == "not_run"


def test_open_intent_questions_block_the_run(harness):
    """AC-6: 의도 단계에서 결정할 질문이 남아 있으면 실행하지 않는다.

    게이트는 질문을 막지 않지만(test_gate.py) **실행은 막는다.** 두 판단은 다르다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.submit_intent_draft(
        case["id"],
        GOOD_FIELDS,
        questions=[
            {
                "key": "case-sensitivity",
                "text": "대소문자를 구분합니까?",
                "summary": "대소문자 구분",
                "decide_at": "intent",
            }
        ],
    )
    instruction = harness.submit_artifact(case["id"], "실행해 주세요.")
    response = _run(harness, case["id"], instruction["artifact_id"], "run-x3")

    assert response.status_code == 409
    assert "open_intent_questions" in _refusals(response)


def test_a_ready_case_is_admitted_and_runs(harness):
    """AC-6·AC-9: 조건을 갖추면 실제로 실행되고 결과가 저장된다."""
    case, _intent, instruction = _ready_feature_case(harness)

    response = _run(harness, case["id"], instruction["artifact_id"], "run-ok-1")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["admission"]["outcome"] == "admitted"
    assert body["admission"]["profile"] == "feature_intent"
    assert body["admission"]["gate_verdict"] == "pass"
    assert body["admission"]["intent_agreement_state"] == "agreed_current"

    harness.agent.poll_once()
    run = harness.client.get("/api/runs/run-ok-1").json()
    assert run["status"] == "finished"
    assert run["outcome"] == "completed"
    assert run["purpose"] == "limited_analysis"
    # 실행 ID와 결과 원문이 남는다.
    assert run["session_ref"] == "fake-session-run-ok-1"
    assert run["output_artifact_id"]
    assert harness.agent.store.exists(run["output_artifact_id"], run["output_artifact_rev"])


# ------------------------------------------------------------------ 우회 차단


def test_a_sub_task_does_not_inherit_admission(harness):
    """AC-7: `task_id` 를 바꿔도 조건을 다시 받는다.

    "하위 작업으로 우회하지 않는다"(FR-29). 검사는 Case가 아니라 **Run마다** 한다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    instruction = harness.submit_artifact(case["id"], "실행해 주세요.")

    first = _run(harness, case["id"], instruction["artifact_id"], "run-sub-1", task_id="task-1")
    second = _run(harness, case["id"], instruction["artifact_id"], "run-sub-2", task_id="task-2")
    assert first.status_code == 409
    assert second.status_code == 409
    assert "intent_not_agreed" in _refusals(second)


def test_changing_the_case_kind_cannot_bypass_the_conditions(harness):
    """AC-7: 유형 변경으로 조건을 벗어나지 못한다.

    두 겹으로 막는다.
      (1) `kind` 를 바꾸는 API가 없다.
      (2) 조건표는 `kind` 가 아니라 **의도 버전의 존재**로 고른다. 이미 의도
          흐름을 탄 Case는 유형 표기를 바꿔도 기능 조건을 그대로 받는다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"], kind="feature")
    harness.submit_intent_draft(case["id"], GOOD_FIELDS)
    instruction = harness.submit_artifact(case["id"], "실행해 주세요.")

    # (1) 유형을 바꾸는 경로가 없다.
    for method, path in (
        ("patch", f"/api/cases/{case['id']}"),
        ("put", f"/api/cases/{case['id']}"),
        ("post", f"/api/cases/{case['id']}/kind"),
    ):
        response = getattr(harness.client, method)(path, json={"kind": "analysis"})
        assert response.status_code in (404, 405), f"{method} {path} 가 유형을 바꿀 수 있다"

    # (2) DB에서 직접 유형을 바꿔도(가장 강한 우회) 조건은 그대로다.
    import sqlite3

    conn = sqlite3.connect(harness.controller_config.db_path)
    conn.execute("UPDATE \"case\" SET kind = 'analysis' WHERE id = ?", (case["id"],))
    conn.commit()
    conn.close()

    response = _run(harness, case["id"], instruction["artifact_id"], "run-kind-1")
    assert response.status_code == 409
    assert response.json()["detail"]["admission"]["profile"] == "feature_intent"
    assert "intent_not_agreed" in _refusals(response)


def test_a_wider_permission_is_refused_in_this_stage(harness):
    """AC-7·AC-8: 권한을 넓혀 달라고 해서 넓혀 주지 않는다.

    코드를 바꾸는 실행은 선행 조건(설계·계획 검토)이 준비된 뒤에 연결한다.
    """
    case, _intent, instruction = _ready_feature_case(harness)

    response = _run(
        harness,
        case["id"],
        instruction["artifact_id"],
        "run-perm-1",
        permission="workspace_write",
    )
    assert response.status_code == 409
    assert "permission_not_allowed_in_stage" in _refusals(response)


def test_feature_implementation_is_refused_without_preparation(harness):
    """AC-8(P2-03) → P3-01 AC-7: **없는 선행 조건을 통과로 처리하지 않는다.**

    의도 조건을 모두 갖춘 Case에서도 거부된다. P2에서는 선행 조건의 구현이 없어
    `prerequisite_not_implemented` 한 줄로 거부했고, P3-01이 그 조건을 실제로
    만들었으므로 이제 **무엇이 없는지**가 사유 코드로 나온다.
    """
    case, _intent, instruction = _ready_feature_case(harness)

    response = _run(
        harness,
        case["id"],
        instruction["artifact_id"],
        "run-impl-1",
        purpose="feature_implementation",
    )
    assert response.status_code == 409
    refusals = _refusals(response)
    # 설계도 계획도 없다. 두 가지가 **따로** 나와야 사람이 무엇을 갖춰야 하는지
    # 한 번에 안다(FR-14). 수준은 AI 초안이 축별 판단과 함께 제안했으므로 그쪽
    # 사유는 없다 — 판단이 없는 경우는 tests/test_preparation.py 가 본다.
    assert "design_missing" in refusals
    assert "plan_missing" in refusals
    assert "sizing_not_decided" not in refusals
    # 더 이상 이 코드로 거부하지 않는다. 없는 구현이 아니라 없는 산출물이 문제다.
    assert "prerequisite_not_implemented" not in refusals
    # 의도 조건은 갖췄으므로 그쪽 사유는 없다. 무엇이 막았는지가 분명해야 한다.
    assert "intent_not_agreed" not in refusals
    assert "intent_gate_not_passed" not in refusals


def test_a_gate_review_cannot_resume_the_authoring_session(harness):
    """AC-2·AC-7: 세션을 이어받는 검토 요청은 거부한다."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.ai_draft(case["id"])
    intent = harness.latest_intent(case["id"])

    response = harness.client.post(
        f"/api/cases/{case['id']}/runs",
        json={
            "run_id": "run-resume-1",
            "instruction_artifact_id": intent["artifact_id"],
            "purpose": "intent_gate_review",
            "role": "reviewer",
            "tool_id": FAKE_TOOL_ID,
            "mode": FAKE_TOOL_MODE,
            "permission": "read_only",
            "session": "resume:fake-session-run-draft-1",
        },
    )
    assert response.status_code == 409
    assert "review_session_not_separate" in _refusals(response)


def test_the_reviewer_role_is_required_for_a_gate_review(harness):
    """AC-7: 역할을 속여 작성 세션으로 검토하게 두지 않는다."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.ai_draft(case["id"])
    intent = harness.latest_intent(case["id"])

    response = _run(
        harness,
        case["id"],
        intent["artifact_id"],
        "run-role-1",
        purpose="intent_gate_review",
        role="author",
    )
    assert response.status_code == 409
    assert "role_mismatch" in _refusals(response)


def test_an_unreported_tool_is_not_usable(harness):
    """AC-13: 미설치·미보고를 사용 가능으로 표시하지 않는다(FR-28)."""
    case, _intent, instruction = _ready_feature_case(harness)

    response = _run(
        harness, case["id"], instruction["artifact_id"], "run-tool-1", tool_id="opencode"
    )
    assert response.status_code == 409
    assert "tool_not_available" in _refusals(response)


def test_an_unmapped_permission_is_refused_rather_than_widened(harness):
    """AC-13: 매핑이 없으면 더 넓은 권한으로 대체하지 않고 거부한다(P1 계약 6절)."""
    case, _intent, instruction = _ready_feature_case(harness)

    response = _run(
        harness,
        case["id"],
        instruction["artifact_id"],
        "run-esc-1",
        permission="explicit_escalated",
    )
    assert response.status_code == 409
    refusals = _refusals(response)
    assert "permission_not_allowed_in_stage" in refusals
    assert "permission_not_mapped" in refusals


# ---------------------------------------------------------------- 기록·멱등


def test_every_check_is_recorded_including_refusals(harness):
    """AC-6: 왜 실행이 시작되지 않았는지 기록에 남는다(FR-14)."""
    case, _intent, instruction = _ready_feature_case(harness)
    _run(harness, case["id"], instruction["artifact_id"], "run-rec-1", permission="workspace_write")
    _run(harness, case["id"], instruction["artifact_id"], "run-rec-2")

    checks = harness.admission_checks(case["id"])
    by_request = {c["requested_run_id"]: c for c in checks}

    refused = by_request["run-rec-1"]
    assert refused["outcome"] == "refused"
    assert refused["run_id"] is None
    assert refused["refusals"] == ["permission_not_allowed_in_stage"]
    assert refused["requested_permission"] == "workspace_write"

    admitted = by_request["run-rec-2"]
    assert admitted["outcome"] == "admitted"
    assert admitted["run_id"] == "run-rec-2"
    assert admitted["refusals"] == []
    assert admitted["gate_verdict"] == "pass"

    # 초안 작성 실행도 검사를 받았다.
    assert any(c["requested_purpose"] == "intent_authoring" for c in checks)


def test_resending_the_same_run_id_does_not_recheck_or_re_execute(harness):
    """AC-10: 재전송은 두 번째 실행도 두 번째 검사도 만들지 않는다.

    하지 않은 검사를 통과로 적지 않으므로 응답의 `admission` 은 `null` 이다.
    """
    case, _intent, instruction = _ready_feature_case(harness)
    body_args = dict(run_id="run-dup-a", purpose="limited_analysis")

    first = _run(harness, case["id"], instruction["artifact_id"], **body_args)
    harness.agent.poll_once()
    second = _run(harness, case["id"], instruction["artifact_id"], **body_args)
    harness.agent.poll_once()

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["created"] is True
    assert second.json()["created"] is False
    assert second.json()["admission"] is None

    # 이 run_id 로 실행기가 **한 번만** 불렸다. 총 호출 수가 아니라 이 실행의
    # 횟수를 본다 — 같은 Case에는 초안 작성·게이트 검토 실행도 들어 있다.
    calls = [c for c in harness.agent.cli_executor.calls if c["run_id"] == "run-dup-a"]
    assert len(calls) == 1
    runs = harness.client.get(f"/api/cases/{case['id']}").json()["runs"]
    assert len([r for r in runs if r["run_id"] == "run-dup-a"]) == 1

    checks = [c for c in harness.admission_checks(case["id"]) if c["requested_run_id"] == "run-dup-a"]
    assert len(checks) == 1, "재전송이 검사 기록을 하나 더 만들었다"


def test_a_non_feature_case_does_not_need_the_whole_feature_document_set(harness):
    """AC-6: 비기능 조사에 기능 개발 문서 전체를 일괄 요구하지 않는다(FR-29).

    다만 **아무 조건도 없는 것은 아니다** — 지시 원문은 읽을 수 있어야 한다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"], kind="analysis")
    instruction = harness.submit_artifact(case["id"], "이 저장소의 의존성을 조사해 주세요.")

    response = _run(harness, case["id"], instruction["artifact_id"], "run-analysis-1")
    assert response.status_code == 201, response.text
    assert response.json()["admission"]["profile"] == "non_feature_minimal"


def test_admission_is_re_evaluated_from_the_database_after_a_restart(harness):
    """AC-7: 제어부를 다시 만들어도 같은 근거로 같은 판단을 한다.

    통과 상태를 메모리에 들고 있지 않다는 뜻이다. 재시작으로 조건을 벗어나지 못한다.
    """
    from fastapi.testclient import TestClient

    from controller.app import create_app

    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.submit_intent_draft(case["id"], GOOD_FIELDS)
    instruction = harness.submit_artifact(case["id"], "실행해 주세요.")

    before = _run(harness, case["id"], instruction["artifact_id"], "run-restart-a")
    assert before.status_code == 409

    # 같은 DB를 쓰는 새 프로세스(새 app 인스턴스)에서 다시 시도한다.
    with TestClient(create_app(harness.controller_config)) as fresh:
        again = fresh.post(
            f"/api/cases/{case['id']}/runs",
            json={
                "run_id": "run-restart-b",
                "instruction_artifact_id": instruction["artifact_id"],
                "purpose": "limited_analysis",
                "role": "author",
                "tool_id": FAKE_TOOL_ID,
                "mode": FAKE_TOOL_MODE,
                "permission": "read_only",
            },
        )
        assert again.status_code == 409
        assert set(_refusals(before)) == set(_refusals(again))

        # 게이트 판정과 진입 기록도 복원된다(AC-14의 자동 시험 쪽).
        gate = fresh.get(f"/api/cases/{case['id']}/gate").json()
        assert gate["rule_verdict"] == "pass"
        assert gate["verdict"] == "not_run"
        checks = fresh.get(f"/api/cases/{case['id']}/admission-checks").json()
        assert any(c["requested_run_id"] == "run-restart-a" for c in checks)


def test_the_runner_only_gets_read_only_work_in_this_stage(harness):
    """AC-9: 배정된 실행이 실제로 읽기 권한으로 불린다."""
    case, _intent, instruction = _ready_feature_case(harness)
    _run(harness, case["id"], instruction["artifact_id"], "run-perm-check")
    harness.agent.poll_once()

    calls = {c["run_id"]: c for c in harness.agent.cli_executor.calls}
    assert calls["run-perm-check"]["permission"] == "read_only"
    assert all(c["permission"] == "read_only" for c in calls.values())
    # 지시 원문이 프롬프트에 실렸다. 제어부는 참조만 줬고 본문은 Runner가 읽었다.
    assert "오류 줄을 세어" in calls["run-perm-check"]["prompt"]


def test_the_runner_is_named_as_the_artifact_owner(harness):
    """배정은 등록된 Runner에게만 간다."""
    runners = harness.client.get("/api/runners").json()
    assert [r["id"] for r in runners] == [RUNNER_ID]


def test_the_skeleton_executor_cannot_author_or_review_an_intent(harness):
    """AC-6: 골격 실행기에 초안 작성·의미 검토를 배정하지 않는다.

    **이 시험은 화면 결함에서 나왔다.** 화면이 `tool_id` 를 빠뜨리면 서버 기본값인
    `local-echo` 로 배정되는데, 그 실행기는 정상 종료하면서 아무 것도 쓰지 않는다.
    사람에게는 "요청했다"고 보이고 실제로는 초안이 생기지 않는다.

    화면을 고치는 것만으로는 부족하다 — 같은 실수가 API 직접 호출로 돌아온다.
    그래서 **도구가 스스로 코딩 CLI인지 보고하고 제어부가 그것을 본다.**
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    instruction = harness.submit_artifact(case["id"], "초안을 써 주세요.")

    # 화면이 도구를 빠뜨렸을 때와 같은 요청 — 서버 기본값은 골격 실행기다.
    response = harness.client.post(
        f"/api/cases/{case['id']}/runs",
        json={
            "run_id": "run-echo-author",
            "instruction_artifact_id": instruction["artifact_id"],
            "purpose": "intent_authoring",
            "role": "author",
            "permission": "read_only",
        },
    )
    assert response.status_code == 409, response.text
    assert "tool_is_not_a_coding_cli" in _refusals(response)

    # 의미 검토도 마찬가지다.
    harness.ai_draft(case["id"])
    intent = harness.latest_intent(case["id"])
    review = harness.client.post(
        f"/api/cases/{case['id']}/runs",
        json={
            "run_id": "run-echo-review",
            "instruction_artifact_id": intent["artifact_id"],
            "instruction_artifact_rev": intent["artifact_rev"],
            "purpose": "intent_gate_review",
            "role": "reviewer",
            "tool_id": "local-echo",
            "mode": "p2-01-local",
            "permission": "read_only",
        },
    )
    assert review.status_code == 409
    assert "tool_is_not_a_coding_cli" in _refusals(review)

    # 아무 것도 만들어지지 않았다. 조용히 완료된 실행이 남지 않는다.
    runs = harness.client.get(f"/api/cases/{case['id']}").json()["runs"]
    assert not [r for r in runs if r["run_id"].startswith("run-echo-")]


def test_the_skeleton_executor_is_still_fine_for_plain_analysis(harness):
    """골격 실행기를 금지한 것이 아니다. **초안을 쓰는 일에만** 배정하지 않는다."""
    project = harness.create_project()
    case = harness.create_case(project["id"], kind="analysis")
    instruction = harness.submit_artifact(case["id"], "읽고 요약해 주세요.")

    response = harness.client.post(
        f"/api/cases/{case['id']}/runs",
        json={
            "run_id": "run-echo-analysis",
            "instruction_artifact_id": instruction["artifact_id"],
            "purpose": "limited_analysis",
            "role": "author",
            "tool_id": "local-echo",
            "mode": "p2-01-local",
            "permission": "read_only",
        },
    )
    assert response.status_code == 201, response.text


def test_a_gate_review_of_a_superseded_intent_version_is_refused(harness):
    """대체된 의도 버전을 검토하려는 요청은 거부한다.

    라이브 검증에서 실제로 났던 일이다. 화면이 목록의 **첫** 의도 원문을 지시로
    지정하는 바람에, v2 가 있는데도 v1 을 검토했다. 검토는 정상 종료하지만 최신
    버전의 게이트는 `not_run` 그대로여서 아무 것도 진척되지 않고, 화면에는 옛
    버전의 판정이 새 결과처럼 보인다.

    검토 대상은 **지시 원문이 정한다.** 그래서 진입 검사도 최신 버전을 가정하지 않고
    지시 원문에서 대상을 끌어내 대조한다. 화면도 함께 고쳤지만, 화면만 고치면 같은
    실수가 API 로 돌아온다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.submit_intent_draft(case["id"], GOOD_FIELDS, summary="v1")
    v1 = harness.latest_intent(case["id"])
    harness.submit_intent_draft(case["id"], GOOD_FIELDS, summary="v2")
    v2 = harness.latest_intent(case["id"])
    assert v1["id"] != v2["id"]

    refused = harness.client.post(
        f"/api/cases/{case['id']}/runs",
        json={
            "run_id": "review-old-version",
            "instruction_artifact_id": v1["artifact_id"],
            "instruction_artifact_rev": v1["artifact_rev"],
            "purpose": "intent_gate_review",
            "role": "reviewer",
            "tool_id": "codex",
            "mode": "exec",
            "permission": "read_only",
        },
    )
    assert refused.status_code == 409, refused.text
    assert "intent_version_not_latest" in refused.json()["detail"]["admission"]["refusals"]

    # 최신 버전을 지정하면 열린다. 검토 자체를 막는 것이 아니다.
    allowed = harness.ai_gate_review(case["id"], v2, run_id="review-current-version")
    assert allowed.status_code == 201, allowed.text
    assert harness.gate(case["id"])["ai_verdict"] != "not_run"
