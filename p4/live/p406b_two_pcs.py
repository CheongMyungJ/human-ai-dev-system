"""P4-06b 라이브 — **두 PC**: PC A 의 대화에서 정한 규칙이 PC A 가 꺼진 뒤 PC B 의 실제 codex 업무에 주입되는가
(P4-PLAN-06b AC-13, 사용자 결정 2026-09-24 — 지식 원문의 서버 저장).

자동 시험은 가짜 CLI 로 같은 경로를 본다. 여기서 보는 것은 실제 AI 와 실제 두 Runner 프로세스에서

    A. 규칙      PC A 의 대화 → "이 프로젝트에서는 앞으로 …" → 자동 등록 → 옮긴 내용과 그 말이 **서버 DB 에**(다른 표·
                 로그에는 없음) · 카드가 "서버에 저장됨" 을 알림 · 열람이 PC 없이 서버에서 옴
    B. 업무      PC A 종료(미연결) → PC B 의 다른 대화 → 명확한 기능 요청 → 업무화 → 실행마다 필수 규칙과 권위 원문이
                 고정 문맥에 있고 **PC B 가 서버 본문을 읽었다**(영수증 `read`) · Manifest 제공 · PC B 저장소에는 그 원문 없음
    C. 관찰      구현 결과가 규칙을 따랐는가 — **제품 규칙이 아니다**(주입은 준수의 증거가 아니다)

**판정은 두 층이다.** 제품 규칙이 어긋나면 멈춘다. AI 의 판단은 관찰로 적는다. **제품 코드를 import 하지 않는다** —
HTTP·브라우저·OS·DB 파일로만 본다. 라이브 데이터는 `%LOCALAPPDATA%\\Temp\\hads-p4-06b-live`, 저장소 `var\\` 를
건드리지 않는다.

**두 Runner 는 차례로 돈다** — A 만 켜서 규칙을 등록하고, A 를 끈 뒤 B 를 켠다. 둘을 동시에 켜면 배정이 먼저
폴링한 Runner 에게 가서(배정은 원문 소유 PC 를 보지 않는다 — S-026 에서 발견, P6-01 의 몫) A 의 대화 응답을 B 가
맡아 지시 원문 `missing` 으로 실패했다(둘째 시도). 이 라이브가 보는 것은 지식 원문의 서버 저장이지 배정 경로가
아니다.

실행: `.venv\\Scripts\\python.exe p4\\live\\p406b_two_pcs.py` (먼저 `npm run build`)
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

RUNNER_A = "runner-p4-06b-A"
RUNNER_B = "runner-p4-06b-B"
OUT = REPO_ROOT / "p4" / "evidence"
LIVE_ROOT = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Temp" / "hads-p4-06b-live"
DIST = REPO_ROOT / "web" / "dist"
PORT = 8798
STALE_SECONDS = 5
STEP_TIMEOUT = 900

WORDS = "RULE-WORDS-6b2f"
RULE = (
    "이 프로젝트에서는 앞으로 모든 작업에서, 새로 만들거나 고치는 파이썬 함수에는 반드시 한 줄짜리"
    f" docstring 을 단다. 예외: 이름이 test_ 로 시작하는 시험 함수는 달지 않아도 된다. (표식 {WORDS})"
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
        self.runners: dict[str, subprocess.Popen] = {}

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

    def start_runner(self, runner_id: str) -> None:
        data = self.root / runner_id
        data.mkdir(parents=True, exist_ok=True)
        self.runners[runner_id] = subprocess.Popen(
            [str(PYTHON), "-m", "runner.agent"],
            cwd=REPO_ROOT,
            env=self._env(HADS_RUNNER_DATA=str(data), HADS_RUNNER_ID=runner_id, HADS_CONTROLLER_URL=self.base),
            stdout=(data / "runner.log").open("a", encoding="utf-8"),
            stderr=subprocess.STDOUT,
        )
        self.log(f"Runner {runner_id} 기동 pid={self.runners[runner_id].pid}")

    def stop_runner(self, runner_id: str) -> None:
        proc = self.runners.get(runner_id)
        if proc is not None and proc.poll() is None:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
            proc.wait(timeout=30)
        self.log(f"Runner {runner_id} 종료")

    def stop(self) -> None:
        for runner_id in list(self.runners):
            self.stop_runner(runner_id)
        if self.controller is not None and self.controller.poll() is None:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.controller.pid)], capture_output=True)
            self.controller.wait(timeout=30)


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
        path = OUT / f"P4-06b-live-{name}.png"
        page.screenshot(path=str(path))
        self.shots.append(path.name)

    def conv(self, case_id: str) -> dict[str, Any]:
        return self.http.get(f"/api/cases/{case_id}/conversation").json()

    def case(self, case_id: str) -> dict[str, Any]:
        return self.http.get(f"/api/cases/{case_id}").json()

    def runner_state(self, runner_id: str) -> str:
        """그 PC 의 연결 상태. 아직 등록되지 않았으면 `unregistered` — `next()` 의 StopIteration 이
        `wait_until` 안에서 RuntimeError 가 되지 않게 한다(첫 시도가 그렇게 죽었다)."""
        for runner in self.http.get("/api/runners").json():
            if runner["id"] == runner_id:
                return runner["connection"]["state"]
        return "unregistered"

    def new_conversation(self, project_id: str, title: str) -> str:
        response = self.http.post(f"/api/projects/{project_id}/conversations", json={"title": title})
        if response.status_code != 201:
            raise LiveError(f"대화 생성 실패: {response.text}")
        return response.json()["case_id"]

    def send(self, case_id: str, text: str, runner_id: str, client_id: str) -> None:
        """HTTP 로 메시지를 보낸다(출처 PC 를 명시). 접수(그 PC 저장)까지 기다린다."""
        response = self.http.post(
            f"/api/cases/{case_id}/messages",
            json={"client_message_id": client_id, "kind": "general", "content": text,
                  "summary": f"사용자 메시지 · {len(text)}자", "target_runner_id": runner_id},
        )
        if response.status_code != 202:
            raise LiveError(f"전송 실패: {response.status_code} {response.text}")
        wait_until(
            lambda: self.http.get(f"/api/cases/{case_id}/messages/by-client-id/{client_id}").json().get("receipt") == "stored" or None,
            "메시지 접수", timeout=60, interval=0.5,
        )

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

    def db_tables_with(self, marker: str) -> set[str]:
        """제어부 DB 에서 표식을 담은 표들(행 단위). 어느 표에 있는가가 경계의 질문이다."""
        raw = marker.encode("utf-8")
        conn = sqlite3.connect(self.system.root / "controller" / "controller.sqlite3")
        try:
            found: set[str] = set()
            for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall():
                for row in conn.execute(f'SELECT * FROM "{table}"').fetchall():
                    for value in row:
                        if (isinstance(value, bytes) and raw in value) or (isinstance(value, str) and marker in value):
                            found.add(table)
            return found
        finally:
            conn.close()


def run(page: Page, system: System, probe: Probe) -> None:
    http = probe.http
    repo = system.root / "workspace"
    project = http.post(
        "/api/projects", json={"name": "로그 도구", "repo_path": str(repo), "default_tool_id": "codex"}
    ).json()
    probe.facts["project_id"] = project["id"]

    # ------------------------------------------------------------------ A 규칙 (PC A)
    rules_case = probe.new_conversation(project["id"], "규칙 이야기")
    probe.facts["rules_case"] = rules_case
    started = time.monotonic()
    probe.send(rules_case, RULE, RUNNER_A, "m-rule")

    def a_done(v: dict[str, Any]) -> dict[str, Any] | None:
        settled = [r for r in v["requests"] if r["state"] not in ("processing", "unknown")]
        return v if settled and v["current_request"] is None else None

    view = wait_until(lambda: a_done(probe.conv(rules_case)), "규칙 응답", timeout=STEP_TIMEOUT, interval=3)
    probe.facts["A_reply_seconds"] = round(time.monotonic() - started, 1)
    registrations = view.get("knowledge_registrations") or []
    probe.observe("A 등록 보고", [
        {k: r.get(k) for k in ("intake_state", "refusal", "knowledge_key", "obligation", "kind", "summary", "scope_kind", "storage", "source_storage")}
        for r in registrations
    ])
    probe.rule("규칙 대화는 업무화되지 않음", view["stage"] == "discussion", view["stage"])
    registered = [r for r in registrations if r["intake_state"] == "registered"]
    if not registered:
        probe.observe("A 자동 등록 없음", "AI 가 등록 블록을 붙이지 않았다(또는 거부) — AI 판단. 라이브를 여기서 끝낸다")
        return
    reg = registered[0]
    knowledge = http.get(f"/api/projects/{project['id']}/knowledge").json()
    current = next(i for i in knowledge["items"] if i["knowledge_key"] == reg["knowledge_key"])["current"]
    user_message = next(m for m in view["messages"] if m["author"] == "user")
    probe.rule("자동 등록은 활성·권위 = 사용자 말·AI 가 옮김",
               current["state"] == "active" and current["authority_kind"] == "user_statement"
               and current["source_message_id"] == user_message["id"] and current["created_by"].startswith("ai:"),
               {k: current[k] for k in ("state", "authority_kind", "created_by")})
    probe.rule("옮긴 내용과 권위 메시지가 서버 저장(storage = server)",
               current["storage"] == "server" and current["source_storage"] == "server",
               {"storage": current["storage"], "source_storage": current["source_storage"]})
    content = probe.read_original(current["artifact_id"], current["artifact_rev"])
    probe.observe("A 옮겨 적은 적용 내용", content)
    probe.rule("적용 내용 원문을 열람할 수 있음(서버가 채움 — 소유 PC 의 열람 대기열에 남지 않음)",
               bool(content) and http.get(f"/api/runner/{RUNNER_A}/read-requests").json() == [])
    tables_words = probe.db_tables_with(WORDS)
    probe.rule("사용자의 말(권위 원문)은 DB 의 knowledge_body 에만 있음", tables_words == {"knowledge_body"}, sorted(tables_words))
    if content:
        head = content.strip()[:40]
        tables_content = probe.db_tables_with(head)
        probe.rule("옮긴 적용 내용은 DB 의 knowledge_body 에만 있음", tables_content == {"knowledge_body"}, sorted(tables_content))
    log_bytes = (system.root / "controller" / "controller.log").read_bytes() if (system.root / "controller" / "controller.log").exists() else b""
    probe.rule("서버 로그에 본문이 없음", WORDS.encode("utf-8") not in log_bytes and (not content or content.strip()[:40].encode("utf-8") not in log_bytes))
    assistant = [m for m in view["messages"] if m["author"] == "assistant"][-1]
    reply_body = probe.read_original(assistant["artifact_id"], assistant["artifact_rev"]) or ""
    probe.rule("대화의 AI 말에는 등록 블록이 없음", "hads-knowledge" not in reply_body)
    probe.observe("A 응답(끝 400자)", reply_body[-400:])
    probe.rule("응답 본문(지식이 아닌 원문)은 서버 DB 에 없음", probe.db_tables_with(reply_body.strip()[-60:]) == set())
    # 카드.
    page.goto(f"{system.base}/?project={project['id']}&case={rules_case}")
    page.wait_for_selector('[data-testid="sidebar"]')
    card = page.locator('[data-testid="knowledge-card"]')
    expect(card.first).to_be_visible(timeout=60_000)
    probe.rule("등록 카드가 '서버에 저장' 을 알림",
               card.first.locator('[data-testid="knowledge-card-storage"]').count() == 1
               and "서버에 저장" in card.first.locator('[data-testid="knowledge-card-storage"]').inner_text())
    probe.shot(page, "A-registered")

    # ------------------------------------------------------------------ PC A 종료 → PC B 기동
    system.stop_runner(RUNNER_A)
    wait_until(lambda: probe.runner_state(RUNNER_A) != "connected" or None, "PC A 미연결", timeout=60, interval=1)
    probe.rule("PC A 가 미연결로 보임", probe.runner_state(RUNNER_A) != "connected", probe.runner_state(RUNNER_A))
    system.start_runner(RUNNER_B)
    wait_until(lambda: probe.runner_state(RUNNER_B) == "connected" or None, "PC B 연결", timeout=60, interval=1)
    probe.rule("PC B 는 연결됨", probe.runner_state(RUNNER_B) == "connected")
    probe.rule("PC B 의 저장소는 비어 있음(PC A 의 원문을 받은 적 없음)",
               not list((system.root / RUNNER_B / "artifacts").rglob("*.bin")) if (system.root / RUNNER_B / "artifacts").exists() else True)

    # ------------------------------------------------------------------ B 업무 (PC B)
    work_case = probe.new_conversation(project["id"], "오류 줄 필터")
    probe.facts["work_case"] = work_case
    probe.send(work_case, WORK_REQUEST, RUNNER_B, "m-work")
    page.goto(f"{system.base}/?project={project['id']}&case={work_case}")
    page.wait_for_selector('[data-testid="sidebar"]')

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
                qcard = page.locator(f'[data-testid="question-card-{question["question_key"]}"]')
                expect(qcard).to_be_visible(timeout=30_000)
                qcard.locator("textarea").fill(GENERIC_ANSWER)
                qcard.locator("button", has_text="답변 보내기").click()
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

    case = probe.case(work_case)
    runs = list(reversed(case["runs"]))
    probe.observe("B 실행", [(r["purpose"], r["outcome"], r.get("assigned_runner_id")) for r in runs])
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
            f"{run_row['purpose']} — PC B 실행에 필수 규칙·권위 원문이 서버 본문으로 있고 PC B 가 읽음",
            run_row.get("assigned_runner_id") == RUNNER_B and len(req) == 1 and len(src) == 1
            and req[0]["receipt_status"] == "read" and src[0]["receipt_status"] == "read"
            and req[0]["tier"] == "core" and req[0]["body_source"] == "server" and src[0]["body_source"] == "server"
            and req[0]["knowledge"]["key"] == reg["knowledge_key"],
            {"runner": run_row.get("assigned_runner_id"),
             "required": [(r["receipt_status"], r["tier"], r["body_source"]) for r in req],
             "source": [(r["receipt_status"], r["body_source"]) for r in src]},
        )
        probe.rule(f"{run_row['purpose']} Manifest 가 제공으로 적음", decision.get(reg["knowledge_key"]) == "provided", decision)
    probe.rule("업무 실행 둘 이상을 확인함(의도 초안 포함)", "intent_authoring" in checked and len(checked) >= 2, checked)
    b_store = system.root / RUNNER_B / "artifacts"
    in_b = any(WORDS.encode("utf-8") in p.read_bytes() for p in b_store.rglob("*.bin")) if b_store.exists() else False
    probe.rule("PC B 의 원문 저장소에는 권위 원문이 없음(서버가 배정에 실어 줌)", not in_b)
    reply = next(r for r in runs if r["purpose"] == "discussion_reply")
    manifest = http.get(f"/api/runs/{reply['run_id']}/knowledge").json()
    probe.rule("논의 응답에는 주입되지 않음(활동 비적용)",
               bool(manifest["items"]) and all(i["decision"] == "not_applicable_activity" for i in manifest["items"]),
               [(i["knowledge_key"], i["decision"]) for i in manifest["items"]])
    criteria = case["result"]["criteria"]
    probe.rule("기준 판정은 지식 제공으로 바뀌지 않음",
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
    with Log(OUT / "P4-06b-live.log") as log:
        log(f"P4-06b 라이브 {tag} · codex {version or '버전 확인 실패'} · 데이터 {root}")
        system = System(root, log)
        probe = Probe(system, log)
        make_repo(root)
        status = "passed"
        error = None
        try:
            system.start_controller()
            system.start_runner(RUNNER_A)
            wait_until(lambda: probe.runner_state(RUNNER_A) == "connected" or None, "Runner A 연결", timeout=60)
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
        (OUT / "P4-06b-live-results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"결과: {status} · 제품 규칙 {sum(r['ok'] for r in probe.product)}/{len(probe.product)} · 관찰 {len(probe.observations)}")
    return 0 if status == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
