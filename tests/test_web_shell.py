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
    banner = page.locator('[data-testid="work-stage-banner"]')
    expect(banner).to_contain_text("아직 자동으로 진행하지")
    assert "view=admin" in banner.locator("a").get_attribute("href")

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
