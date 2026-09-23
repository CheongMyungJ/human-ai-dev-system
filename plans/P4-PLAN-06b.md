# P4-PLAN-06b

지식 원문의 서버 저장. 기준: 설계 v0.8 2차 / D-01~90 / **사용자 결정 2026-09-24(D-67 보충: 지식만 원문 PC
경계의 예외)** / [프로젝트 지식](../project-knowledge.md) 5절 / [데이터 경계](../data-boundary-review.md)
2절. 선행: P4-06(스키마 v22, S-025). 세션 S-026.

기준선(S-026 시작, 변경 전, `scripts\run-tests.ps1`): 웹 빌드 성공, 웹 단위 18, pytest 672 통과·1 건너뜀,
P1 계약 18. 시작 상태 `main`/`facd3c8`, 작업 트리 clean, 로컬 추적 ref `origin/main` 과 같음(원격을 새로
조회하지 않음).

범위는 **P4-06b 하나**다. P4-07(선택 추출), UI-04(결정 사항 패널·프로젝트 규칙 화면·검색), 다른 원문(대화·
의도·설계·계획·코드·로그)의 경계 변경, P5·P6 은 넣지 않는다.

## 0. 사용자 결정 (2026-09-24, S-025 에서 확정 — 이 plan 은 그것을 구현한다)

(1) 지식의 적용 내용(짧은 본문·조건·예외)을 서버 DB 에 저장한다. (2) 대화에서 자동 등록된 규칙의 **권위
원문(그 사용자 메시지 한 건)**도 함께 저장한다 — 대화 전체가 아니다. (3) Runner 의 해시 대조·영수증은
유지한다 — 서버가 배정에 본문을 싣고 Runner 는 해시가 맞을 때만 쓴다. (4) 서버 로그에는 본문을 남기지
않는다. (5) 등록 화면·카드에 "지식 내용은 서버에 저장됨, 비밀값을 적지 말 것"을 알린다. (6) 다른 원문의
경계는 바꾸지 않는다.

**이 plan 에서 새 제품 판단은 없다.** 아래 설계 선택(권위 원문의 올리는 시점·미등록 시 삭제, 등록 규칙의
비밀값 문구, 기존 지식의 자동 이행, `target_runner_id` 유지)은 결정 (1)~(6) 안의 상세 설계이며 9절에 적는다.

## 1. 현재 구현과 차이 (코드 대조)

1. **지식 원문은 Runner 에만 있다.** `artifact_ref`(종류 `knowledge`)의 본문은 소유 Runner 의 저장소다.
   수동 등록(`POST /api/cases/{id}/knowledge`)은 `_knowledge_intake` → `open_intake` 로 **중계**하고 Runner
   가 저장을 보고해야 `available` 이다(그 사이 `pending` → 필수면 진입 검사의 핵심 미확인). 자동 등록은
   Runner 의 `_store_knowledge` 가 자기 저장소에 넣고 `register_artifact` 로 참조만 올린다.
2. **배정에 본문이 없다.** `assignment_payload` 의 `context_refs` 는 참조·해시·등급·메타데이터뿐이고 Runner
   `load_context` → `_read_verified` 가 **자기 저장소**에서 읽는다. 다른 PC 의 실행은 영수증 `missing` →
   핵심이면 `required_context_unavailable` 로 시작하지 않는다. 진입 검사는 `artifact_ref.availability`(소유
   PC 기준 `available`)만 보므로 이것을 미리 알지 못한다 — 실행이 늦게 실패하고 재시도까지 한다(P4-06 결과
   4절).
3. **권위 원문도 같다.** `knowledge_source` 는 요청을 연 사용자 메시지 원문(그 PC 소유)이다. 다른 PC 에서는
   그것도 `missing` 이다 — 필수와 함께 핵심이라 본문만 옮겨도 여전히 보류다.
4. **열람은 소유 PC 로 간다.** `open_read_request` 가 `owner_runner_id` 에 요청을 넣고 Runner 가 올린다.
   화면(`bodies.ts`)은 소유 PC 미연결이면 요청을 만들지 않고 "연결 필요"를 보인다.
5. **로그는 본문을 남기지 않는다.** 접근 로그는 메서드·경로·상태·시간뿐이고(`app.py`), 처리기 오류 로그는
   단계·예외 이름뿐이다. `run.knowledge_report_json`(≤ 8000)은 메타데이터·참조만 담는다.
