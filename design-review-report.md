# v0.7 설계 문서 통합 검토

개정일: 2026-09-21. 사용자 확정 D-01~67을 기존 설계와 통합한 **문서 검토**다. 이번 세션은 제품 코드·테스트·스키마·CLI 실행·외부 게시를 변경하거나 수행하지 않았다. 현재 구현은 v0.6 기준 P3-03이며, 새 설계 구현은 P3-R1부터 진행한다.

## 통합 범위와 추적

| 확정 내용 | 정책·상세 정본 | 구현 배정 |
|---|---|---|
| 실제 판단에서만 사람 호출·WorkDepth/Autonomy 분리 | D-11/14/21/23/31/59, autonomy-budget-policy.md | P3-R1/R4 |
| Fast Lane·누적 material delta·조건부 독립 AI 검토 | D-15/16/25~28/60, intent-artifacts.md, quality-gates.md, gate-operations.md | P3-R4/P4-01/02 |
| 기본 무제한·선택 예산·병렬 예약·측정/강제 능력 | D-29/45/56/61, autonomy-budget-policy.md, NFR-10 | P3-R3/P6 |
| 6 Profile·업무별 AI intake·혼합 목적·증거/완료 | D-14/47/62, case-profiles.md, intent-artifacts.md | P3-R1/R4/P4-03 |
| 같은 Runner 복수 Repo·선택/권한·통합 조합 | D-38/39/63, execution-workspace-review.md | P3-R2/04/P5 |
| Project 기록 Repo·이슈1·사전 허용 push/PR | D-17/19/34/36/63/64, github-journal.md, execution-workspace-review.md | P3-R1/R2/P5 |
| controlled 후보 확인→코드 게시→필요 CI→종료 | D-31/65, completion-lifecycle.md | P3-R4/P4-05/P5-04 |
| 분석·연구의 복구가능 로컬 실험 자동 위임 | D-22/48/66, case-profiles.md, gate-operations.md | P3-R4/P4-03 |
| 최소 지식 관리·선택 추출·활동/범위 주입 | D-49/67, project-knowledge.md, review-context-contract.md, data-boundary-review.md | P4-06/07/P6-02 |

구체 요구는 [FR·SC](scenarios-functional-requirements.md), [NFR](nonfunctional-requirements.md), [40개 수용 사례](review-acceptance-matrix.md)에 연결한다. 공통 규칙을 새 문서에만 추가하고 기존 본문의 의무 승인·단일 Repo·지식 후속 확장 정책을 남기는 방식은 사용하지 않았다. [decisions.md](decisions.md)의 기존 조항도 현재 의미로 갱신하고 [review-status.md](review-status.md)에 대체 관계와 과거 결정 원문을 남겼다.

## 개발 재개와 이력 보존

- 다음 세션은 [DEVELOPMENT.md](DEVELOPMENT.md)의 **P3-R1**과 새 plan부터 시작한다. R1→R2→R3→R4→P3-04의 범위·선행 조건·성공 기준을 명시했다.
- P3-03 완료·스키마v7·242+18 시험은 이전 실행 보고의 사실이다. 이번 문서 작업의 검증 결과 또는 v0.7 통과로 표시하지 않는다.
- 기존 DEVELOPMENT 전체를 [v0.6 보존본](development-history-v0.6.md)에 보존했다. 기존 plan·evidence 원문은 변경하지 않았다. 오래된 다음 작업 지시는 현재 DEVELOPMENT를 대체하지 않는다.
- README의 단계별 시연은 [당시 시연 기록](implementation-walkthrough-v0.6.md)으로 분리했다. README의 현재 구현 설명을 P3-03에 맞추고 새 설계와 구별했다.
- 기존 Case·승인·권한·종료 기록 보존, 새 Case 기본값, 기능별 미지원 상태와 실제 마이그레이션 검증을 R1 이후 작업에 배정했다.

## 교차 검토에서 정리한 경계

1. Case의 여러 저장소를 같은 Runner에 두는 것과 과거 지식 원문이 모두 그 Runner에 있는 것은 다르다. 원문 소유자·가용성은 유지한다.
2. Project의 기록 Repo는 요약 게시 위치이며 코드 변경 범위나 지식의 원본·권위를 바꾸지 않는다.
3. controlled의 결과 확인은 **코드 push·PR 전**이다. 별도 허용된 진행 중 이슈 요약 게시를 막는 의미로 확대하지 않는다.
4. 사전 허용되지 않은 다른 CLI의 장애 대체는 확인한다. 이미 특정 대체가 명시 허용됐으면 동일 확인을 반복하지 않으며 자동 fallback 기능을 새로 약속하지 않는다.
5. controlled는 이미 유효한 명시 시작 확인만 재사용한다. 상세 최초 요청이나 AI 정규화만으로 사람의 시작 확인을 만들어내지 않는다.
6. 필수 지식 주입과 실제 준수를 구분한다. 동적 범위 변경을 관측/통제할 수 없는 실행 방식은 분할·입력 재구성 등 실제 제어 능력에 맞춰 지원 범위를 표시한다.
7. 로컬 실험·무변경 성공·불확실 연구 결론은 각각 목적/권한/증거 기준으로 판단한다. Profile·예산·변경량만으로 성공을 만들지 않는다.
8. 정확한 hard 한도를 요구했는데 강제 능력이 없으면 배정을 보류한다. 명시적으로 추정 한도를 선택한 경우와 구분하고 표시만 바꾸어 자동 하향하지 않는다.

## 문서 구조 검증

2026-09-21 문서 구조 검사에서 Markdown 45개, 로컬 링크 367개, 코드 블록 87개, JSON 예시 3개, 표 198개의 경로 존재·블록 짝·파싱·열 정합성을 확인했다. D 67개, SC 15개, FR 30개, NFR 12개, 수용 사례 AC 40개의 식별자가 연속·유일함을 확인했다. `git diff --check`와 변경 범위 검사도 통과했다.

정책·Profile/복수 저장소·지식/데이터 경계를 분담 검토한 뒤 다른 담당자가 교차 검토했고, 발견한 CLI 확인 조건·controlled 확인 경계·정확한 hard 한도 표현을 수정했다. 현행 문서의 구정책 잔여 문구도 대조했다. 과거 기준을 설명하는 이력·증거는 역사 기록으로 구분하며 원본 plan·evidence 변경은 없다. 링크 검사는 로컬 경로 기준이고 외부 URL·CLI 기술 문서를 이번에 재검증했다는 뜻은 아니다.

## 남은 구현·실증 과제

현재 제품 정책의 미결은 발견하지 않았다. 실제 CLI의 세부 도구 경계·중단·사용량 관측·절대 한도 강제, Windows 자식 활동, 원문 비보관, 부분 복원, 실제 외부 결과·경합, 목표 규모 성능은 구현 후 근거가 필요하다. 해당 과제는 DEVELOPMENT와 수용 시나리오에 배정했으며 문서 통과를 구현·성능·보안 통과로 확대하지 않는다. 외부 검색 시스템이나 분산 Case 실행은 이번 범위에 추가하지 않았다.
