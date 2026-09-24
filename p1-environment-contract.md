# P1-01 실행 환경 실측과 공통 어댑터 계약 초안

조사일: 2026-09-20. 대상 PC: 사용자 Windows 개발 PC 1대. Plan ID: `P1-PLAN-01`.

이 문서는 **P1-01(환경·계약)의 결과물**이다. 아래 2~5절은 이 PC에서 실제로 실행한 조회 명령의 결과이며, 6~7절은 그 사실과 공식 문서·CLI 도움말을 근거로 만든 **계약 초안**이다.

8절의 capability 표는 **P1-02·P1-03 실증 결과(2026-09-20)를 반영해 갱신했다.** 실행 증거는
[P1-02 결과](p1/evidence/P1-02-results.md)와 [P1-03 결과](p1/evidence/P1-03-results.md)에 있다.
OpenCode 열만은 실행이 아니라 **문서 근거**이며 [OpenCode 어댑터 계약](p1/opencode/contract.md)에서 왔다.

**아직 하지 않은 것:** 재연결·재개 시험, 병렬 호출 경계, 훅 적용 범위의 공백 확인, OpenCode 설치·실행.
9절에 미검증으로 남겨 둔다.

## 1. 조사 방법과 판정 규칙

| 판정 | 의미 | 이 문서의 표기 |
|---|---|---|
| `설치 확인` | 실행 파일 경로 확인 + 버전 출력 성공 | 경로와 버전을 함께 기록 |
| `PATH 미조회` | 현재 셸의 PATH에서 찾지 못함. 설치 여부는 별도 확인 필요 | 추가 조회 결과와 함께 기록 |
| `설치 흔적 없음(조사 범위 내)` | PATH + 패키지 관리자 + 일반 설치 경로에서 모두 확인되지 않음 | 조사한 범위를 함께 기록. 디스크 전체 검색은 하지 않았으므로 `미설치 확정`으로 쓰지 않는다 |

실행한 조회 명령(PowerShell 7):

```powershell
Get-Command <name> -All            # 실행 파일 경로와 종류
<tool> --version                   # 실제 버전
Get-CimInstance Win32_OperatingSystem
npm ls -g --depth=0                # 전역 npm 패키지
winget list --id sst.opencode
Test-Path <설치 후보 경로>          # 존재 여부만 확인
codex doctor / claude doctor       # 설치·인증·런타임 진단
```

`codex doctor`·`claude doctor`의 원문 출력에는 계정·엔드포인트 정보가 섞여 있어 저장소에는 **판정에 필요한 항목만 요약**해 남긴다. 인증 파일은 존재·크기·수정시각만 확인했고 내용은 열지 않았다.

## 2. 기반 환경 실측

