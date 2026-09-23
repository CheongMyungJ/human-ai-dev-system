# P4-PLAN-07

선택적 지식 추출. 기준: 설계 v0.8 2차 / D-01~90 / **D-67**(의미 있는 발견을 기존 작업 결과에서
선택적으로 추출, AI 새 규칙 제안은 후보, 중복은 근거 추가·버전 대체로 정리, 추출은 완료를 막지
않음) / [프로젝트 지식](../project-knowledge.md) 2·3·6절 / [품질 게이트](../quality-gates.md) QG-08 /
[완료](../completion-lifecycle.md) 지식 절. 선행: P4-06(스키마 v22, 등록부·자동 활성 등록·주입),
P4-06b(v23, 지식 원문의 서버 저장). 세션 S-027.

기준선(S-027 시작, 변경 전, `scripts\run-tests.ps1`): 5절 끝에 있다. 시작 상태 `main`/`c0c49fc`, 작업
트리 clean, `git fetch` 뒤 `origin/main` 과 같음.

범위는 **P4-07 하나**다. UI-04(결정 사항 패널·프로젝트 규칙 화면·검색·알림), QG-08 의 **독립 AI
검토 실행**, 참고 지식의 **자동 활성화**(0절), 여러 Runner 의 배정 경로(P6-01), P5·P6 은 넣지 않는다.

## 0. 제품 판단 — 이 세션이 물을 수 없어 보수적 기본값으로 간다

인계(DEVELOPMENT.md 1.10절)는 "참고 지식 자동 활성화의 조건" 을 새 제품 판단으로 표시했다. 이
세션은 사용자에게 물을 수 없는 자율 실행이므로 **가장 좁은 쪽**으로 정하고 인계에 질문을 남긴다.

- **자동 활성화는 하지 않는다.** AI 가 낸 모든 후보(`ai_proposal`)는 사람이 활성화할 때까지 후보다
  (D-67 "AI의 새 규칙 제안은 후보이며 의무를 만들지 않음", P4-06 의 DB CHECK 그대로). project-knowledge
  2절의 "관찰·운영 팁은 근거와 조건을 확인하여 참고 지식으로 자동 활성화**할 수 있다**" 는 허용이지
  요구가 아니며, 그 조건은 사용자가 정한다.
- 대신 **활성화의 확인(QG-08)을 값으로 만든다**(3.4절 `adoption_check`). 조건이 확정되면 그 확인의
  통과를 조건으로 참고 후보를 자동 활성화하는 것은 이 위에 얹는 작은 후속 작업이다 — 지금은 사람의
  활성화에만 쓴다.
- **사용자에게 물을 제안 조건**(인계에 적는다): 효력 `reference` 이고 종류가 `operation`·`known_problem`
  이며, 근거가 **서로 다른 실행 둘 이상**(그중 하나는 종료 코드 0 명령이 있는 검증·분석 실행)이고,
  범위가 관측한 저장소로 좁혀져 있고, 반증·충돌 관계가 없고, 채택 확인에 막는 항목이 없을 때만.
  이 조건도 제안이며 사용자 확정 전에는 적용하지 않는다.

나머지(추출 계기·자리, 중복 연결, 후보 → 활성의 확인 수준, Case 브랜치 사실의 범위, 예산 부족의
표시)는 D-67·project-knowledge 3절 안의 상세 설계 선택이며 9절에 적는다.

## 1. 현재 구현과 차이 (코드 대조)

1. **등록 블록은 논의 응답에만 있다.** `report_result` 는 `knowledge_report` 를 `discussion_reply` 외
   목적에서 409 로 거부하고, `assignment_payload` 의 `knowledge_index` 와 지시문의 등록 규칙
   (`KNOWLEDGE_REGISTRATION_RULE`)도 논의 응답에만 붙는다. **작업 결과**(검증·분석·실험·구현 실행)에서
   후보를 남길 길이 없다 — P4-07 이 채울 자리다.
