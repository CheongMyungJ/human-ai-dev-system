// P4-09(f), D-92. 지식 등록 보고의 **사유 코드 → 읽을 말**(서버 `domain.knowledge.REFUSAL_TEXT` 와 같은 뜻).
// 카드·결정 사항 패널·열람이 같은 말을 쓴다 — 서버가 `refusal_text` 를 주면 그것을 먼저 쓴다.

export const KNOWLEDGE_REFUSAL_LABEL: Record<string, string> = {
  unknown_repository: '그런 저장소가 이 프로젝트에 없다',
  unknown_supersedes_key: '바꾸라는 기존 규칙을 찾지 못했다',
  invalid_kind_or_obligation: '종류·효력을 알아볼 수 없다',
  format_error: '형식이 맞지 않는다',
  not_an_object: '항목의 형식이 맞지 않는다',
  reply_not_completed: '응답이 완료되지 않았다',
  run_not_completed: '실행이 완료되지 않았다',
  no_user_message: '권위가 될 사용자 메시지가 없다',
  summary_missing: '제목이 없다',
  content_not_stored: '내용이 저장되지 않았다',
  invalid_scope: '범위(활동·경로)를 알아볼 수 없다 — 사용자 말의 자동 등록은 범위가 분명해야 한다',
  paths_without_repository: '경로 조건은 저장소를 정해야 한다',
  too_many_items: '한 번에 너무 많다',
  unknown_related_key: '관계 대상 지식을 찾지 못했다',
  invalid_relation: '관계를 알아볼 수 없다',
  relation_without_target: '관계 대상이 없다',
  registration_failed: '등록 중 다른 처리와 겹쳤다',
}

export function refusalText(code: string | null | undefined, serverText?: string | null): string {
  if (serverText) return serverText
  if (!code) return ''
  return KNOWLEDGE_REFUSAL_LABEL[code] ?? code
}

// "이 내용으로 수동 등록" — 규칙 화면의 수동 등록 폼을 채우는 값 한 벌. 이 브라우저의 sessionStorage 에만
// 잠시 있고(권한·기록이 아니다) 폼이 읽으면 지운다. 본문은 서버가 열람으로 준 것이며 여기서 새로 저장하지 않는다.
export const REGISTER_PREFILL_KEY = 'hads.rules.register-prefill'

export interface RegisterPrefill {
  caseId: string
  content: string
  summary: string
  kind: string
  obligation: string
  repositoryId: string | null
  repositoryName: string | null
  activities: string[]
  candidate: boolean
  note: string
}

export function putRegisterPrefill(value: RegisterPrefill): void {
  try {
    sessionStorage.setItem(REGISTER_PREFILL_KEY, JSON.stringify(value))
  } catch {
    /* 저장소를 못 쓰면 채우기 없이 연다 */
  }
}

export function takeRegisterPrefill(): RegisterPrefill | null {
  try {
    const raw = sessionStorage.getItem(REGISTER_PREFILL_KEY)
    if (!raw) return null
    sessionStorage.removeItem(REGISTER_PREFILL_KEY)
    const parsed = JSON.parse(raw) as RegisterPrefill
    return parsed && typeof parsed.content === 'string' ? parsed : null
  } catch {
    return null
  }
}
