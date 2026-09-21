"""AC-2 — 저장 완료로 응답한 기록이 프로세스 **강제 종료** 후 복원되는지.

NFR-01은 "저장 완료로 응답한 요청·결정·승인·상태는 프로세스 재시작 후 복원되어야 한다"를
요구한다. 여기서는 실제로 uvicorn을 자식 프로세스로 띄우고 `taskkill /F /T` 로 죽인다.
정상 종료(shutdown 훅이 도는 경로)로는 이 요구를 확인할 수 없다.

함께 확인하는 것: 저장 완료로 **응답하지 않은** 중계 중 원문은 재시작 후 사라지며,
그 사실이 `lost_before_persist` 로 드러난다. 서버에 영구 저장해 우회하지 않는다.
"""

from __future__ import annotations

import base64
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from domain import intent_doc, prep_doc
from domain.models import IntentField, PreparationStage, WorkLevel
from runner.agent import local_executor_capabilities
from runner.store import content_hash

REPO_ROOT = Path(__file__).resolve().parent.parent
PYTHON = REPO_ROOT / ".venv" / "Scripts" / "python.exe"
RUNNER_ID = "runner-restart-1"

pytestmark = pytest.mark.skipif(
    not PYTHON.exists(),
    reason="저장소 로컬 .venv 가 없다. scripts/bootstrap.ps1 을 먼저 실행한다",
)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class ControllerProcess:
    """실제 uvicorn 자식 프로세스."""

    def __init__(self, data_root: Path, port: int) -> None:
        self.data_root = data_root
        self.port = port
        self.base_url = f"http://127.0.0.1:{port}"
        self.proc: subprocess.Popen | None = None

    def start(self) -> None:
        env = dict(os.environ)
        env["HADS_CONTROLLER_DATA"] = str(self.data_root)
        env["HADS_WEB_DIST"] = ""  # 이 시험은 API만 본다
        env["PYTHONPATH"] = str(REPO_ROOT)
        self.proc = subprocess.Popen(
            [
                str(PYTHON),
                "-m",
                "uvicorn",
                "controller.app:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
                "--log-level",
                "warning",
            ],
            cwd=str(REPO_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        deadline = time.time() + 30
        while time.time() < deadline:
            if self.proc.poll() is not None:
                output = self.proc.stdout.read().decode("utf-8", "replace") if self.proc.stdout else ""
                raise RuntimeError(f"controller exited early:\n{output}")
            try:
                if httpx.get(f"{self.base_url}/api/health", timeout=1.0).status_code == 200:
                    return
            except httpx.HTTPError:
                time.sleep(0.2)
        raise RuntimeError("controller did not become healthy in time")

    def kill_hard(self) -> None:
        """강제 종료. 정리 훅이 돌 기회를 주지 않는다."""
        assert self.proc is not None
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(self.proc.pid)],
            check=False,
            capture_output=True,
        )
        self.proc.wait(timeout=30)
        if self.proc.stdout:
            self.proc.stdout.close()
        self.proc = None


@pytest.fixture
def controller(tmp_path):
    proc = ControllerProcess(tmp_path / "controller", _free_port())
    proc.start()
    try:
        yield proc
    finally:
        if proc.proc is not None:
            proc.kill_hard()


def _register_runner(base_url: str) -> None:
    """실제 Runner와 같은 능력 보고로 등록한다.

    빈 능력 목록으로 등록하면 P2-03의 진입 검사가 `tool_not_available` 로 거부한다.
    그것이 옳은 동작이므로(아무 것도 할 수 있다고 보고하지 않은 Runner에 배정하지
    않는다) 여기서는 제품이 실제로 보고하는 값을 쓴다.
    """
    httpx.post(
        f"{base_url}/api/runner/register",
        json={
            "runner_id": RUNNER_ID,
            "name": RUNNER_ID,
            "host": "test-host",
            "capabilities": local_executor_capabilities(),
        },
        timeout=10.0,
    ).raise_for_status()


