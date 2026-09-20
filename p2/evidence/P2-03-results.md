# P2-03 진입 제어·제한 실행 — 실행 결과

수행일: 2026-09-20. 계획: [`P2-PLAN-03`](../../plans/P2-PLAN-03.md).

이 문서는 **실제로 실행한 것만** 적는다. 자동 시험(가짜 실행기)과 실제 코딩 CLI 실행을
구분하고, 검증하지 않은 항목은 7절에 미검증으로 남긴다.

## 1. 실행 환경

| 항목 | 값 | 확인 방법 |
|---|---|---|
| OS | Windows 11 Home 10.0.26200 | P2-02와 동일 |
| 셸 | PowerShell 7 | 〃 |
| Python(고정) | 3.12.10 — 저장소 로컬 `.venv` | `.venv\Scripts\python.exe --version` |
| Node / npm | v22.15.1 / 10.9.2 | `npm run build` 출력 |
| 제어부 스키마 | **v3** | `GET /api/health` |
| Codex CLI | (아래 4절의 관측 버전) | Runner 기동 시 `codex --version` |
| Claude Code | (아래 4절의 관측 버전) | Runner 기동 시 `claude --version` |
| OpenCode | **없음** | `Get-Command opencode` 실패 (P1-04와 같음) |

두 CLI 모두 자동 업데이트가 켜져 있어 실행 시점의 관측 버전을 결과와 함께 남긴다.
시스템은 두 CLI의 **자격증명을 읽지도 주입하지도 않았다.** 로그인은 각 CLI 자신의 설정에 있다.

라이브 실행 데이터는 `%LOCALAPPDATA%\Temp\hads-p2-03-live` 에 두어 저장소 `var\` 를
건드리지 않았다. 작업공간도 같은 곳의 별도 임시 저장소이며 이 저장소를 CLI에 노출하지 않았다.

## 2. 만든 것

| 구성 | 파일 | 역할 |
|---|---|---|
| QG-01 게이트 | `controller/gate.py` (신규) | 규칙 검사, AI 발견 정규화, 판정 결합 |
| FR-29 진입 검사 | `controller/admission.py` (신규) | 목적별 조건표, 거부 사유 판정 |
| 상태값 | `domain/models.py` | `RunPurpose` `AdmissionRefusal` `GateVerdict` `AuthoringMode` 등 |
| 스키마 v3 | `controller/schema.sql`, `db.py` | `gate_result` `gate_finding` `admission_check` + `run.purpose` + `intent_version.authoring_mode/author_run_id` |
| 제어부 | `repository.py`, `api.py` | 게이트 판정·재검토 전이, 진입 검사 기록, Runner 작성 경로 |
| CLI 어댑터 | `runner/cli_adapter.py` `cli_events.py` (신규) | 명령 구성·권한 매핑·실행·정규화·판정·능력 보고 |
| 지시문 | `runner/prompts.py` (신규) | 목적별 지시문과 응답 해석. **Runner에만 있다** |
| Runner | `runner/agent.py` | 목적별 실행과 산출물 생성 |
| 화면 | `web/src/App.tsx`, `IntentPanel.tsx`, `api.ts`, `styles.css` | 게이트 판정·발견, 진입 거부 사유, AI 초안 요청 |
| 시험 | `tests/test_gate.py` `test_admission.py` `test_ai_draft.py` (신규) 외 5개 파일 | 39 → **77건** |

### 누가 무엇을 하는가

```
사람 ──요청 원문──▶ 제어부(중계) ──▶ Runner ──코딩 CLI(read_only)──▶ 여섯 항목 초안
                                       │                              (Runner에 저장)
                                       └── 참조·항목 구조만 ──▶ 제어부

Runner ──**다른 세션**의 CLI──▶ QG-01 의미 검토 ──발견 요약만──▶ 제어부(판정 재계산)

