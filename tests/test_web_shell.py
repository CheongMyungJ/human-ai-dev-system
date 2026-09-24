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
