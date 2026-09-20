# P2-PLAN-01 (완료, 2026-09-20 종료)

이 문서는 [DEVELOPMENT.md](../DEVELOPMENT.md)의 활성 plan 자리에서 옮겨 온 **완료된 plan 원문**이다.
근거 보존이 목적이며 현재 활성 plan은 DEVELOPMENT.md 3절에 있다. 내용은 옮길 때 수정하지 않았다.

성공 기준별 결과와 검증 증거는 [P2-01 실행 결과](../p2/evidence/P2-01-results.md)에 있다.

```text
Plan ID: P2-PLAN-01
단계 / 이번 세션 하위 작업: P2 — 최소 업무 흐름 / P2-01 최소 골격·영속 상태
작성·수정 시점: 2026-09-20 작성
기준 Git 브랜치·커밋 / 기존 미커밋 변경:
  main / 3c8f122 "docs: close P1 with an accepted limitation and hand P2 the carried item"
  시작 시 작업 트리 clean. 사용자 미커밋 변경 없음. origin/main 과 동기 상태
목표와 사용자에게 보일 결과:
  제품 코드의 첫 골격을 만든다. 실제 FastAPI 제어부·SQLite·로컬 Python Runner·React/TS 화면이
  한 줄로 연결되고, 저장 완료로 응답한 기록이 프로세스 재시작 후 복원되며,
  **같은 요청을 다시 보내도 실행이 두 번 일어나지 않음**을 실제 부수효과로 확인한다.
포함 범위:
  (1) Python 런타임 고정과 저장소 로컬 가상환경·의존성 잠금
  (2) implementation-baseline 1절의 디렉터리 책임 구분에 맞춘 최소 골격
  (3) 최소 영속 모델: Owner / Project / Runner·Capability / Case / IntentVersion / Decision /
      Run / RunEvent / ArtifactRef / RequestLog
  (4) 제어 상태·요약(서버 DB)과 Runner 원문 저장(로컬 파일)의 **논리적 분리를 처음부터** 적용
  (5) 로컬 Runner 계약: 등록·능력 보고·배정 수신·이벤트 전송·결과 보고·상태 대조
  (6) React/TS 화면 골격이 실제 API·DB를 읽고 쓰는 연결
  (7) 실행·시험 명령 문서화
  (8) **P1 이월 항목**: run_id 멱등성과 배정 세대(fencing)를 실제 재전송으로 실증
제외 범위:
  의도 여섯 필드 초안·피드백·동의 흐름(P2-02), QG-01·진입 조건 검사와 실제 CLI 실행 연결(P2-03),
  결과 열람·사람 최종 확인 화면 흐름(P2-04), GitHub 연동(P5), 원격·인증·백업(P6),
  사용자의 실제 프로젝트 변경, 사용자 전역 CLI·Python·Node 설정 변경.
  **이번 Runner는 CLI를 실행하지 않는다.** P1 harness(p1/harness/*)는 실증 도구이므로
  제품 코드로 옮기지 않고 그대로 둔다. CLI 어댑터 연결은 P2-03에서 P1 계약을 근거로 한다
적용 결정·요구사항 ID: FR-03(모델 자리만), FR-04, FR-13, FR-15, FR-16, FR-23, FR-29(모델 자리만),
  NFR-01, NFR-03, NFR-09, NFR-12, D-41·42·43·51, 그리고 P1 공통 실행 계약 v0
  (p1-environment-contract.md 6~7절)의 RunRequest·정규화 이벤트·RunResult 필드
읽은 근거 / 확인한 사실 / 아직 검증할 가정:
  읽음: design-draft.md 전체, implementation-baseline.md 전체, intent-artifacts.md 1~3절,
    data-boundary-review.md 1~3절, FR-03/04/13/15/16/23/29, NFR-01/03/09/12,
    p1-environment-contract.md 2·6~8절
  확인한 사실: python 3.12.10 / sqlite3 3.49.1 / node v22.15.1 / npm 10.9.2.
    PyPI·npm registry 조회 가능(fastapi, vite 버전 조회 성공). .gitignore 가 이미
    .venv/ 와 node_modules/ 를 제외하고 있다
  아직 검증할 가정: Windows에서 uvicorn 자식 프로세스를 강제 종료한 뒤 재시작했을 때
    SQLite 기록이 온전히 복원되는지, 원문이 제어부 DB·로그에 실제로 남지 않는지
필요한 설계 선택과 이유:
  (1) **런타임을 Python 3.12.10으로 고정한다.** `python`(3.12)과 `py`(3.14) 기본값이 다르다는
      P1 경고(p1-environment-contract.md 2절 주의 1)를 닫기 위함이다. 3.12를 고른 이유는
      이 PC의 `python` 기본값이고 FastAPI·pydantic 계열의 지원이 넓기 때문이다.
      스크립트는 `py -3.12`로 인터프리터를 명시해 세션마다 달라지지 않게 한다
  (2) 제어부 DB에 원문 본문을 담는 컬럼을 **아예 두지 않는다.** 원문은 Runner 로컬 파일에 두고
      서버는 artifact_id, revision, content_hash, owner_runner_id, availability 만 갖는다
      (data-boundary-review 1절). 나중에 끄는 옵션이 아니라 스키마 수준의 제약으로 둔다
  (3) 멱등성을 **두 층**으로 나눈다. 제어 API는 run_id 를 키로 같은 응답을 돌려주고,
      Runner는 로컬 실행 원장을 보고 이미 실행한 run_id 를 다시 실행하지 않는다.
      한 층만 두면 "응답 유실 후 재배정"(P1 이월 항목의 실제 상황)을 막지 못한다
  (4) 보고에 assignment_generation fencing을 적용한다. 오래된 실행자의 갱신이 최신 상태를
      덮어쓰지 않아야 한다(NFR-03 "지연 도착한 결과가 최신 상태를 덮어쓰지 못하게 한다")
  (5) 실행 결과의 outcome 에 unknown 을 정식 값으로 유지하고 종료 코드만으로 완료로 쓰지 않는다
      (P1 계약 7.2). 이번 executor는 CLI가 아니지만 같은 결과 계약을 쓴다
  (6) Run 실행의 부수효과를 **파일에 기록되는 실행 횟수**로 만든다. 중복 실행 여부를
      로그가 아니라 관측 가능한 부수효과로 판정하기 위함이다(P1-03이 파일 존재로 판정한 것과 같은 방식)
변경할 구성 요소·파일(확정):
  pyproject.toml, requirements.txt, requirements.lock.txt — 런타임·의존성 고정
  domain/ — models.py(공통 모델·상태값), ids.py
  controller/ — config.py, db.py, schema.sql, repository.py, assignments.py, api.py, app.py
  runner/ — config.py, store.py(원문 저장), ledger.py(실행 원장), executor.py(CLI 아님), agent.py
  web/ — Vite + React + TS 최소 화면(프로젝트·Case 목록, Case 상세, Run 생성)
  scripts/ — bootstrap.ps1, run-controller.ps1, run-runner.ps1, run-tests.ps1
  tests/ — 단위·계약·재시작·멱등·데이터 경계 시험
  README.md — 실행·시험 명령 추가, DEVELOPMENT.md — 상태·plan·진행표·인계
  plans/P1-PLAN-01.md — 완료된 P1 plan 원문 이관(내용 무수정)
  데이터 경로: 저장소 아래 var/ (gitignore 추가). 제어부 DB var/controller/controller.sqlite3,
  Runner 원문 var/runner/<runner_id>/artifacts/, 실행 원장 var/runner/<runner_id>/ledger/
실행 순서:
  1. 런타임 고정: py -3.12 -m venv .venv, requirements 작성·설치, 설치 버전을 lock으로 고정.
     .gitignore 에 var/ 추가
  2. domain 최소 모델과 상태값 정의(Case 상태, Run outcome, Decision kind, capability 상태)
  3. controller: schema.sql + db.py(마이그레이션·트랜잭션) + repository.py.
     **원문 컬럼 없음**을 스키마에 주석과 시험으로 고정
  4. controller: api.py — 프로젝트·Case·의도 버전·결정·Run 생성/조회, Runner 등록·능력 보고,
     배정 수신(long poll 아님, 단순 조회), 이벤트 수신, 결과 보고. 모든 쓰기에 요청 키를 받는다
  5. runner: store.py(원문 저장·해시), ledger.py(run_id 원장), executor.py(부수효과 카운터를
     증가시키는 최소 실행기), agent.py(등록 → 배정 조회 → 실행 → 이벤트·결과 보고 루프)
  6. web: Vite React TS 최소 화면. 제어부 API를 실제로 호출해 목록·상세를 표시하고
     Case와 Run을 만든다. npm run build 산출물이 제어부에서 서빙되는지 확인
  7. scripts + README 실행·시험 명령 문서화
  8. 검증 수행(아래 검증 방법) 후 증거를 p2/evidence/P2-01-results.md 에 기록
  9. 변경 diff 검토 → 상태표·진행표·인계 갱신 → 로컬 커밋
성공 기준:
  AC-1: 제어부·Runner·화면이 실제로 연결된다. 화면에서 만든 Case와 Run이 SQLite에 저장되고
        Runner가 그 배정을 받아 실행하며 결과가 화면에 나타난다. mock 응답이 아니다
  AC-2: 저장 완료로 응답한 Project·Case·IntentVersion·Decision·Run·RunEvent가
        제어부 프로세스 강제 종료 후 재시작에서 그대로 복원된다(NFR-01)
  AC-3: **같은 run_id 의 재전송이 중복 실행을 만들지 않는다.** 제어 API 재전송에서도,
        결과 응답이 유실되어 배정이 다시 내려간 경우에도 실행 부수효과는 정확히 1회다.
        (P1에서 이월한 항목. 이 기준을 충족해야 그 이월 항목을 닫는다)
  AC-4: 오래된 assignment_generation 의 결과 보고가 거부되고 최신 상태를 덮어쓰지 않는다
  AC-5: 같은 (run_id, seq) 이벤트를 다시 보내도 이벤트가 중복 저장되지 않는다
  AC-6: 제어부 DB 파일과 제어부 로그 어디에도 원문 본문이 없고, 같은 내용이
        Runner 원문 저장소에는 있다. 서버에는 참조(artifact_id/revision/content_hash/
        owner_runner_id/availability)만 있다(NFR-12, D-51)
  AC-7: Python 런타임이 고정되고, 다른 세션이 같은 명령으로 설치·실행·시험을 재현할 수 있게
        문서화된다(NFR-08). 실행·시험 명령은 실제로 실행해 본 것만 적는다
검증 방법:
  AC-1 → scripts/run-controller.ps1 + scripts/run-runner.ps1 을 띄우고 화면에서
         Case·Run을 만든 뒤, 같은 데이터를 API·DB 조회로 대조한다.
         화면·API·DB 세 곳의 값과 실행 시각을 증거로 남긴다
  AC-2 → 자동 시험: uvicorn을 자식 프로세스로 띄워 기록을 만들고 taskkill /F 로 강제 종료한 뒤
         다시 띄워 같은 ID로 조회한다. 강제 종료 전후 응답을 증거로 남긴다
  AC-3 → 자동 시험 2건. (가) 같은 run_id로 POST를 2회 → run 행 1개, 배정 1개, 카운터 1.
         (나) Runner가 실행을 마친 뒤 결과 보고를 실패시키고 제어부가 같은 run_id를 다시 배정 →
         Runner가 원장을 보고 재실행하지 않고 저장된 결과를 돌려준다. 카운터는 여전히 1.
         카운터는 executor가 파일에 증가시키는 실제 부수효과다
  AC-4 → 자동 시험: generation 1 배정 → generation 2로 재배정 → generation 1 결과 보고가
         409로 거부되고 DB의 run 상태가 바뀌지 않음을 확인
  AC-5 → 자동 시험: 같은 (run_id, seq) 이벤트 2회 전송 후 이벤트 수 확인
  AC-6 → 자동 시험: 알아볼 수 있는 표식 문자열을 원문 본문에 넣어 제출한 뒤,
         controller.sqlite3 파일 **바이트 전체**와 제어부 로그 파일에서 그 표식을 검색해
         발견되지 않음을 확인한다. 같은 표식이 Runner 원문 파일에는 있음을 함께 확인한다
  AC-7 → 새 셸에서 README의 명령만으로 설치·실행·시험을 수행하고 그 출력을 증거로 남긴다.
         python -m pytest 전체 통과 결과와 개수를 기록한다
실패·중단 시 상태 보존과 복구 방법:
  코드·문서는 커밋으로 보존한다. var/ 의 개발용 DB·원문은 커밋하지 않으며 지워도 재생성된다.
  설치가 실패하면 실패한 명령과 출력을 그대로 남기고 다른 버전으로 조용히 바꾸지 않는다.
  시험이 실패하면 실패 상태로 기록하고 통과로 바꾸지 않는다. 중단 시 남은 프로세스
  (uvicorn, runner, vite dev server)와 포트를 인계에 적는다
사용자에게 필요한 결정 / 없는 경우 없음:
  현재 없음. 아래 두 가지는 이미 합의된 범위 안의 구현 선택으로 진행하고 근거를 남긴다.
  (가) Python 3.12.10 고정 — P1이 P2-01에서 고정하라고 넘긴 항목이다
  (나) 저장소 로컬 .venv/ · web/node_modules/ 설치 — implementation-baseline 2절이
      "별도 가상환경과 데이터 경로"를 쓰라고 정했고 .gitignore 에 이미 반영돼 있다.
      사용자 전역 Python·Node·CLI 설정은 바꾸지 않는다
```
