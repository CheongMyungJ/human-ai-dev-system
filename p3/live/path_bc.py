"""경로 B(controlled)와 경로 C(예산 도달) — 같은 요청, 다른 Case.

**한 Case 가 두 경로를 동시에 탈 수 없다**(P3-R4 결과 5절). Autonomy 가 다르면
다른 Case 이고, 예산 도달은 흐름 도중에 걸려야 의미가 있으므로 또 다른 Case 다.

두 경로가 확인하려는 것은 경로 A 와 다르다.

**B:** controlled 가 **기능 흐름 안에서** 사람을 기다리는 모습. R4 는 조건을 만든
직후에 그 조건 하나만 찔러 확인했다. 진행 도중에 걸리면 무엇이 멈추고 무엇이
계속되는지는 다른 질문이다.

**C:** 예산 hard 도달이 **완료도 취소도 아니라는 것.** 새 배정을 막되 진행 중
실행의 결과는 계속 받고 `case.status` 를 바꾸지 않으며, 재개 경로는 한도 변경
하나뿐이다(D-61).

사용법:

    .venv\\Scripts\\python.exe p3\\live\\path_bc.py --path b
    .venv\\Scripts\\python.exe p3\\live\\path_bc.py --path c
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixtures  # noqa: E402
from driver import Api, LiveError, Log, Processes, force_rmtree  # noqa: E402
from path_a import LIVE_ROOT, REQUEST, RUNNER_ID, PathA, dump  # noqa: E402


class PathB(PathA):
    """controlled — 시작 확인 전에는 아무 것도 배정되지 않고, 종료에 확인이 든다."""

    AUTONOMY = "controlled"
    AUTONOMY_REASON = "이 업무는 시작과 결과를 사람이 확인한다"
    LETTER = "B"

    #: 제어부를 강제 종료하고 다시 띄우는 데 쓴다(AC-19). `main()` 이 넣어 준다.
    procs: Processes | None = None

    def blocked_before_start(self) -> None:
        self.log.head("2.5 시작 확인 전 — 무엇이 막히고 무엇이 열리는가")
        policy = self.api.get(f"/api/cases/{self.case_id}/policy")
        self.log(
            "확인 지점: "
            + ", ".join(
                f"{c['checkpoint']}={c['state']}" for c in policy.get("checkpoints") or []
            )
        )
        refused = self.run(
            "design_authoring",
            name="design-before-start",
            request_text="시작 확인 전에는 배정되면 안 되는 요청이다.",
            repository_id=self.repo_ids[fixtures.CORE_NAME],
            expect_refusal=True,
        )
        codes = self.api.refusals(refused)
        if "controlled_start_not_confirmed" not in codes:
            raise LiveError(f"controlled 가 설계를 막지 않았다: {codes}")
        self.log(f"설계 요청: 409 {codes}")
        self.log("  — 다른 사유가 함께 있는 것이 정상이다. 이 축이 막았다는 증거는 위 코드 하나다")

    def confirm_start(self) -> None:
        self.log.head("4.5 사람이 시작을 확인한다")
        self.api.ok(
            "POST",
            f"/api/cases/{self.case_id}/controlled-checkpoints/start_scope/confirmation",
            json={
                "confirmed_by": "owner",
                "explicit": True,
                "subject_type": "case",
                "subject_id": self.case_id,
                "note_summary": "목표·범위·기준·허용 행동을 확인했다",
            },
        )
        checkpoints = self.api.get(f"/api/cases/{self.case_id}/controlled-checkpoints")
        self.log(f"확인 지점: {[c['checkpoint'] + ':' + c['state'] for c in checkpoints]}")
        dump(self.out / f"P3-04-{self.LETTER}-checkpoints-start.json", checkpoints)

    # ------------------------------------------- AC-19 강제 종료 뒤의 복원

    def restore_snapshot(self, composition_id: str) -> dict:
        """강제 종료 전후로 **같은 조회를** 읽어 비교할 값(AC-19).

        시간 지표는 넣지 않는다. 미정리 실행의 경과 시간은 조회 시점에서 계산되므로
        두 조회가 같을 수 없고, 그 차이는 복원 실패가 아니다(R3).
        """
        graph = self.api.get(f"/api/cases/{self.case_id}/work-graph")
        composition = self.api.get(
            f"/api/cases/{self.case_id}/compositions/{composition_id}"
        )
        result = self.api.get(f"/api/cases/{self.case_id}/result")
        budget = self.api.get(f"/api/cases/{self.case_id}/budget")
        return {
            "tasks": [
                {
                    "task_key": task["task_key"],
                    "repository_id": task.get("repository_id"),
                    "repository_name": task.get("repository_name"),
                    "repository_ref": task.get("repository_ref"),
                }
                for task in graph.get("tasks") or []
            ],
            "composition": {
                "revision": composition.get("revision"),
                "covers_all": composition.get("covers_all_code_repositories"),
                "validity": composition.get("validity"),
                "entries": [
                    {
                        "repository_name": entry.get("repository_name"),
                        "base_commit": entry.get("base_commit"),
                        "head_commit": entry.get("head_commit"),
                        "dirty_entries": entry.get("dirty_entries"),
                        "source": entry.get("source"),
                    }
                    for entry in composition.get("entries") or []
                ],
            },
            "criteria": [
                {
                    "key": criterion.get("criterion_key"),
                    "verdict": criterion.get("verdict"),
                    "evidence_kind": criterion.get("evidence_kind"),
                }
                for criterion in result.get("criteria") or []
            ],
            "run_count": budget["usage"]["run_count"],
            "reservations": budget.get("reservations"),
        }

    def restart_probe(self, composition_id: str) -> None:
        """제어부를 **강제 종료**하고 다시 띄운다(AC-19).

        정상 종료가 아니라 전원이 끊긴 것과 같은 상태를 만든다. 확인하려는 것은
        v12 의 Task 저장소·코드 조합·기준 판정·예산 예약이 그대로 돌아오는가이고,
        **그 뒤 흐름이 계속되는가**도 같은 질문의 일부다 — 그래서 여기서 끝내지 않고
        종료까지 이어 간다.
        """
        if self.procs is None:
            raise LiveError("강제 종료를 확인하려면 프로세스 핸들이 필요하다")
        self.log.head("10.5 제어부 강제 종료 → 다시 띄우기 → 같은 조회 대조 (AC-19)")
        before = self.restore_snapshot(composition_id)
        dump(self.out / f"P3-04-{self.LETTER}-restart-before.json", before)
        self.log(
            f"종료 전: Task {len(before['tasks'])}건,"
            f" 조합 항목 {len(before['composition']['entries'])}건,"
            f" 기준 {len(before['criteria'])}건,"
            f" 예약 {len(before['reservations'] or [])}건"
        )
        self.procs.kill_controller()
        # 끊긴 프로세스로 열려 있던 연결을 재사용하지 않는다. 하네스의 연결 문제가
        # 제품의 복원 실패로 보이면 안 된다.
        self.api.reconnect()
        self.procs.restart_controller()
        after = self.restore_snapshot(composition_id)
        dump(self.out / f"P3-04-{self.LETTER}-restart-after.json", after)
        for field in ("tasks", "composition", "criteria", "run_count", "reservations"):
            same = before[field] == after[field]
            self.log(f"  {field}: 동일={same}")
            if not same:
                raise LiveError(f"강제 종료 뒤 {field} 가 복원되지 않았다")
        self.log("  Task 저장소·조합·기준 판정·예약이 모두 그대로다")

    # ------------------------------------------------------- 종료 도우미

    def candidate(self) -> dict:
        """지금 내용으로 결과 후보를 만든다(같은 내용이면 기존 후보가 그대로 온다)."""
        built = self.api.ok(
            "POST", f"/api/cases/{self.case_id}/completion-candidates", json={}
        )
        candidate = built["candidate"]
        self.log(
            f"결과 후보 rev={candidate['revision']} (새로 만듦={built['created']})"
            f" 기준 {candidate['criteria_met']}/{candidate['criteria_total']}"
            f" hash={candidate['snapshot_hash'][:12]}"
            f" 미해결={[u['kind'] for u in candidate['unresolved']]}"
        )
        return candidate

    def accept(self, candidate: dict, *, expect_refusal: bool = False):
        """최종 인수를 시도한다. **확인 지점과 다른 기록이다.**

        `confirm_checkpoint()` 는 "사람이 이 후보를 봤다"만 남기고 권한도 인수도
        만들지 않는다(D-65). 종료는 이 기록이며, controlled 에서는 확인 지점이 그
        **선행 조건**이다.
        """
        response = self.api.request(
            "POST",
            f"/api/cases/{self.case_id}/completion-candidates/{candidate['id']}/acceptance",
            json={"actor": "owner", "statement": "이 결과를 인수합니다."},
        )
        if expect_refusal:
            if response.status_code != 409:
                raise LiveError(
                    f"인수가 거부되지 않았다: {response.status_code}\n{response.text[:1500]}"
                )
            return response
        if response.status_code not in (200, 201):
            raise LiveError(f"인수 → {response.status_code}\n{response.text[:1500]}")
        return response.json()

    def confirm_result(self, candidate: dict) -> None:
        self.log.head("10.8 사람이 결과 후보를 확인한다")
        self.api.ok(
            "POST",
            f"/api/cases/{self.case_id}/controlled-checkpoints/result_candidate/confirmation",
            json={
                "confirmed_by": "owner",
                "explicit": True,
                "subject_type": "completion_candidate",
                "subject_id": candidate["id"],
                "subject_hash": candidate["snapshot_hash"],
                "note_summary": "두 저장소의 결과를 확인했다",
            },
        )
        checkpoints = self.api.get(f"/api/cases/{self.case_id}/controlled-checkpoints")
        self.log(f"확인 지점: {[c['checkpoint'] + ':' + c['state'] for c in checkpoints]}")
        dump(self.out / f"P3-04-{self.LETTER}-checkpoints-result.json", checkpoints)

    def stale_probe(self, confirmed: dict) -> dict:
        """**후보 내용이 바뀌면 이전 확인을 쓰지 않는다**(AC-16 둘째 문장).

        사람이 결과를 확인한 뒤 늦은 의견을 남긴다. 미해결 피드백은 후보 내용의
        일부이므로 후보가 새로 생기고, 그러면 확인했던 대상이 아니다 —
        `controlled_confirmation_stale` 이 그 사실이다. 그 의견을 미반영(이유 포함)
        으로 닫으면 내용이 확인했던 것과 **같아지고** 재확인 없이 인수가 열린다.

        두 방향을 정하는 것은 `subject_hash` 비교 하나이며, 그래서 한 흐름에서
        함께 본다.
        """
        self.log.head("10.9 확인 뒤 후보가 바뀌면 그 확인을 쓰지 않는다")
        intent = self.api.get(
            f"/api/cases/{self.case_id}/intent-state"
        )["latest_intent_version"]
        submitted = self.api.ok(
            "POST",
            f"/api/cases/{self.case_id}/feedback",
            json={
                "target_intent_version_id": intent["id"],
                "content": (
                    "결과를 확인한 뒤 남기는 의견입니다. 이 Case 의 범위 밖이며"
                    " 후속 업무에서 볼 것으로 두세요."
                ),
                "summary": "결과 확인 뒤의 늦은 의견",
                "target_runner_id": RUNNER_ID,
            },
        )
        feedback_id = submitted["feedback"]["id"]
        self.log(f"늦은 의견 {feedback_id} — 미해결 피드백이 후보 내용을 바꾼다")

        changed = self.candidate()
        if changed["snapshot_hash"] == confirmed["snapshot_hash"]:
            raise LiveError("미해결 피드백이 후보 내용을 바꾸지 않았다")
        codes = self.api.refusals(self.accept(changed, expect_refusal=True))
        self.log(f"바뀐 후보의 인수 시도: 409 {codes}")
        if "controlled_confirmation_stale" not in codes:
            raise LiveError(f"바뀐 후보가 이전 확인으로 인수됐다: {codes}")
        if "unresolved_feedback" not in codes:
            raise LiveError(f"미해결 피드백이 사유로 드러나지 않았다: {codes}")

        self.api.ok(
            "POST",
            f"/api/cases/{self.case_id}/feedback/{feedback_id}/disposition",
            json={
                "reflected": False,
                "reason": "이 Case 의 범위 밖이며 후속 업무로 넘긴다",
            },
        )
        restored = self.candidate()
        if restored["snapshot_hash"] != confirmed["snapshot_hash"]:
            raise LiveError("같은 내용으로 돌아왔는데 후보 해시가 다르다")
        self.log("  내용이 확인했던 것과 같아졌다 — 재확인을 요구하지 않는다")
        return restored

    def close(self, composition_id: str) -> None:
        """controlled 의 종료. **결과 후보 확인이 선행 조건이다.**

        **이 경로의 종료는 검증된 완료가 아니다.** 이 호스트의 CLI sandbox 가 Python
        에 닿지 못해 검증 실행이 시험을 돌리지 못하고, 그래서 기준은 `unverified` 로
        남는다(경로 A 와 같다). 그 상태의 인수는 `unresolved_criteria` 로 거부되며 —
        **그것이 맞는 동작이다** — 라이브에서 "확인 뒤 종료"를 보려면 사람이 그
        미검증을 **예외로 수용**해야 한다. 원래 판정은 바뀌지 않고 종료 기록의
        종류가 `closed_with_exceptions` 가 된다.
        """
        self.log.head("10. 기준별 판정 → 결과 후보 확인 → 종료")
        result = self.api.get(f"/api/cases/{self.case_id}/result")
        self.log(
            f"완료 모드: {result['completion_mode']}"
            f" (출처 {result.get('completion_mode_source')})"
        )
        if result["completion_mode"] != "human_acceptance":
            raise LiveError("controlled 인데 완료 모드가 사람 인수가 아니다")
        verified = self.record_criteria(composition_id, result)
        if not verified:
            self.log(
                "검증 실행이 시험을 돌리지 못했다(환경 제약) — 기준은 `unverified` 로"
                " 남는다. 이 뒤의 종료는 **검증된 완료가 아니라** 사람이 미검증을"
                " 수용한 종료다"
            )

        case = self.api.get(f"/api/cases/{self.case_id}")
        self.log(f"기준을 모두 기록한 뒤 Case 상태: {case['status']}")
        if case["status"] == "closed":
            raise LiveError("controlled 인데 결과 후보 확인 없이 닫혔다")

        if self.procs is not None:
            self.restart_probe(composition_id)

        self.log.head("10.6 확인 없이는 인수되지 않는다")
        candidate = self.candidate()
        codes = self.api.refusals(self.accept(candidate, expect_refusal=True))
        self.log(f"확인 없는 인수 시도: 409 {codes}")
        if "controlled_result_not_confirmed" not in codes:
            raise LiveError(f"결과 확인 없이 인수가 열렸다: {codes}")
        case = self.api.get(f"/api/cases/{self.case_id}")
        self.log(f"거부 뒤 Case 상태: {case['status']}")
        if case["status"] == "closed":
            raise LiveError("인수가 거부됐는데 Case 가 닫혔다")

        self.confirm_result(candidate)
        candidate = self.stale_probe(candidate)

        self.log.head("10.10 미검증을 사람이 예외로 수용하고 인수한다")
        codes = self.api.refusals(self.accept(candidate, expect_refusal=True))
        self.log(f"예외 수용 전 인수 시도: 409 {codes}")
        if "unresolved_criteria" not in codes:
            raise LiveError(f"미검증 기준이 인수를 막지 않았다: {codes}")
        for item in candidate["unresolved"]:
            if item["kind"] != "criterion":
                raise LiveError(f"기준 아닌 미해결 항목이 남았다: {item}")
            self.api.ok(
                "POST",
                f"/api/cases/{self.case_id}/completion-candidates/{candidate['id']}/exceptions",
                json={
                    "actor": "owner",
                    "criterion_id": item["id"],
                    "scope_summary": "환경 제약으로 검증 실행이 시험을 돌리지 못한 것을 수용한다",
                },
            )
            self.log(f"  예외 수용: {item.get('key')} (판정은 {item['verdict']} 그대로)")

        accepted = self.accept(candidate)
        acceptance = accepted["acceptance"]
        closure = accepted["closure"]
        case = self.api.get(f"/api/cases/{self.case_id}")
        result = self.api.get(f"/api/cases/{self.case_id}/result")
        self.log(f"인수 기록: mode={acceptance['mode']} actor={acceptance['actor']}")
        self.log(f"종료 기록: {closure}")
        self.log(f"인수 뒤 Case 상태: {case['status']}")
        dump(self.out / f"P3-04-{self.LETTER}-result.json", result)
        if case["status"] != "closed":
            raise LiveError("결과를 확인하고 인수했는데 종료되지 않았다")
        if acceptance["mode"] != "human":
            raise LiveError(f"사람의 확인이 정책 인수로 적혔다: {acceptance}")
        if not closure or closure.get("closure_kind") != "closed_with_exceptions":
            raise LiveError(f"예외를 수용한 종료가 그렇게 적히지 않았다: {closure}")
        verdicts = {c["criterion_key"]: c["verdict"] for c in result["criteria"]}
        self.log(f"종료 뒤 기준 판정: {verdicts}")
        if any(v == "met" for v in verdicts.values()):
            raise LiveError("검증이 돌지 않았는데 met 이 적혔다")
        self.log("  예외 수용이 판정을 바꾸지 않았다 — 기준은 여전히 미검증이다")


class PathC(PathA):
    """예산 도달 — 흐름 도중에 걸리고 한도 변경으로만 풀린다."""

    LETTER = "C"
    AUTONOMY_REASON = "요청이 명확하다. 한도만 걸어 둔다"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.limit = 0

    def set_budget(self) -> None:
        """지금까지 쓴 실행 수 **그대로**를 hard 한도로 건다.

        구현 직전에 걸어야 "진행 도중에 걸렸다"가 된다. 처음부터 낮게 걸면 의도
        초안조차 돌지 않아 예산이 기능 흐름을 막는 모습을 볼 수 없다.
        """
        self.log.head("6.5 흐름 도중에 실행 수 한도를 건다")
        budget = self.api.get(f"/api/cases/{self.case_id}/budget")
        used = budget["usage"]["run_count"]
        self.log(
            f"실행 수: settled={used['settled']} held={used['held']}"
            f" unresolved={used['unresolved']} exposure={used['exposure']}"
            f" complete={used['complete']}"
        )
        self.limit = int(used["exposure"] or 0)
        self.log(f"지금까지의 실행 수: {self.limit} → hard 한도를 같은 값으로 건다")
        self.api.ok(
            "PUT",
            f"/api/cases/{self.case_id}/budget",
            json={
                "metric": "run_count",
                "threshold_kind": "hard",
                "limit_value": self.limit,
                "set_by": "owner",
                "reason_summary": "여기까지만 쓰고 멈춘다",
            },
        )
        state = self.api.get(f"/api/cases/{self.case_id}/budget")
        self.log(f"정지 상태: {state.get('stop')}")
        dump(self.out / f"P3-04-{self.LETTER}-budget-stopped.json", state)

    def implement(self, graph: dict) -> None:
        """구현을 요청한다. **첫 요청이 예산으로 막혀야 한다.**"""
        self.log.head("7. 예산이 막고, 한도를 올리면 그대로 이어진다")
        mapping = self.task_repository_map(graph, ("implementation", "integration"))
        task_key, repo_name = mapping[0]

        refused = self.run(
            "feature_implementation",
            name=f"impl-blocked-{task_key}",
            request_text="이 요청은 예산으로 막혀야 한다.",
            task_id=task_key,
            permission="workspace_write",
            repository_id=self.by_registered[repo_name],
            expect_refusal=True,
        )
        codes = self.api.refusals(refused)
        if "budget_hard_limit_reached" not in codes:
            raise LiveError(f"예산이 막지 않았다: {codes}")
        self.log(f"구현 요청: 409 {codes}")

        # **완료도 취소도 아니다.** Case 는 그대로 진행 중이고 기록도 그대로다.
        case = self.api.get(f"/api/cases/{self.case_id}")
        self.log(f"예산 도달 뒤 Case 상태: {case['status']}")
        if case["status"] in ("closed", "cancelled"):
            raise LiveError("예산 도달이 Case 를 끝냈다")

        self.log.head("7.1 한도를 올리면 같은 요청이 그대로 통과한다")
        self.api.ok(
            "PUT",
            f"/api/cases/{self.case_id}/budget",
            json={
                "metric": "run_count",
                "threshold_kind": "hard",
                "limit_value": self.limit + 10,
                "set_by": "owner",
                "reason_summary": "확인했다. 여기까지 더 쓴다",
            },
        )
        for key, name in mapping:
            self.run(
                "feature_implementation",
                name=f"impl-{key}",
                request_text=(
                    f"{REQUEST}\n\n지금 작업 디렉터리는 {name} 저장소이며 이 저장소가"
                    " 맡은 부분만 바꿉니다. 이 저장소의 테스트도 함께 고치세요."
                ),
                task_id=key,
                permission="workspace_write",
                repository_id=self.by_registered[name],
            )
        dump(
            self.out / f"P3-04-{self.LETTER}-budget-final.json",
            self.api.get(f"/api/cases/{self.case_id}/budget"),
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", choices=("b", "c"), required=True)
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--port", type=int, default=8791)
    args = parser.parse_args()

    flow_cls = PathB if args.path == "b" else PathC
    root = LIVE_ROOT / f"path-{args.path}"
    if root.exists() and not args.keep:
        force_rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    out = root / "evidence"

    with Log(root / f"P3-04-{args.path.upper()}-live.log") as log:
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
            flow = flow_cls(api, log, repos, out)
            flow.procs = procs
            flow.setup()
            flow.workspaces()
            if isinstance(flow, PathB):
                flow.blocked_before_start()
            flow.intent()
            flow.gate_with_remediation()
            if isinstance(flow, PathB):
                flow.confirm_start()
            flow.preparation()
            flow.graph()
            if isinstance(flow, PathC):
                flow.set_budget()
            flow.work_the_graph()
            composition_id = flow.compose()
            flow.close(composition_id)
            flow.human_calls()
        except Exception as exc:  # noqa: BLE001 - 실패도 관측 결과다
            failed = exc
            log.head("실패")
            log(f"{type(exc).__name__}: {exc}")
        finally:
            # **띄운 것은 반드시 내린다.** 여기서 로그 한 줄이 실패해도 제어부·Runner
            # 가 살아남으면 다음 시도가 데이터 디렉터리를 지우지 못하고, 그것은
            # 라이브가 아니라 하네스의 고장이다 — 실제로 그렇게 됐다.
            try:
                log.head("12. 사용자 작업 트리 - 시작 때와 같은가")
                for name, path in repos.items():
                    after = fixtures.porcelain(path)
                    same = after == before[name]
                    log(f"  {name}: 동일={same}")
                    if not same:
                        log(f"    전:\n{before[name]}    후:\n{after}")
            finally:
                api.close()
                procs.stop()
        return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
