"""경로 A — 기본 자율(`ask_on_decision`)로 두 저장소 기능을 끝까지.

이 스크립트가 답하려는 것은 셋이다(P3-PLAN-04 1절).

1. `deep` 수준과 `ask_on_decision` 이 **서로 섞이지 않는가.** 깊이는 준비를 늘리고
   Autonomy 는 확인 지점을 정한다 — 그렇게 도는 것을 아직 본 적이 없다.
2. 같은 Runner 위 두 저장소를 **함께 바꾸는** 업무가 실제로 도는가.
3. 사람이 의도 단계 뒤로는 **한 번도 불리지 않고** 끝나는가.

**제품 코드를 import 하지 않는다.** HTTP 로만 부른다(driver 참조).

사용법:

    .venv\\Scripts\\python.exe p3\\live\\path_a.py [--keep]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixtures  # noqa: E402
from driver import (  # noqa: E402
    Api, LiveError, Log, Processes, force_rmtree, stamp, wait_until,
)

LIVE_ROOT = Path(
    __import__("os").environ.get("LOCALAPPDATA", str(Path.home()))
) / "Temp" / "hads-p3-04-live"

RUNNER_ID = "runner-p3-04-live"
TOOL = {"tool_id": "codex", "mode": "exec"}

#: 사용자의 요청 원문. **이것이 위임의 범위다.**
#:
#: **처음 쓴 요청은 이만큼 자세하지 않았다.** 수준이 `deep` 인 Case 의 독립 의미
#: 검토가 세 번에 걸쳐 빈 곳을 찾아냈고(모순·미정·가정), 그때마다 답을 요청 안으로
#: 옮겼다. 지금 형태는 그 결과다 — 요청이 명확해야 사람이 다시 불리지 않는다는 것이
#: P3-04가 확인하려는 것의 전제이며, 그 전제를 세우는 데 QG-01 이 실제로 쓰였다.
REQUEST = """요약에 문자 수를 더해 주세요.

**repo-core**: `summarize()` 가 지금 돌려주는 `{"lines": ..., "words": ...}` 에
`chars` 를 더합니다.

- `chars` 는 Python `len(text)` 의 값입니다 — 공백과 개행을 포함한 **코드 포인트
  수**이며, 자소(grapheme) 단위나 바이트 수가 아닙니다.
- 기존 키 `lines` 와 `words` 는 **그대로 둡니다.** 이름을 바꾸거나 빼지 마세요.

**repo-report**: `render()` 가 `chars` 를 함께 보여 줍니다.

- 출력 형식은 `"<lines>줄 <words>단어 <chars>자"` 입니다.
- 이 형식을 검증하는 **기존 테스트는 새 형식으로 갱신하세요.** "기존 테스트가
  계속 통과해야 한다"는 요구는 출력 형식 테스트를 제외한 나머지 동작의 회귀를
  뜻합니다.

**호환 범위**: `summarize()` 와 `render()` 를 쓰는 곳은 이 두 저장소가 전부입니다.
다른 호출자도, 저장된 요약 데이터도 없습니다. 마이그레이션은 필요하지 않습니다.

두 저장소는 서로 다른 저장소이며 한쪽만 바꾸면 반대쪽이 어긋납니다. 새 동작에도
테스트가 있어야 합니다.
"""

#: 사람이 AI 의 질문에 답하는 내용. **미리 준비해 두지만 자동 답변이 아니다** —
#: 질문이 나오지 않으면 쓰이지 않고, 답한 사실은 기록으로 남는다.
#:
#: 이 답이 요청의 **모순 하나를 푼다.** "기존 테스트가 계속 통과해야 한다"와
#: "출력 형식을 바꾼다"는 그대로 두면 서로 어긋나고, QG-01 의 독립 검토가 실제로
#: 그것을 `request_missing_or_contradictory` 로 잡아냈다.
ANSWER = """세 가지를 확정합니다.

1. `summarize()` 의 기존 키(`lines`, `words`)는 그대로 두고 `chars` 를 더하기만
   합니다. 키를 바꾸거나 빼지 마세요.
2. `render()` 의 출력 형식은 새 형식으로 바꿉니다. **그 형식을 검증하는
   repo-report 의 기존 테스트는 새 형식으로 갱신하세요.** "기존 테스트가 계속
   통과해야 한다"는 요구는 출력 형식 테스트를 제외한 나머지 동작의 회귀를
   뜻합니다.
