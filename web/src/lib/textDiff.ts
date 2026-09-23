// 두 버전 본문의 줄 단위 비교(D-85 `변경 내용 보기`). 브라우저에서 계산하고 원문은 메모리에만
// 있다. **import 가 없다** — Node 내장 시험 실행기로 돌린다.
//
// 가장 긴 공통 부분열(LCS)로 같은 줄을 맞춘다. 문서는 사람이 읽는 크기이므로 O(n·m) 로 충분하되,
// 너무 크면 계산하지 않고 그 사실을 돌려준다(화면이 멈추지 않게).

export type DiffOp = 'same' | 'added' | 'removed'

export interface DiffLine {
  op: DiffOp
  text: string
}

export interface DiffResult {
  lines: DiffLine[]
  added: number
  removed: number
  // 계산하지 않았다(너무 큼). 같다는 뜻이 아니다.
  tooLarge: boolean
}

export const DIFF_CELL_LIMIT = 4_000_000

export function splitLines(text: string): string[] {
  const normalized = text.replace(/\r\n/g, '\n')
  if (normalized === '') return []
  const lines = normalized.split('\n')
  if (lines[lines.length - 1] === '') lines.pop()
  return lines
}

export function diffLines(before: string, after: string): DiffResult {
  const a = splitLines(before)
  const b = splitLines(after)
  if (a.length * b.length > DIFF_CELL_LIMIT) {
    return { lines: [], added: 0, removed: 0, tooLarge: true }
  }
  // 앞뒤 공통 부분은 표를 만들지 않고 맞춘다.
  let start = 0
  while (start < a.length && start < b.length && a[start] === b[start]) start += 1
  let endA = a.length
  let endB = b.length
  while (endA > start && endB > start && a[endA - 1] === b[endB - 1]) {
    endA -= 1
    endB -= 1
  }
  const midA = a.slice(start, endA)
  const midB = b.slice(start, endB)
  const n = midA.length
  const m = midB.length
  const table: Uint32Array[] = []
  for (let i = 0; i <= n; i += 1) table.push(new Uint32Array(m + 1))
  for (let i = n - 1; i >= 0; i -= 1) {
    for (let j = m - 1; j >= 0; j -= 1) {
      table[i][j] =
        midA[i] === midB[j] ? table[i + 1][j + 1] + 1 : Math.max(table[i + 1][j], table[i][j + 1])
    }
  }
  const lines: DiffLine[] = a.slice(0, start).map((text) => ({ op: 'same' as const, text }))
  let i = 0
  let j = 0
  let added = 0
  let removed = 0
  while (i < n && j < m) {
    if (midA[i] === midB[j]) {
      lines.push({ op: 'same', text: midA[i] })
      i += 1
      j += 1
    } else if (table[i + 1][j] >= table[i][j + 1]) {
      lines.push({ op: 'removed', text: midA[i] })
      removed += 1
      i += 1
    } else {
      lines.push({ op: 'added', text: midB[j] })
      added += 1
      j += 1
    }
  }
  for (; i < n; i += 1) {
    lines.push({ op: 'removed', text: midA[i] })
    removed += 1
  }
  for (; j < m; j += 1) {
    lines.push({ op: 'added', text: midB[j] })
    added += 1
  }
  for (const text of a.slice(endA)) lines.push({ op: 'same', text })
  return { lines, added, removed, tooLarge: false }
}
