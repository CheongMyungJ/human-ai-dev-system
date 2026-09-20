# P1-02 Codex·Claude 최소 실행 실증 결과

실행일: 2026-09-20. Plan ID: `P1-PLAN-01` 8~14번 항목. 실행 도구: [`p1/harness/run_cli.py`](../harness/run_cli.py).

**관측 버전:** codex-cli 0.154.0 / Claude Code 2.1.278 / Windows 11 Home 10.0.26200 (ko-KR) / Python 3.12.10.
두 CLI 모두 자동 업데이트가 켜져 있으므로 **이 결과는 위 버전에만 유효하다.**

**시험 대상:** `%LOCALAPPDATA%\Temp\hads-p1\testrepo` — 이 실증을 위해 새로 만든 임시 git 저장소.
사용자의 실제 프로젝트와 이 설계 저장소는 대상으로 쓰지 않았다. 외부 게시·push는 하지 않았다.

**증거 파일:** 같은 디렉터리의 `<run_id>.result.json`(정규화 결과), `<run_id>.stdout.jsonl`(CLI 원문 이벤트),
`<run_id>.stderr.log`. 원문은 바이트 그대로 저장했다.

## 1. 실행 요약

| # | run_id | 도구·권한 | 목적 | 결과 |
|---|---|---|---|---|
| 1 | `codex-read-e5b30cf3` | codex / read_only | 읽기 호출 | **실패** — 인자 오류(2절 A) |
| 2 | `claude-read-8853d2f7` | claude / read_only | 읽기 호출 | **실패** — 인자 오류(2절 B) |
| 3 | `codex-read-v2-347eb670` | codex / read_only | 읽기 호출 | 성공. 함수명 `add, sub` 회신 |
| 4 | `claude-read-v2-5f612ab5` | claude / read_only | 읽기 호출 | 성공 |
| 5 | `codex-write-0ff03346` | codex / workspace_write | 한 줄 추가 | 성공. git diff로 실제 변경 확인 |
| 6 | `claude-write-b9a16f94` | claude / workspace_write | 한 줄 추가 | 성공. git diff로 실제 변경 확인 |
| 7 | `codex-denied-write-26778a61` | codex / read_only | 쓰기 요청 | 변경 없음. **모델이 스스로 거절**(3절) |
| 8 | `codex-sandbox-enforce-84ef2017` | codex / read_only | 쓰기 강제 시도 | 변경 없음. **OS 수준 차단 확인**(3절) |
| 9 | `claude-denied-write-46028b40` | claude / read_only | 쓰기 강제 시도 | 변경 없음. **도구 차단 확인**(3절) |
| 10 | `claude-strictmcp-f5f49199` | claude / read_only | MCP 도구 제거 확인 | MCP 도구 0개(3절) |
| 11 | `pair-author-8765c23c` | codex / workspace_write | 작성: `mul()` 추가 | 성공. 세션 `01a0be64-f99f-…` |
| 12 | `pair-review-9fed6106` | claude / read_only | 검토: 요구 충족 판정 | 성공. 세션 `8816c38e-50d3-…`, 작업공간 변경 없음 |

## 2. 문서만으로는 알 수 없었던 인터페이스 차이

### A. `codex exec`는 `--ask-for-approval`을 받지 않는다

최상위 `codex --help`에는 `-a, --ask-for-approval`이 있지만 `codex exec`에 그대로 넘기면 종료 코드 2로 실패한다.

```
error: unexpected argument '--ask-for-approval' found
```

→ 증거 `codex-read-e5b30cf3.stderr.log`. **최상위 도움말의 옵션을 하위 명령에 옮겨 쓰지 않는다.**
어댑터는 CLI별이 아니라 **CLI + 하위 명령(모드)별로** 인자 집합을 고정해야 한다.

### B. 값이 여러 개인 옵션이 뒤따르는 프롬프트를 삼킨다

`claude -p … --tools Read,Grep,Glob "<프롬프트>"` 는 프롬프트를 `--tools`의 추가 값으로 먹고 실패한다.

```
Error: Input must be provided either through stdin or as a prompt argument when using --print
```