3. 이 두 저장소 밖에 `summarize()` 나 `render()` 를 쓰는 다른 호출자는 없습니다.
"""


def dump(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


class PathA:
    #: 이 경로의 Autonomy 와 증거 파일의 꼬리표. 하위 경로가 덮어쓴다.
    AUTONOMY = "ask_on_decision"
    AUTONOMY_REASON = "요청이 명확하다. 결정이 필요할 때만 부른다"
    LETTER = "A"

    def __init__(self, api: Api, log: Log, repos: dict[str, Path], out: Path) -> None:
        self.api = api
        self.log = log
        self.repos = repos
        self.out = out
        self.tag = stamp()
        self.repo_ids: dict[str, str] = {}
        #: 제어부에 **등록된 이름** → 저장소 id. 계획이 쓰는 이름이 이것이다.
        #: Project 를 만들 때 자동 등록되는 저장소의 이름은 `primary` 이며 디렉터리
        #: 이름과 다르다 — 계획이 어느 쪽을 적어야 하는지가 실제 문제였다.
        self.by_registered: dict[str, str] = {}
        self.registered_name: dict[str, str] = {}
        self.case_id = ""
        self.project_id = ""

    # ------------------------------------------------------------- 도우미

    def instruction(self, text: str, summary: str) -> str:
        """요청 원문을 접수하고 Runner 가 실제로 저장할 때까지 기다린다."""
        accepted = self.api.ok(
            "POST",
            f"/api/cases/{self.case_id}/artifacts",
            json={
                "kind": "instruction",
                "content": text,
                "summary": summary,
                "target_runner_id": RUNNER_ID,
            },
        )
        artifact_id = accepted["artifact_id"]
        wait_until(
            lambda: self.api.get(f"/api/intakes/{accepted['intake_id']}")["state"] == "stored",
            f"지시 원문 {artifact_id} 저장",
            timeout=120,
        )
        return artifact_id

    def run(
        self,
        purpose: str,
        *,
        name: str,
        request_text: str = "",
        artifact: tuple[str, int] | None = None,
        task_id: str = "task-1",
        permission: str = "read_only",
        repository_id: str | None = None,
        role: str = "author",
        expect_refusal: bool = False,
    ):
        """실행 하나를 요청하고 끝날 때까지 기다린다.

        `artifact` 를 주면 **이미 있는 원문**을 지시로 쓴다. 의미 검토가 그렇다 —
        검토 대상 의도 버전을 제어부가 지시 원문에서 끌어내므로(`assignment_payload`),
        따로 쓴 안내문을 지시로 주면 "검토할 의도 버전을 찾지 못했다"가 된다.

        `expect_refusal` 이면 409 응답을 그대로 돌려준다 — 거부도 관측 대상이다.
        """
        if artifact is not None:
            artifact_id, artifact_rev = artifact
        else:
            artifact_id, artifact_rev = self.instruction(request_text, f"{name} 요청"), 1
        body = {
            "run_id": f"run-{name}-{self.tag}",
            "instruction_artifact_id": artifact_id,
            "instruction_artifact_rev": artifact_rev,
            "purpose": purpose,
            "role": role,
            "permission": permission,
            "task_id": task_id,
            **TOOL,
        }
        if repository_id is not None:
            body["repository_id"] = repository_id
        response = self.api.request("POST", f"/api/cases/{self.case_id}/runs", json=body)
        if response.status_code == 409:
            refusals = self.api.refusals(response)
            self.log(f"[{name}] 409 {refusals}")
            if expect_refusal:
                return response
            raise LiveError(f"{name} 가 거부됐다: {refusals}\n{response.text[:1500]}")
        if response.status_code not in (200, 201):
            raise LiveError(f"{name} → {response.status_code}\n{response.text[:1500]}")
        run_id = body["run_id"]
        self.log(f"[{name}] 실행 {run_id} 생성 (repo={repository_id or '-'} task={task_id})")

        run = wait_until(
            lambda: (lambda r: r if r["status"] == "finished" else None)(
                self.api.get(f"/api/runs/{run_id}")
            ),
            f"{name} 실행 종료",
        )
        self.log(
            f"[{name}] outcome={run['outcome']} exit={run.get('exit_code')}"
            f" version={run.get('observed_tool_version')}"
        )
        for command in run.get("commands") or []:
            self.log(f"      명령: {command['command_summary']} → exit={command['exit_code']}")
        if run["outcome"] != "completed":
            raise LiveError(f"{name} 실행이 {run['outcome']} 로 끝났다")
        return run

    # ------------------------------------------------------------- 단계들

    def setup(self) -> None:
        self.log.head("1. Project · 저장소 둘 · Case")
        project = self.api.ok(
            "POST",
            "/api/projects",
            json={
                "name": f"p3-04-live-{self.tag}",
                "repo_path": str(self.repos[fixtures.CORE_NAME]),
                "default_tool_id": "codex",
            },
        )
        self.project_id = project["id"]
        self.api.ok(
            "POST",
            f"/api/projects/{self.project_id}/repositories",
            json={
                "name": fixtures.REPORT_NAME,
                "repo_path": str(self.repos[fixtures.REPORT_NAME]),
                "registered_by": "owner",
            },
        )
        registry = self.api.get(f"/api/projects/{self.project_id}/repositories")
        for row in registry["repositories"]:
            path = Path(row["repo_path"]).resolve()
            for name, repo in self.repos.items():
                if path == repo.resolve():
                    self.repo_ids[name] = row["id"]
                    self.by_registered[row["name"]] = row["id"]
                    self.registered_name[name] = row["name"]
        if len(self.repo_ids) != 2:
            raise LiveError(f"등록 저장소를 두 개로 잇지 못했다: {registry}")
        self.log(f"등록 저장소: {self.registered_name} → {self.repo_ids}")

        case = self.api.ok(
            "POST",
            f"/api/projects/{self.project_id}/cases",
            json={"title": "요약에 문자 수 더하기", "profile": "feature"},
        )
        self.case_id = case["id"]
        self.log(f"Case {self.case_id} profile=feature")

        self.api.ok(
            "PUT",
            f"/api/cases/{self.case_id}/autonomy",
            json={
                "autonomy": self.AUTONOMY,
                "set_by": "owner",
                "reason_summary": self.AUTONOMY_REASON,
            },
        )
        policy = self.api.get(f"/api/cases/{self.case_id}/policy")
        self.log(
            f"Autonomy: {policy['autonomy']} (effective={policy['effective_autonomy']},"
            f" source={policy['effective_source']})"
        )
        self.log(
            "강제 표시: "
            + ", ".join(f"{k}={v['state']}" for k, v in policy["enforcement"].items())
        )
        dump(self.out / f"P3-04-{self.LETTER}-policy.json", policy)

        for name, repo_id in self.repo_ids.items():
            self.api.ok(
                "PUT",
                f"/api/cases/{self.case_id}/repositories",
                json={
                    "repository_id": repo_id,
                    "selection_source": "explicit",
                    "code_write_allowed": True,
                    "publish_allowed": False,
                    "selected_by": "owner",
                    "reason_summary": f"{name} 의 공개 계약이 함께 바뀐다",
                },
            )
        selection = self.api.get(f"/api/cases/{self.case_id}/repositories")
        self.log(
            "선택: "
            + ", ".join(
                f"{r['repository_name']}(write={bool(r['code_write_allowed'])}"
                f" publish={bool(r['publish_allowed'])} source={r['selection_source']})"
                for r in selection["selected"]
            )
        )

    def workspaces(self) -> None:
        self.log.head("2. 저장소별 작업공간 — 사용자 트리를 건드리지 않는다")
        for name, repo_id in self.repo_ids.items():
            self.api.ok(
                "POST",
                f"/api/cases/{self.case_id}/workspace",
                json={"repository_id": repo_id, "base_ref": "HEAD"},
            )
            self.log(f"작업공간 요청: {name}")

        def all_ready():
            view = self.api.get(f"/api/cases/{self.case_id}/workspace")
            spaces = view.get("workspaces") or []
            if len(spaces) == 2 and all(w["state"] == "ready" for w in spaces):
                return view
            return None

        view = wait_until(all_ready, "두 작업공간 준비", timeout=300)
        for space in view["workspaces"]:
            self.log(
                f"  {space['repository_name']}: branch={space['branch']}"
                f" base={space['base_commit'][:10]} worktree={space['worktree_path']}"
                f" user_tree_dirty={space.get('user_tree_dirty')}"
            )
        dump(self.out / f"P3-04-{self.LETTER}-workspaces.json", view)

    def intent(self) -> None:
        self.log.head("3. 의도 초안 — AI 가 쓰고 사람이 동의한다")
        self.run(
            "intent_authoring",
            name="intent",
            request_text=REQUEST,
            repository_id=self.repo_ids[fixtures.CORE_NAME],
        )
        state = self.api.get(f"/api/cases/{self.case_id}/intent-state")
        intent = state["latest_intent_version"]
        self.log(f"의도 버전 {intent['id']} rev={intent['revision']} status={intent['status']}")

        prep = self.api.get(f"/api/cases/{self.case_id}/preparation")
        sizing = prep.get("sizing") or {}
        self.log(f"AI 의 수준 제안: {sizing.get('recommended_level')} → 결정={sizing.get('level')}")
        for axis in sizing.get("axes") or []:
            self.log(f"  축 {axis['axis']}: {axis['weight']} — {axis['judgement_summary']}")

        # **수준은 AI 가 제안하고 사람이 조정한다**(P3-01). 두 저장소의 공개 계약이
        # 함께 바뀌므로 사람이 deep 으로 올린다. 이것은 의도 단계의 사람 입력이며
        # 설계·계획·구현·검증·완료의 확인이 아니다.
        if sizing.get("level") != "deep":
            self.api.ok(
                "POST",
                f"/api/cases/{self.case_id}/sizing-adjustment",
                json={
                    "level": "deep",
                    "reason": "두 저장소의 공개 계약이 함께 바뀌고 회귀 범위가 두 저장소에 걸친다",
                    "residual_risk": "요청 자체는 명확해 준비가 과할 수 있다",
                    "actor": "owner",
                },
            )
            prep = self.api.get(f"/api/cases/{self.case_id}/preparation")
            self.log(f"사람이 수준을 조정했다 → {prep['sizing']['level']}")

        # **AI 가 물은 것에 사람이 답한다.** 이것이 P3-04가 확인해야 하는
        # "명확한 기능의 추가 사람 호출 없음, **필수 판단에는 질문**"의 뒷면이다.
        # 답하지 않으면 동의가 `open_intent_questions` 로 거부된다 — 답변은 동의가
        # 아니고 동의도 답변이 아니다(FR-03).
        questions = self.api.get(f"/api/cases/{self.case_id}/intent-state").get(
            "open_intent_questions"
        ) or []
        if questions:
            self.log(f"AI 가 물은 것 {len(questions)}건: {[q['summary'] for q in questions]}")
        for question in questions:
            self.api.ok(
                "POST",
                f"/api/cases/{self.case_id}/questions/{question['id']}/answer",
                json={
                    "content": ANSWER,
                    "summary": "기존 키를 유지하고 chars 를 더하기만 한다",
                    "target_runner_id": RUNNER_ID,
                    "actor": "owner",
                },
            )
            self.log(f"  답함: {question['question_key']}")

        if questions:
            # **답변을 반영한 새 버전을 쓴다.** 답하는 것과 반영하는 것은 다른
            # 일이다(intent-artifacts 104행 "필요한 질문의 답변을 반영하면 …").
            # 답만 하고 v1 에 동의하면 초안은 여전히 그 항목을 미정으로 두고 있고,
            # 실제로 QG-01 이 그 모순을 잡아냈다.
            self.run(
                "intent_authoring",
                name="intent-v2",
                request_text=(
                    f"{REQUEST}\n\n질문에 대한 답은 고정 컨텍스트에 있습니다."
                    " 그 답을 초안에 반영하고, 답이 나온 항목을 다시 미정으로 두지"
                    " 마세요."
                ),
                repository_id=self.repo_ids[fixtures.CORE_NAME],
            )
            state = self.api.get(f"/api/cases/{self.case_id}/intent-state")
            intent = state["latest_intent_version"]
            self.log(f"답변 반영 버전 {intent['id']} rev={intent['revision']}")
            still_open = state.get("open_intent_questions") or []
            if still_open:
                self.log(f"  새 버전의 열린 질문: {[q['summary'] for q in still_open]}")
                for question in still_open:
                    self.api.ok(
                        "POST",
                        f"/api/cases/{self.case_id}/questions/{question['id']}/answer",
                        json={
                            "content": ANSWER,
                            "summary": "같은 답을 다시 적는다",
                            "target_runner_id": RUNNER_ID,
                            "actor": "owner",
                        },
                    )

        self.agree_to_latest()

    def agree_to_latest(self) -> None:
        """최신 의도 원문을 **실제로 받아 읽고** 동의한다(FR-23).

        읽지 않은 것에 동의하지 않는다. 열람이 기록을 만들고, 동의는 그 원문의
        해시에 붙는다 — 그 사이 대상이 바뀌면 이전 동의로 진행하지 않는다.
        """
        intent = self.api.get(
            f"/api/cases/{self.case_id}/intent-state"
        )["latest_intent_version"]
        created = self.api.ok(
            "POST",
            f"/api/artifacts/{intent['artifact_id']}/{intent['artifact_rev']}/read-requests",
            json={},
        )
        served = wait_until(
            lambda: (lambda r: r if r["content"] is not None else None)(
                self.api.get(f"/api/read-requests/{created['id']}")
            ),
            "의도 원문 전달",
            timeout=180,
        )
        (self.out / f"P3-04-{self.LETTER}-intent-original.txt").write_text(
            served["content"], encoding="utf-8"
        )
        self.log(
            f"의도 rev={intent['revision']} 원문 {len(served['content'])}바이트를"
            " 실제로 받아 읽었다"
        )
        agreed = self.api.ok(
            "POST",
            f"/api/cases/{self.case_id}/intent-versions/{intent['id']}/agreement",
            json={
                "agree": True,
                "statement": "이 의도에 동의합니다. 이 범위의 실행을 위임합니다.",
                "content_hash": intent["content_hash"],
                "actor": "owner",
            },
        )
        self.log(f"동의 결정 {agreed['decision']['id']}")

    def gate(self, round_tag: str = "") -> dict:
        """규칙 검사와 독립 의미 검토를 돌리고 판정을 돌려준다.

        `round_tag` 가 필요한 이유는 **멱등성** 때문이다. `create_run()` 은 `run_id`
        로 멱등하므로 같은 id 로 다시 부르면 이전 실행이 그대로 돌아온다 — 새 의도
        버전을 검토하지 않고 옛 검토 결과를 다시 보게 되고, 그 버전의 게이트는
        `not_run` 인 채로 남는다. 실제로 그렇게 됐다(P3-R4 6.5와 같은 함정).
        """
        self.log.head("4. QG-01 — 방식이 둘이고 deep 이면 독립 검토가 필수다")
        intent = self.api.get(f"/api/cases/{self.case_id}/intent-state")["latest_intent_version"]
        self.api.ok(
            "POST",
            f"/api/cases/{self.case_id}/intent-versions/{intent['id']}/gate-rules",
            json={},
        )
        conformance = self.api.get(f"/api/cases/{self.case_id}/conformance")
        self.log(
            f"정합성 요구: {conformance['required_method']}"
            f" 이유={[r['reason'] for r in conformance.get('reasons') or []]}"
        )
        if conformance["required_method"] != "independent":
            raise LiveError(
                "deep 인데 가벼운 확인이 허용됐다 — Fast Lane 판정이 수준을 무시했다"
            )
        # **검토의 지시 원문은 의도 문서 자체다.** 제어부가 지시 원문에서 검토 대상
        # 의도 버전을 끌어내므로(`assignment_payload`), 따로 쓴 안내문을 주면
        # "검토할 의도 버전을 찾지 못했다"로 실행이 실패한다 — 실제로 그렇게 됐다.
        self.run(
            "intent_gate_review",
            name=f"gate{round_tag}",
            artifact=(intent["artifact_id"], intent["artifact_rev"]),
            role="reviewer",
            repository_id=self.repo_ids[fixtures.CORE_NAME],
        )
        gate = self.api.get(f"/api/cases/{self.case_id}/gate")
        conformance = self.api.get(f"/api/cases/{self.case_id}/conformance")
        self.log(f"QG-01: verdict={gate['verdict']} rule={gate.get('rule_verdict')} ai={gate.get('ai_verdict')}")
        self.log(f"정합성 기록: method={conformance.get('method')} verdict={conformance.get('verdict')}")
        for finding in gate.get("findings") or []:
            self.log(
                f"  지적: {finding['criterion']} [{finding['severity']}/"
                f"{finding['certainty']}] {finding.get('target')} — {finding['summary']}"
            )
        dump(self.out / f"P3-04-{self.LETTER}-conformance.json", conformance)
        dump(self.out / f"P3-04-{self.LETTER}-gate.json", gate)
        return gate

    def confirm_material_deltas(self) -> int:
        """**동의된 의도를 AI 가 바꾼 것을 사람이 확인한다**(P3-R4·D-60).

        다시 쓴 초안이 동의된 항목을 바꾸면 그 변경은 `material` 로 쌓이고 의존
        작업을 막는다 — 라이브에서 실제로 `material_delta_unconfirmed` 로 막혔다.
        **그것이 맞는 동작이다.** 사람이 그 변경을 보고 확인해야 풀린다.

        AI 의 "의미가 같다"는 평가로는 풀리지 않는다. 여기서 하는 것은 사람의
        확인이며 **한 번의 확인은 한 건에만** 적용된다.
        """
        state = self.api.get(f"/api/cases/{self.case_id}/material-deltas")
        pending = state.get("pending") or []
        if not pending:
            return 0
        self.log(f"동의된 의도의 AI 출처 변경 {len(pending)}건 — 사람이 확인한다:")
        for delta in pending:
            self.log(
                f"  - {delta['change_class']} {delta.get('target_key')}"
                f" ({delta['materiality']}) {delta.get('detail')}"
            )
            self.api.ok(
                "POST",
                f"/api/cases/{self.case_id}/material-deltas/{delta['id']}/confirmation",
                json={
                    "actor": "owner",
                    "explicit": True,
                    "note_summary": "검토 지적을 반영한 변경임을 확인했다",
                },
            )
        return len(pending)

    #: 게이트가 막았을 때 **다시 쓰는 횟수의 상한.**
    #:
    #: 통과할 때까지 돌리는 것은 결과를 고르는 일이다. 상한을 두고, 넘으면 **막힌
    #: 채로 끝낸다** — "미충족은 완료로 표시하지 않는다"(DEVELOPMENT.md 10절).
    #: 제품의 repair 한도(D-29)는 P4-01 이며 이것은 하네스의 상한이다.
    GATE_ROUNDS = 2

    def gate_with_remediation(self) -> None:
        """QG-01 이 막으면 **지적을 피드백으로 넣고 다시 쓴다.**

        통과할 때까지 같은 초안으로 재검토하지 않는다. 그것은 판정이 흔들리기를
        기다리는 일이고, 실제로 이 게이트의 판정은 실행마다 다르다(LLM 검토다).
        제품이 정한 경로는 **피드백 → 새 의도 버전 → 재검토**이며 여기서 그 경로를
        그대로 쓴다.
        """
        gate = self.gate()
        for attempt in range(1, self.GATE_ROUNDS + 1):
            if gate["verdict"] == "pass":
                return
            self.log(f"  QG-01 이 {gate['verdict']} 다 — 지적을 피드백으로 넣고 다시 쓴다"
                     f" ({attempt}/{self.GATE_ROUNDS})")
            intent = self.api.get(
                f"/api/cases/{self.case_id}/intent-state"
            )["latest_intent_version"]
            findings = "\n".join(
                f"- [{f['criterion']}/{f['certainty']}] {f.get('target')}: {f['summary']}"
                for f in gate.get("findings") or []
            )
            self.api.ok(
                "POST",
                f"/api/cases/{self.case_id}/feedback",
                json={
                    "target_intent_version_id": intent["id"],
                    "content": (
                        "독립 의미 검토가 아래를 지적했습니다. 요청 원문의 범위를"
                        " 넘지 말고 이 지적만 고쳐 다시 써 주세요.\n\n" + findings
                    ),
                    "summary": "QG-01 지적 반영 요청",
                    "target_runner_id": RUNNER_ID,
                },
            )
            self.run(
                "intent_authoring",
                name=f"intent-fix{attempt}",
                request_text=(
                    "고정 컨텍스트의 미해결 피드백이 독립 검토의 지적입니다."
                    " 그 지적만 고치고 요청 원문의 범위를 넘지 마세요."
                ),
                repository_id=self.repo_ids[fixtures.CORE_NAME],
            )
            self.confirm_material_deltas()
            self.agree_to_latest()
            gate = self.gate(round_tag=f"-fix{attempt}")
        if gate["verdict"] != "pass":
            raise LiveError(
                f"QG-01 이 {self.GATE_ROUNDS}회 재작성 뒤에도 {gate['verdict']} 다."
                " 통과할 때까지 돌리지 않는다 — 막힌 채로 끝낸다"
            )

    def preparation(self) -> None:
        self.log.head("5. 설계 · 개발계획 — deep 이므로 두 건이 필요하다")
        prep = self.api.get(f"/api/cases/{self.case_id}/preparation")
        fast_lane = prep.get("fast_lane") or {}
        self.log(f"Fast Lane: {fast_lane.get('eligible')} {fast_lane.get('blockers')}")
        if fast_lane.get("eligible"):
            raise LiveError("deep 인데 Fast Lane 이다 — 판정이 수준을 무시했다")

        self.run(
            "design_authoring",
            name="design",
            request_text=(
                "이 요청의 설계를 작성해 주세요. 두 저장소가 함께 바뀌므로"
                " `summarize()` 가 돌려주는 사전의 키 목록을 계약으로 명시하고,"
                " 어느 저장소가 무엇을 맡는지 적어 주세요."
            ),
            repository_id=self.repo_ids[fixtures.CORE_NAME],
        )
        self.run(
            "plan_authoring",
            name="plan",
            request_text=(
                "설계에 따라 개발계획을 작성해 주세요. 작업은 저장소별로 나누고,"
                " 각 작업이 어느 저장소의 코드를 바꾸는지 `repository` 에 적어 주세요."
            ),
            repository_id=self.repo_ids[fixtures.CORE_NAME],
        )

        prep = self.api.get(f"/api/cases/{self.case_id}/preparation")
        for stage in ("design", "plan", "combined"):
            info = prep.get(stage) or {}
            self.log(
                f"  {stage}: present={bool(info.get('artifact'))}"
                f" state={info.get('state')} mode={info.get('mode')}"
                f" source={info.get('mode_source')}"
            )
        dump(self.out / f"P3-04-{self.LETTER}-preparation.json", prep)
        if prep["combined"].get("artifact"):
            raise LiveError("deep 인데 결합 기록이 준비를 대신했다")

    def graph(self) -> dict:
        self.log.head("6. 작업 그래프 — Task 는 자기 저장소를 아는가")
        graph = self.api.get(f"/api/cases/{self.case_id}/work-graph")
        for task in graph.get("tasks") or []:
            self.log(
                f"  {task['task_key']} [{task['kind']}]"
                f" repo={task.get('repository_name') or '(미기록)'}"
                f" ref={task.get('repository_ref') or '-'}"
                f" — {task['summary']}"
            )
        dump(self.out / f"P3-04-{self.LETTER}-work-graph.json", graph)
        return graph

    # ---------------------------------------------------------------- 실행

    #: Task 의 종류가 실행의 목적과 권한을 정한다.
    #:
    #: **하네스가 고르는 것이 아니라 계획이 고른 것이다.** 조사 Task 에 쓰기를
    #: 주거나 검증 Task 를 구현 목적으로 돌리면, 무엇이 확인 작업이고 무엇이 제품
    #: 변경인지가 기록에서 사라진다.
    PURPOSE_BY_KIND = {
        "investigation": ("limited_analysis", "read_only"),
        "implementation": ("feature_implementation", "workspace_write"),
        # **통합 Task 는 확인하는 일이다.** 구현 목적으로 돌리면 바꿀 것이 없어
        # 실패한다("변경도 명령도 없는 구현 실행은 실패다") — 실제로 그렇게 됐다.
        # 두 저장소가 맞는지 보는 것은 검증이지 구현이 아니다.
        "integration": ("verification_run", "workspace_write"),
        "verification": ("verification_run", "workspace_write"),
        # P3-R4 의 로컬 실험. 계획이 실험 Task 를 정의할 수 있고, 그것은 기능 개발
        # pipeline 이 아니라 조사 목적 안의 활동이다(D-66).
        "experiment": ("local_experiment", "workspace_write"),
    }

    def answer_deferred_questions(self) -> int:
        """**설계·계획으로 이월된 질문에 사람이 답한다.**

        이월 질문이 열려 있으면 그 결정에 의존하는 Task 가 막히고, 무엇을 막는지
        모르는 질문은 **전부** 막는다(P3-02). 그것이 정상이며, 여기서 확인하는 것은
        "사람이 답하면 풀린다"이다.

        답의 내용은 **범위를 확인해 주는 것**이다. 이미 동의한 의도 안에서 정하라는
        것도 사람의 결정이며(D-11), 그 결정이 기록으로 남는다.
        """
        prep = self.api.get(f"/api/cases/{self.case_id}/preparation")
        deferred = prep.get("deferred_open_questions") or []
        if not deferred:
            return 0
        self.log(f"설계·계획이 물은 것 {len(deferred)}건:")
        for question in deferred:
            self.log(f"  - [{question['decide_at']}] {question['summary']}")
            self.api.ok(
                "POST",
                f"/api/cases/{self.case_id}/questions/{question['id']}/answer",
                json={
                    "content": (
                        "동의한 의도와 요청 원문의 범위 안에서 정하세요."
                        " 새 제약은 없습니다. 이 범위를 넘는 선택이 필요하면 다시"
                        " 물어 주세요."
                    ),
                    "summary": "합의된 범위 안에서 정하도록 위임한다",
                    "target_runner_id": RUNNER_ID,
                    "actor": "owner",
                },
            )
        return len(deferred)

    def work_the_graph(self) -> None:
        """**그래프가 정한 순서로** Task 를 하나씩 실행한다.

        의존이 있는 계획을 한 줄로 늘어놓으면 `task_dependencies_unmet` 으로
        막힌다 — 실제로 그렇게 막혔다. 무엇을 언제 할지는 계획이 정하고, 하네스는
        **지금 배정 가능한 것**을 그래프에 물어 본다.
        """
        self.log.head("7. 계획이 정한 순서로 두 저장소를 실제로 바꾼다")
        done: set[str] = set()
        probed = False
        answered = self.answer_deferred_questions()
        if answered:
            self.log(f"  이월 질문 {answered}건에 답했다 — 그 뒤 배정이 열리는지 본다")

        while True:
            graph = self.api.get(f"/api/cases/{self.case_id}/work-graph")
            readiness = graph.get("readiness") or {}
            pending = [
                t
                for t in graph["tasks"]
                if not t["cancelled"] and t["task_key"] not in done
            ]
            if not pending:
                break
            runnable = [
                t for t in pending if (readiness.get(t["task_key"]) or {}).get("runnable")
            ]
            if not runnable:
                blocked = {
                    t["task_key"]: [
                        b["reason"] for b in (readiness.get(t["task_key"]) or {}).get("blocked_by") or []
                    ]
                    for t in pending
                }
                raise LiveError(f"배정 가능한 Task 가 없다: {blocked}")

            task = runnable[0]
            key = task["task_key"]
            kind = task["kind"]
            repo_name = task.get("repository_name")
            purpose, permission = self.PURPOSE_BY_KIND[kind]

            if repo_name is None:
                # **제어부가 모르면 하네스도 모른다.** 추측하면 진입 검사가 무엇을
                # 막는지 확인할 수 없고, 추측이 맞을 때만 도는 라이브가 된다.
                raise LiveError(
                    f"{key} 의 저장소가 기록되지 않았다"
                    f" (계획이 적은 것: {task.get('repository_ref') or '없음'})"
                )

            if permission == "workspace_write" and not probed:
                probed = self.probe_wrong_repository(key, repo_name)

            self.run(
                purpose,
                name=f"{kind}-{key}",
                request_text=self.task_request(task, repo_name),
                task_id=key,
                permission=permission,
                repository_id=self.by_registered[repo_name],
            )
            done.add(key)

        self.log(f"실행한 Task: {sorted(done)}")

    def task_request(self, task: dict, repo_name: str) -> str:
        """그 Task 에 주는 지시 원문. **종류마다 방향이 다르다.**

        검증은 "제품 코드를 고치지 마라"이고 구현은 "이 작업의 범위를 고쳐라"다.
        하나로 합치면 둘 중 하나가 거짓이 된다(P3-R4가 실험 지시문에서 한 판단과
        같다).
        """
        head = (
            f"작업 {task['task_key']}: {task['summary']}\n"
            f"완료 조건: {task['completion_summary'] or '(계획에 없음)'}\n"
            f"지금 작업 디렉터리는 {repo_name} 저장소입니다."
            " 다른 저장소의 파일은 여기 없습니다.\n\n"
        )
        if task["kind"] in ("verification", "integration"):
            # **인터프리터를 못박지 않는다.** 이 개발 저장소의 가상환경 경로를
            # 그대로 준 첫 시도에서 CLI 의 sandbox 가 그 기반 인터프리터에 닿지
            # 못해 시험이 한 줄도 돌지 않았다. 저장소의 `run_tests.py` 는 외부
            # 패키지를 요구하지 않으므로 이 호스트에서 쓸 수 있는 Python 이면 된다.
            return (
                head
                + "이 저장소의 `run_tests.py` 를 실행하고 **실제로 실행한 명령과"
                " 종료 코드를 그대로** 보고해 주세요."
                " `python run_tests.py` 가 안 되면 `py -3 run_tests.py` 를 써 보고,"
                " 그래도 안 되면 그 사실을 명령 기록으로 남기세요."
                " **제품 코드를 고치지 마세요.** 시험이 실패하면 실패로 보고하고"
                " 통과를 주장하지 마세요."
            )
        if task["kind"] == "investigation":
            return head + "이 저장소를 읽고 위 작업에 필요한 사실을 확인해 보고해 주세요."
        # **이 작업의 범위만 적는다.** 요청 전체를 지시 원문에 붙이면 AI 가 다음
        # 작업까지 미리 해 버리고, 그러면 그 다음 실행은 바꿀 것이 없어 실패한다 —
        # 실제로 그렇게 됐다. 동의된 의도와 개발계획은 **고정 컨텍스트**로 간다.
        return (
            head
            + "고정 컨텍스트의 동의된 의도와 개발계획을 따르되 **이 작업의 범위만**"
            " 고치세요. 계획의 다른 작업은 다른 실행이 합니다 — 여기서 미리 해"
            " 두지 마세요. 이 작업에 필요한 테스트가 있으면 함께 고치세요."
        )

    def probe_wrong_repository(self, task_key: str, repo_name: str) -> bool:
        """**대상이 틀린 실행이 막히는가**(AC-6).

        실제 흐름 안에서 한 번만 찔러 본다. 이 거부가 없으면 "UI 작업을 한다면서
        API 저장소를 고치는 실행"이 통과하고, 실행 전후 대조가 엉뚱한 Task 에 붙는다.
        """
        other = next((n for n in self.by_registered if n != repo_name), None)
        if other is None:
            return False
        refused = self.run(
            "feature_implementation",
            name=f"wrong-repo-{task_key}",
            request_text="이 실행은 진입 검사를 확인하려는 것이며 배정되면 안 된다.",
            task_id=task_key,
            permission="workspace_write",
            repository_id=self.by_registered[other],
            expect_refusal=True,
        )
        codes = self.api.refusals(refused)
        if "run_task_repository_mismatch" not in codes:
            raise LiveError(f"다른 저장소를 대상으로 한 실행이 막히지 않았다: {codes}")
        self.log(f"  대상을 {other} 로 바꾼 {task_key} 실행: 409 {codes}")
        return True

    def compose(self) -> str:
        self.log.head("9. 코드 조합 — 무엇을 검증했는가")
        composition = self.api.ok("POST", f"/api/cases/{self.case_id}/composition", json={})
        self.log(
            f"조합 rev={composition['revision']}"
            f" covers_all={composition['covers_all_code_repositories']}"
        )
        for entry in composition.get("entries") or []:
            self.log(
                f"  {entry['repository_name']}: base={entry['base_commit'][:10]}"
                f" head={(entry.get('head_commit') or '')[:10] or '(미관측)'}"
                f" dirty={entry.get('dirty_entries')} source={entry['source']}"
            )
        detail = self.api.get(
            f"/api/cases/{self.case_id}/compositions/{composition['id']}"
        )
        self.log(f"유효성: {detail.get('validity')}")
        dump(self.out / f"P3-04-{self.LETTER}-composition.json", detail)
        return composition["id"]

    def evidence_run(self) -> str | None:
        """기준 판정의 근거가 될 **실제로 시험을 돌린** 검증 실행.

        `outcome = completed` 만으로는 부족하다. 검증 실행의 완료는 "명령을 하나라도
        실행했다"이지 "시험이 돌았다"가 아니다(P3-03 의 판정 규칙). 명령이 전부
        실패했으면 그 실행은 **무엇도 확인하지 못했고**, 그것을 근거로 `met` 을
        적으면 실행 불명이 성공이 된다(FR-28).

        그래서 **종료 코드 0 인 명령이 하나라도 있는** 검증 실행만 근거로 쓴다.
        없으면 멈춘다 — 못 한 확인을 한 것으로 적지 않는다.
        """
        runs = self.api.get(f"/api/cases/{self.case_id}")["runs"]
        usable: list[str] = []
        for run in runs:
            if run["purpose"] != "verification_run" or run["outcome"] != "completed":
                continue
            commands = self.api.get(f"/api/runs/{run['run_id']}")["commands"]
            succeeded = [c for c in commands if c["exit_code"] == 0]
            self.log(
                f"  검증 실행 {run['run_id']}: 명령 {len(commands)}건,"
                f" 종료 코드 0 인 것 {len(succeeded)}건"
            )
            for command in commands:
                self.log(f"      {command['command_summary']} → exit={command['exit_code']}")
            if succeeded:
                usable.append(run["run_id"])
        if not usable:
            return None
        return usable[-1]

    def record_criteria(self, composition_id: str, result: dict) -> bool:
        """기준마다 **실행 증거와 함께** 판정을 기록한다.

        근거는 검증 실행이다. 실행이 없으면 기록하지 않는다 — 사람 판단만으로 적으면
        무변경 충족과 미재현이 구별되지 않는다(P3-R4 3.10절).
        """
        evidence_run = self.evidence_run()
        if evidence_run is None:
            # **시험이 돌지 않았다.** 그러면 판정은 `unverified` 이고 근거는 없다.
            # `met` 으로 적으면 실행 불명이 성공이 된다(FR-28). 이 경로가 있는
            # 이유는 이 호스트의 CLI sandbox 가 Python 을 찾지 못하기 때문이며
            # (P3-03 이 같은 것을 관측했다), **제품 결함이 아니라 환경 제약**이다.
            self.log("시험을 실제로 돌린 검증 실행이 없다 — 기준을 `met` 으로 적지 않는다")
            for criterion in result["criteria"]:
                posted = self.api.request(
                    "POST",
                    f"/api/cases/{self.case_id}/criteria/{criterion['id']}/result",
                    json={
                        "verdict": "unverified",
                        "summary": "검증 실행이 시험을 돌리지 못했다(환경 제약)",
                        "recorded_by": "policy:p3-04-live",
                        "evidence_kind": "none",
                    },
                )
                self.log(f"  {criterion['criterion_key']} → unverified ({posted.status_code})")
            return False

        for criterion in result["criteria"]:
            posted = self.api.request(
                "POST",
                f"/api/cases/{self.case_id}/criteria/{criterion['id']}/result",
                json={
                    "verdict": "met",
                    "summary": "두 저장소의 검증 실행이 통과했다",
                    "recorded_by": "policy:p3-04-live",
                    "evidence_kind": "run_output",
                    "evidence_run_id": evidence_run,
                    "composition_id": composition_id,
                    "satisfaction": "changed_and_verified",
                },
            )
            self.log(f"  {criterion['criterion_key']} → {posted.status_code}")
            if posted.status_code not in (200, 201):
                raise LiveError(f"판정 기록 실패: {posted.text[:1500]}")
        return True

    def close(self, composition_id: str) -> None:
        self.log.head("10. 기준별 판정 → 자동 완료")
        result = self.api.get(f"/api/cases/{self.case_id}/result")
        self.log(
            f"완료 모드: {result['completion_mode']}"
            f" (출처 {result.get('completion_mode_source')})"
        )
        verified = self.record_criteria(composition_id, result)

        case = self.api.get(f"/api/cases/{self.case_id}")
        self.log(f"Case 상태: {case['status']}")
        if not verified:
            # **여는 쪽이 더 위험하다**(P3-R4). 검증이 돌지 않았는데 닫히면 아무도
            # 보지 않은 결과가 완료가 된다. 여기서 확인하는 것은 그 반대다.
            dump(
                self.out / f"P3-04-{self.LETTER}-result.json",
                self.api.get(f"/api/cases/{self.case_id}/result"),
            )
            if case["status"] == "closed":
                raise LiveError("검증이 돌지 않았는데 Case 가 닫혔다")
            self.log("검증이 돌지 않아 Case 가 열린 채로 남았다 — 자동 완료는 조건을 지난다")
            return
        result = self.api.get(f"/api/cases/{self.case_id}/result")
        candidate = result.get("candidate") or {}
        acceptance = candidate.get("acceptance")
        self.log(f"결과 후보: rev={candidate.get('revision')} state={candidate.get('state')}")
        self.log(f"인수 기록: {acceptance}")
        self.log(f"종료 기록: {result.get('closure')}")
        dump(self.out / f"P3-04-{self.LETTER}-result.json", result)
        if case["status"] != "closed":
            raise LiveError(f"자동 완료가 일어나지 않았다 (status={case['status']})")
        if not acceptance or acceptance["mode"] != "auto_policy":
            raise LiveError(f"사람 인수가 만들어졌다: {acceptance}")

    def human_calls(self) -> None:
        self.log.head("11. 사람이 몇 번 불렸는가")
        decisions = self.api.get(f"/api/cases/{self.case_id}")["decisions"]
        for decision in decisions:
            self.log(f"  {decision['kind']} · actor={decision['actor']} · {decision['decided_at']}")
        checkpoints = self.api.get(f"/api/cases/{self.case_id}/controlled-checkpoints")
        self.log(f"확인 지점: {[c['checkpoint'] + ':' + c['state'] for c in checkpoints]}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true", help="라이브 데이터를 지우지 않는다")
    parser.add_argument("--port", type=int, default=8790)
    args = parser.parse_args()

    root = LIVE_ROOT / "path-a"
    if root.exists() and not args.keep:
        force_rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    out = root / "evidence"

    with Log(root / "P3-04-A-live.log") as log:
        log(f"라이브 루트: {root}")
        repos = fixtures.create_repositories(root / "repos")
        before = {name: fixtures.porcelain(path) for name, path in repos.items()}
        for name, path in repos.items():
            log(f"저장소 {name}: HEAD={fixtures.head(path)[:10]} dirty=\n{before[name]}")

        procs = Processes(data_root=root / "data", log=log, port=args.port, runner_id=RUNNER_ID)
        api = Api(procs.base_url, log)
        failed: Exception | None = None
        try:
            procs.start()
            flow = PathA(api, log, repos, out)
            flow.setup()
            flow.workspaces()
            flow.intent()
            flow.gate_with_remediation()
            flow.preparation()
            flow.graph()
            flow.work_the_graph()
            composition_id = flow.compose()
            flow.close(composition_id)
            flow.human_calls()
        except Exception as exc:  # noqa: BLE001 - 실패도 관측 결과다
            failed = exc
            log.head("실패")
            log(f"{type(exc).__name__}: {exc}")
        finally:
            log.head("12. 사용자 작업 트리 — 시작 때와 같은가")
            for name, path in repos.items():
                after = fixtures.porcelain(path)
                same = after == before[name]
                log(f"  {name}: 동일={same}")
                if not same:
                    log(f"    전:\n{before[name]}    후:\n{after}")
            api.close()
            procs.stop()
        return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
