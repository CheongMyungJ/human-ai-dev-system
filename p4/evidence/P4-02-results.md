# P4-02 실행 결과 — 변경·예약

상태: **완료**  
기준: 설계 v0.7 / D-01~67 / 2026-09-22  
계획: [P4-PLAN-02](../../plans/P4-PLAN-02.md)

## 1. 구현 결과

- **검증 1회에 시작과 끝이 생겼다.** `start_quality_gate_run` 이 현재 정책의 리비전·
  검사 강도를 그 실행에 고정하고 `status = 'running'` 으로 열며,
  `complete_quality_gate_run` 이 **시작 당시 고정한 강도로** 판정을 검사해 닫는다.
  즉시 끝나는 규칙 검사는 기존 `record_quality_gate_run` 경로를 그대로 쓴다 — 그때는
  예약할 틈이 없기 때문이다.
- **설정 변경이 갈라진다.** 그 범위에 진행 중 검증이 없으면 즉시 적용되고
  (`apply_boundary = immediate`), 있으면 `pending` 으로 예약된다
  (`verification_end`). 예약 행은 유효 정책 조회에 섞이지 않고 `reserved` 블록으로
  따로 붙는다. 예약만으로는 진행 중 검사가 멈추지도, 그 결과의 `validity` 가 내려가지도
  않는다.
- **범위 겹침을 본다.** Case 전체 변경은 그 게이트의 어느 Task 검증이든 돌고 있으면
  기다리고, Task 범위 변경은 그 Task 의 검증만 기다린다. 넓은 변경이 좁은 검증을 못 본
  척하면 "진행 중 검사는 시작 당시 정책을 유지한다"가 깨진다.
- **종료 순서가 계약이다.** `현재 결과 보존 → 예약 적용 → 효과 재평가` 를 한
  트랜잭션에서 지킨다. 판정이 실패여도 예약을 반영한다 — 게이트 통과만 기다리는
  순환을 만들지 않는다.
- **OFF 의 효과를 좁혔다.** 반영된 OFF 는 그 게이트만을 위한 새 `product_repair` 차수
  배정을 거부한다. `remediation_cycle`·`used_attempts`·발견·실패 판정은 그대로 남고,
  다시 ON 해도 초기화되지 않는다. 환경 복구는 게이트 전용 작업이 아니고 차수를
  소비하지도 않으므로 막지 않는다.
- **`needs_recheck` 를 만드는 것을 하나로 좁혔다.** 검사 강도 변경만 기존 판정을
  내린다. P4-01 은 `setting` 이 바뀌기만 해도 내렸는데, ON/OFF 토글은 이미 끝난 검사가
  무엇을 보았는지 바꾸지 않으므로 같은 테스트를 다시 돌릴 이유가 없다
  (gate-operations 5절). repair 한도도 다음 차수의 허용량이라 마찬가지다.
- **변경 영향을 참조로 계산한다.** `quality_change_event` 가 요청·코드·권한 변경을
  기록하고, 순수 함수 `change_impact` 가 실행마다
  `revalidate | reuse | unknown` 을 정해 `quality_revalidation` 에 남긴다. 재사용도
  이유와 참조 버전(입력 해시)을 적는다. 범위를 확인하지 못하면 `unknown` 이고 그것은
  재검증 대상이다 — 확인하지 못한 것을 "무관하다"로 적지 않는다.
- **진행 중 검증은 무효화 대신 취소를 요청한다.** 판정이 아직 없어 내릴 것이 없다.
  `stop_requested_at` 만 적고 상태는 `running` 그대로다 — 취소 요청과 실제 종료 확인은
  다른 값이다.
- **늦은 결과를 원래 실행에 귀속시킨다.** 취소 요청 뒤, 게이트가 OFF 가 된 뒤, 시작
  리비전이 현재와 다를 때, 같은 대상의 더 새로운 판정이 이미 있을 때가 그 경우다.
  결과·발견은 그대로 저장하되 `validity = historical`·`late_result = 1` 이고,
  `remediation_cycle` 을 만들거나 진행시키지 않으며 현재 정책의 통과로도 쓰이지 않는다.
