"""P4-03 라이브 — 실제 codex 가 v2 Profile 의 의도 초안에 목적·의무·결론 요구를 적는가.

P4-03 은 새 **AI 출력 계약**을 만들었다. 의도 초안이 최상위 `objectives`, 기준마다
`obligation`, 원인·조사 기준에 `conclusion_rule` 을 적는다. 자동 시험은
`FakeCliExecutor` 가 올바른 형식을 내므로 지시문의 구멍을 볼 수 없다 — P3-R4 의
결합 기록이 정확히 그렇게 실패했다(R4 결과 6절). 그래서 실제 CLI 로 확인한다.

보는 것은 세 Case 다.

    A. defect-fix + "원인도 확정해 달라"  혼합 목적. objectives 에 cause, 원인 기준에
                                          definitive_required 가 적히는가
    B. research + "판단 불가도 보고로 충분" 조사 기준에 bounded_report_allowed 가 적히는가
    C. refactoring                         보존 기준이 개선 기준과 **별도로** 적히는가

**판정은 AI 가 지시를 따랐는가이지 제품 규칙의 통과가 아니다.** 제품 규칙(구조 보고가
받아들여지는가, 도출·계약이 적용되는가)은 실패하면 `LiveError` 로 멈추고, AI 가 기대와
다르게 쓴 것은 멈추지 않고 **관찰로 기록한다** — 그것이 이 라이브가 찾으려는 것이다.

**제품 코드를 import 하지 않는다.** HTTP 로만 부른다(p3/live/driver.py 와 같은 규칙).
실행: `.venv\\Scripts\\python.exe p4\\live\\profile_intents.py`
"""

from __future__ import annotations

import json
import os
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

RUNNER_ID = "runner-p4-03-live"
TOOL = {"tool_id": "codex", "mode": "exec"}
OUT = REPO_ROOT / "p4" / "evidence"
LIVE_ROOT = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Temp" / "hads-p4-03-live"

CASES: list[dict[str, Any]] = [
    {
        "letter": "A",
        "profile": "defect_fix",
        "title": "저장 뒤 목록이 옛 값을 보인다",
        "request": (
            "저장 버튼을 누른 뒤 목록 화면으로 돌아오면 방금 바꾼 값이 아니라 이전 값이"
            " 보입니다. 새로 고침하면 새 값이 나옵니다. `store.py` 의 `save()` 와"
            " `list_items()` 를 봐 주세요.\n\n"
            "**원인을 확정해 주시고, 그 원인을 고쳐 주세요.** 원인을 확정하지 못한 채"
            " 증상만 사라지게 한 것은 완료가 아닙니다."
        ),
        "expect_objectives": {"cause"},
        "expect_rules": {"cause": "definitive_required"},
    },
    {
        "letter": "B",
        "profile": "research",
        "title": "JSON 직렬화 후보 비교",
        "request": (
            "우리 `store.py` 의 저장 경로에서 표준 `json` 과 `orjson` 중 무엇이 나은지"
            " 조사해 주세요. 기준은 1만 건 저장 시간과 추가 의존성 부담입니다.\n\n"
            "로컬에서 측정해 보고 **우열을 가리지 못하면 근거와 한계를 보고하는 것으로"
            " 충분합니다.** 제품 코드는 바꾸지 마세요."
        ),
        "expect_objectives": set(),
        "expect_rules": {"answer": "bounded_report_allowed"},
    },
    {
        "letter": "C",
        "profile": "refactoring",
        "title": "저장소 모듈 정리",
        "request": (
            "`store.py` 의 `save()` 와 `list_items()` 에 중복된 파일 읽기 코드를 한 곳으로"
            " 모아 주세요. **공개 함수 이름과 반환 형식은 그대로** 두어야 하고, 기존"
            " 호출하는 쪽을 고치지 않아야 합니다."
        ),
        "expect_objectives": set(),
        "expect_rules": {},
    },
]

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


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


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


