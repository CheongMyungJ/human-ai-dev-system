# P2-04 결과·재시작 — 실행 결과

수행일: 2026-09-20. 계획: [`P2-PLAN-04`](../../plans/P2-PLAN-04.md).

이 문서는 **실제로 실행한 것만** 적는다. 자동 시험(가짜 실행기)과 실제 코딩 CLI 실행을
구분하고, 검증하지 않은 항목은 8절에 미검증으로 남긴다.

## 1. 실행 환경

| 항목 | 값 | 확인 방법 |
|---|---|---|
| OS | Windows 11 Home 10.0.26200 | P2-03과 동일 |
| 셸 | PowerShell 7 | 〃 |
| Python(고정) | 3.12.10 — 저장소 로컬 `.venv` | `.venv\Scripts\python.exe --version` |
| Node / npm | v22.15.1 | `npm run build` 출력 |
| 제어부 스키마 | **v4** | `GET /api/health` |
| Codex CLI | **codex-cli 0.154.0** | Runner 기동 시 `codex --version` |
| Claude Code | **2.1.278** | Runner 기동 시 `claude --version` |
| 브라우저 | Microsoft Edge 153.0.4234.48 | Playwright `channel="msedge"` |
| OpenCode | **없음** | P1-04와 같음 |

두 CLI 모두 자동 업데이트가 켜져 있어 실행 시점의 관측 버전을 함께 남긴다.
시스템은 두 CLI의 **자격증명을 읽지도 주입하지도 않았다.**

브라우저는 **이 PC에 이미 있는 Edge 를 썼다.** 검증을 위해 브라우저를 내려받지 않았다.

라이브 실행 데이터는 `%LOCALAPPDATA%\Temp\hads-p2-04-live` 에 두어 저장소 `var\` 를
건드리지 않았다. CLI의 작업공간도 같은 곳의 별도 임시 git 저장소(`workspace\`, 파일
`sample.log` 하나)이며 이 설계 저장소를 CLI에 노출하지 않았다.

## 2. 만든 것

| 구성 | 파일 | 역할 |
|---|---|---|
| 상태값 | `domain/models.py` | `CriterionState` `CriterionVerdict` `EvidenceKind` `CompletionMode` `AcceptanceMode` `ClosureKind` `CandidateState` `AcceptanceRefusal` `CaseRelationKind` |
| 스키마 v4 | `controller/schema.sql`, `db.py` | 표 9개 신규. **전부 본문 컬럼 없음** |
| 의도 문서 v2 | `domain/intent_doc.py` | 성공 기준을 **문서 안에** 넣는다. v1 문서도 계속 읽으며 그 기준은 0건 |
| 제어부 | `controller/repository.py`, `api.py` | 기준 반영·판정 기록·후보·인수·예외·종료·후속 Case·결과 화면 |
| 게이트 | `controller/gate.py` | 기준 0건을 **권고**로 드러낸다 |
| 진입 검사 | `controller/admission.py` | 대체된 의도 버전 검토를 거부(`intent_version_not_latest`) |
| Runner | `runner/prompts.py`, `agent.py` | 초안 지시문에 성공 기준, 확인 방법 없는 기준은 **버린다** |
| 화면 | `web/src/ResultPanel.tsx`(신규), `App.tsx`, `IntentPanel.tsx`, `api.ts` | 기준별 결과·근거 열람·최종 확인·예외·후속 Case·피드백 처리 |
| 시험 | `tests/test_results.py` `test_completion.py`(신규) 외 5개 파일 | 79 → **123건** |

### 세 종류의 기록을 합치지 않는다

```
최종 인수(final_acceptance)   이 후보를 받아들였다
예외 결정(exception_decision) 표시된 미충족·미검증을 수용했다 — 원래 판정은 그대로
종료 기록(closure_record)     업무가 실제로 종료로 확정됐다
```

한 화면에서 결정해도 표는 셋이다. 인수가 예외를 만들지 않고, 인수만으로 종료가
확정되지도 않는다 — 결과를 확정할 수 없는 실행이 남아 있으면 인수는 기록하고
종료 기록은 만들지 않는다(completion-lifecycle 4·5·7절).

## 3. 자동 시험

```
scripts\run-tests.ps1
  제품 시험 (pytest)                       123 passed
  P1 OpenCode 문서 계약 시험 (unittest)     Ran 18, OK
