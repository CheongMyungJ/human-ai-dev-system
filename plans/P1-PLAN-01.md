# P1-PLAN-01 (완료, 2026-09-20 종료)

이 문서는 [DEVELOPMENT.md](../DEVELOPMENT.md)의 활성 plan 자리에서 옮겨 온 **완료된 plan 원문**이다.
근거 보존이 목적이며 현재 활성 plan은 DEVELOPMENT.md 3절에 있다. 내용은 옮길 때 수정하지 않았다.

```text
Plan ID: P1-PLAN-01 (완료, 2026-09-20 종료)
단계 / 이번 세션 하위 작업: P1 — CLI 연결 검증 / P1-01 환경·계약(완료), P1-02 실증(완료), P1-03 중지·복구(완료)
작성·수정 시점: 2026-09-20 작성, 같은 날 P1-02·P1-03 수행 결과로 갱신
기준 Git 브랜치·커밋 / 기존 미커밋 변경:
  main / 815f3f3 "docs: add plan-first development guide for staged sessions"
  시작 시 작업 트리 clean. 사용자 미커밋 변경 없음
목표와 사용자에게 보일 결과:
  이 PC에서 Codex·Claude·OpenCode의 실제 설치·인증·권한 상태를 사실로 확정하고,
  CLI에 종속되지 않는 공통 실행 계약(입력·이벤트·결과·능력표) 초안을 만든 뒤,
  최소 실행 harness로 두 CLI의 실제 동작 증거를 남긴다.
포함 범위:
  P1-01 환경 실측, 인증 구성 확인, 공통 어댑터 계약 초안, capability 표 초안, P1-02 실행 계획
  P1-02 임시 시험 저장소에서의 최소 실행 harness와 실제 호출 증거
제외 범위:
  제품 UI·업무 엔진·DB 구현(P2), GitHub 쓰기(P5), 사용자 실제 프로젝트 변경,
  CLI·계정의 설치·로그인·설정 변경, OpenCode 설치, 사용자 전역 CLI 설정 변경,
  재연결·재개 실증(P2 이후)
적용 결정·요구사항 ID: FR-28, FR-29(별도 검토 세션), NFR-07, NFR-08, D-42·44(신뢰 모드 한계), D-45(CLI 교체 확인), D-53
읽은 근거 / 확인한 사실 / 아직 검증할 가정:
  읽음: cli-pause-feasibility.md, review-tech-findings.md, execution-workspace-review.md, FR-28, NFR-07/08
  확인한 사실: p1-environment-contract.md 2~5절(실행한 조회 명령과 실측값)
  아직 검증할 가정: CLI 도움말의 옵션이 Windows 네이티브에서 실제로 동작하는지,
    이벤트 스트림이 도구 경계를 구별 가능한 형태로 나오는지, 권한 설정이 실제로 쓰기를 막는지
필요한 설계 선택과 이유:
  (1) 계약을 CLI 인자 형태가 아니라 "제어부가 표현할 의미"로 정의 — NFR-07의 종속 금지 요구
  (2) 능력 상태를 doc_only / verified / unsupported / unknown 네 값으로 분리 —
      "도움말에 옵션이 있음"을 "지원함"으로 승격시키지 않기 위함
  (3) outcome에 unknown을 정식 값으로 포함 — 종료 코드만으로 완료를 선언하지 않기 위함(FR-28)
  (4) 어댑터가 자격증명 파일을 읽지 않음 — 인증은 CLI 자체 저장소에 유지(FR-28, NFR-07)
변경할 구성 요소·파일(확정):
  P1-01: p1-environment-contract.md(신규), DEVELOPMENT.md(상태·plan·인계). 제품 코드 없음
  P1-02: p1/harness/run_cli.py(실증용 harness), p1/evidence/(실행 증거와 결과 문서).
         시험 저장소는 %LOCALAPPDATA%\Temp\hads-p1\testrepo, 원본 증거는 같은 경로의 evidence\.
         제품 코드는 아직 없다. harness는 P1 실증 도구이며 P2에서 그대로 제품에 넣지 않는다
실행 순서:
  1. [완료] 시작 절차: git 상태·원격·HEAD 읽기 확인, 안내서 상태표와 실제 상태 대조
  2. [완료] P1 필수 참조와 FR-28·NFR-07/08 확인
  3. [완료] 환경 실측: OS·셸·Python·Git·Node·gh 경로와 버전
  4. [완료] CLI 실측: codex·claude 경로·버전·설치 방식, opencode 다중 경로 조사로 PATH 미조회와 구분
  5. [완료] 인증 구성 확인(존재·모드만, 내용 미조회)과 doctor 진단 요약
  6. [완료] 공통 실행 계약 초안 v0와 capability 표 작성 → p1-environment-contract.md
  7. [완료] 이 plan 기록과 사용자 공유, 상태표·인계 갱신, 로컬 커밋
  8. [완료] P1-02-a: 임시 시험 저장소 준비(시스템 임시 경로, git init, 샘플 파일 2~3개).
     사용자의 실제 프로젝트와 이 설계 저장소는 대상으로 쓰지 않는다
  9. [완료] P1-02-b: harness 최소 구현 — Python으로 CLI를 자식 프로세스로 실행하고
     stdout/stderr 스트림을 소비, 이벤트 원문을 run_id별 파일에 append, 종료·타임아웃 처리
 10. [완료] P1-02-c: 읽기 전용 호출 실증(두 CLI 각각) — 시험 저장소 파일 요약 요청.
     구조화 출력(`codex exec --json`, `claude -p --output-format stream-json`) 실물 스키마 기록
 11. [완료] P1-02-d: 작은 변경 호출 실증 — 시험 저장소의 한 파일에 정해진 한 줄 추가.
     실행 전후 git 상태 비교로 실제 변경 확인
 12. [완료] P1-02-e: 세션 식별·분리 확인 — 작성 호출과 검토 호출의 세션 식별자가 다름을 증거로 확인
 13. [완료] P1-02-f: 권한 경계 확인 — 허용 밖 경로 쓰기를 요청했을 때의 실제 결과 관찰
 14. [완료] P1-02-g: capability 표를 실측으로 갱신(doc_only → verified/unsupported)하고
     실패·거절 사례도 함께 기록
 15. [완료] P1-03 중지·복구 실증 — 결과: p1/evidence/P1-03-results.md
     제어 지점 선택과 근거:
       Codex  → 저장소 로컬 `<repo>/.codex/hooks.json`의 PreToolUse.
                사용자 전역 `~/.codex/config.toml`을 바꾸지 않아도 되고,
                설치 바이너리에 PreToolUse·hooks.json 식별자가 실재함을 확인했다.
                제약: 비관리 hook은 신뢰 승인이 필요하다. 비대화식에서는
                `--dangerously-bypass-hook-trust`가 필요한지 실측하고, 필요하면 제약으로 기록한다
       Claude → `--settings` JSON의 PreToolUse 훅. 세션 한정이라 사용자 설정을 바꾸지 않는다.
                `--include-hook-events`로 훅 수명주기를 스트림에서 함께 관측한다
       app-server 경로는 이번에 쓰지 않는다. 두 CLI에 공통으로 적용 가능한 최소 경로를 먼저 검증한다
     15-a [완료] 연결 상태 파일과 gate hook 구현(p1/harness/gate_hook.py).
          상태가 disconnected면 PreToolUse에서 거부하고, 모든 호출의 시각·도구·판정을 로그로 남긴다
     15-b [완료] harness에 실시간 감시 추가 — 이벤트 스트림에서 tool_call_finished를 N회 관측하면
          연결 상태 파일을 disconnected로 바꾸고 그 시각을 기록한다(단절 주입)
     15-c [완료] 순차 3단계 작업(a.txt → b.txt → c.txt 생성)을 시키고 1회차 완료 직후 단절 주입.
          **부수효과로 검증한다: a.txt는 있고 b.txt·c.txt는 없어야 한다**
     15-d [완료] 훅 없이 같은 작업을 실행해 대조군을 만든다(세 파일 모두 생성되는지)
     15-e [완료] 강제 종료 대조 — 장시간 실행 중 harness가 자식을 종료했을 때
          `.cmd` 진입점 아래 실제 CLI 프로세스와 그 자식이 함께 끝나는지 확인.
          안전 중지와 강제 종료를 같은 지원 수준으로 표시하지 않는다
     15-f [완료] 결과를 capability 표에 반영. 미지원 경로는 unsupported로 명시하고
          해당 기능의 지원을 보류한다. 재연결 대조는 범위 밖이면 미검증으로 남긴다
 16. [완료] P1-04 OpenCode 문서 계약·결론 — 결과: p1/opencode/contract.md
     대상 릴리스 고정: **V2 한 계열만** 사용한다. cli-pause-feasibility.md가 경고한 대로
       V1 server endpoint와 V2 permission 구조를 섞지 않는다. 근거로 쓴 공식 문서는
       /v2/docs/{cli,permissions,build/plugins,build/sdk,api} 다섯 페이지로 제한한다
     연결 방식 후보와 판단 근거:
       (가) `opencode run` 비대화식 CLI — V2 문서에 출력 형식·세션·권한 플래그가 없다.
            구조화 이벤트와 세션 식별을 얻을 수 없으므로 제어 경로로 부적합
       (나) **서버/SDK 경로** — `/api/session` 생성, `/api/session/{id}/prompt`,
            `/api/event` 구독, `/api/session/{id}/permission[/{requestID}/reply]`.
            RunRequest·이벤트·세션·권한을 모두 표현할 수 있어 이쪽을 기준으로 계약을 쓴다
     16-a [완료] 공식 문서에서 확인한 사실만으로 OpenCode V2 어댑터 계약 문서 작성.
          RunRequest/이벤트/RunResult 매핑, 권한 매핑, 미지원·불명 항목 표기
     16-b [완료] 응답·이벤트 fixture 작성. **문서에서 재구성한 것이며 실제 캡처가 아님을
          파일과 문서에 명시한다.** 실행 증거(p1/evidence/)와 다른 디렉터리에 둔다
     16-c [완료] 계약 시험 작성(표준 라이브러리 unittest, 외부 의존성 없음).
          fixture → 정규화 이벤트·결과 변환을 검증하고, **확인 불가 능력이 doc_only/unknown으로
          남아 있는지도 함께 시험한다**. 시험 통과를 실환경 검증으로 표시하지 않는다
     16-d [완료] 세 도구 capability 표의 OpenCode 열을 문서 기준으로 채우고,
          필수 능력의 공백·대안·후속 작업을 명시
     16-e [완료] P1 전체 완료 조건 점검. 남은 미검증 항목과 그 처리(P2 이월/사용자 결정)를 제시
성공 기준:
  AC-1: 세 CLI의 설치·버전·경로·인증 구성 상태가 확인 방법과 함께 기록되고,
        PATH 미조회와 설치 흔적 없음이 구분된다
  AC-2: 비밀값 원문을 읽거나 기록하지 않고도 실행 가능 여부를 판단할 수 있음이 계약에 반영된다
  AC-3: 공통 실행 입력·이벤트·결과 계약 초안이 특정 CLI 인자 구조에 종속되지 않고,
        능력 차이를 숨기지 않는 상태값 체계를 갖는다
  AC-4: P1-02~04의 실증 계획이 이 문서에 남아 다음 세션이 재계획 없이 이어갈 수 있다
  AC-5(P1-02): 두 CLI 각각에 대해 읽기·작은 변경·구조화 결과·세션 분리의 실제 실행 증거가 있고,
        성공/실패/권한 질문이 구분되며 종료 코드만으로 성공을 판정하지 않는다
  AC-7(P1-04): OpenCode 계약이 **단일 V2 문서 계열**에서 나오고, fixture가 재구성물임이
        파일·문서에 표시되며, 계약 시험 통과가 실환경 검증으로 표시되지 않는다.
        필수 능력의 공백과 대안이 구체적으로 적힌다
  AC-6(P1-03): 단절 주입 후 **다음 도구 호출이 실제로 시작되지 않았음**을 부수효과로 확인한다.
        이미 시작한 호출의 결과는 보존된다. 지원되지 않는 CLI·경로는 unsupported로 표시하고
        프롬프트 지시나 프로세스 종료를 안전 중지와 같은 지원 수준으로 적지 않는다
검증 방법:
  AC-1 → `Get-Command -All`, `<tool> --version`, `npm ls -g --depth=0`, `winget list`,
         `Test-Path` 후보 경로, `codex doctor` / `claude doctor`.
         증거: p1-environment-contract.md 1~4절(명령과 실측값 대조 가능)
  AC-2 → 인증 파일은 Test-Path로 존재·크기·시각만 확인. 내용 조회 없음.
         증거: 같은 문서 4절과 이 세션의 명령 이력
  AC-3 → 같은 문서 6~8절을 FR-28·NFR-07 수용 기준과 한 항목씩 대조. 미확인은 unknown으로 남김
  AC-4 → 같은 문서 9절과 이 plan의 15~16번 항목
  AC-5 → 실제 명령·출력·git diff·세션 식별자를 증거로 기록.
         결과: p1/evidence/P1-02-results.md 와 같은 디렉터리의 run별 result.json / stdout.jsonl
  AC-7 → p1/opencode/contract.md 의 모든 주장에 공식 문서 출처를 달고,
         `python -m unittest discover p1/opencode` 로 계약 시험을 실행한다.
         fixture 파일에는 `"_source": "reconstructed-from-docs"` 를 넣는다
  AC-6 → 시험 저장소에서 파일 존재 여부로 판정(a.txt 있음 / b.txt·c.txt 없음).
         대조군(훅 없음)에서는 세 파일이 모두 생기는지 확인해 훅이 원인임을 보인다.
         gate hook 로그의 호출별 시각·도구·판정과 이벤트 스트림 시각을 함께 남긴다
실패·중단 시 상태 보존과 복구 방법:
  P1-01 산출물은 문서뿐이므로 커밋으로 보존한다. 사용자 작업 트리는 건드리지 않는다.
  P1-02는 시스템 임시 경로의 시험 저장소만 사용하고, 중단 시 그 경로와 남은 프로세스를 인계에 기록한다.
  CLI 호출이 실패하면 원문 출력을 남기고 추정으로 성공/실패를 채우지 않는다.
사용자에게 필요한 결정 / 없는 경우 없음:
  현재 없음. 다만 P1-02는 사용자의 기존 Codex·Claude 로그인으로 실제 호출을 하므로
  계정 사용량이 소모된다. 이는 P1 범위("기존 설치·인증을 사용한 최소 실행 harness")에 이미 포함된다.
```
