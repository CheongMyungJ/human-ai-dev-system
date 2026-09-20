# P2-01 최소 골격·영속 상태 — 실행 결과

수행일: 2026-09-20. 계획: [`P2-PLAN-01`](../../DEVELOPMENT.md) (DEVELOPMENT.md 3절).

이 문서는 **실제로 실행한 것만** 적는다. 자동 시험 통과와 실제 프로세스·브라우저 실행을 구분하고,
검증하지 않은 항목은 7절에 미검증으로 남긴다.

## 1. 실행 환경

| 항목 | 값 | 확인 방법 |
|---|---|---|
| OS | Windows 11 Home 10.0.26200 | P1-01 실측과 동일 |
| 셸 | PowerShell 7.6.6 | 〃 |
| Python(고정) | **3.12.10** — `.venv` (`py -3.12 -m venv .venv`) | `.venv\Scripts\python.exe --version` |
| SQLite | 3.49.1 (Python 3.12 내장 모듈) | `python -c "import sqlite3; print(sqlite3.sqlite_version)"` |
| Node / npm | v22.15.1 / 10.9.2 | `node --version`, `npm --version` |
| 브라우저(검증용) | Microsoft Edge (설치본, headless) | `msedge --headless=new` |

P1이 남긴 경고 — `python`(3.12)과 `py` 런처 기본값(3.14)이 다르다 — 는 여기서 닫았다.
모든 실행 스크립트가 `py -3.12` 로 만든 `.venv` 의 인터프리터를 직접 가리킨다.

설치 위치는 저장소 로컬 `.venv\` 와 `web\node_modules\` 뿐이다. 사용자 전역 Python·Node·CLI
설정은 바꾸지 않았다. 런타임 데이터는 `var\` 에 생기며 커밋하지 않는다.

## 2. 만든 것

| 구성 | 파일 | 역할 |
|---|---|---|
| 공통 모델 | `domain/models.py`, `domain/ids.py` | 상태값·RunRequest·RunResult·ArtifactRef. 저장·전송 방식에 의존하지 않음 |
| 제어부 | `controller/schema.sql`, `db.py`, `repository.py`, `api.py`, `app.py`, `relay.py`, `config.py` | 상태 DB, 업무 API, Runner 계약, 원문 일시중계 |
| Runner | `runner/store.py`, `ledger.py`, `executor.py`, `agent.py`, `client.py`, `config.py` | 원문 영속 저장, 실행 원장, 최소 실행기, 폴링 루프 |
| 화면 | `web/` (Vite + React 19 + TS) | 프로젝트·Case·원문 참조·의도/결정·Run 표시와 생성 |
| 스크립트 | `scripts/bootstrap.ps1`, `run-controller.ps1`, `run-runner.ps1`, `run-tests.ps1` | 설치·실행·시험 |
| 시험 | `tests/` 19건 | 아래 3~6절 |

**P2-01의 실행기는 코딩 CLI가 아니다.** `runner/executor.py` 는 지시 원문을 읽고 요약을 만드는
최소 실행기이며, capability 보고에서 CLI 능력을 `verified` 로 올리지 않는다
(`safe_stop_next_call`, `session_identity`, `tool_boundary_observed` = `unsupported`).
Codex·Claude 어댑터 연결은 P2-03에서 P1 공통 계약을 근거로 붙인다.

## 3. 저장 경계 설계 — 왜 이렇게 만들었는가

`POST /api/cases/{id}/artifacts` 는 원문을 받지만 **저장하지 않는다.** 흐름은 이렇다.

```
브라우저 ─원문─> 제어부(메모리 중계 버퍼) ─폴링으로 가져감─> Runner(파일로 영속 저장)
                       │                                            │
                       │<──────── "저장했다" 보고 ───────────────────┘
                       └─> artifact_ref.availability = available  ← 이때가 저장 완료