web> npm run build                          tsc -b 통과, vite 빌드 성공
```

| 파일 | 건수 | 보는 것 |
|---|---|---|
| `tests/test_results.py` | 14 | **신규.** 성공 기준·기준별 결과·실행 불명의 거부·승계 금지 |
| `tests/test_completion.py` | 28 | **신규.** 후보·인수·예외·자동 완료·종료 경계·미정리 실행 |
| `tests/test_admission.py` | 21 | 대체된 버전 검토 거부 1건 추가 |
| `tests/test_restart_recovery.py` | 5 | 기준·판정·후보·인수의 강제 종료 복원 1건 추가 |
| `tests/test_data_boundary.py` | 13 | 기준 본문·인수 문구의 저장 경계 2건 추가 |
| `tests/test_migration.py` | 5 | v4 표 9개와 **완료 정책 행이 생기지 않음** 확인 |
| 그 밖 | 37 | P2-01~03 그대로 |

**자동 시험은 실제 CLI를 부르지 않는다.** conftest 의 `FakeCliExecutor` 를 쓴다.
실제 CLI 실행 증거는 아래 4~6절의 라이브 검증에 있다(P1-02가 세운 구분).

## 4. 라이브 검증 — 화면만으로 처음부터 끝까지

브라우저(Edge)로 조작했고 **API를 직접 부르지 않았다.** 확인용 조회만 HTTP로 했다.
조작 기록은 [P2-04-walkthrough.log](P2-04-walkthrough.log), 화면 캡처는 같은 디렉터리의
`P2-04-ui-*.png` 다.

### 4.1 실제로 실행한 CLI

주 Case(`case-b55ee0ec6964eccb`)에서 **실행 11건**이 모두 실제 CLI였다.

| 목적 | 도구 | 횟수 |
|---|---|---|
| `intent_authoring` | codex-cli 0.154.0 | 4 |
| `intent_gate_review` | Claude Code 2.1.278 | 6 |
| `limited_analysis` | codex-cli 0.154.0 | 1 |

후속 Case 에서 `intent_gate_review` 2건을 더 실행했다. **합계 13건.**
모두 `read_only` 권한이며 작업공간 변경은 관측되지 않았다.

### 4.2 QG-01이 여섯 번 판정했고 다섯 번 막았다

| 의도 버전 | 작성 | 규칙 | AI | 종합 | 검토 run |
|---|---|---|---|---|---|
| v1 | AI(codex) | pass | **fail** | fail | ui-review-2 |
| v2 | AI(codex) | pass | **hold** | needs_recheck | ui-review-3 |
| v3 | AI(codex) | **fail** | pass | needs_recheck | ui-review-4 |
| v4 | AI(codex) | **fail** | not_run | needs_recheck | — |
| v5 | 사람 | pass | **fail** | needs_recheck | ui-review-5 |
| v6 | 사람 | pass | pass | **pass** | ui-review-6 |

**규칙과 AI가 따로 판정한다는 것이 v3 에서 그대로 드러났다** — AI 검토는 통과라고
했는데 규칙 검사가 목표 미정과 성공 기준 0건을 잡아 통과하지 못했다. 반대로 v1·v2·v5
는 규칙이 통과했는데 AI가 막았다. 어느 한쪽만으로는 통과하지 않는다.

검토 세션은 매번 작성 세션과 달랐다. v5·v6 은 사람이 썼으므로 작성 세션이 아예 없고
(`author_session_ref=None`), 그래도 검토는 성립한다.

**AI 검토가 실제로 한 지적**(요약, 원문은 Runner에):

- v1: "'줄 시작의 ERROR' 라는 해석을 확정 요구로 적었으나, 실제 sample.log 의 ERROR
  줄은 모두 타임스탬프로 시작해 이 규칙으로는 출력이 0건이다" — **검토 세션이 작업공간의
  실제 파일을 읽고 찾아낸 것이다.**
- v5(사람이 쓴 것): "open_questions 는 매칭 규칙이 미정이라 하는데 match-rule 질문
  본문과 C-01 은 이미 (가)로 확정해 서로 모순된다" — 내가 쓴 초안의 실제 모순이다.
- 후속 Case v1(사람이 쓴 것): "'파일을 만들거나 바꾸지 않는다' 는 제약과 '표본 파일을
  만들어 대조한다' 는 C-02 검증 방법이 정면으로 충돌한다" — 역시 내가 쓴 모순이다.

**게이트를 느슨하게 고치지 않았다.** 매번 의도를 고쳐 다시 검토받았다.

### 4.3 성공 기준이 의도에서 나오고, 0건이면 0건으로 남는다

| 의도 버전 | 작성 | 기준 건수 |
|---|---|---|
| v1 | AI | 3 |
| v2 | AI | 3 |
| v3 | AI | **0** |
| v4 | AI | 1 |
| v5 | 사람 | 2 |
| v6 | 사람 | 2 |

**v3 가 이 규칙의 증거다.** AI가 기준을 하나도 쓰지 않았고 시스템은 채우지 않았다.
규칙 검사가 `no_success_criteria` 를 권고로 올렸고, 그 상태로는 최종 인수가 거부된다.

동의 전 기준은 `proposed`, 사람이 v6 에 명시 동의한 뒤 `user_confirmed` 가 됐다.
**판정은 그대로 `unverified`** 였다 — 동의가 결과를 만들지 않는다.

### 4.4 기준별 결과와 근거

주 Case:

| 기준 | 판정 | 근거 종류 | 근거 |
|---|---|---|---|
| C-01 | met | `run_output` | run `ui-work-1`, 원문 `art-6b3cf0f863b19b4e` |
| C-02 | met | `human_judgement` | 사람 판단 |

`근거 원문 받아 보기` 를 화면에서 눌러 실행 결과 원문(654자)을 받아 봤다. 본문은
소유 Runner에서 와 화면에만 나타났고 제어부에는 남지 않았다(6절).

**실제 실행 결과**([P2-04-evidence-original.txt](P2-04-evidence-original.txt)):

```
run_id=ui-work-1  tool=codex/exec  permission=read_only
observed_tool_version=codex-cli 0.154.0
session_ref=01a0bf51-6700-7ed2-92d2-1a7f454e5698
exit_code=0  outcome=completed  normalized_events=16 unmapped=0
```

### 4.5 최종 확인

```
결과 후보 v1: 기준 2/2 충족, 미해결 0건, 미정리 실행 0건,
              의도 agreed_current, 게이트 pass
