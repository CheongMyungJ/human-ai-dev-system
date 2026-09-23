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
    # **P3-R1: 필수 항목은 Case 의 Profile 이 정한다.** 재시작 후에도 그 목록이
    # 그대로 복원되는지를 본다 — 개수를 고정하지 않는다(D-62).
    required = set(
        httpx.get(f"{base}/api/cases/{case['id']}/policy", timeout=10.0).json()["profile"][
            "required_fields"
        ]
    )
    assert {f.value for f in IntentField} <= required
    assert {f["field"] for f in latest["fields"]} == required
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

    # P4-03. 이 Case 는 `analysis` → root-cause-analysis 이고 C-01 은 연결 항목에서
    # `cause` 의무로 도출된다. 원인 기준의 `met` 은 **조사로 답했고 확정했다**를 함께
    # 적는다.
    assert (
        record(
            criteria[0]["id"], "met", satisfaction="investigated", conclusion="determined"
        ).status_code
        == 200
    )
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
    #
    # **P3-R4: 설계 쪽은 이제 도출 기본값(자동 진행)이다.** 확인하는 성질은 같다 —
    # 재시작 뒤에도 같은 출처에서 같은 값이 나온다. 아래 `plan` 의 명시 설정이
    # 도출값에 덮이지 않는 것도 함께 본다.
    assert after["design"]["mode"] == "auto_proceed"
    assert after["design"]["mode_source"] == "autonomy_derived"
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

    view = httpx.get(f"{base}/api/cases/{case['id']}/workspace", timeout=10.0).json()
    # **P3-R2: 조회가 저장소별 목록이다.** 이 Case 는 저장소 하나를 쓰므로 하나다.
    assert view["repository_count"] == 1
    assert view["all_ready"] is True
    workspace = view["workspaces"][0]
    assert workspace["state"] == "ready"
    assert workspace["base_commit"] == "0123456789abcdef0123456789abcdef01234567"
    assert workspace["branch"] == f"hads/{case['id']}"
    # 어느 저장소의 작업공간인지도 남는다. 재시작이 그 연결을 잃으면 다음 실행이
    # 어느 저장소에서 도는지 말할 수 없다(P3-R2).
    assert workspace["repository_id"]
    # 사용자의 원래 트리를 정리하지 않았다는 관측도 남아 있다.
    assert workspace["user_tree_dirty"] is True
    assert workspace["user_tree_entries"] == 3
    # 격리 한계 문구는 **값으로** 복원된다. 화면이 지어내지 않는다(D-44).
    assert view["isolation"] == "worktree_file_layout_only"

    restored = httpx.get(f"{base}/api/runs/run-ws-1", timeout=10.0).json()
    assert restored["workspace_effect"]["files_changed"] == 2
    assert restored["workspace_effect"]["changed"] is True
    # **종료 코드 1 이 그대로다.** 실패한 시험을 복원 과정에서 성공으로 바꾸지 않는다.
    assert [c["exit_code"] for c in restored["commands"]] == [1]


