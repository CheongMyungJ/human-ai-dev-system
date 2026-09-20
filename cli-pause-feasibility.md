# Windows native CLI 안전 중지의 문서상 가능성

조사일: 2026-09-20. 공식 문서만 확인했으며 설치·CLI 실행·연결 시험은 하지 않았다. Codex 조사에는 OpenAI Docs 스킬을 적용했다. 각 제품의 근거는 아래 두 페이지씩으로 제한했다.

검토할 요구는 **제어 서버 연결 단절 감지 → 이미 실행 중인 도구 호출의 결과 보존 → 다음 호출은 실행하지 않음 → 재연결·상태 대조 후 재개**다. `interrupt`, `abort`, 프로세스 종료 또는 이벤트 수신만으로 이 요구를 충족했다고 판단하지 않는다.

## 1. 비교

| 실행 수단 | 공식 문서에서 확인한 제어 지점 | 남은 불명확·제약 | 현재 판정 |
|---|---|---|---|
| Codex app-server + 동기 hook | app-server에 명령·파일 승인 요청과 항목 이벤트, 턴 interrupt가 있다. 별도 Hooks 문서는 지원 도구의 PreToolUse 차단과 PostToolUse 후속 제어, Windows 전용 hook 명령을 설명한다. [App Server](https://learn.chatgpt.com/docs/app-server), [Hooks](https://learn.chatgpt.com/docs/hooks) | Hosted 도구·일부 특수 경로는 hook 적용 밖이다. 기존 unified-exec 세션의 write_stdin은 PreToolUse를 다시 거치지 않는다. 코드 모드의 PostToolUse `continue: false`만으로 중첩 스크립트까지 멈춘다고 볼 수 없다. | **부분 경계는 문서상 확인. 모든 호출의 안전 중지는 미확인.** 사용할 도구·실행 경로를 정한 뒤 Windows에서 실증 필요 |
| Claude Agent SDK | PreToolUse는 Python·TypeScript에서 호출 전 차단을 지원한다. matcher를 생략하면 모든 도구를 대상으로 한다. `permissionDecision: defer`는 쿼리를 종료해 이후 재개할 수 있도록 설명한다. [SDK Hooks](https://code.claude.com/docs/en/agent-sdk/hooks), [SDK Permissions](https://code.claude.com/docs/en/agent-sdk/permissions) | canUseTool은 앞 단계에서 자동 허용된 호출에 실행되지 않으므로 전체 경계가 아니다. 훅 대기에는 timeout이 있고, 비동기 훅 출력은 진행을 막지 못한다. 설치 버전·Windows native·자식/병렬 호출 동작은 미실증이다. | **호출 전 보류 구현 후보가 문서상 명확. 전체 안전 중지 보장은 실증 필요.** SDK 경로의 능력을 일반 CLI 실행과 같다고 가정하지 않음 |
| OpenCode V2 제어 확장 후보 | permission `ask`는 클라이언트 결정을 기다리고 `once`로 해당 요청만 허용한다. V2 plugin의 permission evaluate 훅은 실행 전 allow·ask 판단을 바꿀 수 있으며, 도구 실행 전후 훅과 pending permission 조회·응답 API도 설명한다. [V2 Permissions](https://opencode.ai/v2/docs/permissions), [V2 Plugins](https://opencode.ai/v2/docs/build/plugins) | 이번 두 V2 페이지는 기존 `/docs/server`의 serve HTTP 계약을 검증한 자료가 아니다. serve 전송 계층과 V2 훅의 결합, 훅 실패·장기 대기·Windows native 동작은 미확인. 저장된 always 허용이나 agent 규칙을 그대로 두면 매 호출 대기를 가정할 수 없다. | **V2 제어 후보는 문서상 확인, serve 연동·실환경은 미검증.** V1 server endpoint와 V2 permission 구조를 결합하지 않음 |

Codex Hooks 문서는 훅을 완전한 강제 경계로 취급하지 않도록 명시한다. PreToolUse에 지원하지 않는 공통 중지 필드를 반환하면 오류를 보고하고 도구 호출이 계속될 수도 있다. 따라서 다른 제품의 hook 응답 형식을 그대로 이식하지 않는다. [Codex Hooks](https://learn.chatgpt.com/docs/hooks)

Claude의 문서는 canUseTool 우회 가능성과 전체 호출을 검사하려면 PreToolUse를 사용하라는 안내를 명시한다. timeout 후 동작도 버전 영향을 받으므로 콜백을 무기한 기다리게 하는 구현을 안전 중지로 단정하지 않는다. [Claude SDK Permissions](https://code.claude.com/docs/en/agent-sdk/permissions), [Claude SDK Hooks](https://code.claude.com/docs/en/agent-sdk/hooks)

OpenCode V2의 permission 훅은 allow 결과도 ask로 전환할 수 있다는 점이 후보가 된다. 다만 V2 문서는 V1과 필드·훅 구조가 다르다고 명시하므로 어댑터를 만들기 전에 대상 계열과 릴리스를 고정해야 한다. 이번 조사에서는 V2 문서만 판정 근거로 사용했다. [V2 Permissions](https://opencode.ai/v2/docs/permissions), [V2 Plugins](https://opencode.ai/v2/docs/build/plugins)

## 2. 설계 추론

문서로 확인한 제어 지점을 이용하는 후보는 다음과 같다. 이는 제품 선택이나 검증 완료 선언이 아니다.

- Runner에 서버 연결 상태를 보존하고 CLI의 로컬 제어 경로가 이를 조회하게 한다. 서버에 도달해야만 단절을 판단하는 구조로 만들지 않는다.
- 이미 시작된 도구는 결과를 수집한다. 다음 호출의 실행 전 경계에서 보류하고 재개할 호출·세션 정보를 남긴다.
- Codex는 지원하는 로컬 도구의 동기 hook을 후보로 하되 제외 경로를 능력 명세에 표시한다. 승인 이벤트나 PostToolUse 하나만으로 전체 실행을 통제한다고 주장하지 않는다.
- Claude는 전체 PreToolUse에서 연결 상태를 확인하고 문서상의 defer 경로를 우선 검증할 수 있다. 단순 canUseTool callback만으로 설계하지 않는다.
- OpenCode V2는 permission evaluate에서 연결 상태에 따라 ask로 전환하고 재연결 후 해당 요청만 once로 허용하는 경로가 후보다. 실제 serve 연결 및 적용 범위는 아직 검증 대상이다.
- 어떠한 경로도 이미 실행된 셸 내부의 후속 명령, 백그라운드 자식, 다른 병렬 도구의 종료를 자동 보장하지 않는다. 호출 경계와 실제 남은 활동을 함께 추적해야 한다.

## 3. 설치 후 검증 계획

| 시험 | 관찰해야 할 결과 |
|---|---|
| 버전·설정·실행 모드 고정 | OS·CLI·SDK/plugin 버전, 실제 hook 활성화, 적용 도구 목록이 기록됨. 문서상 가능과 실증 통과를 별도 표시 |
| 순차 도구 A 실행 중 단절 | A 결과는 남고 B는 실제 시작하지 않음. 단절 감지 시각·A 종료·B 보류 시각을 로그로 확인 |
| A 종료 직전/직후 반복 단절 | 이벤트 수신과 다음 호출 시작 사이의 경쟁에서 단절 감지 이후 새 허용이 발급되지 않는지 확인 |
| 자동 허용·읽기·MCP·자식/병렬 경로 | 각 경로가 제어 지점을 거치는지 확인. 제외 경로가 있으면 안전 중지 지원 범위를 좁혀 표시 |
| 제어 callback 오류·timeout·중복 응답 | 보류가 조용히 허용으로 바뀌는지, turn이 계속되는지, 재시도로 도구가 중복 실행되는지 확인 |
| 긴 셸·백그라운드 자식·기존 세션 입력 | 도구 반환 뒤 남은 활동과 이미 승인된 프로세스에 대한 후속 입력을 추적. 즉시 pause 완료로 표시하지 않음 |
| 재연결·프로세스 재시작 | 현재 정책·실행 결과를 대조한 뒤 미수행 호출만 재개. 성공한 도구를 다시 실행하지 않음 |

시험 결과는 `tool_boundary_observed`, `next_call_blockable`, `background_activity_tracked`, `reconnect_reconciled` 같은 개별 능력과 근거로 남긴다. 전체 안전 중지 지원 여부는 필요한 능력을 모두 확인한 정확한 버전·모드에만 부여한다. 미지원 조합은 해당 기능의 지원을 보류한다. D-45에 따라 다른 CLI로 바꾸기 전에 확인받고, 실제 시험에서 확인한 제한과 대안을 제시한다. 사용자의 안전 중지 정책을 조용히 완화하지 않는다.
