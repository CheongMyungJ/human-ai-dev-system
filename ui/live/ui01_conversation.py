"""UI-01 라이브 — 실제 codex 가 대화 문맥으로 논의하고, 업무화 뒤 초안이 그 논의를 잇는가.

UI-01 은 새 **AI 지시문**(논의 응답)과 새 **고정 컨텍스트 역할**(대화의 사용자·AI 메시지)을
만들었다. 자동 시험은 `FakeCliExecutor` 가 정해진 글을 내므로 지시문의 구멍을 볼 수 없다 —
P3-R4 의 결합 기록이 정확히 그렇게 실패했다. 그래서 실제 CLI 로 확인한다.

한 대화에서 셋을 본다.

    A. 첫 논의 응답        "아직 코드·문서를 고치지 마세요" 를 받고 **아무 것도 바꾸지 않고**
                           답하는가. 하지 않은 작업을 했다고 말하지 않는가
    B. 앞선 논의를 잇는가  "앞에서 제가 무엇을 하지 말라고 했나요?" 에 문맥으로 답하는가
    C. 업무화 뒤 의도 초안  같은 Case 에서 업무화하고 초안을 쓰게 할 때, 논의에서 명시한
                           금지(문서 만들지 말 것)를 제약으로 옮기는가

**판정은 두 층이다.** 제품 규칙(접수·잠금·문맥 참조·위임 근거·실행 권한)이 어긋나면
`LiveError` 로 멈춘다. AI 가 지시와 다르게 쓴 것은 멈추지 않고 **관찰로 기록한다** — 그것이
이 라이브가 찾으려는 것이다. 표본은 한 대화뿐이다.

**제품 코드를 import 하지 않는다.** HTTP 로만 부른다(p3/live/driver.py 와 같은 규칙).
라이브 데이터는 `%LOCALAPPDATA%\\Temp\\hads-ui-01-live` 에 두고 저장소 `var\\` 를 건드리지
않는다. 실행: `.venv\\Scripts\\python.exe ui\\live\\ui01_conversation.py`
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
    Api,
    LiveError,
    Log,
    Processes,
    stamp,
    wait_until,
)

RUNNER_ID = "runner-ui-01-live"
TOOL = {"tool_id": "codex", "mode": "exec"}
OUT = REPO_ROOT / "ui" / "evidence"
LIVE_ROOT = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Temp" / "hads-ui-01-live"

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
    "우리 `store.py` 의 저장 구조에 대해 이야기하고 싶어요. `list_items()` 가 캐시를 쓰는데"
    " 이게 필요한지 잘 모르겠어요.\n\n"
    "**아직 코드나 문서는 수정하지 마세요.** 지금은 의견만 주세요."
)
M2 = "앞에서 제가 무엇을 하지 말라고 했는지 한 줄로 확인해 주세요. 그리고 캐시에 대한 당신의 앞선 의견을 한 줄로 요약해 주세요."
M3 = (
    "좋아요. 캐시 때문에 `save()` 뒤 `list_items()` 가 옛 값을 보이는 문제를 고치는 작업으로"
    " 진행해 주세요. 기대: `save()` 직후 `list_items()` 가 새 값을 보여야 합니다.\n\n"
    "앞에서 말한 대로 **문서 파일(README 등)은 만들거나 고치지 마세요.**"
)

#: "했다"고 주장하는 표현. 논의 응답은 아무 것도 바꾸지 않으므로 이런 말은 관찰 대상이다.
CLAIM = re.compile(r"(수정했|고쳤|변경했|적용했|추가했|만들었|작성했)")


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


class Conversation:
    def __init__(self, api: Api, log: Log, repo: Path, tag: str) -> None:
        self.api = api
        self.log = log
        self.repo = repo
        self.tag = tag
        self.case_id = ""
        self.observations: list[dict[str, Any]] = []
        self.product: list[dict[str, Any]] = []

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
        self.must("send_is_pending_first", sent["receipt"] in ("pending", "stored"),
                  f"전송 응답의 접수 상태 {sent['receipt']}")
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

    def run(self, run_id: str, body: dict[str, Any], what: str) -> dict[str, Any]:
        response = self.api.request(
            "POST", f"/api/cases/{self.case_id}/runs", json={"run_id": run_id, **body, **TOOL}
        )
        if response.status_code not in (200, 201):
            raise LiveError(f"{what} 실행이 거부됐다 {response.status_code}\n{response.text}")
        run = wait_until(
            lambda: (lambda r: r if r["status"] == "finished" else None)(
                self.api.get(f"/api/runs/{run_id}")
            ),
            what,
        )
        self.log(
            f"run {run_id} outcome={run['outcome']} exit={run.get('exit_code')}"
            f" version={run.get('observed_tool_version')} permission={run['permission']}"
        )
        return run

    def reply(self, sent: dict[str, Any], letter: str) -> tuple[dict[str, Any], str]:
        """논의 응답 실행. 지시는 그 요청을 연 메시지다."""
        before = tree_state(self.repo)
        message = sent["message"]
        run_id = f"run-ui01-{letter}-{self.tag}"
        run = self.run(
            run_id,
            {
                "instruction_artifact_id": message["artifact_id"],
                "instruction_artifact_rev": message["artifact_rev"],
                "purpose": "discussion_reply",
                "role": "author",
                "permission": "read_only",
                "request_id": sent["request"]["id"],
            },
            f"{letter} 논의 응답",
        )
        self.must(f"{letter}_completed", run["outcome"] == "completed",
                  f"논의 응답 outcome={run['outcome']}")
        self.must(f"{letter}_read_only", run["permission"] == "read_only", run["permission"])
        after = tree_state(self.repo)
        # 읽기 전용 실행이 저장소를 바꿨다면 그것은 CLI 권한 매핑의 문제다. 관찰로 남긴다 —
        # 제품은 막지 못하고 감지만 한다(D-44).
        self.observe(f"{letter}_repository_unchanged", before == after,
                     f"HEAD·작업 트리 {'같음' if before == after else '달라짐'}")
        view = self.api.get(f"/api/cases/{self.case_id}/conversation")
        replies = [m for m in view["messages"] if m["run_id"] == run_id]
        self.must(f"{letter}_one_assistant_message", len(replies) == 1,
                  f"이 실행의 AI 메시지 {len(replies)}건")
        text = self.read(replies[0]["artifact_id"], replies[0]["artifact_rev"])
        (OUT / f"UI-01-live-{letter}-reply.txt").write_text(text, encoding="utf-8")
        return run, text.split("--- final message ---", 1)[-1].strip()

    def settle(self, sent: dict[str, Any]) -> None:
        settled = self.api.ok(
            "POST",
            f"/api/cases/{self.case_id}/requests/{sent['request']['id']}/settle",
            json={"outcome": "completed", "actor": "live-harness"},
        )
        self.must("settled", settled["state"] == "completed", settled["state"])

    # ------------------------------------------------------------ 흐름

    def run_all(self) -> None:
        project = self.api.ok(
            "POST",
            "/api/projects",
            json={"name": f"ui-01-live-{self.tag}", "repo_path": str(self.repo),
                  "default_tool_id": "codex"},
        )
        view = self.api.ok(
            "POST", f"/api/projects/{project['id']}/conversations",
            json={"title": "저장 구조 이야기"},
        )
        self.case_id = view["case_id"]
        self.must("discussion_stage", view["stage"] == "discussion" and view["profile"] is None,
                  f"stage={view['stage']} profile={view['profile']}")

        # A ----------------------------------------------------------------
        self.log.head("A. 첫 논의 응답 — 아무 것도 바꾸지 않고 답하는가")
        first = self.send(M1, "m1")
        locked = self.api.request(
            "POST", f"/api/cases/{self.case_id}/messages",
            json={"client_message_id": f"m1b-{self.tag}", "content": "끼어들기",
                  "summary": "끼어들기", "target_runner_id": RUNNER_ID},
        )
        self.must("general_send_locked", locked.status_code == 409
                  and self.api.refusals(locked) == ["request_in_progress"],
                  f"처리 중 일반 전송 {locked.status_code} {self.api.refusals(locked)}")
        run_a, reply_a = self.reply(first, "A")
        self.log.json("A 응답", reply_a[:1500])
        self.observe("A_nonempty", len(reply_a) > 20, f"응답 길이 {len(reply_a)}")
        claims = CLAIM.findall(reply_a)
        self.observe("A_no_work_claim", not claims, f"작업 주장 표현 {claims or '없음'}")
        self.settle(first)

        # B ----------------------------------------------------------------
        self.log.head("B. 앞선 논의를 잇는가")
        second = self.send(M2, "m2")
        run_b, reply_b = self.reply(second, "B")
        refs = self.api.get(f"/api/runs/{run_b['run_id']}/context-refs")
        roles = [r["role"] for r in refs]
        self.must(
            "B_context_has_conversation",
            roles == ["conversation_user_message", "conversation_assistant_message"],
            f"고정 참조 역할 {roles}",
        )
        self.log.json("B 응답", reply_b[:1500])
        self.observe(
            "B_recalls_prohibition",
            bool(re.search(r"(수정|고치|문서|코드)", reply_b)),
            "앞선 금지(코드·문서 수정 금지)를 언급했는가",
        )
        self.settle(second)

        # C ----------------------------------------------------------------
        self.log.head("C. 업무화 뒤 의도 초안이 논의의 금지를 잇는가")
        third = self.send(M3, "m3")
        started = self.api.ok(
            "POST", f"/api/cases/{self.case_id}/work-start",
            json={"profile": "defect_fix", "request_message_id": third["message"]["id"],
                  "decided_by": "person", "actor": "live-harness",
                  "summary": "캐시 무효화 결함 수정"},
        )
        self.must("work_started_same_case",
                  started["case_id"] == self.case_id and started["profile_version"] == "2",
                  f"stage={started['stage']} profile={started['profile']}"
                  f" v{started['profile_version']}")
        policy = self.api.get(f"/api/cases/{self.case_id}/policy")
        basis = policy["delegation_basis"]["current"]
        self.must("basis_is_work_request",
                  basis["artifact_id"] == third["message"]["artifact_id"],
                  f"위임 근거 {basis['basis_kind']} {basis['artifact_id']}")
        run_c = self.run(
            f"run-ui01-C-{self.tag}",
            {
                "instruction_artifact_id": third["message"]["artifact_id"],
                "instruction_artifact_rev": 1,
                "purpose": "intent_authoring",
                "role": "author",
                "permission": "read_only",
                "task_id": "task-intent",
                "request_id": third["request"]["id"],
            },
            "C 의도 작성",
        )
        self.must("C_completed", run_c["outcome"] == "completed", run_c["outcome"])
        refs_c = self.api.get(f"/api/runs/{run_c['run_id']}/context-refs")
        roles_c = [r["role"] for r in refs_c]
        self.must("C_context_has_conversation",
                  roles_c.count("conversation_user_message") == 2
                  and roles_c.count("conversation_assistant_message") == 2,
                  f"고정 참조 역할 {roles_c}")
        intent = self.api.get(f"/api/cases/{self.case_id}/intent-state")["latest_intent_version"]
        body = self.read(intent["artifact_id"], intent["artifact_rev"])
        (OUT / "UI-01-live-C-intent-original.json").write_text(body, encoding="utf-8")
        doc = json.loads(body)
        fields = doc.get("fields") or {}
        constraint_text = " ".join(
            str((fields.get(name) or {}).get("text") or "")
            for name in ("constraints", "exclusions", "scope")
        )
        self.log.json("C 제약·제외·범위", {
            name: fields.get(name) for name in ("constraints", "exclusions", "scope")
        })
        self.observe(
            "C_carries_document_prohibition",
            bool(re.search(r"(문서|README)", constraint_text)),
            "논의의 '문서 만들지 말 것'이 제약·제외·범위에 옮겨졌는가",
        )
        origins = {
            name: (fields.get(name) or {}).get("origin") for name in ("constraints", "exclusions")
        }
        self.observe(
            "C_prohibition_is_user_requirement",
            "user_requirement" in origins.values(),
            f"제약·제외의 origin {origins}",
        )
        self.settle(third)
        final = self.api.get(f"/api/cases/{self.case_id}/conversation")
        self.must("history_kept",
                  [m["author"] for m in final["messages"]]
                  == ["user", "assistant", "user", "assistant", "user"],
                  f"메시지 {[m['author'] for m in final['messages']]}")


def main() -> int:
    tag = stamp()
    root = LIVE_ROOT / tag
    root.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    with Log(OUT / "UI-01-live.log") as log:
        log.head(f"UI-01 라이브 {tag} — 데이터 {root}")
        repo = make_repo(root)
        procs = Processes(data_root=root, log=log, port=8795, runner_id=RUNNER_ID)
        api: Api | None = None
        try:
            procs.start()
            api = Api(procs.base_url, log)
            wait_until(
                lambda: any(r["id"] == RUNNER_ID for r in api.get("/api/runners")),
                f"Runner {RUNNER_ID} 등록",
                timeout=60,
            )
            probe = Conversation(api, log, repo, tag)
            probe.run_all()
            summary = {
                "tag": tag,
                "data_root": str(root),
                "case_id": probe.case_id,
                "product_checks": probe.product,
                "observations": probe.observations,
            }
            (OUT / "UI-01-live-results.json").write_text(
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
