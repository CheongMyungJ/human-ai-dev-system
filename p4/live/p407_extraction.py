"""P4-07 라이브 — **실제 codex** 의 작업 실행이 지식 후보를 남기고, 사람이 활성화한 것이 다른 대화에 주입되는가
(P4-PLAN-07 AC-13).

자동 시험은 가짜 CLI 로 같은 경로를 본다. 여기서 보는 것은 실제 AI 가 (1) 작업 실행(검증·구현)에서 후보
블록을 붙이는지, (2) 사용자가 "정리해줘"라고 청한 논의 응답에서 `proposal: true` 항목을 붙이는지, 그리고
제품이 그것을 **후보로만** 등록하고 사람의 활성화 뒤 **다른 대화**의 실행에 넣는지다.

    A. 업무      새 대화 → 명확한 기능 요청 → 업무화 → 동의 → 구현·검증 → 예외 카드 대기(또는 완료).
                 실행마다 후보 규칙이 지시문에 있었는가(제품 규칙) · 후보를 남겼는가(관찰)
    B. 정리      같은 대화(종료 전이면 업무 단계 논의, 종료 뒤면 설명 응답)에 "이 업무에서 배운 것을 지식
                 후보로 정리해줘" → AI 제안 항목(관찰). 등록되면 후보·ai_proposal·권위 메시지 없음(제품 규칙)
    C. 활성화    후보 하나를 채택 확인 → 활성화(사람의 결정, API) → 다른 대화의 업무 실행에 그 버전이 들어간다
                 (제품 규칙). 후보였을 때는 보조(후보)로, 활성 뒤에는 효력대로

**판정은 두 층이다.** 제품 규칙이 어긋나면 멈춘다. AI 의 판단(후보를 붙였는가·내용)은 관찰로 적는다.
**제품 코드를 import 하지 않는다** — HTTP·브라우저·OS 로만 본다. 라이브 데이터는
`%LOCALAPPDATA%\\Temp\\hads-p4-07-live`, 저장소 `var\\` 를 건드리지 않는다.

실행: `.venv\\Scripts\\python.exe p4\\live\\p407_extraction.py` (먼저 `npm run build`,
`PYTHONUTF8=1 PYTHONIOENCODING=utf-8`)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from playwright.sync_api import Page, expect, sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "p3" / "live"))
sys.path.insert(0, str(REPO_ROOT / "ui" / "live"))

from driver import PYTHON, LiveError, Log, stamp, wait_until  # noqa: E402
from ui03_shell import make_repo, os_processes  # noqa: E402

RUNNER_ID = "runner-p4-07-live"
OUT = REPO_ROOT / "p4" / "evidence"
LIVE_ROOT = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Temp" / "hads-p4-07-live"
DIST = REPO_ROOT / "web" / "dist"
PORT = 8798
STALE_SECONDS = 5
STEP_TIMEOUT = 900

WORK_REQUEST = (
    "app.py 에 오류 줄만 골라 내는 함수 error_lines(lines) 를 추가해 주세요. 인자로 받은 문자열 목록에서"
    " 수준이 ERROR 인 줄(표본 형식은 README 참고)만 원래 순서대로 돌려줍니다. log() 는 바꾸지 마세요. 확인은"
    " README 의 시험 방법대로 기존 시험이 통과하는지와, samples/app.log 로 error_lines 를 돌려 ERROR 줄 두 개가"
    " 나오는지 보면 됩니다. 이 저장소 밖은 건드리지 마세요."
)
SECOND_REQUEST = (
    "app.py 에 경고 줄만 골라 내는 함수 warning_lines(lines) 를 추가해 주세요. 'WARN' 으로 시작하는 줄만"
    " 원래 순서대로 돌려줍니다. 다른 함수는 바꾸지 마세요. 확인은"
    " `python -c \"import app; print(app.warning_lines(['WARN a', 'x', 'WARN b']))\"` 의 출력이"
    " ['WARN a', 'WARN b'] 인지 보는 것으로 충분합니다."
)
SUMMARIZE_REQUEST = (
    "이 업무에서 다음 작업에도 재사용할 만한 사실(빌드·시험·환경 조건, 구조, 알려진 문제)이 있으면 지식 후보로"
    " 정리해 주세요. 저장소(README·tests)를 읽고 당신이 직접 확인한 사실만 적고, 내가 정한 규칙이 아니라 당신의"
    " 관찰이므로 후보(proposal)로 붙여 주세요. 없으면 없다고 답해도 됩니다. 작업을 시작하지는 마세요."
)


def enrich_repo(repo: Path) -> None:
    """둘째 시도부터: 저장소에 **비자명한 시험 조건**을 둔다 — 시험은 루트에서 `python -m pytest -q` 로 돌고 표본
    로그는 `samples/app.log` 이며 환경 변수 `LOGTOOL_SAMPLES` 로 바꾼다. 작업 실행이 관측할 거리를 주는 것이지
    후보를 쓰라고 지시하는 것이 아니다(후보를 붙일지는 AI 판단이며 관찰로 적는다)."""
    (repo / "samples").mkdir(exist_ok=True)
    (repo / "samples" / "app.log").write_text(
        "12:00:01 INFO started\n12:00:02 ERROR disk full\n12:00:03 WARN slow\n12:00:04 ERROR retry failed\n",
        encoding="utf-8",
    )
    (repo / "tests").mkdir(exist_ok=True)
    (repo / "tests" / "test_app.py").write_text(
        "import os\nimport pathlib\n\nimport app\n\n\n"
        "def _sample_lines():\n"
        "    default = pathlib.Path(__file__).resolve().parents[1] / 'samples' / 'app.log'\n"
        "    path = pathlib.Path(os.environ.get('LOGTOOL_SAMPLES', default))\n"
        "    return path.read_text(encoding='utf-8').splitlines()\n\n\n"
        "def test_sample_has_error_lines():\n"
        "    assert any(' ERROR ' in line for line in _sample_lines())\n\n\n"
        "def test_log_is_callable():\n"
        "    assert callable(app.log)\n",
        encoding="utf-8",
    )
    readme = repo / "README.md"
    readme.write_text(
        readme.read_text(encoding="utf-8")
        + "\n## 시험\n\n저장소 **루트에서** `python -m pytest -q` 로 돌린다(시험이 `app` 을 import 한다). 표본 로그는"
        " `samples/app.log` 이며 환경 변수 `LOGTOOL_SAMPLES` 로 다른 파일을 지정할 수 있다. 표본의 줄 형식은"
        " `시각 수준 메시지` 이고 수준은 INFO/WARN/ERROR 다.\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "tests and samples"], cwd=repo, check=True, capture_output=True)
GENERIC_ANSWER = "제안한 대로 하세요. 추가 제약은 없고, 이 요청의 범위를 넘는 선택이 필요하면 다시 물어 주세요."
WORK_PURPOSES = ("intent_authoring", "design_authoring", "plan_authoring", "feature_implementation", "verification_run")
EXTRACTION_PURPOSES = ("feature_implementation", "verification_run", "limited_analysis", "local_experiment")


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

    def start_runner(self) -> None:
        data = self.root / "runner"
        data.mkdir(parents=True, exist_ok=True)
        self.runner = subprocess.Popen(
            [str(PYTHON), "-m", "runner.agent"],
            cwd=REPO_ROOT,
            env=self._env(HADS_RUNNER_DATA=str(data), HADS_RUNNER_ID=RUNNER_ID,
                          HADS_CONTROLLER_URL=self.base),
            stdout=(data / "runner.log").open("a", encoding="utf-8"),
            stderr=subprocess.STDOUT,
        )
        self.log(f"Runner 기동 pid={self.runner.pid}")

    def stop(self) -> None:
        for proc in (self.runner, self.controller):
            if proc is not None and proc.poll() is None:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
                proc.wait(timeout=30)


class Probe:
    def __init__(self, system: System, log: Log) -> None:
        self.system = system
        self.log = log
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
        path = OUT / f"P4-07-live-{name}.png"
        page.screenshot(path=str(path))
        self.shots.append(path.name)

    def conv(self, case_id: str) -> dict[str, Any]:
        return self.http.get(f"/api/cases/{case_id}/conversation").json()

    def case(self, case_id: str) -> dict[str, Any]:
        return self.http.get(f"/api/cases/{case_id}").json()

    def knowledge(self, project_id: str) -> dict[str, Any]:
        return self.http.get(f"/api/projects/{project_id}/knowledge").json()

    def case_in_url(self, page: Page) -> str | None:
        href = page.evaluate("location.href")
        return href.split("case=")[1].split("&")[0] if "case=" in href else None

    def new_conversation(self, page: Page) -> str:
        before = self.case_in_url(page)
        page.click('[data-testid="new-conversation"]')
        return wait_until(
            lambda: (lambda c: c if c and c != before else None)(self.case_in_url(page)),
            "새 대화", timeout=15, interval=0.3,
        )

    def send(self, page: Page, text: str) -> None:
        page.fill('[data-testid="composer-input"]', text)
        expect(page.locator('[data-testid="send-button"]')).to_be_enabled()
        page.click('[data-testid="send-button"]')

    def read_original(self, artifact_id: str, revision: int) -> str | None:
        created = self.http.post(f"/api/artifacts/{artifact_id}/{revision}/read-requests", json={})
        if created.status_code != 201:
            return None
        request_id = created.json()["id"]

        def served():
            row = self.http.get(f"/api/read-requests/{request_id}").json()
            if row.get("content") is not None:
                return row
            return row if row["request"]["state"] in ("failed", "expired", "delivered") else None

        row = wait_until(served, "원문 열람", timeout=60, interval=0.5)
        return row.get("content")

    def wait_progress(self, case_id: str, states: tuple[str, ...], timeout: float = STEP_TIMEOUT) -> dict[str, Any]:
        last = {"step": None}

        def done():
            view = self.conv(case_id)
            progress = view.get("progress") or {}
            if progress.get("step") != last["step"]:
                last["step"] = progress.get("step")
                self.log(f"  진행: {progress.get('state')} · {progress.get('step')} · {progress.get('step_detail')}")
            return view if progress.get("state") in states and view["current_request"] is None else None

        return wait_until(done, f"진행 상태 {states}", timeout=timeout, interval=3)

    def wait_reply(self, case_id: str, count: int, timeout: float = STEP_TIMEOUT) -> dict[str, Any]:
        """대화의 AI 응답이 `count` 개가 되고 현재 요청이 없을 때까지."""

        def done():
            view = self.conv(case_id)
            replies = [m for m in view["messages"] if m["author"] == "assistant"]
            return view if len(replies) >= count and view["current_request"] is None else None

        return wait_until(done, f"응답 {count}개", timeout=timeout, interval=3)


def drive_work(page: Page, probe: Probe, http: httpx.Client, case_id: str, label: str) -> dict[str, Any]:
    """업무화된 대화를 사람 대기(질문·동의)만 처리하며 멈출 때까지 돌린다."""
    while True:
        view = probe.wait_progress(case_id, ("waiting_human", "blocked", "paused", "done"), timeout=STEP_TIMEOUT * 3)
        codes = [w["code"] for w in view["progress"]["wait"]]
        probe.log(f"{label} 대기: {codes} · {view['progress']['state']}")
        if "intent_questions" in codes or "deferred_questions" in codes:
            questions = http.get(f"/api/cases/{case_id}/intent-state").json()["open_intent_questions"]
            deferred = http.get(f"/api/cases/{case_id}/preparation").json()["deferred_open_questions"]
            for question in questions + deferred:
                card = page.locator(f'[data-testid="question-card-{question["question_key"]}"]')
                expect(card).to_be_visible(timeout=30_000)
                card.locator("textarea").fill(GENERIC_ANSWER)
                card.locator("button", has_text="답변 보내기").click()
                probe.observe(f"{label} 질문", question["summary"])
                time.sleep(2)
            wait_until(lambda: (lambda v: v if v["current_request"] or (v["progress"] or {}).get("state") != "waiting_human" else None)(probe.conv(case_id)), "답 뒤 진행", timeout=60, interval=1)
            continue
        if "intent_agreement" in codes:
            page.click('[data-testid="agreement-open"]')
            expect(page.locator('[data-testid="viewer-body"]')).not_to_be_empty(timeout=60_000)
            expect(page.locator('[data-testid="agreement-agree"]')).to_be_enabled(timeout=15_000)
            page.click('[data-testid="agreement-agree"]')
            wait_until(lambda: (lambda v: v if v["current_request"] or (v["progress"] or {}).get("state") != "waiting_human" else None)(probe.conv(case_id)), "동의 뒤 진행", timeout=60, interval=1)
            continue
        return view


def start_work(page: Page, probe: Probe, request: str, label: str) -> str | None:
    case_id = probe.new_conversation(page)
    probe.send(page, request)

    def started(v: dict[str, Any]) -> dict[str, Any] | None:
        if v["stage"] == "work":
            return v
        settled = [r for r in v["requests"] if r["state"] not in ("processing", "unknown")]
        return v if settled and v["current_request"] is None else None

    view = wait_until(lambda: started(probe.conv(case_id)), f"{label} 업무화", timeout=STEP_TIMEOUT, interval=3)
    if view["stage"] != "work":
        probe.observe(f"{label} 업무화되지 않음", "AI 가 업무 요청으로 읽지 않았다 — AI 판단")
        return None
    return case_id


def run(page: Page, system: System, probe: Probe) -> None:
    http = probe.http
    repo = system.root / "workspace"
    project = http.post(
        "/api/projects", json={"name": "로그 도구", "repo_path": str(repo), "default_tool_id": "codex"}
    ).json()
    probe.facts["project_id"] = project["id"]
    page.goto(f"{system.base}/?project={project['id']}")
    page.wait_for_selector('[data-testid="sidebar"]')

    # ------------------------------------------------------------------ A 업무 — 실행마다 후보 규칙, 후보는 관찰
    work_case = start_work(page, probe, WORK_REQUEST, "A")
    if work_case is None:
        return
    probe.facts["work_case"] = work_case
    view = drive_work(page, probe, http, work_case, "A")
    probe.observe("A 멈춘 자리", {"state": view["progress"]["state"], "codes": [w["code"] for w in view["progress"]["wait"]]})
    probe.shot(page, "A-stopped")
    case = probe.case(work_case)
    runs = list(reversed(case["runs"]))
    probe.observe("A 실행", [(r["purpose"], r["outcome"]) for r in runs])
    extraction_runs = [r for r in runs if r["purpose"] in EXTRACTION_PURPOSES and r["status"] == "finished"]
    probe.rule("작업 실행(구현·검증)이 하나 이상 끝났음", bool(extraction_runs), [r["purpose"] for r in extraction_runs])
    registrations = view.get("knowledge_registrations") or []
    extracted = [r for r in registrations if r.get("origin") == "extraction"]
    probe.observe("A 작업 실행이 남긴 후보·근거·거부", [
        {k: r.get(k) for k in ("run_id", "intake_state", "refusal", "knowledge_key", "kind", "obligation", "summary", "relation", "relates_to_key", "basis")}
        for r in extracted
    ])
    probe.rule("실행마다 후보 규칙이 지시문에 있었음(Manifest 기록·지식 목록 배정)",
               all(http.get(f"/api/runs/{r['run_id']}/knowledge").json()["recorded"] for r in extraction_runs))
    for r in extracted:
        if r["intake_state"] == "registered":
            probe.rule(f"후보 {r['knowledge_key']} 는 후보·AI 제안·활성 필수 아님",
                       r["state"] == "candidate" and r["authority_kind"] == "ai_proposal",
                       {k: r.get(k) for k in ("state", "authority_kind", "obligation")})
    if extracted:
        probe.rule("대화에 지식 후보 카드가 보임", page.locator('[data-testid="knowledge-candidate-card"]').count() == 1)
        probe.shot(page, "A-candidates")
    criteria = case["result"]["criteria"]
    probe.rule("기준 판정은 지식 후보와 무관(검증 실행 보고 또는 미검증)",
               all(c["recorded_by"] in ("policy:work_progressor", None) or c["verdict"] == "unverified" for c in criteria)
               if criteria else True)

    # ------------------------------------------------------------------ B 정리 — 논의 응답의 제안
    replies_before = len([m for m in probe.conv(work_case)["messages"] if m["author"] == "assistant"])
    probe.send(page, SUMMARIZE_REQUEST)
    started = time.monotonic()
    view = probe.wait_reply(work_case, replies_before + 1)
    probe.facts["B_reply_seconds"] = round(time.monotonic() - started, 1)
    reply = [m for m in view["messages"] if m["author"] == "assistant"][-1]
    reply_body = probe.read_original(reply["artifact_id"], reply["artifact_rev"]) or ""
    probe.rule("대화의 AI 말에는 등록 블록이 없음", "hads-knowledge" not in reply_body)
    probe.observe("B 응답(끝 500자)", reply_body[-500:])
    proposals = [r for r in (view.get("knowledge_registrations") or []) if r["run_id"] == reply["run_id"]]
    probe.observe("B 정리 응답의 항목", [
        {k: r.get(k) for k in ("origin", "intake_state", "refusal", "knowledge_key", "kind", "obligation", "summary", "basis")}
        for r in proposals
    ])
    statements = [r for r in proposals if r["intake_state"] == "registered" and r["origin"] == "statement"]
    probe.rule("정리 응답이 사용자 말(활성 규칙)을 만들지 않음 — 제안은 후보뿐", not statements,
               [r["knowledge_key"] for r in statements])
    knowledge = probe.knowledge(project["id"])
    candidates = [i for i in knowledge["items"] if i["current"] and i["current"]["state"] == "candidate"]
    probe.observe("현재 후보", [(i["knowledge_key"], i["current"]["kind"], i["current"]["obligation"], i["current"]["summary"]) for i in candidates])
    for item in candidates:
        current = item["current"]
        probe.rule(f"{item['knowledge_key']} 원문은 서버에 있고 권위 메시지 없음",
                   current["storage"] == "server" and current["source_message_id"] is None,
                   {"storage": current["storage"], "source_message_id": current["source_message_id"]})
    user_said = next(m for m in view["messages"] if m["author"] == "user" and "지식 후보로" in (m.get("summary") or ""))\
        if any("지식 후보로" in (m.get("summary") or "") for m in view["messages"] if m["author"] == "user") else None
    if proposals and user_said is not None:
        probe.shot(page, "B-proposal")
    if not candidates:
        probe.observe("후보 없음", "실제 codex 가 작업 실행에서도 정리 응답에서도 후보를 남기지 않았다 — AI 판단. C 를 건너뛴다")
        return

    # ------------------------------------------------------------------ C 활성화 → 다른 대화의 실행에 주입
    chosen = candidates[0]
    kid = chosen["id"]
    check = http.get(f"/api/knowledge/{kid}/adoption-check").json()
    probe.observe("C 채택 확인", {"blocked": check["blocked"], "findings": [(f["code"], f["blocking"]) for f in check["findings"]], "evidence": check["evidence_count"]})
    probe.rule("채택 확인은 근거·독립 검토 없음을 값으로 낸다", "independent_review_not_run" in {f["code"] for f in check["findings"]})
    if check["blocked"]:
        probe.observe("C 활성화 불가", f"막는 항목 {check['blocked']} — 이 후보로는 활성화하지 않는다")
        return
    activated = http.post(f"/api/knowledge/{kid}/activate", json={"reason_summary": "라이브에서 확인한 관찰(사람의 결정)"})
    probe.rule("후보 활성화(사람의 결정)가 새 버전을 만든다", activated.status_code == 200, activated.text[:200])
    version = activated.json()["version"]
    probe.rule("새 버전은 활성·user_decision·채택 확인 기록", version["state"] == "active" and version["authority_kind"] == "user_decision" and version["adoption"] is not None,
               {k: version.get(k) for k in ("knowledge_key", "version", "state", "authority_kind")})
    probe.facts["activated"] = {"key": version["knowledge_key"], "version": version["version"], "obligation": version["obligation"], "activities": version["activities"], "scope": version["scope_kind"]}
    content = probe.read_original(version["artifact_id"], version["artifact_rev"])
    probe.observe("C 활성화한 적용 내용", content)

    page.goto(f"{system.base}/?project={project['id']}")
    page.wait_for_selector('[data-testid="sidebar"]')
    second_case = start_work(page, probe, SECOND_REQUEST, "C")
    if second_case is None:
        return
    probe.facts["second_case"] = second_case
    view = drive_work(page, probe, http, second_case, "C")
    probe.observe("C 멈춘 자리", {"state": view["progress"]["state"], "codes": [w["code"] for w in view["progress"]["wait"]]})
    probe.shot(page, "C-stopped")
    case = probe.case(second_case)
    runs = [r for r in reversed(case["runs"]) if r["purpose"] in WORK_PURPOSES and r["status"] == "finished"]
    probe.observe("C 실행", [(r["purpose"], r["outcome"]) for r in runs])
    expected_role = "knowledge_required" if version["obligation"] == "required" else "knowledge_reference"
    applied_runs = 0
    for run_row in runs:
        manifest = http.get(f"/api/runs/{run_row['run_id']}/knowledge").json()
        decision = {i["knowledge_key"]: (i["decision"], i["version"]) for i in manifest["items"]}
        refs = http.get(f"/api/runs/{run_row['run_id']}/context-refs").json()
        mine = [r for r in refs if r.get("knowledge") and r["knowledge"]["key"] == version["knowledge_key"]]
        if decision.get(version["knowledge_key"], (None,))[0] == "provided":
            applied_runs += 1
            probe.rule(f"{run_row['purpose']} 에 {version['knowledge_key']} v{version['version']} 가 {expected_role} 로 들어가고 Runner 가 읽음",
                       len(mine) == 1 and mine[0]["role"] == expected_role and mine[0]["receipt_status"] == "read"
                       and decision[version["knowledge_key"]][1] == version["version"],
                       {"roles": [r["role"] for r in mine], "receipt": [r["receipt_status"] for r in mine], "decision": decision.get(version["knowledge_key"])})
        else:
            probe.observe(f"{run_row['purpose']} 에는 {version['knowledge_key']} 가 들어가지 않음(활동·범위)", decision.get(version["knowledge_key"]))
    probe.rule("활성화한 지식이 다른 대화의 실행 하나 이상에 주입됨(활동·범위에 맞는 실행)", applied_runs >= 1, applied_runs)


def main() -> int:
    if not (DIST / "index.html").exists():
        print("web/dist 가 없다 — web 에서 npm run build 를 먼저 한다", file=sys.stderr)
        return 2
    tag = stamp()
    root = LIVE_ROOT / tag
    root.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    version = subprocess.run(["codex", "--version"], capture_output=True, text=True, shell=True).stdout.strip()
    with Log(OUT / "P4-07-live.log") as log:
        log(f"P4-07 라이브 {tag} · codex {version or '버전 확인 실패'} · 데이터 {root}")
        system = System(root, log)
        probe = Probe(system, log)
        enrich_repo(make_repo(root))
        status = "passed"
        error = None
        try:
            system.start_controller()
            system.start_runner()
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
        (OUT / "P4-07-live-results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"결과: {status} · 제품 규칙 {sum(r['ok'] for r in probe.product)}/{len(probe.product)} · 관찰 {len(probe.observations)}")
    return 0 if status == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