"좋아 보이네요"        → 400 거절: 대상이 분명한 인수 문구가 아니다
"이 결과를 인수합니다." → 201, closure_kind=completed, case status=closed
```

결정 기록은 `intent_agreement(owner)` 와 `final_acceptance(owner)` **두 행**으로
따로 남았다. 인수가 의도 동의를 만들지도, 그 반대도 아니다.

### 4.6 종료 후

- 종료된 Case 에 직접 API 로 실행을 요청하면 **409 `case_already_closed`** 다.
  진입 검사 기록에도 `refused / case_already_closed` 로 남는다
  ([P2-04-admission-checks.json](P2-04-admission-checks.json)).
- 화면에서 `연결된 새 Case 만들기` 로 후속 Case 를 만들었다. 새 Case 는
  **의도 0버전·동의 `no_intent`·기준 0건**으로 시작했다 — 이전 동의를 승계하지 않는다.
- 이전 Case 의 종료 기록은 그대로 남아 있다.

## 5. 라이브 검증 — 미충족 → 예외 수용 → 예외 종료

후속 Case(`case-480ffa89250dd9c2`)에서 **한 기준이 미충족으로 남는 경우**를 화면에서
끝까지 따라갔다. 이 Case 는 4절과 별개로 의도·게이트·동의를 처음부터 다시 거쳤다.

```
기준 C-01 met (사람 판단) / C-02 not_met (사람 판단)
결과 후보 v1: 기준 1/2 충족, 미해결 1건
"이 결과를 인수합니다." → 409 거절: unresolved_criteria
예외 수용 (C-02, 범위: "이번 종료에만 적용. 소문자 표본 확인은 후속 Case 로 넘긴다")
  → exception_decision.original_verdict = not_met
  → 기준 판정은 {'C-01': 'met', 'C-02': 'not_met'} 그대로. **바뀌지 않았다**
