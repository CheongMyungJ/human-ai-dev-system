"""시험용 가짜 codex CLI (UI-02, P4-05 에서 업무 단계 목적까지).

**AI 를 부르지 않는다.** 실제 CLI 의 자리(PATH 의 `codex.cmd`)에 놓여 제품 어댑터
(`runner.cli_adapter.CliExecutor`)가 그대로 부르게 하고, 실제 프로세스 트리를 만든다 —
중단·잔류 확인은 가짜 실행기로는 시험할 수 없는 **OS 의 사실**이기 때문이다. 출력은 codex
`exec --json` 의 줄 형식(P1-02 관측)을 따른다.

지시문(stdin)에 든 표지로 동작을 고른다.

    HADS_FAKE_SLEEP=<초>     손자 프로세스를 하나 만들고 둘 다 그만큼 잔다(긴 실행)
    HADS_FAKE_LEAVE_CHILD    손자 프로세스를 남겨 두고 바로 끝낸다(정상 종료 뒤 잔류)
    HADS_FAKE_WRITE=<이름>   작업 디렉터리에 그 파일을 쓴다(부분 변경)
    HADS_FAKE_WORK=<Profile> (UI-03) 준비 단계 논의 응답이면 그 Profile 의 업무 요청으로 해석한다.
                             없으면 논의로 해석한다. 해석 규칙을 받지 않은 응답에는 블록을 붙이지 않는다
    HADS_FAKE_NO_QUESTION    (P4-05) 의도 초안에 질문을 넣지 않는다(기본은 의도 질문 하나)
    HADS_FAKE_IMPL_NOCHANGE  (P4-05b) 구현 실행이 고쳤다고 적지만 파일을 바꾸지 않는다(실패 → 재시도 상한)
    HADS_FAKE_RULE           (P4-06) 논의 응답이 사용자의 마지막 메시지를 프로젝트 필수 규칙으로 옮기는
                             등록 블록(`hads-knowledge`)을 붙인다
    HADS_FAKE_PROPOSAL       (P4-07) 논의 응답이 AI 제안(`proposal: true`) 항목 하나를 등록 블록에 붙인다
    HADS_FAKE_CANDIDATE      (P4-07) 검증 실행이 후보 블록(운영 사실·참고, 근거 한 줄)을 답 뒤에 붙인다.
                             `HADS_FAKE_CANDIDATE_SUPPORTS=K-001` 이면 그 키를 뒷받침하는 관측으로 붙인다

P4-05. **업무 단계 목적**(의도 초안·QG-01 검토·결합 기록·설계·계획·구현·검증·분석)은 지시문의
머리(목적별 지시문)로 알아보고 `tests.conftest` 의 정해진 응답을 낸다. 구현은 작업 디렉터리의
`reader.py` 를 실제로 바꾼다 — 실행 전후 대조가 진짜 파일을 보기 때문이다.

손자·자식의 pid 는 환경 변수 `HADS_FAKE_PIDS` 가 가리키는 디렉터리에 파일로 남긴다 —
시험이 OS 에서 그 프로세스가 정말 끝났는지 **독립적으로** 본다.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path


def emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def note_pid(kind: str, pid: int) -> None:
    root = os.environ.get("HADS_FAKE_PIDS")
    if root:
        Path(root).mkdir(parents=True, exist_ok=True)
        (Path(root) / f"{kind}-{pid}.pid").write_text(str(pid), encoding="utf-8")


#: 이 파일은 PATH 의 `codex.cmd` 가 **어느 작업 디렉터리에서든** 부른다(어댑터 시험은 임시 작업
#: 디렉터리에서 부른다). 정해진 응답을 저장소의 시험 모듈에서 가져오므로 저장소 루트를 직접 잇는다.
REPO_ROOT = Path(__file__).resolve().parents[2]


def work_stage_reply(prompt: str) -> str | None:
    """업무 단계 목적의 정해진 응답. 논의 응답이면 `None`."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from runner import prompts as templates
    from tests import conftest as canned

    head = prompt[:60]

    def starts(template: str) -> bool:
        return head.startswith(template[:40])

    if starts(templates.INTENT_AUTHORING_PROMPT):
        # 첫 초안에는 의도 질문 하나 — 질문 카드·답변 반영 재작성 경로를 화면에서 본다. 답이 고정
        # 문맥에 오면(재작성) 질문 없는 초안을 낸다. 표지로 처음부터 질문을 빼는 것도 된다.
        if "HADS_FAKE_NO_QUESTION" in prompt or "미정 질문에 답한 내용" in prompt:
            return canned.FAKE_DRAFT_RESPONSE
        return canned.FAKE_DRAFT_RESPONSE.replace(
            '"questions": []',
            '"questions": [{"key": "q1", "text": "대소문자를 구분합니까?", "summary": "대소문자 구분",'
            ' "decide_at": "intent"}]',
        )
    if starts(templates.GATE_REVIEW_PROMPT) or starts(templates.QUALITY_GATE_REVIEW_PROMPT):
        return canned.FAKE_REVIEW_CLEAN
    if starts(templates.COMBINED_AUTHORING_PROMPT):
        return canned.FAKE_COMBINED_VERIFIED
    if starts(templates.DESIGN_AUTHORING_PROMPT):
        return canned.FAKE_DESIGN_FULL
    if starts(templates.PLAN_AUTHORING_PROMPT):
        return canned.FAKE_PLAN_VERIFIED
    if starts(templates.FEATURE_IMPLEMENTATION_PROMPT):
        if "HADS_FAKE_IMPL_NOCHANGE" in prompt:
            return canned.FAKE_IMPLEMENTATION_RESPONSE  # 바뀐 것이 없다 → 제품이 실패로 본다
        Path("reader.py").write_text(
            "def read(path):\n    return [l for l in open(path) if l.startswith('ERROR')]\n",
            encoding="utf-8",
        )
        return canned.FAKE_IMPLEMENTATION_RESPONSE
    if starts(templates.VERIFICATION_RUN_PROMPT):
        text = canned.FAKE_VERIFICATION_RESPONSE
        if "HADS_FAKE_CANDIDATE" in prompt and "hads-knowledge" in prompt:
            text += candidate_block(prompt)
        return text
    if starts(templates.LIMITED_ANALYSIS_PROMPT):
        return (
            "원인을 확인했습니다.\n\n```json\n"
            '{"criteria": [{"key": "C-01", "verdict": "met", "conclusion": "determined",'
            ' "summary": "형식 비교로 확정"}, {"key": "C-02", "verdict": "met",'
            ' "conclusion": "determined", "summary": "경로 확인"}]}\n```\n'
        )
    return None