→ 증거 `claude-read-8853d2f7.stderr.log`. 조치: **프롬프트를 인자가 아니라 stdin으로 전달**한다.
두 CLI 모두 stdin 입력을 지원하므로 이를 공통 규칙으로 정했다. Windows 명령줄 길이·인용 문제도 함께 피한다.

두 사례 모두 "도움말에 옵션이 있다"와 "그 조합이 동작한다"가 다르다는 증거다.
`p1-environment-contract.md` 8절의 `doc_only` 상태를 그대로 지원으로 승격시키지 않은 판단이 맞았다.

## 3. 권한 경계 — 프롬프트 거절과 실제 차단을 구분

**Codex read-only, 일반 요청(#7):** 모델이 "현재 환경은 읽기 전용이라 추가할 수 없습니다"라고 답하고
쓰기를 **시도조차 하지 않았다**. 작업공간 변경 없음. 이것만으로는 sandbox가 막았다고 말할 수 없다.

**Codex read-only, 강제 시도(#8):** 같은 권한에서 쓰기 명령을 실제로 실행시켰더니 OS가 막았다.

```
Add-Content: Access to the path 'C:\...\hads-p1\testrepo\NOTES.md' is denied.   (exit_code 1)
```

→ Codex의 Windows read-only sandbox는 이 PC에서 **실제로 강제된다**(모델 순응이 아니라 파일 접근 거부).

**Claude read-only, 강제 시도(#9):** 모델이 Write → Edit → Bash를 차례로 시도했고 CLI가 셋 다 거부했다.

```
Error: No such tool available: Write. Write is disabled for this session, in subagents as well as here.
```

→ `--tools` 제한은 **하위 에이전트까지 포함해** CLI 수준에서 강제된다. 작업공간 변경 없음.

**중요: 도구 제한이 MCP 서버 도구를 포함하지 않는다(#9).** `--tools Read,Grep,Glob`을 줬는데도
초기화 이벤트의 도구 목록에 사용자 설정에서 온 MCP 도구 8개가 남아 있었다. 문서 생성 등 외부 쓰기가
가능한 도구가 시스템 권한 밖에서 살아 있다는 뜻이다. `--strict-mcp-config`를 함께 주면 MCP 도구가
0개가 된다(#10 확인). **어댑터는 read_only·workspace_write 모두에 이 옵션을 포함한다.**

**미해결 불일치:** `--permission-mode manual`을 줬는데 초기화 이벤트의 `permissionMode`는 `default`로
보고된다(#9, #10). 요청값과 보고값이 다르므로 이 값을 통제 근거로 쓰지 않는다. P1-03에서 확인한다.

두 CLI의 권한 축이 다르다는 사실도 확인했다. Codex는 **파일시스템 sandbox**, Claude는 **도구 목록**으로
막는다. 공통 계약은 추상 권한값을 받아 각각 매핑하고, 매핑할 수 없는 조합은 실행을 거부한다.

## 4. 이벤트 스키마 실물

### Codex `exec --json`

```
thread.started   {thread_id}                        → session_identified
turn.started                                         → run_started
item.started     {item.type: command_execution}      → tool_call_started
item.completed   {item.type: command_execution,
                  exit_code, aggregated_output}       → tool_call_finished
item.completed   {item.type: agent_message, text}     → assistant_message
turn.completed   {usage:{input_tokens, output_tokens,
                  cached_input_tokens, …}}            → usage_reported + run_finished
```

### Claude `-p --output-format stream-json --verbose`

```
system/init      {session_id, cwd, tools, model,
                  permissionMode, mcp_servers}        → session_identified
assistant        {message.content[].type == tool_use} → tool_call_started
user             {tool_use_result}                    → tool_call_finished
assistant        {message.content[].type == text}     → assistant_message
system/permission_denied {tool_name,
                  decision_reason_type}               → permission_decided
rate_limit_event {rate_limit_info}                    → usage_reported
result           {usage, total_cost_usd, session_id}  → usage_reported + run_finished
system/thinking_tokens, assistant(thinking)           → 경계 의미 없음(무시)
```

정규화기는 **관측한 필드에서만** 분류하고, 모르는 종류는 `unmapped_native_types`로 남긴다.
현재 두 CLI의 위 흐름에서 `unmapped`는 비어 있다(#3~#6, #9~#12).

**차이:** Codex는 토큰 수만 제공하고 비용은 없다. Claude는 토큰과 `total_cost_usd`를 모두 제공한다.
어댑터는 미제공을 0으로 채우지 않고 `not_reported`로 남긴다.

## 5. 완료 판정 — 종료 코드도 종료 이벤트도 충분하지 않다

#7·#8은 요청한 작업을 하지 못했는데도 `exit_code=0`이고 `turn.completed`가 나왔다.
즉 **CLI의 성공 신호는 "턴이 끝났다"는 뜻이지 "업무가 됐다"는 뜻이 아니다.**

harness는 `outcome`을 종료 코드 단독으로 정하지 않고 (a) 타임아웃 여부 (b) 종료 코드
(c) stdout 증거 유무 (d) 종료 이벤트 관측을 함께 본다. 그래도 #7·#8이 `completed`로 나온다.
따라서 **제어부는 여기에 더해 요구·성공 기준 대조와 작업공간 변화(`workspace_effect`)를 봐야 한다.**
이는 FR-28의 "종료 코드만으로 업무 완료를 선언하지 않는다"가 CLI 이벤트까지 포함해야 한다는 뜻이다.

## 6. 세션 식별과 작성·검토 분리

| 실행 | 도구 | 세션 식별자 |
|---|---|---|
| #11 작성 (`mul()` 추가) | codex | `01a0be64-f99f-7453-bcc6-85741564f1b4` |
| #12 검토 (요구 충족 판정) | claude | `8816c38e-50d3-45c9-810f-424ee6bcf9ab` |

호출마다 새 세션 식별자가 나오며 작성과 검토가 서로 다른 세션이다(#3~#12 전부 서로 다름).
검토 세션은 read_only로 실행되어 작업공간을 바꾸지 않았고(`changed: false`),
작성자의 요약이 아니라 **실제 코드를 읽고** 판정했다.
**세션 재개**(`codex exec resume`, `claude --resume`)는 이번에 시험하지 않았다 — `doc_only` 유지.

## 7. 원문 보존에서 확인한 것

- 두 CLI의 stdout은 모두 **유효한 UTF-8**이다(`stdout_utf8_decode_errors: 0`).
  초기 조사에서 한국어가 깨져 보인 것은 확인용 콘솔의 인코딩(cp949) 때문이었다. CLI의 결함이 아니다.
  → 교훈: **판정은 바이트에서 하고, 표시 인코딩을 근거로 CLI를 판단하지 않는다.**
- 다만 **자식 프로세스 출력은 CLI가 이미 손실 변환한 상태로 전달될 수 있다.**
  #8의 `aggregated_output`에 U+FFFD 4개가 들어 있다(PowerShell 오류 표시 문자).
  Runner는 원문을 바이트로 보존해도 **CLI가 잃은 바이트는 복구할 수 없다.** NFR-09 기록 시 이 한계를 표시한다.
- harness 초기 구현은 텍스트 모드로 읽어 원문을 손상시킬 수 있었다. 바이트 보존으로 고쳤다.
  같은 규칙을 제품 Runner에도 적용한다.

## 8. 이번에 확인하지 않은 것

| 항목 | 상태 | 넘긴 곳 |
|---|---|---|
| 도구 경계 정지(단절 후 다음 호출 차단) | 미검증 | P1-03 |
| 취소·프로세스 종료 확인, 자식·백그라운드 활동 추적 | 미검증 (`residual_activity: unknown`) | P1-03 |
| 재연결 결과 대조·중복 실행 방지 | 미검증 | P1-03 |
| 세션 재개 | 미검증 | P1-03 |
| `--permission-mode` 요청값과 보고값 불일치 | 미해결 | P1-03 |
| `.cmd` 진입점 경유 실행의 프로세스 트리 | 미검증. 현재 PATH의 `codex.CMD`/`claude.CMD`를 그대로 사용 | P1-03 |
| OpenCode | 미설치. 실행 시험 없음 | P1-04(문서 계약만) |
| 대용량 출력·장시간 실행·타임아웃 강제 종료 | 미검증 | P1-03 |