def test_policy_profile_budget_and_repositories_survive_a_forced_kill(controller, tmp_path):
    """P3-R1 AC-13 — 정책·Profile·확인 지점·예산·저장소가 강제 종료 후에도 남는다.

    **판정을 메모리에 두지 않는다**는 P2-03의 규칙이 정책에도 적용된다. 재시작한
    프로세스가 Autonomy 를 기본값으로 되돌리면, 사람이 controlled 로 바꾼 사실이
    조용히 사라진다.
    """
    base = controller.base_url
    _register_runner(base)

    project = httpx.post(
        f"{base}/api/projects",
        json={"name": "policy-restart", "repo_path": "C:/tmp/policy", "default_tool_id": "codex"},
        timeout=10.0,
    ).json()
    case = httpx.post(
        f"{base}/api/projects/{project['id']}/cases",
        json={"title": "정책 복원 Case", "profile": "refactoring"},
        timeout=10.0,
    ).json()

    httpx.put(
        f"{base}/api/cases/{case['id']}/autonomy",
        json={
            "autonomy": "controlled",
            "set_by": "owner",
            "reason_summary": "외부 반영이 있는 업무다",
        },
        timeout=10.0,
    ).raise_for_status()
    httpx.post(
        f"{base}/api/cases/{case['id']}/controlled-checkpoints/start_scope/confirmation",
        json={
            "confirmed_by": "owner",
            "explicit": True,
            "subject_type": "case",
            "subject_id": case["id"],
            "subject_hash": "d" * 64,
        },
        timeout=10.0,
    ).raise_for_status()
    httpx.put(
        f"{base}/api/cases/{case['id']}/budget",
        json={
            "metric": "run_count",
            "threshold_kind": "hard",
            "limit_value": 4,
            "set_by": "owner",
        },
        timeout=10.0,
    ).raise_for_status()
    extra = httpx.post(
        f"{base}/api/projects/{project['id']}/repositories",
        json={"name": "docs", "repo_path": "C:/tmp/policy-docs"},
        timeout=10.0,
    ).json()
    httpx.put(
        f"{base}/api/cases/{case['id']}/repositories",
        json={
            "repository_id": extra["id"],
            "code_write_allowed": True,
            "publish_allowed": False,
            "selected_by": "owner",
        },
        timeout=10.0,
    ).raise_for_status()
    httpx.post(
        f"{base}/api/cases/{case['id']}/delegation-basis",
        json={"basis_kind": "original_request", "summary": "최초 요청"},
        timeout=10.0,
    ).raise_for_status()

    # **소비를 남긴다**(P3-R3). 한도만 복원되고 사용량이 0 으로 돌아오면 제어부를
    # 다시 띄우는 것만으로 hard 한도를 우회할 수 있다.
    instruction = httpx.post(
        f"{base}/api/cases/{case['id']}/artifacts",
        json={
            "kind": "instruction",
            "content": "예산 복원 확인용 지시",
            "summary": "예산 복원",
            "target_runner_id": RUNNER_ID,
        },
        timeout=10.0,
    ).json()
    # Runner 프로세스가 없으므로 Runner 역할로 저장 완료를 보고한다(위 시험과 같다).
    httpx.post(
        f"{base}/api/runner/intakes/{instruction['intake_id']}/stored",
        json={"runner_id": RUNNER_ID, "content_hash": instruction["content_hash"]},
        timeout=10.0,
    ).raise_for_status()
    httpx.post(
        f"{base}/api/cases/{case['id']}/runs",
        json={
            "run_id": "run-policy-budget-1",
            "instruction_artifact_id": instruction["artifact_id"],
            "purpose": "limited_analysis",
            "role": "author",
            "tool_id": "local-echo",
            "mode": "p2-01-local",
            "permission": "read_only",
            "task_id": "task-1",
        },
        timeout=10.0,
    ).raise_for_status()
    before = httpx.get(f"{base}/api/cases/{case['id']}/budget", timeout=10.0).json()
    assert before["usage"]["run_count"]["exposure"] == 1.0

    # ---- 강제 종료 ----
    controller.kill_hard()
    controller.start()

    policy = httpx.get(f"{base}/api/cases/{case['id']}/policy", timeout=10.0).json()
    assert policy["autonomy"] == "controlled"
    assert policy["autonomy_source"] == "case_explicit"
    assert policy["profile"]["profile"] == "refactoring"
    # P4-03 부터 새 Case 는 정의판 "2"(완료 계약 포함)를 받는다. 복원되는 것은 **그
    # Case 에 기록된 값**이며 재시작이 현재 정의판으로 바꿔 적지 않는다.
    assert policy["profile"]["version"] == "2"

    points = {p["checkpoint"]: p for p in policy["checkpoints"]}
    assert points["start_scope"]["state"] == "confirmed"
    assert points["start_scope"]["subject_hash"] == "d" * 64
    assert points["result_candidate"]["state"] == "required"

    assert policy["budget"]["unlimited"] is False
    limit = policy["budget"]["limits"][0]
    assert (limit["metric"], limit["limit_value"]) == ("run_count", 4.0)
    # **강제 상태도 그대로 복원된다.** 재시작이 보장 범위를 바꾸지 않는다.
    # P3-R3에서 `recorded_not_enforced` → `enforced_absolute` 로 바뀌었다.
    assert limit["enforcement"] == "enforced_absolute"

    # **소비도 복원된다**(P3-R3 AC-9). 재시작으로 한도가 다시 가득 차지 않는다.
    usage = policy["budget"]["usage"]["run_count"]
    assert usage["exposure"] == 1.0, "재시작이 소비를 초기화했다"
    reservations = [
        r for r in policy["budget"]["reservations"] if r["metric"] == "run_count"
    ]
    assert len(reservations) == 1, "이행이 같은 실행에 예약을 다시 만들었다"

    selected = policy["repositories"]["selected"]
    assert [s["repository_id"] for s in selected] == [extra["id"]]
    assert selected[0]["code_write_allowed"] == 1
    assert selected[0]["publish_allowed"] == 0

    assert policy["delegation_basis"]["current"]["basis_kind"] == "original_request"


