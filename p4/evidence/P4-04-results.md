# P4-04 실행 결과 — 문맥·재개

상태: **완료**  
기준: 설계 v0.8 2차 / D-01~90 / 2026-09-23  
계획: [P4-PLAN-04](../../plans/P4-PLAN-04.md)

## 1. 구현 결과

- **계획과 영수증을 나눴다.** `run_context_ref` 는 여전히 "무엇을 주려 했는가"이고, 새
  `run_context_receipt` 가 "무엇을 실제로 읽었는가"다. 둘을 한 표에 두면 계획이 읽음으로
  보인다. Runner 는 CLI 를 부르기 **전에** 지시(순번 0)와 모든 고정 참조를 자기 저장소에서
  읽고 **해시를 대조해** `read`·`missing`·`hash_mismatch`·`omitted` 를 보고한다. 해시가 다른
  본문은 다른 원문이므로 읽은 것으로 다루지 않고 지시문에 넣지 않는다. 영수증에는 순번·
  역할·상태뿐이고 본문도 경로도 없다. 같은 세대의 같은 영수증 재전송은 멱등, 다른 내용·옛
  세대·배정되지 않은 Runner·모르는 순번·**인라인으로 정한 참조의 `omitted` 주장**은 409 다.
- **실행 문맥 상태는 도출한다.** `complete`(전부 읽음)·`partial`(핵심은 전부 읽고 보조 일부를
  생략·누락)·`blocked`(지시 또는 핵심을 못 읽음 — 실행하지 않음)·`not_reported`(영수증 없음,
  P4-04 이전 실행). 계획을 읽음으로 적지 않는다.
- **등급은 역할에서 나온다**(`domain/context.py`). AI 의 이전 제안(`conversation_assistant_
  message`)만 **보조**이고, 요청·결정·명시 금지·동의 범위·사람의 답·피드백·재작성의 이전
  버전·계획은 **핵심**이다. 모르는 역할은 핵심으로 취급한다. 생성 시 참조 행에 등급·인라인
  여부·크기를, 실행에 적용 한도를 기록한다.
- **실행당 인라인 한도**(기본 256 KiB, 상세 설계 제안값, 제어부 환경 변수
  `HADS_CONTEXT_INLINE_LIMIT_BYTES`, 0 이하는 기동 거부). 한도 안이면 참조 목록·순서가 이전과
  같다. 넘으면 **보조만 오래된 것부터** 드러내어 생략하고(`omitted_size_limit`), 지시문에
  "크기 한도 때문에 이 실행에 넣지 않았다"와 참조 id 를 적는다. 지시 + 핵심만으로 넘으면
  **`context_over_inline_limit` 로 보류**한다 — 핵심을 자르지 않는다. 진입 검사·생성·예약이
  **한 계획**(`plan_context_package`)을 쓰고, 예약하는 `context_bytes` 는 인라인 패키지 크기다
  (재배정도 같다).
- **핵심 원문의 서버 가용성.** 인라인 핵심 참조가 `available` 이 아니면(저장 대기·유실·
  Runner 오프라인) `required_context_unavailable` 로 진입을 거부하고 역할·참조·가용성을 적는다.
  입력을 빼고 실행하지 않는다. 보조 참조는 막지 않는다.
- **Runner 사전 중단.** 지시 또는 핵심이 `missing`·`hash_mismatch` 면 CLI 를 부르지 않고(부수
  효과 0) `failed` + 잔류 `none` + `not_started_reason = required_context_unavailable` 로
  보고하며 원장에 확정한다. 보조만 못 읽으면 실행하고 "읽지 못했다"를 적는다(`partial`).
  지시 원문이 Runner 에 없을 때 원장을 잡은 채 `assigned` 로 멈추던 경로도 이 중단으로 끝난다.
- **시작하지 않은 실행은 소비가 아니다.** `not_started_reason` 은 `failed` + 잔류 `none` 에서만
  받는다. 실행 수·검토 수·문맥 크기·실행 시간이 **0 으로 확정**(`settle_source = not_started`)
  되고 토큰·비용 행을 만들지 않는다. 기존 사전 거부 두 경로(`no_execution_path`·
  `workspace_busy`)도 같은 표시를 보낸다. 시작한 실행의 정산은 그대로다.
