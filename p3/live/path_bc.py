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
        dump(self.out / f"P3-04-{self.LETTER}-checkpoints.json", checkpoints)

    def close(self, composition_id: str) -> None:
        """controlled 의 종료. **결과 후보 확인이 선행 조건이다.**"""
        self.log.head("10. 기준별 판정 → 결과 후보 확인 → 종료")
        result = self.api.get(f"/api/cases/{self.case_id}/result")
        self.log(
            f"완료 모드: {result['completion_mode']}"
            f" (출처 {result.get('completion_mode_source')})"
        )
        if result["completion_mode"] != "human_acceptance":
            raise LiveError("controlled 인데 완료 모드가 사람 인수가 아니다")
        self.record_criteria(composition_id, result)

        case = self.api.get(f"/api/cases/{self.case_id}")
        self.log(f"기준을 모두 기록한 뒤 Case 상태: {case['status']}")
        if case["status"] == "closed":
            raise LiveError("controlled 인데 결과 후보 확인 없이 닫혔다")

        candidate = self.api.ok(
            "POST", f"/api/cases/{self.case_id}/completion-candidates", json={}
        )["candidate"]
        self.log(
            f"결과 후보 rev={candidate['revision']}"
            f" 기준 {candidate['criteria_met']}/{candidate['criteria_total']}"
            f" 미해결={candidate['unresolved']}"
        )
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

        case = self.api.get(f"/api/cases/{self.case_id}")
        result = self.api.get(f"/api/cases/{self.case_id}/result")
        acceptance = (result.get("candidate") or {}).get("acceptance")
        self.log(f"확인 뒤 Case 상태: {case['status']}")
        self.log(f"인수 기록: {acceptance}")
        self.log(f"종료 기록: {result.get('closure')}")
        dump(self.out / f"P3-04-{self.LETTER}-result.json", result)
        if case["status"] != "closed":
            raise LiveError("결과를 확인했는데 종료되지 않았다")
        if not acceptance or acceptance["mode"] != "human":
            raise LiveError(f"사람의 확인이 정책 인수로 적혔다: {acceptance}")


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
            log.head("12. 사용자 작업 트리 — 시작 때와 같은가")
            for name, path in repos.items():
                after = fixtures.porcelain(path)
                log(f"  {name}: 동일={after == before[name]}")
            api.close()
            procs.stop()
        return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
