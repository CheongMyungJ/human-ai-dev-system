// 실행 결과 원문의 모양(runner/cli_adapter.py `_compose_output`): 실행 정보 머리 + 구분 줄 +
// 최종 메시지. 대화에 보일 것은 최종 메시지이고 실행 정보는 접어서 보인다. **import 가 없다.**
//
// 구분 줄이 없으면(골격 실행기·시험용 가짜) 머리를 지어내지 않고 전체를 본문으로 둔다.

export const FINAL_MESSAGE_MARKER = '--- final message ---\n'

export interface SplitOutput {
  header: string | null
  message: string
}

export function splitRunOutput(body: string): SplitOutput {
  const normalized = body.replace(/\r\n/g, '\n')
  const index = normalized.indexOf(FINAL_MESSAGE_MARKER)
  if (index < 0) return { header: null, message: normalized }
  return {
    header: normalized.slice(0, index).trimEnd(),
    message: normalized.slice(index + FINAL_MESSAGE_MARKER.length),
  }
}
