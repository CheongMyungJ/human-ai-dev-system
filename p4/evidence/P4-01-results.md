# P4-01 실행 결과 — 게이트·repair

상태: **완료**  
기준: 설계 v0.7 / D-01~67 / 2026-09-22  
계획: [P4-PLAN-01](../../plans/P4-PLAN-01.md)

## 1. 구현 결과

- QG-01~07을 하나의 유효 정책 조회로 제공한다. QG-01은 기존
  `gate_result`·`conformance_check`를 연결해 보여 주며 복제하거나 소급 변경하지 않는다.
  QG-02~07은 Profile·WorkDepth·Task 종류·저장소 수·위험에서 추천을 도출한다.
- 적용은 `required | on | off | not_applicable`, 검사는
  `rule | light | independent`, 실행·판정·유효성은 별도 값이다. Task 명시 설정이 Case
  설정보다 우선하고, QG-01 OFF와 검사 강도 하향은 거부된다.
- 일반 게이트 실행은 입력 해시와 요청/기준/증거 **참조**를 고정한다. 판정은 발견에서
  계산한다. 독립 검토는 reviewer 역할의 `quality_gate_review` 실행, 작성자와 다른 세션,
  증거 참조를 요구한다. 기존 기준에 연결되지 않은 AI 의견은 필수 위반이 아니라
  advisory로 보존한다.
- 명시 ON인 QG-02/03/04는 관련 설계·계획·구현·검증 진입의 실제 조건이다. 추천 정책이
  이미 기존 준비/작업 그래프 검사로 강제되는 경우에는 중복 거부를 만들지 않는다.
- 최초 실패가 `used_attempts = 0`인 `remediation_cycle`을 만들고, 제품 repair를 시작할 때
  원자적으로 차수를 예약한다. 기본 한도는 2다. 환경 복구는 차수를 소비하지 않고,
  Task 재분할·세션 교체·게이트 OFF/ON으로 주기나 사용량이 초기화되지 않는다. 한도 상향은
  정책 리비전으로 남고 이미 쓴 차수를 보존한다.
- 스키마 v13에 정책·실행·발견·repair 주기·시도 표를 추가했다. 원문/코드/diff/log 본문
  컬럼은 없으며 참조 길이·한 줄·목록 크기와 요약 길이를 제한한다. API와 Case 화면은
  적용·검사·판정·유효성·repair 사용/한도/출처를 분리해 표시한다.

## 2. 성공 기준 근거

| 성공 기준 | 결과·근거 |
|---|---|
| AC-1~7 정책·상태 | `domain/quality.py`, 정책 API와 `tests/test_quality_gates.py`의 7개 게이트·QG-01 보호·Task 우선·상태 분리·명시 게이트 진입 시험으로 확인 |
| AC-8~10 의미 검토 | 별도 reviewer 목적/권한/프롬프트, 다른 세션·참조 요구, 새 필수 요구 방지 시험과 실제 CLI 출력 계약으로 확인 |
| AC-11~15 repair | 최초 실패 0회, 1→2→세 번째 거부, 한도 3 상향, 환경 복구 비소비, 토글·Task·세션 불변 시험으로 확인 |
| AC-16 재시작 | 파일 DB를 다시 열어 정책·실패·repair 1회가 복원되고 다음 상태가 같은지 확인 |
| AC-17 이행 | 커밋된 v12 스키마 DB를 v13으로 두 번 열어 기존 QG-01 실패를 보존하고 일반 통과·repair 행을 만들지 않음을 확인 |
| AC-18 화면/API | Case 상세와 전용 API, 웹 게이트·repair 표의 타입 검사 및 프로덕션 빌드로 확인 |
| AC-19 기존 경계 | 전체 회귀에서 P3 네 강제 축과 게시 미강제 계약 유지. 새 게이트가 push·PR 권한을 만들지 않음 |
| AC-20 데이터 경계 | 새 다섯 표의 컬럼/제약 검사와 본문형 목록 참조·발견 증거 참조 거부 시험으로 확인 |

## 3. 검증

| 검증 | 결과 |
|---|---|
| P4-01 + 이행 집중 시험 | `python -m pytest -q tests/test_quality_gates.py tests/test_migration.py` — **19 통과** |
| 전체 제품 시험 | `scripts\run-tests.ps1` — **pytest 430 통과**, 알려진 deprecation warning 2건 |
| P1 문서 계약 | 같은 스크립트 — **unittest 18 통과** |
| 웹 | `web`에서 `npm run build` — TypeScript/Vite 프로덕션 빌드 성공 |
| 실제 CLI | `codex-cli 0.154.0`, read-only·ephemeral 별도 실행 1회. 작은 ERROR/INFO 대상에서 기존 기준에 연결된 `required/confirmed` 발견 하나를 계약 JSON으로 반환했고 저장소 변경 없음 |
| 재시작·이행 | 정책/실패/repair 파일 DB 재개와 v12→v13 반복 이행 시험 통과 |

실제 CLI의 핵심 출력은 다음과 같았다. 긴 원문은 제어부 DB에 넣지 않았다.

```json
{"findings":[{"finding_key":"info-line-not-filtered","criterion":"criterion-error-only","severity":"required","certainty":"confirmed","target":"텍스트 필터 반환값","summary":"INFO 줄이 포함되어 ERROR 줄만 반환해야 한다는 기준을 위반한다."}]}
```

## 4. 검토 중 발견해 수정한 것

- 일반 게이트 차단 목록이 현재 그래프에 없는 Task를 먼저 조회해 기존 구조화된 409 거부를
  404로 바꾸던 순서 문제를 수정했다. 그래프/Task 부재는 기존 진입 검사가 설명하고,
  존재하는 Task에만 추가 게이트 조건을 계산한다.
- 목록형 참조만 제한하고 발견의 `evidence_artifact_id`·repair 세션 참조는 내부 호출에서
  길이 제한을 우회할 수 있던 데이터 경계를 보강했다. 런타임 거부와 DB CHECK를 함께 둔다.

## 5. 남은 경계와 인계

- 이 결과는 **P4-01만** 완료한다. 실행 중 설정 변경의 예약 적용·부분 재검증은 P4-02,
  여섯 Profile 전수는 P4-03, 지식/QG-08은 P4-06~07, 게시/push/PR은 P5다.
- P3의 예산 라이브 경로 C는 이전 사용자 지시대로 스킵 상태이며 P4-01의 미충족이 아니다.
- 시작은 `main`/`8f50bcb`, `origin/main`과 동일하고 clean이었다. 결과는 현재 작업 트리에
  미커밋으로 남아 있다. commit·push·PR·외부 게시를 수행하지 않았다.
