// 화면 진입점. **기본은 대화 화면**(UI-03)이고 `?view=admin` 은 기존 관리 화면이다.
//
// 두 화면의 스타일이 섞이지 않도록 각 화면을 **나눠서** 불러온다 — 관리 화면의 다크 스타일이 대화
// 화면에 새지 않고, 대화 화면의 테마가 관리 화면을 바꾸지 않는다.

import { StrictMode, type ComponentType } from 'react'
import { createRoot } from 'react-dom/client'

async function start() {
  const admin = new URLSearchParams(window.location.search).get('view') === 'admin'
  document.body.dataset.view = admin ? 'admin' : 'shell'
  let Root: ComponentType
  if (admin) {
    Root = (await import('./AdminEntry')).App
  } else {
    Root = (await import('./shell/Shell')).Shell
  }
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <Root />
    </StrictMode>,
  )
}

void start()
