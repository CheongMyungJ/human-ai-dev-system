# 사람–AI SW 개발 협업 시스템

설계 기준 **v0.7 · 2026-09-21 · D-01~67**. GitHub: [CheongMyungJ/human-ai-dev-system](https://github.com/CheongMyungJ/human-ai-dev-system) (비공개).

정본 위치는 `C:\git\human-ai-dev-system-design`이다. **현재 코드는 v0.6 기준 P3-03까지 구현됐고, 새 설계는 아직 구현되지 않았다.** 이 문서 개정은 Fast Lane·자율성·예산·Profile·복수 저장소·최소 지식 정책을 통합한 것이다.

## 다음 개발 세션

[DEVELOPMENT.md](DEVELOPMENT.md)의 **P3-R1 — 정책·Profile·영속 모델 정합화**부터 시작한다. 코드 변경 전 plan을 기록하고, 현재 하위 작업 하나를 구현·검증·인계한다. 기존 P3-03을 다시 열거나 P3-04 통합 시험부터 진행하지 않는다.

> DEVELOPMENT.md를 읽고 현재 하위 작업 P3-R1을 수행해줘. 기존 구현과 미커밋 설계 변경을 보존하고 plan·검증·인계 절차를 지켜줘.

P3의 남은 순서는 **R1 정책·Profile → R2 복수 저장소 → R3 예산 → R4 자동 실행 → P3-04 통합**이다. P4에서 다양한 업무·품질·최소 지식, P5에서 GitHub 외부 반영, P6에서 원격·운영·전체 수용을 완성한다.

## 설계 방향

사람은 위임하지 않은 제품 선택·권한 확대·중요한 모호성·한도 변경·예외 수용에서 호출한다. AI는 업무에 맞는 작업 그래프를 만들고 시스템은 요청·권한·버전·증거·예산을 검사한다.

- WorkDepth(simple/standard/deep), Autonomy(기본 ask-on-decision/controlled), Budget(기본 무제한)을 분리한다. Fast Lane은 명확·저위험인 작업의 실행 경로다.
- AI intake 초안은 여섯 Case Profile의 목적에 맞게 구성한다. 별도 설계·계획·검토 실행을 모든 업무에 강제하지 않는다.
- Project는 복수 Repository를 포함한다. 한 Case의 저장소 작업은 같은 Runner에서 수행하고, 기록 이슈는 Project의 지정 저장소에 하나를 만든다.
- Case 시작 때 허용한 범위의 push·PR은 자동 수행한다. controlled는 결과 후보 확인 후 게시하고 필요한 외부 CI 뒤 종료한다.
- 지식은 원본·적용 조건·버전을 관리하고 선택적으로 추출해 작업 범위·활동에 맞게 주입한다. 범용 검색이나 별도 외부 지식 시스템은 포함하지 않는다.

Windows 네이티브·한 사용자·Python/FastAPI·Python Runner·SQLite·React/TypeScript를 유지한다. 서버+PC 구성의 상세 원문은 PC에 두고 제어부는 상태·요약·참조만 보관한다. worktree를 OS 격리라고 설명하지 않는다.

## 현재 구현과 실행 방법

P3-03까지 실제 CLI 연결, AI 의도 작성·별도 QG-01·명시 동의, 설계/계획, 작업 그래프·질문 의존성, Case 작업공간·코드 쓰기·명령 증거, 결과 확인·재시작 복원이 연결됐다. **이는 당시 v0.6 승인 중심 동작**이다. 새 Autonomy·Profile intake·예산 강제·복수 Repo·지식 적용·GitHub 연동은 후속 작업이다.

필요 환경은 기존 구현 기준 Windows, Python 3.12, Git, Node.js 22 이상과 설치·로그인된 Codex 또는 Claude Code다. 설치·PATH 문제와 미설치를 구별하고 저장소 스크립트가 사용하는 `.venv` 인터프리터를 확인한다.

```powershell
scripts\bootstrap.ps1
scripts\run-controller.ps1
# 다른 터미널에서 Runner
scripts\run-runner.ps1
# 시험
scripts\run-tests.ps1
```

제어부 기본 주소는 `http://127.0.0.1:8765`다. P3-03 마지막 보고는 제품 pytest 242건과 P1 계약 unittest 18건 통과이며 이번 문서 개정에서 재실행한 수치가 아니다. 실제 최신 결과는 [P3-03 보고](p3/evidence/P3-03-results.md)와 다음 세션 검증을 따른다.

`.venv`, `web/node_modules`, `web/dist`는 로컬 환경·빌드 경로다. `var`에는 업무 DB·원문·증거가 있으므로 단순 캐시처럼 삭제하지 않는다. CLI 로그인은 각 도구의 기존 설정을 사용하고 시스템 업무 기록에 자격증명을 복사하지 않는다.

P3-03의 쓰기는 준비된 Case worktree의 구현·검증 실행에만 열려 있다. 변경 관측은 의미적 정답의 증거가 아니며 명령 기록도 당시에는 AI 자기보고라는 제한이 있다. 기존의 무변경 구현 실패 정책은 후속 작업에서 증거 기반 완료 의미로 바꾼다. 상세 한계와 배정 위치는 DEVELOPMENT.md에 기록했다.

## 읽을 문서

| 문서 | 역할 |
|---|---|
| [DEVELOPMENT.md](DEVELOPMENT.md) | 현재 구현·다음 작업·plan·검증·인계의 시작점 |
| [전체 설계](design-draft.md) / [사용자 결정](decisions.md) | v0.7 범위·책임·정책과 D-01~67 |
| [자동화·예산](autonomy-budget-policy.md) | 위임·material delta·Fast Lane·예산·controlled 경계 |
| [Case Profile](case-profiles.md) / [intake·산출물](intent-artifacts.md) | 목적별 AI 초안·피드백·증거·완료 |
| [프로젝트 지식](project-knowledge.md) | 관리·선택적 추출·자동 주입·유효성 |
| [기능 요구](scenarios-functional-requirements.md) / [비기능 요구](nonfunctional-requirements.md) | 요구사항과 수용 기준 |
| [깊이·UX](sizing-and-review-ux.md) / [품질 게이트](quality-gates.md) / [게이트 운영](gate-operations.md) | 실제 적용 정책·질문·검증·repair |
| [검토 문맥](review-context-contract.md) / [완료](completion-lifecycle.md) | 입력·기준·결과 후보·예외·후속 Case |
| [실행·작업공간](execution-workspace-review.md) / [GitHub 기록](github-journal.md) | 복수 Repo·권한·부분 반영·요약 게시 |
| [데이터 경계](data-boundary-review.md) / [구현 기준](implementation-baseline.md) | Runner 원문·복구·기술·설치·운영 |
| [수용 시나리오](review-acceptance-matrix.md) / [검토 보고](design-review-report.md) | 문서 정합성과 후속 검증 |
| [설계 개정 이력](review-status.md) | v0.6의 과거 결정과 v0.7 대체 관계 |
| [기술 조사](review-tech-findings.md) / [CLI 중지 조사](cli-pause-feasibility.md) | 날짜가 있는 기술 참고·실증 과제 |
| [v0.6 개발 인계 보존본](development-history-v0.6.md) / [당시 시연](implementation-walkthrough-v0.6.md) | 현재 정책과 구분한 P1~P3-03 이력 |

## 검증의 경계

설계 문서 정합성, 제품 자동 시험, 실제 CLI·외부 서비스·호스트 시험은 서로 다른 증거다. OpenCode는 문서 계약과 실증 상태를 구별한다. 안전 중지·절대 예산 통제·원문 비보관·복구·성능은 구현과 실행 모드별로 확인한다. 아직 검증하지 않은 기능을 지원 완료로 표시하지 않는다.
