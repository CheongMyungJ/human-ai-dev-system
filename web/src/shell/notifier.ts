// 브라우저 알림(UI-04b, D-82). 전이 계산은 `lib/notify.ts`(순수)가 하고 여기는 브라우저 API 만 다룬다.
//
//   **권한은 사람이 켤 때 청한다.** 브라우저가 사용자 행동 없이는 권한 요청을 막는다. 권한이 없으면 팝업은
//   없고 화면 안 기록만 남는다 — 기록이 곧 "알렸다" 는 뜻이 아니다.
//   **팝업 클릭은 사람의 행동이다.** 그 대화를 여는 것은 자동 전환이 아니다.

import type { Notice } from '../lib/notify'
import { NOTICE_LABEL } from '../lib/notify'

export type PermissionState = 'granted' | 'denied' | 'default' | 'unsupported'

export function permissionState(): PermissionState {
  if (typeof Notification === 'undefined') return 'unsupported'
  return Notification.permission
}

export async function requestPermission(): Promise<PermissionState> {
  if (typeof Notification === 'undefined') return 'unsupported'
  try {
    return await Notification.requestPermission()
  } catch {
    return Notification.permission
  }
}

/** 팝업을 띄운다. 권한이 없으면 아무 것도 하지 않고 `false`. */
export function show(notice: Notice, onOpen: () => void): boolean {
  if (permissionState() !== 'granted') return false
  try {
    const popup = new Notification(`${NOTICE_LABEL[notice.kind]} · ${notice.title}`, {
      body: notice.body,
      tag: notice.key,
    })
    popup.onclick = () => {
      window.focus()
      onOpen()
      popup.close()
    }
    return true
  } catch {
    return false
  }
}