def test_saved_records_survive_a_forced_kill(controller, tmp_path):
    base = controller.base_url
    _register_runner(base)

    project = httpx.post(
        f"{base}/api/projects",
        json={"name": "restart-demo", "repo_path": "C:/tmp/demo", "default_tool_id": "codex"},
        timeout=10.0,
    ).json()
    case = httpx.post(
        f"{base}/api/projects/{project['id']}/cases",
        # 이 시험은 실행 배관과 복원을 본다. 기능 Case의 진입 조건은
        # test_admission.py 가 따로 확인한다(FR-29).
        json={"title": "재시작 복원 Case", "kind": "analysis"},
        timeout=10.0,
    ).json()

    # 원문을 접수하고 Runner 역할로 영속 저장을 보고한다 → 저장 완료.
    accepted = httpx.post(
        f"{base}/api/cases/{case['id']}/artifacts",
        json={
            "kind": "instruction",
            "content": "재시작 뒤에도 남아야 하는 지시",
            "summary": "지시 원문",
            "target_runner_id": RUNNER_ID,
        },
        timeout=10.0,
    ).json()
    intakes = httpx.get(f"{base}/api/runner/{RUNNER_ID}/intakes", timeout=10.0).json()
    assert len(intakes) == 1
    httpx.post(
        f"{base}/api/runner/intakes/{accepted['intake_id']}/stored",
        json={"runner_id": RUNNER_ID, "content_hash": accepted["content_hash"]},
        timeout=10.0,
    ).raise_for_status()

    run = httpx.post(
        f"{base}/api/cases/{case['id']}/runs",
        json={"run_id": "run-restart-1", "instruction_artifact_id": accepted["artifact_id"]},
        timeout=10.0,
    ).json()
    assert run["created"] is True

    # 의도 동의는 전용 경로에서만 만들어진다(tests/test_intent.py). 여기서는 다른 종류의
    # 사람 결정이 강제 종료 후에도 남는지만 본다.
    decision = httpx.post(
        f"{base}/api/cases/{case['id']}/decisions",
        json={
            "kind": "design_review",
            "subject_type": "case",
            "subject_id": case["id"],
            "subject_revision": 1,
            "actor": "owner",
        },
        timeout=10.0,
    ).json()

    # ---- 강제 종료 ----
    controller.kill_hard()
    controller.start()

    restored_case = httpx.get(f"{base}/api/cases/{case['id']}", timeout=10.0).json()
    assert restored_case["title"] == "재시작 복원 Case"
    assert [d["id"] for d in restored_case["decisions"]] == [decision["id"]]
    assert restored_case["artifacts"][0]["availability"] == "available"

    restored_run = httpx.get(f"{base}/api/runs/run-restart-1", timeout=10.0).json()
    assert restored_run["case_id"] == case["id"]
    assert restored_run["status"] == "pending"
    assert restored_run["assignment_generation"] == 1

    # 재시작 뒤에도 같은 run_id 는 새 실행을 만들지 않는다.
    again = httpx.post(
        f"{base}/api/cases/{case['id']}/runs",
        json={"run_id": "run-restart-1", "instruction_artifact_id": accepted["artifact_id"]},
        timeout=10.0,
    ).json()
    assert again["created"] is False


def test_relayed_body_not_yet_persisted_is_reported_as_lost(controller):
    """저장 완료로 응답하지 않은 원문은 재시작 후 사라진 사실을 드러낸다."""
    base = controller.base_url
    _register_runner(base)

    project = httpx.post(
        f"{base}/api/projects",
        json={"name": "lost-demo", "repo_path": "C:/tmp/demo", "default_tool_id": "codex"},
        timeout=10.0,
    ).json()
    case = httpx.post(
        f"{base}/api/projects/{project['id']}/cases",
        json={"title": "중계 중 재시작", "kind": "feature"},
        timeout=10.0,
    ).json()
    accepted = httpx.post(
        f"{base}/api/cases/{case['id']}/artifacts",
        json={
            "kind": "intent",
            "content": "Runner가 아직 저장하지 않은 의도 원문",
            "summary": "의도 초안",
            "target_runner_id": RUNNER_ID,
        },
        timeout=10.0,
    ).json()
    assert accepted["availability"] == "pending"

    controller.kill_hard()
    controller.start()

    intake = httpx.get(f"{base}/api/intakes/{accepted['intake_id']}", timeout=10.0).json()
    assert intake["state"] == "lost_before_persist"

    detail = httpx.get(f"{base}/api/cases/{case['id']}", timeout=10.0).json()
    assert detail["artifacts"][0]["availability"] == "lost_before_persist"
    # 빈 문서나 삭제로 표시하지 않는다. 참조와 해시는 남아 있다.
    assert detail["artifacts"][0]["content_hash"] == accepted["content_hash"]

    # 사라진 원문으로는 실행을 배정하지 않는다.
    refused = httpx.post(
        f"{base}/api/cases/{case['id']}/runs",
        json={"run_id": "run-lost-art", "instruction_artifact_id": accepted["artifact_id"]},
        timeout=10.0,
    )
    assert refused.status_code == 409


def test_runner_ledger_survives_its_own_restart(tmp_path):
    """Runner 원장은 파일에 있으므로 Runner 재시작 후에도 재실행을 막는다."""
    from runner.ledger import ExecutionLedger

    ledger_a = ExecutionLedger(tmp_path / "ledger")
    should_run, existing = ledger_a.claim("run-x", 1)
    assert should_run is True and existing is None
    ledger_a.finish("run-x", {"outcome": "completed"})

    # 새 프로세스를 흉내 내어 같은 경로로 다시 연다.
    ledger_b = ExecutionLedger(tmp_path / "ledger")
    should_run, existing = ledger_b.claim("run-x", 2)
    assert should_run is False
    assert existing["result"]["outcome"] == "completed"


