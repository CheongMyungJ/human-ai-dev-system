# 사람–AI SW 개발 협업 시스템

설계 기준 **v0.8 2차 반영 · 2026-09-23 · D-01~90**. GitHub: [CheongMyungJ/human-ai-dev-system](https://github.com/CheongMyungJ/human-ai-dev-system) (비공개).

정본 위치는 `C:\git\human-ai-dev-system-design`이다. **현재 구현은 UI-01 완료·스키마 v16**(P4-03의 Profile 정의 v2 위)다. 대화 중심 UI의 주요 제품 정책과 개발 순서를 문서에 2차 반영했고, **UI-01이 대화·요청의 영속 기반과 서버 전송 잠금을 구현했다.** 새 기본 대화 화면·입력/실행 제어·중단은 미구현이다. 화면 폭·간격·단축키와 기술 상세는 구현 과정에서 구체화한다. 화면 시안이나 실제 사용성 검증을 마쳤다는 뜻은 아니다.

## 다음 개발 세션

[DEVELOPMENT.md](DEVELOPMENT.md)와 [대화 중심 UI 설계](ui-conversation-design.md), [UI-01 결과](ui/evidence/UI-01-results.md)를 먼저 읽는다. **UI-01(대화·요청 기반)은 완료**했다 — 준비 Case, 메시지·정정·참조, 요청 처리 상태와 API 전송 잠금, 접수 멱등성, 최초 업무화. 다음 작업은 **P4-04 — 문맥·재개**이며 새 `P4-PLAN-04`를 기록·공유한 뒤 시작한다. 실제 중단 제어와 Runner 수신/실행 분리는 그 다음 UI-02다. 완료된 P4-01~03·UI-01을 다시 열지 않는다. UI-01 변경은 사용자 지시로 `a509063`에 커밋해 `origin/main`에 push했다.

> DEVELOPMENT.md의 최신 인계(S-020)와 UI-01 결과를 읽고 P4-04(문맥·재개)를 진행해줘. UI-01·P4-03 완료 상태를 보존하고 새 P4-PLAN-04를 기록·공유한 뒤, 해당 범위의 구현·검증·인계 절차를 지켜줘. UI-02 중단 제어와 UI 전체 개편으로 범위를 확대하지 말아줘.

P3은 제한을 명시한 완료 상태이고 P4-01~03·UI-01도 완료됐다. 개발 순서는 **UI-01(완료) → P4-04 + UI-02 → UI-03 기본 화면 → P4-05~07 + UI-04 추가 흐름 → P5/P6**다. P4-04 문맥·재개와 UI-02의 수신/실행 분리·질문·중단·복구는 별도 plan으로 다루며, 중단은 실제 확인 능력을 검증한 뒤 화면에 연결한다. UI-04는 착수 시 세분 plan으로 나누고 P4-04에 전체 UI를 몰아넣지 않는다.

## 설계 방향

사람은 위임하지 않은 제품 선택·권한 확대·중요한 모호성·한도 변경·예외 수용에서 호출한다. AI는 업무에 맞는 작업 그래프를 만들고 시스템은 요청·권한·버전·증거·예산을 검사한다.

- WorkDepth(simple/standard/deep), Autonomy(기본 ask-on-decision/controlled), Budget(기본 무제한)을 분리한다. Fast Lane은 명확·저위험인 작업의 실행 경로다.
- 대표 대화 하나가 Case 하나다. 목표·Profile이 미정인 논의 준비 단계에서 명확한 업무 요청으로 같은 Case를 이어가며 소비·결정·제한을 보존하는 UI를 설계한다.
- AI intake 초안은 여섯 Case Profile의 목적에 맞게 구성한다. 별도 설계·계획·검토 실행을 모든 업무에 강제하지 않는다. P4-03의 목적별 완료 계약을 유지한다.
- Project는 복수 Repository를 포함한다. 한 Case의 저장소 작업은 같은 Runner에서 수행한다. 업무화 뒤 연결·허용 안에서 기록 이슈 하나를 만들며 대표 저장소가 코드와 이슈를 겸할 수 있도록 설계를 개정했다. 허용은 각각 검사한다.
- PC·라이트 테마·현재 프로젝트 중심의 대화/검토 화면을 사용한다. 현재 요청 처리 중 초안 편집은 가능하고 일반 전송은 잠그며 질문 카드·중단은 별도 경로로 처리하도록 설계한다.
- 현재 브라우저의 대화별 초안을 복구하고 현재 프로젝트의 보관 대화까지 검색한다. 본문 검색은 PC 연결 시 지원하며 읽던 결과물 버전·피드백 대상을 유지한다. 앱은 검토·참조 의견을 제공하고 파일 직접 편집은 외부 도구에서 한다.
- 미완료인 같은 문제의 목적 확장·Profile 변경은 이력·기준·예산을 보존하며 같은 Case에서 이행한다. 종료 후 설명은 기존 Case 예산에 누적하고 추가 실험·수정은 새 Case로 연결한다. 시간 한도를 선택하면 실행시간 합계를 기본 지표로 사용한다.
- 코드 변경의 기본 완료 지점은 전용 작업공간의 로컬 구현·검증이다. 원래 폴더 반영이나 기본 브랜치 병합을 뜻하지 않는다. 이미지 첨부·분석과 모바일 최적화는 후속 검토다.
- 요청된 push·PR은 유효한 허용 범위 안에서 자동 수행한다. controlled는 결과 후보 확인 후 요청된 게시와 필요한 외부 CI를 거쳐 종료한다. 허용만으로 게시가 의무가 되지는 않는다.
- 지식은 원본·적용 조건·버전을 관리하고 선택적으로 추출해 작업 범위·활동에 맞게 주입한다. 범용 검색이나 별도 외부 지식 시스템은 포함하지 않는다.

Windows 네이티브·한 사용자·Python/FastAPI·Python Runner·SQLite·React/TypeScript를 유지한다. 서버+PC 구성의 상세 원문은 PC에 두고 제어부는 상태·요약·참조만 보관한다. worktree를 OS 격리라고 설명하지 않는다.

## 현재 구현과 실행 방법

P3-R1~R4에서 Autonomy·확인 지점·예산·저장소 선택의 강제와 같은 Runner의 복수 저장소 작업공간이 연결됐다. P4-01~02는 게이트·repair·예약 변경·부분 재검증·늦은 결과를, P4-03은 Profile 정의 v2의 목적별 완료 계약·충족 방식·결론·혼합 목적·실험 정리를 구현했다. 기존 v1 Case에는 새 완료 규칙을 소급하지 않는다. 지식 적용·실제 GitHub 게시와 이번 대화 UI는 후속 구현이다. 상세 상태와 한계는 DEVELOPMENT.md를 따른다.

필요 환경은 기존 구현 기준 Windows, Python 3.12, Git, Node.js 22 이상과 설치·로그인된 Codex 또는 Claude Code다. 설치·PATH 문제와 미설치를 구별하고 저장소 스크립트가 사용하는 `.venv` 인터프리터를 확인한다.

```powershell
scripts\bootstrap.ps1
scripts\run-controller.ps1
# 다른 터미널에서 Runner
scripts\run-runner.ps1
# 시험
scripts\run-tests.ps1
```

제어부 기본 주소는 `http://127.0.0.1:8765`다. [P4-03 보고](p4/evidence/P4-03-results.md)의 마지막 검증은 pytest 481건 + P1 계약 unittest 18건 통과, build 성공, 실제 CLI 의도 초안 3건이다. **이번 문서 개정에서 재실행한 수치가 아니다.** 개발 재개 시 현재 기준선을 다시 확인한다.

`.venv`, `web/node_modules`, `web/dist`는 로컬 환경·빌드 경로다. `var`에는 업무 DB·원문·증거가 있으므로 단순 캐시처럼 삭제하지 않는다. CLI 로그인은 각 도구의 기존 설정을 사용하고 시스템 업무 기록에 자격증명을 복사하지 않는다.

변경 관측만으로 의미적 정답을 증명하지 않으며 실행 증거의 실제 수집·자기보고 한계도 구분한다. P4-03의 무변경 목표 충족은 검증 실행의 관측을 요구한다. 실제 중단 확인·PC 원문 가용성·외부 효과 대조 등 남은 제약은 DEVELOPMENT.md의 이월표와 UI 설계의 구현 차이를 함께 확인한다.

## 읽을 문서

| 문서 | 역할 |
|---|---|
| [DEVELOPMENT.md](DEVELOPMENT.md) | 현재 구현·다음 작업·plan·검증·인계의 시작점 |
| [전체 설계](design-draft.md) / [사용자 결정](decisions.md) | v0.8 2차 범위·책임·정책과 D-01~90 |
| [대화 중심 UI](ui-conversation-design.md) | 확정 화면·상호작용, 현재 구현 차이, 구현 상세·개발 인계 |
| [자동화·예산](autonomy-budget-policy.md) | 위임·material delta·Fast Lane·예산·controlled 경계 |
| [Case Profile](case-profiles.md) / [intake·산출물](intent-artifacts.md) | 목적별 AI 초안·피드백·증거·완료 |
| [프로젝트 지식](project-knowledge.md) | 관리·선택적 추출·자동 주입·유효성 |
| [기능 요구](scenarios-functional-requirements.md) / [비기능 요구](nonfunctional-requirements.md) | 요구사항과 수용 기준 |
| [깊이·UX](sizing-and-review-ux.md) / [품질 게이트](quality-gates.md) / [게이트 운영](gate-operations.md) | 실제 적용 정책·질문·검증·repair |
| [검토 문맥](review-context-contract.md) / [완료](completion-lifecycle.md) | 입력·기준·결과 후보·예외·후속 Case |
| [실행·작업공간](execution-workspace-review.md) / [GitHub 기록](github-journal.md) | 복수 Repo·권한·부분 반영·요약 게시 |
| [데이터 경계](data-boundary-review.md) / [구현 기준](implementation-baseline.md) | Runner 원문·복구·기술·설치·운영 |
| [수용 시나리오](review-acceptance-matrix.md) / [검토 보고](design-review-report.md) | 문서 정합성과 후속 검증 |
| [설계 개정 이력](review-status.md) | 과거 결정과 v0.7·v0.8 1·2차 개정 관계 |
| [기술 조사](review-tech-findings.md) / [CLI 중지 조사](cli-pause-feasibility.md) | 날짜가 있는 기술 참고·실증 과제 |
| [v0.6 개발 인계 보존본](development-history-v0.6.md) / [당시 시연](implementation-walkthrough-v0.6.md) | 현재 정책과 구분한 P1~P3-03 이력 |

## 검증의 경계

설계 문서 정합성, 제품 자동 시험, 실제 CLI·외부 서비스·호스트 시험은 서로 다른 증거다. OpenCode는 문서 계약과 실증 상태를 구별한다. 안전 중지·절대 예산 통제·원문 비보관·복구·성능은 구현과 실행 모드별로 확인한다. 아직 검증하지 않은 기능을 지원 완료로 표시하지 않는다.