"이 결과를 인수합니다." → 201, closure_kind=closed_with_exceptions, exception_count=1
```

결정 기록 **세 행**: `intent_agreement(owner)` · `exception_closure(owner)` ·
`final_acceptance(owner)`. 예외가 인수를 만들지 않고, 인수가 예외를 만들지 않는다.
종료 뒤에도 C-02 는 `not_met` 이다 — **'충족'으로 표시되지 않는다.**

## 6. 재시작 복원

제어부와 Runner를 각각 `taskkill /F /T` 로 죽이고 같은 데이터 경로로 다시 띄웠다.
정상 종료가 아니라 강제 종료다.

| 항목 | 종료 전 | 재기동 후 |
|---|---|---|
| 의도 버전 | 2 | 2 |
| 성공 기준 | 3 | 3 |
| Run | 4 | 4 |
| 원문 참조 | 9 | 9 |
| QG-01 판정 | `not_run` | `not_run` |
| 미해결 피드백 | 1 | 1 |

**재기동이 상태를 개선하지 않는다는 점이 중요하다** — 검토하지 않은 게이트는 재기동
뒤에도 `not_run` 이고, 닫지 않은 피드백도 그대로 남는다. 자동 시험
(`tests/test_restart_recovery.py`)은 여기에 더해 **기준 판정·결과 후보·인수·예외가
강제 종료 뒤에도 남고, 결과가 `unknown` 인 실행은 재기동 뒤에도 근거가 되지 않는다**는
것을 실제 uvicorn 자식 프로세스로 확인한다.

## 7. 데이터 경계 (바이트 검사)

라이브 데이터로 제어부 5,601,565 바이트(DB·WAL·SHM·로그·표준출력)와 Runner 저장소
303,900 바이트를 훑었다.

| 문자열 | 제어부 | Runner |
|---|---|---|
| 의도 목표 본문 | **없음** | 있음 |
| 성공 기준 본문(C-01) | **없음** | 있음 |
| 확인 방법 본문 | **없음** | 있음 |
| 후속 Case 기준 본문 | **없음** | 있음 |
| 실행 결과 원문 | **없음** | 있음 |
| 인수 문구 | **없음** | **없음** |

인수 문구가 어디에도 없는 것은 의도한 동작이다. 제어부가 "대상이 분명한 인수인가"를
판단하는 데만 쓰고 버린다. 남겨야 한다면 원문 참조(`statement_artifact_id`)로 Runner에
저장해야 하며, 이번 화면은 그 경로를 쓰지 않았다.

**짧은 요약은 제어부에 있다**(기준 요약·확인 방법 요약·판정 요약·예외 범위 요약).
이것은 위반이 아니라 설계다 — 목록에서 구별하기 위한 200자 이하 요약이며 원문을
대체하지 않는다(data-boundary-review 1절).

## 8. 성공 기준별 결과 (AC-1~14)

| AC | 결과 | 근거 |
|---|---|---|
| AC-1 기준이 의도 버전에 묶이고 초안은 제안, 동의로 확인됨 | **통과** | `test_results.py` 4건 + 라이브 4.3절(v1~v6 기준 건수, 동의 후 `user_confirmed`) |
| AC-2 기본값 `unverified`, 근거 없는 판정 거부 | **통과** | `test_results.py` 3건 + 라이브(동의 후에도 `unverified`) |
| AC-3 실행 불명이 성공이 되지 않는다 | **통과** | `test_results.py` 5건(`unknown`·`failed`·`cancelled`·진행 중 각각 거부, `completed` 는 허용) + `test_restart_recovery.py`(실제 프로세스, 재기동 뒤에도 거부) |
| AC-4 기준별 근거 원문을 화면에서 읽는다 | **통과** | 라이브 4.4절(654자 수신, 캡처 `P2-04-ui-05-criteria.png`) + 7절 바이트 검사 |
| AC-5 후보가 한 버전으로 묶이고 바뀌면 이전 인수를 쓰지 않는다 | **통과** | `test_completion.py` 3건 + 라이브(후보 v1 내용) |
| AC-6 사람의 명시적 인수만, 거절 사유가 코드로 구별된다 | **통과** | `test_completion.py` 6건 + 라이브(모호한 문구 400, 미충족 409) |
| AC-7 예외를 수용해도 원래 판정이 보존된다 | **통과** | `test_completion.py` 2건 + **라이브 5절**(`original_verdict=not_met`, 종료 뒤에도 `not_met`) |
| AC-8 자동 완료는 사람 인수가 아니며 예외를 수용하지 않는다 | **통과** | `test_completion.py` 4건. **라이브 미실행** — 8.1 참조 |
| AC-9 인수가 다른 권한을 만들지 않는다 | **통과** | `test_completion.py` 2건 + 라이브(결정 기록이 종류별로 따로 남음) |
| AC-10 종료 후 변경은 연결된 새 Case | **통과** | `test_completion.py` 5건 + 라이브 4.6절 |
| AC-11 재시작 복원 | **통과** | 라이브 6절(실제 강제 종료) + `test_restart_recovery.py` 1건 추가 |
| AC-12 중계 중이던 열람은 `expired` 이며 삭제와 구분된다 | **통과** | `test_restart_recovery.py`(P2-02부터 있던 시험, 이번에도 통과). **P2-04 라이브에서는 재현하지 않았다** |
| AC-13 데이터 경계 | **통과** | `test_data_boundary.py` 13건 + 라이브 7절 바이트 검사 |
| AC-14 화면만으로 처음부터 끝까지 | **통과** | 라이브 4·5절. P2-03이 남긴 화면 미확인 경로(게이트 검토 실행·원문 열람·동의·제한 작업)가 여기서 닫혔다 |

### 8.1 라이브로 하지 않은 것

- **자동 완료 모드**는 자동 시험으로만 확인했다. 조건을 갖춘 Case 에 정책을 걸면
  사람 인수 없이 닫히므로, 라이브 검증에서 굳이 그 상태를 만들지 않았다.
- **미정리 실행이 남은 채 인수**하는 경우도 자동 시험으로만 확인했다. 화면에는 실행을
  `unknown` 으로 만드는 버튼이 없다(Runner가 보고하는 값이다).
- **중계 중 재시작으로 열람이 `expired` 가 되는 경로**는 기존 자동 시험이 실제 uvicorn
  프로세스로 확인하며, 이번 라이브 절차에서는 재현하지 않았다.

## 9. 검토·시험 중 발견해 고친 것

라이브에서 실제로 드러난 결함 셋과, 스스로 검토하다 찾은 둘이다.

| # | 무엇 | 어떻게 고쳤나 |
|---|---|---|
| 1 | **화면이 대체된 의도 버전을 검토했다.** 목록의 첫 intent 원문을 지시로 집어, v2 가 있는데도 v1 을 검토했다. 검토는 정상 종료하지만 최신 버전 게이트는 `not_run` 그대로여서 아무 것도 진척되지 않았다 | 화면이 최신 버전의 원문을 지정하게 고치고, **서버도** 지시 원문에서 대상을 끌어내 최신이 아니면 `intent_version_not_latest` 로 거부하게 했다. 화면만 고치면 같은 실수가 API 로 돌아온다. 회귀 시험 1건 |
| 2 | **AI가 새 버전을 써도 피드백이 닫히지 않았다.** Runner 작성 경로에는 `reflects_feedback` 가 없어 피드백이 `received` 로 남고, 최종 인수가 막혔다 | 피드백 처리를 **사람이** 정하는 경로를 만들었다(`POST /api/cases/{id}/feedback/{fid}/disposition`). AI가 스스로 "반영했다"고 선언하게 두지 않는다. 미반영은 이유가 필수다. 시험 1건 |
| 3 | **종료된 Case 의 실행 거부가 진입 검사 기록에 남지 않았다.** 앞단에서 예외로 던져 409만 돌아갔다 | `AdmissionRefusal.CASE_ALREADY_CLOSED` 를 만들어 진입 검사 안에서 판정한다. 허용도 거부도 같은 표에 남는다(FR-29) |
| 4 | **기준 0건이면 아무 것도 확인하지 않은 결과가 조용히 통과했다.** 미해결 0건이 되어 인수가 열린다 | QG-01 규칙 검사가 `no_success_criteria` 를 권고로 올리고, 최종 인수는 같은 이름의 사유로 **거부**한다. 시험 2건 |
| 5 | **미해결 피드백을 "기준 미충족"이라고 적고 있었다.** 사유 코드가 뭉뚱그려져 사람이 엉뚱한 곳을 고치게 된다 | 항목 종류별로 사유를 나눴다(`unresolved_criteria` / `open_intent_questions` / `unresolved_feedback`). 시험 1건 |

### 9.1 고치지 않고 드러낸 것

**AI 재작성 경로는 이전 버전을 보지 못한다.** 초안 작성 실행에 들어가는 것은 요청 원문
하나뿐이라, "이 지적을 고쳐 달라"만 보내면 AI가 의도 전체를 처음부터 다시 쓴다. 라이브
검증에서 실제로 v3 가 목표 미정·기준 0건으로 퇴화했다. 이번 단계에서 고치지 않았다 —
작성 실행에 이전 버전과 피드백을 컨텍스트로 넘기는 것은 P2-03이 만든 작성 경로의 확장이고,
컨텍스트 구성 규칙은 [검토 컨텍스트 계약](../../review-context-contract.md)과 FR-15의
범위다. **P3 또는 P4로 넘긴다.** 그때까지 재작성 요청에는 원래 요청을 함께 적어야 한다.

### 9.2 라이브가 드러낸 한계 하나

주 Case 의 C-01 을 `충족` 으로 기록했지만, **근거로 붙인 실행 결과는 그 판정을 뒷받침하지
않는다.** codex 는 "'ERROR 로 시작하는 줄'은 0개이고, 타임스탬프 뒤에 ERROR 가 있는 줄은
2개"라고 답했을 뿐 두 줄을 나열하지 않았다. 시스템은 **근거가 있는지**와 **그 실행이 정상
완료했는지**는 강제하지만, **근거가 판정을 뒷받침하는지는 강제하지 못한다.** 그것은 사람의
판단이며, 이번 시연에서 그 판단을 대신한 script 가 대충 했다.

이것은 결함이 아니라 경계다. 다만 기록해 둔다 — 자동화가 대신할 수 없는 지점이 어디인지
분명히 하기 위해서다.

## 10. 남은 위험

1. **AI 재작성이 이전 버전을 보지 못한다**(9.1). P3·P4 범위
2. **자동 완료·미정리 실행 인수는 라이브 미실행**(8.1). 자동 시험으로만 확인
3. `residual_activity` 가 항상 `unknown` — 자식 프로세스 잔류 확인 수단이 없다(P1-03 이월)
4. 안전 중지(다음 호출 차단)를 제품 경로에 연결하지 않았다. capability 보고만 한다
5. 열람 요청에 만료·크기 한도가 없다(P2-02에서 넘어온 위험, 그대로)
6. 결과 후보의 **늦게 도착한 결과 재평가**는 만들지 않았다. 후보가 바뀌면 이전 인수를
   쓰지 않는 것까지만 강제한다(P2-PLAN-04 제외 범위 (사))
7. P2-01~03의 남은 위험(하트비트 만료 미구현, 폴링 배정, 피드백 대상 항목 미구조화,
   httpx deprecation 경고)과 P1에서 넘어온 위험(두 CLI 자동 업데이트, Claude 훅
   fail-open, Codex 훅 신뢰 요구, 프로세스 트리 종료 미구현, 재연결 대조·병렬 호출
   경계 미검증)은 그대로다

## 11. 외부 전송·남은 자원

- **외부 AI 전송이 있었다.** 사용자 계정의 codex 5회·claude 8회, 합계 13회를 실행했다.
  각 CLI의 기존 사용자 설정을 따랐고 시스템은 자격증명을 읽지도 주입하지도 않았다.
  claude 의 보고 비용은 실행마다 결과에 남아 있고, codex 는 토큰만 보고하고 비용은
  `not_reported` 다.
- 남은 제어부·Runner 프로세스 **0개**. 이 세션이 띄운 CLI 자식 프로세스도 0개다
  (`claude` 2개와 `codex` 1개가 이 PC에 떠 있으나 모두 라이브 시작 전부터 있던 것이다).
- 라이브 데이터 `%LOCALAPPDATA%\Temp\hads-p2-04-live` 는 지워도 된다(저장소 밖).
- GitHub 이슈·PR 등 외부 게시는 없다.