class Probe:
    def __init__(self, api: Api, log: Log, repo: Path, tag: str) -> None:
        self.api = api
        self.log = log
        self.repo = repo
        self.tag = tag
        self.project_id = ""
        self.observations: list[dict[str, Any]] = []

    def setup(self) -> None:
        project = self.api.ok(
            "POST",
            "/api/projects",
            json={
                "name": f"p4-03-live-{self.tag}",
                "repo_path": str(self.repo),
                "default_tool_id": "codex",
            },
        )
        self.project_id = project["id"]

    def instruction(self, case_id: str, text: str) -> str:
        accepted = self.api.ok(
            "POST",
            f"/api/cases/{case_id}/artifacts",
            json={
                "kind": "instruction",
                "content": text,
                "summary": "의도 초안 작성 요청",
                "target_runner_id": RUNNER_ID,
            },
        )
        wait_until(
            lambda: self.api.get(f"/api/intakes/{accepted['intake_id']}")["state"] == "stored",
            "요청 원문 저장",
            timeout=120,
        )
        return accepted["artifact_id"]

    def original(self, intent: dict[str, Any]) -> str:
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
        return served["content"]

    def draft(self, spec: dict[str, Any]) -> dict[str, Any]:
        letter = spec["letter"]
        self.log.head(f"{letter}. {spec['profile']} — {spec['title']}")
        case = self.api.ok(
            "POST",
            f"/api/projects/{self.project_id}/cases",
            json={"title": spec["title"], "profile": spec["profile"]},
        )
        case_id = case["id"]
        profile = self.api.get(f"/api/cases/{case_id}/policy")["profile"]
        self.log(f"Case {case_id} profile={profile['profile']} version={profile['version']}")
        if profile["version"] != "2":
            raise LiveError("새 Case 가 정의판 2 를 받지 않았다")

        artifact_id = self.instruction(case_id, spec["request"])
        run_id = f"run-p4-03-{letter}-{self.tag}"
        response = self.api.request(
            "POST",
            f"/api/cases/{case_id}/runs",
            json={
                "run_id": run_id,
                "instruction_artifact_id": artifact_id,
                "instruction_artifact_rev": 1,
                "purpose": "intent_authoring",
                "role": "author",
                "permission": "read_only",
                "task_id": "task-intent",
                **TOOL,
            },
        )
        if response.status_code not in (200, 201):
            raise LiveError(f"의도 작성 실행이 거부됐다 {response.status_code}\n{response.text}")
        run = wait_until(
            lambda: (lambda r: r if r["status"] == "finished" else None)(
                self.api.get(f"/api/runs/{run_id}")
            ),
            f"{letter} 의도 작성",
        )
        self.log(
            f"run {run_id} outcome={run['outcome']} exit={run.get('exit_code')}"
            f" version={run.get('observed_tool_version')}"
        )
        if run["outcome"] != "completed":
            # **제품 규칙 쪽의 실패다.** 파서·문서 작성이 AI 출력을 받지 못했다.
            raise LiveError(f"{letter} 의도 작성 실행이 {run['outcome']} 로 끝났다")

        intent = self.api.get(f"/api/cases/{case_id}/intent-state")["latest_intent_version"]
        body = self.original(intent)
        (OUT / f"P4-03-live-{letter}-intent-original.json").write_text(body, encoding="utf-8")
        doc = json.loads(body)
        result = self.api.get(f"/api/cases/{case_id}/result")
        meaning = result["completion_meaning"]
        criteria = [
            {
                "key": c["criterion_key"],
                "relates_to": c["relates_to"],
                "obligation": c["obligation"],
                "obligation_source": c["obligation_source"],
                "conclusion_rule": c["conclusion_rule"],
                "conclusion_rule_effective": c["conclusion_rule_effective"],
                "summary": c["summary"],
            }
            for c in result["criteria"]
        ]
        self.log.json(f"{letter} 기준", criteria)
        self.log.json(f"{letter} 목적별 완료 의미", meaning["objectives"])

        checks = self.check(spec, doc, criteria, meaning)
        observation = {
            "letter": letter,
            "profile": spec["profile"],
            "case_id": case_id,
            "run_id": run_id,
            "observed_tool_version": run.get("observed_tool_version"),
            "doc_version": doc.get("doc_version"),
            "doc_objectives": doc.get("objectives"),
            "declared_objectives": meaning["declared_objectives"],
            "criteria": criteria,
            "objectives": meaning["objectives"],
            "missing": meaning["missing"],
            "checks": checks,
        }
        self.observations.append(observation)
        return observation

    def check(
        self,
        spec: dict[str, Any],
        doc: dict[str, Any],
        criteria: list[dict[str, Any]],
        meaning: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """AI 가 지시를 따랐는가. **통과하지 않아도 멈추지 않는다** — 관찰이다."""
        results: list[dict[str, Any]] = []

        def note(name: str, ok: bool, detail: str) -> None:
            results.append({"check": name, "ok": ok, "detail": detail})
            self.log(f"  [{'OK' if ok else '관찰'}] {name}: {detail}")

        note("doc_version_5", doc.get("doc_version") == 5, f"doc_version={doc.get('doc_version')}")
        declared = set(doc.get("objectives") or [])
        note(
            "objectives_declared",
            spec["expect_objectives"] <= declared,
            f"기대 {sorted(spec['expect_objectives'])} ⊆ 문서 {sorted(declared)}",
        )
        reported = [c for c in criteria if c["obligation_source"] == "reported"]
        note(
            "obligations_reported",
            len(reported) == len(criteria) and bool(criteria),
            f"원문이 의무를 적은 기준 {len(reported)}/{len(criteria)}",
        )
        for obligation, rule in spec["expect_rules"].items():
            rules = {c["conclusion_rule"] for c in criteria if c["obligation"] == obligation}
            note(
                f"conclusion_rule_{obligation}",
                rule in rules,
                f"{obligation} 기준의 결론 요구 {sorted(r or 'NULL' for r in rules)} (기대 {rule})",
            )
        note(
            "every_required_objective_has_a_criterion",
            not meaning["missing"],
            f"기준 없는 목적 {meaning['missing']}",
        )
        return results


def main() -> int:
    tag = stamp()
    root = LIVE_ROOT / tag
    root.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    with Log(OUT / "P4-03-live.log") as log:
        log.head(f"P4-03 라이브 {tag} — 데이터 {root}")
        repo = make_repo(root)
        procs = Processes(data_root=root, log=log, port=8793, runner_id=RUNNER_ID)
        api: Api | None = None
        try:
            procs.start()
            api = Api(procs.base_url, log)
            wait_until(
                lambda: any(r["id"] == RUNNER_ID for r in api.get("/api/runners")),
                f"Runner {RUNNER_ID} 등록",
                timeout=60,
            )
            probe = Probe(api, log, repo, tag)
            probe.setup()
            for spec in CASES:
                probe.draft(spec)
            summary = {
                "tag": tag,
                "data_root": str(root),
                "observations": probe.observations,
            }
            (OUT / "P4-03-live-results.json").write_text(
                json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            failed = [
                (o["letter"], c["check"])
                for o in probe.observations
                for c in o["checks"]
                if not c["ok"]
            ]
            log.head("요약")
            log(f"관찰(지시와 다름): {failed or '없음'}")
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