- **배정 직전에 다시 본다.** 실행 요청이 `expected_gate_policy` 를 적으면 현재 유효
  정책과 대조해 다르면 새 사유 `quality_gate_policy_changed` 로 거부한다. 예약만 있는
  상태는 현재 정책을 바꾸지 않으므로 이 사유가 아니다.
- 스키마 **v14**. 정책에 `requested_at`·`applied_at`·`apply_after_run_id`·
  `apply_boundary`·취소 삼종을, 실행에 `started_policy_revision`·`late_result`·
  취소 요청 삼종을 더하고 새 표 둘을 추가했다.

## 2. 성공 기준 근거

| 성공 기준 | 결과·근거 |
|---|---|
| AC-1 즉시 적용·적용 시각 | `test_a_change_with_no_verification_running_applies_at_once` |
| AC-2 진행 중이면 예약 | `test_a_change_during_a_verification_is_reserved_and_changes_nothing_yet` — 현재 설정·리비전이 그대로다 |
| AC-3 예약이 무효화하지 않음 | 같은 시험. 진행 중 실행이 `running`·`current` 로 남는다 |
| AC-4 요청/예약/적용 시각 분리 | 위 두 시험. 유효 정책에 `requested_at`·`applied_at`·`reserved` 가 각각 있다 |
| AC-5 종료 순서·실패에서도 적용 | `test_the_reservation_lands_when_the_verification_ends_even_on_a_failure` — 실패 판정이 보존된 채 OFF 가 반영된다 |
| AC-6 OFF 뒤 repair 거부·누적 보존 | 같은 시험 4항. `product_repair` 는 409, 환경 복구는 201이고 사용량은 0 그대로 |
| AC-7 토글 재사용 | `test_toggling_a_gate_off_and_on_reuses_the_existing_pass` — 통과가 `current` 로 남는다 |
| AC-8 강도 변경만 재검증 | `test_only_a_stronger_inspection_sends_a_verdict_back_for_recheck` — 한도 변경은 내리지 않는다 |
| AC-9 범위 전파 없음 | `test_a_reservation_does_not_spread_to_other_tasks_or_the_case` |
| AC-10 예약 취소·롤백 없음 | `test_a_reservation_can_be_cancelled_and_an_applied_policy_is_not_rolled_back` — 취소 주체·이유가 남고 적용된 정책은 404 |
| AC-11 요청 변경의 부분 재검증 | `test_a_request_change_only_touches_the_checks_that_used_it` |
| AC-12 코드 변경의 저장소 경계 | `test_a_code_change_leaves_evidence_from_other_repositories_alone` |
| AC-13 `unknown` | `test_an_unknown_scope_is_not_recorded_as_unaffected` |
| AC-14 권한 변경은 별도 제어 | `test_a_permission_change_blocks_the_next_assignment_without_waiting` — 기다리지 않고 반영되며 판정·진행 중 실행을 되돌리지 않는다 |
| AC-15 배정 리비전 불일치 | `test_an_old_assignment_request_does_not_start_after_the_policy_moved`, `test_a_reservation_alone_is_not_an_assignment_refusal` |
| AC-16 늦은 결과 | `test_a_late_result_stays_with_its_own_run_and_starts_nothing` — 수정 주기가 만들어지지 않는다 |
| AC-17 OFF 뒤 도착한 통과 | `test_a_pass_arriving_after_the_gate_went_off_is_not_the_current_pass` |
| AC-18 독립 작업 진행 | `test_an_unaffected_gate_keeps_its_evidence_and_stays_open` |
| AC-19 재시작 복원 | `test_reservations_and_late_results_survive_a_reopened_database` — 파일 DB 를 다시 열어 예약·재검증 기록·늦은 결과 판단을 확인 |
| AC-20 v13→v14 이행 | `test_a_v13_database_gets_an_application_time_and_invents_no_reservation` — 적용 시각만 채우고 예약·취소·재검증을 만들지 않으며 반복 이행이 멱등 |
| AC-21 API·화면 구분 표시 | 새 엔드포인트 6개, `QualityGatesPanel` 의 요청/적용 시각·예약 줄·검사 중·늦은 결과 표시, 프로덕션 빌드 |
| AC-22 기존 경계 유지 | 전체 회귀 451 통과. `enforcement` 네 축과 게시 미강제는 그대로이고 새 기능이 push·PR 권한을 만들지 않는다 |

