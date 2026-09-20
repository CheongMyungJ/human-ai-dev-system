# P2-02 의도·피드백 — 실행 결과

수행일: 2026-09-20. 계획: [`P2-PLAN-02`](../../plans/P2-PLAN-02.md).

이 문서는 **실제로 실행한 것만** 적는다. 자동 시험 통과와 실제 프로세스·브라우저 실행을
구분하고, 검증하지 않은 항목은 7절에 미검증으로 남긴다.

## 1. 실행 환경

| 항목 | 값 | 확인 방법 |
|---|---|---|
| OS | Windows 11 Home 10.0.26200 | P2-01과 동일 |
| 셸 | PowerShell 7 | 〃 |
| Python(고정) | 3.12.10 — 저장소 로컬 `.venv` | `.venv\Scripts\python.exe --version` |
| Node / npm | v22.15.1 / 10.9.2 | `npm run build` 출력 |
| 브라우저(검증용) | Microsoft Edge (설치본, headless) | Playwright `channel="msedge"` |
| 제어부 스키마 | **v2** | `GET /api/health` → `"schema_version":2` |

검증용 Playwright는 **저장소 밖 임시 가상환경**(`%LOCALAPPDATA%\Temp\hads-playwright`)에
설치했다. 제품 의존성이 아니며 `requirements.txt` 에 없다. 같은 확인을 사람이 직접
브라우저에서 클릭해 재현할 수 있다. 사용자 전역 설정은 바꾸지 않았다.

라이브 실행 데이터는 `%LOCALAPPDATA%\Temp\hads-p2-02-live` 에 두었고 저장소 `var\` 를
건드리지 않았다.

## 2. 만든 것

| 구성 | 파일 | 역할 |
|---|---|---|
| 정규 의도 문서 | `domain/intent_doc.py` (신규) | 여섯 항목 문서 형식, 구조 추출, 항목 단위 차이 |
| 상태값 | `domain/models.py` | 확인 상태·내용의 성격·결정 시점·피드백 상태·열람 상태·동의 상태·거절 사유 |
| 제어부 스키마 v2 | `controller/schema.sql`, `db.py` | `intent_field` `intent_question` `feedback` `intent_view` `artifact_read_request` + `decision.subject_content_hash` |
| 제어부 | `repository.py`, `api.py`, `app.py` | 의도 구조·질문·피드백·열람 중계·명시 동의 |
| Runner | `agent.py`, `client.py` | 의도 원문 저장 후 구조 보고, 열람 요청 응답 |
| 화면 | `web/src/IntentPanel.tsx` (신규), `api.ts`, `App.tsx`, `styles.css` | 초안 작성·원문 열람·피드백·질문 답변·명시 동의 |
| 시험 | `tests/test_intent.py`·`test_migration.py` (신규) 외 4개 파일 | 19 → **39건** |

**이번 초안은 사람이 쓴다.** `domain/intent_doc.py` 가 만드는 문서에는
`"authoring_note": "P2-02: 사람이 입력한 초안이다. AI 작성자 연결은 P2-03 이후다."` 가
그대로 들어가고 화면에도 같은 문구를 표시한다. AI가 초안을 작성한 것으로 적지 않는다.

### 누가 본문을 다루는가

```
브라우저 ──여섯 항목──▶ 제어부(compose, 메모리) ──▶ Runner(영속 저장)
                                                      │
                                              구조·차이 계산(parse)
                                                      ▼
                          제어부 ◀── 항목 상태·질문 요약만 (본문 없음)

브라우저 ◀── 한 번 전달 ── 제어부(메모리 버퍼) ◀── 본문 ── Runner   (열람)
```

제어부는 `compose()` 만 부르고 `parse()`·`structure()` 는 부르지 않는다.
`tests/test_data_boundary.py::test_the_controller_never_parses_the_intent_document` 가
이것을 관측 가능한 형태로 고정한다 — Runner가 보고하기 전에는 항목 상태가 비어 있다.

## 3. 자동 시험

```
scripts\run-tests.ps1
  → pytest 39 passed
  → P1 OpenCode 문서 계약 unittest: Ran 18 tests, OK