6. **경계 시험.** `tests/test_knowledge.py` AC-15 는 제어부 데이터 폴더의 **모든 파일**에 표식이 없다고
   단언한다(이제 DB 에는 있어야 한다). `tests/test_data_boundary.py` 는 특정 표들의 본문 컬럼 부재와 여러
   원문 표식의 DB·로그 부재를 본다 — 지식 외 원문의 검사는 그대로 성립해야 한다.
7. **화면.** 관리 화면 지식 패널은 "원문은 PC 에 있다"고 적고 등록에 PC(Runner)를 요구한다. 새 화면의 등록
   카드는 "원문과 함께 주입된다"고만 적는다.

## 2. 범위

| 넣는 것 | 넣지 않는 것 (담당) |
|---|---|
| **서버 본문 표**(v23 `knowledge_body`): `(artifact_id, revision)` 별 본문·해시·크기. 지식 원문(종류 `knowledge`)과 **권위 사용자 메시지 한 건**만 들어간다. `artifact_ref` 는 그대로(소유 PC 는 등록한 대화의 PC = 출처, 가용성은 서버 보관이면 `available`) | 다른 종류 원문의 서버 저장, `artifact_ref` 구조 변경 |
| **수동 등록·개정**: 중계 대신 서버 저장. 내용 ≤ 4,000 자. 소유 PC 가 미연결이어도 등록된다 | 결정 사항 패널·프로젝트 규칙 화면(UI-04) |
| **자동 등록**: Runner 가 결과 보고 **전에** 옮겨 적은 내용과 **그 응답의 지시 원문(= 요청을 연 사용자 메시지)**을 서버에 올린다(`POST /api/runner/knowledge-originals`, 해시 대조). 처리기가 그 보고에서 하나도 등록하지 못하면 권위 메시지 본문은 지운다 | 대화 전체·다른 메시지의 서버 저장 |
| **기존 지식의 이행**: 서버가 본문이 없는 지식 원문·권위 메시지를 소유 PC 별로 "올릴 것"으로 내려주고(`GET /api/runner/{id}/knowledge-uploads`) Runner 가 연결될 때 올린다. 올리기 전까지는 P4-06 그대로(소유 PC 만 읽음) | 사람의 수동 이행 절차 |
| **배정에 본문 싣기**: 서버 본문이 있는 참조는 `context_refs` 항목에 `body_b64` 를 붙인다. Runner 는 해시가 맞을 때만 쓰고(영수증 `read`), 다르면 `hash_mismatch`(자기 저장소로 대신하지 않는다), 없으면 지금처럼 자기 저장소 | 실행 중 동적 주입 |
| **열람**: 서버 본문이 있는 원문의 열람 요청은 서버가 바로 채운다(PC 연결 무관) | 화면의 "연결 필요" 판정 일반화(UI-04) |
| **조회·화면**: 버전마다 `storage`(server / runner = 이행 대기), 권위 메시지의 `source_storage`. 지식 패널·등록 카드에 "서버에 저장됨 · 비밀값을 적지 말 것", 패널의 "내용 보기" | — |
| **등록 규칙(지시문)**: 내용과 그 사용자 메시지가 서버에 저장된다는 것과, 비밀값이 들어 있으면 블록을 붙이지 말고 글로 알리라는 줄 | AI 가 비밀값을 판정한다는 보장 |
| **문서**: data-boundary 2·5절, project-knowledge 5절, AC-35·36, README, decisions 표시를 구현 사실로 고침 | — |

## 3. 설계

### 3.1 저장 (스키마 v23)

```
knowledge_body(artifact_id, revision, body BLOB, content_hash, byte_size, purpose, stored_by, stored_at)
    PK(artifact_id, revision), FK → artifact_ref(artifact_id, revision)
    purpose IN ('knowledge', 'authority_message')
    CHECK byte_size = length(body), CHECK byte_size <= 262144
```

- `body` 는 **이 결정의 유일한 본문 컬럼**이다. `tests/test_data_boundary.py` 의 "새 표에 본문 컬럼 없음"은
  이 표를 명시 예외로 적고(결정 참조), 지식 외 원문 표식은 지금처럼 DB 에 없어야 한다.
- 지식 내용의 상한은 **4,000 자**(`domain.knowledge.MAX_CONTENT_CHARS`, 자동 등록에 이미 있음)를 수동
  API 에도 건다. 권위 메시지는 그 메시지 그대로이며 표의 바이트 상한(256 KiB, P4-04 인라인 한도 기본값)만
  받는다.
