# P1-04 OpenCode 어댑터 계약 (문서 기반)

작성일: 2026-09-20. Plan ID: `P1-PLAN-01` 16번.

> **이 문서는 실증 결과가 아니다.**
> OpenCode는 이 PC에 설치되어 있지 않다(P1-01 3절, 조사 범위 내 설치 흔적 없음).
> 아래 내용은 **공식 문서만 읽고 만든 계약**이며, 여기 있는 어떤 항목도 실행해 확인하지 않았다.
> 같은 디렉터리의 fixture는 **문서에서 재구성한 것이고 캡처한 응답이 아니다.**
> 계약 시험이 통과한다는 것은 **우리 어댑터가 우리가 가정한 형태를 올바로 다룬다**는 뜻이며,
> OpenCode가 실제로 그 형태를 낸다는 뜻이 아니다. 이는 FR-28·NFR-07이 요구하는 구분이다.

## 1. 대상 릴리스 고정

**V2 한 계열만** 근거로 쓴다. `cli-pause-feasibility.md`가 경고한 대로 V1 server endpoint와 V2
permission 구조를 섞지 않는다. 이 문서가 근거로 삼은 공식 페이지는 다음 다섯 개뿐이다.

| 약칭 | URL |
|---|---|
| CLI | https://opencode.ai/v2/docs/cli |
| PERM | https://opencode.ai/v2/docs/permissions |
| PLUG | https://opencode.ai/v2/docs/build/plugins |
| SDK | https://opencode.ai/v2/docs/build/sdk |
| API | https://opencode.ai/v2/docs/api |

버전 문자열을 실제로 관측하지 않았으므로 `observed_tool_version`은 **없음**으로 남는다.
Codex·Claude와 달리 "이 버전에서 확인함"이라고 쓸 수 없다.

## 2. 연결 방식 결정 — 서버/SDK 경로

| 후보 | 문서에서 확인한 것 | 판단 |
|---|---|---|
| `opencode run "<프롬프트>"` 비대화식 CLI | 존재한다. "스크립트·CI용"으로 설명된다 [CLI] | **부적합.** 출력 형식·세션 식별·권한을 다루는 플래그가 V2 CLI 문서에 없다. 구조화 이벤트와 세션 식별을 얻을 수 없다 |
| 서버 HTTP API (`/api/...`) + SDK | 세션 생성·프롬프트·이벤트 구독·권한 조회/응답 엔드포인트가 모두 있다 [API][SDK] | **채택.** RunRequest·이벤트·세션·권한을 모두 표현할 수 있다 |
| 플러그인 훅 | `permission.hook("evaluate")`, `tool.hook("execute.before"/"execute.after")` [PLUG] | 안전 중지의 후보. 3절·6절 참조 |

`opencode --server http://localhost:4096` 로 특정 서버에 붙을 수 있고, `opencode --standalone` 은
공유 서버 대신 전용 백그라운드 서버를 쓴다 [CLI]. **P2에서 연결할 방식은 서버 API**로 정한다.

SDK 경로는 `@opencode/sdk`(bun 설치)로 `OpenCode.create()` → `sessions.create({location:{directory}})`
→ `sessions.prompt({sessionID, text})` → `events.subscribe()` 순이다 [SDK]. 이 시스템의 제어부는
Python이므로 **SDK가 아니라 같은 서버의 HTTP API를 직접 쓴다.** SDK 문서는 의미 확인용으로만 참조한다.

## 3. RunRequest 매핑

[공통 계약](../../p1-environment-contract.md) 6절의 필드를 OpenCode V2로 옮긴 것이다.

