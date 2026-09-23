"""UI-02 라이브 — 실제 codex 가 **도는 동안** 입력을 받고, 중단·Runner 강제 종료 뒤 트리가
실제로 끝났는지를 OS 에서 확인한다.

자동 시험은 가짜 CLI(`tests/fake_cli/fake_codex.py`)로 같은 경로를 본다. 여기서 보는 것은 그것이
**실제 codex 의 프로세스 트리**(`codex.cmd → node → codex.exe → 명령 실행기 → pwsh`)에서도
성립하는가다 — P1-03 #6 에서 `proc.kill()` 뒤에 남았던 바로 그 트리다.

한 업무(기능 Case, 질문 하나가 열린 의도 초안)에서 셋을 본다.

    A. 긴 실행 중 입력    codex 가 셸에서 `Start-Sleep -Seconds 91` 을 도는 동안 같은 Case 의
                         질문 카드 답변과 다른 대화의 메시지가 저장되고, 같은 Case 일반 전송은
                         409 이며, heartbeat·실행 중 보고가 이어진다
    B. 중단               요청 중단 → OS 목록에서 그 트리(pwsh·codex)가 사라지고 요청
                         `interrupted`, 전송이 열린다
    C. Runner 강제 종료   다시 긴 실행 → Runner **프로세스 하나만** 강제 종료(`/T` 없음) → 트리가
                         함께 끝나고, PC 미연결로 전송이 거부되며, 재기동한 Runner 가 CLI 를 다시
                         부르지 않고 원장으로 대조해 `unknown` + 잔류 `none` 을 보고한다

**판정은 두 층이다.** 제품 규칙이 어긋나면 `LiveError` 로 멈춘다. AI 가 지시와 다르게 한 것은
멈추지 않고 관찰로 적는다. **프로세스 확인은 제품 코드가 아니라 OS(`Win32_Process`)에 묻는다** —
제품이 "끝났다"고 한 것을 제품 코드로 확인하면 확인이 아니다.

**제품 코드를 import 하지 않는다.** HTTP 로만 부른다(p3/live/driver.py 와 같은 규칙). 라이브
데이터는 `%LOCALAPPDATA%\\Temp\\hads-ui-02-live` 에 두고 저장소 `var\\` 를 건드리지 않는다.
실행: `.venv\\Scripts\\python.exe ui\\live\\ui02_control.py`
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "p3" / "live"))

from driver import PYTHON, Api, LiveError, Log, stamp, wait_until  # noqa: E402

RUNNER_ID = "runner-ui-02-live"
OUT = REPO_ROOT / "ui" / "evidence"
LIVE_ROOT = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Temp" / "hads-ui-02-live"
PORT = 8798
STALE_SECONDS = 5

SLEEP_A = 91
SLEEP_C = 92


def long_prompt(seconds: int) -> str:
    return (
        f"PowerShell 에서 `Start-Sleep -Seconds {seconds}` 명령 하나만 실행하고 그 명령이 끝날 때까지"
        " 기다린 뒤, 'done' 이라고만 답해 주세요. 파일은 읽거나 수정하지 마세요."
    )


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout


def make_repo(root: Path) -> Path:
    repo = root / "workspace"
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "live@example.invalid")
    _git(repo, "config", "user.name", "live")
    (repo / "README.md").write_text("UI-02 live workspace\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")
    return repo


def os_processes(*needles: str) -> list[dict[str, Any]]:
    """명령줄에 표지가 든 프로세스(OS 에서 직접). 제품 코드를 쓰지 않는다."""
    script = (
        "[Console]::OutputEncoding = [Text.Encoding]::UTF8;"
        " Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,Name,CommandLine"
        " | ConvertTo-Json -Compress"
    )
    # 바이트로 받아 직접 푼다. 명령줄에 한글이 있으면 text=True 의 읽기 스레드가 풀지 못해
    # 출력이 통째로 사라진다(첫 시도에서 실제로 났다).
    raw = subprocess.run(
        ["pwsh", "-NoProfile", "-Command", script], capture_output=True, timeout=60
    ).stdout
    out = raw.decode("utf-8", errors="replace")
    rows = json.loads(out) if out.strip() else []
    rows = rows if isinstance(rows, list) else [rows]
    me = os.getpid()
    return [
        {"pid": r["ProcessId"], "ppid": r["ParentProcessId"], "name": r["Name"],
         "cmd": (r.get("CommandLine") or "")[:300]}
        for r in rows
        if r["ProcessId"] != me
        and any(n in (r.get("CommandLine") or "") for n in needles)
        and "Get-CimInstance" not in (r.get("CommandLine") or "")
    ]


class System:
    """제어부·Runner 프로세스. Runner 를 **따로** 죽이고 다시 띄울 수 있어야 한다."""

    def __init__(self, root: Path, log: Log) -> None:
        self.root = root
        self.log = log
        self.base_url = f"http://127.0.0.1:{PORT}"
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
                HADS_CONTROLLER_DATA=str(data), HADS_WEB_DIST="",
                HADS_RUNNER_STALE_SECONDS=str(STALE_SECONDS),
            ),
            stdout=(data / "uvicorn.log").open("a", encoding="utf-8"),
            stderr=subprocess.STDOUT,
        )
        import httpx

        wait_until(
            lambda: self._healthy(httpx), "제어부 health", timeout=30, interval=0.3
        )

    @staticmethod
    def _healthy(httpx: Any) -> bool:
        try:
            return httpx.get(f"http://127.0.0.1:{PORT}/api/health", timeout=2).status_code == 200
        except httpx.HTTPError:
            return False

    def start_runner(self, tag: str) -> None:
        data = self.root / "runner"
        data.mkdir(parents=True, exist_ok=True)
        self.runner = subprocess.Popen(
            [str(PYTHON), "-m", "runner.agent"],
            cwd=REPO_ROOT,
            env=self._env(
                HADS_RUNNER_DATA=str(data), HADS_RUNNER_ID=RUNNER_ID,
                HADS_CONTROLLER_URL=self.base_url,
            ),
            stdout=(data / f"runner-{tag}.log").open("a", encoding="utf-8"),
            stderr=subprocess.STDOUT,
        )
        self.log(f"Runner 기동 ({tag}) 진입점 pid={self.runner.pid}")

    def ledger(self, run_id: str) -> dict[str, Any]:
        return json.loads(
            (self.root / "runner" / "ledger" / f"{run_id}.json").read_text(encoding="utf-8")
        )

    def effects(self, case_id: str) -> int:
        path = self.root / "runner" / "effects" / f"{case_id}.log"
        return len([l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]) if path.exists() else 0

    def stop(self) -> None:
        for proc in (self.runner, self.controller):
            if proc is not None and proc.poll() is None:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
                proc.wait(timeout=30)


class Probe:
    def __init__(self, api: Api, log: Log, system: System, repo: Path, tag: str) -> None:
        self.api = api
        self.log = log
        self.system = system
        self.repo = repo
        self.tag = tag
        self.product: list[dict[str, Any]] = []
        self.observations: list[dict[str, Any]] = []
        self.facts: dict[str, Any] = {}

    # --------------------------------------------------------------- 판정
    def rule(self, name: str, ok: bool, detail: Any = None) -> None:
        self.product.append({"rule": name, "ok": bool(ok), "detail": detail})
        self.log(f"[{'OK' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail is not None else ""))
        if not ok:
            raise LiveError(f"제품 규칙 위반: {name}: {detail}")

    def observe(self, name: str, detail: Any) -> None:
        self.observations.append({"observation": name, "detail": detail})
        self.log(f"[관찰] {name} — {detail}")

    # --------------------------------------------------------------- HTTP
    def send(self, case_id: str, text: str, cid: str, **extra: Any):
        body = {
            "client_message_id": cid, "kind": extra.pop("kind", "general"), "content": text,
            "summary": f"사용자 메시지 · {len(text)}자", "target_runner_id": RUNNER_ID, **extra,
        }
        return self.api.request("POST", f"/api/cases/{case_id}/messages", json=body)

    def stored(self, case_id: str, cid: str) -> bool:
        response = self.api.request("GET", f"/api/cases/{case_id}/messages/by-client-id/{cid}")
        return response.status_code == 200 and response.json()["receipt"] == "stored"

    def request(self, case_id: str, request_id: str) -> dict[str, Any]:
        view = self.api.get(f"/api/cases/{case_id}/conversation")
        return next(r for r in view["requests"] if r["id"] == request_id)

    def reply_run(self, case_id: str, message: dict, request_id: str, run_id: str) -> None:
        self.api.ok("POST", f"/api/cases/{case_id}/runs", json={
            "run_id": run_id,
            "instruction_artifact_id": message["artifact_id"],
            "instruction_artifact_rev": message["artifact_rev"],
            "purpose": "discussion_reply", "role": "author", "tool_id": "codex", "mode": "exec",
            "permission": "read_only", "request_id": request_id,
        }, expect=(201,))

    def long_request(self, case_id: str, seconds: int, cid: str, run_id: str) -> str:
        sent = self.send(case_id, long_prompt(seconds), cid)
        if sent.status_code != 202:
            raise LiveError(f"긴 요청 전송 실패: {sent.status_code} {sent.text}")
        wait_until(lambda: self.stored(case_id, cid), f"{cid} 저장", timeout=30, interval=0.5)
        request_id = sent.json()["request"]["id"]
        self.reply_run(case_id, sent.json()["message"], request_id, run_id)
        return request_id

    # ============================================================ 흐름
    def run(self) -> None:
        api, log = self.api, self.log
        runners = api.get("/api/runners")
        codex = next(
            (c for r in runners for c in r["capabilities"]
             if c["tool_id"] == "codex" and c["capability"] == "installed"), None
        )
        self.facts["codex_installed"] = codex
        self.facts["process_tree_control"] = next(
            (c for r in runners for c in r["capabilities"]
             if c["tool_id"] == "codex" and c["capability"] == "process_tree_control"), None
        )
        project = api.ok("POST", "/api/projects", json={
            "name": f"ui02-live-{self.tag}", "repo_path": str(self.repo), "default_tool_id": "codex"
        })
        case = api.ok("POST", f"/api/projects/{project['id']}/cases",
                      json={"title": "긴 실행 업무", "kind": "feature"})
        case_id = case["id"]
        side = api.ok("POST", f"/api/projects/{project['id']}/conversations", json={"title": "옆 대화"})
        # 질문이 하나 열린 의도 초안(사람이 쓴 것). 카드 답변의 대상이다.
        api.ok("POST", f"/api/cases/{case_id}/intent-drafts", json={
            "summary": "의도 초안", "target_runner_id": RUNNER_ID,
            "fields": {
                "goal": {"text": "셸 대기 명령으로 실행 제어를 확인한다.", "state": "proposed",
                         "origin": "user_requirement"},
                "expected_outcome": {"text": "중단과 재시작 대조가 동작한다.", "state": "proposed",
                                     "origin": "ai_proposal"},
                "scope": {"text": "읽기 전용 논의 응답.", "state": "proposed",
                          "origin": "user_requirement"},
            },
            "questions": [{"key": "q-live", "text": "대기 시간을 줄일까요?", "summary": "대기 시간",
                           "decide_at": "intent"}],
            "criteria": [], "sizing": None, "reflects_feedback": [], "not_reflected": {},
        }, expect=(202,))
        state = wait_until(
            lambda: (lambda s: s if s.get("open_intent_questions") else None)(
                api.get(f"/api/cases/{case_id}/intent-state")),
            "의도 초안 구조(열린 질문)", timeout=30, interval=0.5,
        )
        question = state["open_intent_questions"][0]
        intent = {"id": question["intent_version_id"]}

        # ------------------------------------------------------------ A
        log.head("A. 긴 실행 중 입력")
        run_a = f"run-ui02-a-{self.tag}"
        started = time.monotonic()
        request_a = self.long_request(case_id, SLEEP_A, f"c-a-{self.tag}", run_a)
        sleeping = wait_until(
            lambda: os_processes(f"Start-Sleep -Seconds {SLEEP_A}"),
            "codex 가 셸 대기를 시작함", timeout=240, interval=2,
        )
        self.facts["A_seconds_until_sleep"] = round(time.monotonic() - started, 1)
        tree_a = os_processes(f"Start-Sleep -Seconds {SLEEP_A}", str(self.repo))
        self.facts["A_tree_before_stop"] = tree_a
        log.json("A 트리(OS)", tree_a)
        # 같은 Case 의 카드 답변 — 처리 중에도 대상이 유효하면 받는다.
        card = self.send(case_id, "줄이지 말고 그대로 두세요.", f"c-card-{self.tag}",
                         kind="card_answer", question_id=question["id"],
                         intent_version_id=intent["id"])
        self.rule("A 카드 답변 접수 대기(202)", card.status_code == 202, card.status_code)
        t0 = time.monotonic()
        wait_until(lambda: self.stored(case_id, f"c-card-{self.tag}"), "카드 답변 저장",
                   timeout=15, interval=0.3)
        self.facts["A_card_stored_seconds"] = round(time.monotonic() - t0, 2)
        other = self.send(side["case_id"], "그동안 이것도 받아 주세요.", f"c-side-{self.tag}")
        t0 = time.monotonic()
        wait_until(lambda: self.stored(side["case_id"], f"c-side-{self.tag}"), "다른 대화 저장",
                   timeout=15, interval=0.3)
        self.facts["A_side_stored_seconds"] = round(time.monotonic() - t0, 2)
        self.rule("A 실행 중 다른 대화 메시지 저장", other.status_code == 202)
        # 옆 대화의 요청은 여기서 닫는다 — C 에서 PC 미연결 **하나만**의 거부를 보려고.
        # (닫지 않으면 요청 잠금과 미연결이 함께 걸리고 제어부는 둘 다 돌려준다 — 2회차 관찰)
        api.ok("POST", f"/api/cases/{side['case_id']}/requests/{other.json()['request']['id']}/settle",
               json={"outcome": "completed", "actor": "system"})
        blocked = self.send(case_id, "다음 질문", f"c-blocked-{self.tag}")
        self.rule("A 같은 Case 일반 전송은 409 request_in_progress",
                  blocked.status_code == 409 and api.refusals(blocked) == ["request_in_progress"],
                  api.refusals(blocked))
        # 입력을 저장하는 동안 **실행이 끝나지 않았다** — 저장이 실행 종료를 기다린 것이 아니다.
        status = api.get(f"/api/runs/{run_a}")["status"]
        self.rule("A 입력 저장 동안 실행이 끝나지 않음", status in ("assigned", "running"), status)
        self.facts["A_sleep_still_running_after_inputs"] = bool(
            os_processes(f"Start-Sleep -Seconds {SLEEP_A}")
        )
        live = self.request(case_id, request_a)
        self.rule("A 실행 중 보고", live["runs"][0]["execution_state"] == "executing",
                  live["runs"][0]["execution_state"])
        runner = next(r for r in api.get("/api/runners") if r["id"] == RUNNER_ID)
        self.facts["A_runner_last_heartbeat"] = runner["last_heartbeat_at"]

        # ------------------------------------------------------------ B
        log.head("B. 중단")
        stop = api.ok("POST", f"/api/cases/{case_id}/requests/{request_a}/stop",
                      json={"actor": "owner", "reason": "라이브 중단"})
        self.rule("B 중단 요청 직후는 중단 요청 중(처리 중)", stop["stopping"] is True, stop["state"])
        t0 = time.monotonic()
        done = wait_until(
            lambda: (lambda r: r if r["state"] != "processing" else None)(self.request(case_id, request_a)),
            "중단 확인", timeout=90, interval=0.5,
        )
        self.facts["B_stop_to_settled_seconds"] = round(time.monotonic() - t0, 2)
        self.rule("B 요청 interrupted(stopped_by_request)",
                  (done["state"], done["outcome_reason"]) == ("interrupted", "stopped_by_request"),
                  (done["state"], done["outcome_reason"]))
        run = api.get(f"/api/runs/{run_a}")
        self.facts["B_run"] = {k: run.get(k) for k in (
            "outcome", "residual_activity", "stop_requested_at", "stop_delivered_at",
            "session_ref", "exit_code", "observed_tool_version")}
        self.facts["B_observations"] = run["residual_observations"]
        self.rule("B 실행 cancelled + 잔류 none",
                  (run["outcome"], run["residual_activity"]) == ("cancelled", "none"),
                  (run["outcome"], run["residual_activity"]))
        self.rule("B 근거 job_terminated",
                  run["residual_observations"][0]["basis"] == "job_terminated",
                  run["residual_observations"])
        time.sleep(1)
        left = os_processes(f"Start-Sleep -Seconds {SLEEP_A}", str(self.repo))
        self.facts["B_tree_after_stop"] = left
        self.rule("B OS 에 그 트리(pwsh 대기·codex)가 남지 않음", left == [], left)
        again = self.send(case_id, "중단 뒤 이어서 이야기해요.", f"c-after-{self.tag}")
        self.rule("B 중단 확인 뒤 전송 열림(202)", again.status_code == 202, again.status_code)
        wait_until(lambda: self.stored(case_id, f"c-after-{self.tag}"), "중단 뒤 메시지 저장",
                   timeout=15, interval=0.3)
        after_request = again.json()["request"]["id"]
        api.ok("POST", f"/api/cases/{case_id}/requests/{after_request}/settle",
               json={"outcome": "completed", "actor": "system"})

        # ------------------------------------------------------------ C
        log.head("C. Runner 강제 종료")
        effects_before = self.system.effects(case_id)
        run_c = f"run-ui02-c-{self.tag}"
        request_c = self.long_request(case_id, SLEEP_C, f"c-c-{self.tag}", run_c)
        wait_until(lambda: os_processes(f"Start-Sleep -Seconds {SLEEP_C}"),
                   "두 번째 셸 대기", timeout=240, interval=2)
        tree_c = os_processes(f"Start-Sleep -Seconds {SLEEP_C}", str(self.repo))
        self.facts["C_tree_before_kill"] = tree_c
        ledger = self.system.ledger(run_c)
        self.facts["C_ledger"] = {k: ledger.get(k) for k in ("ledger_version", "state", "launch", "runner_process")}
        self.rule("C 원장 v2·시작 기록(KILL_ON_JOB_CLOSE)",
                  ledger["ledger_version"] == 2 and ledger["launch"]["kill_on_close"] is True)
        runner_pid = ledger["runner_process"]["pid"]
        killed = subprocess.run(["taskkill", "/F", "/PID", str(runner_pid)], capture_output=True, text=True)
        log(f"Runner 프로세스 pid={runner_pid} 만 강제 종료: {killed.stdout.strip()} {killed.stderr.strip()}")
        t0 = time.monotonic()
        gone = wait_until(
            lambda: (lambda l: "gone" if not l else None)(
                os_processes(f"Start-Sleep -Seconds {SLEEP_C}", str(self.repo))),
            "Runner 와 함께 트리 종료", timeout=30, interval=0.5,
        )
        self.facts["C_tree_gone_seconds"] = round(time.monotonic() - t0, 2)
        self.rule("C Runner 만 죽여도 CLI 트리가 끝남(OS)", gone == "gone")
        if self.system.runner is not None and self.system.runner.poll() is None:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.system.runner.pid)], capture_output=True)
        wait_until(
            lambda: api.get(f"/api/cases/{side['case_id']}/conversation")["send"]["runner_connection"]["state"]
            == "disconnected", "PC 미연결 판정", timeout=30, interval=0.5,
        )
        refused = self.send(side["case_id"], "끊긴 동안 보냅니다.", f"c-off-{self.tag}")
        self.rule("C PC 미연결 전송 409 runner_disconnected",
                  refused.status_code == 409 and api.refusals(refused) == ["runner_disconnected"],
                  (refused.status_code, api.refusals(refused)))
        self.rule("C 끊긴 동안 실행은 끝나지 않은 채",
                  api.get(f"/api/runs/{run_c}")["status"] in ("assigned", "running"))

        self.system.start_runner("restart")
        reported = wait_until(
            lambda: (lambda r: r if r["status"] == "finished" else None)(api.get(f"/api/runs/{run_c}")),
            "재기동 대조", timeout=90, interval=0.5,
        )
        self.facts["C_reported"] = {k: reported.get(k) for k in (
            "outcome", "residual_activity", "assignment_generation", "session_ref", "usage")}
        self.facts["C_observations"] = reported["residual_observations"]
        self.rule("C 결과 unknown + 잔류 none",
                  (reported["outcome"], reported["residual_activity"]) == ("unknown", "none"),
                  (reported["outcome"], reported["residual_activity"]))
        self.rule("C 근거 reconcile/job_closed_kill_on_close",
                  [(o["source"], o["basis"]) for o in reported["residual_observations"]]
                  == [("reconcile", "job_closed_kill_on_close")], reported["residual_observations"])
        self.rule("C 세대를 올리지 않음", reported["assignment_generation"] == 1)
        time.sleep(3)
        effects_after = self.system.effects(case_id)
        self.rule("C CLI 를 다시 부르지 않음(부수효과 1회)", effects_after - effects_before == 1,
                  (effects_before, effects_after))
        self.rule("C 원시 출력에서 세션을 되찾음", bool(reported.get("session_ref")),
                  reported.get("session_ref"))
        settled = api.ok("POST", f"/api/cases/{case_id}/requests/{request_c}/settle",
                         json={"outcome": "failed", "actor": "system"})
        self.rule("C 요청 interrupted(execution_ended_result_unknown)",
                  (settled["state"], settled["outcome_reason"])
                  == ("interrupted", "execution_ended_result_unknown"),
                  (settled["state"], settled["outcome_reason"]))
        wait_until(
            lambda: api.get(f"/api/cases/{side['case_id']}/conversation")["send"]["runner_connection"]["state"]
            == "connected", "재연결", timeout=30, interval=0.5,
        )
        side_messages = [m["client_message_id"] for m in api.get(f"/api/cases/{side['case_id']}/conversation")["messages"]]
        self.rule("C 재연결 뒤 자동으로 보내진 것 없음", side_messages == [f"c-side-{self.tag}"], side_messages)
        resent = self.send(side["case_id"], "끊긴 동안 보냅니다.", f"c-off-{self.tag}")
        self.rule("C 사람이 다시 보내면 받음(202)", resent.status_code == 202, resent.status_code)
        self.facts["repo_unchanged"] = _git(self.repo, "status", "--porcelain")


def main() -> int:
    tag = stamp()
    root = LIVE_ROOT / tag
    root.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    with Log(OUT / "UI-02-live.log") as log:
        log(f"UI-02 라이브 tag={tag} root={root}")
        version = subprocess.run(["codex", "--version"], capture_output=True, text=True, shell=True)
        log(f"codex --version: {version.stdout.strip()}")
        system = System(root, log)
        repo = make_repo(root)
        api = Api(system.base_url, log)
        probe = Probe(api, log, system, repo, tag)
        probe.facts["codex_version"] = version.stdout.strip()
        error: str | None = None
        try:
            system.start_controller()
            system.start_runner("first")
            wait_until(lambda: any(r["id"] == RUNNER_ID for r in api.get("/api/runners")),
                       "Runner 등록", timeout=60, interval=0.5)
            probe.run()
        except LiveError as exc:
            error = str(exc)
            log(f"LiveError: {exc}")
        finally:
            api.close()
            system.stop()
            leftovers = os_processes(str(repo), f"Start-Sleep -Seconds {SLEEP_A}",
                                     f"Start-Sleep -Seconds {SLEEP_C}")
            probe.facts["leftovers_after_shutdown"] = leftovers
            for proc in leftovers:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc["pid"])], capture_output=True)
            result = {
                "tag": tag,
                "root": str(root),
                "error": error,
                "product_rules": probe.product,
                "observations": probe.observations,
                "facts": probe.facts,
            }
            (OUT / "UI-02-live-results.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            log(f"제품 규칙 {sum(r['ok'] for r in probe.product)}/{len(probe.product)} 통과"
                + (f", 오류: {error}" if error else ""))
    return 1 if error else 0


if __name__ == "__main__":
    sys.exit(main())
