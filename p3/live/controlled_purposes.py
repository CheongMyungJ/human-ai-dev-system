"""controlled 의 시작 확인이 **막는 목적 전부**를 실제 프로세스에서 확인한다(AC-15).

경로 B 라이브는 기능 흐름 안에서 그 축을 확인하고, 거기서 찔러 보는 것은 설계
하나다. 막히는 목적은 다섯이며(`domain/progression.py` 의 `NEEDS_CONTROLLED_START`)
그 전부를 한 자리에서 보는 것이 이 스크립트다.

**AI 실행은 하나도 일어나지 않는다.** 다섯 요청이 전부 진입에서 거부되므로 codex 가
불리지 않고, 그래서 몇 초에 끝난다. 경로 B 를 다시 돌려 확인할 종류의 사실이 아니다.

확인 뒤에는 같은 요청에서 **그 사유만 사라진다.** 다른 사유(의도 미동의·게이트
미통과)는 그대로 남는 것이 정상이며, 여기서 보는 것은 이 축이 막았는지 하나다.

사용법:

    .venv\\Scripts\\python.exe p3\\live\\controlled_purposes.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixtures  # noqa: E402
from driver import (  # noqa: E402
    Api, LiveError, Log, Processes, force_rmtree, wait_until,
)
from path_a import LIVE_ROOT, RUNNER_ID, dump  # noqa: E402
from path_bc import PathB  # noqa: E402

#: 시작 확인 전에 배정하지 않는 목적과 그 실행이 요구하는 권한.
#:
#: **초안 작성·의미 검토·조사는 여기 없다.** 사람이 시작 범위를 확인하려면 초안이
#: 먼저 있어야 하고, 조사까지 막으면 확인에 필요한 사실을 모을 수 없다(D-65).
BLOCKED = (
    ("design_authoring", "read_only"),
    ("plan_authoring", "read_only"),
    ("feature_implementation", "workspace_write"),
    ("verification_run", "workspace_write"),
    ("local_experiment", "workspace_write"),
)

#: 시작 확인과 무관하게 **열려 있어야** 하는 목적. 막히면 확인 자체가 불가능해진다.
OPEN_BEFORE_START = (("limited_analysis", "read_only"),)

CODE = "controlled_start_not_confirmed"


class Probe(PathB):
    """`PathB` 의 설정(controlled·두 저장소 선택)만 쓰고 흐름은 타지 않는다."""

    LETTER = "B-purposes"

    def probe(self, round_tag: str) -> dict[str, list[str]]:
        seen: dict[str, list[str]] = {}
        for purpose, permission in BLOCKED + OPEN_BEFORE_START:
            try:
                response = self.run(
                    purpose,
                    name=f"{purpose}-{round_tag}",
                    request_text=(
                        "이 요청은 진입 검사를 확인하려는 것이며 배정되면 안 된다."
                    ),
                    permission=permission,
                    repository_id=self.repo_ids[fixtures.CORE_NAME],
                    expect_refusal=True,
                )
            except LiveError as exc:
                if (purpose, permission) in BLOCKED:
                    raise
                # 열려 있어야 하는 목적은 **실제로 배정되어** 돌 수 있다. 그 실행이
                # 어떻게 끝났는지는 이 축의 질문이 아니다 — 막히지 않았다는 것이
                # 확인하려는 것이고, 실행 결과를 여기서 성공으로도 실패로도 적지 않는다.
                seen[purpose] = [f"(배정됨·실행 {type(exc).__name__})"]
                self.log(f"  {purpose}: 배정됐다(실행은 {exc})")
                continue
            if not hasattr(response, "status_code"):
                # 거부되지 않고 실제로 배정됐다. 그 자체가 관측 결과다.
                seen[purpose] = ["(배정됨)"]
                self.log(f"  {purpose}: **배정됐다** — 거부되지 않았다")
                continue
            codes = self.api.refusals(response)
            seen[purpose] = codes
            self.log(f"  {purpose}: 409 {codes}")
        return seen


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--port", type=int, default=8793)
    args = parser.parse_args()

    root = LIVE_ROOT / "controlled-purposes"
    if root.exists() and not args.keep:
        force_rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    out = root / "evidence"

    with Log(root / "P3-04-B-purposes.log") as log:
        log(f"라이브 루트: {root}")
        repos = fixtures.create_repositories(root / "repos")
        procs = Processes(data_root=root / "data", log=log, port=args.port, runner_id=RUNNER_ID)
        api = Api(procs.base_url, log)
        failed: Exception | None = None
        try:
            procs.start()
            # **Runner 가 등록될 때까지 기다린다.** 경로 A·B 는 작업공간 준비가 그
            # 시간을 벌어 주지만 이 스크립트는 작업공간을 만들지 않는다 — 기다리지
            # 않으면 첫 지시 원문 접수가 "runner not found" 로 죽고, 그것은 제품이
            # 아니라 하네스의 순서 문제다.
            wait_until(
                lambda: any(
                    r["id"] == RUNNER_ID for r in api.get("/api/runners")
                ),
                f"Runner {RUNNER_ID} 등록",
                timeout=60,
            )
            probe = Probe(api, log, repos, out)
            probe.setup()

            log.head("1. 시작 확인 전 — 다섯 목적이 전부 막힌다")
            before = probe.probe("before")
            missing = [p for p, _ in BLOCKED if CODE not in before.get(p, [])]
            if missing:
                raise LiveError(f"시작 확인 전인데 이 목적이 막히지 않았다: {missing}")
            for purpose, _ in OPEN_BEFORE_START:
                if CODE in before.get(purpose, []):
                    raise LiveError(f"{purpose} 까지 막혔다 — 확인에 필요한 조사가 닫힌다")
            log("  조사(`limited_analysis`)에는 이 사유가 없다 — 열려 있어야 하는 쪽이다")

            probe.confirm_start()

            log.head("2. 확인 뒤 — 그 사유만 사라진다")
            after = probe.probe("after")
            still = [p for p, _ in BLOCKED if CODE in after.get(p, [])]
            if still:
                raise LiveError(f"시작을 확인했는데 이 목적이 아직 그 사유로 막힌다: {still}")
            log("  다른 사유(의도 미동의·게이트 미통과)는 그대로 남는다 — 정상이다")

            dump(out / "P3-04-B-purposes.json", {"before": before, "after": after})
        except Exception as exc:  # noqa: BLE001 - 실패도 관측 결과다
            failed = exc
            log.head("실패")
            log(f"{type(exc).__name__}: {exc}")
        finally:
            api.close()
            procs.stop()
        return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