| 공통 필드 | OpenCode V2 | 상태 |
|---|---|---|
| `run_id` | 어댑터가 보관. OpenCode에 대응 개념 없음 | 어댑터 책임 |
| `workspace.repo_path` | `POST /api/session` 의 `location.directory` [SDK] | `doc_only` |
| `session: new` | `POST /api/session` → `session.id` [API][SDK] | `doc_only` |
| `session: resume` | `POST /api/session/{sessionID}/prompt` 로 같은 세션에 이어 보냄 [API] | `doc_only` |
| `instruction_ref` 원문 | `POST /api/session/{sessionID}/prompt` 의 `text` [SDK] | `doc_only` |
| `model` | `GET /api/model`, `GET /api/model/default` 로 확인 [API]. prompt 시 지정 방법은 **문서에서 확인 못 함** | `unknown` |
| `permission: read_only` | `permissions` 규칙으로 `edit`·`shell` 을 `deny`, `read`·`glob`·`grep` 을 `allow` [PERM] | `doc_only` |
| `permission: workspace_write` | `edit` 을 `allow`(또는 `ask`), `external_directory` 는 `deny` 유지 [PERM] | `doc_only` |
| `writable_paths` | 규칙의 `resource` 에 경로 패턴 [PERM] | `doc_only` |
| `output_schema` | **대응 없음.** 구조화 출력 스키마를 강제하는 수단을 문서에서 찾지 못함 | `unknown` |
| `limits` | **대응 없음** | `unknown` |
| `secrets` | 없음. 자격증명은 OpenCode 쪽에 유지 | 계약상 동일 |

권한 규칙은 `opencode.jsonc` 의 최상위 `permissions` 배열이며 각 규칙은 `action`·`resource`·`effect`
세 문자열이다. `effect` 는 `allow`·`deny`·`ask` 다 [PERM].

내장 `action` 값: `read`, `edit`, `glob`, `grep`, `shell`, `subagent`, `skill`, `question`,
`webfetch`, `websearch`, `external_directory`, 그리고 MCP 도구는 `<server>_<tool>` 형식 [PERM].

**Codex·Claude와 다른 점:** Codex는 파일시스템 sandbox 축, Claude는 도구 목록 축, OpenCode는
**행위(action)×자원(resource) 규칙 축**이다. 세 축을 같은 것으로 취급하지 않는다(NFR-07).

## 4. 이벤트 매핑

`GET /api/event` 가 "네이티브 이벤트와 플러그인 RPC 이벤트"를 스트림으로 준다 [API].
SDK 쪽은 `for await (const event of opencode.events.subscribe())` 이며 각 이벤트에 `type` 이 있다 [SDK].

문서에서 **구체적인 이름을 확인한 이벤트는 셋뿐이다.**

| 정규화 종류 | OpenCode 이벤트 | 상태 |
|---|---|---|
| `tool_call_started` | `shell.started` — 실행 전에 발생 [API] | `doc_only` |
| `tool_call_finished` | `shell.ended` — 완료 후 출력이 합쳐져 발생 [API] | `doc_only` |
| (해당 없음) | `location.shutdown` [API] | `doc_only` |
| `session_identified` | 세션 생성 응답의 `id` 로 대체. **이벤트 이름 확인 못 함** | `unknown` |
| `assistant_message` | **이벤트 이름 확인 못 함** | `unknown` |
| `permission_requested` | **이벤트 이름 확인 못 함.** `GET /api/session/{id}/permission` 폴링으로 대체 가능 [API] | `unknown` |
| `permission_decided` | 같음. `POST .../permission/{requestID}/reply` 의 결과로 판단 [API] | `unknown` |
| `usage_reported` | **대응 없음** | `unknown` |
| `run_finished` | 세션 agent 루프가 idle 이 될 때까지 기다리는 엔드포인트가 있다고 확인. 정확한 경로·응답은 확인 못 함 | `unknown` |

**이벤트 이름 세 개만으로는 어댑터를 완성할 수 없다.** 나머지는 설치 후 실물 스트림을 보고
채워야 하며, 지금은 비워 둔다. 추정으로 채우지 않는다(공통 계약 7.1절 규칙).

### 4.1 스트림 신뢰성 — 이 설계에 직접 걸리는 제약

공식 문서는 이벤트 구독이 **계약상 휘발성**이라고 밝힌다. 느린 소비자는 오버플로로 스트림이
실패하고, **연결이 끊긴 동안의 이벤트는 유실된다.**