- **결과 시점의 최신성.** 결과를 기록할 때 "지금 구성하면 들어갈 참조 − 고정한 참조 − 그
  실행이 만든 산출물"을 `run.context_freshness_json` 에 남긴다(`current`/`drifted`, 추가된
  역할·참조, 50개까지 적고 수는 전부 센다). **추가만 본다** — 실행이 피드백을 반영해 해결하면
  그 피드백이 빠지는 것이 정상이다. 진행 중 실행은 조회 시점으로 도출한다(`live`). 최신성은
  표시이며 결과·판정을 바꾸지 않는다.
- **Runner 재시작의 사용량 복구.** 원장에 착수만 있는 실행을 다시 받으면 CLI 를 다시 부르지
  않고 원시 출력(`raw/{run_id}.stdout.jsonl`)을 배정의 도구 규칙으로 정규화해 **사용량·세션
  식별자·이벤트**를 되찾아 `unknown` 으로 보고한다. 사용량에 `recovered_from = runner_raw_log`
  가 붙고 토큰·비용은 `settle_source = recovered_from_runner_log` 로 확정된다. 실행 시간은
  여전히 `unresolved`. 원시 출력에 사용량이 없거나 원시 출력이 없으면 이전처럼 미제공이다.
  복구한 결과는 원장에 확정해 원시 출력이 지워져도 같은 값을 다시 보낸다.
- **영수증은 원장보다 먼저다**(plan 10절). 영수증 보고가 유실되면 아무 것도 잡지 않은 채
  올라가 다음 배정에 다시 읽는다. 원장을 먼저 잡으면 CLI 를 부르지도 않은 실행이 다음
  재배정에서 결과 불명으로 보고된다.
- **조회·화면.** `GET /api/runs/{id}`·Case 실행 목록에 `context`(상태·한도·인라인 크기·생략·
  못 읽음·`not_started_reason`·최신성), `GET /api/runs/{id}/context-refs` 에 참조별 적용
  등급·인라인·크기·서버 가용성·영수증 상태·`*_recorded`. 관리 화면 실행 표에 **문맥** 열과
  두 거부 사유 문구, 문맥 역할 표지를 더했다. 새 화면은 만들지 않았다.
- 스키마 **v17**: 새 표 하나(`run_context_receipt`)와 컬럼 여섯(`run_context_ref.tier`·
  `inclusion`·`byte_size`, `run.context_inline_limit`·`not_started_reason`·
  `context_freshness_json`). 값은 `CHECK`, 최신성 JSON ≤20000. 본문 없음.

## 2. 성공 기준 근거

시험은 `tests/test_context.py`(24)와 표시한 기존 파일이다.

