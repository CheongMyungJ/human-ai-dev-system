"""UI-03 AC-11~18 — 기본 대화 화면을 **실제 브라우저로** 쓴다.

실제 제어부(uvicorn, 빌드된 `web/dist` 를 그대로 서빙)·실제 Runner 프로세스·PATH 앞의 시험용
`codex`(`tests/fake_cli/fake_codex.py`, AI 를 부르지 않는다)·설치된 Edge(Playwright `msedge` 채널,
브라우저를 내려받지 않는다). 화면이 서버 판정을 그대로 보이는지, 초안이 이 브라우저에만 남고
접수가 확인된 것만 비워지는지, 결과물 열람 버전이 고정되는지를 **사람이 누르는 대로** 본다.

실제 codex·실제 사용 확인은 `ui/live/ui03_shell.py` 다(UI-PLAN-03 AC-19).

`web/dist` 가 없거나 소스보다 오래됐으면 건너뛴다 — `scripts\\run-tests.ps1` 은 먼저 빌드한다.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

import httpx
import pytest

from runner import process_tree
from tests.conftest import DEFAULT_CRITERIA, DEFAULT_SIZING
from tests.test_intent import _draft_fields
from tests.test_restart_recovery import PYTHON, REPO_ROOT, _free_port
from tests.test_runner_process_control import FAKE_CLI, RunnerProcess

DIST = REPO_ROOT / "web" / "dist"
WEB_SRC = REPO_ROOT / "web" / "src"
STALE_SECONDS = 3

pytestmark = [
    pytest.mark.skipif(not process_tree.IS_WINDOWS, reason="실제 Runner 트리 제어는 Windows 에서만"),
    pytest.mark.skipif(not PYTHON.exists(), reason="저장소 로컬 .venv 가 없다"),
]

try:  # 브라우저 시험 의존성(requirements.txt). 없으면 건너뛴다.
    from playwright.sync_api import Page, expect, sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None  # type: ignore[assignment]

REQUEST_IN_PROGRESS = "현재 요청을 처리하고 있다"
RUNNER_DISCONNECTED = "PC 가 연결돼 있지 않다"


def _dist_problem() -> str | None:
    index = DIST / "index.html"
    if not index.exists():
        return "web/dist 가 없다 — npm run build"
    built = index.stat().st_mtime
    newest = max(p.stat().st_mtime for p in WEB_SRC.rglob("*") if p.is_file())
    if newest > built:
        return "web/dist 가 web/src 보다 오래됐다 — npm run build"
    return None


class WebController:
    """빌드된 화면을 서빙하는 실제 uvicorn. **요청 처리기는 켠다**(제품 기본값)."""

    def __init__(self, data_root: Path, port: int) -> None:
        self.data_root = data_root
        self.port = port
        self.base_url = f"http://127.0.0.1:{port}"
        self.proc: subprocess.Popen | None = None

    def start(self) -> None:
        env = dict(os.environ)
        env.update(
            {
                "HADS_CONTROLLER_DATA": str(self.data_root),
                "HADS_WEB_DIST": str(DIST),
                "HADS_AUTO_PROCESS_REQUESTS": "1",
                "HADS_RUNNER_STALE_SECONDS": str(STALE_SECONDS),
                "PYTHONPATH": str(REPO_ROOT),
            }
        )
        self.proc = subprocess.Popen(
            [str(PYTHON), "-m", "uvicorn", "controller.app:app", "--host", "127.0.0.1",
             "--port", str(self.port), "--log-level", "warning"],
            cwd=str(REPO_ROOT),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _wait(lambda: httpx.get(f"{self.base_url}/api/health").status_code == 200, 30, "제어부 기동")

    def stop(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.proc.pid)], capture_output=True)
            self.proc.wait(timeout=30)


def _wait(predicate: Callable[[], Any], timeout: float, what: str) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = predicate()
        except httpx.HTTPError:
            value = None
        if value:
            return value
        time.sleep(0.2)
    raise AssertionError(f"기다렸지만 오지 않았다: {what}")


class Stack:
    def __init__(self, root: Path, controller: WebController, runner: RunnerProcess, browser) -> None:
        self.root = root
        self.controller = controller
        self.runner = runner
        self.browser = browser
        self.base = controller.base_url
        self.http = httpx.Client(base_url=self.base, timeout=30)
        self.counter = 0

    def repo_dir(self) -> Path:
        self.counter += 1
        path = self.root / f"repo-{self.counter}"
        path.mkdir()
        return path

    def project(self, name: str) -> dict[str, Any]:
        response = self.http.post(
            "/api/projects",
            json={"name": name, "repo_path": str(self.repo_dir()), "default_tool_id": "codex"},
        )
        assert response.status_code == 201, response.text
        return response.json()

    def page(self, context=None) -> Page:
        context = context or self.browser.new_context(viewport={"width": 1360, "height": 860})
        page = context.new_page()
        page.set_default_timeout(30_000)
        return page

    def db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.controller.data_root / "controller.sqlite3")
        conn.row_factory = sqlite3.Row
        return conn

    def wait_connected(self, connected: bool = True) -> None:
        want = "connected" if connected else "disconnected"
        _wait(
            lambda: any(r["connection"]["state"] == want for r in self.http.get("/api/runners").json()),
            40,
            f"PC {want}",
        )


@pytest.fixture(scope="module")
def stack(tmp_path_factory):
    if sync_playwright is None:
        pytest.skip("playwright 가 설치되지 않았다(requirements.txt)")
    problem = _dist_problem()
    if problem:
        pytest.skip(problem)
    root = tmp_path_factory.mktemp("web-shell")
    controller = WebController(root / "controller", _free_port())
    controller.start()
    bin_dir = root / "bin"
    bin_dir.mkdir()
    (bin_dir / "codex.cmd").write_text(f'@"{sys.executable}" "{FAKE_CLI}" %*\r\n', encoding="utf-8")
    runner = RunnerProcess(controller.base_url, root / "runner", bin_dir, root / "pids", root / "runner.log")
    # UI-04c(D-89). 시험 Runner 는 이 PC 에서 폴더·편집기를 열지 않는다 — 실제 창을 띄우지 않기 위해서다. 화면은 그
    # 사실("이 PC 는 지원하지 않음 — HADS_RUNNER_DESKTOP=off")을 보인다. 실제로 여는 경로는 tests/test_workspace_open.py 가
    # 기록만 하는 opener 로 본다.
    runner.env["HADS_RUNNER_DESKTOP"] = "off"
    playwright = None
    browser = None
    try:
        runner.start()
        playwright = sync_playwright().start()
        try:
            browser = playwright.chromium.launch(channel="msedge", headless=True)
        except Exception as exc:  # noqa: BLE001 — 설치된 Edge 가 없는 환경
            pytest.skip(f"설치된 Edge 를 열 수 없다: {exc}")
        expect.set_options(timeout=15_000)
        stack = Stack(root, controller, runner, browser)
        stack.wait_connected()
        yield stack
    finally:
        if browser is not None:
            browser.close()
        if playwright is not None:
            playwright.stop()
        runner.kill_tree()
        controller.stop()


def _open(stack: Stack, page: Page, project_id: str, case_id: str | None = None) -> None:
    query = f"?project={project_id}" + (f"&case={case_id}" if case_id else "")
    page.goto(f"{stack.base}/{query}")
    page.wait_for_selector('[data-testid="sidebar"]')


def _case_in_url(page: Page) -> str | None:
    # `page.url` 은 동기 API 가 이벤트를 처리할 때만 갱신된다 — 주소는 페이지에 직접 묻는다.
    href = page.evaluate("location.href")
    return href.split("case=")[1].split("&")[0] if "case=" in href else None


def _new_conversation(page: Page) -> str:
    before = _case_in_url(page)
    page.click('[data-testid="new-conversation"]')
    case_id = _wait(lambda: (_case_in_url(page) or before) != before and _case_in_url(page), 15, "새 대화")
    # 새 대화의 입력창이 떴다(대화마다 다시 만들어진다).
    page.wait_for_selector('[data-testid="stage-label"]')
    expect(page.locator('[data-testid="composer-input"]')).to_have_value("")
    return case_id


def _send(page: Page, text: str) -> None:
    page.fill('[data-testid="composer-input"]', text)
    expect(page.locator('[data-testid="send-button"]')).to_be_enabled()
    page.click('[data-testid="send-button"]')


def _messages(stack: Stack, case_id: str) -> list[dict[str, Any]]:
    return stack.http.get(f"/api/cases/{case_id}/conversation").json()["messages"]


# ================================================== AC-11 화면 구성


def test_the_conversation_shell_is_the_default_screen(stack):
    """AC-11 — 새 기본 화면, 관리 화면 유지, 라이트 기본·테마 기억, 패널 접기, 프로젝트 복원."""
    first = stack.project("첫 프로젝트")
    page = stack.page()
    _open(stack, page, first["id"])
    assert page.evaluate("document.documentElement.dataset.theme") == "light"
    assert page.evaluate("document.body.dataset.view") == "shell"
    case_a = _new_conversation(page)
    expect(page.locator('[data-testid="conversation-list"]')).to_contain_text("새 대화")
    expect(page.locator('[data-testid="stage-label"]')).to_contain_text("논의 중")
    # 오른쪽 패널은 누를 때만 열린다 — 결과물이 없으면 그렇게 말한다.
    assert page.locator('[data-testid="review-panel"]').count() == 0
    page.click('[data-testid="open-results"]')
    expect(page.locator('[data-testid="result-list"]')).to_contain_text("아직 결과물이 없다")
    page.click('[data-testid="open-results"]')
    assert page.locator('[data-testid="review-panel"]').count() == 0

    page.select_option('[data-testid="theme-select"]', "dark")
    assert page.evaluate("document.documentElement.dataset.theme") == "dark"
    page.click('button[title="목록 접기"]')
    assert page.locator('[data-testid="sidebar"]').count() == 0
    page.reload()
    page.wait_for_selector('[data-testid="composer-input"]')
    assert page.evaluate("document.documentElement.dataset.theme") == "dark"  # 기억한다
    assert page.locator('[data-testid="sidebar"]').count() == 0
    page.click('button[title="목록 펼치기"]')
    page.select_option('[data-testid="theme-select"]', "light")

    # 프로젝트를 바꿨다 돌아오면 **그 프로젝트의 마지막 대화**가 열린다(D-68).
    second = stack.project("둘째 프로젝트")
    page.reload()
    page.wait_for_selector('[data-testid="project-select"]')
    page.select_option('[data-testid="project-select"]', second["id"])
    expect(page.locator('[data-testid="new-conversation"]')).to_be_enabled()
    assert page.locator('[data-testid="conversation-title"]').count() == 0
    page.select_option('[data-testid="project-select"]', first["id"])
    page.wait_for_selector('[data-testid="conversation-title"]')
    assert _case_in_url(page) == case_a

    # 관리 화면은 그대로 있다.
    page.goto(f"{stack.base}/?view=admin")
    expect(page.locator("h1")).to_contain_text("사람–AI 개발 협업 시스템")
    assert page.evaluate("document.body.dataset.view") == "admin"
    page.context.close()


# ================================================== AC-12·15 논의·잠금·업무화·중단


def test_a_conversation_gets_answered_locks_while_processing_and_starts_work(stack):
    """AC-12·AC-15 (+AC-1·2·6 화면 경로) — 서버 판정 그대로의 잠금, 응답, AI 해석 업무화, 중단."""
    project = stack.project("논의")
    page = stack.page()
    _open(stack, page, project["id"])
    case_id = _new_conversation(page)

    _send(page, "HADS_FAKE_SLEEP=5 천천히 답해 주세요")
    expect(page.locator('[data-testid="progress-headline"]')).to_contain_text("AI 가 답을 쓰는 중", timeout=20_000)
    # 처리 중: 일반 전송은 막히고 초안 편집은 된다. 사유는 서버가 준 것이다.
    expect(page.locator('[data-testid="send-refusal"]')).to_contain_text(REQUEST_IN_PROGRESS)
    page.fill('[data-testid="composer-input"]', "다음에 할 말")
    expect(page.locator('[data-testid="send-button"]')).to_be_disabled()
    direct = stack.http.post(
        f"/api/cases/{case_id}/messages",
        json={"client_message_id": "direct-1", "content": "우회", "summary": "직접",
              "target_runner_id": RunnerProcessId.get(stack)},
    )
    assert direct.status_code == 409
    assert direct.json()["detail"]["refusals"] == ["request_in_progress"]

    expect(page.locator('[data-testid="message-2"] [data-testid="message-body"]')).to_contain_text(
        "가짜 응답입니다", timeout=40_000
    )
    assert "hads-interpretation" not in page.content()  # 기계용 블록은 대화에 붙지 않는다
    expect(page.locator('[data-testid="send-button"]')).to_be_enabled()
    # 막혀 있던 동안 쓴 초안은 **자동으로 보내지지 않았다.**
    assert page.input_value('[data-testid="composer-input"]') == "다음에 할 말"
    assert len(_messages(stack, case_id)) == 2

    _send(page, "HADS_FAKE_WORK=research 서버 로그를 분석해서 개선안을 정리해줘")
    expect(page.locator('[data-testid="work-start-card"]')).to_contain_text("조사·연구", timeout=40_000)
    expect(page.locator('[data-testid="stage-label"]')).to_contain_text("업무 · 조사·연구")
    # P4-05. 업무화 뒤 진행기가 첫 걸음(의도 초안)을 같은 요청에 만든다 — 배너가 진행 상태를 보인다.
    banner = page.locator('[data-testid="work-stage-banner"]')
    expect(banner).to_have_attribute("data-progress", "running", timeout=20_000)
    assert "view=admin" in banner.locator("a").last.get_attribute("href")
    # 가짜 codex 의 초안에는 의도 질문 하나가 있다 → 질문 카드에서 멈추고 전송이 열린다.
    expect(page.locator('[data-testid="question-cards"]')).to_have_count(1, timeout=60_000)
    expect(banner).to_have_attribute("data-progress", "waiting_human", timeout=20_000)
    expect(page.locator('[data-testid="send-refusal"]')).to_have_count(0)  # 전송이 열렸다(입력은 비어 있다)

    # 중단은 요청이다 — 실제 종료를 서버가 확인하면 전송이 열린다.
    _send(page, "HADS_FAKE_SLEEP=40 오래 걸리는 질문")
    expect(page.locator('[data-testid="progress-headline"]')).to_contain_text("AI 가 답을 쓰는 중", timeout=20_000)
    page.click('[data-testid="stop-button"]')
    expect(page.locator('[data-testid="request-outcome"]').last).to_contain_text("중단됨", timeout=30_000)
    assert page.locator('[data-testid="request-progress"]').count() == 0
    page.fill('[data-testid="composer-input"]', "이어서")
    expect(page.locator('[data-testid="send-button"]')).to_be_enabled()
    page.context.close()


class RunnerProcessId:
    """시험 Runner 의 식별자(RunnerProcess 가 정한다)."""

    @staticmethod
    def get(stack: Stack) -> str:
        return stack.runner.env["HADS_RUNNER_ID"]


# ================================================== AC-13·14 초안·본문 저장 위치


def test_drafts_live_in_this_browser_and_only_stored_sends_are_cleared(stack):
    """AC-14·AC-13 — 초안은 대화별로 복구되고, 접수 확인된 전송만 비워지며, 본문은 저장소에 없다."""
    project = stack.project("초안")
    page = stack.page()
    _open(stack, page, project["id"])
    first = _new_conversation(page)
    page.fill('[data-testid="composer-input"]', "첫 대화의 초안")
    expect(page.locator('[data-testid="draft-state"]')).to_contain_text("초안 저장됨")
    page.reload()
    page.wait_for_selector('[data-testid="composer-input"]')
    assert page.input_value('[data-testid="composer-input"]') == "첫 대화의 초안"
    expect(page.locator('[data-testid="send-notice"]')).to_contain_text("자동으로 보내지 않는다")
    assert _messages(stack, first) == []

    second = _new_conversation(page)
    page.fill('[data-testid="composer-input"]', "둘째 대화의 초안")
    expect(page.locator('[data-testid="draft-state"]')).to_contain_text("초안 저장됨")
    page.click(f'[data-testid="conversation-row-{first}"]')
    expect(page.locator('[data-testid="composer-input"]')).to_have_value("첫 대화의 초안")
    page.click(f'[data-testid="conversation-row-{second}"]')
    expect(page.locator('[data-testid="composer-input"]')).to_have_value("둘째 대화의 초안")

    # 보내고 접수가 확인되면 비운다.
    page.click('[data-testid="send-button"]')
    expect(page.locator('[data-testid="send-notice"]')).to_contain_text("메시지 접수됨", timeout=30_000)
    expect(page.locator('[data-testid="composer-input"]')).to_have_value("")
    expect(page.locator('[data-testid="message-2"] [data-testid="message-body"]')).to_contain_text(
        "가짜 응답입니다", timeout=40_000
    )
    storage = page.evaluate("JSON.stringify(Object.assign({}, window.localStorage))")
    assert "가짜 응답입니다" not in storage  # 불러온 본문은 브라우저 저장소에 없다
    assert "둘째 대화의 초안" not in storage  # 접수된 전송분은 지워졌다
    assert "첫 대화의 초안" in storage

    # 응답을 못 받은 전송의 보냄 기록 — 새로 고치면 **대조만** 한다. 받지 않았으면 초안이 남는다.
    key = f"hads.draft.v1.{first}"
    record = json.loads(page.evaluate(f"window.localStorage.getItem('{key}')"))
    record["pending"] = {"clientId": "web-never-sent-1", "content": record["content"], "sentAt": "t"}
    page.evaluate(f"window.localStorage.setItem('{key}', {json.dumps(json.dumps(record))})")
    _open(stack, page, project["id"], first)  # 새로 연다 — 기록이 남은 채로 입력창이 뜬다
    page.wait_for_selector('[data-testid="composer-input"]')
    expect(page.locator('[data-testid="send-notice"]')).to_contain_text("서버가 받지 않았다")
    assert page.input_value('[data-testid="composer-input"]') == "첫 대화의 초안"
    assert _messages(stack, first) == []  # 자동 전송 없음

    # 다른 브라우저(새 저장소)에는 없다 — 기기 간 자동 동기화를 하지 않는다.
    other = stack.page()
    _open(stack, other, project["id"], first)
    other.wait_for_selector('[data-testid="composer-input"]')
    assert other.input_value('[data-testid="composer-input"]') == ""
    other.context.close()
    page.context.close()


# ================================================== AC-16·17 질문 카드·결과물 버전


def _intent_draft(stack: Stack, case_id: str, goal: str, questions: list[dict[str, Any]]) -> None:
    fields = _draft_fields(
        goal={"text": goal, "state": "proposed", "origin": "user_requirement"}
    )
    response = stack.http.post(
        f"/api/cases/{case_id}/intent-drafts",
        json={
            "summary": "의도 초안",
            "target_runner_id": RunnerProcessId.get(stack),
            "fields": fields,
            "questions": questions,
            "criteria": DEFAULT_CRITERIA,
            "sizing": DEFAULT_SIZING,
        },
    )
    assert response.status_code == 202, response.text


def test_question_cards_and_results_keep_the_version_being_read(stack):
    """AC-16·AC-17 — 질문 카드 답변, 결과물 열람 버전 고정·새 버전 안내·비교·전환, 참조의 버전."""
    project = stack.project("결과물")
    created = stack.http.post(
        f"/api/projects/{project['id']}/cases", json={"title": "CSV 내보내기", "kind": "feature"}
    ).json()
    case_id = created["id"]
    _intent_draft(
        stack,
        case_id,
        "관리 화면의 데이터를 CSV로 얻을 수 있게 한다.",
        [{"key": "q-cols", "text": "숨긴 열도 넣을까요?", "summary": "숨긴 열 포함 여부", "decide_at": "intent"}],
    )
    _wait(
        lambda: stack.http.get(f"/api/cases/{case_id}/intent-state").json()["open_intent_questions"],
        30,
        "의도 v1 의 질문",
    )
    page = stack.page()
    _open(stack, page, project["id"], case_id)
    card = page.locator('[data-testid="question-card-q-cols"]')
    expect(card).to_contain_text("숨긴 열 포함 여부")
    expect(card).to_contain_text("동의·권한이 아니다")
    card.locator("textarea").fill("숨긴 열은 빼 주세요")
    card.locator("button", has_text="답변 보내기").click()
    expect(page.locator('[data-testid="question-cards"]')).to_have_count(0, timeout=30_000)
    state = stack.http.get(f"/api/cases/{case_id}/intent-state").json()
    assert state["open_intent_questions"] == []
    assert state["agreement_state"] == "never_agreed"  # 답변은 동의가 아니다

    # 의도 원문 전달은 "사람이 원문을 확인했다" 기록을 남긴다 — 화면이 스스로 부르지 않는다(AC-13).
    with stack.db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM intent_view").fetchone()[0] == 0
    page.click('[data-testid="open-results"]')
    page.click('[data-testid="result-intent"]')
    expect(page.locator('[data-testid="viewer-title"]')).to_contain_text("의도 v1")
    expect(page.locator('[data-testid="viewer-body"]')).to_contain_text("CSV로 얻을 수 있게", timeout=30_000)
    with stack.db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM intent_view").fetchone()[0] == 1  # 사람이 열었다

    # 읽는 동안 v2 가 생긴다 — 본문은 v1 그대로이고 안내만 나온다.
    _intent_draft(stack, case_id, "관리 화면과 보고서 데이터를 CSV로 얻을 수 있게 한다.", [])
    expect(page.locator('[data-testid="newer-version"]')).to_contain_text("v2", timeout=30_000)
    expect(page.locator('[data-testid="viewer-title"]')).to_contain_text("의도 v1")
    expect(page.locator('[data-testid="viewer-body"]')).to_contain_text("관리 화면의 데이터를")
    page.click('[data-testid="show-diff"]')
    expect(page.locator('[data-testid="diff"]')).to_contain_text("보고서", timeout=30_000)
    page.click('[data-testid="show-diff"]')

    # v1 을 대화에 참조해 보낸다. 메시지의 참조는 v1 이고 최신이 아님을 보인다.
    page.fill('.sh-attach input', "목표 항목")
    page.click('[data-testid="attach-ref"]')
    expect(page.locator('[data-testid="draft-refs"]')).to_contain_text("의도 v1")
    _send(page, "v1 의 목표가 좁았어요")
    expect(page.locator('[data-testid="send-notice"]')).to_contain_text("메시지 접수됨", timeout=30_000)
    user_message = page.locator('article[data-author="user"]').last
    expect(user_message).to_contain_text("의도 v1")
    expect(user_message).to_contain_text("최신 아님")
    [sent] = [m for m in _messages(stack, case_id) if m["references"]]
    assert sent["references"][0]["artifact_rev"] == 1

    page.click('[data-testid="switch-latest"]')
    expect(page.locator('[data-testid="viewer-title"]')).to_contain_text("의도 v2")
    assert page.locator('[data-testid="newer-version"]').count() == 0
    # 과거 메시지의 참조는 **그 버전**을 연다.
    user_message.locator("button", has_text="의도 v1").click()
    expect(page.locator('[data-testid="viewer-title"]')).to_contain_text("의도 v1")
    page.context.close()


# ================================================== AC-12·13 PC 단절 (마지막: Runner 를 내렸다 올린다)


def test_a_disconnected_pc_keeps_what_was_loaded_and_sends_nothing(stack):
    """AC-12·AC-13 (D-75) — 불러온 본문·초안은 남고, 새 열람·전송은 막히며, 재연결 뒤 자동 전송이 없다."""
    project = stack.project("단절")
    page = stack.page()
    _open(stack, page, project["id"])
    case_id = _new_conversation(page)
    _send(page, "안녕하세요")
    expect(page.locator('[data-testid="message-2"] [data-testid="message-body"]')).to_contain_text(
        "가짜 응답입니다", timeout=40_000
    )

    stack.runner.kill_tree()
    stack.wait_connected(False)
    expect(page.locator('[data-testid="pc-disconnected"]')).to_be_visible(timeout=20_000)
    expect(page.locator('[data-testid="message-2"] [data-testid="message-body"]')).to_contain_text("가짜 응답입니다")
    page.fill('[data-testid="composer-input"]', "끊긴 동안 쓴 말")
    expect(page.locator('[data-testid="draft-state"]')).to_contain_text("초안 저장됨")
    expect(page.locator('[data-testid="send-refusal"]')).to_contain_text(RUNNER_DISCONNECTED)
    expect(page.locator('[data-testid="send-button"]')).to_be_disabled()

    with stack.db() as conn:
        reads_before = conn.execute("SELECT COUNT(*) FROM artifact_read_request").fetchone()[0]
    fresh = stack.page(page.context)  # 같은 브라우저 저장소, 빈 메모리
    _open(stack, fresh, project["id"], case_id)
    states = fresh.locator('[data-testid="message-body-state"]')
    expect(states.first).to_contain_text("연결 필요", timeout=20_000)
    with stack.db() as conn:
        reads_after = conn.execute("SELECT COUNT(*) FROM artifact_read_request").fetchone()[0]
    assert reads_after == reads_before  # 미연결 PC 로 열람 요청을 쌓지 않는다
    assert fresh.input_value('[data-testid="composer-input"]') == "끊긴 동안 쓴 말"

    stack.runner.start()
    stack.wait_connected(True)
    expect(fresh.locator('[data-testid="message-2"] [data-testid="message-body"]')).to_contain_text(
        "가짜 응답입니다", timeout=40_000
    )
    expect(fresh.locator('[data-testid="send-button"]')).to_be_enabled(timeout=20_000)
    assert fresh.input_value('[data-testid="composer-input"]') == "끊긴 동안 쓴 말"
    assert len(_messages(stack, case_id)) == 2  # 재연결 뒤 자동 전송 없음
    page.context.close()


# ================================================== P4-05 AC-19 업무 단계 자동 진행·확인 카드·종료 후


def _progress_state(stack: Stack, case_id: str) -> str | None:
    progress = stack.http.get(f"/api/cases/{case_id}/conversation").json()["progress"]
    return progress["state"] if progress else None


def test_the_work_stage_runs_by_itself_and_stops_only_at_the_cards(stack):
    """P4-05 AC-19 — 업무화 뒤 제품이 잇는다. 사람은 질문 카드·동의 카드에서만 부르고, 완료 뒤
    설명은 같은 대화에서, 수정 요청은 연결된 새 대화로 옮겨진다.
    """
    project = stack.project("자동 진행")
    # 실제 git 저장소 — 작업공간(worktree)·실행 전후 대조가 진짜 파일을 본다.
    repo = Path(project["repo_path"])
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@example.invalid"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True, capture_output=True)
    (repo / "reader.py").write_text("def read(path):\n    return open(path).read()\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True, capture_output=True)

    page = stack.page()
    _open(stack, page, project["id"])
    case_id = _new_conversation(page)
    _send(page, "HADS_FAKE_WORK=feature 오류 줄만 남기는 필터를 구현해줘")
    banner = page.locator('[data-testid="work-stage-banner"]')
    # 업무화 → 의도 초안(같은 요청, 전송 잠금) → 질문 카드에서 멈춤(전송 열림).
    expect(page.locator('[data-testid="work-start-card"]')).to_be_visible(timeout=40_000)
    expect(page.locator('[data-testid="question-card-q1"]')).to_be_visible(timeout=60_000)
    expect(banner).to_have_attribute("data-progress", "waiting_human")
    expect(page.locator('[data-testid="send-refusal"]')).to_have_count(0)  # 전송이 열렸다
    conv = stack.http.get(f"/api/cases/{case_id}/conversation").json()
    assert conv["current_request"] is None
    assert [r["state"] for r in conv["requests"]] == ["completed"]
    assert conv["requests"][0]["note_summary"] == "waiting: intent_questions"

    # 카드 답변 → 진행 요청(여는 메시지 없음)이 열리고 답을 반영한 재작성 → 동의 카드.
    card = page.locator('[data-testid="question-card-q1"]')
    card.locator("textarea").fill("구분하지 않습니다")
    card.locator("button", has_text="답변 보내기").click()
    expect(page.locator('[data-testid="agreement-card"]')).to_be_visible(timeout=60_000)
    conv = stack.http.get(f"/api/cases/{case_id}/conversation").json()
    origins = [r["origin"] for r in conv["requests"]]
    assert origins[:2] == ["user_message", "human_decision"]
    assert conv["requests"][1]["opened_by_message_id"] is None
    assert conv["progress"]["wait"][0]["code"] == "intent_agreement"
    # 원문을 열기 전에는 동의할 수 없다(서버도 열람 기록을 검사한다).
    expect(page.locator('[data-testid="agreement-agree"]')).to_be_disabled()
    page.click('[data-testid="agreement-open"]')
    expect(page.locator('[data-testid="viewer-body"]')).to_contain_text("오류 줄만", timeout=30_000)
    expect(page.locator('[data-testid="agreement-agree"]')).to_be_enabled(timeout=10_000)
    page.click('[data-testid="agreement-agree"]')

    # 동의 뒤 사람 없이 끝까지: 결합 기록 → 작업공간 → 구현 → 검증 → 기준 판정 → 자동 완료.
    expect(banner).to_have_attribute("data-progress", "done", timeout=120_000)
    expect(page.locator('[data-testid="stage-label"]')).to_contain_text("종료(closed)")
    case = stack.http.get(f"/api/cases/{case_id}").json()
    assert case["result"]["closure"]["closure_kind"] == "completed"
    assert all(c["verdict"] == "met" for c in case["result"]["criteria"])
    assert all(c["recorded_by"] == "policy:work_progressor" for c in case["result"]["criteria"])
    purposes = [r["purpose"] for r in reversed(case["runs"])]
    assert purposes == [
        "discussion_reply", "intent_authoring", "intent_authoring", "plan_authoring",
        "feature_implementation", "verification_run",
    ]
    assert all(r["request_id"] for r in case["runs"])
    human = [d for d in case["decisions"] if not d["actor"].startswith("policy:")]
    assert [d["kind"] for d in human] == ["intent_agreement"]
    # 진행 이력이 결정 사항 패널에 있다.
    page.click('[data-testid="open-decisions"]')
    expect(page.locator('[data-testid="progress-events"]')).to_contain_text("기준 판정 기록")
    page.click('[data-testid="open-decisions"]')

    # 종료 뒤: 입력창은 설명 전용으로 열린다. 설명 질문은 같은 대화에서 답을 받는다.
    expect(page.locator('[data-testid="send-note"]')).to_contain_text("설명만")
    _send(page, "C-01 은 어떻게 확인한 거야?")
    expect(page.locator('article[data-author="assistant"]').last).to_contain_text("가짜 응답입니다", timeout=60_000)
    assert stack.http.get(f"/api/cases/{case_id}").json()["status"] == "closed"
    # 설명 실행의 소비는 같은 Case 에 누적되고 종료 뒤 소비로 나뉜다(정산은 결과 보고와 함께 온다).
    _wait(
        lambda: stack.http.get(f"/api/cases/{case_id}/budget").json()["since_closure"]["run_count"] == 1,
        30,
        "종료 뒤 소비 1건",
    )
    assert stack.http.get(f"/api/cases/{case_id}/conversation").json()["relations"] == []  # 설명은 새 대화를 만들지 않는다

    # 수정 요청 → AI 해석 → 연결된 새 대화로 옮겨진다. 이 대화는 그대로 종료다.
    _send(page, "HADS_FAKE_WORK=feature 선택한 열만 내보내는 기능도 추가해줘")
    expect(page.locator('[data-testid="follow-up-card"]')).to_be_visible(timeout=60_000)
    conv = stack.http.get(f"/api/cases/{case_id}/conversation").json()
    [relation] = conv["relations"]
    assert relation["direction"] == "successor"
    page.click('[data-testid="follow-up-link"]')
    page.wait_for_selector('[data-testid="predecessor-line"]')
    assert _case_in_url(page) == relation["case_id"]
    new_conv = stack.http.get(f"/api/cases/{relation['case_id']}/conversation").json()
    assert new_conv["messages"][0]["receipt"] == "stored"
    # 새 대화는 처음부터 잇는다 — 응답·해석·업무화가 다시 일어난다.
    expect(page.locator('[data-testid="work-start-card"]')).to_be_visible(timeout=60_000)
    assert stack.http.get(f"/api/cases/{relation['case_id']}/policy").json()["delegation_basis"]["current"] is not None
    page.context.close()


def test_a_limit_card_raises_the_limit_and_goes_once_more(stack):
    """P4-05b AC-10 — 재시도 상한에 걸린 카드가 "재시도 1/1" 을 보이고, "한도를 올리고 계속" 을 누르면
    한 번 더 가서 새 한도에서 다시 멈춘다(재시도 2/2). 누른 것은 이력으로 남는다.
    """
    project = stack.project("상한")
    repo = Path(project["repo_path"])
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@example.invalid"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True, capture_output=True)
    (repo / "reader.py").write_text("def read(path):\n    return open(path).read()\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True, capture_output=True)

    page = stack.page()
    _open(stack, page, project["id"])
    case_id = _new_conversation(page)
    _send(page, "HADS_FAKE_WORK=feature HADS_FAKE_NO_QUESTION HADS_FAKE_IMPL_NOCHANGE 필터를 구현해줘")
    expect(page.locator('[data-testid="agreement-card"]')).to_be_visible(timeout=60_000)
    page.click('[data-testid="agreement-open"]')
    expect(page.locator('[data-testid="agreement-agree"]')).to_be_enabled(timeout=30_000)
    page.click('[data-testid="agreement-agree"]')

    card = page.locator('[data-testid="wait-card-task_failed"]')
    expect(card).to_be_visible(timeout=120_000)
    expect(card).to_have_attribute("data-limit-key", "task_retry_limit")
    expect(card.locator('[data-testid="limit-usage"]')).to_contain_text("재시도 1/1")
    expect(card.locator('[data-testid="limit-usage"]')).to_contain_text("시스템 기본값")
    # 상한 대기에서는 아무 것도 하지 않던 "다시 시도" 가 없다.
    expect(card.locator('[data-testid="wait-retry"]')).to_have_count(0)

    def impl_runs() -> int:
        runs = stack.http.get(f"/api/cases/{case_id}").json()["runs"]
        return len([r for r in runs if r["purpose"] == "feature_implementation"])

    assert impl_runs() == 2
    card.locator('[data-testid="limit-raise"]').click()
    # 한 번 더 가서(구현 3회) 새 한도에서 다시 멈춘다.
    expect(page.locator('[data-testid="wait-card-task_failed"] [data-testid="limit-usage"]')).to_contain_text(
        "재시도 2/2", timeout=120_000
    )
    expect(page.locator('[data-testid="wait-card-task_failed"] [data-testid="limit-usage"]')).to_contain_text(
        "이 업무에서 정함"
    )
    assert impl_runs() == 3
    limits = stack.http.get(f"/api/cases/{case_id}/progress").json()["limits"]
    assert [(r["limit_key"], r["limit_value"], r["reason_summary"]) for r in limits["history"]] == [
        ("task_retry_limit", 2, "대기 카드에서 한도를 올림")
    ]
    page.context.close()


def test_a_rule_said_in_the_conversation_gets_a_card_and_can_be_invalidated(stack):
    """P4-06 AC-10·17 — 대화에서 프로젝트 규칙을 말하면 응답 아래에 "프로젝트 규칙으로 등록됨" 카드가
    뜨고(글에는 블록이 없다), 카드에서 무효로 할 수 있다. 관리 화면의 지식 패널에서 사람이 등록한다.
    """
    project = stack.project("지식")
    page = stack.page()
    _open(stack, page, project["id"])
    case_id = _new_conversation(page)
    _send(page, "HADS_FAKE_RULE 이 프로젝트에서는 앞으로 로그에 비밀값을 남기지 마")
    card = page.locator('[data-testid="knowledge-card"]')
    expect(card).to_be_visible(timeout=60_000)
    expect(card).to_contain_text("K-001 v1")
    expect(card).to_contain_text("필수")
    expect(card).to_have_attribute("data-state", "active")
    expect(page.locator('article[data-author="assistant"]').last).not_to_contain_text("hads-knowledge")
    # P4-06b — 카드가 "서버에 저장됨" 을 알린다. 옮긴 글과 권위 메시지가 서버에 있다.
    expect(card.locator('[data-testid="knowledge-card-storage"]')).to_contain_text("서버에 저장")
    view = stack.http.get(f"/api/projects/{project['id']}/knowledge").json()
    current = view["items"][0]["current"]
    assert (current["authority_kind"], current["state"]) == ("user_statement", "active")
    assert (current["storage"], current["source_storage"]) == ("server", "server")
    with stack.db() as conn:
        purposes = sorted(r["purpose"] for r in conn.execute("SELECT purpose FROM knowledge_body"))
    assert purposes == ["authority_message", "knowledge"]

    card.locator('[data-testid="knowledge-invalidate"]').click()
    card.locator('[data-testid="knowledge-invalidate-reason"]').fill("옮긴 내용이 내 말과 다르다")
    card.locator('[data-testid="knowledge-invalidate-confirm"]').click()
    expect(card).to_have_attribute("data-state", "invalid", timeout=15_000)
    view = stack.http.get(f"/api/projects/{project['id']}/knowledge").json()
    assert view["items"][0]["current"]["invalid_reason"] == "옮긴 내용이 내 말과 다르다"

    # 관리 화면 — 사람이 이 대화에서 등록한다(재승인 없이 활성).
    page.goto(f"{stack.base}/?view=admin&project={project['id']}&case={case_id}")
    panel = page.locator('[data-testid="knowledge-panel"]')
    expect(panel).to_be_visible(timeout=30_000)
    expect(panel.locator('[data-testid="knowledge-K-001"]')).to_contain_text("무효")
    # P4-06b — 등록 안내: 서버 저장 · 비밀값 금지.
    expect(panel.locator('[data-testid="knowledge-storage-note"]')).to_contain_text("서버에 저장")
    expect(panel.locator('[data-testid="knowledge-storage-note"]')).to_contain_text("비밀값")
    panel.locator('[data-testid="knowledge-content"]').fill("배포 전에는 반드시 시험을 돌린다. 예외: 문서만 바뀐 경우")
    panel.locator('[data-testid="knowledge-summary"]').fill("배포 전 시험")
    panel.locator('[data-testid="knowledge-register"]').click()
    expect(panel.locator('[data-testid="knowledge-K-002"]')).to_contain_text("활성", timeout=15_000)
    view = stack.http.get(f"/api/projects/{project['id']}/knowledge").json()
    second = view["items"][1]["current"]
    assert (second["authority_kind"], second["obligation"]) == ("user_registration", "required")
    assert second["storage"] == "server"
    expect(panel.locator('[data-testid="knowledge-storage-K-002"]')).to_contain_text("서버 저장")
    # 내용 보기 — 열람 경로로 서버 본문이 온다.
    panel.locator('[data-testid="knowledge-show-K-002"]').click()
    expect(panel.locator('[data-testid="knowledge-body-K-002"]')).to_contain_text(
        "배포 전에는 반드시 시험을 돌린다", timeout=15_000
    )
    page.context.close()


def test_a_work_run_leaves_a_candidate_card_and_the_admin_panel_checks_and_activates_it(stack):
    """P4-07 AC-12 — 검증 실행이 남긴 후보가 대화에 "지식 후보" 카드로 보이고(규칙이 아니다), 관리 화면의
    지식 패널에서 채택 확인을 본 뒤 사람이 활성화한다. 종료 뒤 논의 응답의 AI 제안은 후보 카드로 보인다.
    """
    project = stack.project("지식 추출")
    repo = Path(project["repo_path"])
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@example.invalid"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True, capture_output=True)
    (repo / "reader.py").write_text("def read(path):\n    return open(path).read()\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True, capture_output=True)

    page = stack.page()
    _open(stack, page, project["id"])
    case_id = _new_conversation(page)
    _send(page, "HADS_FAKE_WORK=feature HADS_FAKE_NO_QUESTION HADS_FAKE_CANDIDATE 필터를 구현해줘")
    expect(page.locator('[data-testid="agreement-card"]')).to_be_visible(timeout=60_000)
    page.click('[data-testid="agreement-open"]')
    expect(page.locator('[data-testid="agreement-agree"]')).to_be_enabled(timeout=30_000)
    page.click('[data-testid="agreement-agree"]')
    expect(page.locator('[data-testid="work-stage-banner"]')).to_have_attribute("data-progress", "done", timeout=120_000)

    card = page.locator('[data-testid="knowledge-candidate-card"]')
    expect(card).to_be_visible(timeout=30_000)
    expect(card).to_contain_text("K-001")
    expect(card).to_contain_text("후보이며 규칙이 아니다")
    expect(card.locator('[data-testid="knowledge-candidate-row-0"]')).to_have_attribute("data-state", "registered")
    expect(card).to_contain_text("관측: 저장소")
    view = stack.http.get(f"/api/projects/{project['id']}/knowledge").json()
    current = view["items"][0]["current"]
    assert (current["state"], current["authority_kind"], current["obligation"]) == ("candidate", "ai_proposal", "reference")
    assert current["observed"]["purpose"] == "verification_run" and current["storage"] == "server"
    assert stack.http.get(f"/api/cases/{case_id}").json()["status"] == "closed"  # 후보는 완료를 막지 않는다
    # 이 대화의 원문 중 서버 본문은 후보 원문뿐이다(권위 메시지 없음). 제어부는 세션 공유라 다른 시험의 행이 있다.
    with stack.db() as conn:
        purposes = [
            r["purpose"]
            for r in conn.execute(
                "SELECT b.purpose FROM knowledge_body b JOIN artifact_ref a"
                " ON a.artifact_id = b.artifact_id AND a.revision = b.revision WHERE a.case_id = ?",
                (case_id,),
            )
        ]
    assert purposes == ["knowledge"]

    # 종료 뒤 논의 응답의 AI 제안 → 후보 카드(사용자 말이 아니다).
    _send(page, "HADS_FAKE_PROPOSAL 이 업무에서 배운 것을 정리해줘")
    proposal = page.locator('[data-testid="knowledge-proposal-card"]')
    expect(proposal).to_be_visible(timeout=60_000)
    expect(proposal).to_contain_text("K-002")
    expect(proposal).to_contain_text("AI 제안")
    view = stack.http.get(f"/api/projects/{project['id']}/knowledge").json()
    assert view["items"][1]["current"]["authority_kind"] == "ai_proposal"
    assert view["items"][1]["current"]["source_message_id"] is None

    # 관리 화면 — 채택 확인 → 활성화(사람의 결정).
    page.goto(f"{stack.base}/?view=admin&project={project['id']}&case={case_id}")
    panel = page.locator('[data-testid="knowledge-panel"]')
    expect(panel).to_be_visible(timeout=30_000)
    row = panel.locator('[data-testid="knowledge-K-001"]')
    expect(row).to_contain_text("후보")
    expect(row.locator('[data-testid="knowledge-origin-K-001"]')).to_contain_text("관측: 저장소")
    row.locator('[data-testid="knowledge-check-K-001"]').click()
    result = row.locator('[data-testid="knowledge-check-result-K-001"]')
    expect(result).to_be_visible(timeout=15_000)
    expect(result).to_contain_text("막는 항목 없음")
    expect(result).to_contain_text("독립 AI 검토는 돌리지 않았다")
    panel.locator('[data-testid="knowledge-reason"]').fill("시험으로 확인한 관찰이다")
    row.locator('[data-testid="knowledge-activate-K-001"]').click()
    expect(row).to_contain_text("활성", timeout=15_000)
    expect(row.locator('[data-testid="knowledge-adoption-K-001"]')).to_contain_text("채택 확인")
    view = stack.http.get(f"/api/projects/{project['id']}/knowledge").json()
    versions = view["items"][0]["versions"]
    assert [(v["version"], v["state"], v["authority_kind"]) for v in versions] == [
        (1, "superseded", "ai_proposal"), (2, "active", "user_decision")
    ]
    assert versions[1]["adoption"]["by"] == "owner"
    page.context.close()


# ================================================== UI-04a 결정 사항 패널 · 프로젝트 규칙 화면


def _address(page: Page) -> str:
    return page.evaluate("location.href")


def test_the_decisions_panel_and_the_rules_screen_lead_back_to_the_message(stack):
    """UI-04a AC-1·2·4·5·7·9 — 대화에서 말한 규칙이 결정 사항 패널의 "이 대화에서 정한 규칙" 에 보이고 메시지로
    이동한다. 프로젝트 규칙 화면이 등록부를 보이며 "원래 대화로" 가 그 메시지를 강조한다(주소의 `seq` 는 소비).
    개정은 새 버전(이력), 무효는 사유와 함께 상태만 바꾼다. 카드 링크는 프로젝트 규칙 화면을 가리킨다.
    """
    project = stack.project("규칙 화면")
    page = stack.page()
    _open(stack, page, project["id"])
    case_id = _new_conversation(page)
    # 먼저 한 마디 나눈 뒤(#1·#2) 규칙을 말한다(#3) — 가짜 codex 는 고정 컨텍스트 뒤의 마지막 메시지에서만
    # 규칙을 옮기므로, 첫 메시지에서 말하면 지시문 머리를 옮긴다(시험 도구의 특성이지 제품 규칙이 아니다).
    _send(page, "먼저 이야기부터 하자")
    expect(page.locator('[data-testid="message-2"] [data-testid="message-body"]')).to_contain_text("가짜 응답", timeout=60_000)
    expect(page.locator('[data-testid="send-refusal"]')).to_have_count(0, timeout=30_000)  # 요청이 끝나 전송이 열렸다
    _send(page, "HADS_FAKE_RULE 이 프로젝트에서는 앞으로 오류 로그에 시각을 붙이지 마")
    card = page.locator('[data-testid="knowledge-card"]')
    expect(card).to_be_visible(timeout=60_000)
    expect(card).to_have_attribute("data-state", "active")
    expect(card.locator('[data-testid="knowledge-card-rules"]')).to_have_attribute(
        "href", f"?project={project['id']}&screen=rules&item=K-001"
    )

    # 결정 사항 패널 — 이 대화에서 정한 규칙, 메시지로 이동(강조), 프로젝트 규칙으로 가는 링크. 활성화 버튼은 없다.
    page.click('[data-testid="open-decisions"]')
    row = page.locator('[data-testid="decisions-rule-K-001"]')
    expect(row).to_be_visible()
    expect(row).to_contain_text("K-001 v1")
    expect(row).to_contain_text("지금 활성")
    expect(row).to_contain_text("이 대화에서 한 말")
    expect(row).to_have_attribute("data-state", "active")
    assert page.locator('[data-testid="decisions"] [data-testid^="rule-activate-"]').count() == 0
    expect(row.locator('[data-testid="decisions-rule-message-K-001"]')).to_contain_text("메시지 #3")
    row.locator('[data-testid="decisions-rule-message-K-001"]').click()
    expect(page.locator('[data-testid="message-3"]')).to_have_attribute("data-focus", "1")
    expect(row.locator('[data-testid="decisions-rule-open-K-001"]')).to_have_attribute(
        "href", f"?project={project['id']}&screen=rules&item=K-001"
    )

    # 프로젝트 규칙 화면(왼쪽 목록) — 등록부, 출처 링크.
    page.click('[data-testid="open-rules"]')
    screen = page.locator('[data-testid="rules-screen"]')
    expect(screen).to_be_visible()
    assert "screen=rules" in _address(page)
    assert page.locator('[data-testid="review-panel"]').count() == 0  # 규칙 화면에서는 오른쪽 패널이 닫힌다
    rule = screen.locator('[data-testid="rule-K-001"]')
    expect(rule).to_have_attribute("data-state", "active")
    expect(rule).to_have_attribute("data-obligation", "required")
    expect(screen.locator('[data-testid="rules-required"]')).to_contain_text("K-001")
    link = rule.locator('[data-testid="rule-source-link-K-001"]')
    expect(link).to_contain_text("메시지 #3")
    expect(link).to_have_attribute("href", f"?project={project['id']}&case={case_id}&seq=3")

    # 원래 대화로 이동 — 그 메시지가 강조되고 주소의 `seq` 는 소비된다.
    link.click()
    page.wait_for_selector('[data-testid="conversation-title"]')
    expect(page.locator('[data-testid="message-3"]')).to_have_attribute("data-focus", "1", timeout=30_000)
    _wait(lambda: "seq=" not in _address(page), 10, "seq 소비")
    assert f"case={case_id}" in _address(page)

    # 규칙 화면에서 개정(새 버전) → 이력, 내용 보기, 무효(사유).
    page.click('[data-testid="open-rules"]')
    rule = page.locator('[data-testid="rule-K-001"]')
    rule.locator('[data-testid="rule-toggle-K-001"]').click()
    expect(rule.locator('[data-testid="rule-storage-K-001"]')).to_contain_text("서버 저장")
    rule.locator('[data-testid="rule-revise-K-001"]').click()
    rule.locator('[data-testid="rule-revise-summary-K-001"]').fill("오류 로그에 시각 없음(개정)")
    rule.locator('[data-testid="rule-revise-reason-K-001"]').fill("표현을 다듬음")
    rule.locator('[data-testid="rule-revise-submit-K-001"]').click()
    expect(rule).to_contain_text("v2", timeout=15_000)
    expect(rule.locator('[data-testid="rule-history-K-001"]')).to_contain_text("v1 대체됨")
    expect(rule.locator('[data-testid="rule-history-K-001"]')).to_contain_text("표현을 다듬음")
    view = stack.http.get(f"/api/projects/{project['id']}/knowledge").json()
    item = next(i for i in view["items"] if i["knowledge_key"] == "K-001")
    assert [(v["version"], v["state"], v["authority_kind"]) for v in item["versions"]] == [
        (1, "superseded", "user_statement"), (2, "active", "user_registration")
    ]
    assert item["current"]["source_case_title"] == "새 대화" and item["current"]["source_message_seq"] is None
    rule.locator('[data-testid="rule-show-K-001"]').click()
    expect(rule.locator('[data-testid="rule-body-K-001"]')).to_contain_text("오류 로그에 시각을 붙이지 마", timeout=15_000)
    rule.locator('[data-testid="rule-invalidate-K-001"]').click()
    rule.locator('[data-testid="rule-invalidate-reason-K-001"]').fill("더 이상 맞지 않는다")
    rule.locator('[data-testid="rule-invalidate-confirm-K-001"]').click()
    expect(page.locator('[data-testid="rules-history-toggle"]')).to_contain_text("대체·무효 1", timeout=15_000)
    assert page.locator('[data-testid="rules-required"] [data-testid="rule-K-001"]').count() == 0
    view = stack.http.get(f"/api/projects/{project['id']}/knowledge").json()
    current = next(i for i in view["items"] if i["knowledge_key"] == "K-001")["current"]
    assert (current["state"], current["invalid_reason"]) == ("invalid", "더 이상 맞지 않는다")
    page.context.close()


def test_a_rule_registered_on_the_rules_screen_reaches_the_work_and_a_candidate_is_activated_there(stack):
    """UI-04a AC-1·3·6·8·9·14 — 규칙 화면의 수동 등록(출처 대화 선택)은 바로 활성이고 그 뒤의 업무 실행에
    들어간다. 결정 사항 패널이 목표·기준·결정·적용된 규칙(Manifest 집계)·실행 후보를 보이고, 후보의 채택 확인·
    활성화는 규칙 화면에서 한다(카드 링크로 항목이 펼쳐진다). 관리 화면의 지식 패널은 그대로다.
    """
    project = stack.project("규칙 적용")
    repo = Path(project["repo_path"])
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@example.invalid"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True, capture_output=True)
    (repo / "reader.py").write_text("def read(path):\n    return open(path).read()\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True, capture_output=True)

    page = stack.page()
    _open(stack, page, project["id"])
    case_id = _new_conversation(page)

    # 규칙 화면에서 수동 등록 — 출처는 이 대화, 바로 활성(재승인 없음).
    page.click('[data-testid="open-rules"]')
    screen = page.locator('[data-testid="rules-screen"]')
    expect(screen).to_be_visible()
    expect(screen.locator('[data-testid="rules-note"]')).to_contain_text("서버에 저장")
    expect(screen.locator('[data-testid="rules-note"]')).to_contain_text("비밀값")
    expect(screen.locator('[data-testid="rules-required"]')).to_contain_text("활성 필수 규칙이 없다")
    page.select_option('[data-testid="rules-register-case"]', case_id)
    page.fill('[data-testid="rules-register-content"]', "구현할 때 함수마다 한 줄 docstring 을 단다. 예외: 시험 파일")
    page.fill('[data-testid="rules-register-summary"]', "한 줄 docstring")
    page.click('[data-testid="rules-register"]')
    expect(screen.locator('[data-testid="rules-register-done"]')).to_contain_text("K-001 v1", timeout=15_000)
    rule = screen.locator('[data-testid="rule-K-001"]')
    expect(rule).to_have_attribute("data-state", "active")
    expect(rule.locator('[data-testid="rule-source-link-K-001"]')).to_contain_text("새 대화")
    view = stack.http.get(f"/api/projects/{project['id']}/knowledge").json()
    current = next(i for i in view["items"] if i["knowledge_key"] == "K-001")["current"]
    assert (current["authority_kind"], current["storage"], current["source_case_id"]) == (
        "user_registration", "server", case_id
    )

    # 대화로 돌아가 업무를 돌린다 — 규칙이 실행에 들어가고 검증 실행이 후보를 남긴다.
    page.click('[data-testid="rules-back"]')
    page.wait_for_selector('[data-testid="composer-input"]')
    assert "screen=rules" not in _address(page)
    _send(page, "HADS_FAKE_WORK=feature HADS_FAKE_NO_QUESTION HADS_FAKE_CANDIDATE 필터를 구현해줘")
    expect(page.locator('[data-testid="agreement-card"]')).to_be_visible(timeout=60_000)
    page.click('[data-testid="agreement-open"]')
    expect(page.locator('[data-testid="agreement-agree"]')).to_be_enabled(timeout=30_000)
    page.click('[data-testid="agreement-agree"]')
    expect(page.locator('[data-testid="work-stage-banner"]')).to_have_attribute("data-progress", "done", timeout=120_000)

    # 결정 사항 패널 — 목표·기준, 결정(의도 동의 → 의도 v1), 적용된 규칙(집계 = 서버 값), 실행 후보.
    page.click('[data-testid="open-decisions"]')
    expect(page.locator('[data-testid="decisions-goal"]')).to_contain_text("의도 v1")
    expect(page.locator('[data-testid="decisions-goal"]')).to_contain_text("의도 동의됨")
    expect(page.locator('[data-testid="decision-intent_agreement"]').first).to_contain_text("의도 v1")
    applied = page.locator('[data-testid="applied-K-001"]')
    expect(applied).to_be_visible(timeout=15_000)
    expect(applied).to_contain_text("필수")
    expect(applied).to_contain_text("제공 실행")
    expect(page.locator('[data-testid="decisions-applied"]')).to_contain_text("준수의 증거가 아니다")
    use = stack.http.get(f"/api/cases/{case_id}/knowledge-use").json()
    [use_item] = use["items"]
    assert use_item["knowledge_key"] == "K-001" and use_item["provided_runs"] >= 1
    assert applied.get_attribute("data-provided") == str(use_item["provided_runs"])
    assert use["runs_unrecorded"] == 0
    candidate = page.locator('[data-testid="decisions-rule-K-002"]')
    expect(candidate).to_have_attribute("data-state", "candidate")
    expect(candidate).to_contain_text("실행이 남긴 후보")
    assert page.locator('[data-testid="decisions"] [data-testid^="rule-activate-"]').count() == 0
    expect(page.locator('[data-testid="knowledge-candidate-rules"]')).to_have_attribute(
        "href", f"?project={project['id']}&screen=rules&item=K-002"
    )

    # 프로젝트 규칙에서 보기 → 항목이 펼쳐진다 → 채택 확인 → 활성화(사람의 결정, 새 버전).
    candidate.locator('[data-testid="decisions-rule-open-K-002"]').click()
    screen = page.locator('[data-testid="rules-screen"]')
    expect(screen).to_be_visible(timeout=30_000)
    rule = screen.locator('[data-testid="rule-K-002"]')
    expect(rule.locator('[data-testid="rule-details-K-002"]')).to_be_visible()
    expect(rule.locator('[data-testid="rule-origin-K-002"]')).to_contain_text("관측: 저장소")
    expect(rule.locator('[data-testid="rule-source-K-002"]')).to_contain_text("AI 제안")
    expect(screen.locator('[data-testid="rules-candidates"]')).to_contain_text("K-002")
    rule.locator('[data-testid="rule-check-K-002"]').click()
    result = rule.locator('[data-testid="rule-check-result-K-002"]')
    expect(result).to_be_visible(timeout=15_000)
    expect(result).to_contain_text("막는 항목 없음")
    expect(result).to_contain_text("독립 AI 검토는 돌리지 않았다")
    rule.locator('[data-testid="rule-activate-reason-K-002"]').fill("시험으로 확인한 관찰이다")
    rule.locator('[data-testid="rule-activate-K-002"]').click()
    expect(rule).to_have_attribute("data-state", "active", timeout=15_000)
    expect(rule.locator('[data-testid="rule-adoption-K-002"]')).to_contain_text("채택 확인")
    expect(screen.locator('[data-testid="rules-reference"]')).to_contain_text("K-002")
    view = stack.http.get(f"/api/projects/{project['id']}/knowledge").json()
    versions = next(i for i in view["items"] if i["knowledge_key"] == "K-002")["versions"]
    assert [(v["version"], v["state"], v["authority_kind"]) for v in versions] == [
        (1, "superseded", "ai_proposal"), (2, "active", "user_decision")
    ]
    assert versions[1]["adoption"]["by"] == "owner" and versions[1]["obligation"] == "reference"

    # 관리 화면의 지식 패널은 그대로 동작한다.
    page.goto(f"{stack.base}/?view=admin&project={project['id']}&case={case_id}")
    panel = page.locator('[data-testid="knowledge-panel"]')
    expect(panel).to_be_visible(timeout=30_000)
    expect(panel.locator('[data-testid="knowledge-K-002"]')).to_contain_text("활성")
    expect(panel.locator('[data-testid="knowledge-adoption-K-002"]')).to_contain_text("채택 확인")
    page.context.close()


# ================================================== P4-07b 참고 후보의 자동 활성 조건(반자동)


def _git_repo(project: dict[str, Any]) -> None:
    repo = Path(project["repo_path"])
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@example.invalid"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True, capture_output=True)
    (repo / "reader.py").write_text("def read(path):\n    return open(path).read()\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True, capture_output=True)


def _run_work_with_candidate(page: Page) -> str:
    case_id = _new_conversation(page)
    _send(page, "HADS_FAKE_WORK=feature HADS_FAKE_NO_QUESTION HADS_FAKE_CANDIDATE 필터를 구현해줘")
    expect(page.locator('[data-testid="agreement-card"]')).to_be_visible(timeout=60_000)
    page.click('[data-testid="agreement-open"]')
    expect(page.locator('[data-testid="agreement-agree"]')).to_be_enabled(timeout=30_000)
    page.click('[data-testid="agreement-agree"]')
    expect(page.locator('[data-testid="work-stage-banner"]')).to_have_attribute("data-progress", "done", timeout=120_000)
    return case_id


def test_a_candidate_seen_by_two_runs_shows_the_ready_badge_and_a_human_activates_it_at_once(stack):
    """P4-07b AC-8 — 검증 실행 하나의 후보는 카드·규칙 화면에 "자동 활성 조건 미충족(근거 실행)" 배지, 다른 대화의
    검증 실행이 같은 내용을 보고하면 "충족" 배지. **그래도 후보 그대로다.** 사람이 규칙 화면의 "한 번에 활성화"를 누르면
    활성 참고(v2, `user_decision`, 충족 항목 기록)가 되고 버튼은 0건으로 돌아간다. 사용자 결정(2026-09-24): 반자동.
    """
    project = stack.project("자동 활성 조건")
    _git_repo(project)
    page = stack.page()
    _open(stack, page, project["id"])

    first = _run_work_with_candidate(page)
    card = page.locator('[data-testid="knowledge-candidate-card"]')
    expect(card).to_be_visible(timeout=30_000)
    badge = card.locator('[data-testid="knowledge-candidate-auto-0"]')
    expect(badge).to_have_attribute("data-ready", "0")
    expect(badge).to_contain_text("미충족")
    expect(badge).to_contain_text("서로 다른 실행 둘 이상의 근거")
    view = stack.http.get(f"/api/projects/{project['id']}/knowledge").json()
    [item] = view["items"]
    assert item["knowledge_key"] == "K-001" and item["current"]["state"] == "candidate"
    assert item["auto_reference"]["unmet"] == ["two_runs"]

    # 둘째 대화 — 같은 후보를 다시 보고(같은 내용 → 근거). 조건 충족이지만 **활성화되지 않는다**.
    second = _run_work_with_candidate(page)
    assert second != first
    evidence_row = page.locator('[data-testid="knowledge-candidate-card"] [data-testid="knowledge-candidate-row-0"]')
    expect(evidence_row).to_have_attribute("data-state", "evidence", timeout=30_000)
    view = stack.http.get(f"/api/projects/{project['id']}/knowledge").json()
    [item] = view["items"]
    assert item["auto_reference"]["ready"] is True and item["current"]["state"] == "candidate"
    assert len(item["auto_reference"]["evidence_runs"]) == 2

    # 규칙 화면 — 충족 배지, 상태는 후보, 버튼 "조건 충족 1건". 누르면(사람의 결정) 활성 참고 v2.
    page.click('[data-testid="open-rules"]')
    screen = page.locator('[data-testid="rules-screen"]')
    expect(screen).to_be_visible(timeout=30_000)
    rule = screen.locator('[data-testid="rule-K-001"]')
    expect(rule).to_have_attribute("data-state", "candidate")
    expect(rule.locator('[data-testid="rule-auto-K-001"]')).to_have_attribute("data-ready", "1")
    expect(rule.locator('[data-testid="rule-auto-K-001"]')).to_contain_text("자동 활성 조건 충족")
    button = screen.locator('[data-testid="rules-activate-ready"]')
    expect(button).to_have_attribute("data-count", "1")
    expect(button).to_be_enabled()
    expect(screen.locator('[data-testid="rules-candidates"]')).to_contain_text("K-001")
    rule.locator('[data-testid="rule-toggle-K-001"]').click()
    conditions = rule.locator('[data-testid="rule-auto-list-K-001"] [data-met]')
    expect(conditions).to_have_count(8)
    assert conditions.evaluate_all("els => els.every(e => e.dataset.met === '1')")
    assert stack.http.get(f"/api/projects/{project['id']}/knowledge").json()["items"][0]["current"]["state"] == "candidate"

    button.click()
    expect(screen.locator('[data-testid="rules-activate-ready-result"]')).to_contain_text("활성화 1건 — K-001 v2", timeout=15_000)
    expect(rule).to_have_attribute("data-state", "active", timeout=15_000)
    expect(rule).to_have_attribute("data-obligation", "reference")
    expect(screen.locator('[data-testid="rules-reference"]')).to_contain_text("K-001")
    assert screen.locator('[data-testid="rules-candidates"] [data-testid="rule-K-001"]').count() == 0
    expect(button).to_have_attribute("data-count", "0")
    expect(button).to_be_disabled()
    # 펼침 상태는 항목 키로 기억되므로 절이 바뀌어도(후보 → 활성 참고) 펼쳐진 채다. 접혀 있으면 연다.
    if rule.locator('[data-testid="rule-details-K-001"]').count() == 0:
        rule.locator('[data-testid="rule-toggle-K-001"]').click()
    expect(rule.locator('[data-testid="rule-adoption-K-001"]')).to_contain_text("사람이 한 번에 활성화")
    assert rule.locator('[data-testid="rule-auto-K-001"]').count() == 0  # 후보가 아니면 배지가 없다
    view = stack.http.get(f"/api/projects/{project['id']}/knowledge").json()
    [item] = view["items"]
    assert [(v["version"], v["state"], v["authority_kind"], v["obligation"]) for v in item["versions"]] == [
        (1, "superseded", "ai_proposal", "reference"), (2, "active", "user_decision", "reference")
    ]
    new = item["current"]
    assert new["reason_summary"] == "자동 활성 조건 충족 — 사람이 한 번에 활성화"
    assert new["adoption"]["by"] == "owner" and len(new["adoption"]["auto_reference"]["met"]) == 8
    assert len(new["adoption"]["auto_reference"]["evidence_runs"]) == 2
    assert item["auto_reference"] is None
    page.context.close()


# ================================================== UI-04b 프로젝트 설정·상세 설정·알림


def test_project_defaults_reach_new_conversations_and_the_case_settings_tab_adjusts_and_reverts(stack):
    """UI-04b AC-1·2·4·5·6·7 — 프로젝트 설정 화면(기본값·규칙·저장소 탭)에서 기본값을 바꾸면 **그 뒤에 만든** 대화의
    출처가 `프로젝트 기본값`이고 설정 전 대화는 그대로다. 상세 설정 탭에서 Autonomy·진행 상한을 바꾸고 기본값으로
    되돌리며, 저장소 선택(허용 명시)·QG 설정(사유 필수)이 서버 규칙 그대로 반영된다. 규칙 화면은 설정 화면의 탭으로
    옮겨 왔고 주소·뒤로 가기가 그대로다.
    """
    project = stack.project("설정 화면")
    page = stack.page()
    _open(stack, page, project["id"])
    before = _new_conversation(page)

    # 프로젝트 설정 — 기본값 탭. 모델·깊이는 기본값이 없다는 사실이 보인다.
    page.click('[data-testid="open-settings"]')
    screen = page.locator('[data-testid="settings-screen"]')
    expect(screen).to_be_visible()
    expect(screen).to_have_attribute("data-tab", "defaults")
    assert "screen=settings" in _address(page)
    expect(page.locator('[data-testid="setting-model"]')).to_contain_text("CLI 가 스스로 정한다")
    expect(page.locator('[data-testid="setting-depth"]')).to_contain_text("수준 판단")
    expect(page.locator('[data-testid="setting-default_autonomy"]')).to_have_attribute("data-source", "system_default")
    expect(page.locator('[data-testid="settings-tool-verified"]')).to_contain_text("verified")
    expect(page.locator('[data-testid="settings-note"]')).to_contain_text("이 뒤에 만드는 대화")
    page.fill('[data-testid="settings-reason"]', "시험 기본값")
    page.click('[data-testid="setting-autonomy-controlled"]')
    autonomy = page.locator('[data-testid="setting-default_autonomy"]')
    expect(autonomy).to_have_attribute("data-source", "project_setting", timeout=15_000)
    expect(autonomy).to_have_attribute("data-value", "controlled")
    expect(autonomy.locator('[data-testid="setting-source-default_autonomy"]')).to_contain_text("프로젝트 설정")
    expect(autonomy).to_contain_text("적용 시점")
    page.fill('[data-testid="setting-input-repair_limit"]', "1")
    page.click('[data-testid="setting-input-repair_limit-set"]')
    expect(page.locator('[data-testid="setting-repair_limit"]')).to_have_attribute("data-value", "1", timeout=15_000)
    expect(page.locator('[data-testid="setting-repair_limit"]')).to_have_attribute("data-source", "project_setting")
    # 기본 예산 — 강제 불가한 hard 한도는 거부되고(문구 그대로) 저장되지 않는다.
    page.select_option('[data-testid="setting-budget-metric"]', "input_tokens")
    page.select_option('[data-testid="setting-budget-threshold"]', "hard")
    page.fill('[data-testid="setting-budget-value"]', "5")
    page.click('[data-testid="setting-budget-set"]')
    expect(page.locator('[data-testid="settings-error"]')).to_contain_text("cannot be enforced", timeout=15_000)
    page.select_option('[data-testid="setting-budget-metric"]', "run_count")
    page.fill('[data-testid="setting-budget-value"]', "3")
    page.click('[data-testid="setting-budget-set"]')
    expect(page.locator('[data-testid="setting-budget-run_count-hard"]')).to_contain_text("절대 상한", timeout=15_000)
    page.click('[data-testid="settings-history-toggle"]')
    expect(page.locator('[data-testid="settings-history-1"]')).to_contain_text("controlled")
    expect(page.locator('[data-testid="settings-history-1"]')).to_contain_text("시험 기본값")
    view = stack.http.get(f"/api/projects/{project['id']}/settings").json()
    assert [(r["setting_key"], r["value"], r["state"]) for r in view["history"]] == [
        ("default_autonomy", "controlled", "current"), ("repair_limit", 1, "current"), ("budget:run_count:hard", 3.0, "current"),
    ]

    # 저장소 탭·규칙 탭(UI-04a 화면이 옮겨 왔다 — 주소 `screen=rules`·`rules-back` 그대로).
    page.click('[data-testid="settings-tab-repositories"]')
    expect(page.locator('[data-testid="settings-repositories"]')).to_contain_text("primary")
    expect(page.locator('[data-testid="settings-repositories"]')).to_contain_text("등록은 선택도 허용도 아니다")
    assert "screen=repositories" in _address(page)
    page.click('[data-testid="settings-tab-rules"]')
    expect(page.locator('[data-testid="rules-screen"]')).to_be_visible()
    expect(page.locator('[data-testid="rules-required"]')).to_contain_text("활성 필수 규칙이 없다")
    assert "screen=rules" in _address(page)
    page.click('[data-testid="open-rules"]')  # 왼쪽 목록의 진입도 규칙 탭이다
    expect(page.locator('[data-testid="settings-screen"]')).to_have_attribute("data-tab", "rules")
    page.click('[data-testid="rules-back"]')
    page.wait_for_selector('[data-testid="composer-input"]')
    assert "screen=" not in _address(page)

    # 설정 뒤 만든 대화 — 적용 요약과 상세 설정 탭이 프로젝트 기본값을 출처로 보인다.
    after = _new_conversation(page)
    summary = page.locator('[data-testid="settings-summary"]')
    expect(summary).to_contain_text("controlled", timeout=15_000)
    page.click('[data-testid="settings-summary-line"]')
    expect(page.locator('[data-testid="settings-summary-sources"]')).to_contain_text("프로젝트 기본값")
    page.click('[data-testid="open-case-settings"]')
    settings = page.locator('[data-testid="case-settings"]')
    expect(settings).to_be_visible()
    expect(page.locator('[data-testid="case-setting-autonomy"]')).to_have_attribute("data-source", "project_default")
    expect(page.locator('[data-testid="case-limit-repair_limit"]')).to_have_attribute("data-source", "project_setting")
    expect(page.locator('[data-testid="case-limit-repair_limit"]')).to_contain_text("1")
    expect(page.locator('[data-testid="case-budget-run_count-hard"]')).to_have_attribute("data-set-by", "project_default")
    expect(page.locator('[data-testid="case-level-none"]')).to_contain_text("수준 판단 없음")
    policy = stack.http.get(f"/api/cases/{after}/policy").json()
    assert (policy["autonomy"], policy["autonomy_source"]) == ("controlled", "project_default")

    # 이 업무에서 바꾸면 출처가 바뀌고, 복귀하면 프로젝트 기본값으로 돌아온다(새 리비전).
    page.fill('[data-testid="case-autonomy-reason"]', "이 업무는 자율로")
    page.click('[data-testid="case-autonomy-ask"]')
    expect(page.locator('[data-testid="case-setting-autonomy"]')).to_have_attribute("data-source", "case_explicit", timeout=15_000)
    page.click('[data-testid="case-autonomy-reset"]')
    expect(page.locator('[data-testid="case-setting-autonomy"]')).to_have_attribute("data-source", "project_default", timeout=15_000)
    revisions = stack.http.get(f"/api/cases/{after}/policy-revisions").json()
    assert [(r["autonomy"], r["autonomy_source"], r["state"]) for r in revisions] == [
        ("controlled", "project_default", "superseded"), ("ask_on_decision", "case_explicit", "superseded"),
        ("controlled", "project_default", "current"),
    ]
    page.fill('[data-testid="case-limit-input-repair_limit"]', "4")
    page.click('[data-testid="case-limit-set"]')
    expect(page.locator('[data-testid="case-limit-repair_limit"]')).to_have_attribute("data-source", "case_setting", timeout=15_000)
    page.click('[data-testid="case-limit-reset-repair_limit"]')
    expect(page.locator('[data-testid="case-limit-repair_limit"]')).to_have_attribute("data-source", "project_setting", timeout=15_000)
    limits = stack.http.get(f"/api/cases/{after}/progress").json()["limits"]
    assert (limits["repair_limit"]["value"], limits["repair_limit"]["source"]) == (1, "project_setting")
    assert [(r["limit_value"], r["state"]) for r in limits["history"]] == [(4, "superseded")]

    # 저장소 선택 — 쓰기·게시 허용은 명시다. QG-02 설정 — 사유가 필수다.
    repo_id = stack.http.get(f"/api/projects/{project['id']}/repositories").json()["repositories"][0]["id"]
    page.select_option('[data-testid="case-repo-select"]', repo_id)
    page.check('[data-testid="case-repo-write"]')
    page.click('[data-testid="case-repo-submit"]')
    row = page.locator(f'[data-testid="case-repo-{repo_id}"]')
    expect(row).to_have_attribute("data-selected", "1", timeout=15_000)
    expect(row).to_contain_text("코드 쓰기 허용")
    expect(row).to_contain_text("게시 불허")
    page.click('[data-testid="case-gate-edit-QG-02"]')
    expect(page.locator('[data-testid="case-gate-submit-QG-02"]')).to_be_disabled()
    page.fill('[data-testid="case-gate-reason-QG-02"]', "설계 검토를 켠다")
    page.click('[data-testid="case-gate-submit-QG-02"]')
    expect(page.locator('[data-testid="case-gate-QG-02"]')).to_have_attribute("data-setting", "on", timeout=15_000)
    gates = stack.http.get(f"/api/cases/{after}/quality-gates").json()["gates"]
    qg02 = next(g for g in gates if g["gate"] == "QG-02")
    assert (qg02["setting"], qg02["source"]) == ("on", "case_explicit")

    # 설정 전 대화는 그대로다 — 시스템 기본값, 예산 행 없음(소급 없음).
    page.click(f'[data-testid="conversation-row-{before}"]')
    page.wait_for_selector('[data-testid="composer-input"]')
    page.click('[data-testid="settings-summary-line"]')
    page.click('[data-testid="open-case-settings"]')
    expect(page.locator('[data-testid="case-setting-autonomy"]')).to_have_attribute("data-source", "system_default")
    assert page.locator('[data-testid^="case-budget-run_count"]').count() == 0
    policy = stack.http.get(f"/api/cases/{before}/policy").json()
    assert (policy["autonomy"], policy["autonomy_source"], policy["budget"]["unlimited"]) == ("ask_on_decision", "system_default", True)
    page.context.close()


def test_pc_notifications_record_transitions_and_suppress_the_conversation_being_viewed(stack):
    """UI-04b AC-8 — 알림을 켜면(권한 허용) **보고 있지 않은** 대화의 답변 필요가 기록·팝업이 되고, 보고 있는 대화의
    같은 사건은 억제로 기록된다. 다른 프로젝트의 주의 증가는 수로 알리고 자동으로 옮기지 않는다. 첫 조회·빈 새 대화는
    알리지 않는다. 기록의 `열기`는 사람이 그 대화를 여는 것이다.
    """
    project = stack.project("알림")
    context = stack.browser.new_context(viewport={"width": 1360, "height": 860}, permissions=["notifications"])
    page = stack.page(context)
    _open(stack, page, project["id"])
    log = page.locator('[data-testid="notice-log"]')
    expect(log).to_have_attribute("data-count", "0")
    page.check('[data-testid="notify-toggle"]')
    expect(page.locator('[data-testid="notify-state"]')).to_contain_text("켜짐")
    expect(page.locator('[data-testid="notify-state"]')).to_have_attribute("data-permission", "granted")

    viewing = _new_conversation(page)
    page.wait_for_timeout(6_000)  # 목록 조회 한 바퀴 — 빈 새 대화는 알림이 아니다
    expect(log).to_have_attribute("data-count", "0")

    # 보고 있지 않은 대화 — API 로 만들어 업무 요청(질문 하나가 남는다) → 답변 필요 → 기록·팝업.
    other = stack.http.post(f"/api/projects/{project['id']}/conversations", json={"title": "다른 대화"}).json()["case_id"]
    sent = stack.http.post(
        f"/api/cases/{other}/messages",
        json={"client_message_id": "notify-1", "content": "HADS_FAKE_WORK=research 서버 로그를 분석해서 개선안을 정리해줘",
              "summary": "요청", "target_runner_id": RunnerProcessId.get(stack)},
    )
    assert sent.status_code == 202, sent.text
    entry = page.locator(f'[data-testid="notice-log"] [data-case="{other}"][data-kind="needs_response"]')
    _wait(lambda: int(log.get_attribute("data-count") or "0") >= 1, 90, "알림 기록")
    page.click('[data-testid="notice-log-toggle"]')
    expect(entry).to_have_count(1, timeout=30_000)
    expect(entry).to_have_attribute("data-suppressed", "0")
    expect(entry).to_have_attribute("data-popped", "1")
    expect(entry).to_contain_text("답변 필요")
    expect(entry).to_contain_text("다른 대화")
    assert _case_in_url(page) == viewing  # 자동으로 옮기지 않았다

    # 보고 있는 대화의 같은 사건은 억제된다(기록에는 남는다).
    _send(page, "HADS_FAKE_WORK=research 이 로그도 분석해서 정리해줘")
    expect(page.locator('[data-testid="question-cards"]')).to_have_count(1, timeout=90_000)
    mine = page.locator(f'[data-testid="notice-log"] [data-case="{viewing}"][data-kind="needs_response"]')
    expect(mine).to_have_count(1, timeout=30_000)
    expect(mine).to_have_attribute("data-suppressed", "1")
    expect(mine).to_have_attribute("data-popped", "0")
    expect(mine).to_contain_text("보고 있는 대화라 팝업 없음")

    # 다른 프로젝트의 주의 수가 늘면 한 건으로 알리고 자동으로 옮기지 않는다.
    elsewhere = stack.project("알림 다른 프로젝트")
    far = stack.http.post(f"/api/projects/{elsewhere['id']}/conversations", json={"title": "먼 대화"}).json()["case_id"]
    stack.http.post(
        f"/api/cases/{far}/messages",
        json={"client_message_id": "notify-2", "content": "HADS_FAKE_WORK=research 여기도 분석해줘",
              "summary": "요청", "target_runner_id": RunnerProcessId.get(stack)},
    )
    attention = page.locator(f'[data-testid="notice-log"] [data-project="{elsewhere["id"]}"][data-kind="project_attention"]')
    expect(attention).to_have_count(1, timeout=90_000)
    expect(attention).to_contain_text("답변 필요 1")
    expect(attention).to_contain_text("자동으로 옮기지 않는다")
    assert page.input_value('[data-testid="project-select"]') == project["id"]

    # 예산 도달(UI-04b 보충, 사용자 결정) — 보고 있지 않은 대화에 프로젝트 기본 예산(run_count hard 1)을 적용하면 이미 실행 둘을
    # 쓴 그 대화는 hard 도달 → 기록·팝업·목록 배지. 한도를 올리면 풀린다(도출).
    assert stack.http.put(
        f"/api/projects/{project['id']}/settings",
        json={"values": {"budget:run_count:hard": 1}, "set_by": "owner"},
    ).status_code == 200
    applied = stack.http.post(f"/api/cases/{other}/budget/project-defaults", json={"set_by": "owner"})
    assert applied.status_code == 200 and applied.json()["applied"] == 1 and applied.json()["stop"]["stopped"]
    budget_entry = page.locator(f'[data-testid="notice-log"] [data-case="{other}"][data-kind="budget_stop"]')
    expect(budget_entry).to_have_count(1, timeout=30_000)
    expect(budget_entry).to_have_attribute("data-suppressed", "0")
    expect(budget_entry).to_have_attribute("data-popped", "1")
    expect(budget_entry).to_contain_text("예산 도달")
    # 답변이 필요한 대화 절과 대화 절에 같은 행이 있다 — 첫 것으로 본다.
    expect(page.locator(f'[data-testid="conversation-row-{other}"]').first).to_contain_text("예산 도달")
    assert page.locator(f'[data-testid="conversation-row-{viewing}"]').get_by_text("예산 도달").count() == 0

    # 기록의 `열기` — 사람이 그 대화를 연다.
    n = entry.get_attribute("data-testid").split("-")[-1]
    page.click(f'[data-testid="notice-open-{n}"]')
    _wait(lambda: _case_in_url(page) == other, 15, "알림에서 연 대화")
    expect(page.locator('[data-testid="conversation-title"]')).to_contain_text("다른 대화")
    context.close()


# ================================================== UI-04c — D-86 목적·유형 변경 / D-88 시간 / D-89 작업 PC

RCA_FIELDS = ["phenomenon", "observations", "cause_questions", "conclusion_requirement", "analysis_end_condition"]


def test_a_purpose_change_in_the_work_stage_revises_the_profile_and_reauthors_the_intent(stack):
    """UI-04c AC-9 — 결정 사항 패널의 개정 폼으로 원인 분석 업무를 결함 수정으로 개정(이전 목적 유지)하면 같은 대화의
    Profile 이 바뀌고(머리·업무 절·타임라인 표식), 진행기가 의도를 새 버전(유지 항목 포함)으로 다시 써 동의 카드가 그
    버전을 가리킨다. 개정 목록이 대응(승계/재검사)을 보인다. 준비 단계 대화에는 개정 폼이 없다."""
    project = stack.project("목적 변경")
    _git_repo(project)
    page = stack.page()
    _open(stack, page, project["id"])
    case_id = _new_conversation(page)
    _send(page, "HADS_FAKE_WORK=root_cause_analysis HADS_FAKE_NO_QUESTION 로그 형식 문제의 원인을 찾아줘")
    expect(page.locator('[data-testid="agreement-card"]')).to_be_visible(timeout=60_000)
    expect(page.locator('[data-testid="stage-label"]')).to_contain_text("원인 분석")
    first = stack.http.get(f"/api/cases/{case_id}/intent-state").json()["latest_intent_version"]
    assert (first["revision"], first["profile"], first["retained_fields"]) == (1, "root_cause_analysis", [])

    page.click('[data-testid="open-decisions"]')
    work = page.locator('[data-testid="decisions-work"]')
    expect(work).to_have_attribute("data-profile", "root_cause_analysis")
    expect(page.locator('[data-testid="decisions-current-profile"]')).to_have_text("원인 분석")
    expect(page.locator('[data-testid="revision-submit"]')).to_be_disabled()  # 사유가 필수다
    page.select_option('[data-testid="revision-profile"]', "defect_fix")
    page.fill('[data-testid="revision-reason"]', "원인을 찾고 수정도 한다")
    page.click('[data-testid="revision-submit"]')
    expect(page.locator('[data-testid="revision-notice"]')).to_contain_text("개정을 기록했다", timeout=15_000)
    expect(work).to_have_attribute("data-profile", "defect_fix", timeout=15_000)
    expect(page.locator('[data-testid="decisions-current-profile"]')).to_have_text("결함 수정")
    revision = page.locator('[data-testid="profile-revision-1"]')
    expect(revision).to_contain_text("원인 분석 → 결함 수정")
    expect(revision).to_contain_text("이전 목적 유지: 원인 질문에 대한 결론")
    expect(revision).to_contain_text("사람")
    expect(page.locator('[data-testid="stage-label"]')).to_contain_text("결함 수정")
    expect(page.locator('[data-testid="profile-revision-marker-1"]')).to_contain_text("목적·유형 변경됨")
    view = stack.http.get(f"/api/cases/{case_id}/profile-revisions").json()
    assert (view["profile"], view["profile_source"]) == ("defect_fix", "revised")
    assert view["revisions"][0]["carried_objectives"] == ["cause"] and view["retained_fields"] == RCA_FIELDS

    # 진행기 — 의도 개정 실행이 새 버전을 쓰고(유지 항목 포함) 동의 카드가 그 버전을 가리킨다.
    second = _wait(
        lambda: (lambda v: v if v and v["revision"] == 2 else None)(
            stack.http.get(f"/api/cases/{case_id}/intent-state").json()["latest_intent_version"]
        ),
        90,
        "의도 v2",
    )
    assert (second["profile"], second["retained_fields"]) == ("defect_fix", RCA_FIELDS)
    assert {f["field"] for f in second["fields"]} >= set(RCA_FIELDS)
    expect(page.locator('[data-testid="agreement-card"]')).to_be_visible(timeout=60_000)
    _wait(
        lambda: stack.http.get(f"/api/cases/{case_id}/conversation").json()["progress"]["wait"]
        and stack.http.get(f"/api/cases/{case_id}/conversation").json()["progress"]["wait"][0].get("intent_version_id") == second["id"],
        60,
        "새 버전의 동의 대기",
    )
    expect(page.locator('[data-testid="revision-mapping-1"]')).to_be_visible(timeout=30_000)
    mapping = stack.http.get(f"/api/cases/{case_id}/profile-revisions").json()["revisions"][0]["criteria_mapping"]
    assert {m["key"] for m in mapping} == {"C-01", "C-02"}
    assert all(m["state"] in ("carried", "recheck", "no_target") for m in mapping)  # 판정이 없던 기준은 승계할 것이 없다
    conv = stack.http.get(f"/api/cases/{case_id}/conversation").json()
    assert (conv["profile"], conv["profile_source"], len(conv["profile_revisions"])) == ("defect_fix", "revised", 1)

    # 준비 단계 대화 — 업무 절·개정 폼이 없다(처음 Profile 은 업무화가 정한다).
    prep = _new_conversation(page)
    page.click('[data-testid="open-decisions"]')
    expect(page.locator('[data-testid="decisions"]')).to_be_visible()
    assert page.locator('[data-testid="profile-revision-form"]').count() == 0
    refused = stack.http.post(
        f"/api/cases/{prep}/profile-revisions",
        json={"profile": "feature", "added_objectives": [], "keep_previous_objectives": True, "actor": "owner", "reason_summary": "x"},
    )
    assert refused.status_code == 409 and refused.json()["detail"]["refusals"] == ["case_not_in_work_stage"]
    page.context.close()


def test_time_limits_default_to_execution_time_and_the_workspace_row_names_the_work_pc(stack):
    """UI-04c AC-10·AC-14 — 상세 설정의 시간 절이 실행시간 합계·경과시간을 보이고 "시간 한도 추가" 가 실행시간 합계를
    기본으로 고른다(설정된 한도는 라벨·보장 그대로). 결과물의 작업공간 절이 작업 PC(작업공간을 만든 Runner)·경로·복사·
    열기 지원 상태를 서버 값 그대로 보인다 — 시험 Runner 는 열기를 껐으므로 버튼이 비활성이고 서버도 거부한다."""
    project = stack.project("작업 PC")
    _git_repo(project)
    page = stack.page()
    _open(stack, page, project["id"])
    case_id = _run_work_with_candidate(page)

    page.click('[data-testid="settings-summary-line"]')
    page.click('[data-testid="open-case-settings"]')
    expect(page.locator('[data-testid="case-time-execution"]')).to_contain_text("합계")
    expect(page.locator('[data-testid="case-time-elapsed"]')).to_contain_text("합계")
    usage = stack.http.get(f"/api/cases/{case_id}/budget").json()["usage"]
    assert usage["execution_seconds"]["exposure"] > 0 and usage["elapsed_seconds"]["exposure"] > 0
    page.click('[data-testid="case-budget-add-time"]')
    expect(page.locator('[data-testid="case-budget-metric"]')).to_have_value("execution_seconds")
    expect(page.locator('[data-testid="case-budget-threshold"]')).to_have_value("hard")
    expect(page.locator('[data-testid="case-budget-metric-note"]')).to_contain_text("병렬")
    page.click('[data-testid="case-budget-set"]')
    row = page.locator('[data-testid="case-budget-execution_seconds-hard"]')
    expect(row).to_contain_text("실행시간 합계", timeout=15_000)
    expect(row).to_contain_text("새 배정만 차단")
    limits = [l for l in stack.http.get(f"/api/cases/{case_id}/budget").json()["limits"] if l["state"] == "current"]
    assert [(l["metric"], l["threshold_kind"], l["limit_value"], l["guarantee"]) for l in limits] == [
        ("execution_seconds", "hard", 1800.0, "no_absolute_cap"),
    ]
    expect(page.locator('[data-testid="settings-summary"]')).to_contain_text("실행시간 합계")

    page.click('[data-testid="open-results"]')
    if page.locator('[data-testid="viewer"]').count():
        page.click('[data-testid="viewer"] >> text=← 목록')  # 동의 때 연 의도 원문이 열려 있다 — 목록으로
    ws = stack.http.get(f"/api/cases/{case_id}/workspace").json()["workspaces"][0]
    repo_id = ws["repository_id"]
    assert ws["runner"]["runner_id"] == RunnerProcessId.get(stack) and ws["runner"]["host"]
    assert ws["open_support"]["open_folder"]["state"] == "unsupported"
    assert "HADS_RUNNER_DESKTOP=off" in ws["open_support"]["open_folder"]["source"]
    expect(page.locator(f'[data-testid="workspace-{repo_id}"]')).to_have_attribute("data-connection", "connected")
    expect(page.locator(f'[data-testid="ws-runner-{repo_id}"]')).to_contain_text(ws["runner"]["host"])
    expect(page.locator(f'[data-testid="ws-path-{repo_id}"]')).to_have_text(ws["worktree_path"])
    expect(page.locator(f'[data-testid="ws-copy-{repo_id}"]')).to_be_enabled()
    expect(page.locator(f'[data-testid="ws-open-folder-{repo_id}"]')).to_be_disabled()
    expect(page.locator(f'[data-testid="ws-open-editor-{repo_id}"]')).to_be_disabled()
    expect(page.locator(f'[data-testid="ws-open-support-{repo_id}"]')).to_contain_text("HADS_RUNNER_DESKTOP=off")
    # 화면의 비활성 버튼은 잠금이 아니다 — 서버가 같은 이유로 거부한다.
    refused = stack.http.post(
        f"/api/cases/{case_id}/workspaces/{repo_id}/open", json={"target": "folder", "requested_by": "owner"}
    )
    assert refused.status_code == 409 and "open_unsupported" in refused.text
    assert ws["open_requests"] == []
    # 첫 쓰기 실행은 직전 실행이 없어 외부 변경을 "모른다"(`null`) — `false` 가 아니다.
    effects = [e for e in ws["run_effects"] if e["permission"] == "workspace_write"]
    assert effects and effects[0]["external_change_before_run"] is None
    expect(page.locator(f'[data-testid="effect-{effects[0]["run_id"]}"]')).to_have_attribute("data-external", "null")
    page.context.close()


# ================================================== UI-04d 대화 검색(D-84)·미커밋 포함 시작(D-77)


def _db_has(stack: Stack, needle: str) -> bool:
    """제어부 DB 의 모든 표·모든 글 칸에 이 글이 있는가."""
    with stack.db() as conn:
        for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall():
            for row in conn.execute(f'SELECT * FROM "{table}"'):
                if any(isinstance(v, str) and needle in v for v in row):
                    return True
    return False


def test_search_finds_titles_rules_and_pc_bodies_and_leads_to_the_message(stack):
    """UI-04d AC-5 — 왼쪽 검색 → 가운데 검색 화면(범위 줄·대화별 묶음·발췌 강조). 본문 일치는 작업 PC 가 올린 뒤
    도착하고(`relayed`), 보관된 대화도 든다. 메시지 일치를 누르면 그 대화의 그 메시지가 강조되고, 규칙 일치를 누르면
    규칙 화면의 그 항목이 열린다. 검색어는 주소·DB 에 없다."""
    project = stack.project("검색")
    page = stack.page()
    _open(stack, page, project["id"])
    first = _new_conversation(page)
    _send(page, "quokka 낱말이 든 첫 메시지")
    expect(page.locator('[data-testid="message-2"] [data-testid="message-body"]')).to_contain_text("가짜 응답", timeout=60_000)
    expect(page.locator('[data-testid="send-refusal"]')).to_have_count(0, timeout=30_000)
    registered = stack.http.post(
        f"/api/cases/{first}/knowledge",
        json={
            "content": "배포 전에 lint 를 돌린다",
            "summary": "배포 전 lint 규칙",
            "kind": "constraint",
            "obligation": "required",
            "target_runner_id": RunnerProcessId.get(stack),
        },
    )
    assert registered.status_code == 201, registered.text
    rule_key = registered.json()["version"]["knowledge_key"] if "knowledge_key" in registered.json()["version"] else None
    second = _new_conversation(page)
    _send(page, "둘째 대화에도 quokka 가 있다")
    expect(page.locator('[data-testid="message-2"] [data-testid="message-body"]')).to_contain_text("가짜 응답", timeout=60_000)
    assert stack.http.post(f"/api/cases/{second}/archive", json={"actor": "owner"}).status_code == 200

    page.fill('[data-testid="search-input"]', "quokka")
    page.click('[data-testid="search-submit"]')
    screen = page.locator('[data-testid="search-screen"]')
    expect(screen).to_be_visible()
    assert "screen=search" in _address(page) and "quokka" not in _address(page)
    assert page.locator('[data-testid="review-panel"]').count() == 0
    scope = page.locator('[data-testid="search-scope"]')
    expect(scope).to_have_attribute("data-bodies", "relayed", timeout=40_000)
    expect(scope).to_contain_text("본문(PC)")
    results = page.locator('[data-testid="search-results"]')
    expect(results.locator(f'[data-testid="search-case-{first}"]')).to_be_visible()
    expect(results.locator(f'[data-testid="search-case-{second}"]')).to_contain_text("보관됨")
    hit = results.locator(f'[data-testid="search-case-{first}"] [data-kind="body"]').first
    expect(hit).to_have_attribute("data-seq", "1")
    expect(hit.locator("mark.sh-hit")).to_have_text("quokka")
    hit.click()
    page.wait_for_selector('[data-testid="conversation-title"]')
    expect(page.locator('[data-testid="message-1"]')).to_have_attribute("data-focus", "1", timeout=30_000)
    assert f"case={first}" in _address(page)

    # 규칙 일치 → 규칙 화면의 그 항목.
    page.fill('[data-testid="search-input"]', "lint 규칙")
    page.click('[data-testid="search-submit"]')
    rule_hit = page.locator('[data-testid="search-results"] [data-kind="rule"]').first
    expect(rule_hit).to_be_visible(timeout=20_000)
    rule_hit.click()
    expect(page.locator('[data-testid="rules-screen"]')).to_be_visible()
    assert "screen=rules" in _address(page)
    if rule_key:
        expect(page.locator(f'[data-testid="rule-{rule_key}"]')).to_be_visible()
    # 검색어·발췌는 DB 에 없다(본문은 PC 에만 있다).
    assert not _db_has(stack, "quokka")
    page.context.close()


def test_a_dirty_repository_asks_for_the_start_basis_and_including_keeps_the_original(stack):
    """UI-04d AC-11 — 원래 폴더에 커밋하지 않은 변경이 있으면 동의 뒤 진행기가 "어느 코드에서 시작할까" 카드(목록·기준
    커밋·두 버튼)에서 멈춘다. 포함해서 시작을 고르면 이어져 완료되고, 작업공간 절이 시작 기준(포함 2건·스냅샷·커밋 기준)을
    서버 값 그대로 보인다. 원래 폴더는 그대로이고 파일 경로는 DB 에 없다."""
    project = stack.project("미커밋 시작")
    _git_repo(project)
    repo = Path(project["repo_path"])
    (repo / "reader.py").write_text("def read(path):\n    return open(path).read()  # 사용자가 쓰던 중\n", encoding="utf-8")
    (repo / "wip-note.txt").write_text("사용자의 미추적 메모\n", encoding="utf-8")
    status = lambda: subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True, check=True).stdout  # noqa: E731
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()
    before = status()

    page = stack.page()
    _open(stack, page, project["id"])
    case_id = _new_conversation(page)
    _send(page, "HADS_FAKE_WORK=feature HADS_FAKE_NO_QUESTION HADS_FAKE_CANDIDATE 필터를 구현해줘")
    expect(page.locator('[data-testid="agreement-card"]')).to_be_visible(timeout=60_000)
    page.click('[data-testid="agreement-open"]')
    expect(page.locator('[data-testid="agreement-agree"]')).to_be_enabled(timeout=30_000)
    page.click('[data-testid="agreement-agree"]')

    card = page.locator('[data-testid="wait-card-workspace_start_basis"]')
    expect(card).to_be_visible(timeout=90_000)
    expect(card).to_have_attribute("data-available", "true", timeout=15_000)
    expect(card.locator('[data-testid="basis-count"]')).to_have_text("2")
    expect(card.locator('[data-testid="basis-entries"]')).to_contain_text("wip-note.txt")
    expect(card.locator('[data-testid="basis-entries"]')).to_contain_text("reader.py")
    expect(card).to_contain_text(head[:10])
    expect(page.locator('[data-testid="work-stage-banner"]')).to_have_attribute("data-progress", "waiting_human")
    ws = stack.http.get(f"/api/cases/{case_id}/workspace").json()["workspaces"][0]
    assert ws["state"] == "awaiting_basis" and ws["basis_entries"] == 2 and ws["start_basis"] is None
    assert status() == before  # 원래 폴더는 그대로
    assert not _db_has(stack, "wip-note.txt")

    card.locator('[data-testid="basis-include"]').click()
    expect(page.locator('[data-testid="work-stage-banner"]')).to_have_attribute("data-progress", "done", timeout=120_000)
    ws = stack.http.get(f"/api/cases/{case_id}/workspace").json()["workspaces"][0]
    assert (ws["state"], ws["start_basis"], ws["included_entries"], ws["basis_decided_by"]) == ("ready", "include_uncommitted", 2, "owner")
    assert ws["committed_base"] == head and ws["base_commit"] != head
    assert status() == before and "사용자가 쓰던 중" in (repo / "reader.py").read_text(encoding="utf-8")
    # 스냅샷 커밋(시작 상태)에는 사용자의 수정이 있고, 그 위에서 AI 구현이 `reader.py` 를 고쳤다(그것이 이 실행의 변경이다).
    snapshot_reader = subprocess.run(
        ["git", "show", f"{ws['base_commit']}:reader.py"], cwd=repo, capture_output=True, text=True, check=True, encoding="utf-8"
    ).stdout
    assert "사용자가 쓰던 중" in snapshot_reader
    assert (Path(ws["worktree_path"]) / "wip-note.txt").read_text(encoding="utf-8") == "사용자의 미추적 메모\n"
    assert not _db_has(stack, "wip-note.txt")

    # 결과물 패널은 동의 때(`agreement-open`) 이미 열려 있을 수 있다 — `open-results` 는 토글이라 그때 누르면 닫힌다.
    if not page.locator('[data-testid="result-list"], [data-testid="viewer"]').count():
        page.click('[data-testid="open-results"]')
    expect(page.locator('[data-testid="review-panel"]')).to_be_visible()
    if page.locator('[data-testid="viewer"]').count():
        page.click('[data-testid="viewer"] >> text=← 목록')  # 동의 때 연 의도 원문이 열려 있다 — 목록으로
    expect(page.locator('[data-testid="result-list"]')).to_be_visible()
    basis = page.locator(f'[data-testid="ws-basis-{ws["repository_id"]}"]')
    expect(basis).to_have_attribute("data-basis", "include_uncommitted")
    expect(basis).to_contain_text("포함해 시작")
    expect(basis).to_contain_text("2건")
    expect(basis).to_contain_text(ws["base_commit"][:10])
    page.context.close()


# ================================================== P4-09 — P5 전 정리 묶음(취소 · 거부 후보 열람 · 제목)


def test_a_conversation_gets_a_title_from_the_reply_and_a_person_renames_it_in_the_header_and_the_list(stack):
    """P4-09(g) AC-33 — 첫 응답이 낸 제목이 머리·목록에 보이고, 머리에서 바꾼 제목은 다음 응답이 덮지 않으며, 목록의
    ✎ 로도 바꾼다(D-93). 제목은 표시값이다."""
    project = stack.project("제목")
    page = stack.page()
    _open(stack, page, project["id"])
    case_id = _new_conversation(page)
    expect(page.locator('[data-testid="conversation-title"]')).to_have_text("새 대화")
    _send(page, "HADS_FAKE_TITLE=저장 뒤 목록 문제\n저장하면 목록이 옛 값을 보여요")
    title = page.locator('[data-testid="conversation-title"]')
    expect(title).to_have_text("저장 뒤 목록 문제", timeout=60_000)
    expect(title).to_have_attribute("data-title-source", "ai")
    row = page.locator(f'[data-testid="conversation-row-{case_id}"]')
    expect(row).to_contain_text("저장 뒤 목록 문제", timeout=15_000)
    conv = stack.http.get(f"/api/cases/{case_id}/conversation").json()
    assert (conv["title"], conv["title_source"], conv["title_set_by"]) == ("저장 뒤 목록 문제", "ai", "ai:discussion")

    # 머리에서 바꾼다 — 그 뒤 응답의 제목은 덮지 않는다.
    title.click()
    page.fill('[data-testid="title-input"]', "내가 정한 제목")
    page.click('[data-testid="title-save"]')
    expect(page.locator('[data-testid="conversation-title"]')).to_have_text("내가 정한 제목", timeout=15_000)
    expect(page.locator('[data-testid="conversation-title"]')).to_have_attribute("data-title-source", "user")
    expect(row).to_contain_text("내가 정한 제목", timeout=15_000)
    expect(page.locator('[data-testid="send-refusal"]')).to_have_count(0, timeout=30_000)
    _send(page, "HADS_FAKE_TITLE=AI 가 다시 붙인 제목\n왜 그럴까요?")
    expect(page.locator('article[data-author="assistant"]')).to_have_count(2, timeout=60_000)
    expect(page.locator('[data-testid="conversation-title"]')).to_have_text("내가 정한 제목")
    conv = stack.http.get(f"/api/cases/{case_id}/conversation").json()
    assert conv["title_source"] == "user" and conv["title_previous"] == "저장 뒤 목록 문제"

    # 목록의 ✎ 로도 바꾼다.
    page.click(f'[data-testid="rename-{case_id}"]')
    page.fill(f'[data-testid="rename-input-{case_id}"]', "목록에서 바꾼 제목")
    page.click(f'[data-testid="rename-save-{case_id}"]')
    expect(page.locator(f'[data-testid="conversation-row-{case_id}"]')).to_contain_text("목록에서 바꾼 제목", timeout=15_000)
    expect(page.locator('[data-testid="conversation-title"]')).to_have_text("목록에서 바꾼 제목", timeout=15_000)
    page.context.close()


def test_a_waiting_case_is_cancelled_from_the_header_with_a_reason(stack):
    """P4-09(e) AC-20 — 동의 카드(실행 없음)에서 '업무 취소' → 사유 → 확정 → 머리·목록이 취소됨을 보이고 버튼이 사라진다.
    취소는 종료지만 성공·예외 인수가 아니다(D-33 그대로 되돌리지 않는다)."""
    project = stack.project("취소")
    _git_repo(project)
    page = stack.page()
    _open(stack, page, project["id"])
    case_id = _new_conversation(page)
    _send(page, "HADS_FAKE_WORK=feature HADS_FAKE_NO_QUESTION 필터를 구현해줘")
    expect(page.locator('[data-testid="agreement-card"]')).to_be_visible(timeout=60_000)
    conv = stack.http.get(f"/api/cases/{case_id}/conversation").json()
    assert conv["progress"]["state"] == "waiting_human"

    page.click('[data-testid="cancel-case"]')
    expect(page.locator('[data-testid="cancel-confirm"]')).to_be_disabled()  # 사유 없이는 확정할 수 없다
    page.fill('[data-testid="cancel-reason"]', "방향이 바뀌어 이 업무는 버린다")
    page.click('[data-testid="cancel-confirm"]')
    expect(page.locator('[data-testid="cancelled-label"]')).to_contain_text("취소됨", timeout=15_000)
    expect(page.locator('[data-testid="cancelled-label"]')).to_contain_text("방향이 바뀌어")
    expect(page.locator('[data-testid="cancel-case"]')).to_have_count(0)
    expect(page.locator(f'[data-testid="conversation-row-{case_id}"]')).to_contain_text("취소됨", timeout=15_000)
    expect(page.locator('[data-testid="agreement-card"]')).to_have_count(0)
    case = stack.http.get(f"/api/cases/{case_id}").json()
    assert case["status"] == "cancelled"
    closure = case["result"]["closure"]
    assert (closure["closure_kind"], closure["candidate_id"], closure["cancelled_by"]) == ("cancelled", None, "owner")
    conv = stack.http.get(f"/api/cases/{case_id}/conversation").json()
    assert conv["cancellation"]["reason"] == "방향이 바뀌어 이 업무는 버린다"
    assert conv["progress"]["state"] == "done" and conv["progress"]["step"] == "cancelled"
    page.context.close()


def test_a_refused_candidate_shows_its_content_and_fills_the_manual_registration_form(stack):
    """P4-09(f) AC-26 — 사용자 말의 자동 등록이 범위 때문에 거부되면 카드가 읽을 말로 사유를 보이고, '내용 보기' 가
    본문·AI 가 적은 활동을 보이며, '이 내용으로 수동 등록' 이 규칙 화면의 폼을 그 내용으로 채운다(D-92)."""
    project = stack.project("거부 열람")
    page = stack.page()
    _open(stack, page, project["id"])
    case_id = _new_conversation(page)
    _send(page, "HADS_FAKE_RULE_BADSCOPE 이 프로젝트에서는 앞으로 읽기 전용 실행에서 adb 조회를 하지 마")
    card = page.locator('[data-testid="knowledge-refused-card"]')
    expect(card).to_be_visible(timeout=60_000)
    expect(card).to_contain_text("범위(활동·경로)를 알아볼 수 없다")
    conv = stack.http.get(f"/api/cases/{case_id}/conversation").json()
    [row] = conv["knowledge_registrations"]
    assert (row["intake_state"], row["refusal"]) == ("refused", "invalid_scope")

    card.locator('[data-testid="knowledge-refused-open-0"]').click()
    body = card.locator('[data-testid="knowledge-refused-body-0"]')
    expect(body).to_be_visible(timeout=15_000)
    expect(body.locator('[data-testid="knowledge-refused-activities-0"]')).to_have_text("기기 확인")
    expect(body.locator('[data-testid="knowledge-refused-content-0"]')).to_contain_text("adb 조회를 하지 마")
    card.locator('[data-testid="knowledge-refused-register-0"]').click()
    form = page.locator('[data-testid="rules-register-form"]')
    expect(form).to_be_visible(timeout=30_000)
    expect(form).to_have_attribute("data-prefilled", "1")
    expect(form.locator('[data-testid="rules-register-content"]')).to_have_value(
        "이 프로젝트에서는 앞으로 읽기 전용 실행에서 adb 조회를 하지 마"
    )
    expect(form.locator('[data-testid="rules-register-summary"]')).to_have_value("대화에서 정한 규칙")
    expect(form.locator('[data-testid="rules-register-activities"]')).to_have_value("기기 확인")
    expect(form.locator('[data-testid="rules-register-case"]')).to_have_value(case_id)
    # 사람이 활동을 고쳐 등록한다 — 권위는 등록하는 사람이다.
    form.locator('[data-testid="rules-register-activities"]').fill("investigation")
    form.locator('[data-testid="rules-register"]').click()
    expect(form.locator('[data-testid="rules-register-done"]')).to_contain_text("K-001 v1", timeout=15_000)
    view = stack.http.get(f"/api/projects/{project['id']}/knowledge").json()
    current = view["items"][0]["current"]
    assert (current["authority_kind"], current["state"], current["activities"]) == ("user_registration", "active", ["investigation"])
    page.context.close()


# ================================================== UI-05a 작업 탭 (이슈 #7)


def test_the_work_tab_links_a_blocking_question_edits_the_graph_and_shows_a_run(stack):
    """UI-PLAN-05a AC-2·3·4·6·7·8 — 관리 화면에만 있던 작업 그래프·실행 상세를 새 화면 `작업` 탭에서 쓴다.

    연결 없는 계획 질문이 모든 작업을 막은 업무에서, 질문 카드의 `기다리는 작업 고치기` → 작업 탭에서 질문을 T2 에만
    연결하면(이유 필수, 답이 아니다) `다시 시도` 없이 T1 구현이 돈다. 그 구현 실행의 상세(고정 입력·이벤트·작업공간 효과·
    출력 열기)를 진행 이력의 실행 id 로 연다. 작업을 더하고 취소하면(이유 필수) 새 리비전으로 남는다. 종료된 업무는 보기만 한다.
    """
    project = stack.project("작업 탭")
    _git_repo(project)
    page = stack.page()
    _open(stack, page, project["id"])
    case_id = _new_conversation(page)
    _send(page, "HADS_FAKE_WORK=feature HADS_FAKE_NO_QUESTION HADS_FAKE_PLAN_QUESTION 필터를 구현해줘")
    expect(page.locator('[data-testid="agreement-card"]')).to_be_visible(timeout=60_000)
    page.click('[data-testid="agreement-open"]')
    expect(page.locator('[data-testid="agreement-agree"]')).to_be_enabled(timeout=30_000)
    page.click('[data-testid="agreement-agree"]')

    # 결합 기록의 연결 없는 질문이 전부 막는다 — 질문 카드가 그 사실과 고치는 길을 보인다.
    blocks = page.locator('[data-testid="question-blocks-combined:d1"]')
    expect(blocks).to_contain_text("모든 작업을 막는다", timeout=120_000)
    [question] = stack.http.get(f"/api/cases/{case_id}/work-graph").json()["deferred_open_questions"]
    page.click('[data-testid="question-blocks-edit-combined:d1"]')
    panel = page.locator('[data-testid="work-panel"]')
    expect(panel.locator('[data-testid="work-graph"]')).to_have_attribute("data-revision", "1")
    expect(panel.locator('[data-testid="work-graph-unlinked"]')).to_contain_text("combined:d1")
    expect(panel.locator('[data-testid="work-task-T1"]')).to_have_attribute("data-runnable", "false")
    expect(panel.locator('[data-testid="work-task-blocked-T1"]')).to_contain_text("사람 결정 대기")

    # 이유 없이 저장할 수 없다(버튼) — 적으면 저장된다.
    page.click('[data-testid="work-question-edit-combined:d1"]')
    page.check('[data-testid="work-question-task-combined:d1-T2"]')
    expect(page.locator('[data-testid="work-question-submit-combined:d1"]')).to_be_disabled()
    page.fill('[data-testid="work-question-reason-combined:d1"]', "출력 형식은 검증 작업만 기다린다")
    page.click('[data-testid="work-question-submit-combined:d1"]')
    expect(panel.locator('[data-testid="work-question-combined:d1"]')).to_have_attribute("data-blocks", "T2")
    graph = stack.http.get(f"/api/cases/{case_id}/work-graph").json()
    assert graph["question_blocks"] == {question["id"]: ["T2"]}
    assert graph["deferred_open_questions"][0]["state"] == "open"  # 연결은 답이 아니다

    # 사람이 `다시 시도` 를 누르지 않았는데 T1 이 돈다(진행기가 연결 저장 때 봤다). T2 는 계속 그 결정을 기다린다.
    expect(panel.locator('[data-testid="work-task-T1"]')).to_have_attribute("data-state", "done", timeout=120_000)
    expect(panel.locator('[data-testid="work-task-blocked-T2"]')).to_contain_text("사람 결정 대기")
    runs = stack.http.get(f"/api/cases/{case_id}").json()["runs"]
    [impl] = [r for r in runs if r["purpose"] == "feature_implementation"]
    assert impl["outcome"] == "completed"

    # 진행 이력의 실행 id → 작업 탭의 그 실행 상세.
    page.click('[data-testid="open-decisions"]')
    page.locator('[data-testid="progress-events"]').get_by_role("button", name=impl["run_id"]).first.click()
    detail = page.locator('[data-testid="run-detail"]')
    expect(detail).to_have_attribute("data-run-id", impl["run_id"])
    expect(detail.locator('[data-testid="run-detail-basics"]')).to_contain_text("구현")
    expect(detail.locator('[data-testid="run-detail-refs"]')).to_contain_text("동의된 의도 원문")
    expect(detail.locator('[data-testid="run-detail-ref-agreed_intent"]')).to_contain_text("읽음")
    assert int(detail.locator('[data-testid="run-detail-events"]').get_attribute("data-count")) > 0
    expect(detail.locator('[data-testid="run-detail-workspace"]')).to_contain_text("이 실행이 바꿨다")
    refs = stack.http.get(f"/api/runs/{impl['run_id']}/context-refs").json()
    assert len(detail.locator('[data-testid="run-detail-refs"] li').all()) == len(refs)
    # 출력 원문은 결과물 뷰어가 PC 에서 불러온다.
    page.click('[data-testid="run-detail-open-output"]')
    expect(page.locator('[data-testid="viewer-body"]')).to_contain_text("구현했습니다", timeout=30_000)

    # 작업 탭으로 돌아오면 목록부터(지난 실행을 다시 열지 않는다). 작업 추가 → 취소, 둘 다 이유가 남는다.
    page.click('[data-testid="panel-tab-work"]')
    expect(panel.locator('[data-testid="work-runs"]')).to_be_visible()
    page.click('[data-testid="work-add-open"]')
    page.fill('[data-testid="work-add-key"]', "T3")
    page.select_option('[data-testid="work-add-kind"]', "verification")
    page.fill('[data-testid="work-add-summary"]', "빈 파일 경계 시험")
    # T2(결정 대기) 뒤에 둔다 — 막히지 않은 작업을 더하면 진행기가 그 자리에서 실행을 연다(연결 저장 때와 같다).
    page.check('[data-testid="work-add-dep-T2"]')
    expect(page.locator('[data-testid="work-add-submit"]')).to_be_disabled()
    page.fill('[data-testid="work-add-reason"]', "빈 파일 경계를 따로 확인한다")
    page.click('[data-testid="work-add-submit"]')
    expect(panel.locator('[data-testid="work-task-T3"]')).to_have_attribute("data-cancelled", "false")
    expect(panel.locator('[data-testid="work-task-blocked-T3"]')).to_contain_text("선행 작업 미완료")
    page.click('[data-testid="work-task-cancel-T3"]')
    page.fill('[data-testid="work-task-cancel-reason-T3"]', "T2 가 이미 덮는다")
    page.click('[data-testid="work-task-cancel-submit-T3"]')
    expect(panel.locator('[data-testid="work-task-cancelled-T3"]')).to_contain_text("T2 가 이미 덮는다")
    revisions = stack.http.get(f"/api/cases/{case_id}/work-graph-revisions").json()
    reasons = {r["revision"]: r["reason_summary"] for r in revisions}
    top = max(reasons)
    assert [reasons[top - 1], reasons[top]] == ["빈 파일 경계를 따로 확인한다", "T2 가 이미 덮는다"]
    assert reasons[2] == "출력 형식은 검증 작업만 기다린다"

    # 업무를 취소하면(종료) 작업 탭은 보기만 한다 — 폼이 없다(서버도 거부한다, tests/test_work_graph_edit.py).
    response = stack.http.post(f"/api/cases/{case_id}/cancel", json={"actor": "owner", "reason": "시험을 끝낸다"})
    assert response.status_code == 200, response.text
    page.reload()
    page.wait_for_selector('[data-testid="sidebar"]')
    page.click('[data-testid="open-work"]')
    expect(page.locator('[data-testid="work-closed"]')).to_be_visible(timeout=15_000)
    expect(page.locator('[data-testid="work-add-open"]')).to_have_count(0)
    expect(page.locator('[data-testid="work-task-cancel-T1"]')).to_have_count(0)
    page.context.close()


def test_an_explicit_quality_gate_is_reviewed_by_itself_and_the_card_raises_the_limit_or_turns_it_off(stack):
    """UI-PLAN-05a AC-9·11 (D-94) — 사람이 QG-04 를 켜면(수정 한도 0) 진행기가 검증 전에 별도 세션 검토를 스스로 만든다.
    검토가 실패하면 `quality_gate` 카드가 판정·지적·수정 0/0 을 보인다. 카드에서 한도를 올리면(사유) 한 번 더 고치고
    다시 멈추며(1/1), 게이트를 끄면(사유) 검증이 이어져 끝난다. 관리 화면을 거치지 않는다.
    """
    project = stack.project("게이트 카드")
    _git_repo(project)
    page = stack.page()
    _open(stack, page, project["id"])
    case_id = _new_conversation(page)
    _send(page, "HADS_FAKE_WORK=feature HADS_FAKE_NO_QUESTION HADS_FAKE_GATE_FAIL 필터를 구현해줘")
    expect(page.locator('[data-testid="agreement-card"]')).to_be_visible(timeout=60_000)
    response = stack.http.put(
        f"/api/cases/{case_id}/quality-gates/QG-04/policy",
        json={"task_key": "", "setting": "on", "inspection": None, "repair_limit": 0, "actor": "owner",
              "reason_summary": "구현 묶음을 따로 검토한다"},
    )
    assert response.status_code == 200, response.text
    page.click('[data-testid="agreement-open"]')
    expect(page.locator('[data-testid="agreement-agree"]')).to_be_enabled(timeout=30_000)
    page.click('[data-testid="agreement-agree"]')

    card = page.locator('[data-testid="wait-card-quality_gate"]')
    expect(card).to_be_visible(timeout=120_000)
    expect(card).to_have_attribute("data-verdict", "fail")
    expect(card.locator('[data-testid="quality-gate-usage"]')).to_contain_text("수정 0/0")
    expect(card.locator('[data-testid="quality-gate-findings"]')).to_contain_text("GATE-FAIL-MARK")
    runs = stack.http.get(f"/api/cases/{case_id}").json()["runs"]
    [review] = [r for r in runs if r["purpose"] == "quality_gate_review"]
    assert review["task_id"] == "qg:QG-04:T2" and review["outcome"] == "completed"
    assert not [r for r in runs if r["purpose"] == "verification_run"]

    # 사유 없이는 누를 수 없다. 한도를 올리면 한 번 더 고친다(가짜 구현은 같은 내용이라 바뀐 것이 없다 — 대상이 그대로이므로
    # 다시 검토하지 않고 1/1 에서 멈춘다).
    expect(card.locator('[data-testid="quality-gate-raise"]')).to_be_disabled()
    card.locator('[data-testid="quality-gate-reason"]').fill("한 번 더 고쳐 본다")
    card.locator('[data-testid="quality-gate-raise"]').click()
    expect(page.locator('[data-testid="wait-card-quality_gate"] [data-testid="quality-gate-usage"]')).to_contain_text(
        "수정 1/1", timeout=120_000
    )
    impl = [r for r in stack.http.get(f"/api/cases/{case_id}").json()["runs"] if r["purpose"] == "feature_implementation"]
    assert len(impl) == 2

    # 끄면(사유) 검증이 이어져 끝난다. 끄는 것은 통과가 아니다 — 게이트의 실패 판정은 기록에 남는다.
    card = page.locator('[data-testid="wait-card-quality_gate"]')
    card.locator('[data-testid="quality-gate-reason"]').fill("검증 실행으로 확인한다")
    card.locator('[data-testid="quality-gate-off"]').click()
    expect(page.locator('[data-testid="work-stage-banner"]')).to_have_attribute("data-progress", "done", timeout=120_000)
    gates = stack.http.get(f"/api/cases/{case_id}/quality-gates", params={"task_key": "T2"}).json()["gates"]
    qg04 = next(g for g in gates if g["gate"] == "QG-04")
    assert qg04["setting"] == "off" and qg04["latest_run"]["verdict"] == "fail"
    page.context.close()


def test_a_timed_out_verification_waits_on_a_card_and_a_longer_limit_finishes_the_work(stack):
    """P4-PLAN-10 AC-10 (이슈 #8, D-95) — 제한 시간(이 업무 20초)에 걸린 검증은 실패가 아니라 시간 초과로 기록되고, 진행기가
    같은 제한으로 다시 돌리지 않고 `run_timed_out` 카드에서 멈춘다. 카드에서 끊긴 실행의 상세를 보고(시간 초과·제한),
    제한을 늘리면(분) 그 검증이 새 제한으로 다시 돌아 업무가 끝난다. 가짜 codex 는 그 작업 디렉터리의 첫 검증만 잔다.
    """
    project = stack.project("시간 초과")
    _git_repo(project)
    page = stack.page()
    _open(stack, page, project["id"])
    case_id = _new_conversation(page)
    _send(page, "HADS_FAKE_WORK=feature HADS_FAKE_NO_QUESTION HADS_FAKE_SLOW_VERIFY=60 필터를 구현해줘")
    expect(page.locator('[data-testid="agreement-card"]')).to_be_visible(timeout=60_000)
    response = stack.http.put(
        f"/api/cases/{case_id}/progress/limits",
        json={"run_timeout_seconds": 20, "reason_summary": "시험: 짧은 제한"},
    )
    assert response.status_code == 200, response.text
    page.click('[data-testid="agreement-open"]')
    expect(page.locator('[data-testid="agreement-agree"]')).to_be_enabled(timeout=30_000)
    page.click('[data-testid="agreement-agree"]')

    card = page.locator('[data-testid="wait-card-run_timed_out"]')
    expect(card).to_be_visible(timeout=180_000)
    expect(card.locator('[data-testid="timeout-usage"]')).to_contain_text("작업 T2")
    expect(card.locator('[data-testid="timeout-usage"]')).to_contain_text("20초")
    runs = stack.http.get(f"/api/cases/{case_id}").json()["runs"]
    [cut] = [r for r in runs if r["purpose"] == "verification_run"]
    assert (cut["outcome"], cut["stop_reason"], cut["timeout_seconds"]) == ("unknown", "timeout", 20)
    assert card.get_attribute("data-run-id") == cut["run_id"]

    # 끊긴 실행의 상세 — 작업 탭에서 시간 초과와 적용 제한을 본다.
    card.locator('[data-testid="timeout-open-run"]').click()
    detail = page.locator('[data-testid="run-detail"]')
    expect(detail).to_have_attribute("data-run-id", cut["run_id"], timeout=20_000)
    expect(detail.locator('[data-testid="run-detail-timeout"]')).to_have_attribute("data-stop-reason", "timeout")
    expect(detail.locator('[data-testid="run-detail-timeout"]')).to_contain_text("시간 초과")

    # 제한을 늘려(2분) 다시 시도 → 검증이 새 제한으로 다시 돌고 업무가 끝난다.
    card = page.locator('[data-testid="wait-card-run_timed_out"]')
    card.locator('[data-testid="timeout-minutes"]').fill("2")
    card.locator('[data-testid="timeout-raise"]').click()
    expect(page.locator('[data-testid="work-stage-banner"]')).to_have_attribute("data-progress", "done", timeout=120_000)
    case = stack.http.get(f"/api/cases/{case_id}").json()
    assert case["result"]["closure"]["closure_kind"] == "completed"
    verify = [r for r in reversed(case["runs"]) if r["purpose"] == "verification_run"]
    assert [(r["outcome"], r["timeout_seconds"]) for r in verify] == [("unknown", 20), ("completed", 120)]
    history = stack.http.get(f"/api/cases/{case_id}/progress").json()["limits"]["history"]
    assert [(r["limit_key"], r["limit_value"]) for r in history] == [("run_timeout_seconds", 20), ("run_timeout_seconds", 120)]
    page.context.close()


def test_a_not_met_verification_is_fixed_and_reverified_by_the_progressor_and_the_card_raises_a_zero_limit(stack):
    """P4-PLAN-10 AC-11 (이슈 #9) — 검증이 근거와 함께 C-02 미충족을 보고하면 사람 없이 수정 구현(FIX1)·재검증(REVERIFY1)이
    작업 그래프 새 리비전(진행기 수정 사이클)으로 더해져 돌고 업무가 끝난다. 작업 탭에 그 리비전 출처와 작업이 보인다.
    수정 한도가 0 인 업무는 미충족 카드가 사이클 정보(끔 0/0)를 보이고, 카드에서 한도를 올리면 이어 가 끝난다.
    """
    project = stack.project("수정 사이클")
    _git_repo(project)
    page = stack.page()
    _open(stack, page, project["id"])
    case_id = _new_conversation(page)
    _send(page, "HADS_FAKE_WORK=feature HADS_FAKE_NO_QUESTION HADS_FAKE_VERIFY_NOT_MET 필터를 구현해줘")
    expect(page.locator('[data-testid="agreement-card"]')).to_be_visible(timeout=60_000)
    page.click('[data-testid="agreement-open"]')
    expect(page.locator('[data-testid="agreement-agree"]')).to_be_enabled(timeout=30_000)
    page.click('[data-testid="agreement-agree"]')
    expect(page.locator('[data-testid="work-stage-banner"]')).to_have_attribute("data-progress", "done", timeout=180_000)
    case = stack.http.get(f"/api/cases/{case_id}").json()
    assert case["result"]["closure"]["closure_kind"] == "completed"
    tasks = [r["task_id"] for r in reversed(case["runs"]) if r["purpose"] in ("feature_implementation", "verification_run")]
    assert tasks == ["T1", "T2", "FIX1", "REVERIFY1"]
    page.click('[data-testid="open-work"]')
    graph = page.locator('[data-testid="work-graph"]')
    expect(graph).to_contain_text("진행기 수정 사이클", timeout=20_000)
    expect(graph.locator('[data-testid="work-task-FIX1"]')).to_be_visible()
    expect(graph.locator('[data-testid="work-task-REVERIFY1"]')).to_be_visible()

    # 한도 0 인 업무 — 카드가 사이클 정보를 보이고, 올리면 이어 간다.
    page2 = stack.page()
    _open(stack, page2, project["id"])
    case2 = _new_conversation(page2)
    _send(page2, "HADS_FAKE_WORK=feature HADS_FAKE_NO_QUESTION HADS_FAKE_VERIFY_NOT_MET 경로 처리도 구현해줘")
    expect(page2.locator('[data-testid="agreement-card"]')).to_be_visible(timeout=60_000)
    response = stack.http.put(f"/api/cases/{case2}/progress/limits", json={"remediation_limit": 0})
    assert response.status_code == 200, response.text
    page2.click('[data-testid="agreement-open"]')
    expect(page2.locator('[data-testid="agreement-agree"]')).to_be_enabled(timeout=30_000)
    page2.click('[data-testid="agreement-agree"]')
    card = page2.locator('[data-testid="exception-card"]')
    expect(card).to_be_visible(timeout=180_000)
    info = card.locator('[data-testid="remediation-info"]')
    expect(info).to_have_attribute("data-status", "off")
    expect(info.locator('[data-testid="remediation-usage"]')).to_contain_text("0/0")
    info.locator('[data-testid="remediation-raise"]').click()
    expect(page2.locator('[data-testid="work-stage-banner"]')).to_have_attribute("data-progress", "done", timeout=180_000)
    runs2 = [r["task_id"] for r in reversed(stack.http.get(f"/api/cases/{case2}").json()["runs"])
             if r["purpose"] in ("feature_implementation", "verification_run")]
    assert runs2 == ["T1", "T2", "FIX1", "REVERIFY1"]
    page.context.close()
    page2.context.close()


def test_a_read_only_run_that_changes_the_folder_shows_a_banner_not_a_failure(stack):
    """P4-PLAN-10b AC-6 (D-96) — 권한 확인을 건너뛰는 CLI 의 읽기 전용 실행(논의 응답)이 원래 저장소에 파일을 쓰면, 응답은 그대로
    대화에 붙고(실패 아님) 대화 화면에 배너가 뜬다. 배너에서 그 실행의 상세로 가면 "바뀜" 이 보인다. 목록 행에도 배지가 있다.
    """
    project = stack.project("읽기 전용 변경")
    _git_repo(project)
    page = stack.page()
    _open(stack, page, project["id"])
    case_id = _new_conversation(page)
    _send(page, "HADS_FAKE_RO_WRITE 이 저장소 구조를 설명해줘")
    expect(page.locator('article[data-author="assistant"]').last).to_contain_text("가짜 응답입니다", timeout=60_000)
    banner = page.locator('[data-testid="read-only-change-banner"]')
    expect(banner).to_be_visible(timeout=30_000)
    expect(banner).to_contain_text("실패로 표시하지 않았다")
    [run] = [r for r in stack.http.get(f"/api/cases/{case_id}").json()["runs"] if r["purpose"] == "discussion_reply"]
    assert run["outcome"] == "completed" and run["read_only_change"]["changed"] is True
    assert run["read_only_change"]["where"] == ["original_repo"]
    rows = stack.http.get(f"/api/projects/{project['id']}/conversations").json()
    row = next(r for r in (rows["conversations"] if isinstance(rows, dict) else rows) if r["id"] == case_id)
    assert row["read_only_changes"] == 1
    banner.locator(f'[data-testid="read-only-change-{run["run_id"]}"]').click()
    detail = page.locator('[data-testid="run-detail"]')
    expect(detail).to_have_attribute("data-run-id", run["run_id"], timeout=20_000)
    expect(detail.locator('[data-testid="run-detail-read-only"]')).to_have_attribute("data-changed", "true")
    page.context.close()


def test_a_work_closed_by_its_criteria_shows_the_task_it_did_not_run(stack):
    """P4-PLAN-10c AC-3 (D-97) — 기준에 이어지지 않은 작업 T3 이 있는 계획에서 기준이 모두 충족되면 업무가 닫히고(T3 을 돌리지
    않는다), 진행 배너가 "완료하지 않은 작업 T3" 을, 작업 탭이 T3 의 "완료하지 않고 종료" 를 보인다.
    """
    project = stack.project("남은 작업")
    _git_repo(project)
    page = stack.page()
    _open(stack, page, project["id"])
    case_id = _new_conversation(page)
    _send(page, "HADS_FAKE_WORK=feature HADS_FAKE_NO_QUESTION HADS_FAKE_EXTRA_TASK 필터를 구현해줘")
    expect(page.locator('[data-testid="agreement-card"]')).to_be_visible(timeout=60_000)
    page.click('[data-testid="agreement-open"]')
    expect(page.locator('[data-testid="agreement-agree"]')).to_be_enabled(timeout=30_000)
    page.click('[data-testid="agreement-agree"]')
    expect(page.locator('[data-testid="work-stage-banner"]')).to_have_attribute("data-progress", "done", timeout=120_000)
    unrun = page.locator('[data-testid="unrun-tasks"]')
    expect(unrun).to_contain_text("완료하지 않은 작업 T3", timeout=20_000)
    expect(unrun).to_contain_text("기준을 모두 충족해 종료")
    runs = stack.http.get(f"/api/cases/{case_id}").json()["runs"]
    assert not [r for r in runs if r["task_id"] == "T3"]
    page.click('[data-testid="open-work"]')
    expect(page.locator('[data-testid="work-task-not-run-T3"]')).to_contain_text("완료하지 않고 종료", timeout=20_000)
    page.context.close()



def test_unknown_runs_are_superseded_or_confirmed_on_a_card_and_the_work_closes(stack):
    """P4-PLAN-10d AC-7 (이슈 #10, D-98) — 검증의 첫 시도가 결과 모름(`unknown`)으로 끝나고 재시도가 완료하면 앞 시도는
    대체돼 종료를 막지 않는다(작업 탭에 `대체됨`). 업무 단계의 논의 응답 하나가 결과 모름으로 끝나면(재시도가 없는 실행)
    진행은 "처리 중" 으로 남지 않고 `unsettled_runs` 카드에서 멈춘다. 카드에서 작업공간 영향 확인 표시 + 사유로 확인하면
    업무가 끝난다. 실제 Edge·실제 Runner·가짜 codex(실제 프로세스 트리).
    """
    project = stack.project("결과 모름")
    _git_repo(project)
    page = stack.page()
    _open(stack, page, project["id"])
    case_id = _new_conversation(page)
    _send(page, "HADS_FAKE_WORK=feature HADS_FAKE_NO_QUESTION HADS_FAKE_VERIFY_UNKNOWN 필터를 구현해줘")
    expect(page.locator('[data-testid="agreement-card"]')).to_be_visible(timeout=60_000)

    # 업무 단계의 질문 하나 — 그 응답이 결과를 남기지 않고 끝난다(재시도 없는 실행).
    _send(page, "HADS_FAKE_REPLY_UNKNOWN 진행 전에 하나만 묻자")

    def reply_unknown() -> Any:
        runs = stack.http.get(f"/api/cases/{case_id}").json()["runs"]
        done = [r for r in runs if r["purpose"] == "discussion_reply" and r["outcome"] == "unknown"]
        busy = [r for r in runs if r["status"] != "finished"]
        return done[0] if done and not busy else None

    reply = _wait(reply_unknown, 60, "결과 모름 논의 응답")
    page.click('[data-testid="agreement-open"]')
    expect(page.locator('[data-testid="agreement-agree"]')).to_be_enabled(timeout=30_000)
    page.click('[data-testid="agreement-agree"]')

    card = page.locator('[data-testid="wait-card-unsettled_runs"]')
    expect(card).to_be_visible(timeout=180_000)
    expect(card).to_have_attribute("data-count", "1")
    row = card.locator(f'[data-testid="unsettled-run-{reply["run_id"]}"]')
    expect(row).to_have_attribute("data-confirmable", "true")
    # 요청은 "처리 중" 으로 남지 않는다.
    requests = stack.http.get(f"/api/cases/{case_id}/conversation").json()["requests"]
    assert not [r for r in requests if r["state"] == "processing"], requests
    case = stack.http.get(f"/api/cases/{case_id}").json()
    verify = [r for r in reversed(case["runs"]) if r["purpose"] == "verification_run"]
    assert [r["outcome"] for r in verify] == ["unknown", "completed"]
    assert verify[0]["unknown_settlement"] == {"kind": "superseded", "by_run_id": verify[1]["run_id"]}

    # 작업 탭 — 대체된 검증 시도가 표시된다.
    page.click('[data-testid="open-work"]')
    expect(page.locator(f'[data-testid="work-run-settled-{verify[0]["run_id"]}"]')).to_have_attribute(
        "data-kind", "superseded", timeout=20_000
    )

    # 카드에서 확인 — 표시와 사유가 있어야 버튼이 열린다.
    card = page.locator('[data-testid="wait-card-unsettled_runs"]')
    confirm = card.locator(f'[data-testid="unsettled-confirm-{reply["run_id"]}"]')
    expect(confirm).to_be_disabled()
    card.locator(f'[data-testid="unsettled-checked-{reply["run_id"]}"]').check()
    card.locator(f'[data-testid="unsettled-reason-{reply["run_id"]}"]').fill("읽기 전용 응답이었고 작업 폴더에 변화가 없다")
    expect(confirm).to_be_enabled()
    confirm.click()
    expect(page.locator('[data-testid="work-stage-banner"]')).to_have_attribute("data-progress", "done", timeout=60_000)
    case = stack.http.get(f"/api/cases/{case_id}").json()
    assert case["result"]["closure"]["closure_kind"] == "completed"
    settled = stack.http.get(f"/api/runs/{reply['run_id']}").json()
    assert settled["outcome"] == "unknown" and settled["unknown_settlement"]["kind"] == "confirmed"
    page.context.close()