```

- 응답은 **202**다. 201/200이 아니다. 접수는 저장 완료가 아니다(NFR-01).
- 제어부 DB 스키마에는 원문 본문을 담는 컬럼이 없다. `summary` 는 200자 상한의
  `CHECK` 제약이 걸린 표시용 문구이며 호출자가 따로 준다(본문에서 뽑지 않는다).
- 제어부가 중계 중에 재시작하면 본문은 사라진다. 이는 결함이 아니라 요구다 —
  저장 완료로 응답한 적이 없는 입력이고, 서버 영구 저장으로 우회하지 않는다.
  사라진 접수는 `lost_before_persist` 로 드러나고, 그 참조로는 실행을 배정하지 않는다.
- 요청 로그에 본문을 쓰지 않는다. 메서드·경로·상태 코드·소요 시간만 남긴다.

**메모리 중계는 "서버로 전송되지 않음"을 뜻하지 않는다.** 서버 프로세스가 내용을 취급한다.
영구 보관을 하지 않을 뿐이다(data-boundary-review.md 3절).

## 4. 중복 실행 방지 — P1에서 이월한 항목

P1은 '지연 이벤트·응답 유실에서 중복 호출하지 않음'을 미검증으로 남기고 P2-01로 넘겼다.
여기서 **두 층**으로 구현하고 실제 부수효과로 확인했다.

| 층 | 위치 | 막는 상황 |
|---|---|---|
| 제어 API | `run` 테이블의 `run_id` 기본 키 + `request_log` | 같은 요청이 두 번 들어옴 |
| Runner 원장 | `var/runner/<id>/ledger/<run_id>.json` | **결과 보고가 유실돼 같은 run_id 가 다시 배정됨** |
| fencing | `assignment_generation` | 오래된 실행자의 지연 보고가 최신 상태를 덮어씀 |

판정 근거는 로그 문장이 아니라 `runner/executor.py` 가 실행할 때마다
`var/runner/<id>/effects/<case_id>.log` 에 덧붙이는 **한 줄**이다. 실행되지 않으면 그 줄도 없다.
P1-03이 파일 존재로 판정한 것과 같은 방식이다.

원장은 결과를 **보고하기 전에** 확정한다. 그래서 보고가 유실돼도 재실행이 일어나지 않는다.
착수만 적히고 결과가 없는 경우(실행 중 강제 종료)는 재실행하지 않고 `outcome = unknown` 으로
보고한다. **성공으로도 미실행으로도 바꾸지 않는다.**

## 5. 성공 기준별 결과

| 기준 | 결과 | 증거 |
|---|---|---|
| AC-1 제어부·Runner·화면 실제 연결 | **통과** | 6절 (실제 프로세스 + 브라우저 클릭) |
| AC-2 강제 종료 후 복원 | **통과** | `tests/test_restart_recovery.py` — uvicorn 자식 프로세스를 `taskkill /F /T` 로 죽이고 재기동 |
| AC-3 같은 요청 재전송이 중복 실행을 만들지 않음 | **통과** | `tests/test_idempotency.py` 2건 + 6절의 브라우저 2회 클릭 |
| AC-4 오래된 배정 세대의 보고 거부 | **통과** | `tests/test_idempotency.py::test_stale_generation_report_is_rejected_and_state_untouched` |
| AC-5 같은 `(run_id, seq)` 이벤트 중복 저장 안 됨 | **통과** | `tests/test_idempotency.py::test_duplicate_events_are_not_stored_twice` |
| AC-6 원문이 제어부 DB·로그에 없음 | **통과** | `tests/test_data_boundary.py` + 6절의 표식 검색 |
| AC-7 런타임 고정·재현 명령 문서화 | **통과** | 1절, `scripts/`, [README](../../README.md) |

### 자동 시험

```
.venv\Scripts\python.exe -m pytest
→ 19 passed (7.16s)

