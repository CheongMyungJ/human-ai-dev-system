// 실행 제한 시간의 사람 말(P4-10, 이슈 #8, D-95). 순수 함수 — 카드·설정 탭·작업 탭·시험이 같은 문구를 쓴다.
//
//   **값은 서버가 정한다.** 제한은 초로 저장되고(설정 범위 10초~24시간) 화면은 분으로 받는다.
//   **시간 초과는 실패가 아니다.** 결과는 `unknown` 그대로이고 끊긴 이유만 다르다 — 문구도 그렇게 말한다.

export const TIMEOUT_MIN_SECONDS = 10
export const TIMEOUT_MAX_SECONDS = 86400

//: 초 → "1시간", "1시간 30분", "90초". 모르면 "기록 없음".
export function formatTimeout(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds) || seconds <= 0) return '기록 없음'
  const s = Math.round(seconds)
  if (s < 60 || s % 60 !== 0) return s >= 60 ? `${Math.floor(s / 60)}분 ${s % 60}초` : `${s}초`
  const minutes = s / 60
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  if (hours === 0) return `${minutes}분`
  return rest === 0 ? `${hours}시간` : `${hours}시간 ${rest}분`
}

//: 끊긴 이유의 사람 말. 없으면 빈 문자열.
export function stopReasonText(reason: string | null | undefined, timeoutSeconds?: number | null): string {
  if (reason === 'timeout') return `시간 초과(제한 ${formatTimeout(timeoutSeconds)}) — 결과는 모름, 실패가 아니다`
  if (reason === 'stop_requested') return '중단 요청으로 끊음'
  return ''
}

//: "제한 시간 늘려 다시 시도" 의 기본 제안값(분) — 적용했던 제한의 두 배, 최대 24시간. 지금 제한보다 커야 다시 돈다.
export function suggestedMinutes(appliedSeconds: number | null | undefined, currentSeconds?: number | null): number {
  const base = Math.max(appliedSeconds ?? 0, currentSeconds ?? 0, 60)
  return Math.min(Math.ceil((base * 2) / 60), TIMEOUT_MAX_SECONDS / 60)
}

//: 분 입력 → 초. 범위 밖이면 null(보내지 않는다).
export function minutesToSeconds(text: string): number | null {
  const value = Number(text)
  if (!Number.isFinite(value) || value <= 0) return null
  const seconds = Math.round(value * 60)
  if (seconds < TIMEOUT_MIN_SECONDS || seconds > TIMEOUT_MAX_SECONDS) return null
  return seconds
}
