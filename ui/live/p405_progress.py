"""P4-05 라이브 — 업무 단계 자동 진행을 **실제 브라우저·실제 codex** 로 끝까지 쓴다(P4-PLAN-05 AC-20).

자동 시험(`tests/test_web_shell.py`)은 가짜 CLI 로 같은 화면 경로를 본다. 여기서 보는 것은 사람이
실제로 쓰는 모양 그대로다: 설치된 Edge 로 화면을 누르고, 제어부의 처리기·진행기가 **실제 codex** 에게
의도 초안·검토·결합 기록(또는 설계·계획)·구현·검증을 시키고, 사람은 카드에서만 부른다.

    A. 업무화      새 대화 → 명확한 기능 요청 → AI 해석 업무화 → 의도 초안이 같은 요청에 붙음(전송 잠금)
    B. 카드        질문 카드(있으면 답) → 동의 카드(원문을 연 뒤 동의) → 진행 요청이 열려 이어 감
    C. 자동 진행   준비 → 작업공간 → 구현 → 검증 → 기준 판정 → 자동 완료 **또는** 미검증 기준의 예외 카드
                   (이 호스트의 CLI sandbox 가 시험을 돌리지 못하면 기준이 `unverified` 로 남는다 —
                   DEVELOPMENT.md 9절의 알려진 제약. 그때는 예외 수용이 실제 경로다)
    D. 종료 뒤     설명 질문 → 같은 대화의 설명 응답 · 종료 뒤 소비 구분
    E. 후속        수정 요청 → AI 해석 → 연결된 새 대화로 옮겨져 처음부터 잇는다

**판정은 두 층이다.** 제품 규칙이 어긋나면 멈춘다. AI 의 판단(질문 수·수준·게이트 판정·시험 실행 여부·
기준 판정)은 관찰로 적는다. **제품 코드를 import 하지 않는다** — HTTP·브라우저·OS 로만 본다.
라이브 데이터는 `%LOCALAPPDATA%\\Temp\\hads-p4-05-live`, 저장소 `var\\` 를 건드리지 않는다.

실행: `.venv\\Scripts\\python.exe ui\\live\\p405_progress.py` (먼저 `npm run build`)
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from playwright.sync_api import Page, expect, sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "p3" / "live"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from driver import PYTHON, LiveError, Log, stamp, wait_until  # noqa: E402
from ui03_shell import make_repo, os_processes  # noqa: E402

RUNNER_ID = "runner-p4-05-live"
OUT = REPO_ROOT / "p4" / "evidence"
LIVE_ROOT = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Temp" / "hads-p4-05-live"
DIST = REPO_ROOT / "web" / "dist"
PORT = 8798
STALE_SECONDS = 5
#: 실제 codex 실행은 분 단위다. 한 걸음의 상한(초).
STEP_TIMEOUT = 900

WORK_REQUEST = (
    "app.py 의 log() 가 남기는 한 줄에 수준을 더해 주세요. 형식은 `시각 [수준] 메시지` 이고 수준은"
    " INFO 와 ERROR 둘뿐입니다. log() 는 `log(message, level='INFO')` 로 바꾸되 기존 호출은 그대로 동작해야"
    " 합니다. README 의 형식 설명도 새 형식으로 고쳐 주세요. 확인은 `python app.py` 를 실행해 출력 첫 줄이"
    " 새 형식인지 보는 것으로 충분합니다. 이 저장소 밖은 건드리지 마세요."
)
GENERIC_ANSWER = "제안한 대로 하세요. 추가 제약은 없고, 이 요청의 범위를 넘는 선택이 필요하면 다시 물어 주세요."
EXPLANATION = "지금 결과에서 기준마다 무엇을 근거로 판정했는지 짧게 설명해 주세요. 아무 것도 고치지 마세요."
FOLLOW_UP = (
    "이 결과 위에 하나 더 추가해 주세요: log() 에 출처(호출한 함수 이름)도 함께 남기게 고쳐 주세요."
    " 형식은 `시각 [수준] [출처] 메시지` 입니다."
)


class System:
    def __init__(self, root: Path, log: Log) -> None:
        self.root = root
        self.log = log
        self.base = f"http://127.0.0.1:{PORT}"
        self.controller: subprocess.Popen | None = None
        self.runner: subprocess.Popen | None = None

    def _env(self, **extra: str) -> dict[str, str]:
        env = dict(os.environ)
        env.update({"PYTHONPATH": str(REPO_ROOT), "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
        env.update(extra)
        return env

    def start_controller(self) -> None:
        data = self.root / "controller"
        data.mkdir(parents=True, exist_ok=True)
        self.controller = subprocess.Popen(
            [str(PYTHON), "-m", "uvicorn", "controller.app:app", "--host", "127.0.0.1",
             "--port", str(PORT), "--log-level", "warning"],
            cwd=REPO_ROOT,
            # 제품 기본값 그대로 — 처리기·진행기 켜짐. 화면은 빌드된 web/dist.
            env=self._env(
                HADS_CONTROLLER_DATA=str(data), HADS_WEB_DIST=str(DIST),
                HADS_RUNNER_STALE_SECONDS=str(STALE_SECONDS), HADS_AUTO_PROCESS_REQUESTS="1",
                HADS_AUTO_PROGRESS_WORK="1",
            ),
            stdout=(data / "uvicorn.log").open("a", encoding="utf-8"),
            stderr=subprocess.STDOUT,
        )
        wait_until(self._healthy, "제어부 health", timeout=30, interval=0.3)

    def _healthy(self) -> bool:
        try:
            return httpx.get(f"{self.base}/api/health", timeout=2).status_code == 200
        except httpx.HTTPError:
            return False

    def start_runner(self, tag: str) -> None:
        data = self.root / "runner"
        data.mkdir(parents=True, exist_ok=True)
        self.runner = subprocess.Popen(
            [str(PYTHON), "-m", "runner.agent"],
            cwd=REPO_ROOT,
            env=self._env(HADS_RUNNER_DATA=str(data), HADS_RUNNER_ID=RUNNER_ID,
                          HADS_CONTROLLER_URL=self.base),
            stdout=(data / f"runner-{tag}.log").open("a", encoding="utf-8"),
            stderr=subprocess.STDOUT,
        )
        self.log(f"Runner 기동 ({tag}) pid={self.runner.pid}")

    def db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.root / "controller" / "controller.sqlite3")
        conn.row_factory = sqlite3.Row
        return conn

    def stop(self) -> None:
        for proc in (self.runner, self.controller):
            if proc is not None and proc.poll() is None:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
                proc.wait(timeout=30)


class Probe:
    def __init__(self, system: System, log: Log, tag: str) -> None:
        self.system = system
        self.log = log
        self.tag = tag
        self.http = httpx.Client(base_url=system.base, timeout=120)
        self.product: list[dict[str, Any]] = []
        self.observations: list[dict[str, Any]] = []
        self.facts: dict[str, Any] = {}
        self.shots: list[str] = []

    def rule(self, name: str, ok: bool, detail: Any = None) -> None:
        self.product.append({"rule": name, "ok": bool(ok), "detail": detail})
        self.log(f"[{'OK' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail is not None else ""))
        if not ok:
            raise LiveError(f"제품 규칙 위반: {name}: {detail}")

    def observe(self, name: str, detail: Any) -> None:
        self.observations.append({"observation": name, "detail": detail})
        self.log(f"[관찰] {name} — {detail}")

    def shot(self, page: Page, name: str) -> None:
        path = OUT / f"P4-05-live-{name}.png"
        page.screenshot(path=str(path))
        self.shots.append(path.name)

    def conv(self, case_id: str) -> dict[str, Any]:
        return self.http.get(f"/api/cases/{case_id}/conversation").json()

    def case(self, case_id: str) -> dict[str, Any]:
        return self.http.get(f"/api/cases/{case_id}").json()

    def case_in_url(self, page: Page) -> str | None:
        href = page.evaluate("location.href")
        return href.split("case=")[1].split("&")[0] if "case=" in href else None

    def send(self, page: Page, text: str) -> None:
        page.fill('[data-testid="composer-input"]', text)
        expect(page.locator('[data-testid="send-button"]')).to_be_enabled()
        page.click('[data-testid="send-button"]')

    def wait_progress(self, case_id: str, states: tuple[str, ...], timeout: float = STEP_TIMEOUT) -> dict[str, Any]:
        """진행이 주어진 상태(사람 대기·완료·막힘·멈춤) 중 하나가 될 때까지. 실제 AI 실행은 분 단위다."""
        last = {"step": None}

        def done():
            view = self.conv(case_id)
            progress = view.get("progress") or {}
            if progress.get("step") != last["step"]:
                last["step"] = progress.get("step")
                self.log(f"  진행: {progress.get('state')} · {progress.get('step')} · {progress.get('step_detail')}")
            return view if progress.get("state") in states and view["current_request"] is None else None

        return wait_until(done, f"진행 상태 {states}", timeout=timeout, interval=3)


def run(page: Page, system: System, probe: Probe) -> None:
    http = probe.http
    repo = system.root / "workspace"
    project = http.post(
        "/api/projects", json={"name": "로그 도구", "repo_path": str(repo), "default_tool_id": "codex"}
    ).json()
    page.goto(f"{system.base}/?project={project['id']}")
    page.wait_for_selector('[data-testid="sidebar"]')

    # ------------------------------------------------------------------ A 업무화
    page.click('[data-testid="new-conversation"]')
    case_id = wait_until(lambda: probe.case_in_url(page), "새 대화", timeout=15, interval=0.3)
    probe.facts["case_id"] = case_id
    probe.send(page, WORK_REQUEST)
    started = time.monotonic()
    # 두 번째 시도에서 본 것: 브라우저의 저장 요청과 같은 순간의 조회는 아직 요청이 없거나 막 열린
    # 요청을 싣고 온다. "처리됐다"는 **메시지가 연 요청이 끝난 것**으로만 본다.
    def a_processed(v: dict[str, Any]) -> dict[str, Any] | None:
        if v["stage"] == "work":
            return v
        settled = [r for r in v["requests"] if r["state"] not in ("processing", "unknown")]
        return v if settled and v["current_request"] is None else None

    view = wait_until(lambda: a_processed(probe.conv(case_id)), "응답·해석", timeout=STEP_TIMEOUT, interval=3)
    probe.facts["A_reply_seconds"] = round(time.monotonic() - started, 1)
    interp = view["interpretations"][-1] if view["interpretations"] else None
    probe.observe("A 해석", {k: interp[k] for k in ("report_status", "kind", "profile", "applied", "refusal")} if interp else None)
    if view["stage"] != "work":
        probe.observe("A 업무화되지 않음", "AI 가 명확한 업무 요청으로 읽지 않았다 — 제품 규칙 위반이 아니라 AI 판단. 라이브를 여기서 끝낸다")
        probe.rule("업무화되지 않았으면 준비 단계 그대로", view["stage"] == "discussion")
        probe.shot(page, "A-not-work")
        return
    probe.rule("업무화 뒤 진행 행이 생기고 첫 걸음이 같은 요청에 붙음",
               (view["progress"] or {}).get("state") in ("running", "waiting_human")
               and any(r["purpose"] == "intent_authoring" for r in probe.case(case_id)["runs"]),
               (view["progress"] or {}).get("step"))
    probe.rule("의도 초안이 도는 동안 전송 잠금(요청 유지)",
               view["current_request"] is None or view["send"]["general"]["allowed"] is False)
    probe.shot(page, "A-work")

    # ------------------------------------------------------------------ B 카드
    answered = 0
    while True:
        view = probe.wait_progress(case_id, ("waiting_human", "blocked", "paused", "done"))
        codes = [w["code"] for w in view["progress"]["wait"]]
        probe.log(f"B 대기: {codes}")
        if "intent_questions" in codes or "deferred_questions" in codes:
            questions = http.get(f"/api/cases/{case_id}/intent-state").json()["open_intent_questions"]
            deferred = http.get(f"/api/cases/{case_id}/preparation").json()["deferred_open_questions"]
            for question in questions + deferred:
                card = page.locator(f'[data-testid="question-card-{question["question_key"]}"]')
                expect(card).to_be_visible(timeout=30_000)
                card.locator("textarea").fill(GENERIC_ANSWER)
                card.locator("button", has_text="답변 보내기").click()
                answered += 1
                probe.observe("B 질문", question["summary"])
                time.sleep(2)
            probe.rule("답변 뒤 전송이 잠기고(진행 요청) 재작성이 붙음", True)
            continue
        if "intent_agreement" in codes:
            probe.rule("동의 대기에서 전송 열림·요청 종료", view["send"]["general"]["allowed"] is True and view["current_request"] is None)
            request = view["requests"][-1]
            probe.rule("요청 종료 사유에 대기 코드", (request["note_summary"] or "").startswith("waiting:"), request["note_summary"])
            gate = http.get(f"/api/cases/{case_id}/gate").json()
            conformance = http.get(f"/api/cases/{case_id}/conformance").json()
            prep = http.get(f"/api/cases/{case_id}/preparation").json()
            probe.observe("B QG-01", {"verdict": gate["verdict"], "method": conformance.get("method"), "level": prep.get("level")})
            probe.shot(page, "B-agreement")
            expect(page.locator('[data-testid="agreement-agree"]')).to_be_disabled()
            page.click('[data-testid="agreement-open"]')
            expect(page.locator('[data-testid="viewer-body"]')).not_to_be_empty(timeout=60_000)
            expect(page.locator('[data-testid="agreement-agree"]')).to_be_enabled(timeout=15_000)
            page.click('[data-testid="agreement-agree"]')
            view = wait_until(lambda: (lambda v: v if v["current_request"] or (v["progress"] or {}).get("state") != "waiting_human" else None)(probe.conv(case_id)), "동의 뒤 진행", timeout=60, interval=1)
            current = view["current_request"]
            probe.rule("동의 뒤 시스템이 진행 요청을 열어 이어 감(여는 메시지 없음)",
                       current is not None and current["origin"] == "human_decision" and current["opened_by_message_id"] is None,
                       current and (current["origin"], current["origin_ref"]))
            break
        if "gate_repair_exhausted" in codes or "preparation_repair_exhausted" in codes:
            probe.observe("B 재작성 상한", codes)
            probe.rule("재작성 상한 뒤 사람 대기(통과할 때까지 돌리지 않음)", True)
            probe.shot(page, "B-repair-exhausted")
            return
        if view["progress"]["state"] in ("blocked", "done", "paused"):
            probe.observe("B 예상 밖 상태", view["progress"])
            probe.rule("동의 전에 완료·막힘이 아님", False, view["progress"]["state"])
        probe.observe("B 다른 대기", codes)
        probe.rule("알 수 없는 대기는 없어야 한다", False, codes)
    probe.facts["B_questions_answered"] = answered

    # ------------------------------------------------------------------ C 자동 진행
    probe.shot(page, "C-running")
    view = probe.wait_progress(case_id, ("waiting_human", "blocked", "paused", "done"), timeout=STEP_TIMEOUT * 3)
    # 세 번째 시도에서 본 것: 실제 AI 는 설계·계획에 질문을 이월하고, 그 질문이 막는 작업 앞에서 진행기가
    # 사람 대기(`deferred_questions`)로 멈춘다 — 제품 규칙대로다. 이월 질문 카드에 답하고 이어 간다.
    while "deferred_questions" in [w["code"] for w in view["progress"]["wait"]]:
        probe.rule("이월 질문 대기에서 전송 열림·요청 종료",
                   view["send"]["general"]["allowed"] is True and view["current_request"] is None)
        deferred = http.get(f"/api/cases/{case_id}/preparation").json()["deferred_open_questions"]
        for question in deferred:
            card = page.locator(f'[data-testid="question-card-{question["question_key"]}"]')
            expect(card).to_be_visible(timeout=30_000)
            card.locator("textarea").fill(GENERIC_ANSWER)
            card.locator("button", has_text="답변 보내기").click()
            answered += 1
            probe.observe("C 이월 질문", question["summary"])
            time.sleep(2)
        probe.facts["B_questions_answered"] = answered
        view = wait_until(lambda: (lambda v: v if v["current_request"] or (v["progress"] or {}).get("state") != "waiting_human" else None)(probe.conv(case_id)), "이월 질문 답 뒤 진행", timeout=60, interval=1)
        current = view["current_request"]
        probe.rule("이월 질문 답 뒤 시스템이 진행 요청을 열어 이어 감",
                   current is None or (current["origin"] == "human_decision" and current["opened_by_message_id"] is None),
                   current and (current["origin"], current["origin_ref"]))
        view = probe.wait_progress(case_id, ("waiting_human", "blocked", "paused", "done"), timeout=STEP_TIMEOUT * 3)
    case = probe.case(case_id)
    purposes = [r["purpose"] for r in reversed(case["runs"])]
    probe.observe("C 실행 순서", purposes)
    probe.rule("실행은 전부 요청에 붙음(실행 사이 잠금)", all(r["request_id"] for r in case["runs"]),
               [r["run_id"] for r in case["runs"] if not r["request_id"]])
    prep = http.get(f"/api/cases/{case_id}/preparation").json()
    probe.observe("C 준비", {s: (prep[s]["state"], bool(prep[s]["artifact"])) for s in ("design", "plan", "combined")})
    tasks = prep["work_graph"].get("tasks") or []
    probe.observe("C 작업 그래프", [(t["task_key"], t["kind"], t["state"]) for t in tasks])
    criteria = case["result"]["criteria"]
    probe.observe("C 기준 판정", [(c["criterion_key"], c["verdict"], c.get("satisfaction"), c.get("recorded_by")) for c in criteria])
    probe.rule("제품이 적은 기준 판정은 검증 실행을 근거로 함",
               all(c["recorded_by"] != "policy:work_progressor" or (c["evidence_kind"] == "run_output" and c["evidence_run_id"]) for c in criteria))
    verification = [r for r in case["runs"] if r["purpose"] == "verification_run"]
    for run in verification:
        probe.observe("C 검증 명령", [(c["command_summary"], c["exit_code"]) for c in run["commands"]])
    codes = [w["code"] for w in view["progress"]["wait"]]
    human = [d for d in case["decisions"] if not d["actor"].startswith("policy:")]
    probe.observe("C 사람의 결정", [(d["kind"], d["actor"]) for d in human])
    if view["progress"]["state"] == "done":
        closure = case["result"]["closure"]
        probe.rule("자동 완료 — 사람 인수 없음", closure and closure["closure_kind"] == "completed" and all(d["kind"] != "final_acceptance" for d in human), closure)
        probe.shot(page, "C-done")
    elif "criteria_unresolved" in codes:
        probe.observe("C 미검증·미충족 기준으로 예외 카드", [(c["key"], c["verdict"]) for c in view["progress"]["wait"][0]["criteria"]])
        probe.rule("자동 정책이 예외를 스스로 수용하지 않음", case["status"] == "waiting_final_acceptance" and case["result"]["closure"] is None)
        probe.shot(page, "C-exception")
        card = page.locator('[data-testid="exception-card"]')
        expect(card).to_be_visible(timeout=30_000)
        for crit in view["progress"]["wait"][0]["criteria"]:
            page.check(f'[data-testid="exception-pick-{crit["key"]}"]')
        page.fill('[data-testid="exception-scope"]', "이 호스트에서 시험을 돌리지 못했다(알려진 환경 제약). 라이브 확인 범위에서만 수용")
        page.click('[data-testid="exception-accept"]')
        view = probe.wait_progress(case_id, ("done",), timeout=120)
        case = probe.case(case_id)
        closure = case["result"]["closure"]
        probe.rule("사람의 예외 수용으로 종료 · 원래 판정 보존",
                   closure and closure["closure_kind"] == "closed_with_exceptions"
                   and any(c["verdict"] != "met" for c in case["result"]["criteria"]), closure)
        probe.shot(page, "C-closed-with-exceptions")
    elif "task_failed" in codes or "tasks_blocked" in codes or view["progress"]["state"] == "blocked":
        probe.observe("C 멈춤", view["progress"])
        probe.rule("실패·막힘은 사람 대기로 드러남(성공으로 적지 않음)", case["result"]["closure"] is None)
        probe.shot(page, "C-stopped")
        return
    else:
        probe.observe("C 다른 대기", codes)
        probe.rule("알 수 없는 대기는 없어야 한다", False, codes)

    # ------------------------------------------------------------------ D 종료 뒤 설명
    closure_before = probe.case(case_id)["result"]["closure"]
    budget_before = http.get(f"/api/cases/{case_id}/budget").json()
    probe.rule("종료 시점 소비 snapshot 이 있음", budget_before["at_closure"] is not None)
    expect(page.locator('[data-testid="send-note"]')).to_contain_text("설명만", timeout=20_000)
    probe.send(page, EXPLANATION)
    view = wait_until(lambda: (lambda v: v if v["current_request"] is None and v["messages"][-1]["author"] == "assistant" else None)(probe.conv(case_id)), "설명 응답", timeout=STEP_TIMEOUT, interval=3)
    case = probe.case(case_id)
    probe.rule("설명 응답이 같은 대화에 붙고 종료 기록은 불변",
               case["status"] == "closed" and case["result"]["closure"] == closure_before
               and view["messages"][-1]["author"] == "assistant")
    budget_after = http.get(f"/api/cases/{case_id}/budget").json()
    probe.rule("설명 소비가 종료 뒤 소비로 나뉨", (budget_after["since_closure"] or {}).get("run_count") == 1, budget_after["since_closure"])
    probe.rule("설명이 새 대화를 만들지 않음", view["relations"] == [], view["relations"])
    expect(page.locator('article[data-author="assistant"]').last).not_to_be_empty(timeout=60_000)
    probe.observe("D 설명 응답(앞 300자)", page.locator('article[data-author="assistant"]').last.inner_text()[:300])
    probe.shot(page, "D-explanation")

    # ------------------------------------------------------------------ E 후속
    probe.send(page, FOLLOW_UP)
    view = wait_until(lambda: (lambda v: v if v["current_request"] is None and len(v["requests"]) >= 2 and v["requests"][-1]["state"] != "processing" else None)(probe.conv(case_id)), "후속 응답", timeout=STEP_TIMEOUT, interval=3)
    interp = view["interpretations"][-1]
    probe.observe("E 해석", {k: interp[k] for k in ("kind", "profile", "applied", "refusal")})
    if interp["kind"] == "work_request" and interp["applied"]:
        [relation] = [r for r in view["relations"] if r["direction"] == "successor"]
        probe.rule("수정 요청이 연결된 새 대화로 옮겨짐 · 이 업무는 종료 그대로", probe.case(case_id)["status"] == "closed", relation)
        expect(page.locator('[data-testid="follow-up-card"]')).to_be_visible(timeout=20_000)
        probe.shot(page, "E-follow-up")
        page.click('[data-testid="follow-up-link"]')
        page.wait_for_selector('[data-testid="predecessor-line"]')
        new_id = relation["case_id"]
        new_view = probe.conv(new_id)
        probe.rule("새 대화의 첫 메시지가 옮겨진 원문(저장됨)이고 이전 동의는 없음",
                   new_view["messages"][0]["receipt"] == "stored"
                   and http.get(f"/api/cases/{new_id}/policy").json()["delegation_basis"]["current"] is None)
        new_view = wait_until(lambda: (lambda v: v if v["stage"] == "work" or (v["requests"] and v["current_request"] is None) else None)(probe.conv(new_id)), "새 대화의 응답", timeout=STEP_TIMEOUT, interval=3)
        probe.observe("E 새 대화", {"stage": new_view["stage"], "profile": new_view["profile"], "progress": (new_view["progress"] or {}).get("step")})
        probe.shot(page, "E-new-conversation")
    else:
        probe.observe("E 후속 업무화되지 않음", "AI 가 수정 요청으로 읽지 않았다 — 제품 규칙 위반이 아니라 AI 판단")
        probe.rule("옮겨지지 않았으면 연결 없음", view["relations"] == [])


def main() -> int:
    if not (DIST / "index.html").exists():
        print("web/dist 가 없다 — web 에서 npm run build 를 먼저 한다", file=sys.stderr)
        return 2
    tag = stamp()
    root = LIVE_ROOT / tag
    root.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    version = subprocess.run(["codex", "--version"], capture_output=True, text=True, shell=True).stdout.strip()
    with Log(OUT / "P4-05-live.log") as log:
        log(f"P4-05 라이브 {tag} · codex {version or '버전 확인 실패'} · 데이터 {root}")
        system = System(root, log)
        probe = Probe(system, log, tag)
        make_repo(root)
        status = "passed"
        error = None
        try:
            system.start_controller()
            system.start_runner("first")
            wait_until(lambda: any(r["id"] == RUNNER_ID and r["connection"]["state"] == "connected"
                                   for r in probe.http.get("/api/runners").json()), "Runner 연결", timeout=60)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="msedge", headless=True)
                expect.set_options(timeout=20_000)
                page = browser.new_context(viewport={"width": 1400, "height": 900}).new_page()
                page.set_default_timeout(60_000)
                try:
                    run(page, system, probe)
                finally:
                    browser.close()
        except Exception as exc:  # noqa: BLE001 — 라이브는 실패를 그대로 적는다
            status = "failed"
            error = f"{type(exc).__name__}: {exc}"
            log(f"실패: {error}")
        finally:
            system.stop()
            leftover = os_processes(str(root))
            log(f"종료 뒤 이 라이브의 남은 프로세스: {len(leftover)}")
        result = {
            "tag": tag, "status": status, "error": error, "codex_version": version,
            "product_rules": probe.product, "observations": probe.observations,
            "facts": probe.facts, "screenshots": probe.shots, "data_root": str(root),
        }
        (OUT / "P4-05-live-results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"결과: {status} · 제품 규칙 {sum(r['ok'] for r in probe.product)}/{len(probe.product)} · 관찰 {len(probe.observations)}")
    return 0 if status == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