.venv\Scripts\python.exe -m unittest discover -s p1/opencode -t p1/opencode
→ Ran 18 tests, OK   (P1 문서 계약 시험. CLI를 실행하지 않으며 OpenCode 실환경 검증이 아니다)
```

두 묶음을 `scripts\run-tests.ps1` 하나로 실행한다.

| 시험 파일 | 건수 | 확인 대상 |
|---|---|---|
| `tests/test_flow.py` | 5 | 종단 연결, 의도 버전·동의의 분리, 저장 안 된 지시로 실행 거부, capability 보고 |
| `tests/test_idempotency.py` | 6 | AC-3·4·5, 멱등 키, 끝난 Run 덮어쓰기 거부 |
| `tests/test_data_boundary.py` | 5 | AC-6, 중계 버퍼 비움, 접수≠저장완료, 경로 탈출 거부 |
| `tests/test_restart_recovery.py` | 3 | AC-2, 중계 중 재시작 시 `lost_before_persist`, Runner 원장의 재시작 생존 |

## 6. 실제 프로세스·브라우저 실행 증거 (AC-1)

제어부와 Runner를 각각 **실제 프로세스**로 띄우고, 설치된 Edge로 화면을 열어 클릭으로 수행했다.

```
제어부: .venv\Scripts\python.exe -m uvicorn controller.app:app --host 127.0.0.1 --port 8765
Runner: HADS_RUNNER_ID=runner-local-1 .venv\Scripts\python.exe -m runner.agent
화면  : http://127.0.0.1:8765/  (제어부가 web\dist 를 직접 서빙)
```

### 6-a. 브라우저에서 눌러서 수행한 것 — [`P2-01-ui-driven.log`](P2-01-ui-driven.log)

화면 캡처: [`P2-01-ui-driven.png`](P2-01-ui-driven.png)

```
클릭: 프로젝트 열기
클릭: Case 추가 — '화면에서 만든 Case 1789904641'
클릭: Case 열기 — case-549366859d230fae
클릭: 원문 제출 → 접수함(art-66ed51dddd13caaf). 아직 저장 완료가 아니다 — Runner가 저장을 보고하면 상태가 바뀐다. 목록을 새로 고쳐 확
화면 표시: 원문 상태가 'Runner에 저장됨'으로 바뀜
클릭: 실행 요청 — Run run-ui-1789904641 를 새로 만들었다.
클릭: 같은 run_id 로 다시 실행 요청 — Run run-ui-1789904641 는 이미 있다. 같은 run_id 는 새 실행을 만들지 않는다.
화면 표시: Run 결과 completed
```

화면이 아니라 **DB를 직접 열어** 대조한 결과:

```
DB case: id=case-549366859d230fae title='화면에서 만든 Case 1789904641' status=received
DB run rows for run-ui-1789904641: 1 (중복 실행이면 2가 된다)
DB run outcome=completed generation=1
DB artifact instruction: available sha256:130285de02e225319a8… summary='화면 제출 지시 v1'
DB artifact run_output: available sha256:b7adb02152856e8286f… summary='run output for run-ui-1789904641'
실행 부수효과 줄 수: 1 (화면에서 실행을 두 번 눌렀다)
UI 표식이 제어부 DB 바이트에 있는가: False
UI 표식이 제어부 로그에 있는가: False
UI 표식이 Runner 원문 저장소에 있는가: True
```

마지막 세 줄이 AC-6의 핵심이다. 셋 다 False였다면 원문이 아예 저장되지 않은 것이므로
경계를 지킨 증거가 되지 않는다. **Runner에는 있고 제어부에는 없어야** 한다.

### 6-b. API 경로로 한 바퀴 — [`P2-01-live-session.log`](P2-01-live-session.log)

전체 응답: [`P2-01-live-run.json`](P2-01-live-run.json), [`P2-01-live-case.json`](P2-01-live-case.json).
화면 캡처: [`P2-01-ui.png`](P2-01-ui.png)(목록), [`P2-01-ui-case.png`](P2-01-ui-case.png)(Case 상세).

```
submit artifact -> HTTP 202 (202 = 접수, 저장 완료 아님)
intake stored_at=2026-09-20T11:43:52.690699+00:00 state=stored
create run run-live-1789904633: HTTP 201 created=True
same run_id resent: HTTP 200 created=False  (만들지 않은 것을 201 Created 로 보고하지 않는다)
run finished: outcome=completed exit_code=0 generation=1 usage=not_reported residual=none events=5
event types: run_started, tool_call_started, tool_call_finished, assistant_message, run_finished
effect file case-575bc1cb004bcc22.log: 1 줄 (실제 실행 횟수)
marker in controller db bytes: False
marker in controller log: False
marker in runner artifact store: True
```

이벤트 종류는 P1 공통 계약 7.1절의 정규화 이름을 그대로 쓴다. `usage` 는 이 실행기가
사용량을 제공하지 않으므로 `not_reported` 다. **0으로 표시하지 않는다.**

프로세스 원문 로그: [`live-controller.out`](live-controller.out), [`live-runner.out`](live-runner.out).
검증 후 두 프로세스를 모두 종료했고 포트 8765에 남은 연결이 없음을 확인했다.

브라우저 자동 조작에 쓴 도구(playwright + 설치된 Edge)는 **저장소 밖 임시 가상환경**에 설치했다.
제품 의존성이 아니며 `requirements.txt` 에 넣지 않았다. 같은 확인을 사람이 직접 클릭해서
재현할 수 있다.

## 7. 남은 미검증 항목과 다음 단계로 넘기는 것

이번에 확인하지 않은 것을 확인한 것처럼 적지 않는다.

| 항목 | 상태 | 처리 |
|---|---|---|
| 의도 여섯 필드 초안·피드백·최신 동의 흐름 | 미구현 | **P2-02**. 지금은 의도 버전과 동의 기록의 *자리*만 있다 |
| FR-29 진입 조건 검사(미동의·오래된 동의의 실행 차단) | **미구현** | **P2-03**. 지금 통과 처리를 넣어 두지 않았다 |
| 실제 코딩 CLI 실행 연결 | 미구현 | **P2-03**. P1 계약과 capability 표를 근거로 붙인다 |
| 원문 본문의 웹 열람(인증된 일시중계 읽기 경로) | 미구현 | **P2-04**. 화면은 참조와 availability 만 표시한다 |
| Runner 오프라인 시 `runner_offline` 표시 | **미검증** | 상태값은 있으나 전이 조건을 아직 구현하지 않았다. 하트비트 만료 판정과 함께 P2-04 |
| 동시 Runner 2대 이상, 같은 Case 쓰기 직렬화 | 미검증 | P3-03의 worktree 작업과 함께 |
| 정지 확인 없는 재배정 금지(NFR-01) | **부분** | `bump_generation()` 은 fencing 일 뿐 정지 증거가 아니다. 코드 주석과 API 설명에 명시했고, 실제 정지 확인은 P6-03 |
| 백업·복원 | 미구현 | P6-04 |
| 원격·인증·암호화 | 미구현 | P6-01 |
| 프록시·브라우저 캐시의 원문 잔존 | 미검증 | 이번 확인은 제어부 DB·WAL·로그 범위다. 프록시·캐시 경로는 P6-02 |

## 8. 남은 위험

1. `synchronous = FULL` 로 두었지만 이는 SQLite 수준의 내구성이다. 디스크 캐시·전원 장애까지
   포함한 보장은 아니며 백업 요구(NFR-01)를 대신하지 않는다.
2. 제어부가 단일 프로세스·단일 연결을 쓴다. 규모 시험(프로젝트 10개·Runner 3대)은 아직 안 했다.
3. `starlette.testclient` 가 httpx 사용에 대한 deprecation 경고를 낸다. 시험은 통과하지만
   다음 주요 버전에서 바뀔 수 있다.
4. 배정이 폴링이다. 지연은 폴링 간격(기본 1초)만큼 생긴다. 실시간 제어가 필요해지면 바꿔야 한다.
5. P1에서 넘어온 위험은 그대로 남아 있다 — 두 CLI의 자동 업데이트, Claude 훅의 fail-open,
   Codex 훅 신뢰 요구, 프로세스 트리 종료 미구현. 해당 기능을 붙일 때 확인한다.