- `artifact_ref` 는 바꾸지 않는다. 서버 보관 원문의 `owner_runner_id` 는 **등록한 대화의 PC**(출처)이고
  `availability` 는 서버가 저장한 순간 `available` 이다 — "소유 Runner 가 확인함" 대신 "서버가 저장함"이며
  조회의 `storage = server` 가 그 사실을 드러낸다.
- **데이터 이행 없음.** v22 의 지식 원문·권위 메시지는 소유 PC 에 있고 `storage = runner` 다. 아래 3.4 의
  이행으로 채운다. 없던 본문을 지어내지 않는다.

### 3.2 등록 경로

- **수동**(`POST /api/cases/{id}/knowledge`, `POST /api/knowledge/{id}/versions` 의 새 내용):
  `Repository.store_knowledge_original(case_id, runner_id, body, summary)` 가 한 트랜잭션으로 `artifact_ref`
  (종류 `knowledge`, `available`, 소유 = `target_runner_id`)와 `knowledge_body` 를 넣고, 이어 기존
  `register_knowledge` 를 부른다. **중계·접수 행이 없다.** `target_runner_id` 는 출처로 남기되 연결돼 있을
  필요가 없다(등록된 Runner 면 된다). 종료된 Case 에서도 등록된다(P4-06 문서 그대로).
- **자동**: Runner `_store_knowledge` 가 항목마다 `POST /api/runner/knowledge-originals`
  `{runner_id, case_id, kind: knowledge, artifact_id, revision: 1, content_b64, content_hash, byte_size,
  summary}` 를 올린다(서버가 해시·크기를 대조해 참조 + 본문을 만든다. 같은 해시의 재전송은 그대로, 다른
  해시는 409). 이어 **그 응답의 지시 원문**(요청을 연 사용자 메시지 — Runner 가 이미 해시를 대조해 읽었다)을
  같은 끝점에 `kind: user_message` 로 올린다(참조가 이미 있으므로 본문만, 해시가 참조와 같아야 하고 소유
  Runner 만 올릴 수 있다). Runner 는 새 지식 원문을 자기 저장소에 **두지 않는다** — 집은 서버다.
- **처리기**(`apply_knowledge_report`): 등록은 P4-06 그대로. 보고 처리 뒤 **그 실행의 항목이 하나도 등록되지
  않았으면** 권위 메시지 본문을 지운다(다른 버전이 그 메시지를 권위로 가리키면 남긴다). 등록된 항목의 원문은
  거부된 항목의 것도 남는다(P4-06 에서 Runner 에 남던 것과 같다 — 가리키는 버전 없는 원문).

### 3.3 주입

- `assignment_payload`: `context_refs` 의 각 항목에 대해 서버 본문이 있고 인라인이면 `body_b64` 와
  `body_source = "server"` 를 붙인다. 참조의 `content_hash` 는 그대로 간다. 역할과 무관하게 **그 원문의
  서버 본문이 있으면** 싣는다 — 같은 사용자 메시지가 `conversation_user_message` 로 들어가는 실행에서도 같은
  본문·같은 해시다.
- Runner `load_context`: `body_b64` 가 있으면 그것을 해시와 대조한다 — 같으면 `read`, 다르면
  `hash_mismatch`(**자기 저장소로 대신하지 않는다** — 서버가 준 것이 다른 원문이면 그 실행에 넣지 않는다).
  없으면 지금처럼 자기 저장소에서 읽는다. 영수증 형식·검사(`check_receipt`)는 그대로다.
- 진입 검사는 바꾸지 않는다. 서버 보관 원문은 만들 때부터 `available` 이므로 `_unavailable_core` 가 PC
  연결과 무관하게 통과한다. 이행 전(`storage = runner`)의 옛 지식은 P4-06 그대로 — 다른 PC 에서 `missing`
  으로 늦게 드러난다. 그 사실을 `knowledge_view` 의 `storage` 가 보인다.
- `list_context_refs`·`run_knowledge_view` 에 `body_source`(server / runner)를 더한다.

### 3.4 이행(기존 지식)과 올릴 것

- `GET /api/runner/{runner_id}/knowledge-uploads`: 이 Runner 가 소유하고 `available` 이며 **서버 본문이 없는**
  원문 중, 어떤 지식 버전(상태 무관 — 이력 열람도 서버가 채운다)의 원문이거나 권위 메시지인 것. 참조·해시만.