def candidate_block(prompt: str) -> str:
    """P4-07. 검증 실행의 후보 블록. 저장소 이름은 지시문의 후보 규칙이 준 값을 그대로 쓴다(지어내지 않는다)."""
    given = re.search(r'"repository": ("[^"]*"|null)', prompt)
    repository = json.loads(given.group(1)) if given else None
    supports = re.search(r"HADS_FAKE_CANDIDATE_SUPPORTS=(K-\d+)", prompt)
    item = {
        "kind": "operation", "obligation": "reference", "summary": "검증 환경 관찰",
        "content": "CANDIDATE-MARK 이 저장소의 시험은 표본 파일 두 개로 돌고 종료 코드 0 이 정상이다.",
        "basis": "python -m pytest tests/test_reader.py 종료 코드 0", "repository": repository,
        "paths": [], "activities": ["verification"],
        "relates_to": supports.group(1) if supports else None,
        "relation": "supports" if supports else None,
    }
    return "\n\n```hads-knowledge\n" + json.dumps({"items": [item]}, ensure_ascii=False) + "\n```"


def main() -> int:
    if "--version" in sys.argv:
        print("codex-cli 0.0.0-fake")
        return 0
    prompt = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    # 실제 codex 는 UTF-8 로 낸다. 파이프에 쓰는 파이썬의 기본(콘솔 코드 페이지)을 따르지 않는다.
    sys.stdout.reconfigure(encoding="utf-8")
    note_pid("cli", os.getpid())
    emit({"type": "thread.started", "thread_id": f"fake-thread-{os.getpid()}"})
    emit({"type": "turn.started"})

    written = re.search(r"HADS_FAKE_WRITE=([A-Za-z0-9_.-]+)", prompt)
    if written:
        Path(written.group(1)).write_text("partial change\n", encoding="utf-8")

    sleep = re.search(r"HADS_FAKE_SLEEP=(\d+)", prompt)
    if sleep:
        seconds = int(sleep.group(1))
        child = subprocess.Popen([sys.executable, "-c", f"import time; time.sleep({seconds})"])
        note_pid("grandchild", child.pid)
        emit(
            {
                "type": "item.started",
                "item": {"id": "item_1", "type": "command_execution", "command": "sleep"},
            }
        )
        time.sleep(seconds)
        child.wait()
        emit(
            {
                "type": "item.completed",
                "item": {"id": "item_1", "type": "command_execution", "command": "sleep"},
            }
        )

    if "HADS_FAKE_LEAVE_CHILD" in prompt:
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        note_pid("leftover", child.pid)

    text = work_stage_reply(prompt)
    if text is None:
        text = "가짜 응답입니다. 변경한 것은 없습니다."
        if "hads-interpretation" in prompt:
            # UI-03. 해석 규칙을 받은(준비 단계·종료 Case) 논의 응답이다. 실제 AI 처럼 답 글 끝에 블록을 둔다.
            # 표지는 **사용자의 마지막 메시지**(고정 컨텍스트 뒤의 지시 원문)에서만 읽는다 — 앞선 대화에
            # 남은 표지를 다시 읽으면 설명 질문이 업무 요청이 된다.
            last = prompt.rsplit("--- 고정 컨텍스트 끝 ---", 1)[-1]
            tail = last.split("hads-interpretation")[-1]
            work = re.search(r"HADS_FAKE_WORK=([a-z_]+)", tail)
            # UI-04c(D-86). 업무 단계 규칙을 받은 응답의 목적·유형 변경 표지 — `HADS_FAKE_PROFILE_CHANGE=<profile>`
            # 또는 `<profile>:<obligation,...>`. 규칙을 받지 않았으면 표지가 있어도 붙이지 않는다.
            change = re.search(r"HADS_FAKE_PROFILE_CHANGE=([a-z_]+)(?::([a-z_,]+))?", tail)
            if change and "profile_change" in prompt:
                verdict = {
                    "kind": "profile_change",
                    "profile": change.group(1),
                    "objectives": [o for o in (change.group(2) or "").split(",") if o],
                }
            elif work:
                verdict = {"kind": "work_request", "profile": work.group(1)}
            else:
                verdict = {"kind": "discussion"}
            text += "\n\n```hads-interpretation\n" + json.dumps(verdict) + "\n```"
        if "hads-knowledge" in prompt:
            # P4-06. 등록 규칙을 받은 논의 응답. 표지는 사용자의 마지막 메시지에서만 읽는다.
            last = prompt.rsplit("--- 고정 컨텍스트 끝 ---", 1)[-1]
            items = []
            if "HADS_FAKE_RULE" in last:
                said = " ".join(last.replace("HADS_FAKE_RULE", "").replace("HADS_FAKE_PROPOSAL", "").split())[:300]
                items.append({
                    "kind": "constraint", "obligation": "required", "summary": "대화에서 정한 규칙",
                    "content": said, "repository": None, "paths": [], "activities": [],
                    "supersedes": None,
                })
            if "HADS_FAKE_PROPOSAL" in last:
                # P4-07. AI 제안 — 사용자의 말이 아니다. 후보로만 등록된다.
                items.append({
                    "kind": "operation", "obligation": "reference", "summary": "AI 관찰(제안)",
                    "content": "PROPOSAL-MARK 시험은 저장소 루트에서 python -m pytest 로 돈다.",
                    "basis": "이 대화의 논의", "repository": None, "paths": [], "activities": [],
                    "relates_to": None, "relation": None, "proposal": True,
                })
            if items:
                text += (
                    "\n\n```hads-knowledge\n"
                    + json.dumps({"items": items}, ensure_ascii=False)
                    + "\n```"
                )
    emit(
        {
            "type": "item.completed",
            "item": {"id": "item_2", "type": "agent_message", "text": text},
        }
    )
    emit(
        {
            "type": "turn.completed",
            "usage": {"input_tokens": 11, "cached_input_tokens": 0, "output_tokens": 7},
        }
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