| 기준 | 근거 |
|---|---|
| AC-1 등급·기록 | `test_tiers_come_from_the_role_and_unknown_roles_are_core`, `test_a_run_records_its_plan_and_what_the_runner_actually_read`(등급·인라인·크기·`*_recorded`, 실행의 적용 한도) |
| AC-2 보조만 생략 | `test_the_inline_plan_drops_only_old_supporting_items_and_holds_when_core_overflows`, `test_a_long_conversation_omits_only_old_ai_messages`(오래된 AI 말만 `omitted_size_limit`, 지시문 표시·참조 id, 생략 본문 없음, 사용자 금지 포함) |
| AC-3 핵심 초과 보류 | `test_core_input_over_the_limit_holds_the_run_instead_of_cutting_it`(409 `context_over_inline_limit`, 사유의 크기·한도·조정 안내, 실행·예약 없음, 한도 조정 뒤 열림) |
| AC-4 예약 = 인라인 패키지 | 위 두 API 시험의 `context_bytes` 예약값 = `inline_bytes`, 재시작 시험·라이브 C |
| AC-5 핵심 가용성 | `test_a_core_input_that_is_not_stored_holds_the_run`(저장 대기 피드백 409·사유, 저장 뒤 허용, 유실 피드백 409 `lost_before_persist`) |
| AC-6 영수증 | `test_a_receipt_must_match_the_plan`, `test_the_receipt_endpoint_is_idempotent_and_refuses_what_does_not_match`(옛 세대·인라인 `omitted` 주장·순번 누락·다른 Runner 409, 재전송 200, 다른 내용 409, 표에 본문·경로 컬럼 없음), `test_a_lost_receipt_report_claims_nothing_and_the_run_is_not_reported_unknown` |
| AC-7 핵심 미확인 → 실행 전 중단 | `test_a_missing_core_input_stops_the_run_before_the_cli_and_costs_nothing`(요청 원문이 다른 내용으로 복원된 QG-01 검토: CLI 호출 0, `failed`·`none`·`required_context_unavailable`, `blocked`, 게이트 통과 없음, 원장 확정), `test_a_missing_instruction_is_a_not_started_failure_not_a_stuck_run` |
| AC-8 보조 누락 → 부분 | `test_a_missing_ai_message_runs_marked_unread_and_partial`. **기존 시험 의미 변경**: `test_preparation.py::test_an_unreadable_reference_is_reported_as_unread`(3절) |
| AC-9 시작하지 않은 실행 | 위 AC-7 시험(네 지표 0·`not_started`·토큰 행 없음), `test_not_started_is_accepted_only_for_a_failed_run_with_nothing_left`, `test_a_started_run_still_settles_as_before` |
| AC-10 문맥 상태 | `test_the_run_context_state_distinguishes_four_cases` 와 API 시험들의 `context.state` |
| AC-11 최신성 | `test_drift_counts_only_inputs_the_run_did_not_see`(추가만·자기 산출물 제외·목록 상한), `test_freshness_records_inputs_that_arrived_after_the_run_fixed_its_context`(진행 중 `live` drift → 결과 시점 `at_result` 기록, 자기 의도 버전 제외, 결과 `completed` 유지) |
| AC-12 재시작 사용량 복구 | `test_a_restarted_runner_recovers_usage_from_the_real_codex_raw_log`(실제 codex 원시 출력: CLI 재호출 0, `unknown`, 세션 id·이벤트, 토큰 32305/62 `recovered_from_runner_log`, 시간 `unresolved`, 원장 확정), `test_a_killed_run_log_without_usage_stays_not_reported`(실제 강제 종료 로그·로그 없음), `test_the_claude_raw_log_is_recovered_with_its_own_rules`, 라이브 D |
| AC-13 새 세션 보존 | `test_a_new_session_after_an_unknown_run_resets_nothing`(불명 실행 뒤 새 실행의 핵심 참조 동일, Profile·정의판 2·기준 의무/결론 요구·미해결 질문·repair 1회·복구 토큰 포함 누적 예산 유지) |
| AC-14 부분 복원 | `test_partial_restore_blocks_only_runs_that_depend_on_the_missing_original`, AC-7 시험(다른 내용으로 돌아온 원문) |
| AC-15 대화 문맥 | `test_a_long_conversation_omits_only_old_ai_messages`(논의 응답·업무화 뒤 의도 작성), 기존 `test_conversation.py::test_runs_receive_the_conversation_as_fixed_context_with_roles`·`test_a_case_without_a_conversation_keeps_its_old_context` 통과, 라이브 C |
| AC-16 조회·화면 | API 시험들의 `context`·참조 필드, `npm run build` 성공 |
| AC-17 이행 | `test_migration.py::test_a_v16_database_gets_no_receipt_or_freshness_it_never_had`(커밋된 v16 스키마 DB: 새 컬럼 NULL, 영수증 0행, `not_reported`, 등급 도출·`tier_recorded=False`, CHECK 넷, 반복 이행 멱등) |
| AC-18 강제 종료 재시작 | `test_restart_recovery.py::test_context_plans_receipts_and_recovered_usage_survive_a_forced_kill` — 실제 uvicorn(`HADS_CONTEXT_INLINE_LIMIT_BYTES=1000`)을 `taskkill /F /T` 로 죽인 뒤 한도·등급·인라인·영수증·상태·`not_started`·최신성·복구 정산 출처가 같다 |
| AC-19 실제 CLI | 3절 — 실제 `codex-cli 0.154.0`, 제품 규칙 21건 통과, 지시와 다른 관찰 없음 |
| AC-20 경계 | `test_enforcement_axes_are_unchanged`, `test_p404_records_keep_no_bodies`, 기존 데이터 경계 시험 통과 |