def test_per_repository_workspaces_and_the_composition_survive_a_forced_kill(
    controller, tmp_path
):
    """P3-R2 AC-16 — 저장소별 작업공간과 코드 조합이 강제 종료 후에도 남는다.

    **무엇이 복원돼야 하는가.** 저장소가 여럿이면 "어떤 코드 위에서 시작했는가"가
    저장소마다 따로 있고, 그 연결을 잃으면 다음 실행이 어느 저장소에서 도는지 말할
    수 없다. 조합도 마찬가지다 — 근거가 가리키는 대상이 재시작으로 사라지면 그
    근거가 아직 유효한지 답할 수 없다(execution-workspace-review 2.1절).

    여기서는 제어부 API 만 쓴다. git 동작은 `tests/test_repositories.py` 가 진짜
    저장소로 본다.
    """
    base = controller.base_url
    _register_runner(base)

    project = httpx.post(
        f"{base}/api/projects",
        json={"name": "multi-restart", "repo_path": "C:/tmp/api", "default_tool_id": "codex"},
        timeout=10.0,
    ).json()
    registry = httpx.get(f"{base}/api/projects/{project['id']}/repositories", timeout=10.0).json()
    primary = registry["repositories"][0]["id"]
    ui = httpx.post(
        f"{base}/api/projects/{project['id']}/repositories",
        json={"name": "ui", "repo_path": "C:/tmp/ui"},
        timeout=10.0,
    ).json()["id"]

    case = httpx.post(
        f"{base}/api/projects/{project['id']}/cases",
        json={"title": "두 저장소 Case", "kind": "analysis"},
        timeout=10.0,
    ).json()

    for repository_id in (primary, ui):
        httpx.put(
            f"{base}/api/cases/{case['id']}/repositories",
            json={
                "repository_id": repository_id,
                "code_write_allowed": True,
                "publish_allowed": False,
                "selected_by": "owner",
            },
            timeout=10.0,
        ).raise_for_status()

    for repository_id, path, sha in (
        (primary, "C:/tmp/api", "1111111111111111111111111111111111111111"),
        (ui, "C:/tmp/ui", "2222222222222222222222222222222222222222"),
    ):
        httpx.post(
            f"{base}/api/cases/{case['id']}/workspace",
            json={"repository_id": repository_id, "base_ref": "HEAD"},
            timeout=10.0,
        ).raise_for_status()
        httpx.post(
            f"{base}/api/runner/workspaces/{case['id']}/ready",
            json={
                "runner_id": RUNNER_ID,
                "repository_id": repository_id,
                "repo_path": path,
                "worktree_path": f"{path}-worktree",
                "branch": f"hads/{case['id']}",
                "base_commit": sha,
                "base_ref": "HEAD",
                "user_tree_dirty": repository_id == ui,
                "user_tree_entries": 2 if repository_id == ui else 0,
            },
            timeout=10.0,
        ).raise_for_status()

    composition = httpx.post(
        f"{base}/api/cases/{case['id']}/composition", timeout=10.0
    ).json()
    assert len(composition["entries"]) == 2

    # ---- 강제 종료 ----
    controller.kill_hard()
    controller.start()

    view = httpx.get(f"{base}/api/cases/{case['id']}/workspace", timeout=10.0).json()
    assert view["repository_count"] == 2
    assert view["all_ready"] is True
    spaces = {w["repository_id"]: w for w in view["workspaces"]}
    # **저장소마다 자기 기준 커밋과 자기 사용자 트리 관측이 그대로다.**
    assert spaces[primary]["base_commit"] == "1111111111111111111111111111111111111111"
    assert spaces[ui]["base_commit"] == "2222222222222222222222222222222222222222"
    assert spaces[primary]["user_tree_dirty"] is False
    assert spaces[ui]["user_tree_dirty"] is True
    assert spaces[ui]["user_tree_entries"] == 2
    assert spaces[primary]["allowance_source"] == "case_repository"

    restored = httpx.get(f"{base}/api/cases/{case['id']}/composition", timeout=10.0).json()
    assert restored["id"] == composition["id"]
    assert restored["composition_hash"] == composition["composition_hash"]
    assert {e["repository_id"] for e in restored["entries"]} == {primary, ui}
    # 조합이 무엇을 관측하지 못했는지도 남는다. 복원이 빈칸을 채우지 않는다.
    assert restored["snapshot_complete"] is False
    assert restored["matches_current_state"] is True


