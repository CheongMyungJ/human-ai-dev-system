// 대화 검색 화면(UI-04d, D-84). 현재 프로젝트의 대화(보관 포함)를 제목·요약·결정·규칙(서버)과 본문(소유 PC)에서
// 찾는다. **범위는 서버가 말한다** — PC 가 미연결이면 "본문 N건 제외" 를 그대로 보이고, 본문 결과는 PC 가 올린 뒤
// 도착한다. 발췌는 서버 메모리로만 중계된 것이며 저장되지 않는다. 결과를 누르면 그 대화의 그 메시지·결정·규칙으로
// 이동한다(기존 `seq`·패널·규칙 화면 경로). 검색어는 주소에도 서버에도 남지 않는다.

import { useState } from 'react'

import { SEARCH_KIND_LABEL, type ProjectWithAttention, type SearchMatch, type SearchView } from '../api'
import { groupByCase, highlight, scopeText, titleMatches, tokens } from '../lib/search'

export interface SearchState {
  query: string
  view: SearchView | null
  status: 'idle' | 'searching' | 'done' | 'expired' | 'error'
  error: string | null
}

export const EMPTY_SEARCH: SearchState = { query: '', view: null, status: 'idle', error: null }

function Excerpt(props: { text: string; words: string[] }) {
  return (
    <>
      {highlight(props.text, props.words).map((piece, i) =>
        piece.hit ? (
          <mark key={i} className="sh-hit">
            {piece.text}
          </mark>
        ) : (
          <span key={i}>{piece.text}</span>
        ),
      )}
    </>
  )
}

export function SearchScreen(props: {
  project: ProjectWithAttention
  search: SearchState
  onSearch: (query: string) => void
  onOpenMessage: (caseId: string, seq: number | null) => void
  onOpenDecisions: (caseId: string) => void
  onOpenRule: (itemKey: string) => void
  onBack: () => void
}) {
  const { search } = props
  const [draft, setDraft] = useState(search.query)
  const view = search.view
  const words = view ? view.words : tokens(draft)
  const groups = view ? groupByCase(view.matches) : []
  const open = (match: SearchMatch) => {
    if (match.target === 'rule' && match.item_key) props.onOpenRule(match.item_key)
    else if (match.target === 'message') props.onOpenMessage(match.case_id, match.seq)
    else if (match.target === 'decisions') props.onOpenDecisions(match.case_id)
    else props.onOpenMessage(match.case_id, null)
  }
  return (
    <div className="sh-rules sh-settings-screen sh-search-screen" data-testid="search-screen" data-status={search.status}>
      <header className="sh-header">
        <div className="sh-header-title">
          <h1>대화 검색 · {props.project.name}</h1>
          <span className="sh-muted">
            보관된 대화까지 제목·요약·결정·규칙은 이 서버에서, 본문은 원문을 가진 작업 PC 에서 찾는다. 검색어·발췌는
            저장되지 않는다. 프로젝트 코드·파일 검색이 아니다
          </span>
        </div>
        <div className="sh-header-actions">
          <button type="button" className="sh-link" onClick={props.onBack} data-testid="search-back">
            ← 대화로
          </button>
        </div>
      </header>
      <div className="sh-rules-body">
        <form
          className="sh-search-form sh-search-form-wide"
          onSubmit={(event) => {
            event.preventDefault()
            if (draft.trim()) props.onSearch(draft.trim())
          }}
        >
          <input
            value={draft}
            placeholder="찾을 낱말(공백으로 나누면 전부 있어야 한다)"
            onChange={(e) => setDraft(e.target.value)}
            data-testid="search-screen-input"
          />
          <button type="submit" className="sh-primary" disabled={!draft.trim() || search.status === 'searching'} data-testid="search-screen-submit">
            검색
          </button>
        </form>
        {search.error && (
          <p className="sh-warn" data-testid="search-error">
            검색하지 못했다: {search.error}
          </p>
        )}
        {view && (
          <p className="sh-muted" data-testid="search-scope" data-bodies={view.scope.bodies}>
            범위: {scopeText(view.scope)}
            {search.status === 'expired' && ' · 본문 결과를 기다리는 시간이 지났다 — 다시 검색한다'}
          </p>
        )}
        {view && groups.length === 0 && search.status !== 'searching' && (
          <p className="sh-muted" data-testid="search-empty">
            일치하는 대화가 없다(검색한 범위 안에서).
          </p>
        )}
        {view && (
          <div data-testid="search-results" data-count={view.matches.length}>
            {groups.map((group) => (
              <section key={group.case_id} className="sh-search-group" data-testid={`search-case-${group.case_id}`}>
                <h3 className="sh-section-title">
                  <button type="button" className="sh-link" onClick={() => props.onOpenMessage(group.case_id, null)} data-testid={`search-open-${group.case_id}`}>
                    {titleMatches(group.title, words) ? <Excerpt text={group.title} words={words} /> : group.title}
                  </button>
                  {group.archived && <span className="sh-badge sh-badge-plain"> 보관됨</span>}
                  {['closed', 'cancelled'].includes(group.status) && <span className="sh-badge sh-badge-plain"> 종료</span>}
                </h3>
                <ul className="sh-result-list">
                  {group.matches.map((match, i) => (
                    <li key={`${match.kind}-${match.seq ?? 'x'}-${i}`}>
                      <button
                        type="button"
                        className="sh-row sh-search-hit"
                        onClick={() => open(match)}
                        data-testid={`search-hit-${group.case_id}-${i}`}
                        data-kind={match.kind}
                        data-seq={match.seq ?? ''}
                        data-source={match.source}
                      >
                        <span className="sh-badge sh-badge-plain">{SEARCH_KIND_LABEL[match.kind] ?? match.kind}</span>
                        {match.seq !== null && <span className="sh-muted"> #{match.seq}</span>}
                        {match.author && <span className="sh-muted"> · {match.author === 'assistant' ? 'AI' : '나'}</span>}{' '}
                        <span className="sh-search-excerpt">
                          <Excerpt text={match.text} words={words} />
                        </span>
                        {match.match_count > 1 && <span className="sh-muted"> · {match.match_count}회</span>}
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            ))}
          </div>
        )}
        {!view && search.status === 'idle' && (
          <p className="sh-muted">낱말을 넣고 검색한다. 결과에서 해당 메시지·결정·규칙으로 이동한다.</p>
        )}
      </div>
    </div>
  )
}
