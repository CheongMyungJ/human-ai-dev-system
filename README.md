# 사람–AI SW 개발 협업 시스템 설계

설계 기준안 **v0.6** · 2026-09-20

GitHub 저장소: [CheongMyungJ/human-ai-dev-system](https://github.com/CheongMyungJ/human-ai-dev-system) — 비공개. 설계 문서와 후속 개발 코드를 같은 저장소에서 관리한다.

정본 위치는 `C:\git\human-ai-dev-system-design`이다. 이 디렉터리의 문서가 이후 설계·구현의 기준이다. 주요 제품 결정 58건을 통합했으며 구현과 실제 CLI·복구·성능 시험은 아직 수행하지 않았다.

## 개발을 시작하는 새 세션

[개발 진행 안내서 DEVELOPMENT.md](DEVELOPMENT.md)를 읽고 현재 단계를 수행한다. 이 문서에 현재 상태, 6단계별 범위·성공 기준, 코드 변경 전 필수 plan, 검증·인계 절차가 있다. 시작 단계는 P1 CLI 연결 검증이며 아직 제품 구현을 시작하지 않았다.

새 세션 요청 예시: `DEVELOPMENT.md를 읽고 지금 진행할 단계를 수행해줘. plan·검증·인계 절차를 지켜줘.`

## 먼저 읽을 문서

1. [전체 설계](design-draft.md): 첫 버전 범위, 업무 흐름, 구성도, 실행·저장 모델.
2. [주요 시나리오·기능 요구사항](scenarios-functional-requirements.md): SC-01~12, FR-01~30과 수용 기준.
3. [비기능 요구사항](nonfunctional-requirements.md): NFR-01~12와 장애·데이터·컨텍스트 검증.
4. [구현·운영 계획](implementation-baseline.md): 채택 기술, 설치, 백업, 동시성, 개발 순서와 기술 검증.

핵심 구조는 Python/FastAPI 제어부·Python Runner·SQLite·React/TypeScript 웹 UI다. 기능 개발은 의도 초안·사람 피드백·최신 동의를 필수로 거치고 필요한 설계·개발계획 후 구현한다. AI가 업무에 맞는 작업 그래프를 제안하며 시스템이 승인·버전·검증·진행 조건을 검사한다.

첫 버전은 Windows 네이티브·한 사용자·프로젝트당 Git 저장소 하나·업무별 브랜치와 worktree다. 로컬·서버 완결형과 서버 제어부 + 개인 PC Runner를 지원한다. PC 분리형에서는 상세 문서·대화·코드·diff·로그를 PC에 두고 서버는 상태·요약·참조와 일시중계만 맡는다. 상세 열람과 새 원문 저장에는 PC 연결이 필요하다.

## 상세 문서

| 문서 | 내용 |
|---|---|
| [사용자 결정 목록](decisions.md) | D-01~58의 확정 범위와 근거 |
| [연속 검토 기록](review-status.md) | 검토 순서와 후속 결정 이력 |
| [의도·설계·계획 산출물](intent-artifacts.md) | 여섯 의도 항목, 성공 기준, 이월 질문, 예시 |
| [작업 수준·검토 화면](sizing-and-review-ux.md) | 간소·표준·심층 추천, 대화·원문·버전·게이트 설정 |
| [품질 게이트](quality-gates.md) | 적용 지점·비용·검증 예시와 선택 정책 |
| [게이트 실행·복구](gate-operations.md) | 별도 검토, 수정 2회, 검증 1회 종료 후 설정 적용 |
| [검토 컨텍스트 계약](review-context-contract.md) | 원문·기준·증거 입력, 분할 검토와 새 세션 복원 |
| [완료·예외 종료](completion-lifecycle.md) | 사람 인수·자동 완료·예외 수용·연결된 새 Case |
| [실행·작업공간](execution-workspace-review.md) | worktree, 중복 배정 방지, 도구 경계 정지, push/PR |
| [서버·PC 데이터 경계](data-boundary-review.md) | 원문 보관·일시중계·오프라인·백업·Runner 이관 |
| [GitHub 요약 기록](github-journal.md) | 새 기록 이슈, 상단 표식, 요약 append, 게시 장애 |
| [수용 시나리오](review-acceptance-matrix.md) | 정상·변경·실패·단절·복원 상황에서 확인할 동작 |
| [공식 기술 문서 확인](review-tech-findings.md) | 기술 선택 근거와 실제 검증의 구분 |
| [CLI 안전 중지 조사](cli-pause-feasibility.md) | 세 CLI의 제어 후보·제약·실증 계획 |
| [최종 문서 검토](design-review-report.md) | 요구사항 추적, 일관성 점검, 남은 기술 검증 |
| [P1-01 환경 실측·계약 초안](p1-environment-contract.md) | 이 PC의 실측 환경·CLI·인증 상태, 공통 실행 계약과 capability 표 |

## 검토 결과의 경계

주요 제품 정책에 대한 답변 수집은 끝났다. 실제 Windows/CLI의 도구 경계 제어, 원문이 서버 로그·캐시에 남지 않는지, 부분 장애 복구와 목표 규모의 성능은 구현 단계에서 시험해야 한다. OpenCode는 미설치 상태의 문서 기반 설계이며 실환경 검증 완료로 표시하지 않는다.

공동 사용·Linux/WSL·복수 저장소/프로젝트 업무·지식 자동 추출/채택·인터넷 직접 공개·병합/배포는 확장 범위로 분리했다. 확장 가능성을 준비하는 것과 첫 버전에서 구현하는 것을 구분한다.