def test_progression_records_survive_a_forced_kill(controller):
    """P3-R4 AC-28 — 확인 지점·정합성 방식·누적 변경이 강제 종료 후 복원된다.

    R4 가 여는 문은 "조건이 갖춰졌으면 사람 없이 진행·완료한다"이다. 재시작이 그
    판단의 근거를 잃으면 둘 중 하나가 된다.

        근거가 사라진다   확인했던 시작 확인이 없어져 진행이 막힌다
        근거가 생긴다     확인하지 않은 것이 확인된 것처럼 보인다

    **둘째가 더 위험하다.** 그래서 이 시험은 "복원됐다"뿐 아니라 **확인하지 않은
    것이 확인되지 않은 채로 남았는지**도 본다.
    """
    base = controller.base_url
    _register_runner(base)

    project = httpx.post(
        f"{base}/api/projects",
        json={"name": "r4-restart", "repo_path": "C:/tmp/demo", "default_tool_id": "codex"},
        timeout=10.0,
    ).json()
    case = httpx.post(
        f"{base}/api/projects/{project['id']}/cases",
        json={"title": "R4 재시작 Case", "kind": "feature"},
        timeout=10.0,
    ).json()

    # controlled 로 설정한다. 확인 지점 둘이 `required` 로 생긴다.
    httpx.put(
        f"{base}/api/cases/{case['id']}/autonomy",
        json={"autonomy": "controlled", "set_by": "owner"},
        timeout=10.0,
    ).raise_for_status()

    axes = [
        {
            "axis": axis,
            "weight": "low",
            "evidence": f"{axis} 근거",
            "judgement": f"{axis} 판단",
            "unconfirmed": "",
        }
        for axis in (
            "intent_clarity",
            "change_scope",
            "compatibility_and_data",
            "permission_and_security",
            "reversibility",
            "uncertainty",
            "verification_difficulty",
        )
    ]
    draft = httpx.post(
        f"{base}/api/cases/{case['id']}/intent-drafts",
        json={
            "summary": "의도 초안 v1",
            "target_runner_id": RUNNER_ID,
            "fields": {
                "goal": {
                    "text": "로그에서 오류 줄만 뽑는다",
                    "state": "proposed",
                    "origin": "user_requirement",
                }
            },
            "criteria": [
                {
                    "key": "C-01",
                    "relates_to": "expected_outcome",
                    "text": "오류 줄만 출력된다",
                    "method": "표본 파일로 확인한다",
                    "summary": "오류 줄만 출력",
                    "method_summary": "표본 파일 확인",
                }
            ],
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
    intent_version_id = pending["intent"]["intent_version_id"]
    httpx.post(
        f"{base}/api/runner/intent-structure",
        json={
            "runner_id": RUNNER_ID,
            "intent_version_id": intent_version_id,
            "fields": structure["fields"],
            "questions": structure["questions"],
            "criteria": structure["criteria"],
            "sizing": structure["sizing"],
        },
        timeout=10.0,
    ).raise_for_status()

    # 가벼운 요청 정합성 확인을 기록한다. **독립 검토는 하지 않았다.**
    conformance = httpx.post(
        f"{base}/api/cases/{case['id']}/conformance-checks/light",
        json={"intent_version_id": intent_version_id},
        timeout=10.0,
    )
    assert conformance.status_code == 201, conformance.text

    # 시작 확인만 한다. **결과 후보 확인은 하지 않는다.**
    confirmed = httpx.post(
        f"{base}/api/cases/{case['id']}/controlled-checkpoints/start_scope/confirmation",
        json={
            "confirmed_by": "owner",
            "explicit": True,
            "subject_type": "case",
            "subject_id": case["id"],
            "note_summary": "목표·범위·허용 행동을 확인했다",
        },
        timeout=10.0,
    )
    assert confirmed.status_code == 201, confirmed.text

    controller.kill_hard()
    controller.start()

    policy = httpx.get(f"{base}/api/cases/{case['id']}/policy", timeout=10.0).json()

    # --- 확인한 것은 확인된 채로 남는다 ---------------------------------
    points = {p["checkpoint"]: p for p in policy["checkpoints"]}
    assert points["start_scope"]["state"] == "confirmed"
    assert points["start_scope"]["confirmed_by"] == "owner"
    # --- **확인하지 않은 것은 확인되지 않은 채로 남는다** ----------------
    assert points["result_candidate"]["state"] == "required"

    # --- 정합성은 **방식과 보지 않은 범위**까지 복원된다 -----------------
    assert policy["conformance"]["method"] == "light"
    assert policy["conformance"]["verdict"] == "pass"
    assert "AI 가 검토하지 않았다" in policy["conformance"]["unverified_scope"]
    # 독립 검토를 한 것으로 바뀌지 않았다.
    assert policy["conformance"]["required_method"] == "light"
    assert [c["method"] for c in policy["conformance"]["checks"]] == ["light"]

    # --- 완료 모드의 도출과 그 출처도 그대로다 ---------------------------
    assert policy["completion_mode"] == "human_acceptance"
    assert policy["completion_mode_source"] == "autonomy_derived"
    assert policy["effective_autonomy"] == "controlled"
    assert policy["is_treatment"] is False

    # --- 강제 표시가 되돌아가지 않았다 -----------------------------------
    assert policy["enforcement"]["autonomy"]["state"] == "enforced"
    assert policy["enforcement"]["controlled_checkpoint"]["state"] == "enforced"
    assert policy["enforcement"]["publish"]["state"] == "not_implemented"


def test_conversation_requests_and_lock_survive_a_forced_kill(controller):
    """UI-01 AC-17 — 준비 Case·메시지·요청·잠금·업무화·보관이 강제 종료 뒤 복원되고,
    중계 중이던 메시지는 유실로 드러나 그 요청이 거짓 완료되지 않는다."""
    base = controller.base_url
    _register_runner(base)
    project = httpx.post(
        f"{base}/api/projects",
        json={"name": "ui01-restart", "repo_path": "C:/tmp/demo", "default_tool_id": "codex"},
        timeout=10.0,
    ).json()

    def conversation(title: str) -> str:
        view = httpx.post(
            f"{base}/api/projects/{project['id']}/conversations",
            json={"title": title},
            timeout=10.0,
        ).json()
        return view["case_id"]

    def send(case_id: str, text: str, cid: str) -> httpx.Response:
        return httpx.post(
            f"{base}/api/cases/{case_id}/messages",
            json={
                "client_message_id": cid,
                "content": text,
                "summary": text[:20],
                "target_runner_id": RUNNER_ID,
            },
            timeout=10.0,
        )

    kept = conversation("저장된 대화")
    sent = send(kept, "이 범위로 구현해 주세요.", "c-restart-1").json()
    # Runner 역할로 영속 저장을 보고한다 → 접수 완료.
    intakes = httpx.get(f"{base}/api/runner/{RUNNER_ID}/intakes", timeout=10.0).json()
    assert [i["intake_id"] for i in intakes] == [sent["message"]["intake_id"]]
    httpx.post(
        f"{base}/api/runner/intakes/{sent['message']['intake_id']}/stored",
        json={"runner_id": RUNNER_ID, "content_hash": sent["message"]["content_hash"]},
        timeout=10.0,
    ).raise_for_status()
    started = httpx.post(
        f"{base}/api/cases/{kept}/work-start",
        json={
            "profile": "feature",
            "request_message_id": sent["message"]["id"],
            "decided_by": "person",
            "summary": "구현 요청",
        },
        timeout=10.0,
    )
    assert started.status_code == 201, started.text
    httpx.post(f"{base}/api/cases/{kept}/archive", json={"actor": "owner"}, timeout=10.0)

    lost = conversation("중계 중인 대화")
    pending = send(lost, "PC 가 아직 저장하지 않은 말", "c-restart-2").json()
    assert pending["receipt"] == "pending"

    # ---- 강제 종료 ----
    controller.kill_hard()
    controller.start()

    view = httpx.get(f"{base}/api/cases/{kept}/conversation", timeout=10.0).json()
    assert view["stage"] == "work" and view["stage_source"] == "work_started"
    assert view["profile_version"] == "2"
    assert view["work_start"]["request_message_id"] == sent["message"]["id"]
    assert view["messages"][0]["receipt"] == "stored"
    assert view["current_request"]["id"] == sent["request"]["id"]
    assert view["current_request"]["state"] == "processing"
    assert view["visibility"]["archived"] is True
    # **잠금도 복원된다.** 메모리에 "처리 중"을 두지 않았기 때문이다.
    again = send(kept, "재시작 뒤 새 요청", "c-restart-3")
    assert again.status_code == 409
    assert again.json()["detail"]["refusals"] == ["request_in_progress"]
    # 같은 식별자의 재전송은 재시작 뒤에도 새 메시지를 만들지 않는다.
    replay = send(kept, "이 범위로 구현해 주세요.", "c-restart-1")
    assert replay.status_code == 200 and replay.json()["created"] is False

    gone = httpx.get(f"{base}/api/cases/{lost}/conversation", timeout=10.0).json()
    assert gone["messages"][0]["receipt"] == "lost_before_persist"
    assert gone["requests"][0]["state"] == "failed"
    assert gone["requests"][0]["outcome_reason"] == "original_lost_before_persist"
    # 잠금이 풀려 새 식별자로 다시 보낼 수 있다. 자동으로 다시 보내지 않았다.
    assert len(gone["messages"]) == 1
    assert send(lost, "다시 보냅니다", "c-restart-4").status_code == 202


def test_context_plans_receipts_and_recovered_usage_survive_a_forced_kill(tmp_path, monkeypatch):
    """P4-04 AC-18 — 등급·인라인·한도·영수증·시작하지 않은 실행·최신성·되찾은 사용량이
    강제 종료 뒤 그대로다. 메모리에 둔 것이 없다는 것을 실제 프로세스로 확인한다."""
    from tests.conftest import fake_capabilities

    # **작은 한도로 띄운다** — 제어부 설정 경로 그대로다. AI 메시지 하나가 생략된다.
    monkeypatch.setenv("HADS_CONTEXT_INLINE_LIMIT_BYTES", "1000")
    controller = ControllerProcess(tmp_path / "controller", _free_port())
    controller.start()
    try:
        base = controller.base_url
        httpx.post(
            f"{base}/api/runner/register",
            json={"runner_id": RUNNER_ID, "name": RUNNER_ID, "host": "test-host",
                  "capabilities": fake_capabilities()},
            timeout=10.0,
        ).raise_for_status()
        project = httpx.post(
            f"{base}/api/projects",
            json={"name": "p404-restart", "repo_path": "C:/tmp/demo", "default_tool_id": "codex"},
            timeout=10.0,
        ).json()
        case_id = httpx.post(
            f"{base}/api/projects/{project['id']}/conversations",
            json={"title": "문맥"},
            timeout=10.0,
        ).json()["case_id"]

        def send(text: str, cid: str) -> dict:
            sent = httpx.post(
                f"{base}/api/cases/{case_id}/messages",
                json={"client_message_id": cid, "content": text, "summary": f"메시지 {cid}",
                      "target_runner_id": RUNNER_ID},
                timeout=10.0,
            ).json()
            httpx.post(
                f"{base}/api/runner/intakes/{sent['message']['intake_id']}/stored",
                json={"runner_id": RUNNER_ID, "content_hash": sent["message"]["content_hash"]},
                timeout=10.0,
            ).raise_for_status()
            return sent

        def reply(sent: dict, run_id: str) -> None:
            created = httpx.post(
                f"{base}/api/cases/{case_id}/runs",
                json={"run_id": run_id,
                      "instruction_artifact_id": sent["message"]["artifact_id"],
                      "purpose": "discussion_reply", "tool_id": "codex", "mode": "exec",
                      "request_id": sent["request"]["id"]},
                timeout=10.0,
            )
            assert created.status_code == 201, created.text

        def claim() -> dict:
            claimed = httpx.post(f"{base}/api/runner/{RUNNER_ID}/assignments", timeout=10.0)
            return {a["run_id"]: a for a in claimed.json()}

        def receipt(assignment: dict, statuses: dict[int, str]) -> None:
            items = [{"seq": 0, "role": "instruction", "status": "read"}] + [
                {
                    "seq": r["seq"],
                    "role": r["role"],
                    "status": statuses.get(r["seq"])
                    or ("omitted" if r["inclusion"] == "omitted_size_limit" else "read"),
                }
                for r in assignment["context_refs"]
            ]
            httpx.post(
                f"{base}/api/runner/runs/{assignment['run_id']}/context-receipt",
                json={"runner_id": RUNNER_ID, "generation": 1, "items": items},
                timeout=10.0,
            ).raise_for_status()

        def result(run_id: str, **payload) -> None:
            httpx.post(
                f"{base}/api/runner/runs/{run_id}/result",
                json={"runner_id": RUNNER_ID, "generation": 1, **payload},
                timeout=10.0,
            ).raise_for_status()

        # 1) 첫 논의 응답: 큰 AI 응답을 남긴다(크기는 Runner 가 보고한다).
        first = send("아직 문서는 쓰지 마세요.", "c-k-1")
        reply(first, "run-k-1")
        receipt(claim()["run-k-1"], {})
        httpx.post(
            f"{base}/api/runner/artifacts",
            json={"runner_id": RUNNER_ID, "case_id": case_id, "kind": "run_output",
                  "artifact_id": "art-k-out-1", "revision": 1, "content_hash": "sha256:x",
                  "byte_size": 5000, "summary": "run output for run-k-1"},
            timeout=10.0,
        ).raise_for_status()
        result("run-k-1", outcome="completed", output_artifact_id="art-k-out-1",
               output_artifact_rev=1, residual_activity="none")
        httpx.post(f"{base}/api/cases/{case_id}/requests/{first['request']['id']}/settle",
                   json={"outcome": "completed", "actor": "system"},
                   timeout=10.0).raise_for_status()

        # 2) 두 번째: 핵심을 못 읽어 **시작하지 않은** 실행. 결과가 확정이므로 요청을 닫는다.
        second = send("계속해요.", "c-k-2")
        reply(second, "run-k-3")
        receipt(claim()["run-k-3"], {1: "missing"})
        result("run-k-3", outcome="failed", residual_activity="none",
               not_started_reason="required_context_unavailable")
        httpx.post(f"{base}/api/cases/{case_id}/requests/{second['request']['id']}/settle",
                   json={"outcome": "failed", "actor": "system"},
                   timeout=10.0).raise_for_status()

        # 3) 세 번째: 앞의 큰 AI 응답이 한도로 생략된다. 결과는 되찾은 사용량과 함께 불명.
        third = send("구조를 설명해 주세요.", "c-k-3")
        reply(third, "run-k-2")
        assignment = claim()["run-k-2"]
        assert [(r["role"], r["inclusion"]) for r in assignment["context_refs"]] == [
            ("conversation_user_message", "inline"),
            ("conversation_assistant_message", "omitted_size_limit"),
            ("conversation_user_message", "inline"),
        ]
        receipt(assignment, {})
        result("run-k-2", outcome="unknown",
               usage={"tokens": {"input_tokens": 100, "output_tokens": 7},
                      "cost_usd": "not_reported", "recovered_from": "runner_raw_log"})

        def snapshot() -> dict:
            runs = {r["run_id"]: r for r in httpx.get(
                f"{base}/api/cases/{case_id}", timeout=10.0).json()["runs"]}
            refs = httpx.get(f"{base}/api/runs/run-k-2/context-refs", timeout=10.0).json()
            budget = httpx.get(f"{base}/api/cases/{case_id}/budget", timeout=10.0).json()
            rows = {(r["run_id"], r["metric"]): (r["actual_value"], r["settle_source"])
                    for r in budget["reservations"]}
            return {
                "limit": runs["run-k-2"]["context_inline_limit"],
                "refs": [(r["tier"], r["inclusion"], r["byte_size"], r["receipt_status"])
                         for r in refs],
                "states": {k: v["context"]["state"] for k, v in runs.items()},
                "not_started": runs["run-k-3"]["not_started_reason"],
                "freshness": runs["run-k-1"]["context"]["freshness"],
                "tokens": rows[("run-k-2", "input_tokens")],
                "not_started_rows": rows[("run-k-3", "run_count")],
            }

        before = snapshot()
        assert before["limit"] == 1000
        assert [r[:2] + r[3:] for r in before["refs"]] == [
            ("core", "inline", "read"),
            ("supporting", "omitted_size_limit", "omitted"),
            ("core", "inline", "read"),
        ]
        assert before["refs"][1][2] == 5000
        assert before["states"] == {"run-k-1": "complete", "run-k-2": "partial",
                                    "run-k-3": "blocked"}
        assert before["not_started"] == "required_context_unavailable"
        assert before["freshness"]["basis"] == "at_result"
        assert before["tokens"] == (100.0, "recovered_from_runner_log")
        assert before["not_started_rows"] == (0.0, "not_started")

        # ---- 강제 종료 ----
        controller.kill_hard()
        controller.start()

        assert snapshot() == before
    finally:
        if controller.proc is not None:
            controller.kill_hard()
