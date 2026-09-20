# 사람–AI SW 개발 협업 시스템 설계

설계 기준안 **v0.6** · 2026-09-20

GitHub 저장소: [CheongMyungJ/human-ai-dev-system](https://github.com/CheongMyungJ/human-ai-dev-system) — 비공개. 설계 문서와 후속 개발 코드를 같은 저장소에서 관리한다.

정본 위치는 `C:\git\human-ai-dev-system-design`이다. 이 디렉터리의 문서가 이후 설계·구현의 기준이다. 주요 제품 결정 58건을 통합했다. 구현은 **P2-01 최소 골격까지** 와 있다(아래 실행 방법 참조). 실제 코딩 CLI 연결, 품질 게이트, GitHub 연동, 원격·성능 시험은 아직이다.

## 개발을 시작하는 새 세션

[개발 진행 안내서 DEVELOPMENT.md](DEVELOPMENT.md)를 읽고 현재 단계를 수행한다. 이 문서에 현재 상태, 6단계별 범위·성공 기준, 코드 변경 전 필수 plan, 검증·인계 절차가 있다. P1은 제한 수용으로 종료했고 현재 단계는 P2 최소 업무 흐름이다.

새 세션 요청 예시: `DEVELOPMENT.md를 읽고 지금 진행할 단계를 수행해줘. plan·검증·인계 절차를 지켜줘.`

## 실행 방법 (P2-01 기준)

**필요한 것:** Windows, Python 3.12(`py -3.12` 로 잡히는 것), Git, Node.js 22 이상.
런타임은 3.12로 고정돼 있다. `python` 과 `py` 의 기본 버전이 달라도 스크립트가 `.venv` 의
인터프리터를 직접 가리키므로 세션마다 달라지지 않는다.

```powershell
# 1) 한 번만: 저장소 로컬 가상환경 + Python 의존성 + 웹 UI 빌드
scripts\bootstrap.ps1

# 2) 제어부 (기본 http://127.0.0.1:8765, 빌드된 화면을 같은 주소에서 서빙)
scripts\run-controller.ps1

# 3) 다른 창에서 로컬 Runner
scripts\run-runner.ps1

# 4) 전체 시험 (P2-01 pytest 19건 + P1 OpenCode 문서 계약 unittest 18건)
scripts\run-tests.ps1
```

설치 대상은 저장소 안의 `.venv\` 와 `web\node_modules\` 뿐이다. 사용자 전역 Python·Node·CLI
설정은 바꾸지 않는다. 상태 DB·원문·로그는 `var\` 에 생기며 커밋하지 않는다. 지워도 다시 만들어진다.

**지금 동작하는 범위:** 프로젝트·Case 생성, 원문 제출과 Runner 영속 저장, 의도 버전·결정 기록,
Run 생성·배정·실행·결과 표시, 강제 종료 후 복원, 같은 요청 재전송의 중복 실행 방지.
**아직 아닌 것:** 의도 초안·피드백·동의 흐름(P2-02), 진입 조건 검사와 실제 코딩 CLI 실행(P2-03),
원문 본문 열람(P2-04). P2-01의 실행기는 코딩 CLI가 아니다.

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
| [P1-02 CLI 실증 결과](p1/evidence/P1-02-results.md) | Codex·Claude 실제 실행 증거, 권한 경계·이벤트 스키마·완료 판정에서 확인한 것 |
| [P1-03 중지·복구 실증 결과](p1/evidence/P1-03-results.md) | 단절 시 다음 도구 호출 차단, 훅 fail-open, 강제 종료의 프로세스 잔류 |
| [P1-04 OpenCode 어댑터 계약](p1/opencode/contract.md) | 설치 없이 공식 V2 문서로만 만든 계약·fixture·계약 시험. 실증 아님 |
| [P2-01 최소 골격 실행 결과](p2/evidence/P2-01-results.md) | 제어부·Runner·화면의 실제 연결, 강제 종료 복원, 중복 실행 방지, 원문 비보관 확인 |

## 검토 결과의 경계

주요 제품 정책에 대한 답변 수집은 끝났다. 실제 Windows/CLI의 도구 경계 제어, 원문이 서버 로그·캐시에 남지 않는지, 부분 장애 복구와 목표 규모의 성능은 구현 단계에서 시험해야 한다. OpenCode는 미설치 상태의 문서 기반 설계이며 실환경 검증 완료로 표시하지 않는다.

공동 사용·Linux/WSL·복수 저장소/프로젝트 업무·지식 자동 추출/채택·인터넷 직접 공개·병합/배포는 확장 범위로 분리했다. 확장 가능성을 준비하는 것과 첫 버전에서 구현하는 것을 구분한다.
