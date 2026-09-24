# P4-10b 결과 — CLI 권한 전부 허용 + 읽기 전용 실행의 변경 알림 (D-96)

세션 S-037(2026-09-25). plan: [P4-PLAN-10b](../../plans/P4-PLAN-10b.md). 사용자 결정 **D-96**: Claude·Codex 모두 권한 확인을 건너뛰는
옵션으로 돌리고 읽기 전용은 허용 도구로 제한한다. Codex 는 허용 도구 목록이 없어 읽기 전용을 막지 못하므로 실행 전후 작업 트리를 대조해
바뀌었으면 **알리기만 한다(실패로 표시하지 않는다)**.

## 1. 지금 제품이 하는 일

| 도구 | 쓰기 실행(구현·검증·실험) | 읽기 전용 실행(논의 응답·의도 작성·검토·분석) |
|---|---|---|
| codex | `--dangerously-bypass-approvals-and-sandbox` | 같다 — **막지 못함**, 전후 대조로 알림 |
| claude | `--dangerously-skip-permissions --permission-prompts none --strict-mcp-config` | 같음 + `--tools Read,Grep,Glob`(쓰기·실행 도구 없음) + 전후 대조 |

- **전후 대조:** Runner 가 읽기 전용 실행 전후로 도는 폴더(작업공간 또는 원래 저장소)와, 작업공간이 있으면 원래 저장소의 트리 지문
  (P3-03 `workspace.observe` — HEAD·미커밋 diff·미추적 파일)을 비교한다. 결과에 `read_only_change{observed, changed, where, unobserved}` 를
  싣는다 — 자리 이름뿐, 경로·본문 없음. git 저장소가 아니거나 관측이 실패하면 `unobserved`.
- **제어부:** `run.read_only_change_json`(v29 에 더함, 모양 검사 — 모르는 자리 이름은 버림). 쓰기 실행이 보낸 보고는 거부. **결과·판정은
  바꾸지 않는다.** 바뀌었으면 진행 이력 한 줄(`read_only_changed`), 대화 조회 `read_only_changes`, 목록 행 수 `read_only_changes`.
- **화면:** 대화 화면 배너("읽기 전용 실행 동안 작업 폴더가 바뀌었다 — 실패로 표시하지 않았다", 실행별 → 실행 상세), 목록 배지
  "읽기 전용 변경 N", 브라우저 알림 종류 `read_only_change`(수가 늘 때 한 건), 작업 탭 실행 상세의 전후 대조 줄.
- **능력 보고:** `read_only_enforcement` — codex `unsupported`, claude `doc_only`(도구 제한, 실제 CLI 미실증). `permission:read_only` 근거는 D-96.

## 2. 검증

| AC | 결과 | 근거 |
|---|---|---|
| AC-1 인자 | 충족 | `tests/test_cli_adapter_permissions.py::test_every_run_skips_permission_checks_and_claude_read_only_is_limited_by_tools` |
| AC-2 능력 보고 | 충족 | 같은 파일의 능력 보고 시험(두 도구) |
| AC-3 감지·실패 아님 | 충족 | `tests/test_read_only_change.py` 첫째(논의 응답이 원래 저장소에 파일을 씀 → `completed`·응답 붙음·`changed`/`original_repo`)·둘째(안 바꾸면 `changed=false`, git 아님이면 `unobserved`) |
| AC-4 알림 경로 | 충족 | 같은 첫째(대화 조회·목록 수·진행 이력, 파일 이름이 이력에 없음) + 웹 단위 `notify.test.ts`(수가 늘 때 한 건, 그대로면 없음) |
| AC-5 쓰기 실행 보고 거부·모양 | 충족 | 같은 셋째 |
| AC-6 배너 | 충족 | `tests/test_web_shell.py::test_a_read_only_run_that_changes_the_folder_shows_a_banner_not_a_failure`(실제 Edge·실제 Runner·가짜 codex `HADS_FAKE_RO_WRITE`) |
| AC-7 전체 시험 | (아래) | |

### 전체 실행

| 실행 | 웹 빌드 | 웹 단위 | pytest | P1 계약 | 종료 코드 |
|---|---|---|---|---|---|
| P4-10 최종(`44e4f04`) | 성공 | 41 | 807 통과·0 실패·2 건너뜀 | 18 | 0 |
| P4-10b 최종 | | | | | |

## 3. 경계와 한계

- 권한을 넓혔다(사용자 수용 D-96). Codex 읽기 전용 실행은 무엇이든 바꾸거나 지울 수 있고 파괴적 명령의 확인도 없다. 감지는 git 이 보는
  작업 트리뿐이다(`.gitignore` 된 파일·저장소 밖·자격증명은 보지 않는다). 막지 않고 되돌리지 않는다.
- 같은 폴더에서 동시에 돈 다른 실행·사람의 편집도 "바뀜" 으로 잡힌다(원인을 가리지 않는다 — 문구가 그렇게 말한다).
- 게시 규칙(P5)·진입 검사·강제 축은 그대로다. Claude 쪽 인자는 실제 CLI 로 돌려 보지 않았다(P4-09 부터 Claude 실행은 미실증).
- P4-ENV 의 "읽기 전용 샌드박스가 사용자 프로필의 도구를 읽지 못함" 은 샌드박스가 없어져 풀릴 것이다(실제 codex 로 확인하지 않음).
