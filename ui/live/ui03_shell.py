"""UI-03 라이브 — 기본 대화 화면을 **실제 브라우저·실제 codex** 로 쓴다(UI-PLAN-03 AC-19).

자동 시험(`tests/test_web_shell.py`)은 가짜 CLI 로 같은 화면 경로를 본다. 여기서 보는 것은 사람이
실제로 쓰는 모양 그대로다: 설치된 Edge 로 화면을 누르고, 제어부의 요청 처리기가 **실제 codex** 에게
논의 응답을 시키고, AI 가 업무 요청을 해석해 같은 대화에서 업무로 전환되는가.

    A. 논의        새 대화 → 논의 메시지 → 처리 중 전송 잠금 → 실제 AI 응답이 대화에 붙음
    B. 초안        입력 → 이 브라우저에 저장 → 새로 고침 뒤 복구(자동 전송 없음)
    C. 업무화      명확한 분석 요청 → AI 해석 → 같은 Case 업무화(위임 근거 = 사용자 메시지)
    D. 중단        긴 실행을 화면의 중단 버튼으로 → 트리 종료(OS 목록으로 확인) → 전송 열림
    E. 결과물      의도 v1(질문 하나) → 질문 카드 답변 → 열람 v1 고정 중 v2 → 새 버전 안내·비교·전환
    F. PC 단절     Runner 프로세스를 내림 → 불러온 본문·초안 유지, 전송·새 열람 없음 → 재기동 뒤
                   자동 전송 없음

**판정은 두 층이다.** 제품 규칙이 어긋나면 멈춘다. AI 의 판단(어느 Profile 로 읽었는가, 글이 무엇을
말했는가)은 관찰로 적는다. **제품 코드를 import 하지 않는다** — HTTP·브라우저·OS 로만 본다.
라이브 데이터는 `%LOCALAPPDATA%\\Temp\\hads-ui-03-live`, 저장소 `var\\` 를 건드리지 않는다.

실행: `.venv\\Scripts\\python.exe ui\\live\\ui03_shell.py` (먼저 `npm run build`)
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

from driver import PYTHON, LiveError, Log, stamp, wait_until  # noqa: E402

RUNNER_ID = "runner-ui-03-live"
OUT = REPO_ROOT / "ui" / "evidence"
LIVE_ROOT = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Temp" / "hads-ui-03-live"
DIST = REPO_ROOT / "web" / "dist"
PORT = 8799
STALE_SECONDS = 5
SLEEP_D = 93

DISCUSSION = (
    "이 저장소의 README 와 app.py 를 보고, 로그 한 줄의 형식을 바꾸는 방향으로 두 가지 선택지를 짧게"
    " 이야기해 주세요. 아직 아무 것도 만들거나 고치지 말고, 어느 쪽이 나을지는 제가 정하겠습니다."
)
WORK_REQUEST = (
    "좋아요. 이 저장소의 README 와 app.py 를 읽고 지금 로그 형식의 문제와 개선안을 분석해서 정리해"
    " 주세요. 파일은 고치지 말고 결과를 글로 정리해 주세요."
)


def long_prompt(seconds: int) -> str:
    return (
        f"PowerShell 에서 `Start-Sleep -Seconds {seconds}` 명령 하나만 실행하고 그 명령이 끝날 때까지"
        " 기다린 뒤, 'done' 이라고만 답해 주세요. 파일은 읽거나 수정하지 마세요."
    )


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def make_repo(root: Path) -> Path:
    repo = root / "workspace"
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "live@example.invalid")
    _git(repo, "config", "user.name", "live")
    (repo / "README.md").write_text(
        "# 작은 로그 도구\n\n`app.py` 의 `log()` 가 한 줄씩 남긴다. 사람이 읽기도 하고, 나중에 모아\n"
        "분석하기도 한다. 지금 형식은 `시각 메시지` 이며 수준(INFO/ERROR)과 출처가 없다.\n",
        encoding="utf-8",
    )
    (repo / "app.py").write_text(
        "import time\n\n\ndef log(message):\n    print(f\"{time.strftime('%H:%M:%S')} {message}\")\n",
        encoding="utf-8",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")
    return repo


def os_processes(*needles: str) -> list[dict[str, Any]]:
    """명령줄에 표지가 든 프로세스(OS 에서 직접). 제품 코드를 쓰지 않는다(UI-02 라이브와 같다)."""
    script = (
        "[Console]::OutputEncoding = [Text.Encoding]::UTF8;"
        " Get-CimInstance Win32_Process | Select-Object ProcessId,Name,CommandLine"
        " | ConvertTo-Json -Compress"
    )
    raw = subprocess.run(["pwsh", "-NoProfile", "-Command", script], capture_output=True, timeout=60).stdout
    out = raw.decode("utf-8", errors="replace")
    rows = json.loads(out) if out.strip() else []
    rows = rows if isinstance(rows, list) else [rows]
    return [
        {"pid": r["ProcessId"], "name": r["Name"], "cmd": (r.get("CommandLine") or "")[:200]}
        for r in rows
        if r["ProcessId"] != os.getpid()
        and any(n in (r.get("CommandLine") or "") for n in needles)
        and "Get-CimInstance" not in (r.get("CommandLine") or "")
    ]


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
            # 제품 기본값 그대로 — 요청 처리기 켜짐. 화면은 빌드된 web/dist.
            env=self._env(
                HADS_CONTROLLER_DATA=str(data), HADS_WEB_DIST=str(DIST),
                HADS_RUNNER_STALE_SECONDS=str(STALE_SECONDS), HADS_AUTO_PROCESS_REQUESTS="1",
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

    def kill_runner_only(self) -> None:
        """Runner 프로세스 하나만(`/T` 없이). 사람이 PC 에서 Runner 를 끈 것과 같다."""
        assert self.runner is not None
        subprocess.run(["taskkill", "/F", "/PID", str(self.runner.pid)], capture_output=True)
        self.runner.wait(timeout=30)

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
        path = OUT / f"UI-03-live-{name}.png"
        page.screenshot(path=str(path))
        self.shots.append(path.name)

    def conv(self, case_id: str) -> dict[str, Any]:
        return self.http.get(f"/api/cases/{case_id}/conversation").json()

    def case_in_url(self, page: Page) -> str | None:
        href = page.evaluate("location.href")
        return href.split("case=")[1].split("&")[0] if "case=" in href else None

    def send(self, page: Page, text: str) -> None:
        page.fill('[data-testid="composer-input"]', text)
        expect(page.locator('[data-testid="send-button"]')).to_be_enabled()
        page.click('[data-testid="send-button"]')

    def wait_settled(self, case_id: str, count: int, timeout: float = 600) -> dict[str, Any]:
        """요청 `count` 개가 모두 끝날 때까지(실제 AI 응답은 분 단위일 수 있다)."""
        def done():
            view = self.conv(case_id)
            return view if len(view["requests"]) >= count and view["current_request"] is None else None
        return wait_until(done, f"요청 {count}개 종료", timeout=timeout, interval=2)


def run(page: Page, system: System, probe: Probe) -> None:
    http = probe.http
    repo = system.root / "workspace"
    project = http.post(
        "/api/projects", json={"name": "로그 도구", "repo_path": str(repo), "default_tool_id": "codex"}
    ).json()
    page.goto(f"{system.base}/?project={project['id']}")
    page.wait_for_selector('[data-testid="sidebar"]')
    probe.rule("기본 화면이 대화 화면이고 라이트 테마", page.evaluate("document.documentElement.dataset.theme") == "light")

    # ------------------------------------------------------------------ A 논의
    page.click('[data-testid="new-conversation"]')
    case_id = wait_until(lambda: probe.case_in_url(page), "새 대화", timeout=15, interval=0.3)
    probe.facts["case_id"] = case_id
    expect(page.locator('[data-testid="stage-label"]')).to_contain_text("논의 중")
    probe.send(page, DISCUSSION)
    expect(page.locator('[data-testid="request-progress"]')).to_be_visible(timeout=20_000)
    refusal = page.locator('[data-testid="send-refusal"]').inner_text()
    probe.rule("처리 중 일반 전송은 서버 판정대로 막힘", "현재 요청을 처리하고 있다" in refusal, refusal)
    page.fill('[data-testid="composer-input"]', "응답을 기다리는 동안 쓰는 초안")
    probe.rule("처리 중에도 초안 편집 가능 · 보내기 비활성",
               page.locator('[data-testid="send-button"]').is_disabled())
    probe.shot(page, "A-processing")
    started = time.monotonic()
    view = probe.wait_settled(case_id, 1)
    probe.facts["A_reply_seconds"] = round(time.monotonic() - started, 1)
    request = view["requests"][0]
    probe.rule("요청 처리기가 응답하고 요청을 끝냄", (request["state"], request["settled_by"]) == ("completed", "request-processor"), request["state"])
    probe.rule("응답 실행은 읽기 전용 논의 응답 하나", [(r["purpose"]) for r in request["runs"]] == ["discussion_reply"])
    expect(page.locator('[data-testid="message-2"] [data-testid="message-body"]')).not_to_be_empty(timeout=60_000)
    reply_a = page.locator('[data-testid="message-2"] [data-testid="message-body"]').inner_text()
    probe.rule("AI 응답 본문이 화면에 보이고 기계용 블록은 없다", bool(reply_a.strip()) and "hads-interpretation" not in page.content())
    probe.observe("A 응답(앞 200자)", reply_a[:200])
    [interp_a] = view["interpretations"]
    probe.observe("A 해석", {k: interp_a[k] for k in ("report_status", "kind", "profile", "applied", "refusal")})
    probe.rule("해석과 단계가 일치(적용된 업무 요청이 없으면 논의 단계)",
               (view["stage"] == "discussion") == (not interp_a["applied"]), view["stage"])
    probe.rule("막혀 있던 동안 쓴 초안은 자동으로 보내지지 않음",
               page.input_value('[data-testid="composer-input"]') == "응답을 기다리는 동안 쓰는 초안"
               and len(view["messages"]) == 2)
    probe.shot(page, "A-reply")

    # ------------------------------------------------------------------ B 초안
    page.fill('[data-testid="composer-input"]', "새로 고쳐도 남아야 하는 초안")
    expect(page.locator('[data-testid="draft-state"]')).to_contain_text("초안 저장됨")
    page.reload()
    page.wait_for_selector('[data-testid="composer-input"]')
    probe.rule("새로 고침 뒤 초안 복구", page.input_value('[data-testid="composer-input"]') == "새로 고쳐도 남아야 하는 초안")
    probe.rule("복구가 전송을 만들지 않음", len(probe.conv(case_id)["messages"]) == 2)
    storage = page.evaluate("JSON.stringify(Object.assign({}, window.localStorage))")
    probe.rule("브라우저 저장소에 대화 본문 없음(초안만)", reply_a[:40] not in storage)
    page.fill('[data-testid="composer-input"]', "")

    # ------------------------------------------------------------------ C 업무화
    probe.send(page, WORK_REQUEST)
    view = probe.wait_settled(case_id, 2)
    interp_c = view["interpretations"][-1]
    probe.observe("C 해석", {k: interp_c[k] for k in ("report_status", "kind", "profile", "applied", "refusal")})
    expect(page.locator('[data-testid="message-4"] [data-testid="message-body"]')).not_to_be_empty(timeout=60_000)
    reply_c = page.locator('[data-testid="message-4"] [data-testid="message-body"]').inner_text()
    probe.observe("C 응답(앞 300자)", reply_c[:300])
    if interp_c["applied"]:
        work = view["work_start"]
        probe.rule("AI 해석 업무화: 같은 Case·결정 주체 AI·근거 실행", (work["decided_by"], work["interpretation_run_id"]) == ("ai_interpretation", interp_c["run_id"]))
        opening = next(m for m in view["messages"] if m["id"] == work["request_message_id"])
        policy = http.get(f"/api/cases/{case_id}/policy").json()
        basis = policy["delegation_basis"]["current"]
        probe.rule("위임 근거는 사용자 메시지 원문", (basis["basis_kind"], basis["artifact_id"]) == ("original_request", opening["artifact_id"]))
        runs = http.get(f"/api/cases/{case_id}").json()["runs"]
        probe.rule("업무화가 실행을 시작하지 않음(응답 실행만)", all(r["purpose"] == "discussion_reply" for r in runs), [r["purpose"] for r in runs])
        expect(page.locator('[data-testid="work-start-card"]')).to_be_visible(timeout=20_000)
        expect(page.locator('[data-testid="work-stage-banner"]')).to_contain_text("아직 자동으로 진행하지")
        probe.rule("화면이 업무 단계와 미지원 자동 진행을 보임", True)
    else:
        probe.observe("C 가 업무화되지 않음", "AI 가 명확한 업무 요청으로 읽지 않았다 — 제품 규칙 위반이 아니라 AI 판단")
        probe.rule("업무화되지 않았으면 준비 단계 그대로", view["stage"] == "discussion")
    probe.shot(page, "C-work")

    # ------------------------------------------------------------------ D 중단
    probe.send(page, long_prompt(SLEEP_D))
    wait_until(lambda: os_processes(f"Start-Sleep -Seconds {SLEEP_D}"), "codex 의 셸 대기", timeout=240, interval=2)
    expect(page.locator('[data-testid="progress-headline"]')).to_contain_text("AI 가 답을 쓰는 중", timeout=30_000)
    probe.shot(page, "D-running")
    page.click('[data-testid="stop-button"]')
    view = probe.wait_settled(case_id, 3, timeout=120)
    stopped = view["requests"][-1]
    probe.rule("화면의 중단 → 요청 interrupted(stopped_by_request)", (stopped["state"], stopped["outcome_reason"]) == ("interrupted", "stopped_by_request"), stopped["state"])
    probe.rule("OS 목록에 그 셸 대기가 없음", not os_processes(f"Start-Sleep -Seconds {SLEEP_D}"))
    expect(page.locator('[data-testid="request-outcome"]').last).to_contain_text("중단됨", timeout=20_000)
    probe.shot(page, "D-stopped")

    # ------------------------------------------------------------------ E 결과물·질문 카드
    def draft(goal: str, questions: list[dict[str, Any]]) -> None:
        response = http.post(f"/api/cases/{case_id}/intent-drafts", json={
            "summary": "사람이 쓴 의도 초안", "target_runner_id": RUNNER_ID,
            "fields": {"goal": {"text": goal, "state": "proposed", "origin": "user_requirement"}},
            "questions": questions, "criteria": [],
        })
        if response.status_code != 202:
            raise LiveError(f"의도 초안 접수 실패: {response.status_code} {response.text[:300]}")

    stage = probe.conv(case_id)["stage"]
    if stage == "work":
        draft("로그 한 줄에 수준과 출처를 더한다.",
              [{"key": "q-level", "text": "수준 이름은 INFO/ERROR 둘이면 충분한가요?", "summary": "수준 이름 범위", "decide_at": "intent"}])
        wait_until(lambda: http.get(f"/api/cases/{case_id}/intent-state").json()["open_intent_questions"], "의도 v1 질문", timeout=60)
        card = page.locator('[data-testid="question-card-q-level"]')
        expect(card).to_be_visible(timeout=20_000)
        card.locator("textarea").fill("INFO 와 ERROR 둘이면 됩니다")
        card.locator("button", has_text="답변 보내기").click()
        expect(page.locator('[data-testid="question-cards"]')).to_have_count(0, timeout=60_000)
        state = http.get(f"/api/cases/{case_id}/intent-state").json()
        probe.rule("카드 답변이 그 질문만 닫고 동의가 되지 않음", state["open_intent_questions"] == [] and state["agreement_state"] == "never_agreed", state["agreement_state"])
        page.click('[data-testid="open-results"]')
        page.click('[data-testid="result-intent"]')
        expect(page.locator('[data-testid="viewer-body"]')).to_contain_text("수준과 출처", timeout=60_000)
        draft("로그 한 줄에 수준·출처·요청 식별자를 더한다.", [])
        expect(page.locator('[data-testid="newer-version"]')).to_contain_text("v2", timeout=60_000)
        probe.rule("읽는 동안 새 버전이 생겨도 본문은 v1 그대로", "요청 식별자" not in page.locator('[data-testid="viewer-body"]').inner_text())
        page.click('[data-testid="show-diff"]')
        expect(page.locator('[data-testid="diff"]')).to_contain_text("요청 식별자", timeout=60_000)
        probe.shot(page, "E-diff")
        page.click('[data-testid="show-diff"]')
        page.click('[data-testid="switch-latest"]')
        expect(page.locator('[data-testid="viewer-title"]')).to_contain_text("의도 v2")
        probe.rule("전환은 사람이 고른 뒤에만", True)
        page.click('button[title="패널 닫기"]')
    else:
        probe.observe("E 생략", "C 가 업무화되지 않아 의도 버전을 만들 수 없다(준비 단계에는 의도가 없다)")

    # ------------------------------------------------------------------ F PC 단절
    before = len(probe.conv(case_id)["messages"])
    system.kill_runner_only()
    wait_until(lambda: any(r["connection"]["state"] == "disconnected" for r in http.get("/api/runners").json()), "PC 미연결", timeout=60)
    expect(page.locator('[data-testid="pc-disconnected"]')).to_be_visible(timeout=20_000)
    probe.rule("불러온 본문은 단절 뒤에도 보임", reply_a[:20] in page.locator('[data-testid="message-2"]').inner_text())
    page.fill('[data-testid="composer-input"]', "PC 가 꺼진 동안 쓴 말")
    expect(page.locator('[data-testid="draft-state"]')).to_contain_text("초안 저장됨")
    probe.rule("PC 미연결이면 전송 비활성·사유 표시",
               page.locator('[data-testid="send-button"]').is_disabled()
               and "PC 가 연결돼 있지 않다" in page.locator('[data-testid="send-refusal"]').inner_text())
    with system.db() as conn:
        reads_before = conn.execute("SELECT COUNT(*) FROM artifact_read_request").fetchone()[0]
    fresh = page.context.new_page()
    fresh.goto(f"{system.base}/?project={project['id']}&case={case_id}")
    expect(fresh.locator('[data-testid="message-body-state"]').first).to_contain_text("연결 필요", timeout=20_000)
    with system.db() as conn:
        reads_after = conn.execute("SELECT COUNT(*) FROM artifact_read_request").fetchone()[0]
    probe.rule("미연결 PC 로 새 열람 요청을 만들지 않음", reads_after == reads_before, (reads_before, reads_after))
    probe.shot(fresh, "F-disconnected")
    system.start_runner("restart")
    wait_until(lambda: any(r["connection"]["state"] == "connected" for r in http.get("/api/runners").json()), "재연결", timeout=60)
    expect(fresh.locator('[data-testid="message-2"] [data-testid="message-body"]')).not_to_be_empty(timeout=60_000)
    probe.rule("재연결 뒤 본문을 불러옴 · 초안 유지 · 자동 전송 없음",
               fresh.input_value('[data-testid="composer-input"]') == "PC 가 꺼진 동안 쓴 말"
               and len(probe.conv(case_id)["messages"]) == before)
    probe.shot(fresh, "F-reconnected")


def main() -> int:
    if not (DIST / "index.html").exists():
        print("web/dist 가 없다 — web 에서 npm run build 를 먼저 한다", file=sys.stderr)
        return 2
    tag = stamp()
    root = LIVE_ROOT / tag
    root.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    version = subprocess.run(["codex", "--version"], capture_output=True, text=True, shell=True).stdout.strip()
    with Log(OUT / "UI-03-live.log") as log:
        log(f"UI-03 라이브 {tag} · codex {version or '버전 확인 실패'} · 데이터 {root}")
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
        (OUT / "UI-03-live-results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"결과: {status} · 제품 규칙 {sum(r['ok'] for r in probe.product)}/{len(probe.product)} · 관찰 {len(probe.observations)}")
    return 0 if status == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