## 3. 검증

### 자동 시험

- 기준선(이 세션 시작, 변경 전): `scripts\run-tests.ps1` → pytest **513**, P1 계약 unittest
  **18** 통과(4분 26초).
- 최종: `scripts\run-tests.ps1` → pytest **539**, P1 계약 unittest **18** 통과. 새 시험
  26건(`test_context.py` 24, v16→v17 이행 1, 강제 종료 재시작 1). 알려진 deprecation warning
  2건 외 실패 없음.
- 웹: `npm run build` 성공.
- **기존 시험 두 건의 의미를 검토해 고쳤다. 검사를 지우지 않았다.**
  - `test_preparation.py::test_an_unreadable_reference_is_reported_as_unread`(P3-01 AC-12)는
    동의된 의도 원문이 Runner 에 없을 때 "읽지 못했다"를 지시문에 적고 **설계를 쓰는 것**을
    고정했다. 동의된 의도는 핵심 입력이다 — 그것 없이 쓴 설계가 성공 산출물로 남는다. 원래
    뜻("읽지 못한 것을 읽음으로 적지 않는다")은 유지하고 더 강하게 바꿨다: CLI 호출 없음,
    `not_started_reason`, `blocked`, 영수증의 `agreed_intent = missing`, 설계 산출물 없음.
    보조 누락의 "읽지 못함 표시 후 실행"은 새 시험이 맡는다.
  - `test_migration.py::test_a_v15_database_gets_no_conversation_it_never_had` 가
    `SCHEMA_VERSION == 16` 을 고정했다. 뜻은 "현재 판으로 이행"이므로 `>= 16` 으로 바꾸고 v17
    고정은 새 이행 시험이 맡는다(UI-01 이 v14 시험에 한 것과 같은 판단).
- **실제 CLI 원시 출력을 자동 시험 입력으로 썼다.** P1 증거로 커밋된 실제 출력
  (`p1/evidence/codex-read-v2-347eb670.stdout.jsonl`·`claude-read-v2-5f612ab5.stdout.jsonl`·
  실제 강제 종료 `p103-kill-d435ff68.stdout.jsonl`)을 Runner 원시 출력 자리에 두었다. 충돌
  지점(원장 착수 기록)은 시험이 만든다.

### 실제 CLI (AC-19)