- Runner `upload_knowledge_originals()`(제어 루프, 열람 다음): 자기 저장소에서 읽어 해시가 맞는 것만 올린다.
  없거나 다르면 올리지 않고 건너뛴다(지어내지 않는다 — 그 원문은 `storage = runner` 로 남는다).
- 수동 등록에 `source_message_id` 를 준 경우도 같은 길이다 — 서버는 그 메시지 본문이 없으므로 올릴 것에
  넣고 소유 PC 가 연결되면 채운다.

### 3.5 열람

`open_read_request`: 서버 본문이 있으면 요청을 만들면서 바로 `relayed` 로 두고 본문을 중계 버퍼(요청 id)에
넣는다 — `GET /api/read-requests/{id}` 가 지금 경로 그대로 내려준다. 소유 Runner 는 이 요청을 보지 않는다.
없으면 지금처럼 소유 PC 에 넣는다.

### 3.6 화면·지시문

- 관리 화면 지식 패널: 안내를 "적용 내용과 자동 등록의 권위 메시지는 **서버에 저장**된다 — 비밀값(토큰·
  비밀번호·키)을 적지 말 것"으로 바꾸고, 버전마다 `서버 저장` / `PC 에만(이행 대기)` 표시, 현재 버전의
  "내용 보기"(열람 경로, PC 연결 무관). 등록에 PC 가 여전히 필요하다는 문구는 "출처 PC" 로 고친다.
- 새 화면 등록 카드: "이 규칙의 적용 내용과 이 대화에서 한 그 말 한 건은 서버에 저장된다 — 비밀값이 들어
  있으면 무효로 한다" 한 줄.
- Runner 등록 규칙(`KNOWLEDGE_REGISTRATION_RULE`): "content 와 사용자의 그 메시지는 서버에 저장된다. 비밀값
  (토큰·비밀번호·키·개인정보)이 들어 있으면 블록을 붙이지 말고 글로 알린다" 한 줄. AI 의 판정이며 시스템이
  비밀값을 검사하지 않는다(9절).

## 4. 성공 기준

| AC | 기준 |
|---|---|
| AC-1 | 수동 등록이 중계 없이 서버에 저장된다: 201, 접수 행 없음, 바로 `available`·`storage = server`, `knowledge_body` 의 해시 = 참조 해시. 소유 PC 가 미연결(heartbeat 오래됨)이어도 등록된다 |
| AC-2 | 자동 등록: Runner 가 결과 전에 옮긴 내용과 권위 메시지를 올려 둘 다 `knowledge_body` 에 있다. `run.knowledge_report_json`·`knowledge_version`·`intake` 에는 본문이 없다. 등록 결과(키·권위·출처)는 P4-06 그대로 |
| AC-3 | **두 PC**: PC A 의 대화에서 자동 등록된 필수 규칙이 PC B 의 업무 실행(의도 초안·결합 기록·구현·검증)에 `knowledge_required`+`knowledge_source` 로 들어가고 영수증이 둘 다 `read`, 지시문에 두 원문이 있고, Manifest 가 제공이다. PC B 의 저장소에는 그 원문이 없다 |
| AC-4 | PC A 미연결에서도 AC-3 이 성립한다(진입 검사 통과, `read`) |
| AC-5 | 해시: 서버 본문을 바꾸면 Runner 영수증 `hash_mismatch` 로 시작하지 않는다(`required_context_unavailable`, CLI 호출 없음) — 자기 저장소로 대신하지 않는다. 서버 본문도 자기 저장소 본문도 없으면 `missing` 이다(P4-06 AC-6 의 의미 유지) |
| AC-6 | 열람: 서버 본문이 있는 원문의 열람 요청은 Runner 없이 바로 채워지고 해시가 맞는다 |
| AC-7 | 이행: 소유 PC 에만 있는 옛 지식(v22 방식)은 `storage = runner` 이고 올릴 것 목록에 있으며, 소유 PC 가 돌면 올라와 `server` 가 되고 다른 PC 의 실행이 읽는다. 올리기 전 다른 PC 는 `missing`(P4-06 그대로) |
| AC-8 | 권위 메시지 정리: 그 응답에서 하나도 등록되지 않으면(전부 거부) 메시지 본문을 지운다. 하나라도 등록되면 남는다 |
| AC-9 | 크기: 수동 4,000 자 초과 422. 서버 끝점은 해시·크기 불일치·소유 아님·다른 종류를 409 로 거부한다 |
| AC-10 | 데이터 경계: 지식 표식·권위 메시지 표식은 DB 에서 **`knowledge_body` 에만** 있고 로그에 없다. 지식 외 원문(의도·피드백·답변·설계·응답 본문·권위가 아닌 메시지)은 지금처럼 DB·로그에 없다(기존 경계 시험 통과) |
| AC-11 | v22 → v23: 표가 생기고 비어 있으며, 옛 버전은 `storage = runner`·올릴 것에 나온다. 멱등. 데이터를 지어내지 않는다 |
| AC-12 | 화면: 패널 안내(서버 저장·비밀값)·`서버 저장` 표시·"내용 보기", 카드 안내(브라우저 시험) |
| AC-13 | 실제 CLI: 같은 호스트의 **두 Runner 프로세스**와 실제 `codex` — A 의 대화에서 규칙 등록 → A 종료 → B 의 다른 대화 업무 실행에 규칙·권위 원문 주입·영수증 `read`·Manifest 제공 |
| AC-14 | 강제 축·권한·준수 의미는 그대로(주입은 준수의 증거가 아니다). 다른 원문 경계 변경 없음 |