def test_intent_agreement_and_structure_survive_a_forced_kill(controller):
    """AC-10 — 의도 버전·항목 상태·질문·피드백·동의가 강제 종료 후에도 복원된다.

    그리고 중계 중이던 **열람 응답**은 사라진다. 원문이 사라진 것이 아니라
    중계가 끊긴 것이므로 요청만 `expired` 로 닫히고 다시 요청할 수 있다.
    """
    base = controller.base_url
    _register_runner(base)

    project = httpx.post(
        f"{base}/api/projects",
        json={"name": "intent-restart", "repo_path": "C:/tmp/demo", "default_tool_id": "codex"},
        timeout=10.0,
    ).json()
    case = httpx.post(
        f"{base}/api/projects/{project['id']}/cases",
        json={"title": "의도 재시작 Case", "kind": "feature"},
        timeout=10.0,
    ).json()

    draft = httpx.post(
        f"{base}/api/cases/{case['id']}/intent-drafts",
        json={
            "summary": "의도 초안 v1",
            "target_runner_id": RUNNER_ID,
            "fields": {
                "goal": {
                    "text": "재시작 뒤에도 남아야 하는 목표",
                    "state": "proposed",
                    "origin": "user_requirement",
                }
            },
            "questions": [
                {
                    "key": "later",
                    "text": "설계에서 정할 질문",
                    "summary": "설계 단계 질문",
                    "decide_at": "design",
                }
            ],
        },
        timeout=10.0,
    ).json()

    # Runner 역할로 원문을 저장하고 구조를 보고한다.
    intakes = httpx.get(f"{base}/api/runner/{RUNNER_ID}/intakes", timeout=10.0).json()
    assert len(intakes) == 1 and intakes[0]["intent"]["intent_version_id"]
    body = base64.b64decode(intakes[0]["content_b64"])
    httpx.post(
        f"{base}/api/runner/intakes/{draft['intake_id']}/stored",
        json={"runner_id": RUNNER_ID, "content_hash": draft["content_hash"]},
        timeout=10.0,
    ).raise_for_status()
    structure = intent_doc.structure(body, None)
    httpx.post(
        f"{base}/api/runner/intent-structure",
        json={
            "runner_id": RUNNER_ID,
            "intent_version_id": intakes[0]["intent"]["intent_version_id"],
            "fields": structure["fields"],
            "questions": structure["questions"],
        },
        timeout=10.0,
    ).raise_for_status()

    feedback = httpx.post(
        f"{base}/api/cases/{case['id']}/feedback",
        json={
            "target_intent_version_id": draft["intent_version"]["id"],
            "content": "재시작 뒤에도 남아야 하는 피드백",
            "summary": "피드백 하나",
            "target_runner_id": RUNNER_ID,
        },
        timeout=10.0,
    ).json()

    def relay_read() -> dict:
        """열람 요청을 열고 Runner 역할로 본문을 올린다(= 제어부 메모리에만 있는 상태)."""
        opened = httpx.post(
            f"{base}/api/artifacts/{draft['artifact_id']}/{draft['revision']}/read-requests",
            json={},
            timeout=10.0,
        ).json()
        httpx.post(
            f"{base}/api/runner/read-requests/{opened['id']}/content",
            json={
                "runner_id": RUNNER_ID,
                "content_b64": base64.b64encode(body).decode("ascii"),
                "content_hash": draft["content_hash"],
            },
            timeout=10.0,
        ).raise_for_status()
        return opened

    # 사람이 원문을 실제로 받아 봐야 동의할 수 있다.
    delivered = httpx.get(
        f"{base}/api/read-requests/{relay_read()['id']}", timeout=10.0
    ).json()
    assert delivered["content"] is not None

    agreed = httpx.post(
        f"{base}/api/cases/{case['id']}/intent-versions/{draft['intent_version']['id']}/agreement",
        json={
            "agree": True,
            "statement": "이 의도에 동의합니다.",
            "content_hash": draft["content_hash"],
            "actor": "owner",
        },
        timeout=10.0,
    )
    assert agreed.status_code == 201, agreed.text

    # 두 번째 열람은 **받아 가기 전에** 재시작을 맞는다.
    read_request = relay_read()

    # ---- 강제 종료 ----
    controller.kill_hard()
    controller.start()

    state = httpx.get(f"{base}/api/cases/{case['id']}/intent-state", timeout=10.0).json()
    assert state["agreement_state"] == "agreed_current"
    assert state["agreed_version"]["subject_content_hash"] == draft["content_hash"]

    latest = state["latest_intent_version"]
    assert {f["field"] for f in latest["fields"]} == {f.value for f in IntentField}
    assert [q["question_key"] for q in latest["questions"]] == ["later"]

    stored_feedback = httpx.get(f"{base}/api/cases/{case['id']}/feedback", timeout=10.0).json()
    assert [f["id"] for f in stored_feedback] == [feedback["feedback"]["id"]]

    # 중계 중이던 열람 응답은 이 프로세스에 없다. 빈 본문으로 채우지 않는다.
    after = httpx.get(f"{base}/api/read-requests/{read_request['id']}", timeout=10.0).json()
    assert after["content"] is None
    assert after["request"]["state"] == "expired"

    # 다시 요청하면 된다 — 원문은 Runner에 그대로 있다.
    retry = httpx.post(
        f"{base}/api/artifacts/{draft['artifact_id']}/{draft['revision']}/read-requests",
        json={},
        timeout=10.0,
    ).json()
    assert retry["state"] == "pending"