이는 `execution-workspace-review.md` 3절의 "이벤트를 로컬에 보존한 뒤 전송하여 재접속 때
중복·누락을 대조한다"와 정면으로 관계된다. 대안은 **세션 로그**다.
`GET /api/session/{sessionID}/log` 는 배타적 시퀀스 이후의 이벤트를 읽고 `follow=true` 면
라이브로 이어간다(문서상 실험적).

→ **어댑터 규칙:** 재접속 대조의 정본은 `/api/event` 스트림이 아니라 **세션 로그의 시퀀스**로
삼는다. 스트림 유실을 누락 없음으로 해석하지 않는다. 이 규칙은 문서 근거만 있고 미검증이다.

## 5. RunResult 매핑

| 공통 필드 | OpenCode V2 | 상태 |
|---|---|---|
| `outcome` | idle 대기 + 세션 메시지 조회(`GET /api/session/{id}/message`)로 판정 [API] | `doc_only` |
| `exit_code` | 프로세스가 아니라 서버 세션이므로 **해당 없음.** 셸 명령의 종료 코드는 `shell.ended` 쪽 | 구조가 다름 |
| `session_ref` | 세션 `id` [SDK] | `doc_only` |
| `usage` | **`not_reported`.** 사용량·비용을 제공하는 엔드포인트를 확인하지 못함 | 공백 |
| `workspace_effect` | 어댑터가 git 스냅샷으로 직접 산출(Codex·Claude와 동일) | 어댑터 책임 |
| `residual_activity` | `GET /api/shell`, `GET /api/shell/{shellID}` 로 셸 목록·상태 조회 가능 [API] | `doc_only` — **세 도구 중 유일하게 조회 수단이 문서에 있다** |
| `observed_tool_version` | `GET /api/info` [API] | `doc_only` |

**주목할 차이:** Codex·Claude는 `residual_activity`가 `unknown`이었다(P1-02·P1-03). OpenCode는
셸 조회 엔드포인트가 있어 **남은 활동 추적의 후보가 문서상 존재**한다. 실증 전까지 `doc_only`다.

## 6. 안전 중지 — 다음 호출 차단의 후보와 공백

P1-03에서 Codex·Claude는 PreToolUse 훅으로 차단을 `verified` 했다. OpenCode의 후보는 두 가지다.

**후보 A. 플러그인 permission evaluate 훅** [PLUG]

```ts
await ctx.permission.hook("evaluate", async (event) => {
  event.effect = "ask"          // 단절 상태면 allow 를 ask 로 바꾼다
  event.message = "연결 끊김"
})
```

`event` 에 `sessionID`, `action`, `resources` 가 있어 **어느 호출인지 식별할 수 있다.**
그러나 문서는 중요한 제약을 명시한다.

> 훅은 `allow` 와 `ask` 결정에서만 실행된다. 설정으로 정한 `deny` 는 최종이며 훅을 부르지 않는다.

즉 **훅에서 직접 `deny` 로 바꿀 수는 있으나, 설정이 이미 `deny`인 경로는 훅을 거치지 않는다.**
차단 자체에는 문제가 없지만 **모든 호출이 훅을 거친다고 가정할 수 없다.** 적용 범위는 미확인이다.

**후보 B. `ask` 로 두고 클라이언트가 응답하지 않기** [PERM][API]

`ask` 는 "클라이언트의 결정을 기다린다". 단절 중에는 `reply` 를 보내지 않으면 호출이 대기한다는
것이 문서상 기대되는 동작이다. 응답 값은 `once`(해당 요청만 승인), `always`(도구의 제안 패턴을
프로젝트에 저장), `reject`(해당 요청과 **그 세션의 다른 모든 대기 중 권한 요청**을 거부)다 [PERM].

→ **주의:** `reject` 는 단일 호출 거부가 아니라 **세션의 모든 대기 요청을 한 번에 거부**한다.
"다음 호출 하나만 보류"와 의미가 다르므로 재개 설계에서 그대로 쓰면 안 된다.
`always` 는 **프로젝트에 패턴을 저장**하므로 일시적 판단에 쓰면 영구 권한을 만든다. 쓰지 않는다.

