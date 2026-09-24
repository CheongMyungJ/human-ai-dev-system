"""UI-04a 라이브 — 결정 사항 패널·프로젝트 규칙 화면을 **실제 codex·실제 Edge** 로 쓴다(UI-PLAN-04a AC-13).

자동 시험(`tests/test_web_shell.py`)은 가짜 CLI 로 같은 화면 경로를 본다. 여기서 보는 것은 실제 AI 가 (1) 대화에서
말한 규칙을 옮겨 등록하는지, (2) "정리해줘" 에 제안(`proposal: true`)을 붙이는지 — 둘 다 **관찰** — 와, 그 뒤의
화면·이동·변경이 제품 규칙대로 도는가다.

    A. 규칙      새 대화 → 짧은 논의 → "이 프로젝트에서는 앞으로 …"(관찰: AI 가 옮겨 등록했는가) → 결정 사항
                 패널의 "이 대화에서 정한 규칙" · 메시지로 이동 → 프로젝트 규칙 화면의 항목 · "원래 대화로" →
                 그 메시지 강조·주소의 seq 소비 · 내용 보기(서버 본문)
    B. 정리      같은 대화에 "재사용할 사실을 지식 후보로 정리해줘"(관찰: 제안을 붙였는가) → 규칙 화면에서
                 채택 확인 → 활성화(사람의 결정, 새 버전)
    C. 적용      다른 대화의 업무(구현 요청) → 실행에 규칙이 들어감 → 그 대화의 결정 사항 패널 "이 업무에 적용된
                 프로젝트 규칙" 이 Manifest 집계와 같다

**판정은 두 층이다.** 제품 규칙이 어긋나면 멈춘다. AI 의 판단은 관찰로 적는다. **제품 코드를 import 하지 않는다**
— HTTP·브라우저·OS 로만 본다. 라이브 데이터는 `%LOCALAPPDATA%\\Temp\\hads-ui-04a-live`, 저장소 `var\\` 를
건드리지 않는다.

실행: `.venv\\Scripts\\python.exe ui\\live\\ui04a_rules.py` (먼저 `npm run build`, `PYTHONUTF8=1 PYTHONIOENCODING=utf-8`)
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
sys.path.insert(0, str(REPO_ROOT / "p4" / "live"))

from driver import PYTHON, LiveError, Log, stamp, wait_until  # noqa: E402
from p407_extraction import Probe as BaseProbe, drive_work, enrich_repo, start_work  # noqa: E402
from ui03_shell import make_repo, os_processes  # noqa: E402

RUNNER_ID = "runner-ui-04a-live"
OUT = REPO_ROOT / "ui" / "evidence"
LIVE_ROOT = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Temp" / "hads-ui-04a-live"
DIST = REPO_ROOT / "web" / "dist"
PORT = 8797
STALE_SECONDS = 5
STEP_TIMEOUT = 900

OPENING = (
    "이 저장소의 README 와 app.py 를 보고 로그 한 줄의 형식이 어떤지 두세 문장으로만 이야기해 주세요. 아직 아무"
    " 것도 만들거나 고치지 마세요."
)
RULE_STATEMENT = (
    "이 프로젝트에서는 앞으로 모든 작업에서, 새로 만들거나 고치는 파이썬 함수에는 반드시 한 줄짜리 docstring 을"
    " 단다. 예외: 이름이 test_ 로 시작하는 시험 함수는 달지 않아도 된다. 지금 이 대화에서 작업을 시작하지는 마세요."
)
SUMMARIZE_REQUEST = (
    "이 저장소에서 다음 작업에도 재사용할 만한 사실(빌드·시험·환경 조건, 구조, 알려진 문제)이 있으면 지식 후보로"
    " 정리해 주세요. 저장소(README·tests)를 읽고 당신이 직접 확인한 사실만 적고, 내가 정한 규칙이 아니라 당신의"
    " 관찰이므로 후보(proposal)로 붙여 주세요. 없으면 없다고 답해도 됩니다. 작업을 시작하지는 마세요."
)
WORK_REQUEST = (
    "app.py 에 오류 줄만 골라 내는 함수 error_lines(lines) 를 추가해 주세요. 인자로 받은 문자열 목록에서"
    " 수준이 ERROR 인 줄(표본 형식은 README 참고)만 원래 순서대로 돌려줍니다. log() 는 바꾸지 마세요. 확인은"
    " README 의 시험 방법대로 기존 시험이 통과하는지와, samples/app.log 로 error_lines 를 돌려 ERROR 줄 두 개가"
    " 나오는지 보면 됩니다. 이 저장소 밖은 건드리지 마세요."
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


class Probe(BaseProbe):
    def shot(self, page: Page, name: str) -> None:
        path = OUT / f"UI-04a-live-{name}.png"
        page.screenshot(path=str(path))
        self.shots.append(path.name)

    def address(self, page: Page) -> str:
        return page.evaluate("location.href")

    def use(self, case_id: str) -> dict[str, Any]:
        return self.http.get(f"/api/cases/{case_id}/knowledge-use").json()


def run(page: Page, system: System, probe: Probe) -> None:
    http = probe.http
    repo = system.root / "workspace"
    project = http.post(
        "/api/projects", json={"name": "로그 도구", "repo_path": str(repo), "default_tool_id": "codex"}
    ).json()
    probe.facts["project_id"] = project["id"]
    page.goto(f"{system.base}/?project={project['id']}")
    page.wait_for_selector('[data-testid="sidebar"]')

    # ------------------------------------------------------------------ A 규칙 — 말하기(관찰) → 패널 → 규칙 화면 → 원래 메시지
    talk = probe.new_conversation(page)
    probe.facts["talk_case"] = talk
    probe.send(page, OPENING)
    started = time.monotonic()
    probe.wait_reply(talk, 1)
    probe.facts["A_opening_seconds"] = round(time.monotonic() - started, 1)
    # 응답이 끝나면 전송이 열린다(입력이 비어 있어 버튼은 꺼져 있다 — `send` 가 채운 뒤 열림을 기다린다).
    expect(page.locator('[data-testid="send-refusal"]')).to_have_count(0, timeout=30_000)
    probe.send(page, RULE_STATEMENT)
    started = time.monotonic()
    view = probe.wait_reply(talk, 2)
    probe.facts["A_rule_seconds"] = round(time.monotonic() - started, 1)
    statements = [r for r in (view.get("knowledge_registrations") or []) if r.get("origin") == "statement"]
    probe.observe("A 규칙 발언의 등록", [
        {k: r.get(k) for k in ("intake_state", "refusal", "knowledge_key", "obligation", "summary", "source_message_seq", "reply_seq")}
        for r in statements
    ])
    registered = [r for r in statements if r["intake_state"] == "registered"]
    if not registered:
        probe.observe("A 등록 없음", "실제 codex 가 규칙을 옮겨 등록하지 않았다 — AI 판단. 화면 검증은 B·C 로 이어 간다")
        rule_key = None
    else:
        rule = registered[0]
        rule_key = rule["knowledge_key"]
        user_seq = next(m["seq"] for m in view["messages"] if m["author"] == "user" and m["seq"] == rule["source_message_seq"])
        probe.rule("등록 조회가 권위 메시지·응답의 순번을 가진다", rule["source_message_seq"] == user_seq and rule["reply_seq"] == user_seq + 1,
                   (rule["source_message_seq"], rule["reply_seq"]))
        card = page.locator('[data-testid="knowledge-card"]')
        expect(card).to_be_visible(timeout=30_000)
        probe.rule("등록 카드의 링크가 프로젝트 규칙 화면의 그 항목을 가리킨다",
                   card.locator('[data-testid="knowledge-card-rules"]').get_attribute("href") == f"?project={project['id']}&screen=rules&item={rule_key}")
        # 결정 사항 패널
        page.click('[data-testid="open-decisions"]')
        row = page.locator(f'[data-testid="decisions-rule-{rule_key}"]')
        expect(row).to_be_visible(timeout=20_000)
        probe.rule("결정 사항 패널이 이 대화에서 정한 규칙을 지금 상태와 함께 보인다",
                   "지금 활성" in row.inner_text() and row.get_attribute("data-state") == "active", row.inner_text()[:160])
        probe.rule("결정 사항 패널에는 활성화 버튼이 없다",
                   page.locator('[data-testid="decisions"] [data-testid^="rule-activate-"]').count() == 0)
        row.locator(f'[data-testid="decisions-rule-message-{rule_key}"]').click()
        expect(page.locator(f'[data-testid="message-{user_seq}"]')).to_have_attribute("data-focus", "1", timeout=10_000)
        probe.rule("패널의 '메시지 #n' 이 그 메시지를 강조한다", True)
        probe.shot(page, "A-panel")
        # 프로젝트 규칙 화면
        page.click('[data-testid="open-rules"]')
        screen = page.locator('[data-testid="rules-screen"]')
        expect(screen).to_be_visible(timeout=20_000)
        probe.rule("규칙 화면의 주소는 screen=rules 이고 오른쪽 패널은 닫힌다",
                   "screen=rules" in probe.address(page) and page.locator('[data-testid="review-panel"]').count() == 0)
        item = screen.locator(f'[data-testid="rule-{rule_key}"]')
        expect(item).to_be_visible(timeout=20_000)
        probe.rule("항목이 활성 필수 절에 있고 상태·효력이 서버 값과 같다",
                   item.get_attribute("data-state") == "active" and item.get_attribute("data-obligation") == rule["obligation"]
                   and screen.locator(f'[data-testid="rules-required"] [data-testid="rule-{rule_key}"]').count() == (1 if rule["obligation"] == "required" else 0))
        link = item.locator(f'[data-testid="rule-source-link-{rule_key}"]')
        probe.rule("출처 링크가 대화 제목·메시지 순번을 가리킨다",
                   link.get_attribute("href") == f"?project={project['id']}&case={talk}&seq={user_seq}" and f"메시지 #{user_seq}" in link.inner_text(),
                   link.get_attribute("href"))
        item.locator(f'[data-testid="rule-toggle-{rule_key}"]').click()
        item.locator(f'[data-testid="rule-show-{rule_key}"]').click()
        body = item.locator(f'[data-testid="rule-body-{rule_key}"]')
        expect(body).to_be_visible(timeout=30_000)
        probe.observe("A 옮겨 적힌 적용 내용", body.inner_text()[:400])
        probe.rule("내용 보기는 서버 본문을 연다(storage=server)", "서버 저장" in item.locator(f'[data-testid="rule-storage-{rule_key}"]').inner_text())
        probe.shot(page, "A-rules")
        # 원래 대화로
        link.click()
        page.wait_for_selector('[data-testid="conversation-title"]')
        expect(page.locator(f'[data-testid="message-{user_seq}"]')).to_have_attribute("data-focus", "1", timeout=60_000)
        wait_until(lambda: "seq=" not in probe.address(page), "seq 소비", timeout=10, interval=0.3)
        probe.rule("'원래 대화로' 가 그 메시지를 강조하고 주소의 seq 는 소비된다", f"case={talk}" in probe.address(page), probe.address(page))
        probe.shot(page, "A-focus")

    # ------------------------------------------------------------------ B 정리 — 제안(관찰) → 규칙 화면에서 채택 확인·활성화
    replies_before = len([m for m in probe.conv(talk)["messages"] if m["author"] == "assistant"])
    expect(page.locator('[data-testid="send-refusal"]')).to_have_count(0, timeout=30_000)
    probe.send(page, SUMMARIZE_REQUEST)
    started = time.monotonic()
    view = probe.wait_reply(talk, replies_before + 1)
    probe.facts["B_reply_seconds"] = round(time.monotonic() - started, 1)
    reply = [m for m in view["messages"] if m["author"] == "assistant"][-1]
    proposals = [r for r in (view.get("knowledge_registrations") or []) if r["run_id"] == reply["run_id"]]
    probe.observe("B 정리 응답의 항목", [
        {k: r.get(k) for k in ("origin", "intake_state", "refusal", "knowledge_key", "kind", "obligation", "summary", "basis", "reply_seq")}
        for r in proposals
    ])
    probe.rule("정리 응답이 사용자 말(활성 규칙)을 만들지 않음 — 제안은 후보뿐",
               not [r for r in proposals if r["intake_state"] == "registered" and r["origin"] == "statement"])
    candidates = [r for r in proposals if r["intake_state"] == "registered" and r["origin"] == "proposal"]
    activated: dict[str, Any] | None = None
    if not candidates:
        probe.observe("B 후보 없음", "실제 codex 가 정리 응답에 제안을 붙이지 않았다 — AI 판단. 활성화 단계를 건너뛴다")
    else:
        cand = candidates[0]
        key = cand["knowledge_key"]
        probe.rule("제안은 후보·AI 제안이고 응답 순번만 가진다(권위 메시지 없음)",
                   cand["state"] == "candidate" and cand["authority_kind"] == "ai_proposal" and cand["source_message_seq"] is None and cand["reply_seq"] == reply["seq"],
                   {k: cand.get(k) for k in ("state", "authority_kind", "source_message_seq", "reply_seq")})
        page.click('[data-testid="open-decisions"]')
        row = page.locator(f'[data-testid="decisions-rule-{key}"]')
        expect(row).to_be_visible(timeout=20_000)
        probe.rule("결정 사항 패널이 AI 제안을 후보로 보인다", row.get_attribute("data-state") == "candidate" and "AI 제안" in row.inner_text())
        row.locator(f'[data-testid="decisions-rule-open-{key}"]').click()
        screen = page.locator('[data-testid="rules-screen"]')
        expect(screen).to_be_visible(timeout=30_000)
        item = screen.locator(f'[data-testid="rule-{key}"]')
        expect(item.locator(f'[data-testid="rule-details-{key}"]')).to_be_visible(timeout=20_000)
        probe.rule("'프로젝트 규칙에서 보기' 가 그 항목을 펼쳐 연다", screen.locator(f'[data-testid="rules-candidates"] [data-testid="rule-{key}"]').count() == 1)
        item.locator(f'[data-testid="rule-check-{key}"]').click()
        result = item.locator(f'[data-testid="rule-check-result-{key}"]')
        expect(result).to_be_visible(timeout=20_000)
        check = http.get(f"/api/knowledge/{cand['knowledge_id']}/adoption-check").json()
        probe.observe("B 채택 확인", {"blocked": check["blocked"], "findings": [(f["code"], f["blocking"]) for f in check["findings"]], "evidence": check["evidence_count"]})
        probe.rule("화면의 채택 확인이 서버 값과 같다(독립 검토 없음 표시)",
                   ("독립 AI 검토는 돌리지 않았다" in result.inner_text()) and (("막는 항목 없음" in result.inner_text()) == (not check["blocked"])))
        probe.shot(page, "B-check")
        if check["blocked"]:
            probe.observe("B 활성화 불가", f"막는 항목 {check['blocked']} — 이 후보로는 활성화하지 않는다")
        else:
            item.locator(f'[data-testid="rule-activate-reason-{key}"]').fill("라이브에서 확인한 관찰(사람의 결정)")
            item.locator(f'[data-testid="rule-activate-{key}"]').click()
            expect(item).to_have_attribute("data-state", "active", timeout=20_000)
            knowledge = probe.knowledge(project["id"])
            entry = next(i for i in knowledge["items"] if i["knowledge_key"] == key)
            versions = entry["versions"]
            probe.rule("활성화는 새 버전(user_decision)·채택 기록이고 후보 버전은 대체됨",
                       [(v["version"], v["state"], v["authority_kind"]) for v in versions] == [(1, "superseded", "ai_proposal"), (2, "active", "user_decision")]
                       and versions[1]["adoption"] is not None,
                       [(v["version"], v["state"], v["authority_kind"]) for v in versions])
            probe.rule("활성화한 항목이 활성 절로 옮겨졌다",
                       screen.locator(f'[data-testid="rules-{"required" if versions[1]["obligation"] == "required" else "reference"}"] [data-testid="rule-{key}"]').count() == 1)
            activated = versions[1]
            probe.facts["activated"] = {"key": key, "obligation": activated["obligation"], "activities": activated["activities"], "scope": activated["scope_kind"]}
            probe.shot(page, "B-activated")

    # ------------------------------------------------------------------ C 적용 — 다른 대화의 업무 → 적용된 규칙 절
    page.goto(f"{system.base}/?project={project['id']}")
    page.wait_for_selector('[data-testid="sidebar"]')
    work_case = start_work(page, probe, WORK_REQUEST, "C")
    if work_case is None:
        return
    probe.facts["work_case"] = work_case
    view = drive_work(page, probe, http, work_case, "C")
    probe.observe("C 멈춘 자리", {"state": view["progress"]["state"], "codes": [w["code"] for w in view["progress"]["wait"]]})
    case = probe.case(work_case)
    runs = [r for r in reversed(case["runs"]) if r["status"] == "finished"]
    probe.observe("C 실행", [(r["purpose"], r["outcome"]) for r in runs])
    use = probe.use(work_case)
    probe.observe("C 적용된 규칙(집계)", [(i["knowledge_key"], i["version"], i["obligation"], i["provided_runs"], i["skipped"]) for i in use["items"]])
    # 집계 = Manifest
    provided: dict[str, int] = {}
    for run_row in runs:
        for row_ in http.get(f"/api/runs/{run_row['run_id']}/knowledge").json()["items"]:
            if row_["decision"] == "provided":
                provided[(row_["knowledge_key"], row_["version"])] = provided.get((row_["knowledge_key"], row_["version"]), 0) + 1
    probe.rule("적용된 규칙 집계가 실행별 Manifest 의 제공 수와 같다",
               {(i["knowledge_key"], i["version"]): i["provided_runs"] for i in use["items"] if i["provided_runs"]} == provided,
               {"use": {f"{k[0]} v{k[1]}": v for k, v in provided.items()}})
    probe.rule("이 라이브의 실행은 전부 Manifest 기록 뒤의 실행이다", use["runs_unrecorded"] == 0, use)
    if rule_key is not None:
        mine = next((i for i in use["items"] if i["knowledge_key"] == rule_key), None)
        probe.rule("대화에서 정한 필수 규칙이 업무 실행에 제공됐다", mine is not None and mine["provided_runs"] >= 1, mine)
    page.click('[data-testid="open-decisions"]')
    applied = page.locator('[data-testid="decisions-applied"]')
    if use["items"]:
        expect(applied).to_be_visible(timeout=20_000)
        for entry in use["items"]:
            row = page.locator(f'[data-testid="applied-{entry["knowledge_key"]}"]')
            expect(row).to_be_visible(timeout=10_000)
            probe.rule(f"패널의 {entry['knowledge_key']} 제공 수가 서버 값과 같다",
                       row.get_attribute("data-provided") == str(entry["provided_runs"]), row.get_attribute("data-provided"))
        probe.rule("적용 절이 '준수의 증거가 아니다' 를 적는다", "준수의 증거가 아니다" in applied.inner_text())
    else:
        probe.observe("C 적용된 규칙 없음", "등록·활성화된 규칙이 없어 적용 절이 비었다")
    goal = page.locator('[data-testid="decisions-goal"]')
    expect(goal).to_be_visible(timeout=20_000)
    probe.rule("목표·기준 절이 의도 버전과 동의 상태를 보인다", "의도 v" in goal.inner_text(), goal.inner_text()[:120])
    decisions = page.locator('[data-testid="decisions-list"]')
    if decisions.count():
        probe.rule("결정 절의 종류가 사람 말이고 대상 버전을 가리킨다", "의도 동의" in decisions.inner_text() and "의도 v" in decisions.inner_text(), decisions.inner_text()[:160])
    probe.shot(page, "C-applied")


def main() -> int:
    if not (DIST / "index.html").exists():
        print("web/dist 가 없다 — web 에서 npm run build 를 먼저 한다", file=sys.stderr)
        return 2
    tag = stamp()
    root = LIVE_ROOT / tag
    root.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    version = subprocess.run(["codex", "--version"], capture_output=True, text=True, shell=True).stdout.strip()
    with Log(OUT / "UI-04a-live.log") as log:
        log(f"UI-04a 라이브 {tag} · codex {version or '버전 확인 실패'} · 데이터 {root}")
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
        (OUT / "UI-04a-live-results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"결과: {status} · 제품 규칙 {sum(r['ok'] for r in probe.product)}/{len(probe.product)} · 관찰 {len(probe.observations)}")
    return 0 if status == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