```

P1 계약 시험 18건은 CLI를 실행하지 않는 **문서 계약 시험**이며 OpenCode 실환경 검증이 아니다.

P2-02가 더한 시험(19 → 39):

| 파일 | 건수 | 대상 |
|---|---|---|
| `tests/test_intent.py` | 13 | 여섯 항목·출처·열람·피드백·질문·동의와 거절 5조건 |
| `tests/test_flow.py` | +1 | 일반 결정 경로로 의도 동의를 만들 수 없음 |
| `tests/test_data_boundary.py` | +3 | 의도·피드백·답변·열람 본문 비보관, 새 표의 본문 컬럼 없음, 제어부가 본문을 해석하지 않음 |
| `tests/test_restart_recovery.py` | +1 | 강제 종료 후 의도·구조·질문·피드백·동의 복원과 열람 요청 만료 |
| `tests/test_migration.py` | 1 | 커밋된 v1 스키마로 만든 DB가 기록을 잃지 않고 v2로 올라감 |

**시험이 설계를 고친 경우가 두 번 있다.** 둘 다 시험이 아니라 코드를 고쳤다.
[`P2-PLAN-02` 수정 기록](../../plans/P2-PLAN-02.md#수정-기록-2026-09-20-구현-중)에 근거가 있다.

1. 데이터 경계 시험이 **질문 본문이 제어부 DB에 남는 것**을 잡았다. Runner가 질문 본문
   앞부분을 잘라 요약으로 올리고 있었다. 요약은 작성자가 따로 쓰게 바꿨다.
2. 구현 검토 중 **동의 기록이 원문을 한 번도 받지 않고도 가능**하다는 것을 확인했다.
   해시는 상태 조회로도 알 수 있기 때문이다. 열람 기록을 전달 시점에만 만들도록 바꾸고
   동의의 선행 조건으로 넣었다(거절 사유 `original_not_read`).

## 4. 실제 프로세스 실행 (TestClient 아님)

실제 uvicorn 제어부와 별도 프로세스 Runner를 띄우고 진짜 HTTP로 한 바퀴 돌렸다.
전문은 [`P2-02-live-api.log`](P2-02-live-api.log).

```
[3] AC-1 여섯 항목 {"goal": "proposed/user_requirement", "expected_outcome": "proposed/ai_proposal",
     "scope": "proposed/user_requirement", "exclusions": "undecided/none",
     "constraints": "undecided/none", "open_questions": "undecided/none"}
[4] AC-7 명시 표시 없음            400 not_explicit
[5] AC-7 원문이 바뀜               409 content_changed
[6] AC-7 의도 단계 질문 미해결     409 open_intent_questions
[7] AC-2 열람 요청                 state=pending
[8] AC-2 원문 수령                 state=delivered bytes=1487
[9] AC-2 재수령 불가               content=None state=delivered
[10] AC-4 열람+피드백+답변 후 동의 상태  never_agreed
[11] AC-5 명시 동의                201 hash=sha256:0354cad9011903ae…
[12] AC-3 버전 차이 {"compared_with": 1, "changed": ["exclusions"],
      "q_removed": ["row-scope"], "full_text_diff": "not_on_controller"}
[13] AC-6 v2 생성 후 동의 상태     stale_agreement (동의한 버전 v1)
[14] AC-6 옛 버전 재동의 거절      409 not_latest_version
```

### 4-1. 브라우저 (설치된 Edge)

전문은 [`P2-02-ui-driven.log`](P2-02-ui-driven.log), 화면은
[초안](P2-02-ui-draft.png) · [원문 열람](P2-02-ui-original.png) · [동의 후](P2-02-ui-agreed.png).

```
[b1] Case 를 화면에서 만들고 열었다
[b2] 초안 제출 후 동의 상태 = 동의 없음
[b3] 여섯 항목 표에 미정/제안됨과 내용의 성격이 보인다
[b4] 원문을 읽기 전 동의 버튼이 잠겨 있다
[b5] 원문 본문이 화면에 표시됐다 (제어부는 메모리 중계만)
[b6] 명시 동의 후 동의 상태 = 최신 버전에 동의함
```

### 4-2. Runner 오프라인 중 열람

Runner 프로세스만 멈추고 같은 원문을 요청했다([`P2-02-live-offline.log`](P2-02-live-offline.log)).

```
열람 요청 상태: pending
본문: null (전달되지 않음)
원문 참조 availability: available   해시: sha256:e58b16cd…
```

원문이 사라진 것이 아니라 소유 Runner에 닿지 못하는 상태다. 빈 문서나 삭제로 표시하지 않는다.

### 4-3. 데이터 경계 — 파일 바이트 확인

라이브 실행에서 표식 문자열을 의도 본문·질문 본문·피드백 본문·답변 본문에 넣고 열람까지
수행한 뒤 파일을 직접 읽었다([`P2-02-live-boundary.log`](P2-02-live-boundary.log)).

```
== 제어부 ==
  controller.log                23,116 bytes  표식=없음
  controller.sqlite3             4,096 bytes  표식=없음
  controller.sqlite3-shm        32,768 bytes  표식=없음
  controller.sqlite3-wal     1,116,552 bytes  표식=없음