def test_criteria_results_acceptance_and_closure_survive_a_forced_kill(controller):
    """AC-11 — 기준·판정·후보·인수·종료 기록이 강제 종료 후에도 복원된다(P2-04).

    P2-04 성공 기준: "입력·동의·Run·원문 참조가 보존되고 실행 불명 상태가 성공이
    되지 않음." 여기서는 그 앞쪽(보존)을 실제 프로세스 강제 종료로 확인하고,
    뒤쪽(불명이 성공이 되지 않음)이 재시작 뒤에도 유지되는지 함께 본다.
    """
    base = controller.base_url
    _register_runner(base)

    project = httpx.post(
        f"{base}/api/projects",
        json={"name": "result-restart", "repo_path": "C:/tmp/demo", "default_tool_id": "codex"},
        timeout=10.0,
    ).json()
    case = httpx.post(
        f"{base}/api/projects/{project['id']}/cases",
        json={"title": "결과 재시작 Case", "kind": "analysis"},
        timeout=10.0,
    ).json()

    # 결과가 `unknown` 인 실행을 하나 만든다. 이것이 근거가 될 수 없어야 한다.
    # 의도 버전이 생기기 **전에** 만든다 — 의도 버전이 있으면 기능 조건표가 붙어
    # 동의·게이트 없이는 실행이 열리지 않기 때문이다(P2-03의 진입 검사). 그 검사를
    # 여기서 우회하지 않고 순서로 피한다.
    instruction = httpx.post(
        f"{base}/api/cases/{case['id']}/artifacts",
        json={
            "kind": "instruction",
            "content": "결과를 확정할 수 없는 실행의 지시",
            "summary": "지시 원문",
            "target_runner_id": RUNNER_ID,
        },
        timeout=10.0,
    ).json()
    httpx.post(
        f"{base}/api/runner/intakes/{instruction['intake_id']}/stored",
        json={"runner_id": RUNNER_ID, "content_hash": instruction["content_hash"]},
        timeout=10.0,
    ).raise_for_status()
    created_run = httpx.post(
        f"{base}/api/cases/{case['id']}/runs",
        json={"run_id": "run-unknown-1", "instruction_artifact_id": instruction["artifact_id"]},
        timeout=10.0,
    )
    assert created_run.status_code == 201, created_run.text
    run = created_run.json()["run"]
    httpx.post(
        f"{base}/api/runner/runs/{run['run_id']}/result",
        json={
            "runner_id": RUNNER_ID,
            "generation": run["assignment_generation"],
            "outcome": "unknown",
        },
        timeout=10.0,
    ).raise_for_status()

    criteria_in = [
        {
            "key": "C-01",
            "relates_to": "expected_outcome",
            "text": "재시작 뒤에도 남아야 하는 기준",
            "method": "재시작 후 조회해서 확인한다",
            "summary": "재시작 뒤에도 남는다",
            "method_summary": "재시작 후 조회",
        },
        {
            "key": "C-02",
            "relates_to": "constraints",
            "text": "예외로 수용할 기준",
            "method": "수용 기록이 남는지 확인한다",
            "summary": "예외로 수용할 기준",
            "method_summary": "수용 기록 확인",
        },
    ]
    draft = httpx.post(
        f"{base}/api/cases/{case['id']}/intent-drafts",
        json={
            "summary": "의도 초안 v1",
            "target_runner_id": RUNNER_ID,
            "fields": {
                "goal": {
                    "text": "결과를 기준별로 남긴다",
                    "state": "proposed",
                    "origin": "user_requirement",
                }
            },
            "criteria": criteria_in,
        },
        timeout=10.0,
    ).json()

    intakes = httpx.get(f"{base}/api/runner/{RUNNER_ID}/intakes", timeout=10.0).json()
    pending = next(i for i in intakes if i["intake_id"] == draft["intake_id"])
    body = base64.b64decode(pending["content_b64"])
    httpx.post(
        f"{base}/api/runner/intakes/{draft['intake_id']}/stored",
        json={"runner_id": RUNNER_ID, "content_hash": draft["content_hash"]},
        timeout=10.0,
    ).raise_for_status()
    structure = intent_doc.structure(body, None)
    httpx.post(
        f"{base}/api/runner/intent-structure",
        json={
            "runner_id": RUNNER_ID,
            "intent_version_id": pending["intent"]["intent_version_id"],
            "fields": structure["fields"],
            "questions": structure["questions"],
            "criteria": structure["criteria"],
        },
        timeout=10.0,
    ).raise_for_status()

    criteria = httpx.get(f"{base}/api/cases/{case['id']}/result", timeout=10.0).json()["criteria"]
    assert [c["criterion_key"] for c in criteria] == ["C-01", "C-02"]

    # 원문을 실제로 받아 보고 그 버전에 명시 동의한다. 동의가 없으면 아래 인수가
    # `intent_not_agreed` 로 거부되며, 그 거부 자체는 올바른 동작이므로 우회하지 않는다.
    opened = httpx.post(
        f"{base}/api/artifacts/{draft['artifact_id']}/{draft['revision']}/read-requests",
        json={},
        timeout=10.0,
    ).json()
    httpx.post(
        f"{base}/api/runner/read-requests/{opened['id']}/content",
        json={
            "runner_id": RUNNER_ID,
            "content_b64": base64.b64encode(body).decode("ascii"),
            "content_hash": draft["content_hash"],
        },
        timeout=10.0,
    ).raise_for_status()
    delivered = httpx.get(f"{base}/api/read-requests/{opened['id']}", timeout=10.0).json()
    assert delivered["content"] is not None
    agreed = httpx.post(
        f"{base}/api/cases/{case['id']}"
        f"/intent-versions/{draft['intent_version']['id']}/agreement",
        json={
            "agree": True,
            "statement": "이 의도에 동의합니다.",
            "content_hash": draft["content_hash"],
            "actor": "owner",
        },
        timeout=10.0,
    )
    assert agreed.status_code == 201, agreed.text

    def record(criterion_id: str, verdict: str, **extra) -> httpx.Response:
        return httpx.post(
            f"{base}/api/cases/{case['id']}/criteria/{criterion_id}/result",
            json={
                "verdict": verdict,
                "summary": "재시작 시험",
                "recorded_by": "owner",
                "evidence_kind": "human_judgement",
                **extra,
            },
            timeout=10.0,
        )

    refused = record(
        criteria[0]["id"],
        "met",
        evidence_kind="run_output",
        evidence_run_id=run["run_id"],
    )
    assert refused.status_code == 409, refused.text

    assert record(criteria[0]["id"], "met").status_code == 200
    assert record(criteria[1]["id"], "not_met").status_code == 200

    candidate = httpx.post(
        f"{base}/api/cases/{case['id']}/completion-candidates", timeout=10.0
    ).json()["candidate"]
    assert [r["run_id"] for r in candidate["unsettled_runs"]] == ["run-unknown-1"]

    httpx.post(
        f"{base}/api/cases/{case['id']}/completion-candidates/{candidate['id']}/exceptions",
        json={
            "actor": "owner",
            "criterion_id": criteria[1]["id"],
            "scope_summary": "이번 종료에만 적용",
        },
        timeout=10.0,
    ).raise_for_status()
    accepted = httpx.post(
        f"{base}/api/cases/{case['id']}/completion-candidates/{candidate['id']}/acceptance",
        json={"actor": "owner", "statement": "이 결과를 인수합니다."},
        timeout=10.0,
    )
    assert accepted.status_code == 201, accepted.text
    # 미정리 실행이 남아 있으므로 인수는 되고 종료는 확정되지 않는다.
    assert accepted.json()["closure"] is None

    # ---- 강제 종료 ----
    controller.kill_hard()
    controller.start()

    after = httpx.get(f"{base}/api/cases/{case['id']}/result", timeout=10.0).json()
    verdicts = {c["criterion_key"]: c["verdict"] for c in after["criteria"]}
    assert verdicts == {"C-01": "met", "C-02": "not_met"}
    # 예외를 수용했어도 원래 판정은 그대로다. 재시작이 그것을 바꾸지 않는다.
    restored = after["candidate"]
    assert restored["acceptance"]["mode"] == "human"
    assert [e["original_verdict"] for e in restored["exceptions"]] == ["not_met"]
    # 종료는 여전히 확정되지 않았다. 재시작이 미정리 실행을 정리해 주지 않는다.
    assert after["closure"] is None
    assert [r["run_id"] for r in after["unsettled_runs"]] == ["run-unknown-1"]

    # 불명인 실행은 재시작 뒤에도 근거가 되지 않는다.
    still_refused = record(
        after["criteria"][0]["id"],
        "met",
        evidence_kind="run_output",
        evidence_run_id="run-unknown-1",
    )
    assert still_refused.status_code == 409
    assert "not 'completed'" in still_refused.json()["detail"]