2. **블록의 모든 항목이 사용자 권위로 활성 등록된다.** `apply_knowledge_report` 는 항목을 전부
   `user_statement` 활성으로 등록한다. AI 의 관찰·제안이 블록에 들어오면 사용자 말의 권위를 빌려 활성
   필수가 된다(P4-06 이 "옮겨 적기의 충실성은 판정하지 않는다" 로 적은 위험의 한 갈래). 항목에 "이것은
   내 제안이다" 라고 적을 표지가 없다.
3. **새 버전은 언제나 이전 버전을 대체한다.** `register_knowledge(knowledge_id=…)` 는 이전 현재 버전을
   `superseded` 로 바꾼다. AI 후보를 기존 항목의 새 버전으로 넣으면 **활성 규칙이 후보에 밀려난다.**
   후보와 기존 항목의 관계(근거 추가·대체 제안·반증)를 적을 자리가 없다.
4. **활성화는 상태만 본다.** `activate_knowledge` 는 후보인지 보고 새 버전(`user_decision`)을 만든다.
   QG-08 의 근거·범위·상태·버전·충돌 확인이 없고, 범위를 좁혀 활성화하거나 **다른 항목의 새 버전으로**
   적용하는 길이 없다.
5. **중복 후보를 잇지 않는다.** 같은 내용을 두 실행이 보고하면 항목이 둘 생긴다.
6. **후보에 당시 코드·환경이 없다.** `source_run_id` 만 있어 저장소·기준 커밋·도구 판은 실행을 따라가야
   안다. 주입 머리에도 없다.
7. **화면.** 관리 화면 지식 패널의 "활성으로" 는 사유 한 줄만 받는다. 새 화면은 논의 응답 아래의 등록
   카드뿐이라 업무에서 나온 후보를 보이지 않는다.
8. **가짜 CLI.** 후보 블록을 내는 표지(`HADS_FAKE_*`)가 없다.
9. **경계 시험.** `tests/test_data_boundary.py` 는 지식 표 여섯의 본문 컬럼 부재와 `knowledge_body` 가
   유일한 본문 표임을 본다 — 새 표·컬럼도 같은 규칙을 지켜야 한다.

## 2. 범위

| 넣는 것 | 넣지 않는 것 (담당) |
|---|---|
| **작업 결과의 후보 블록**: 검증·분석·실험·구현 실행이 응답 끝에 선택적 `hads-knowledge` 블록으로 **후보**(최대 3건, 근거 한 줄)를 남긴다. Runner 가 원문을 서버에 올리고 결과 보고에 참조만 싣는다. 제어부가 `ai_proposal` **후보로만** 등록한다 | 별도 추출 실행·추출 목적(`RunPurpose`)·추출 의무. QG-08 독립 AI 검토 실행 |
| **논의 응답의 제안 표지**: 등록 블록 항목의 `proposal: true` 는 사용자 말이 아니라 AI 제안이며 후보로 등록된다(권위 메시지 없음). 사람이 "이 업무에서 배운 것을 정리해줘" 라고 하면 이 길로 후보가 생긴다 — 이것이 "별도 실행" 의 자리다(요청 하나 = 논의 응답 하나, 예산은 그 응답의 것) | 대화의 명시 규칙 등록 규칙 변경(P4-06 그대로) |
| **중복·관계 정리**: `supports`(근거 추가 → 새 항목 없이 근거 행), 같은 내용(해시) → 근거 행(중복 연결), `supersedes`(대체 제안 → 관계를 가진 새 후보, 기존 활성은 그대로), `contradicts`(반증 → 관계를 가진 새 후보, 자동 무효 없음) | 자동 충돌 탐지, 의미 비교로 중복 판정 |
| **QG-08 채택 확인**(`domain.knowledge.adoption_check`): 원문 가용성·근거·범위·상태·버전·충돌·반증 대상의 상태를 값으로 낸다. 막는 항목이 있으면 활성화 거부(사유 코드), 경고는 새 버전에 기록. **범위 축소·효력 조정·다른 항목의 새 버전으로 적용**을 활성화가 받는다 | 참고 후보의 자동 활성화(0절), 독립 AI 검토 |
| **관측 문맥**: 후보 버전에 당시 실행의 저장소·기준 커밋·도구 판·Case 를 남기고(`observed_json`) 주입 머리와 화면에 보인다. Case 브랜치의 사실을 기본 브랜치의 사실로 적지 않는다 | 커밋 변경으로 지식을 만료시키는 규칙(project-knowledge 2절 "모든 커밋 변경으로 만료시키지 않는다") |
| **저장(v24)**: `knowledge_version` 에 관계·관측·채택 컬럼, `knowledge_evidence` 표, `knowledge_intake` 에 `evidence` 상태. 데이터 이행 없음 | 지식 외 원문 경계 변경 |
| **화면**: 관리 화면 지식 패널의 후보 행(관계·근거·관측·채택 확인 결과·범위 축소 활성화·다른 항목으로 적용), 새 화면의 **후보 카드**(이 업무에서 나온 후보 목록 → 관리 화면) | 결정 사항 패널·프로젝트 규칙 화면(UI-04) |
| **문서**: project-knowledge 3절·6절, quality-gates QG-08 행, README, DEVELOPMENT, 수용 표 AC-32 표시 | — |