== Runner ==
  표식 있음: runner\artifacts\art-…\1.bin  (4개 파일)

제어부에서 읽지 못한 파일: 없음
```

"읽지 못한 파일: 없음"을 함께 적는 이유는, 열려 있어 읽지 못한 파일을 '표식 없음'으로
보고하면 확인이 성립하지 않기 때문이다. 첫 시도에서 실제로 그 일이 있었고 공유 읽기로 고쳤다.
Runner에도 표식이 없으면 애초에 저장되지 않은 것이므로 경계 확인이 무의미하다 — 그래서
"제어부에 없음"과 "Runner에 있음"을 함께 확인한다.

## 5. 성공 기준별 결과

| 기준 | 결과 | 근거 |
|---|---|---|
| AC-1 여섯 항목·미정 유지·출처 구별 | **통과** | 라이브 `[3]`, `test_all_six_fields_exist_and_missing_information_stays_undecided`, `test_content_with_no_origin_is_refused` |
| AC-2 화면에서 원문 열람, 닿지 못하면 연결 필요 | **통과** | 브라우저 `[b5]`, 라이브 `[7][8][9]`, 4-2절, `test_original_is_readable_through_the_temporary_relay`, `test_original_stays_pending_while_the_runner_does_not_answer` |
| AC-3 피드백 반영과 항목 단위 차이 | **통과** | 라이브 `[12]`, `test_feedback_creates_a_new_version_with_a_field_level_diff` |
| AC-4 조회·피드백·답변·무응답은 동의가 아님 | **통과** | 라이브 `[10]`, `test_viewing_feedback_and_answering_do_not_create_agreement` |
| AC-5 명시 동의에 버전·해시·행위자 기록 | **통과** | 라이브 `[11]`, 브라우저 `[b6]`, `test_explicit_agreement_records_the_version_and_the_content_hash` |
| AC-6 오래된 동의가 최신 버전에 적용되지 않음 | **통과** | 라이브 `[13][14]`, `test_old_agreement_does_not_carry_to_a_newer_version` |
| AC-7 동의 거절 **5조건**을 구별 | **통과** | 라이브 `[4][5][6]`, `test_agreement_waits_when_the_original_cannot_be_read`, `test_agreement_is_refused_when_the_read_content_no_longer_matches`, `test_open_intent_stage_question_blocks_agreement_but_deferred_one_does_not`, `test_knowing_the_hash_is_not_reading_the_original` |
| AC-8 작은 기능도 흐름을 거침 | **통과** | `test_a_small_feature_still_goes_through_the_whole_flow` |
| AC-9 본문 비보관 | **통과** | 4-3절(라이브 바이트), `test_intent_feedback_answer_and_read_bodies_never_persist_on_the_controller`, `test_new_p2_02_tables_have_no_body_columns` |
| AC-10 강제 종료 후 복원·열람 요청 만료 | **통과** | `test_intent_agreement_and_structure_survive_a_forced_kill` (실제 uvicorn 자식 프로세스를 `taskkill /F /T` 로 죽인다) |

계획은 AC-7의 거절 조건을 네 가지로 잡았으나 구현 중 다섯 번째(`original_not_read`)를
더했다. 근거는 [plan 수정 기록](../../plans/P2-PLAN-02.md#수정-기록-2026-09-20-구현-중)에 있다.

## 6. 동의를 기록할 수 없는 다섯 조건

검사 순서와 이유다. **이것은 FR-29 진입 조건 검사가 아니다.** 실행 배정을 여는 조건은
P2-03에서 따로 만든다. 여기서 막히는 것은 "사람의 동의를 기록하는 일"뿐이다.

| 순서 | 사유 | 뜻 |
|---|---|---|
| 1 | `not_explicit` (400) | `agree` 표시와 사람이 쓴 문구가 없다. 무응답·조회·질문 답변과 같은 취급 |
| 2 | `not_latest_version` (409) | 최신이 아닌 버전에 새로 동의하게 두지 않는다 |
| 3 | `original_not_available` (409) | 지금 원문을 확인할 수 없다. 과거의 유효한 동의는 이 이유로 폐기하지 않는다 |
| 4 | `content_changed` (409) | 읽은 원문과 현재 원문이 다르다. 이전 확인으로 진행하지 않는다 |
| 5 | `open_intent_questions` (409) | 의도 단계 질문이 남았다. **이월한 설계·계획 질문은 막지 않는다** |
| 6 | `original_not_read` (409) | 이 사람에게 이 원문이 전달된 기록이 없다. 요약만 보고 동의하지 않는다 |

의도 동의를 만드는 경로는 하나뿐이다. 일반 결정 경로
`POST /api/cases/{id}/decisions` 는 `intent_agreement` 를 409로 거절한다 —
화면에서 버튼을 없애는 것만으로는 API 직접 호출을 막지 못하기 때문이다.
미정 질문이 있어도 **열람과 피드백은 항상 열려 있다**(FR-03 수용 기준).

## 7. 검증하지 않은 것 / 남은 제약

미검증을 통과로 적지 않기 위해 여기 남긴다.

1. **AI가 의도 초안을 작성하는 흐름은 없다. 따라서 FR-03의 역할 분리는 미검증이다.**
   이번 초안은 사람이 화면에서 입력한다. 코딩 CLI 연결이 P2-03이기 때문이며 계획의
   제외 범위 그대로다. 다만 이 제한의 무게를 정확히 적어 둔다 — FR-03이 요구하는 것은
   여섯 항목이 기록된다는 사실이 아니라 **AI가 초안을 작성해 제시하고 사람은 피드백과
   동의를 한다는 역할 분리**다. 지금은 검토할 사람이 초안도 쓰므로 그 분리가 성립하지
   않는다. **5절에서 통과로 적은 것은 동의 규율**(버전 고정, 조회·피드백·질문 답변이
   동의가 아님, 오래된 동의 무효, 거절 5조건)이며 역할 분리가 아니다.
   P2-03 이월 항목으로 [DEVELOPMENT.md 6절](../../DEVELOPMENT.md)에 기록했다.
2. **FR-29 진입 조건 검사는 없다.** 동의가 실행 배정을 여는지는 검사하지 않는다(P2-03).
   지금은 동의와 무관하게 Run을 만들 수 있다 — 임시 통과 처리를 넣어 두지 않았다.
3. **QG-01 의도 게이트의 검토 준비 평가**는 구현하지 않았다(P2-03).
4. 열람은 **한 사용자·로컬 루프백** 환경에서만 확인했다. 인증·LAN/VPN 암호화는 P6-01이다.
   메모리 중계가 "서버로 전송되지 않음"을 뜻하지 않는다는 설명은 그대로 유지한다.
   운영체제 메모리 덤프 등까지 포함한 보장 범위는 확인하지 않았다.
5. 열람 요청에 **만료 시간이 없다.** 아무도 받아 가지 않은 `relayed` 본문은 제어부가
   재시작하거나 누가 받아 갈 때까지 메모리에 남는다. 크기 한도도 없다.
6. **질문의 `blocks`(의존 작업)는 기록만 한다.** 작업 그래프가 없어 차단을 강제하지
   않는다. 실제 차단은 P3-02다.
7. 피드백이 **어느 항목을 겨냥했는지**는 구조화하지 않았다. 대상 의도 버전까지만 연결한다.
8. 버전 차이는 **항목 단위**다. 전체 본문 차이는 두 버전 원문을 각각 열람해 사람이 비교한다.
9. 규모 시험(프로젝트 10개·Runner 3대) 미수행. P2-01의 남은 위험
   (하트비트 만료 미구현, 폴링 배정, `bump_generation` 이 정지 증거가 아님)은 그대로다.
10. P1에서 넘어온 미검증 항목(재연결 대조, 병렬 호출 경계, 훅 적용 공백, 훅 timeout,
    프로세스 트리 종료, 훅 신뢰 영속화)은 **그대로 남아 있다.**

## 8. 재현 방법

```powershell
scripts\bootstrap.ps1        # .venv · 의존성 · web 빌드
scripts\run-tests.ps1        # pytest 39 + P1 계약 unittest 18
scripts\run-controller.ps1   # 별도 창
scripts\run-runner.ps1       # 또 다른 창
# 브라우저에서 http://127.0.0.1:8765 → 프로젝트·Case(기능 개발) 생성 →
# 의도 화면에서 초안 작성 → 원문 받아 보기 → 동의
```

화면 절차는 [README 의도 흐름](../../README.md)에 있다.