`p4/live/p4_04_context.py` 로 실제 `codex-cli 0.154.0` 을 불렀다. 합성 저장소 하나, 대화
하나. 라이브 데이터는 `%LOCALAPPDATA%\Temp\hads-p4-04-live\<tag>` 이고 저장소 `var\` 는
건드리지 않았다. 증거 사본은 `p4/evidence/P4-04-live*` 다(2회차 `163738630`).

| 단계 | 제품 규칙(멈춤) | AI 관찰(기록) |
|---|---|---|
| A·B. 문맥 쌓기(기본 한도) — "제안을 번호로 세 가지, 아직 코드·문서 수정하지 마세요" → "가장 작은 변경은?" | `completed`, AI 메시지 1건, 문맥 `complete` | 저장소 같음. A 는 1. 캐시 제거 2. `save()` 뒤 무효화 3. 파일 변경 감지를 제안, B 는 "가장 작은 변경은 2번" |
| C. **A 의 AI 응답만 생략되는 한도**(1029 B; A 1619 B·B 457 B)로 "첫 번째 답의 세 가지를 번호대로 요약, 내가 무엇을 하지 말라고 했는지 확인" | 제어부를 새 한도로 재기동, 참조가 정확히 `[user inline read, assistant omitted_size_limit omitted, user inline read, assistant inline read]`, 생략된 것이 A, 문맥 `partial`, 기록된 한도 = 설정, 예약 1013 = 인라인 1013 ≤ 1029 | **"첫 번째 답변은 현재 컨텍스트에서 생략되어 있어 세 가지를 정확히 복원할 수 없습니다"**, 1·3번은 "확인 불가 — 첫 번째 답변이 필요합니다", 2번은 **보이는 B 응답("2번")에서** 복원. 사용자 금지를 원문 그대로 인용하고 "이번에도 아무것도 변경하지 않았습니다". 저장소 같음 |
| D. 실행 중 강제 종료 — CLI 가 원시 출력에 `thread.started` 를 쓰는 즉시 Runner 트리(`taskkill /F /T`, 프로세스 5개)를 죽이고 재기동·재배정 | 종료 뒤 `assigned`(결과 없음), 이 실행의 CLI 호출 기록 1회 그대로(재호출 없음), `unknown`, **세션 id 가 원시 출력의 `thread_id` 와 같다**, 원시 출력(9줄)에 사용량이 없어 토큰 `None`·`outcome_unknown`, 실행 시간 `unresolved`, 요청 종료 기록 → `unknown`(잠금 유지) | — |

**2회 실행했다.** 1회차는 A~C 가 같은 모양으로 통과했고(C 응답도 "첫 번째 답변은 현재
컨텍스트에서 생략되어 세 가지를 정확히 재현할 수 없습니다", 2번만 B 에서 복원) D 에서 **하네스
타이밍**으로 멈췄다 — `thread.started` 를 본 뒤 2초를 기다리는 사이 짧은 응답이 끝나 결과가
먼저 보고됐다. 제품 규칙 위반이 아니다. 하네스를 "보는 즉시 종료, 그래도 먼저 끝나면 새
메시지로 재시도(최대 3회)"로 고쳤고 2회차는 첫 시도에 실행 중 종료가 됐다. 위 증거는
2회차다. **표본은 대화 하나·강제 종료 하나다.** D 의 원시 출력은 사용량 없는 경로만 보였고,
사용량이 있는 원시 출력의 복구는 자동 시험(실제 P1 원시 출력)이 본다.

## 4. 구현 중 찾은 것

- **영수증이 원장 뒤에 있으면 없던 호출이 불명으로 남는다.** 처음 구현은 원장을 잡은 뒤
  영수증을 보냈다. 영수증 보고가 네트워크에서 실패하면 CLI 를 부르지도 않았는데 원장에는
  착수가 있고, 다음 재배정이 그 실행을 결과 불명으로 보고한다. 읽기·영수증을 원장 앞으로
  옮기고 원장에 이미 있는 실행(재전송)은 다시 읽지 않게 했다. 시험으로 고정했다.
- **지시 원문이 Runner 에 없으면 실행이 멈춘 채 남았다.** 기존 경로는 원장을 잡은 뒤
  `store.get` 이 예외를 던져 실행이 `assigned` 로 남았다. 이제 영수증의 지시 `missing` 으로
  시작하지 않은 실패가 된다.
- **재배정은 원장이 재실행을 막아도 새 세대 예약을 잡는다**(P3-R3 규칙). 되찾은 사용량은 새
  세대 행에 확정되고 이전 세대 예약은 `held` 로 남는다 — 과대 쪽이다. P4-04 는 바꾸지 않았고
  DEVELOPMENT.md 9절에 배정했다.
- **시험 도우미의 함정.** `submit_artifact` 는 대기 중인 원문을 전부 저장하므로, 저장 대기
  피드백을 만든 뒤 지시를 접수하면 피드백도 저장된다. 시험은 지시를 먼저 접수한다.

## 5. 경계와 남은 것

- **강제 축은 넷 그대로다.** `enforcement` 에서 `autonomy`·`controlled_checkpoint`·
  `budget`·`repository_selection` 이 `enforced`, `publish` 만 P5 다. 영수증·한도·최신성이
  권한·동의·위임을 새로 만들지 않는다.
- **넣지 않은 것**(P4-PLAN-04 2절·3.9절): 분할 검토(하위 + 통합)·검토 체크포인트, 생략 자료의
  단계적 조회, 요청 `unknown` 해제·중단·Runner 수신/실행 분리(UI-02), CLI 세션 이어가기
  (`resume` 은 `doc_only`), 지식 Manifest(P4-06), 원문 재동기화·백업 복원(P6-04), 새 기본
  화면(UI-03).
- 남은 한계는 [DEVELOPMENT.md](../../DEVELOPMENT.md) 9절 표에 배정했다.