브라우저 ──실행 요청──▶ 제어부: 진입 조건 검사 ──거부 사유──▶ 브라우저
                                   │ 통과
                                   ▼
                              Run 생성·배정
```

**지시문은 제어부에 없다.** 목적별 지시문을 제어부에 두면 본문이 제어부를 지나간다.
제어부는 목적과 원문 참조만 내려보내고 Runner가 둘을 합친다
(`tests/test_data_boundary.py::test_the_controller_stores_no_prompt_text`).

## 3. 자동 시험

```
scripts
un-tests.ps1
  제품 시험 (pytest)                       77 passed
  P1 OpenCode 문서 계약 시험 (unittest)     Ran 18, OK
web> npm run build                          tsc -b 통과, vite 빌드 성공
```

| 파일 | 건수 | 보는 것 |
|---|---|---|
| `tests/test_admission.py` | 18 | **신규.** FR-29 진입 조건 검사와 우회 차단 |
| `tests/test_gate.py` | 11 | **신규.** QG-01 규칙·AI 검토·판정 결합·재검토 전이 |
| `tests/test_ai_draft.py` | 5 | **신규.** AI 작성 경로와 작성 주체 기록 |
| `tests/test_data_boundary.py` | 11 | 게이트 검토 본문·지시문의 저장 경계 3건 추가 |
| `tests/test_intent.py` | 14 | P2-02 그대로 |
| `tests/test_flow.py` | 6 | 능력 보고 시험을 도구별로 바꿈 |
| `tests/test_idempotency.py` | 6 | P2-01 그대로 (Case 유형만 조사로) |
| `tests/test_restart_recovery.py` | 4 | 〃 |
| `tests/test_migration.py` | 2 | v2 → v3 마이그레이션 1건 추가 |

**자동 시험은 실제 CLI를 부르지 않는다.** `tests/conftest.py` 의 `FakeCliExecutor` 가
`runner.cli_adapter.CliExecutor` 와 같은 계약으로 응답한다. 시험이 결정적이어야 하고
사용자 계정의 외부 AI 호출에 의존해서는 안 되기 때문이다. 실제 CLI 증거는 아래 4~6절이다.

**기존 시험 중 6건의 Case 유형을 `feature` → `analysis` 로 바꿨다.** 그 시험들이 보는
것은 실행 배관·멱등성·복원이지 기능 개발의 진입 조건이 아니다. 기능 Case는 이제 의도
동의와 QG-01 통과를 요구하므로(FR-29), 배관 시험에 그 조건을 끼워 넣으면 무엇이 깨졌는지
알기 어려워진다. 기능 Case의 조건은 `test_admission.py` 가 따로 본다. 기준을 완화한 것이
아니라 **검사 대상을 분리**한 것이다.

## 4. 실제 코딩 CLI 실행 (라이브)

실제 프로세스로 제어부(uvicorn, 127.0.0.1:8767)와 Runner를 띄우고 **진짜 codex·claude 를**
불렀다. 작업공간은 저장소 밖의 임시 git 저장소(`app.log` 4줄 · `README.md`)이며 이
설계 저장소를 CLI에 노출하지 않았다. 전체 기록은 [P2-03-live-run.log](P2-03-live-run.log).

| 실행 | 목적 | 도구·관측 버전 | 결과 | 세션 식별자 | 사용량 |
|---|---|---|---|---|---|
| `live-draft-1` | intent_authoring | codex-cli 0.154.0 | completed (94초) | `01a0bef1-…754f` | 토큰만 (비용 없음) |
| `live-review-1` | intent_gate_review | 2.1.278 (Claude Code) | completed (35초) | `b344d179-…6bbd` | 토큰 + $0.117206 |
| `live-draft-2` | intent_authoring | codex-cli 0.154.0 | completed (50초) | `01a0bef4-…5448` | 토큰만 |
| `live-review-2` | intent_gate_review | 2.1.278 (Claude Code) | completed (37초) | `aab140ca-…7ce0` | 토큰 + $0.099949 |
| `live-review-3` | intent_gate_review | 2.1.278 (Claude Code) | completed (27초) | `03b0528d-…f466` | 토큰 + $0.086862 |
| `live-work-1` | limited_analysis | codex-cli 0.154.0 | completed (27초) | `01a0bef8-…0ae86` | 토큰만 |

전부 `permission=read_only` 로 배정됐다. 이 단계에서 쓰기 권한은 진입 검사가 거부한다.

**종료 코드만으로 완료를 선언하지 않았다.** `live-work-1` 은 `exit_code=0` 이면서
정규화 이벤트에 `run_finished` 가 있고 최종 메시지가 실제로 만들어졌기 때문에
`completed` 다. 판정 규칙은 `runner/cli_adapter.py` 의 `CliExecutor._judge`.

정규화 이벤트(`live-work-1`, 12건, **unmapped 0건**):
`run_started` `session_identified` `tool_call_started` `tool_call_finished`
`assistant_message` `usage_reported` `run_finished`
— 원문 스트림은 [P2-03-codex-work-stream.jsonl](P2-03-codex-work-stream.jsonl).

**읽기 권한이 실제로 지켜졌다.** 실행 전후 작업공간 `HEAD` 가 `12e33311` 로 같고
미커밋 변경이 0 → 0 이었다. 결과 원문은 [P2-03-work-output.txt](P2-03-work-output.txt):

> app.log에서 대문자 `ERROR`로 시작하는 줄은 **2개**입니다. 파일을 만들거나 수정하지 않았습니다.

작업공간의 실제 ERROR 줄도 2개다.

**사용량을 지어내지 않았다.** codex 는 토큰만 주므로 `cost_usd` 가 `not_reported` 이고
claude 는 토큰과 비용을 모두 준다. 0으로 채우지 않았다.

**`residual_activity` 는 전부 `unknown` 이다.** 자식 프로세스가 남았는지 확인할 수단을
아직 만들지 않았다. 확인하지 않은 것을 "없음"으로 적지 않는다(P1-03의 남은 항목).

### capability 보고 ([P2-03-capabilities.json](P2-03-capabilities.json))

| 도구 | `installed` | `permission:read_only` | `permission:explicit_escalated` |
|---|---|---|---|
| codex | `verified` (기동 시 `codex --version`) | `verified` (근거: P1-02) | `unsupported` (이 어댑터에 매핑 없음) |
| claude | `verified` | `verified` (근거: P1-02) | `unsupported` |
| opencode | **보고되지 않음** — 미설치 | — | — |

`verified` 는 실측 근거가 있는 것만이고 `source` 에 근거 위치가 들어간다.
OpenCode 는 어댑터가 없어 아무 능력도 보고하지 않으며, 그 도구를 요청하면
`tool_not_available` 로 거부된다.

## 5. QG-01 게이트 — **실제로 실패했다**

이 절이 이번 단계에서 가장 중요한 결과다. 게이트는 도장 찍는 절차가 아니었다.

| 버전 | 작성 | 규칙 | AI 의미 검토(별도 세션) | 종합 | 근거 |
|---|---|---|---|---|---|
| v1 | codex | pass | **fail** — 확정 위반 2건 | **fail** | [gate-v1](P2-03-gate-v1.json) |
| v2 | codex (피드백 반영) | pass | **fail** — 확정 위반 2건, 의심 3건 | **fail** | [gate-v2](P2-03-gate-v2.json) |
| v3 | **사람** | pass | pass — 발견 0건 | **pass** | [gate-v3](P2-03-gate-v3.json) |

v1에서 Claude가 찾은 것(요약):

- `request_missing_or_contradictory` (필수·확정): goal/scope 는 기능을 만들라고 하는데
  constraints 는 코드 수정 금지라고 적혀 있어 서로 모순이다
- `important_open_question_unlisted` (필수·확정): 언어·실행 방식을 사람이 정해야 하는데
  질문 목록에 없다

v2에서 찾은 것 중 일부:

- `unverifiable_success_criteria` (필수·확정): 기대 결과가 "의도 초안이 정리된다"로
  순환적이어서 확인할 방법이 없다
- `assumption_presented_as_requirement` (필수·**의심**): goal에 없는 조건이
  `origin=user_requirement` 로 확정 기재됐다 — 의심 단계라 **차단하지 않고 판단 보류**로 갔다

**의심을 확정 실패로 과장하지 않았다.** v2의 판정은 확정 위반 2건 때문에 `fail` 이고,
의심 3건은 기록되되 `blocking=0` 이다. 또 AI가 목록 밖 기준(`other`)으로 올린 지적은
`required` 로 요청했더라도 **권고로 내려갔다**(quality-gates 3절).

**별도 세션이 기록으로 증명된다.** v1의 작성 세션은 `01a0bef1-…754f`(codex),
검토 세션은 `b344d179-…6bbd`(claude)로 서로 다르고 도구도 다르다. v3은 사람이 썼으므로
작성 실행이 없어 `author_session_ref` 가 `null` 이다 — "같은 세션인가"를 물을 대상이 없다.

**새 버전은 이전 판정을 승계하지 않았다.** v2가 생긴 순간 v1의 판정이 `needs_recheck`
가 되고 `superseded_at` 이 찍혔으며, v2의 게이트는 `not_run` 에서 다시 시작했다.
v3이 생기자 v2도 같은 전이를 거쳤다. 세 판정이 모두 보존돼 있다.

**AI가 쓴 초안이 두 번 연속 게이트에 걸렸다는 사실 자체가 결과다.** 여섯 항목이
채워졌다는 것과 그 내용이 검토를 요청할 만하다는 것은 다르고, 이 차이를 잡아내는 것이
QG-01의 목적이다. 통과한 v3은 사람이 그 지적을 반영해 직접 쓴 것이다.

## 6. FR-29 진입 조건 검사 — 실행을 실제로 막았다

전부 **브라우저를 거치지 않은 직접 HTTP 호출**이다. 기록은
[P2-03-admission-checks.json](P2-03-admission-checks.json)에 14건이 있다.

| 시도 | 응답 | 사유 코드 |
|---|---|---|
| 의도 없는 Case에서 제한 작업 | 409 | `intent_not_agreed`, `intent_gate_not_passed` |
| 초안은 있으나 동의·검토 전 | 409 | `intent_not_agreed`, `intent_gate_not_passed` |
| **동의는 했지만 게이트 fail** | 409 | `intent_gate_not_passed` |
| 권한을 `workspace_write` 로 요청 | 409 | `permission_not_allowed_in_stage` |
| `feature_implementation` 목적 | 409 | `prerequisite_not_implemented` |
| 같은 목적을 **다른 task_id**로 재시도 | 409 | `prerequisite_not_implemented` |
| 미설치 도구(`opencode`) 지정 | 409 | `tool_not_available` |
| **조건을 모두 갖춘 뒤 제한 작업** | 201 | 허용 (`profile=feature_intent`, `gate_verdict=pass`) |

**동의가 실행 권한이 아니다.** 사람이 v1에 명시적으로 동의한 뒤에도(`201 Created`)
게이트가 `fail` 이라 실행은 거부됐다. 같은 일이 v2에서도 반복됐다. 두 조건이 별개라는
것이 실제 기록으로 남았다.

**없는 선행 조건을 통과로 처리하지 않았다.** 의도 동의·게이트를 모두 갖춘 상태에서도
`feature_implementation` 은 `prerequisite_not_implemented` 로 거부된다. 설계·계획 검토가
아직 없기 때문이며, 이 거부는 임시 통과 처리를 넣지 않았다는 증거다.

**거부도 기록된다.** 14건 중 8건이 `refused` 이고 각각 요청한 목적·권한·적용 조건표와
사유 코드가 남아 있다. Run은 만들어지지 않았다 — 거부가 "만들었지만 멈춤"이 아니다.

### 중복 실행 방지 (실제 CLI 경로)

`live-work-1` 을 같은 `run_id` 로 재전송했다.

```
재전송 -> 200 created=False admission=null   부수효과 5 → 6 → 6
```

실행 부수효과가 1회만 늘었고, 재전송에는 **검사 기록도 생기지 않았다**(`admission=null`).
하지 않은 검사를 통과로 적지 않는다. CLI 원문 스트림 파일도 `live-work-1` 에 대해
하나뿐이다.

### 데이터 경계

표식 문자열 `ZZMARKER-P203-LIVE` 를 요청·피드백·지시에 넣고 라이브 실행 뒤 검사했다.

| 위치 | 결과 |
|---|---|
| 제어부 파일(sqlite3·WAL·SHM·로그) **4개 전부** | **0건** (못 읽은 파일 0개) |
| Runner 저장소 | 6개 파일에 존재 |

게이트 검토 지시문도 제어부에 없다. 지시문 조립이 Runner에 있기 때문이며
`tests/test_data_boundary.py` 의 `test_the_controller_stores_no_prompt_text` 가 이를 고정한다.

### 강제 종료 후 복원

제어부 자식 프로세스를 `taskkill /F /T` 로 죽이고 재기동했다.

```
게이트 pass→pass · 발견 0→0 · 진입 검사 14→14 · Run 6→6 · 의도 버전 3 · 동의 agreed_current
재시작 후 feature_implementation -> 409 [prerequisite_not_implemented]
재시작 후 workspace_write        -> 409 [permission_not_allowed_in_stage]
```

**재시작으로 조건을 벗어나지 못한다.** 판단 근거를 전부 DB에서 다시 읽기 때문이다.
메모리에 "이 Case는 통과했다"를 두지 않는다.

## 7. 성공 기준별 결과

| ID | 기준 | 결과 | 근거 |
|---|---|---|---|
| AC-1 | QG-01 규칙 검사와 발견 사항의 구성 | **통과** | `test_gate.py` 3건, 라이브 v1~v3 |
| AC-2 | AI 의미 검토가 작성과 별도 세션, 미실행은 `not_run` | **통과** | 라이브 세션 식별자 대조, `test_gate.py` |
| AC-3 | 게이트와 동의는 별개 기록 | **통과** | 라이브: 동의 201 후에도 실행 거부 |
| AC-4 | 새 버전은 이전 판정을 승계하지 않음 | **통과** | 라이브 v1→v2→v3 `needs_recheck` 전이 |
| AC-5 | 게이트 실패 중에도 열람·질문·피드백 가능 | **통과** | `test_gate.py`, 라이브에서 v1 fail 상태로 열람·피드백 수행 |
| AC-6 | 진입 검사가 서버에서, 직접 호출도 동일 | **통과** | 라이브 14건 전부 직접 HTTP |
| AC-7 | 하위 작업·재시작·유형·권한 확대로 우회 불가 | **통과** | `test_admission.py` 4건 + 라이브 재시작 후 재확인 |
| AC-8 | 미구현 선행 조건은 거부로 드러남 | **통과** | `prerequisite_not_implemented` (자동·라이브) |
| AC-9 | 실제 CLI 한 경로 연결, read_only, 실행 ID·이벤트·결과 저장 | **통과** | 4절. codex·claude **두 경로** 모두 |
| AC-10 | 재전송이 실제 CLI 경로에서도 중복 실행 없음 | **통과** | 부수효과 5→6→6 |
| AC-11 | AI가 의도 초안을 작성, 작성 주체가 실제와 일치, 사람 경로 유지 | **통과** | v1·v2는 `ai_drafted`, v3은 `human_typed` |
| AC-12 | 게이트·초안 본문이 제어부 바이트에 없음 | **통과** | 6절 + `test_data_boundary.py` 3건 |
| AC-13 | capability 는 실측 근거가 있는 것만 verified | **통과** | 4절 표, `test_admission.py` |
| AC-14 | 재시작 복원 | **통과** | 6절 |

## 8. 이번에 검증하지 않은 것

**미검증을 통과로 적지 않는다.** 아래는 남아 있다.

| 항목 | 상태 | 어디서 |
|---|---|---|
| 코드를 바꾸는 실행(`workspace_write`) | **의도적으로 열지 않음.** 거부만 확인 | P3 |
| 설계·계획 산출물과 그 검토 | 없음. 그래서 `feature_implementation` 이 거부된다 | P3 |
| QG-02~07과 게이트 ON/OFF 설정 | 구현하지 않음 | P4 |
| 질문의 `blocks`(의존 작업) 강제 | 기록만 하고 차단하지 않음 | P3-02 |
| 자식 프로세스 잔류 확인 | `residual_activity` 가 항상 `unknown` | P1-03 이월 |
| 안전 중지(다음 호출 차단)를 제품 경로에 연결 | 어댑터에 훅 주입을 넣지 않았다. capability 로만 보고한다 | 이후 |
| 세션 재개(`resume`) | 진입 검사가 거부만 한다. 실제 재개 동작 미확인 | 이후 |
| 브라우저 화면 | **이번에는 사람이 클릭해 확인하지 않았다.** 빌드(tsc+vite)와 API 계약까지만 확인 | 아래 참조 |
| 오래된 의도 버전을 대상으로 한 검토 요청 | 진입 검사는 최신 버전을 보고, 실제 대상은 지시 원문이 정한다. 그 경우 규칙 검사가 `not_latest_version` 으로 잡지만 라이브로 확인하지 않았다 | 이후 |
| 여러 Runner·여러 사용자 | 한 Runner·한 사용자·루프백에서만 확인 | P6 |

**화면은 라이브로 클릭 검증하지 않았다.** P2-02에서는 Edge headless로 한 바퀴 돌렸지만
이번에는 API 계약 검증에 집중했다. 조건 판단이 전부 서버에 있어 화면이 조건을 바꿀 수
없다는 것은 코드와 시험으로 확인했지만, **실제 렌더링은 확인하지 않았다.**
P2-04의 화면 작업과 함께 확인하는 것이 낫다.

## 9. 구현 중 고친 것

| 발견 | 고친 방식 |
|---|---|
| 빈 능력 목록으로 등록한 Runner에 실행을 배정할 뻔했다 | `tool_not_available` 로 거부한다. 시험의 등록 helper도 제품이 실제로 보고하는 값을 쓰게 바꿨다 |
| 기존 배관 시험 6건이 기능 Case를 써서 새 진입 검사에 걸렸다 | 기준을 낮추지 않고 **검사 대상을 분리**했다 — 배관 시험은 조사 유형 Case로, 기능 조건은 `test_admission.py` 로 |
| `test_flow.py` 의 capability 시험이 도구별 값을 한 사전에 합쳐 마지막 도구가 이겼다 | 도구별로 보도록 고쳤다. 합치면 "누구의 능력인가"가 사라진다 |
| AI가 요약 없이 질문을 내면 본문을 잘라 요약으로 쓸 위험이 있었다 | `runner/prompts.py` 가 자리표시 문구를 쓴다. 본문 발췌가 제어부에 남지 않는다 |
| 첫 라이브 실행이 게이트 실패로 멈췄다 | **스크립트를 고치지 않고 제품 절차를 그대로 따랐다** — 피드백 → 새 버전 → 재검토. 게이트를 느슨하게 만들지 않았다 |