**확인되지 않은 공백**

| 항목 | 왜 문제인가 |
|---|---|
| 대기 중 `ask` 가 **무기한** 기다리는지, timeout 후 어떻게 되는지 | Claude는 훅 실패 시 fail-open 이었다(P1-03). OpenCode도 확인 전에는 같은 위험을 가정해야 한다 |
| 훅 실패·예외 시 동작 | 위와 동일 |
| 저장된 `always` 허용이나 agent 규칙이 있으면 매 호출 대기를 가정할 수 없음 | `cli-pause-feasibility.md`가 이미 지적한 제약 |
| 이미 시작된 셸의 후속 활동 | 호출 경계와 실제 활동이 다르다는 P1-03 결론이 그대로 적용된다 |
| serve 전송 계층과 V2 훅의 결합 | 두 문서가 같은 실행 경로를 설명한다고 확인하지 못함 |

→ **결론: OpenCode의 안전 중지는 현재 `unknown` 이다.** 후보 경로는 있으나 필수 능력을 확인하지
못했으므로 **해당 기능의 지원을 보류한다.** 설치·실증 전까지 OpenCode에 안전 중지가 필요한 작업을
배정하지 않는다.

## 7. 필수 능력의 공백·대안·후속 작업

| 필수 능력 | 상태 | 대안 / 후속 작업 |
|---|---|---|
| 다음 호출 차단 | `unknown` | 설치 후 후보 A·B를 P1-03과 같은 부수효과 시험으로 검증. 그 전까지 지원 보류 |
| 구조화 이벤트의 도구 경계 | 부분(`shell.started`/`ended`만) | 설치 후 실물 스트림에서 나머지 이벤트 이름 확인 |
| 세션 재개 | `doc_only` | 같은 `sessionID` 로 prompt 재전송. 실증 필요 |
| 사용량 제공 | 공백 | `not_reported` 로 남긴다. **0으로 표시하지 않는다** |
| 구조화 출력 스키마 | 공백 | 프롬프트로 형식을 요구하고 어댑터가 검증. 강제 수단 없음을 표시 |
| 이벤트 유실 대조 | `doc_only` | 세션 로그 시퀀스를 정본으로. 4.1절 |
| 남은 활동 추적 | `doc_only` | `GET /api/shell` 계열. 세 도구 중 유일하게 문서상 수단 있음 |
| 버전 확인 | `doc_only` | `GET /api/info` |

## 8. 이 계약으로 할 수 있는 것과 없는 것

**할 수 있는 것:** 어댑터 인터페이스를 세 도구 공통으로 유지한 채 OpenCode 자리를 비워 두기.
fixture로 정규화 코드의 분기를 시험해 두어, 설치 후 실물 스키마만 갈아 끼우면 되도록 하기.

**할 수 없는 것:** OpenCode 지원 여부 판정. 안전 중지 가능성 결론. 성능·안정성 판단.

계약 시험은 `p1/opencode/test_contract.py` 에 있고 다음으로 실행한다.

```
python -m unittest discover -s p1/opencode -t p1/opencode
```

2026-09-20 기준 18개 시험 통과. 외부 의존성 없이 표준 라이브러리만 쓴다.

시험이 통과해도 **OpenCode 실환경 검증 상태는 바뀌지 않는다.** 마지막 시험군(`TestEvidenceBoundary`)이
바로 그 경계를 지킨다.

- 모든 fixture에 `"_source": "reconstructed-from-docs"` 표시가 있는지
- 어떤 능력도 `verified` 로 올라가 있지 않은지
- `next_call_blockable` 이 `unknown` 으로 남아 있는지
- 확인하지 못한 이벤트 종류가 몰래 매핑되지 않았는지

이 가드가 실제로 깨지는지도 확인했다. 능력을 `verified` 로 바꾸거나 미확인 이벤트를 매핑하면
시험이 실패한다. 즉 **나중에 이 시험을 통과시키려고 상태만 올리는 일이 불가능하다.**
