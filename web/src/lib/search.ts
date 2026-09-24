// 대화 검색의 화면 쪽 순수 규칙(UI-04d, D-84). **import 가 없다.**
//
//   낱말 규칙은 서버·PC 와 같다(`domain/search.py`): 공백으로 나눈 낱말 전부, 대소문자 무시. 화면은 그 낱말로
//   발췌를 **강조**할 뿐 스스로 일치를 판정하지 않는다 — 결과는 서버가 준 것이다.
//   범위 문구도 서버의 `note` 를 그대로 보이되, 상태 코드별 짧은 이름표는 여기서 정한다.

import type { SearchBodyState, SearchMatch, SearchScope } from '../api'

const MAX_TOKENS = 8

export function tokens(query: string): string[] {
  const seen: string[] = []
  for (const word of (query ?? '').trim().toLowerCase().split(/\s+/)) {
    if (word && !seen.includes(word)) seen.push(word)
  }
  return seen.slice(0, MAX_TOKENS)
}

export interface Piece {
  text: string
  hit: boolean
}

/** 발췌를 강조 조각으로 나눈다. 낱말은 대소문자 무시로 찾고 겹치면 긴 것을 먼저 본다. */
export function highlight(text: string, words: string[]): Piece[] {
  if (!text) return []
  const lowered = text.toLowerCase()
  const sorted = [...words].filter(Boolean).sort((a, b) => b.length - a.length)
  const pieces: Piece[] = []
  let at = 0
  while (at < text.length) {
    let bestStart = -1
    let bestLen = 0
    for (const word of sorted) {
      const idx = lowered.indexOf(word, at)
      if (idx >= 0 && (bestStart < 0 || idx < bestStart || (idx === bestStart && word.length > bestLen))) {
        bestStart = idx
        bestLen = word.length
      }
    }
    if (bestStart < 0) {
      pieces.push({ text: text.slice(at), hit: false })
      break
    }
    if (bestStart > at) pieces.push({ text: text.slice(at, bestStart), hit: false })
    pieces.push({ text: text.slice(bestStart, bestStart + bestLen), hit: true })
    at = bestStart + bestLen
  }
  return pieces
}

export const BODY_STATE_LABEL: Record<SearchBodyState, string> = {
  none: '본문 없음',
  pending: '본문 검색 중(PC)',
  partial: '일부 PC 의 본문만',
  relayed: '본문 포함(PC)',
  expired: '본문 검색 만료',
  excluded: 'PC 미연결 — 본문 제외',
}

/** 범위 한 줄. 서버의 `note` 가 정본이고 앞에 짧은 이름표를 붙인다. */
export function scopeText(scope: SearchScope): string {
  return `${BODY_STATE_LABEL[scope.bodies] ?? scope.bodies} · ${scope.note}`
}

export interface CaseGroup {
  case_id: string
  title: string
  archived: boolean
  status: string
  matches: SearchMatch[]
}

/** 대화별로 묶는다(제목 일치·본문 일치가 한 묶음). 순서는 첫 일치가 나온 순서, 묶음 안은 순번 순. */
export function groupByCase(matches: SearchMatch[]): CaseGroup[] {
  const groups = new Map<string, CaseGroup>()
  for (const match of matches) {
    let group = groups.get(match.case_id)
    if (!group) {
      group = { case_id: match.case_id, title: match.case_title, archived: match.archived, status: match.status, matches: [] }
      groups.set(match.case_id, group)
    }
    group.matches.push(match)
  }
  for (const group of groups.values()) {
    group.matches.sort((a, b) => (a.seq ?? -1) - (b.seq ?? -1))
  }
  return [...groups.values()]
}

/** 제목 일치는 서버 필드 목록에 따로 없다 — 낱말이 제목에 들어 있으면 화면이 묶음 머리에 표시한다. */
export function titleMatches(title: string, words: string[]): boolean {
  if (!words.length || !title) return false
  const lowered = title.toLowerCase()
  return words.every((w) => lowered.includes(w))
}
