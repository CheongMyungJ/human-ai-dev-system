"""검증 환경 실험 — 실제 codex 가 어느 조건에서 `python -m unittest` 를 실행할 수 있는가(S-034).

P3-04·P4-05·P4-06·P4-06b·P4-07 라이브에서 실제 codex 의 검증 실행은 셸에서 `python`·`py` 를 찾지
못해(절대 경로 시도도 실패) 기준이 전부 `unverified` 였다(DEVELOPMENT 9절 "검증 실행이 이 호스트에서
시험을 돌리지 못한다"). 이 스크립트는 **제품을 거치지 않고** codex 를 직접 불러 조건별로 관찰한다 —
제품 규칙의 통과가 아니라 환경·CLI 샌드박스의 사실을 적는 실험이다.

조건(같은 임시 저장소·같은 지시):

    A. `--sandbox workspace-write`                              제품이 쓰기 실행에 주는 값 그대로
    B. A + 지시에 인터프리터 **절대 경로**                       지시만으로 풀리는가
    C. A + `-c shell_environment_policy.inherit=all`           환경 변수 상속 정책이 원인인가
    D. `--sandbox danger-full-access`                          샌드박스가 원인인가(대조군)

**제품 코드를 import 하지 않는다.** 실행: `.venv\\Scripts\\python.exe p4\\live\\verify_env.py`
결과: `p4/evidence/P4-ENV-live-results.json`·`P4-ENV-live.log`(회차마다 새로 쓴다).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT = REPO_ROOT / "p4" / "evidence"
LIVE_ROOT = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Temp" / "hads-p4-env-live"
PYTHON312 = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Python" / "Python312" / "python.exe"

PROMPT = (
    "이 저장소에서 시험을 실행하고 결과를 보고해 주세요.\n\n"
    "1. `{command}` 를 저장소 루트에서 실행한다.\n"
    "2. 실행한 명령·종료 코드·출력의 마지막 5줄을 그대로 적는다. 실행하지 못했으면 그 이유(오류 메시지 그대로)를 적는다.\n"
    "3. `python`·`py` 가 셸에서 해석되는지(`where python`, `where py`, `python --version`)도 함께 적는다.\n"
    "4. 파일은 바꾸지 않는다.\n\n"
    "마지막 메시지는 아래 JSON 하나만 적는다(다른 글 없이):\n"
    '{{"command": "...", "exit_code": <정수 또는 null>, "ran": true|false, "python_resolved": "...", '
    '"error": "...", "stdout_tail": "..."}}'
)

VARIANTS: list[dict[str, Any]] = [
    {"key": "A", "label": "workspace-write (제품 기본)", "args": ["--sandbox", "workspace-write"],
     "command": "python -m unittest -v"},
    {"key": "B", "label": "workspace-write + 절대 경로 지시", "args": ["--sandbox", "workspace-write"],
     "command": f'"{PYTHON312}" -m unittest -v'},
    {"key": "C", "label": "workspace-write + shell_environment_policy.inherit=all",
     "args": ["--sandbox", "workspace-write", "-c", "shell_environment_policy.inherit=all"],
     "command": "python -m unittest -v"},
    {"key": "D", "label": "danger-full-access (대조군)", "args": ["--sandbox", "danger-full-access"],
     "command": "python -m unittest -v"},
]


def _codex() -> str:
    exe = shutil.which("codex")
    if exe is None:
        raise SystemExit("codex 를 PATH 에서 찾지 못했다")
    return exe


def _make_repo(root: Path, key: str) -> Path:
    repo = root / f"repo-{key}"
    if repo.exists():
        shutil.rmtree(repo)
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "__init__.py").write_text("", encoding="utf-8")  # 패키지여야 발견된다
    (repo / "app.py").write_text(
        "def error_lines(lines):\n    return [l for l in lines if l.startswith('ERROR')]\n", encoding="utf-8"
    )
    (repo / "tests" / "test_app.py").write_text(
        "import unittest\n\nfrom app import error_lines\n\n\n"
        "class ErrorLines(unittest.TestCase):\n"
        "    def test_only_error_lines(self):\n"
        "        self.assertEqual(error_lines(['ERROR a', 'INFO b']), ['ERROR a'])\n",
        encoding="utf-8",
    )
    (repo / "README.md").write_text("# env probe\n\n시험: `python -m unittest -v`\n", encoding="utf-8")
    return repo


def _run(codex: str, repo: Path, variant: dict[str, Any], log) -> dict[str, Any]:
    last = repo / "last-message.txt"
    raw = repo / "events.jsonl"
    command = [
        codex, "exec", "--json", "--skip-git-repo-check", "-C", str(repo), *variant["args"],
        "-o", str(last), "-",
    ]
    prompt = PROMPT.format(command=variant["command"])
    log(f"[{variant['key']}] {variant['label']}: {' '.join(command[1:])}")
    started = time.monotonic()
    proc = subprocess.run(
        command, input=prompt, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=600, cwd=str(repo),
    )
    elapsed = round(time.monotonic() - started, 1)
    raw.write_text(proc.stdout, encoding="utf-8")
    commands: list[dict[str, Any]] = []
    for line in proc.stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        item = event.get("item") if isinstance(event, dict) else None
        if event.get("type") == "item.completed" and isinstance(item, dict) and item.get("type") == "command_execution":
            commands.append({
                "command": (item.get("command") or "")[:300],
                "exit_code": item.get("exit_code"),
                "output_tail": (item.get("aggregated_output") or "")[-400:],
            })
    final = last.read_text(encoding="utf-8", errors="replace") if last.exists() else ""
    report: Any = None
    text = final.strip()
    if text.startswith("```"):
        text = text.strip("`").split("\n", 1)[-1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    try:
        report = json.loads(text[text.find("{"): text.rfind("}") + 1]) if "{" in text else None
    except ValueError:
        report = None
    pytest_ok = any(
        c["exit_code"] == 0 and "unittest" in c["command"] and ("OK" in c["output_tail"]) for c in commands
    )
    result = {
        "key": variant["key"], "label": variant["label"], "args": variant["args"], "command": variant["command"],
        "codex_exit": proc.returncode, "elapsed_s": elapsed, "commands": commands,
        "unittest_ran_ok_observed": pytest_ok, "final_report": report, "final_message_head": final[:600],
        "stderr_tail": proc.stderr[-800:],
    }
    log(f"[{variant['key']}] codex exit={proc.returncode} · {elapsed}s · 명령 {len(commands)}건 · unittest 통과 관측={pytest_ok}")
    for c in commands:
        log(f"[{variant['key']}]   exit={c['exit_code']} · {c['command'][:140]}")
    log(f"[{variant['key']}] 마지막 메시지: {final[:300].replace(chr(10), ' / ')}")
    return result


def main() -> int:
    tag = time.strftime("%H%M%S")
    root = LIVE_ROOT / tag
    root.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    log_path = OUT / "P4-ENV-live.log"
    lines: list[str] = []

    def log(msg: str) -> None:
        lines.append(msg)
        print(msg, flush=True)
        log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    codex = _codex()
    version = subprocess.run([codex, "--version"], capture_output=True, text=True, encoding="utf-8").stdout.strip()
    log(f"회차 {tag} · {version} · python312={PYTHON312.exists()} · 실험 루트 {root}")
    only = set(sys.argv[1:])  # 예: `verify_env.py A` — 조건 일부만 다시 돌린다
    results = []
    for variant in VARIANTS:
        if only and variant["key"] not in only:
            continue
        repo = _make_repo(root, variant["key"])
        try:
            results.append(_run(codex, repo, variant, log))
        except subprocess.TimeoutExpired:
            log(f"[{variant['key']}] 600초 안에 끝나지 않았다")
            results.append({"key": variant["key"], "label": variant["label"], "timeout": True})
        # 파일 변경 관측(지시: 바꾸지 않는다)
        app = (repo / "app.py").read_text(encoding="utf-8")
        results[-1]["app_py_unchanged"] = "startswith('ERROR')" in app
    summary = {v["key"]: v.get("unittest_ran_ok_observed") for v in results}
    log(f"요약(unittest 통과 관측) {summary}")
    (OUT / "P4-ENV-live-results.json").write_text(
        json.dumps({"tag": tag, "codex_version": version, "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
