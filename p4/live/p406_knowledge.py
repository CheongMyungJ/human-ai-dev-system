"""P4-06 라이브 — 대화에서 정한 프로젝트 규칙이 **실제 codex** 의 다른 업무에 주입되는가(P4-PLAN-06 AC-18).

자동 시험은 가짜 CLI 로 같은 경로를 본다. 여기서 보는 것은 실제 AI 가 사용자의 말을 등록 블록으로
옮기는지와, 그 규칙이 같은 Project 의 **다른 대화**의 업무 실행 입력에 실제로 들어가는지다.

    A. 규칙      새 대화 → "이 프로젝트에서는 앞으로 …" → 응답 아래 등록 카드(자동 활성, 사용자 말이 권위)
    B. 업무      다른 대화 → 명확한 기능 요청 → 업무화 → 의도 초안·준비·구현·검증 실행마다 필수 규칙과
                 권위 원문이 고정 문맥에 있고 Runner 가 읽었다(영수증) · Manifest 가 제공으로 적었다
    C. 관찰      구현 결과가 규칙을 따랐는가 — **제품 규칙이 아니다**(주입은 준수의 증거가 아니다)

**판정은 두 층이다.** 제품 규칙이 어긋나면 멈춘다. AI 의 판단(블록을 붙였는가·옮긴 문구·구현이 규칙을
지켰는가)은 관찰로 적는다. **제품 코드를 import 하지 않는다** — HTTP·브라우저·OS 로만 본다.
라이브 데이터는 `%LOCALAPPDATA%\\Temp\\hads-p4-06-live`, 저장소 `var\\` 를 건드리지 않는다.

실행: `.venv\\Scripts\\python.exe p4\\live\\p406_knowledge.py` (먼저 `npm run build`)
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
sys.path.insert(0, str(REPO_ROOT / "ui" / "live"))

from driver import PYTHON, LiveError, Log, stamp, wait_until  # noqa: E402
from ui03_shell import make_repo, os_processes  # noqa: E402

RUNNER_ID = "runner-p4-06-live"
OUT = REPO_ROOT / "p4" / "evidence"
LIVE_ROOT = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Temp" / "hads-p4-06-live"
DIST = REPO_ROOT / "web" / "dist"
PORT = 8799
STALE_SECONDS = 5
STEP_TIMEOUT = 900

RULE = (
    "이 프로젝트에서는 앞으로 모든 작업에서, 새로 만들거나 고치는 파이썬 함수에는 반드시 한 줄짜리"
    " docstring 을 단다. 예외: 이름이 test_ 로 시작하는 시험 함수는 달지 않아도 된다."
    " 지금 이 대화에서 작업을 시작하지는 마세요."
)
WORK_REQUEST = (
    "app.py 에 오류 줄만 골라 내는 함수 error_lines(lines) 를 추가해 주세요. 인자로 받은 문자열 목록에서"
    " 'ERROR' 로 시작하는 줄만 원래 순서대로 돌려줍니다. log() 는 바꾸지 마세요. 확인은"
    " `python -c \"import app; print(app.error_lines(['ERROR a', 'x', 'ERROR b']))\"` 의 출력이"
    " ['ERROR a', 'ERROR b'] 인지 보는 것으로 충분합니다. 이 저장소 밖은 건드리지 마세요."
)
GENERIC_ANSWER = "제안한 대로 하세요. 추가 제약은 없고, 이 요청의 범위를 넘는 선택이 필요하면 다시 물어 주세요."
WORK_PURPOSES = ("intent_authoring", "design_authoring", "plan_authoring", "feature_implementation", "verification_run")


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
        path = OUT / f"P4-06-live-{name}.png"
        page.screenshot(path=str(path))
        self.shots.append(path.name)

    def conv(self, case_id: str) -> dict[str, Any]:
        return self.http.get(f"/api/cases/{case_id}/conversation").json()

    def case(self, case_id: str) -> dict[str, Any]:
        return self.http.get(f"/api/cases/{case_id}").json()

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
        """열람 중계로 원문을 받는다(서버에 저장되지 않는다). 받지 못하면 None."""
        created = self.http.post(f"/api/artifacts/{artifact_id}/{revision}/read-requests", json={})
        if created.status_code != 201:
            return None
        request_id = created.json()["id"]

        def served():
            # 본문은 **한 번** 받아 간다(받는 순간 중계 버퍼에서 버려진다). 끝난 상태면 그대로 돌려준다.
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


def run(page: Page, system: System, probe: Probe) -> None:
    http = probe.http
    repo = system.root / "workspace"
    project = http.post(
        "/api/projects", json={"name": "로그 도구", "repo_path": str(repo), "default_tool_id": "codex"}
    ).json()
    probe.facts["project_id"] = project["id"]
    page.goto(f"{system.base}/?project={project['id']}")
    page.wait_for_selector('[data-testid="sidebar"]')

    # ------------------------------------------------------------------ A 규칙
    rules_case = probe.new_conversation(page)
    probe.facts["rules_case"] = rules_case
    probe.send(page, RULE)
    started = time.monotonic()

    def a_done(v: dict[str, Any]) -> dict[str, Any] | None:
        settled = [r for r in v["requests"] if r["state"] not in ("processing", "unknown")]
        return v if settled and v["current_request"] is None else None

    view = wait_until(lambda: a_done(probe.conv(rules_case)), "규칙 응답", timeout=STEP_TIMEOUT, interval=3)
    probe.facts["A_reply_seconds"] = round(time.monotonic() - started, 1)
    registrations = view.get("knowledge_registrations") or []
    probe.observe("A 등록 보고", [
        {k: r.get(k) for k in ("intake_state", "refusal", "knowledge_key", "obligation", "kind", "summary", "scope_kind", "activities")}
        for r in registrations
    ])
    probe.rule("규칙 대화는 업무화되지 않음(작업을 맡기지 않았다)", view["stage"] == "discussion", view["stage"])
    registered = [r for r in registrations if r["intake_state"] == "registered"]
    if not registered:
        probe.observe("A 자동 등록 없음", "AI 가 등록 블록을 붙이지 않았다(또는 거부) — 제품 규칙 위반이 아니라 AI 판단. 라이브를 여기서 끝낸다")
        probe.shot(page, "A-not-registered")
        return
    reg = registered[0]
    probe.rule("등록 카드가 응답 아래에 보임", page.locator('[data-testid="knowledge-card"]').count() >= 1)
    expect(page.locator('[data-testid="knowledge-card"]').first).to_contain_text(reg["knowledge_key"])
    probe.shot(page, "A-registered")
    knowledge = http.get(f"/api/projects/{project['id']}/knowledge").json()
    item = next(i for i in knowledge["items"] if i["knowledge_key"] == reg["knowledge_key"])
    current = item["current"]
    user_message = next(m for m in view["messages"] if m["author"] == "user")
    probe.rule("자동 등록은 활성·권위 = 사용자 말(출처 메시지)·AI 가 옮김",
               current["state"] == "active" and current["authority_kind"] == "user_statement"
               and current["source_message_id"] == user_message["id"] and current["created_by"].startswith("ai:"),
               {k: current[k] for k in ("state", "authority_kind", "created_by")})
    content = probe.read_original(current["artifact_id"], current["artifact_rev"])
    probe.observe("A 옮겨 적은 적용 내용", content)
    probe.rule("적용 내용 원문을 PC 에서 읽을 수 있음", bool(content))
    assistant = [m for m in view["messages"] if m["author"] == "assistant"][-1]
    reply_body = probe.read_original(assistant["artifact_id"], assistant["artifact_rev"]) or ""
    probe.rule("대화의 AI 말에는 등록 블록이 없음", "hads-knowledge" not in reply_body)
    # 실행 결과 원문은 실행 정보 머리 + 최종 메시지다. 사람이 읽는 글은 끝부분이다.
    probe.observe("A 응답(끝 400자)", reply_body[-400:])
    db_bytes = b"".join(p.read_bytes() for p in (system.root / "controller").iterdir()
                        if p.is_file() and p.name.startswith("controller.sqlite3"))
    probe.rule("서버 DB 에 적용 내용 원문이 없음", bool(content) and content.strip()[:40].encode("utf-8") not in db_bytes)

    # ------------------------------------------------------------------ B 다른 대화의 업무
    page.goto(f"{system.base}/?project={project['id']}")
    page.wait_for_selector('[data-testid="sidebar"]')
    work_case = probe.new_conversation(page)
    probe.facts["work_case"] = work_case
    probe.send(page, WORK_REQUEST)

    def b_started(v: dict[str, Any]) -> dict[str, Any] | None:
        if v["stage"] == "work":
            return v
        settled = [r for r in v["requests"] if r["state"] not in ("processing", "unknown")]
        return v if settled and v["current_request"] is None else None

    view = wait_until(lambda: b_started(probe.conv(work_case)), "업무화", timeout=STEP_TIMEOUT, interval=3)
    if view["stage"] != "work":
        probe.observe("B 업무화되지 않음", "AI 가 업무 요청으로 읽지 않았다 — AI 판단. 여기서 끝낸다")
        return
    while True:
        view = probe.wait_progress(work_case, ("waiting_human", "blocked", "paused", "done"), timeout=STEP_TIMEOUT * 3)
        codes = [w["code"] for w in view["progress"]["wait"]]
        probe.log(f"B 대기: {codes} · {view['progress']['state']}")
        if "intent_questions" in codes or "deferred_questions" in codes:
            questions = http.get(f"/api/cases/{work_case}/intent-state").json()["open_intent_questions"]
            deferred = http.get(f"/api/cases/{work_case}/preparation").json()["deferred_open_questions"]
            for question in questions + deferred:
                card = page.locator(f'[data-testid="question-card-{question["question_key"]}"]')
                expect(card).to_be_visible(timeout=30_000)
                card.locator("textarea").fill(GENERIC_ANSWER)
                card.locator("button", has_text="답변 보내기").click()
                probe.observe("B 질문", question["summary"])
                time.sleep(2)
            wait_until(lambda: (lambda v: v if v["current_request"] or (v["progress"] or {}).get("state") != "waiting_human" else None)(probe.conv(work_case)), "답 뒤 진행", timeout=60, interval=1)
            continue
        if "intent_agreement" in codes:
            probe.shot(page, "B-agreement")
            page.click('[data-testid="agreement-open"]')
            expect(page.locator('[data-testid="viewer-body"]')).not_to_be_empty(timeout=60_000)
            expect(page.locator('[data-testid="agreement-agree"]')).to_be_enabled(timeout=15_000)
            page.click('[data-testid="agreement-agree"]')
            wait_until(lambda: (lambda v: v if v["current_request"] or (v["progress"] or {}).get("state") != "waiting_human" else None)(probe.conv(work_case)), "동의 뒤 진행", timeout=60, interval=1)
            continue
        break
    probe.observe("B 멈춘 자리", {"state": view["progress"]["state"], "codes": codes})
    probe.shot(page, "B-stopped")

    # 실행마다 고정 문맥·영수증·Manifest.
    case = probe.case(work_case)
    runs = list(reversed(case["runs"]))
    probe.observe("B 실행", [(r["purpose"], r["outcome"]) for r in runs])
    checked = []
    for run_row in runs:
        if run_row["purpose"] not in WORK_PURPOSES or run_row["status"] != "finished":
            continue
        refs = http.get(f"/api/runs/{run_row['run_id']}/context-refs").json()
        req = [r for r in refs if r["role"] == "knowledge_required"]
        src = [r for r in refs if r["role"] == "knowledge_source"]
        manifest = http.get(f"/api/runs/{run_row['run_id']}/knowledge").json()
        decision = {i["knowledge_key"]: i["decision"] for i in manifest["items"]}
        checked.append(run_row["purpose"])
        probe.rule(
            f"{run_row['purpose']} 실행에 필수 규칙과 권위 원문이 있고 Runner 가 읽음",
            len(req) == 1 and len(src) == 1 and req[0]["receipt_status"] == "read"
            and src[0]["receipt_status"] == "read" and req[0]["tier"] == "core"
            and req[0]["knowledge"]["key"] == reg["knowledge_key"],
            {"required": [(r["receipt_status"], r["tier"]) for r in req], "source": [r["receipt_status"] for r in src]},
        )
        probe.rule(f"{run_row['purpose']} Manifest 가 제공으로 적음", decision.get(reg["knowledge_key"]) == "provided", decision)
    probe.rule("업무 실행 둘 이상을 확인함(의도 초안 포함)", "intent_authoring" in checked and len(checked) >= 2, checked)
    reply = next(r for r in runs if r["purpose"] == "discussion_reply")
    manifest = http.get(f"/api/runs/{reply['run_id']}/knowledge").json()
    probe.rule("논의 응답에는 주입되지 않음(활동 비적용)",
               all(i["decision"] == "not_applicable_activity" for i in manifest["items"]) and manifest["items"],
               [(i["knowledge_key"], i["decision"]) for i in manifest["items"]])
    criteria = case["result"]["criteria"]
    probe.rule("기준 판정은 지식 제공으로 바뀌지 않음(검증 실행 보고 또는 미검증)",
               all(c["recorded_by"] in ("policy:work_progressor", None) or c["verdict"] == "unverified" for c in criteria)
               if criteria else True,
               [(c["criterion_key"], c["verdict"], c.get("recorded_by")) for c in criteria])

    # ------------------------------------------------------------------ C 관찰 — 준수는 제품 판정이 아니다
    workspace = http.get(f"/api/cases/{work_case}/workspace").json()
    spaces = workspace.get("workspaces") or []
    if spaces and spaces[0].get("worktree_path"):
        app = Path(spaces[0]["worktree_path"]) / "app.py"
        text = app.read_text(encoding="utf-8") if app.exists() else ""
        probe.observe("C 구현 결과 app.py", text[:1200])
        if "def error_lines" in text:
            # 함수 머리 다음 첫 비어 있지 않은 줄이 docstring 인가(S-025 통과 회차는 이 검사가 틀려 False 로 적었다 —
            # 결과 JSON 의 app.py 관찰에는 docstring 이 있다).
            body = [ln.strip() for ln in text.split("def error_lines", 1)[1].splitlines()[1:] if ln.strip()]
            probe.observe("C error_lines 에 docstring 이 있는가(관찰)", bool(body) and body[0][:3] in ('"""', "'''"))


def main() -> int:
    if not (DIST / "index.html").exists():
        print("web/dist 가 없다 — web 에서 npm run build 를 먼저 한다", file=sys.stderr)
        return 2
    tag = stamp()
    root = LIVE_ROOT / tag
    root.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    version = subprocess.run(["codex", "--version"], capture_output=True, text=True, shell=True).stdout.strip()
    with Log(OUT / "P4-06-live.log") as log:
        log(f"P4-06 라이브 {tag} · codex {version or '버전 확인 실패'} · 데이터 {root}")
        system = System(root, log)
        probe = Probe(system, log)
        make_repo(root)
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
        (OUT / "P4-06-live-results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"결과: {status} · 제품 규칙 {sum(r['ok'] for r in probe.product)}/{len(probe.product)} · 관찰 {len(probe.observations)}")
    return 0 if status == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