## 3. 검증

| 검증 | 결과 |
|---|---|
| P4-02 집중 시험 | `pytest tests/test_quality_changes.py` — **20 통과** |
| 이행 집중 시험 | `pytest tests/test_migration.py` — **9 통과**(v13→v14 신규 1건 포함) |
| 전체 제품 시험 | `scripts\run-tests.ps1` — **pytest 451 통과**, 알려진 deprecation warning 2건 |
| P1 문서 계약 | 같은 스크립트 — **unittest 18 통과** |
| 웹 | `web`에서 `npm run build` — TypeScript/Vite 프로덕션 빌드 성공 |
| 재시작 | 파일 DB 재개로 예약·적용 시각·재검증 판정·늦은 결과가 복원되고, 재개한 제어부에서 예약이 정상 반영됨을 확인 |
| 실제 CLI | **수행하지 않았다.** P4-02는 새 AI 출력 계약이나 프롬프트를 만들지 않으므로 확인할 새 계약이 없다. 기존 `quality_gate_review` 계약은 P4-01 결과의 실제 실행이 근거다 |

## 4. 검토 중 발견해 고친 것

- 변경 사건 기록이 **종료된 Case 에도 열려 있었다.** 그대로 두면 닫힌 Case 의 판정이
  나중에 `needs_recheck` 로 바뀌어 종료 기록이 조용히 달라진다. 완료 후 수정은 연결된
  새 Case 이므로(D-33) `guard_open_case` 를 붙이고 시험으로 고정했다.
- `changed_refs_json` 에 **런타임 검사만 있었다.** P4-01 검토에서 고친 것과 같은 자리라
  DB `CHECK` 를 함께 뒀다. 내부 호출이 본문을 밀어 넣을 수 있는 자리를 하나만 남기지
  않는다.
- 시작만으로 이전 통과를 `historical` 로 내리던 초안을 고쳤다. 끝내지 못한 검증 하나가
  유효한 증거를 없애 버린다. 대체는 **종료 시점**에만 한다.

## 5. 남은 경계와 인계

- 이 결과는 **P4-02만** 완료한다. 여섯 Profile 전수는 P4-03, 컨텍스트 고정·재개는
  P4-04, 완료·예외 경로는 P4-05, 지식/QG-08은 P4-06~07, 게시·push·PR은 P5다.
- **강제 축은 늘지 않았다.** `enforcement` 는 여전히 넷이 `enforced` 이고 `publish` 만
  P5 다. P4-02가 더한 것은 그 축들 위의 **시간축**이지 새 축이 아니다.
- 권한 철회의 **기계 자체는 만들지 않았다.** P4-02가 한 것은 권한 변경을 변경 사건으로
  기록해 영향받는 증거만 재검증 대상으로 만들고, 그것이 게이트 예약과 달리 검증 종료를
  기다리지 않으며 기존 판정·외부 효과를 되돌리지 않는다는 경계를 시험으로 고정한 것이다.
  실제 철회·중지 제어의 실증은 P6-03에 남는다.
- 늦은 결과의 판단은 **제어부가 아는 사실**(취소 요청·정책 리비전·게이트 적용·더 새로운
  판정)로만 한다. CLI 가 실제로 언제 멈췄는지는 여전히 P1-03의 `cancel_confirmed =
  unknown` 경계 안에 있다.
- P3의 예산 라이브 경로 C는 이전 사용자 지시대로 스킵 상태이며 P4-02의 미충족이 아니다.
- 시작은 `main`/`eaae2d9`(P4-01 커밋), `origin/main` 과 동일했다. 이 결과는 **사용자
  지시로 커밋·push** 했다. 그 허용은 이 커밋에만 적용되며 다음 변경은 다시 확인받는다.