## 5. 검증

- 순수: 없음(규칙 변경 없음). `split_knowledge` 의 4,000 자 상한은 그대로.
- 제어부·Runner(`tests/test_knowledge_server.py`, `processing_harness` + **둘째 Runner**(`runner-test-2`,
  별도 저장소·가짜 CLI)): AC-1~11. `tests/test_knowledge.py` 의 기존 시험 셋의 **의미 검토** — AC-15 단언
  (DB 에 없음 → `knowledge_body` 에만 있고 로그에 없음), AC-6 시험(Runner 파일 삭제 → 서버 본문 삭제·변조로
  같은 의미를 봄, `pending` 하위 사례는 서버 저장에서 성립하지 않아 "바로 `available`" 로 바꿈), 이행 시험
  이름은 그대로. `tests/test_data_boundary.py` 에 `knowledge_body` 예외와 "그 표 밖에는 없음"을 더한다.
  검사를 지우지 않는다.
- 브라우저(`tests/test_web_shell.py`): 기존 지식 시험에 패널 안내·저장 표시·"내용 보기"·카드 안내.
- 전체 `scripts\run-tests.ps1`.
- **실제 CLI 라이브**(`p4/live/p406b_two_pcs.py`, 제품 코드 import 없음): AC-13. 실행하지 못하면 미수행으로
  적는다.

## 6. 경계

- 지식 외 원문의 경계는 그대로다 — 서버 본문 표에는 지식 원문과 권위 메시지 한 건만 들어간다. 대화 전체·
  응답·의도·설계·계획·코드는 여전히 PC 에만 있다.
- 서버 저장은 권한·동의·인수·준수가 아니다. Runner 가 서버 본문을 읽었다는 영수증은 "제공했다"이지 "지켰다"
  가 아니다.
- 이행은 소유 PC 가 연결될 때 일어난다. 연결되지 않는 PC 의 옛 지식은 `storage = runner` 로 남고 다른 PC 는
  여전히 읽지 못한다 — 지어내지 않는다.

## 9. 알려진 한계·설계 선택

- **권위 메시지는 응답 시점에 올라간다.** AI 가 블록을 붙인 응답의 지시 원문(그 사용자 메시지)을 Runner 가
  결과 전에 올리고, 처리기가 하나도 등록하지 못하면 지운다. 결정과 삭제 사이의 짧은 창에 그 메시지 본문이
  DB 에 있다. 대안(중계 버퍼에 잡아 두고 등록 때 확정)은 제어부 재시작의 기동 복구에서 본문을 잃어 권위
  원문 없는 등록을 만든다 — 그 퇴화 경로를 두지 않기 위해 이쪽을 골랐다.
- **비밀값은 시스템이 검사하지 않는다.** 화면·카드·등록 규칙이 알릴 뿐이다. 등록된 뒤 알게 되면 무효화
  (상태만 바뀌고 본문은 이력으로 남는다)다 — 본문 삭제 경로는 이 plan 에 없다.
- **Runner 는 새 지식 원문의 사본을 두지 않는다.** 서버 본문이 유일한 집이다. 서버 백업이 지식 본문을
  포함한다(P6-04 에서 백업 범위 문서를 고칠 때 반영).
- **옛 지식의 이행은 소유 PC 연결에 달렸다.** 자동이지만 즉시가 아니다.