## 3. 설계

### 3.1 추출 계기와 자리

- **자리는 기존 실행이다**(project-knowledge 3절 "기존 작성·검토·완료 실행에서 해당 근거를 이미
  다루었다면 그 결과에 후보를 함께 남길 수 있다"). `verification_run`·`limited_analysis`·
  `local_experiment`·`feature_implementation` 의 지시문 끝에 **추출 규칙**(`KNOWLEDGE_EXTRACTION_RULE`)이
  붙고, 그 실행이 아래 계기 중 하나를 실제로 겪었을 때만 응답 끝에 `hads-knowledge` 블록을 둔다.
  계기: 비자명한 문제의 원인·해결을 확인, 반복되는 문제, 구조·계약이 코드와 다르게 관측됨, 기존 지식과
  다른 관측(반증), 실행·환경 조건(빌드·시험·도구)의 비자명한 사실. 없으면 붙이지 않는다 — **후보 없는
  실행·Case 는 정상이다.**
- 항목: `kind`·`obligation`·`summary`·`content`(≤ 4,000 자, 서버 저장, 비밀값 금지)·`repository`
  (이 실행의 저장소 이름 — 제어부가 준다)·`paths`·`activities`·`relates_to`(기존 키 또는 null)·
  `relation`(`supports`/`supersedes`/`contradicts` 또는 null)·`basis`(어떤 명령·관측이 근거인지 한 줄).
  한 실행 최대 **3건**(`MAX_CANDIDATES_PER_RUN`), 넘는 항목은 `too_many_items` 거부.
- 추출 비용은 그 실행의 사용량 안에 있다 — **추가 호출이 없다.** 그 실행이 예산으로 거부되면 후보도
  없고, 그것은 그 실행의 진입 기록이다(별도 "추출 미처리" 상태를 만들지 않는다 — 9절).
- 별도 실행이 필요할 때: 사람이 논의 응답으로 청한다("이 업무에서 재사용할 것을 정리해줘"). 논의
  응답의 등록 규칙에 **`proposal: true`** 항목 형식을 더해, 사용자가 정하지 않은 AI 관찰·제안은 그 표지로
  붙이게 한다 → 후보 등록(`ai_proposal`, 권위 메시지를 올리지 않는다). 종료 Case 의 설명 응답도 같다.

### 3.2 보고와 처리

- Runner(`_produce_for_purpose`): 네 목적의 응답에서 `split_knowledge` 로 블록을 떼어 `knowledge_items`
  로 두고 나머지 글로 기존 파싱(JSON 산출물)을 한다. 실행 결과 원문에서도 블록을 뗀다(논의 응답과
  같은 규칙 — 블록은 기계용). `_store_knowledge(with_authority=False)` 가 원문을 서버에 올리고
  (`kind = knowledge`, P4-06b 경로 그대로) 보고 항목을 만든다 — **권위 메시지는 올리지 않는다.**
  논의 응답의 `proposal: true` 항목은 보고에 그대로 실린다(권위 메시지는 그 응답에 사용자 말 항목이
  하나라도 있을 때만 올린다).
- 제어부 `report_result`: `knowledge_report` 를 `discussion_reply` + 네 목적에서 받는다(다른 목적은
  409 그대로). 기록은 결과와 같은 트랜잭션(P4-06 그대로), 적용은 뒤에.
- **적용 자리**: `runner_result` 의 결과 뒤 훅에서 `apply_extraction_report(run_id)` — 네 목적의 보고를
  처리기·진행기 켜짐과 무관하게 한 번 처리한다(`knowledge_intake` 멱등). 논의 응답의 보고는 P4-06 대로
  처리기가 `apply_knowledge_report` 로 처리한다(`proposal: true` 항목은 거기서 후보로 갈린다).
- 처리 규칙(`_apply_report_items`, 두 경로가 공유):
  1. 실행이 `completed` 가 아니면 `run_not_completed`(논의는 `reply_not_completed` 그대로).
  2. `parse_report_item` → 종류·효력·요약·원문 참조·범위 검사(P4-06 그대로) + `relates_to`/`relation`/
     `basis`/`proposal` 검사. `relation` 이 있는데 `relates_to` 가 없거나 모르는 키면 `unknown_related_key`.
  3. 원문이 서버에 없으면 `content_not_stored`(참조는 있는데 본문이 없는 경우 포함).
  4. **같은 내용**(원문 해시)이 이 Project 의 현재 버전(후보·활성)에 이미 있으면 새 항목을 만들지 않고
     그 항목에 **근거 행**(`duplicate`)을 남긴다 → intake `evidence`.
  5. `relation = supports` 면 새 항목 없이 대상 항목에 근거 행(`supports`) → intake `evidence`.
  6. 그 밖에는 새 항목 `K-NNN` 을 **후보**(`ai_proposal`·`candidate`)로 등록한다. `relates_to`·`relation`
     (`supersedes`/`contradicts`)을 버전에 적는다 — **대상 항목의 버전 사슬은 건드리지 않는다.**
     `observed_json` = {run_id, purpose, case_id, repository_id, repository_name, base_commit, tool_version}
     (실행·작업공간에서 읽는다; 모르면 null). `reason_summary` = "추출 근거: {basis}".
  7. 논의 응답의 사용자 말 항목은 P4-06 그대로 `user_statement` 활성. `proposal: true` 항목은 6 과 같이
     후보이며 `source_message_id` 를 적지 않는다.
- 후보의 범위는 AI 가 말한 대로 적는다(저장소 실행에서 `repository: null` 이면 Project 범위 후보).
  넓힘의 위험은 활성화의 확인이 본다(`scope_wider_than_observed`) — 후보는 규칙이 아니므로 등록 시점에
  범위를 바꾸지 않고, 관측 문맥을 함께 남겨 사람이 좁힐 수 있게 한다.

### 3.3 저장 (스키마 v24)

```
knowledge_version  + relates_to_knowledge_id TEXT REFERENCES knowledge_item(id)
                   + relation TEXT CHECK (relation IN ('supports','supersedes','contradicts'))
                   + observed_json TEXT CHECK (length <= 1000)     -- 당시 실행·저장소·기준 커밋·도구
                   + adoption_json TEXT CHECK (length <= 2000)     -- 활성화 때의 QG-08 확인 결과
knowledge_evidence(id, knowledge_id, version_id NULL, kind IN ('supports','duplicate'),
                   source_run_id, source_case_id, source_report_index, artifact_id, artifact_rev,
                   summary ≤ 200, recorded_by, created_at, UNIQUE(source_run_id, source_report_index))
knowledge_intake   state IN ('registered','refused','evidence') + evidence_id REFERENCES knowledge_evidence
                   CHECK ((state='registered') = (knowledge_version_id IS NOT NULL))
                   CHECK ((state='evidence') = (evidence_id IS NOT NULL))
```

- `knowledge_intake` 는 `_rebuild_table` 로 다시 만든다(CHECK 변경). 행은 그대로 옮긴다.
- **데이터 이행 없음.** 옛 버전의 새 컬럼은 NULL — "관측 문맥 없음·채택 확인 전" 이지 값이 아니다.
- 근거 행의 `artifact_id` 는 그 실행이 올린 지식 원문(서버 본문)이다 — 사람이 "무엇을 근거로 봤는가"
  를 열람할 수 있다. 본문 컬럼은 없다(`knowledge_body` 만).

### 3.4 QG-08 채택 확인 (`domain.knowledge.adoption_check`)

순수 함수. 입력: 후보의 현재 버전, 근거 수(`source_run_id` + 근거 행), 원문 저장 위치, 그 항목의
열린 충돌, 관계 대상의 현재 버전, 관측 문맥, 활성화 요청(효력·범위·활동·`into`). 출력: 항목 목록
`{code, blocking, detail}`.

| 코드 | 막음 | 뜻 |
|---|---|---|
| `not_a_candidate` | 예 | 후보가 아니다 |
| `content_unavailable` | 예 | 원문이 서버에 없다(`storage != server`) — 원문 없이 규칙을 만들지 않는다 |
| `open_conflict` | 예 | 이 항목에 열린 충돌이 있다 |
| `contradicts_active` | 예 | 반증 대상이 아직 활성이다 — 대상을 무효·개정하거나 `into` 로 대체해야 한다 |
| `target_not_active` | 예 | `into` 대상이 활성·후보가 아니다(무효·대체됨) |
| `scope_widened` | 예 | 요청한 범위가 후보보다 넓다(저장소 → 프로젝트, 활동 추가). 축소만 된다 |
| `no_evidence` | 아니오 | 근거가 없다(사람이 적어 둔 제안). 사유가 근거다 |
| `scope_wider_than_observed` | 아니오 | Project 범위인데 관측은 저장소 하나다 |
| `obligation_raised` | 아니오 | 참고 후보를 필수로 올린다 — 사람의 결정이다 |
| `related_version_changed` | 아니오 | 관계 대상이 후보 이후 새 버전이 됐다 |
| `independent_review_not_run` | 아니오 | 독립 AI 검토는 이 판에 없다(선택 사항, 9절) |

- `POST /api/knowledge/{id}/activate` 가 `obligation`·`scope_kind`·`repository_id`·`paths`·
  `activities`(축소만)·`into_knowledge_id` 를 더 받는다. 막는 항목이 있으면 409 와 코드 목록. 아니면 새
  버전(`user_decision`)을 만들고 `adoption_json` 에 확인 결과(경고 포함)를 남긴다.
- **다른 항목의 새 버전으로 적용**(`into_knowledge_id`): 대상 항목에 새 버전(`user_decision`, 원문 =
  후보의 원문, 메타데이터 = 후보 것에 요청한 축소를 적용)을 만들고 대상의 이전 버전은 `superseded`,
  **후보 항목의 버전은 `superseded_by` = 새 버전·상태 `superseded`** 로 닫는다(이력 보존, 후보 키는
  남는다). 대상이 없는 `supersedes` 후보도 같은 길로 활성화할 수 있고, 관계가 없는 후보를 `into` 로
  적용해도 된다(사람의 판단).
- `GET /api/knowledge/{id}/adoption-check` 는 활성화 없이 같은 확인을 돌려준다(화면이 먼저 보인다).
- 무효(`invalidate`)는 그대로 후보를 닫는 길이다("후보 유지·범위 축소·충돌 검토·근거 확보" 중 근거
  확보는 근거 행이 쌓이는 것으로 본다).

### 3.5 주입

- 후보는 P4-06 그대로 `knowledge_candidate`(보조)로 들어간다. 머리(`knowledge_head`)에 관계와 관측을
  더한다: `{K-004 v1 · 후보 · 운영 사실 · 저장소 app · 활동 verification · 제목 · ← K-001 반증 · 관측:
  저장소 app@ab12cd3 (Case 브랜치)}`. `KNOWLEDGE_NOTE` 의 "후보는 규칙이 아니다" 는 그대로다.
- Manifest·영수증·최신성은 바꾸지 않는다. 활성화로 생긴 새 버전은 다음 실행부터 들어가고, 고정된 실행의
  Manifest 는 그대로다(P4-06 AC-13).
- `assignment_payload` 가 네 목적에도 `knowledge_index`(현재 키·요약·효력·범위 + 이 실행의 저장소 이름)를
  싣는다 — `relates_to`·`repository` 를 지어내지 않게.

### 3.6 지시문

- `KNOWLEDGE_EXTRACTION_RULE`(네 목적, `knowledge_index` 가 있을 때만): 계기 목록, "관찰을 프로젝트 전체
  규칙으로 일반화하지 마라(이 실행의 저장소·환경에 한정해 적어라)", "후보이며 규칙이 되지 않는다",
  "content 는 서버에 저장 — 비밀값 금지", "basis 에 근거가 된 명령·관측을 적는다", "해당 없으면 붙이지
  않는다", 항목 형식, 현재 지식 목록(`relates_to` 후보)·이 실행의 저장소 이름.
- `KNOWLEDGE_REGISTRATION_RULE`(논의 응답): "사용자가 정하지 않았지만 재사용할 만한 관찰·제안은
  `proposal: true` 로 붙인다 — 후보로만 등록되고 규칙이 되지 않는다" 한 항목.

### 3.7 화면

- 관리 화면 지식 패널: 후보 행에 관계(`← K-001 의 대체 제안` 등)·근거 수·관측(저장소@커밋)·`채택 확인`
  버튼(결과 항목 목록, 막는 것/경고)·활성화 폼(효력, 저장소 범위로 좁히기, `K-00x 의 새 버전으로`).
  활성 항목 행에 근거 목록(출처 실행·근거 원문 보기).
- 새 화면(`ProgressCards`): **후보 카드** — 이 대화의 실행이 남긴 후보·근거(키·요약·종류·관계·근거 한
  줄·"후보이며 규칙이 아니다")와 관리 화면 링크. 활성화는 여기서 하지 않는다(UI-04 의 결정 사항 패널).
- `api.ts` 형·`KnowledgeRegistration` 에 `origin`(`statement`/`proposal`/`extraction`)·`relation`·
  `relates_to_key`·`basis`·`evidence` 을 더한다.

### 3.8 문서

project-knowledge 3절(구현 사실·자동 활성화 미구현·사용자 판단 대기)·6절(시나리오 표시), quality-gates
QG-08 행(채택 확인의 구현 범위), README, DEVELOPMENT(1절·1.10절·4절·6절·9절·인계), review-acceptance-matrix
AC-32 표시.

## 4. 성공 기준

| AC | 기준 |
|---|---|
| AC-1 | 검증 실행의 후보 블록 → 후보 등록: `K-NNN`·`candidate`·`ai_proposal`·`source_run_id`·`reason_summary` 에 근거, 원문은 `knowledge_body` 에만(로그·다른 표 없음), 실행 결과 원문에 블록 없음, 실행의 산출물(명령·기준 보고)은 그대로. 활성 필수가 아니다(DB CHECK 그대로) |
| AC-2 | 후보 없는 실행·Case: 블록이 없으면 아무 것도 기록하지 않고 진행·완료가 그대로다(추가 실행 없음, intake 없음) |
| AC-3 | `supports: K-001` → 새 항목 없이 K-001 에 근거 행(`supports`), intake `evidence`. 같은 내용을 두 실행이 보고 → 둘째는 근거 행(`duplicate`), 항목은 하나 |
| AC-4 | `supersedes: K-001`·`contradicts: K-001` → 관계를 가진 새 후보 항목, **K-001 의 현재 활성 버전은 그대로**(대체·무효 없음), 주입 머리에 관계 표시 |
| AC-5 | 활성화의 QG-08 확인: 원문 없음·열린 충돌·반증 대상 활성·범위 확대 → 409 와 코드. 경고(관측보다 넓은 범위·필수 승격·근거 없음)는 `adoption_json` 에 남고 활성화된다. 축소(저장소·활동·효력 낮춤)는 새 버전에 반영된다. `GET adoption-check` 가 같은 결과를 준다 |
| AC-6 | `into_knowledge_id`: 대상 항목에 새 버전(`user_decision`, 후보의 원문), 대상 이전 버전 `superseded`, 후보 버전 `superseded_by` = 새 버전. 다음 실행에 새 버전이 필수로 들어가고 후보는 들어가지 않는다 |
| AC-7 | 관측 문맥: 후보 버전의 `observed_json` 에 저장소·기준 커밋·도구·실행이 있고 조회·주입 머리에 보인다. 옛 버전은 NULL 이며 "없음" 으로 표시된다 |
| AC-8 | 논의 응답의 `proposal: true` 항목 → 후보(`ai_proposal`, `source_message_id` 없음, 권위 메시지 본문 없음). 같은 응답의 사용자 말 항목은 P4-06 그대로 활성 |
| AC-9 | 거부: 의도 초안·설계·계획 실행의 `knowledge_report` 는 409. 완료되지 않은 검증 실행의 후보는 `run_not_completed`. 4건째부터 `too_many_items`. 모르는 `relates_to` 는 `unknown_related_key`. 거부도 intake 에 사유와 함께 남는다 |
| AC-10 | v23 → v24: 컬럼·표가 생기고 비어 있으며, 옛 버전의 새 컬럼은 NULL, `knowledge_intake` 행이 보존되고 새 CHECK 가 있다. 멱등 |
| AC-11 | 데이터 경계: 새 표·컬럼에 본문 컬럼 없음(`knowledge_evidence`·`knowledge_intake`), `observed_json ≤ 1000`·`adoption_json ≤ 2000`, 후보 원문 표식은 `knowledge_body` 에만·로그 없음. 기존 경계 시험 통과 |
| AC-12 | 화면: 새 화면 후보 카드(키·관계·근거·"규칙이 아니다"), 관리 패널의 채택 확인·범위 축소 활성화·`into` 적용(브라우저 시험) |
| AC-13 | 실제 codex: 규칙 대화 없이 업무 하나를 돌려 검증·구현 실행이 후보를 남기는가는 **관찰**, 남기면 후보 등록·서버 본문·주입 머리·카드는 **제품 규칙**. 사람이 후보 하나를 활성화(확인 결과 기록)한 뒤 다른 대화의 실행에 그 버전이 들어간다 |
| AC-14 | 강제 축·권한·준수 의미 그대로. 후보·근거·활성화는 준수·인수·권한이 아니고 기준 판정·완료는 지식으로 바뀌지 않는다. 다른 원문 경계 변경 없음 |

## 5. 검증

- 순수(`tests/test_knowledge_extraction.py`): `parse_report_item` 의 새 칸, `adoption_check` 의 표 전부,
  `knowledge_head` 의 관계·관측.
- 제어부·Runner(같은 파일, `processing_harness`·`FakeCliExecutor` 의 `verification_response` 등):
  AC-1~9·11·14. 가짜 codex 표지 `HADS_FAKE_CANDIDATE`(검증 실행이 후보 블록을 붙임)·
  `HADS_FAKE_PROPOSAL`(논의 응답이 `proposal: true` 항목을 붙임).
- 이행(`test_knowledge_extraction.py`): v23 스키마 → v24, AC-10.
- 경계(`tests/test_data_boundary.py`): 표 목록에 `knowledge_evidence` 추가, CHECK 확인.
- 브라우저(`tests/test_web_shell.py`): AC-12 한 건.
- 전체 `scripts\run-tests.ps1`.
- **실제 CLI 라이브**(`p4/live/p407_extraction.py`, 제품 코드 import 없음): AC-13. 실행하지 못하면
  미수행으로 적는다.

기준선(S-027 시작, 변경 전, `pwsh -File scripts\run-tests.ps1`): 웹 빌드 성공, 웹 단위 **18**, pytest
**677 통과·2 건너뜀·0 실패**(8분 0초), P1 계약 **18**. S-026 인계는 678 통과·1 건너뜀이었다 — 건너뜀 하나가
늘었고 그 사유는 5절 뒤 결과 문서에 적는다(이 세션의 변경 전 상태다).

## 6. 경계

- 후보·근거·채택 확인은 **권한·동의·인수·준수가 아니다.** 활성화는 사람의 결정이며 새 버전이다.
- AI 후보는 어떤 경로로도 활성 필수가 되지 않는다(DB CHECK). 참고 후보의 자동 활성화는 없다(0절).
- 추출은 완료를 막지 않는다 — 후보가 있든 없든 진행기의 걸음은 같다.
- 지식 외 원문의 경계는 그대로다. 후보 원문·근거 원문은 지식 원문(`kind = knowledge`)이며 서버 본문 표에만
  들어간다. 근거 행의 요약은 200자다.

## 9. 알려진 한계·설계 선택

- **별도 추출 실행이 없다.** 후보는 기존 실행의 응답에 얹히거나 사람이 청한 논의 응답에서 나온다. 그래서
  "추출 예산 부족" 은 그 실행의 진입 거부와 같은 것이고, 별도 미처리 상태를 두지 않았다. 추출만 따로
  돌리는 목적이 필요해지면 그때 진입 조건·예산과 함께 정한다.
- **추출의 판단은 AI 다.** 무엇이 "의미 있는 사건" 인지 시스템이 판정하지 않는다. 계기 목록과 상한(3건)·
  근거 한 줄을 요구할 뿐이다. 후보를 안 남긴 실행이 "재사용할 것이 없었다" 는 뜻은 아니다.
- **중복 판정은 원문 해시다.** 같은 뜻의 다른 문장은 다른 후보가 된다. `relates_to`/`supports` 로 AI 가
  잇거나 사람이 무효·`into` 로 정리한다.
- **관측 문맥은 실행이 아는 만큼이다.** 기준 커밋은 작업공간이 있는 실행(구현·검증·실험)에서 오고 분석
  실행은 저장소만 안다. 도구 판은 `observed_tool_version` 이다.
- **독립 AI 검토(QG-08 선택 사항)는 없다.** `adoption_json` 이 `independent_review = not_run` 으로 남긴다.
  위험·충돌·영향에 따라 검토를 붙이는 조건은 QG-02~07 의 자동 실행(별도 plan)과 함께 본다.
- **반증 후보는 대상을 자동으로 바꾸지 않는다.** 활성 규칙과 다른 관측은 후보와 관계로만 남고, 사람이
  대상을 무효·개정하거나 `into` 로 대체한다. 그 전까지 활성 규칙은 그대로 주입된다 — "코드 변경만으로
  규칙을 무효화하지 않는다" 의 자리다.
- **논의 응답의 `proposal: true` 는 AI 의 표지다.** AI 가 사용자 말과 자기 제안을 잘못 구분할 수 있다
  (P4-06 의 충실성 한계와 같다). 사용자 말이 후보로 적히면 사람이 활성화하면 되고, 제안이 사용자 말로
  적히면 카드에서 무효로 한다.