| 항목 | 실측값 | 확인 방법 |
|---|---|---|
| OS | Microsoft Windows 11 Home, 버전 10.0.26200, 빌드 26200, 64비트, 로캘 ko-KR | `Win32_OperatingSystem`, `codex doctor` |
| 셸 | PowerShell 7.6.6 (Windows Terminal). 콘솔 코드 페이지 입·출력 모두 65001 | `$PSVersionTable`, `codex doctor` |
| Python (기본) | 3.12.10 — `C:\Users\USER\AppData\Local\Programs\Python\Python312\python.exe` | `python --version` |
| Python (추가) | 3.14.7 — `...\Python314\python.exe`. `py` 런처 기본값은 **3.14** | `py -0` |
| Git | 2.52.0.windows.1 — `C:\Program Files\Git\cmd\git.exe` | `git --version` |
| Node / npm | v22.15.1 / 10.9.2 — `C:\Program Files\nodejs\` | `node --version`, `npm --version` |
| GitHub CLI | 2.100.0 — `C:\Program Files\GitHub CLI\gh.exe` | `gh --version` |
| 디스크 여유 | 689.4 GiB | `codex doctor` |

**주의 1.** `python`과 `py`의 기본 버전이 다르다(3.12 대 3.14). P2에서 제어부·Runner를 만들 때 실행 스크립트가 어느 인터프리터를 쓰는지 명시하지 않으면 세션마다 다른 런타임이 잡힌다. NFR-08의 재현성 요구에 직접 걸리므로 P2-01에서 사용할 Python 버전을 고정한다. 이 문서는 버전을 선택하지 않는다.

**주의 2.** 위 값은 **이 PC 1대의 관측**이다. NFR-08이 정한 우선 호환 환경(Windows 11 Home 10.0.26200)과 일치하지만, 이를 최소 지원 버전이나 다른 Windows 호환 보장으로 확대하지 않는다.

## 3. 코딩 CLI 실측

| CLI | 상태 | 버전 | 실행 경로 | 설치 방식 |
|---|---|---|---|---|
| Codex | 설치 확인 | `codex-cli 0.154.0` | PATH 진입점 `C:\Users\USER\AppData\Roaming\npm\codex.cmd` → 실제 `...\node_modules\@openai\codex\node_modules\@openai\codex-win32-x64\vendor\x86_64-pc-windows-msvc\bin\codex.exe` | 전역 npm `@openai/codex@0.154.0` |
| Claude Code | 설치 확인 | `2.1.278 (Claude Code)`, commit 809c980662e3, win32-x64 | PATH 진입점 `C:\Users\USER\AppData\Roaming\npm\claude.cmd` → `...\node_modules\@anthropic-ai\claude-code\bin\claude.exe` | 전역 npm `@anthropic-ai/claude-code@2.1.278` |
| OpenCode | 설치 흔적 없음(조사 범위 내) | — | — | — |

OpenCode 조사 범위: PATH(`Get-Command opencode`), 전역 npm 목록, `winget list --id sst.opencode`, scoop·chocolatey 디렉터리, `%LOCALAPPDATA%\Programs`, `%APPDATA%\npm`, `%LOCALAPPDATA%\Microsoft\WinGet\Packages`, `~\.opencode`, `~\.config\opencode`. 모두 없음. 디스크 전체 검색은 하지 않았다. 이는 사전에 합의한 제한(P1 범위에서 OpenCode 설치 제외)과 일치하며, OpenCode는 P1-04에서 **문서 계약만** 다룬다.

두 CLI 모두 **자동 업데이트가 켜져 있다**. Codex는 0.155.1이 이미 배포됐고 Claude Code는 최근 자동 업데이트 성공 기록(2026-09-19)이 있다. 어댑터 계약과 실증 결과에는 반드시 **관측한 버전 문자열**을 함께 남겨야 하며, 버전이 바뀐 뒤의 실증 결과를 이전 버전의 검증으로 재사용하지 않는다.

## 4. 인증과 비밀값 취급

| 항목 | 관측 | 근거 |
|---|---|---|
| Codex 인증 | 구성됨. 저장 방식 `File`, 모드 `chatgpt`, 저장된 API 키 없음, ChatGPT 토큰 있음. 파일 `~\.codex\auth.json` 존재 | `codex doctor`(요약 항목), `Test-Path` |
| Codex 연결 | 활성 공급자 엔드포인트 도달 가능. websocket 핸드셰이크 HTTP 101 성공 | `codex doctor` |
| Claude 인증 | `~\.claude\.credentials.json` 존재(523바이트, 2026-09-20). `claude doctor`는 설치 문제 없음으로 보고 | `Test-Path`, `claude doctor` |
| OpenCode 인증 | 해당 없음(미설치) | — |

**계약상 결론:** 두 CLI 모두 **자격증명을 각자의 사용자 홈 저장소에 보관**하므로, 이 시스템은 실행 시 비밀값을 읽거나 주입하지 않고 CLI를 그대로 호출하면 된다. 이는 FR-28·NFR-07의 "로그인은 Runner에 유지", "외부 AI 전송은 기존 CLI 설정을 따른다"와 맞는다. 어댑터는 자격증명 파일을 읽지 않고, 인증 실패는 CLI가 반환한 오류로만 판정한다.

다만 **인증 파일이 있다는 사실이 호출 성공을 보장하지 않는다.** 토큰 만료·요금제 한도·조직 정책은 실제 호출에서만 드러난다. 따라서 이 절은 "인증 구성됨"까지만 확정하고, "사용 가능"은 P1-02의 실행 증거로 판정한다.

## 5. 관측한 권한·격리 차이

| CLI | 관측값 | 해석 |
|---|---|---|
| Codex | `codex doctor` 기준 sandbox = 제한된 파일시스템 + 제한된 네트워크, 승인 정책 `OnRequest`, sandbox backend `elevated`, provisioning complete | Windows 네이티브에서 sandbox 기능이 구성되어 있다고 **진단 도구가 보고**한다. 실제 차단 동작은 확인하지 않았다 |
| Claude Code | `claude doctor`에 sandbox 항목 없음. 기존 조사(`review-tech-findings.md`)는 Windows 네이티브 내장 sandbox 미지원·WSL2 지원으로 기록 | Windows 네이티브 공통 모드에서 두 CLI의 OS 격리 수준을 같다고 표시할 수 없다 |
| 공통 | Codex는 `--sandbox {read-only, workspace-write, danger-full-access}`, Claude는 `--permission-mode`·`--allowedTools`·`--tools`·`--restricted`로 권한을 표현 | 권한 모델의 **축이 다르다**. 공통 계약은 요구 권한을 추상 값으로 받고 CLI별로 매핑하되, 매핑할 수 없는 조합은 미지원으로 표시한다 |

Codex 진단의 sandbox 보고는 **설정값**이며 실제 쓰기 차단·네트워크 차단 관찰이 아니다. P1-02에서 허용 밖 경로 쓰기를 시도해 실제 결과를 확인하기 전까지 "격리 확인됨"으로 쓰지 않는다. 어느 쪽도 D-42·44가 전제한 신뢰 모드의 한계를 넘는 OS 완전 격리로 설명하지 않는다.

## 6. 공통 실행 계약 초안 v0 — 입력(RunRequest)

CLI별 인자 형태가 아니라 **제어부가 표현해야 할 의미**를 정의한다. NFR-07에 따라 업무 상태를 특정 CLI의 세션·출력 형식·ID 체계에 종속시키지 않는다.

| 필드 | 의미 | 필수 | 비고 |
|---|---|---|---|
| `run_id` | 시스템이 만드는 실행 식별자. 재전송 멱등 키 | 필수 | 같은 `run_id` 재전달은 새 실행을 만들지 않는다 |
| `case_id` / `task_id` / `role` | 업무 연결과 역할(작성·의미 검토). 검토는 작성과 별도 세션 | 필수 | FR-29의 별도 세션 요구 |
| `assignment_generation` | 배정 세대 번호(fencing) | 필수 | 오래된 실행자의 갱신 거부용 |
| `tool_id` / `tool_version_expected` | `codex` / `claude` / `opencode`와 기대 버전 | 필수 | 실제 관측 버전과 불일치하면 결과에 표시 |
| `mode` | 실행 모드 식별자(예: Codex `exec`, Claude `print`) | 필수 | 모드마다 능력표가 다르다 |
| `model` | 프로젝트 기본의 Case·역할별 override | 선택 | 미지정이면 CLI 설정을 따른다 |
| `workspace` | `repo_path`, `worktree_path`, `branch`, `base_commit` | 필수 | 서버 프로젝트 ID와 Runner 실제 경로를 구분 |
| `permission` | 추상 권한: `read_only` / `workspace_write` / `explicit_escalated` | 필수 | CLI별 매핑은 `runner/cli_adapter.py` `PERMISSION_MAP`. 매핑 불가는 실행 거부. **D-91(2026-09-24, P4-09):** `read_only` 만 CLI 샌드박스(codex `--sandbox read-only`, claude `manual` + `--tools Read,Grep,Glob`)를 유지하고 `workspace_write` 는 **CLI 권한 제약이 없다**(codex `--sandbox danger-full-access`, claude `bypassPermissions`; `--strict-mcp-config` 는 남긴다) — 쓰기 실행은 사용자 계정 권한으로 돌아 worktree 밖·자격증명에 닿을 수 있고 AI 의 직접 push 를 막지 못한다(사용자가 받아들인 손실). 게시 규칙(P5)은 그대로다 |
| `writable_paths` | 추가 쓰기 허용 경로 | 선택 | 워크스페이스 밖 경로는 기본 불허 |
| `instruction_ref` | 입력 원문의 영속 참조(ID·버전·해시) | 필수 | 원문 자체는 PC 보관. 서버에는 참조만 |
| `context_refs` | 함께 전달한 자료의 ID·버전 목록 | 필수(빈 목록 허용) | NFR-09의 출처 추적 |
| `output_schema` | 구조화 결과 스키마 | 선택 | 지원 CLI에서만 적용 |
| `session` | `new` 또는 `resume(session_ref)` | 필수 | 재개 미지원 CLI·모드는 `new`만 허용 |
| `limits` | 시간·비용 등 상한 | 선택 | 총 자동 실행 시간의 기본 한도는 두지 않는다(D 기준 유지) |
| `secrets` | **없음** | — | 시스템은 CLI 자격증명을 읽지도 주입하지도 않는다 |

## 7. 공통 실행 계약 초안 v0 — 이벤트와 결과

### 7.1 정규화 이벤트

모든 이벤트는 `run_id`, 단조 증가 `seq`, `ts`, `native_type`(CLI 원래 이벤트 이름), `raw_ref`(원문 저장 위치)를 갖는다. 정규화 종류는 최소한 아래를 둔다.

`run_started` · `session_identified` · `assistant_message` · `tool_call_started` · `tool_call_finished` · `permission_requested` · `permission_decided` · `usage_reported` · `error` · `run_finished`

CLI가 어떤 종류를 제공하지 않으면 **비어 있는 것으로 두고 추정으로 채우지 않는다.** 예를 들어 `tool_call_started`를 관측할 수 없는 모드는 8절 능력표에서 `tool_boundary_observed = unsupported`가 되고, 그 모드에는 도구 경계 정지 기능을 배정하지 않는다.

이벤트는 Runner 로컬에 먼저 보존한 뒤 전송한다(`execution-workspace-review.md` 3절). 재접속 시 `run_id + seq`로 중복·누락을 대조한다.

### 7.2 결과(RunResult)

| 필드 | 값 | 규칙 |
|---|---|---|
| `outcome` | `completed` / `failed` / `cancelled` / `unknown` | **종료 코드만으로 `completed`를 쓰지 않는다**(FR-28). `unknown`은 정상 상태값이며 실패로도 성공으로도 바꾸지 않는다 |
| `exit_code` | 정수 또는 없음 | 참고 정보 |
| `final_output` | 최종 메시지 / 구조화 결과 | 원문 참조와 함께 보존 |
| `session_ref` | CLI가 준 세션·스레드 식별자 | 재개 가능 여부와 함께 기록 |
| `usage` | 제공값 또는 `not_reported` | **미제공을 0으로 표시하지 않는다**(P6-05 기준) |
| `workspace_effect` | 실행 전후 HEAD·인덱스·미커밋 변경 비교 결과 | 실행 전후 스냅샷으로 산출 |
| `residual_activity` | 남은 자식 프로세스·백그라운드 활동 | 확인 불가면 `unknown` |
| `observed_tool_version` | 실행 시점 CLI 버전 | 능력표 적용 근거 |

`outcome`은 제어부가 **이벤트·결과물·작업공간 변화**를 함께 보고 판정한다. 이 판정 규칙 자체가 P1-02의 검증 대상이다.

## 8. Capability 표 (P1-02 실증 반영, 2026-09-20)

상태값: `doc_only`(공식 문서·CLI 도움말에 인터페이스 존재, 실행 미확인) · `verified`(이 PC에서 실제 관측) · `unsupported`(없음을 확인) · `unknown`(확인 안 함).

`verified` 항목의 근거는 [P1-02 실증 결과](p1/evidence/P1-02-results.md)와 같은 디렉터리의 실행 증거 파일이다.

| 능력 | Codex 0.154.0 | Claude Code 2.1.278 | OpenCode | 근거 |
|---|---|---|---|---|
| 설치·기동 | `verified` | `verified` | `unsupported`(미설치) | 3절 |
| 인증 구성 | `verified` | `verified` | — | 4절 |
| 비대화식 실행 | `verified` — `codex exec`, 프롬프트는 stdin | `verified` — `claude -p`, 프롬프트는 stdin | `doc_only` — 서버 API `POST /api/session/{id}/prompt`. `opencode run` 은 플래그 부족으로 부적합 | P1-02 #3~#6, [OpenCode 계약 2절](p1/opencode/contract.md) |
| 구조화 이벤트 스트림 | `verified` — `--json` JSONL | `verified` — `--output-format stream-json --verbose` | `doc_only` — `GET /api/event`. **스트림이 휘발성이며 단절 중 이벤트는 유실된다** | P1-02 4절, OpenCode 계약 4.1절 |
| 도구 경계 관찰 | `verified` — `item.started/completed` + `command_execution` | `verified` — `assistant(tool_use)` ↔ `user(tool_use_result)` | `doc_only`(부분) — `shell.started`/`shell.ended` 만 이름 확인 | P1-02 4절, OpenCode 계약 4절 |
| 실제 코드 변경 | `verified` — git diff로 확인 | `verified` — git diff로 확인 | `unknown` — 실행한 적 없음 | P1-02 #5·#6·#11 |
| 쓰기 범위 제한(실강제) | `verified` — read-only sandbox가 OS 수준에서 차단 | `verified` — `--tools` 제한이 하위 에이전트까지 강제 | `doc_only` — `permissions` 의 action×resource 규칙 | P1-02 3절, OpenCode 계약 3절 |
| 쓰기 실행의 샌드박스 | `unsupported` — **D-91(2026-09-24)** 로 `danger-full-access`. 능력 보고 `write_sandbox = unsupported` | `unsupported` — `bypassPermissions`(Windows 에 OS 샌드박스 없음) | `unknown` | 이슈 #3 · [P4-ENV 결과](p4/evidence/P4-ENV-results.md) · decisions.md D-91 |
| 도구 제한의 MCP 포함 여부 | 해당 없음(sandbox 축) | `verified` — **`--tools`는 MCP 도구를 줄이지 않는다.** `--strict-mcp-config` 필요 | `unknown` | P1-02 #9·#10 |
| 권한 거절 이벤트 | `unknown` — 이번 경로에서는 명령 실패로만 드러남 | `verified` — `system/permission_denied` | `unknown` | P1-02 3~4절 |
| 세션 식별 | `verified` — `thread.started.thread_id` | `verified` — `system/init.session_id` | `doc_only` — 세션 생성 응답의 `id` | P1-02 6절, OpenCode 계약 3절 |
| 작성·검토 세션 분리 | `verified` | `verified` | `unknown` | P1-02 #11·#12 |
| 사용량 제공 | `verified` — 토큰만. 비용 없음 | `verified` — 토큰 + `total_cost_usd` | **공백** — 제공 수단을 문서에서 찾지 못함. `not_reported` 로 남긴다 | P1-02 4절, OpenCode 계약 7절 |
| 작업 디렉터리 고정 | `verified` — `-C` + 프로세스 cwd | `verified` — 프로세스 cwd (`system/init.cwd`로 확인) | `unknown` | P1-02 #3·#4 |
| 최종 결과 분리 수집 | `doc_only` — `-o/--output-last-message` | `doc_only` — `--output-format json` | `unknown` | `--help` |
| 구조화 출력 스키마 | `doc_only` — `--output-schema <FILE>` | `doc_only` — `--json-schema <schema>` | `unknown` | `--help` |
| 세션 재개 | `doc_only` — `codex exec resume`, `fork` | `doc_only` — `--resume`, `--session-id`, `--fork-session` | `doc_only` — 같은 `sessionID` 로 prompt 재전송 | `--help`, OpenCode 계약 3절 |
| 승인 요청 노출 | `doc_only` — 최상위 `codex`에만 `--ask-for-approval`. **`exec`는 거부** | `doc_only` — `--permission-prompts host` | `unknown` | P1-02 2절 |
| **다음 호출 차단** | `verified` — 저장소 로컬 `.codex/hooks.json`의 PreToolUse. **단 `--dangerously-bypass-hook-trust` 필요** | `verified` — `--settings`의 PreToolUse | `unknown` — permission `ask` 와 plugin evaluate 훅이 후보. **지원 보류** | [P1-03 1절](p1/evidence/P1-03-results.md), OpenCode 계약 6절 |
| 훅 실패 시 동작 | `unknown` — 이번 경로에서는 훅 미발화가 곧 무통제였다 | `verified` — **fail-open.** 훅이 exit 127로 실패해도 호출이 진행됨 | `unknown` | P1-03 2절 C |
| 훅 거부의 이벤트 노출 | `unsupported` — 거부를 알리는 이벤트가 없다. 훅 로그가 정본 | `verified` — `system/hook_response`(+ `tool_result` 오류) | `unknown` | P1-03 5절 |
| 호출 요청과 실행의 구분 | `verified` — 거부 시 `command_execution` 항목이 생기지 않음 | `verified` — `tool_use`는 요청일 뿐 실행이 아님 | `unknown` | P1-03 5절 |
| 훅 입력의 호출 식별자 | `verified` — `tool_use_id`, `session_id`, `turn_id` | `verified` — `tool_use_id`, `session_id`, `prompt_id` | `unknown` | P1-03 4절 |
| 취소·종료 확인 | `unsupported`(현재 실행 방식) — 진입점 종료 후 `codex.exe`·command-runner·자식 셸이 잔류 | `doc_only` — `claude stop <id>`(백그라운드 세션) | `unknown` | P1-03 3절 |
| 자식·병렬 활동 추적 | `unknown` | `unknown` | `doc_only` — `GET /api/shell`, `GET /api/shell/{id}`. **세 도구 중 유일하게 조회 수단이 문서에 있다** | OpenCode 계약 5절 |
| 재연결 결과 대조 | `unknown` | `unknown` | `doc_only` — `GET /api/session/{id}/log` 의 시퀀스를 정본으로. 이벤트 스트림은 정본이 아님 | OpenCode 계약 4.1절 |

**`doc_only`는 "지원함"이 아니다.** P1-02에서 실제로 두 건이 뒤집혔다: 최상위 도움말의 `--ask-for-approval`은
`codex exec`에서 거부되고, `--tools` 뒤의 위치 인자는 옵션 값으로 흡수된다([P1-02 결과 2절](p1/evidence/P1-02-results.md)).

**다음 호출 차단**은 P1의 핵심 요구이며 P1-03에서 두 CLI 모두 `verified`가 되었다. 다만 조건부다.

- Codex는 훅 명령에 따옴표가 들어가면 **오류 없이 실행되지 않는다.** 설정했다는 것과 돌았다는 것이 다르다
- Codex 비대화식에서는 `--dangerously-bypass-hook-trust`가 필요했다. 제품이 이 플래그에 의존해선 안 된다
- Claude는 **훅이 실패하면 호출을 그대로 진행한다(fail-open).** 훅 실행 성공 여부를 확인하지 않은 실행은
  안전 경계가 성립한 것으로 보지 않는다
- **강제 종료는 안전 중지가 아니다.** 진입점을 종료해도 CLI와 자식 셸이 살아남는다

자세한 근거와 남은 공백은 [P1-03 결과](p1/evidence/P1-03-results.md)에 있다.

**P2-03 추가 (2026-09-20):** 이 표가 이제 **제품의 capability 근거**다.
`runner/cli_adapter.py` 의 `capabilities_for()` 가 기동 시점에 설치 여부를 직접 확인하고
(`installed`), 나머지 능력은 이 표의 실측값을 근거 위치와 함께 제어부에 보고한다.
제어부의 진입 검사는 그 보고를 보고 판단하므로 **아무 것도 보고하지 않은 도구에는 실행을
배정하지 않는다**(`tool_not_available`). P2-03 라이브에서 관측한 버전은 codex-cli 0.154.0,
Claude Code 2.1.278 로 P1-02와 같았고 표의 값을 바꿀 새 관측은 없었다. 다만 두 CLI 모두
자동 업데이트가 켜져 있으므로 이 표는 **관측 시점의 사실**이며 실행마다 버전을 다시 기록한다.

**OpenCode 열은 실행 결과가 아니다.** 설치하지 않았으므로 `verified` 가 하나도 없다.
`doc_only` 는 공식 V2 문서에서 인터페이스를 확인했다는 뜻이며, 근거와 공백은
[OpenCode 어댑터 계약](p1/opencode/contract.md)에 있다. 핵심 요구인 다음 호출 차단은
후보만 있고 `unknown` 이므로 **OpenCode에 안전 중지가 필요한 작업을 배정하지 않는다.**

## 9. 남은 미검증 항목

P1-02에서 해소한 항목(실제 호출·이벤트 스키마·세션 분리·권한 경계 실동작)과 P1-03에서 해소한 항목
(다음 호출 차단, 강제 종료의 프로세스 잔류)은 각 결과 문서로 옮겼다. 아래는 아직 남은 것이다.

| 항목 | 넘긴 하위 작업 | 확인해야 할 것 |
|---|---|---|
| 재연결·재개와 결과 대조 | P1-03 잔여 또는 P2 | 회복 경로에서 이미 한 작업을 다시 하지 않는지 |
| 병렬 도구 호출에서의 경계 | P1-03 잔여 | 순차 실행을 프롬프트로 요구하지 않은 경우의 차단 범위 |
| 훅 적용 범위의 공백 | P1-03 잔여 | 자동 허용·MCP·하위 에이전트 경로가 PreToolUse를 거치는지 |
| 훅 timeout 초과 시 동작 | P1-03 잔여 | Claude의 fail-open이 timeout에도 적용되는지 |
| 프로세스 트리 단위 종료 | P2 | job object 등으로 자식까지 끝내고 종료를 확인하는 방법 |
| 훅 신뢰의 영속화 | P2 | `--dangerously-bypass-hook-trust` 없이 훅을 돌리는 방법 |
| `--permission-mode` 요청값·보고값 불일치 | 부분 해소 | `acceptEdits`는 그대로 보고됨. `manual`만 `default`로 보고된다 |
| Python 런타임 고정 | P2-01 | 3.12 / 3.14 중 사용할 버전과 실행 스크립트 반영 |
| OpenCode | P1-04 | 공식 문서 계약·fixture·계약 시험만. 설치·실행으로 표시하지 않음 |
| CLI 버전 변동 | 상시 | 자동 업데이트로 버전이 바뀌면 해당 실증의 유효 범위를 다시 표시 |