def test_sizing_preparation_and_stage_reviews_survive_a_forced_kill(controller):
    """AC-14 — 수준·조정 이력·설계·계획·검토 모드·검토 기록이 강제 종료 후 복원된다.

    P3-01이 여는 문은 "준비가 갖춰졌으면 기능 구현을 배정한다"이다. 재시작이 그
    판단의 근거를 잃으면 갖춰졌던 준비가 사라지거나(진행 불가) 갖춰지지 않은 준비가
    갖춰진 것처럼 보인다(우회). 둘 다 막혀야 한다.

    여기서는 제어부 API 만 쓴다. 준비 산출물은 Runner가 등록하는 경로를 그대로
    쓰되 실제 CLI는 부르지 않는다 — 이 시험이 보는 것은 **복원**이다.
    """
    base = controller.base_url
    _register_runner(base)

    project = httpx.post(
        f"{base}/api/projects",
        json={"name": "prep-restart", "repo_path": "C:/tmp/demo", "default_tool_id": "codex"},
        timeout=10.0,
    ).json()
    case = httpx.post(
        f"{base}/api/projects/{project['id']}/cases",
        json={"title": "준비 재시작 Case", "kind": "feature"},
        timeout=10.0,
    ).json()

    axes = [
        {
            "axis": axis,
            "weight": weight,
            "evidence": f"{axis} 근거",
            "judgement": f"{axis} 판단",
            "unconfirmed": "",
        }
        for axis, weight in (
            ("intent_clarity", "low"),
            ("change_scope", "low"),
            ("compatibility_and_data", "low"),
            ("permission_and_security", "high"),
            ("reversibility", "low"),
            ("uncertainty", "low"),
            ("verification_difficulty", "low"),
        )
    ]
    draft = httpx.post(
        f"{base}/api/cases/{case['id']}/intent-drafts",
        json={
            "summary": "의도 초안 v1",
            "target_runner_id": RUNNER_ID,
            "fields": {
                "goal": {
                    "text": "권한 조건을 한 줄 바꾼다",
                    "state": "proposed",
                    "origin": "user_requirement",
                }
            },
            "criteria": [
                {
                    "key": "C-01",
                    "relates_to": "expected_outcome",
                    "text": "허용·거부 조합이 기대대로 동작한다",
                    "method": "허용/거부/경계 세 조합을 확인한다",
                    "summary": "권한 조합이 기대대로",
                    "method_summary": "세 조합 확인",
                }
            ],
            # **낮은 축들의 평균으로 상쇄되지 않는지**를 재시작 뒤에도 확인한다.
            "sizing": {"recommended_level": "simple", "axes": axes},
        },
        timeout=10.0,
    ).json()

    intakes = httpx.get(f"{base}/api/runner/{RUNNER_ID}/intakes", timeout=10.0).json()
    pending = next(i for i in intakes if i["intake_id"] == draft["intake_id"])
    body = base64.b64decode(pending["content_b64"])
    httpx.post(
        f"{base}/api/runner/intakes/{draft['intake_id']}/stored",
        json={"runner_id": RUNNER_ID, "content_hash": draft["content_hash"]},
        timeout=10.0,
    ).raise_for_status()
    structure = intent_doc.structure(body, None)
    httpx.post(
        f"{base}/api/runner/intent-structure",
        json={
            "runner_id": RUNNER_ID,
            "intent_version_id": pending["intent"]["intent_version_id"],
            "fields": structure["fields"],
            "questions": structure["questions"],
            "criteria": structure["criteria"],
            "sizing": structure["sizing"],
        },
        timeout=10.0,
    ).raise_for_status()

    # 제안은 간소였지만 권한 축이 높아 심층이 적용된다.
    prep = httpx.get(f"{base}/api/cases/{case['id']}/preparation", timeout=10.0).json()
    assert prep["sizing"]["recommended_level"] == "simple"
    assert prep["sizing"]["level"] == "deep"

    # 사람이 표준으로 내린다. 이유와 남는 위험이 함께 남는다.
    adjusted = httpx.post(
        f"{base}/api/cases/{case['id']}/sizing-adjustment",
        json={
            "level": "standard",
            "reason": "권한 모델은 조사로 확인했다",
            "residual_risk": "기존 사용자 영향은 아직 미확인",
            "actor": "owner",
        },
        timeout=10.0,
    )
    assert adjusted.status_code == 201, adjusted.text

    # 계획 단계만 자동 진행으로 바꾼다. 두 단계가 독립임을 재시작 뒤에도 본다.
    httpx.put(
        f"{base}/api/cases/{case['id']}/stage-review-settings/plan",
        json={"mode": "auto_proceed", "reason": "계획이 짧다", "set_by": "owner"},
        timeout=10.0,
    ).raise_for_status()

    def register_prep(
        stage: str, sections: dict, artifact_id: str, tasks: list | None = None,
        questions: list | None = None,
    ) -> dict:
        kind = "design" if stage == "design" else "dev_plan"
        prep_body = prep_doc.compose(
            stage=PreparationStage(stage),
            level=WorkLevel.STANDARD,
            sections={k: {"text": v, "origin": "ai_proposal"} for k, v in sections.items()},
            questions=questions or [],
            tasks=tasks or [],
            case_id=case["id"],
            intent_version_id=pending["intent"]["intent_version_id"],
            authored_by="codex/exec",
        )
        httpx.post(
            f"{base}/api/runner/artifacts",
            json={
                "runner_id": RUNNER_ID,
                "case_id": case["id"],
                "kind": kind,
                "artifact_id": artifact_id,
                "revision": 1,
                "content_hash": content_hash(prep_body),
                "byte_size": len(prep_body),
                "summary": f"{stage} 원문",
            },
            timeout=10.0,
        ).raise_for_status()
        created = httpx.post(
            f"{base}/api/runner/preparation-artifacts",
            json={
                "runner_id": RUNNER_ID,
                "case_id": case["id"],
                "stage": stage,
                "artifact_id": artifact_id,
                "revision": 1,
                "level": "standard",
                "authoring_mode": "ai_drafted",
                "summary": f"{stage} v1",
            },
            timeout=10.0,
        )
        assert created.status_code == 201, created.text
        prep_row = created.json()["preparation_artifact"]
        reported = prep_doc.structure(prep_body)
        httpx.post(
            f"{base}/api/runner/preparation-structure",
            json={
                "runner_id": RUNNER_ID,
                "preparation_id": prep_row["id"],
                "sections": reported["sections"],
                "questions": reported["questions"],
                "tasks": reported["tasks"],
            },
            timeout=10.0,
        ).raise_for_status()
        return prep_row

    register_prep(
        "design",
        {
            "change_summary": "권한 조건 한 줄을 바꾼다",
            "requirement_mapping": "C-01 은 조건 분기로 대응한다",
            "interfaces_and_data": "공개 계약은 바뀌지 않는다",
            "failure_handling": "권한 없음은 거부로 응답한다",
            "verifiability": "허용/거부/경계 세 조합을 확인한다",
        },
        "art-design-1",
    )
    reviewed = httpx.post(
        f"{base}/api/cases/{case['id']}/stage-reviews/design",
        json={"reviewed": True, "note": "권한 경계를 확인했다", "actor": "owner"},
        timeout=10.0,
    )
    assert reviewed.status_code == 201, reviewed.text

    register_prep(
        "plan",
        {
            "tasks": "작업 목록은 tasks 에 있다",
            "verification": "허용/거부/경계 세 조합 시험",
            "dependencies": "T2 는 T1 을 기다린다",
            "integration_order": "T1 → T2 → 회귀 확인",
            "human_decision_points": "기존 사용자 영향 확인",
            "environment_prerequisites": "저장소 checkout",
        },
        "art-plan-1",
        tasks=[
            {
                "key": "T1",
                "kind": "implementation",
                "purpose": "권한 조건 한 줄을 바꾼다",
                "purpose_summary": "권한 조건 변경",
                "deliverable": "조건 분기",
                "deliverable_summary": "조건 분기",
                "completion": "세 조합 시험 통과",
                "completion_summary": "세 조합 시험 통과",
                "criteria": [{"key": "C-01", "relation": "implements"}],
            },
            {
                "key": "T2",
                "kind": "verification",
                "purpose": "허용·거부·경계 세 조합을 확인한다",
                "purpose_summary": "세 조합 확인",
                "deliverable": "시험 결과",
                "deliverable_summary": "시험 결과",
                "completion": "세 조합이 기대대로 동작한다",
                "completion_summary": "세 조합이 기대대로",
                "depends_on": ["T1"],
                "criteria": [{"key": "C-01", "relation": "verifies"}],
            },
        ],
        questions=[
            {
                "key": "p1",
                "text": "기존 사용자 영향 범위를 사람이 정해야 한다",
                "summary": "기존 사용자 영향",
                "decide_at": "plan",
                "blocks": ["T2"],
            }
        ],
    )
    auto = httpx.post(
        f"{base}/api/cases/{case['id']}/stage-auto-proceed/plan", json={}, timeout=10.0
    )
    assert auto.status_code == 201, auto.text

    # ---- 강제 종료 ----
    controller.kill_hard()
    controller.start()

    after = httpx.get(f"{base}/api/cases/{case['id']}/preparation", timeout=10.0).json()

    # 수준과 조정 이력이 그대로다. 도출값도 남아 있어 조정이 무엇을 낮췄는지 보인다.
    assert after["level"] == "standard"
    assert after["sizing"]["source"] == "human_adjustment"
    assert after["sizing"]["adjusted_from"] == "deep"
    assert after["sizing"]["derived_level"] == "deep"
    assert after["sizing"]["residual_risk_summary"] == "기존 사용자 영향은 아직 미확인"
    assert len(after["sizing"]["axes"]) == 7
    assert len(after["sizing_history"]) == 2

    # 검토 모드와 그 출처가 그대로다. 재시작이 기본값으로 되돌리지 않는다.
    assert after["design"]["mode"] == "human_review"
    assert after["design"]["mode_source"] == "project_default"
    assert after["plan"]["mode"] == "auto_proceed"
    assert after["plan"]["mode_source"] == "case_setting"

    # 검토 기록이 그대로이고 **사람 검토와 자동 조건 충족이 여전히 구별된다.**
    assert after["design"]["state"] == "human_reviewed"
    assert after["design"]["review"]["decision_id"] is not None
    assert after["plan"]["state"] == "auto_conditions_met"
    assert after["plan"]["review"]["decision_id"] is None
    assert after["plan"]["review"]["actor"] == "stage-auto-proceed-policy"

    # AC-15: **작업 그래프와 차단 이유가 그대로 복원된다.** 재시작이 그래프를
    # 잃으면 좁히기의 근거가 사라지고, 무엇이 왜 막혀 있는지 답할 수 없다.
    graph = httpx.get(f"{base}/api/cases/{case['id']}/work-graph", timeout=10.0).json()
    assert graph["present"] is True
    assert [t["task_key"] for t in graph["tasks"]] == ["T1", "T2"]
    assert graph["tasks"][1]["depends_on"] == ["T1"]
    question = graph["deferred_open_questions"][0]
    assert graph["question_blocks"][question["id"]] == ["T2"]
    # 연결이 살아 있으므로 T1 은 그 질문에 막히지 않는다(좁히기가 복원됐다).
    assert [b["reason"] for b in graph["readiness"]["T1"]["blocked_by"]] == []
    assert "deferred_questions_unresolved" in [
        b["reason"] for b in graph["readiness"]["T2"]["blocked_by"]
    ]
    coverage = {c["criterion_key"]: c for c in graph["criteria_coverage"]}
    assert coverage["C-01"]["verified_by"] == ["T2"]

    # 준비가 갖춰졌으므로 기능 구현이 열린다. 재시작이 그 판단을 잃지 않는다.
    instruction = httpx.post(
        f"{base}/api/cases/{case['id']}/artifacts",
        json={
            "kind": "instruction",
            "content": "계획대로 구현한다",
            "summary": "구현 지시",
            "target_runner_id": RUNNER_ID,
        },
        timeout=10.0,
    ).json()
    httpx.post(
        f"{base}/api/runner/intakes/{instruction['intake_id']}/stored",
        json={"runner_id": RUNNER_ID, "content_hash": instruction["content_hash"]},
        timeout=10.0,
    ).raise_for_status()
    # 의도 동의가 없으므로 그 사유로 막히고, 준비 관련 사유는 나오지 않는다.
    refused = httpx.post(
        f"{base}/api/cases/{case['id']}/runs",
        json={
            "run_id": "run-impl-restart",
            "instruction_artifact_id": instruction["artifact_id"],
            "purpose": "feature_implementation",
            "role": "author",
            "tool_id": "codex",
            "mode": "exec",
            "permission": "read_only",
            "task_id": "T1",
        },
        timeout=10.0,
    )
    assert refused.status_code == 409, refused.text
    refusals = refused.json()["detail"]["admission"]["refusals"]
    assert "intent_not_agreed" in refusals
    for code in (
        "sizing_not_decided",
        "design_missing",
        "design_review_missing",
        "plan_missing",
        "plan_review_missing",
        # 그래프도 복원됐으므로 "없다"로 되돌아가지 않는다.
        "work_graph_missing",
        "task_not_in_work_graph",
    ):
        assert code not in refusals, f"{code} 가 재시작 뒤에 다시 나타났다"


