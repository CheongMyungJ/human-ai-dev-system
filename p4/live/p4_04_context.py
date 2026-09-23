"""P4-04 라이브 — 실제 codex 가 **생략 표시가 있는 문맥**으로 답하고, 실제 강제 종료 뒤
Runner 가 원시 출력에서 사용량·세션을 되찾는가.

P4-04 는 새 **지시문 문구**(크기 한도로 넣지 않은 자료의 표시)와 새 **재시작 경로**(원시
출력 복구)를 만들었다. 자동 시험은 `FakeCliExecutor` 가 정해진 글을 내고 원시 출력도 P1
증거를 복사해 쓰므로, 실제 AI 가 생략 표시를 어떻게 다루는지와 실제로 죽은 CLI 가 남긴
원시 출력이 어떤 모양인지는 볼 수 없다. 그래서 실제 CLI 로 확인한다.

한 대화에서 넷을 본다.

    A·B. 논의 응답 두 번     문맥을 쌓는다(사용자 금지, AI 제안 둘)
    C.   생략된 문맥의 응답  한도를 줄여 **A 의 AI 응답만** 생략되게 한 뒤 "당신의 첫 제안을
                            요약해 달라"고 묻는다. 생략된 내용을 지어내지 않는가, 남은 사용자
                            금지를 따르는가, 저장소를 바꾸지 않는가
    D.   실행 중 강제 종료   CLI 가 도는 동안 Runner 프로세스 트리를 `taskkill /F /T` 로
                            죽이고 다시 띄워 재배정한다. CLI 를 다시 부르지 않고 원시 출력에서
                            되찾은 것만 보고하는가

**판정은 두 층이다.** 제품 규칙(계획·영수증·예약·재실행 없음·결과 불명 유지)이 어긋나면
`LiveError` 로 멈춘다. AI 가 지시와 다르게 쓴 것은 멈추지 않고 **관찰로 기록한다**.
표본은 한 대화뿐이다.

**제품 코드를 import 하지 않는다.** HTTP 로만 부른다(p3/live/driver.py 와 같은 규칙).
라이브 데이터는 `%LOCALAPPDATA%\\Temp\\hads-p4-04-live` 에 두고 저장소 `var\\` 를 건드리지
않는다. 실행: `.venv\\Scripts\\python.exe p4\\live\\p4_04_context.py`
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "p3" / "live"))

from driver import (  # noqa: E402
    PYTHON,
    Api,
    LiveError,
    Log,
    Processes,
    stamp,
    wait_until,
)

RUNNER_ID = "runner-p4-04-live"
TOOL = {"tool_id": "codex", "mode": "exec"}
OUT = REPO_ROOT / "p4" / "evidence"
LIVE_ROOT = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Temp" / "hads-p4-04-live"
PORT = 8797

STORE_PY = '''"""작은 저장소 — 라이브 시험용."""
import json
from pathlib import Path

_CACHE: dict[str, list[dict]] = {}
PATH = Path("items.json")


def list_items() -> list[dict]:
    if "items" in _CACHE:
        return _CACHE["items"]
    data = json.loads(PATH.read_text(encoding="utf-8")) if PATH.exists() else []
    _CACHE["items"] = data
    return data


def save(item_id: str, value: str) -> None:
    data = json.loads(PATH.read_text(encoding="utf-8")) if PATH.exists() else []
    for item in data:
        if item["id"] == item_id:
            item["value"] = value
    PATH.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
'''

M1 = (
    "우리 `store.py` 의 `list_items()` 캐시에 대해 이야기하고 싶어요. 캐시를 없앨지, 무효화를"
    " 넣을지 당신의 제안을 **번호를 붙여 세 가지** 주세요.\n\n"
    "**아직 코드나 문서는 수정하지 마세요.** 지금은 의견만 주세요."
)
M2 = "고마워요. 그중 가장 작은 변경은 무엇인지 한 문장으로만 말해 주세요."
M3 = (
    "당신이 **첫 번째 답에서** 제안한 세 가지를 번호대로 다시 요약해 주세요."
    " 그리고 제가 처음에 무엇을 하지 말라고 했는지도 확인해 주세요."
)
M4 = (
    "`store.py` 를 읽고, 캐시를 없앴을 때 `list_items()`·`save()` 의 성능과 정확성이 각각"
    " 어떻게 달라지는지 호출 흐름을 따라 자세히 설명해 주세요. 코드는 수정하지 마세요."
)

#: "했다"고 주장하는 표현. 논의 응답은 아무 것도 바꾸지 않으므로 이런 말은 관찰 대상이다.
CLAIM = re.compile(r"(수정했|고쳤|변경했|적용했|추가했|만들었|작성했)")
#: 생략된 자료를 볼 수 없다고 밝히는 표현.
#: **넓은 표현("없습니다")은 넣지 않는다** — 다른 문장에도 흔해 거짓 통과를 만든다.
UNSEEN = re.compile(r"(넣지 않|생략|볼 수 없|보이지 않|제공되지 않|확인할 수 없|포함되지 않|읽지 못)")


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
    (repo / "store.py").write_text(STORE_PY, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")
    return repo


def tree_state(repo: Path) -> dict[str, str]:
    """관측한 저장소 상태. **바뀌지 않았다는 것은 이 두 값이 같다는 뜻뿐이다.**"""
    return {
        "head": _git(repo, "rev-parse", "HEAD").strip(),
        "status": _git(repo, "status", "--porcelain", "--untracked-files=all"),
    }


class Probe:
    def __init__(self, api: Api, log: Log, procs: Processes, repo: Path, tag: str) -> None:
        self.api = api
        self.log = log
        self.procs = procs
        self.repo = repo
        self.tag = tag
        self.case_id = ""
        self.observations: list[dict[str, Any]] = []
        self.product: list[dict[str, Any]] = []
        self.facts: dict[str, Any] = {}

    # ---------------------------------------------------------- 도우미

    def must(self, name: str, ok: bool, detail: str) -> None:
        """**제품 규칙.** 어긋나면 멈춘다."""
        self.product.append({"check": name, "ok": ok, "detail": detail})
        self.log(f"  [{'규칙 OK' if ok else '규칙 위반'}] {name}: {detail}")
        if not ok:
            raise LiveError(f"{name}: {detail}")

    def observe(self, name: str, ok: bool, detail: str) -> None:
        """**AI 가 지시를 따랐는가.** 멈추지 않고 기록한다."""
        self.observations.append({"check": name, "ok": ok, "detail": detail})
        self.log(f"  [{'OK' if ok else '관찰'}] {name}: {detail}")

    def send(self, text: str, cid: str) -> dict[str, Any]:
        sent = self.api.ok(
            "POST",
            f"/api/cases/{self.case_id}/messages",
            json={
                "client_message_id": f"{cid}-{self.tag}",
                "content": text,
                # 요약은 제어부에 남는다. **본문에서 잘라 내지 않는다**(D-51·D-84).
                "summary": f"라이브 메시지 {cid}",
                "target_runner_id": RUNNER_ID,
            },
        )
        found = wait_until(
            lambda: (lambda r: r if r["receipt"] == "stored" else None)(
                self.api.get(
                    f"/api/cases/{self.case_id}/messages/by-client-id/{cid}-{self.tag}"
                )
            ),
            f"{cid} 접수",
            timeout=120,
        )
        return {**sent, "message": found["message"]}

    def read(self, artifact_id: str, revision: int) -> str:
        created = self.api.ok(
            "POST", f"/api/artifacts/{artifact_id}/{revision}/read-requests", json={}
        )
        served = wait_until(
            lambda: (lambda r: r if r["content"] is not None else None)(
                self.api.get(f"/api/read-requests/{created['id']}")
            ),
            "원문 전달",
            timeout=180,
        )
        return served["content"]

    def create_reply_run(self, sent: dict[str, Any], run_id: str) -> None:
        message = sent["message"]
        response = self.api.request(
            "POST",
            f"/api/cases/{self.case_id}/runs",
            json={
                "run_id": run_id,
                "instruction_artifact_id": message["artifact_id"],
                "instruction_artifact_rev": message["artifact_rev"],
                "purpose": "discussion_reply",
                "role": "author",
                "permission": "read_only",
                "request_id": sent["request"]["id"],
                **TOOL,
            },
        )
        if response.status_code not in (200, 201):
            raise LiveError(f"{run_id} 실행이 거부됐다 {response.status_code}\n{response.text}")

    def reply(self, sent: dict[str, Any], letter: str) -> tuple[dict[str, Any], str]:
        """논의 응답 실행. 지시는 그 요청을 연 메시지다."""
        before = tree_state(self.repo)
        run_id = f"run-p404-{letter}-{self.tag}"
        self.create_reply_run(sent, run_id)
        run = wait_until(
            lambda: (lambda r: r if r["status"] == "finished" else None)(
                self.api.get(f"/api/runs/{run_id}")
            ),
            f"{letter} 논의 응답",
        )
        self.log(
            f"run {run_id} outcome={run['outcome']} version={run.get('observed_tool_version')}"
            f" context={run['context']['state']}"
        )
        self.must(f"{letter}_completed", run["outcome"] == "completed",
                  f"논의 응답 outcome={run['outcome']}")
        after = tree_state(self.repo)
        self.observe(f"{letter}_repository_unchanged", before == after,
                     f"HEAD·작업 트리 {'같음' if before == after else '달라짐'}")
        view = self.api.get(f"/api/cases/{self.case_id}/conversation")
        replies = [m for m in view["messages"] if m["run_id"] == run_id]
        self.must(f"{letter}_one_assistant_message", len(replies) == 1,
                  f"이 실행의 AI 메시지 {len(replies)}건")
        text = self.read(replies[0]["artifact_id"], replies[0]["artifact_rev"])
        (OUT / f"P4-04-live-{letter}-reply.txt").write_text(text, encoding="utf-8")
        return run, text.split("--- final message ---", 1)[-1].strip()

    def settle(self, sent: dict[str, Any], outcome: str = "completed") -> dict[str, Any]:
        return self.api.ok(
            "POST",
            f"/api/cases/{self.case_id}/requests/{sent['request']['id']}/settle",
            json={"outcome": outcome, "actor": "live-harness"},
        )

    def sizes(self) -> dict[str, int]:
        detail = self.api.get(f"/api/cases/{self.case_id}")
        return {a["artifact_id"]: int(a["byte_size"]) for a in detail["artifacts"]}

    # ------------------------------------------------------------ 흐름

    def run_all(self) -> None:
        project = self.api.ok(
            "POST",
            "/api/projects",
            json={"name": f"p4-04-live-{self.tag}", "repo_path": str(self.repo),
                  "default_tool_id": "codex"},
        )
        view = self.api.ok(
            "POST", f"/api/projects/{project['id']}/conversations",
            json={"title": "캐시 이야기"},
        )
        self.case_id = view["case_id"]

        # A·B ------------------------------------------------------------
        self.log.head("A·B. 문맥을 쌓는다 — 기본 한도")
        first = self.send(M1, "m1")
        run_a, reply_a = self.reply(first, "A")
        self.log.json("A 응답", reply_a[:2000])
        self.must("A_context_complete", run_a["context"]["state"] == "complete",
                  f"A 문맥 {run_a['context']['state']}")
        self.settle(first)
        second = self.send(M2, "m2")
        run_b, reply_b = self.reply(second, "B")
        self.log.json("B 응답", reply_b[:1500])
        self.must("B_context_complete", run_b["context"]["state"] == "complete",
                  f"B 문맥 {run_b['context']['state']} (한도 {run_b['context']['limit']})")
        self.settle(second)

        # C --------------------------------------------------------------
        self.log.head("C. A 의 AI 응답만 생략되는 한도에서 첫 제안을 묻는다")
        third = self.send(M3, "m3")
        messages = self.api.get(f"/api/cases/{self.case_id}/conversation")["messages"]
        a_msg, b_msg = messages[1], messages[3]
        sizes = self.sizes()
        keep = [third["message"], first["message"], second["message"], b_msg]
        limit = sum(sizes[m["artifact_id"]] for m in keep) + 16
        self.must("A_is_the_larger_ai_message",
                  sizes[a_msg["artifact_id"]] > 16,
                  f"A 응답 {sizes[a_msg['artifact_id']]}B, B 응답 {sizes[b_msg['artifact_id']]}B")
        self.facts["limit_c"] = limit
        self.facts["sizes"] = {
            "instruction_m3": sizes[third["message"]["artifact_id"]],
            "user_m1": sizes[first["message"]["artifact_id"]],
            "user_m2": sizes[second["message"]["artifact_id"]],
            "assistant_a": sizes[a_msg["artifact_id"]],
            "assistant_b": sizes[b_msg["artifact_id"]],
        }
        # 한도는 제어부 설정이다. 설정을 바꿔 제어부만 다시 띄운다 — 기록은 DB 에 있다.
        os.environ["HADS_CONTEXT_INLINE_LIMIT_BYTES"] = str(limit)
        self.procs.kill_controller()
        self.procs.restart_controller()
        self.api.reconnect()
        run_c, reply_c = self.reply(third, "C")
        refs = self.api.get(f"/api/runs/{run_c['run_id']}/context-refs")
        shape = [(r["role"], r["inclusion"], r["receipt_status"]) for r in refs]
        self.must(
            "C_only_old_ai_message_omitted",
            shape == [
                ("conversation_user_message", "inline", "read"),
                ("conversation_assistant_message", "omitted_size_limit", "omitted"),
                ("conversation_user_message", "inline", "read"),
                ("conversation_assistant_message", "inline", "read"),
            ],
            f"참조 {shape}",
        )
        self.must("C_omitted_is_A", refs[1]["artifact_id"] == a_msg["artifact_id"],
                  f"생략된 참조 {refs[1]['artifact_id']}")
        context = run_c["context"]
        self.must("C_context_partial", context["state"] == "partial", context["state"])
        self.must("C_limit_recorded", run_c["context_inline_limit"] == limit,
                  f"기록된 한도 {run_c['context_inline_limit']} / 설정 {limit}")
        budget = self.api.get(f"/api/cases/{self.case_id}/budget")
        reserved = next(
            r for r in budget["reservations"]
            if r["run_id"] == run_c["run_id"] and r["metric"] == "context_bytes"
        )
        self.must("C_reserved_is_inline_package",
                  reserved["reserved_value"] == context["inline_bytes"] <= limit,
                  f"예약 {reserved['reserved_value']} = 인라인 {context['inline_bytes']}"
                  f" ≤ 한도 {limit}")
        self.log.json("C 응답", reply_c[:2000])
        self.observe("C_says_it_cannot_see_the_first_reply", bool(UNSEEN.search(reply_c)),
                     "첫 답을 볼 수 없다고 밝혔는가")
        self.observe("C_recalls_prohibition",
                     bool(re.search(r"(수정|고치|문서|코드)", reply_c)),
                     "남아 있는 사용자 금지(코드·문서 수정 금지)를 확인했는가")
        claims = CLAIM.findall(reply_c)
        self.observe("C_no_work_claim", not claims, f"작업 주장 표현 {claims or '없음'}")
        self.settle(third)

        # D --------------------------------------------------------------
        self.log.head("D. 실행 중 Runner 강제 종료 → 재시작 → 원시 출력 복구")
        os.environ.pop("HADS_CONTEXT_INLINE_LIMIT_BYTES", None)
        self.procs.kill_controller()
        self.procs.restart_controller()
        self.api.reconnect()
        # **CLI 가 도는 동안** 죽여야 한다. 원시 출력에서 세션 시작(`thread.started`)을 보는
        # 즉시 Runner 프로세스 트리를 죽인다. 그 사이 CLI 가 먼저 끝나 결과가 보고되면
        # 그것은 하네스 타이밍의 문제이며 제품 판정이 아니다 — 새 메시지로 다시 한다.
        for attempt in range(1, 4):
            fourth = self.send(M4, f"m4-{attempt}")
            run_id = f"run-p404-D{attempt}-{self.tag}"
            raw = self.procs.data_root / "runner" / "raw" / f"{run_id}.stdout.jsonl"
            effects = self.procs.data_root / "runner" / "effects" / f"{self.case_id}.log"
            effects_before = (
                effects.read_text(encoding="utf-8").count(run_id) if effects.exists() else 0
            )
            self.create_reply_run(fourth, run_id)
            wait_until(
                lambda: raw.exists()
                and "thread.started" in raw.read_text(encoding="utf-8", errors="replace"),
                "D CLI 시작(원시 출력의 thread.started)",
                timeout=180,
                interval=0.1,
            )
            killed = subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(self.procs.runner.pid)],
                capture_output=True, text=True,
            )
            self.procs.runner.wait(timeout=30)
            self.log(f"Runner 트리 강제 종료: {killed.stdout.strip() or killed.stderr.strip()}")
            before_restart = self.api.get(f"/api/runs/{run_id}")
            if before_restart["status"] != "finished":
                break
            self.log(f"  (하네스) 시도 {attempt}: 죽이기 전에 실행이 끝났다 — 다시 한다")
            self.facts.setdefault("d_attempts_finished_before_kill", []).append(run_id)
            self.settle(fourth)
            self.restart_runner()
        else:
            raise LiveError("세 번 모두 CLI 가 죽이기 전에 끝났다 — 실행 중 종료를 만들지 못했다")
        raw_text = raw.read_text(encoding="utf-8", errors="replace")
        (OUT / "P4-04-live-D-raw.stdout.jsonl").write_text(raw_text, encoding="utf-8")
        raw_lines = [line for line in raw_text.splitlines() if line.strip()]
        usage_in_raw = any('"turn.completed"' in line for line in raw_lines)
        self.facts["d_run_id"] = run_id
        self.facts["d_raw_lines"] = len(raw_lines)
        self.facts["d_raw_has_usage"] = usage_in_raw
        self.must("D_not_finished_before_restart", before_restart["status"] != "finished",
                  f"강제 종료 뒤 상태 {before_restart['status']}")

        self.restart_runner()
        self.api.ok("POST", f"/api/runs/{run_id}/reassign", json={})
        run_d = wait_until(
            lambda: (lambda r: r if r["status"] == "finished" else None)(
                self.api.get(f"/api/runs/{run_id}")
            ),
            "D 재시작 뒤 보고",
            timeout=120,
        )
        effects_after = effects.read_text(encoding="utf-8").count(run_id) if effects.exists() else 0
        self.must("D_cli_not_called_again", effects_after == effects_before + 1,
                  f"이 실행의 CLI 호출 기록 {effects_before} → {effects_after}")
        self.must("D_outcome_unknown", run_d["outcome"] == "unknown", run_d["outcome"])
        thread = re.search(r'"thread_id":"([^"]+)"', raw_text)
        self.must("D_session_recovered",
                  thread is not None and run_d["session_ref"] == thread.group(1),
                  f"session_ref {run_d['session_ref']} / 원시 출력 {thread.group(1) if thread else None}")
        rows = {
            r["metric"]: r for r in self.api.get(f"/api/cases/{self.case_id}/budget")["reservations"]
            if r["run_id"] == run_id and r["generation"] == run_d["assignment_generation"]
        }
        tokens = rows.get("input_tokens", {})
        if usage_in_raw:
            self.must("D_usage_recovered",
                      tokens.get("settle_source") == "recovered_from_runner_log",
                      f"토큰 {tokens.get('actual_value')} {tokens.get('settle_source')}")
        else:
            self.must("D_usage_not_invented",
                      tokens.get("actual_value") is None
                      and tokens.get("settle_source") == "outcome_unknown",
                      f"원시 출력에 사용량 없음 → 토큰 {tokens.get('actual_value')}"
                      f" {tokens.get('settle_source')}")
        self.must("D_seconds_unresolved",
                  rows.get("execution_seconds", {}).get("state") == "unresolved",
                  f"실행 시간 {rows.get('execution_seconds', {}).get('state')}")
        request = next(
            r for r in self.api.get(f"/api/cases/{self.case_id}/conversation")["requests"]
            if r["id"] == fourth["request"]["id"]
        )
        settled = self.api.request(
            "POST",
            f"/api/cases/{self.case_id}/requests/{fourth['request']['id']}/settle",
            json={"outcome": "completed", "actor": "live-harness"},
        )
        after = self.api.get(f"/api/cases/{self.case_id}/conversation")["requests"]
        state = next(r["state"] for r in after if r["id"] == fourth["request"]["id"])
        self.must("D_request_not_completed",
                  state == "unknown",
                  f"불명 실행의 요청 {request['state']} → 종료 기록 {settled.status_code} → {state}")
        self.facts["d_run"] = {
            "outcome": run_d["outcome"],
            "session_ref": run_d["session_ref"],
            "usage": run_d["usage"],
            "context": run_d["context"]["state"],
        }

    def restart_runner(self) -> None:
        runner_data = self.procs.data_root / "runner"
        self.procs.runner = subprocess.Popen(
            [str(PYTHON), "-m", "runner.agent"],
            cwd=REPO_ROOT,
            env=self.procs._env(
                HADS_RUNNER_DATA=str(runner_data),
                HADS_RUNNER_ID=self.procs.runner_id,
                HADS_CONTROLLER_URL=self.procs.base_url,
            ),
            stdout=(runner_data / "runner-restart.log").open("w", encoding="utf-8"),
            stderr=subprocess.STDOUT,
            text=True,
        )
        self.log(f"Runner 재시작 pid={self.procs.runner.pid}")


def main() -> int:
    tag = stamp()
    root = LIVE_ROOT / tag
    root.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    os.environ.pop("HADS_CONTEXT_INLINE_LIMIT_BYTES", None)
    with Log(OUT / "P4-04-live.log") as log:
        log.head(f"P4-04 라이브 {tag} — 데이터 {root}")
        repo = make_repo(root)
        procs = Processes(data_root=root, log=log, port=PORT, runner_id=RUNNER_ID)
        api: Api | None = None
        try:
            procs.start()
            api = Api(procs.base_url, log)
            wait_until(
                lambda: any(r["id"] == RUNNER_ID for r in api.get("/api/runners")),
                f"Runner {RUNNER_ID} 등록",
                timeout=60,
            )
            probe = Probe(api, log, procs, repo, tag)
            probe.run_all()
            summary = {
                "tag": tag,
                "data_root": str(root),
                "case_id": probe.case_id,
                "facts": probe.facts,
                "product_checks": probe.product,
                "observations": probe.observations,
            }
            (OUT / "P4-04-live-results.json").write_text(
                json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            differ = [o["check"] for o in probe.observations if not o["ok"]]
            log.head("요약")
            log(f"제품 규칙 {len(probe.product)}건 통과. 관찰(지시와 다름): {differ or '없음'}")
            return 0
        finally:
            if api is not None:
                api.close()
            procs.stop()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except LiveError as exc:
        print(f"LIVE FAILED: {exc}", file=sys.stderr)
        sys.exit(2)