def test_workspace_and_execution_effects_survive_a_forced_kill(controller):
    """P3-03 AC-14 — 작업공간·기준 커밋·실행 효과·명령 기록이 강제 종료 후 복원된다.

    P3-03이 여는 문은 "준비된 작업공간이 있으면 코드를 바꾼다"이다. 재시작이 그
    근거를 잃으면 두 방향으로 틀어진다 — 준비된 작업공간이 사라져 진행이 막히거나,
    **무엇이 바뀌었는지의 기록을 잃어** 바뀌지 않은 실행을 완료로 읽게 된다.

    여기서는 제어부 API 만 쓴다. 실제 git·CLI는 부르지 않는다 — 이 시험이 보는
    것은 **복원**이고, git 동작은 tests/test_workspace.py 가 진짜 저장소로 본다.
    """
    base = controller.base_url
    _register_runner(base)

    project = httpx.post(
        f"{base}/api/projects",
        json={"name": "ws-restart", "repo_path": "C:/tmp/ws", "default_tool_id": "codex"},
        timeout=10.0,
    ).json()
    case = httpx.post(
        f"{base}/api/projects/{project['id']}/cases",
        json={"title": "작업공간 재시작 Case", "kind": "analysis"},
        timeout=10.0,
    ).json()

    requested = httpx.post(
        f"{base}/api/cases/{case['id']}/workspace", json={"base_ref": "HEAD"}, timeout=10.0
    ).json()
    assert requested["state"] == "requested"

    httpx.post(
        f"{base}/api/runner/workspaces/{case['id']}/ready",
        json={
            "runner_id": RUNNER_ID,
            "repo_path": "C:/tmp/ws",
            "worktree_path": "C:/tmp/worktrees/ws-restart",
            "branch": f"hads/{case['id']}",
            "base_commit": "0123456789abcdef0123456789abcdef01234567",
            "base_ref": "HEAD",
            "user_tree_dirty": True,
            "user_tree_entries": 3,
        },
        timeout=10.0,
    ).raise_for_status()

    accepted = httpx.post(
        f"{base}/api/cases/{case['id']}/artifacts",
        json={
            "kind": "instruction",
            "content": "작업공간 위에서 실행할 지시",
            "summary": "지시 원문",
            "target_runner_id": RUNNER_ID,
        },
        timeout=10.0,
    ).json()
    httpx.post(
        f"{base}/api/runner/intakes/{accepted['intake_id']}/stored",
        json={"runner_id": RUNNER_ID, "content_hash": accepted["content_hash"]},
        timeout=10.0,
    ).raise_for_status()
    httpx.post(
        f"{base}/api/cases/{case['id']}/runs",
        json={"run_id": "run-ws-1", "instruction_artifact_id": accepted["artifact_id"]},
        timeout=10.0,
    ).raise_for_status()
    httpx.post(f"{base}/api/runner/{RUNNER_ID}/assignments", timeout=10.0).raise_for_status()

    httpx.post(
        f"{base}/api/runner/runs/run-ws-1/commands",
        json={
            "runner_id": RUNNER_ID,
            "generation": 1,
            "commands": [
                {"seq": 1, "command_summary": "전체 시험", "exit_code": 1, "duration_ms": 1200}
            ],
        },
        timeout=10.0,
    ).raise_for_status()
    httpx.post(
        f"{base}/api/runner/runs/run-ws-1/result",
        json={
            "runner_id": RUNNER_ID,
            "generation": 1,
            "outcome": "completed",
            "exit_code": 0,
            "workspace_effect": {
                "base_commit": "0123456789abcdef0123456789abcdef01234567",
                "head_before": "0123456789abcdef0123456789abcdef01234567",
                "head_after": "0123456789abcdef0123456789abcdef01234567",
                "entries_before": 0,
                "entries_after": 2,
                "changed": True,
                "files_changed": 2,
                "insertions": 7,
                "deletions": 1,
                "isolation": "worktree_file_layout_only",
                "outside_workspace_observed": True,
                "outside_workspace_changed": False,
            },
        },
        timeout=10.0,
    ).raise_for_status()

    # ---- 강제 종료 ----
    controller.kill_hard()
    controller.start()

    workspace = httpx.get(f"{base}/api/cases/{case['id']}/workspace", timeout=10.0).json()
    assert workspace["state"] == "ready"
    assert workspace["base_commit"] == "0123456789abcdef0123456789abcdef01234567"
    assert workspace["branch"] == f"hads/{case['id']}"
    # 사용자의 원래 트리를 정리하지 않았다는 관측도 남아 있다.
    assert workspace["user_tree_dirty"] is True
    assert workspace["user_tree_entries"] == 3
    # 격리 한계 문구는 **값으로** 복원된다. 화면이 지어내지 않는다(D-44).
    assert workspace["isolation"] == "worktree_file_layout_only"

    restored = httpx.get(f"{base}/api/runs/run-ws-1", timeout=10.0).json()
    assert restored["workspace_effect"]["files_changed"] == 2
    assert restored["workspace_effect"]["changed"] is True
    # **종료 코드 1 이 그대로다.** 실패한 시험을 복원 과정에서 성공으로 바꾸지 않는다.
    assert [c["exit_code"] for c in restored["commands"]] == [1]
