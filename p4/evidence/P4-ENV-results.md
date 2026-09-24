# P4-ENV 실험 결과 — 실제 codex 의 검증 실행이 이 호스트에서 시험을 돌리지 못하는 원인과 풀리는 조건

상태: **실험 완료 — 원인 확인, 풀리는 조건 확인(환경 조치 하나 + 절대 경로). 제품 코드는 바꾸지 않았다.**
기준: [P4 수용 확인](P4-ACCEPT-results.md) 6절·7절 2 / [DEVELOPMENT](../../DEVELOPMENT.md) 9절 "검증 실행이 이 호스트에서 시험을 돌리지 못한다" /
[환경 계약](../../p1-environment-contract.md) 6~8절 / 2026-09-24. 세션 S-034(사용자 허용 "codex 사용 가능하니 환경실험 해도되고").
**제품 규칙의 통과가 아니라 환경·CLI 샌드박스의 사실을 적는 실험이다.** 스크립트 `p4/live/verify_env.py`(제품 코드 import 없음),
로그 `P4-ENV-live.log`·결과 `P4-ENV-live-results.json`(최종 회차 `183717`), 이전 회차는 `P4-ENV-live-183132.*`(네 조건)·`P4-ENV-live-183504.*`.

## 1. 배경

P3-04·P4-05·P4-06·P4-06b·P4-07 의 실제 codex 라이브에서 검증 실행은 셸에서 `python`·`py` 를 찾지 못했고(P4-05 라이브에서는 codex 가
가상환경의 `python.exe` 를 찾아 절대 경로로도 시도했으나 "기본 Python 설치 경로가 없어" 실패), 그래서 제품이 `met` 을 실제 검증 실행으로
적은 라이브 증거가 없었다(기준은 전부 `unverified` → 사람의 예외 수용으로만 종료). 이 호스트의 셸에서는 `python`(3.12, `%LOCALAPPDATA%\Programs\Python\Python312`)·
`py` 가 해석된다([환경 계약](../../p1-environment-contract.md) 4절).

## 2. AI 없이 본 것 — `codex sandbox <명령>` (Windows 제한 토큰 샌드박스)

`codex sandbox` 는 모델 없이 명령 하나를 codex 의 Windows 샌드박스(사용자 설정 `[windows] sandbox = "elevated"`, 제한 토큰 + 로컬 그룹
`CodexSandboxUsers` + 작업공간별 SID)에서 돌린다. 제품이 쓰기 실행에 주는 `--sandbox workspace-write` 가 쓰는 것과 같은 실행기다.

| 시도 | 결과 | 뜻 |
|---|---|---|
| `python --version`, `py --version` | `CreateProcessAsUserW failed: 2 (지정된 파일을 찾을 수 없습니다)` | 샌드박스 안의 PATH 로는 인터프리터가 해석되지 않는다 |
| `C:\Users\USER\AppData\Local\Programs\Python\Python312\python.exe --version` (절대 경로) | `CreateProcessAsUserW failed: 5 (액세스가 거부되었습니다)` | **원인**: 제한 토큰이 사용자 프로필 아래의 Python 설치 폴더를 읽지 못한다(그 폴더의 ACL 은 SYSTEM·Administrators·USER 뿐) |
| 절대 경로 + `-c 'sandbox_permissions=["disk-full-read-access"]'` | 같은 error 5 | 그 설정으로는 풀리지 않는다 |
| `-c shell_environment_policy.inherit=all` + `python --version` | error 2 | 환경 변수 상속 정책의 문제가 아니다 |
| **환경 조치**: `icacls "%LOCALAPPDATA%\Programs\Python\Python312" /grant "CodexSandboxUsers:(OI)(CI)(RX)"` 뒤 절대 경로 `python.exe --version` | **`Python 3.12.10`** | 샌드박스 그룹에 읽기·실행을 주면 절대 경로로 실행된다 |
| 같은 조치 뒤 절대 경로 `python.exe -m unittest -v`(표본 저장소) | **`Ran 1 test … OK`** | 시험 실행도 된다 |
| 같은 조치 뒤 `python --version`(PATH) | 여전히 error 2 | PATH 해석은 별개 — **절대 경로가 필요하다** |

환경 조치는 이 PC 의 Python 3.12 설치 폴더에 codex 샌드박스 그룹의 읽기·실행 ACE 하나를 더한 것이다(되돌리기:
`icacls "%LOCALAPPDATA%\Programs\Python\Python312" /remove "CodexSandboxUsers"`). 제품·저장소 파일은 바꾸지 않았다. `py` 런처·3.14 는 조치하지 않았다.

## 3. 실제 codex 로 본 것 — `codex exec` 네 조건(2절의 환경 조치 뒤)

`p4/live/verify_env.py` 가 표본 저장소(`app.py` + `tests/test_app.py`, 표준 라이브러리 `unittest`)를 만들고 codex 에게 "시험을 실행하고
JSON 으로 보고, 파일은 바꾸지 말 것" 을 지시했다(제품과 같은 `exec --json --skip-git-repo-check -C <저장소>` + 조건별 인자, 프롬프트는
stdin). 세 회차 — `183132`(네 조건), `183504`·`183717`(A 만 재실행). 사용자 설정은 `approval_policy = "never"`·`[windows] sandbox = "elevated"`.

| 조건 | 인터프리터 해석(codex 의 셸 = pwsh) | `python -m unittest -v` | 파일 |
|---|---|---|---|
| A `--sandbox workspace-write`(제품이 쓰기 실행에 주는 값) | `python --version` → **Python 3.12.10**, `Get-Command python` → `…\Python312\python.exe`; `py` 는 미해석 | 회차 183132·183504: `NO TESTS RAN`(exit 5) — **표본의 결함**(시험 함수가 `TestCase` 가 아니었고 `tests/__init__.py` 가 없었다, 스크립트 수정). **회차 183717: exit 0 · `OK`(1 test)** — `unittest_ran_ok_observed = true` | 무변경 |
| B A + 지시에 절대 경로 | `& '…\Python312\python.exe' -m unittest -v` 실행됨(exit 5 = 표본 결함, 인터프리터는 돌았다) | 표본 결함 회차만(재실행하지 않음) | 무변경 |
| C A + `-c shell_environment_policy.inherit=all` | A 와 같음 | 표본 결함 회차만 | 무변경 |
| D `--sandbox danger-full-access`(대조군) | `python`·`py`·`where.exe` 전부 해석(Python312·314·WindowsApps·Launcher) | 표본 결함 회차만 | 무변경 |

읽는 법: **인터프리터 실행은 네 조건 전부에서 됐다**(2절의 조치 뒤) — B·C·D 의 `NO TESTS RAN` 은 표본 저장소의 결함이지 샌드박스가 아니며,
그 결함을 고친 뒤 제품 기본 조건 A 만 다시 돌려 시험 통과를 관측했다(B·C·D 는 조치의 효과가 이미 A 로 보이므로 다시 돌리지 않았다).
조치 전의 상태는 2절의 AI 없는 실행(error 2·5)과 P3-04·P4-05 라이브의 관측이 말한다. `py` 런처는 `workspace-write` 에서 여전히 보이지
않는다(런처 폴더에는 조치하지 않았다).

## 4. 뜻 — 제품에 무엇이 필요한가(제안, 결정 아님)

- **원인은 환경이다.** codex 의 Windows 제한 토큰 샌드박스는 사용자 프로필 아래의 Python 설치(기본 설치 위치)를 읽지 못한다. 제품이 쓰기
  실행에 `--sandbox workspace-write` 를 주는 한 이 조치(인터프리터 폴더에 샌드박스 그룹 읽기·실행) 없이는 검증 실행이 시험을 돌리지 못한다.
  `danger-full-access` 로 바꾸는 것은 권한 모델의 변경(제품 판단)이며 이 실험은 그것을 권하지 않는다 — 조치 하나로 기본 샌드박스 안에서 된다.
- **PC 마다 한 번의 조치다.** 인터프리터가 어디 있든(사용자 설치·전체 설치·venv 의 기반 설치) 그 폴더에 `CodexSandboxUsers` 의 RX 가 있어야
  한다. 저장소의 `.venv` 는 원래 폴더에 있고 작업공간(worktree)에는 없으므로, 실제 프로젝트의 시험은 **기반 인터프리터 + 프로젝트별 환경
  준비**(의존성 설치)가 따로 필요하다 — 이것은 P4-05 결과 5절이 남긴 "Project 별 환경 설정" 그대로다.
- **제품 반영 후보**(사용자 결정, 별도 plan): (a) Runner 기동 시 "샌드박스 그룹이 인터프리터를 읽을 수 있는가" 를 능력 행으로 보고(막지
  않고 표시 — `runner-host/interpreter`), (b) 프로젝트 설정에 "검증 인터프리터 경로·준비 명령" 을 두고 검증 지시문에 싣기(P4-05 의 이월
  질문 "Python 검증 환경 지정" 이 매번 나오는 자리), (c) 설치 안내(`scripts\bootstrap.ps1`·README)에 ACL 조치를 적기(P6-04 설치와 함께).
- **아직 없는 것:** 제품 경유 라이브(검증 실행이 `met` 을 실제 명령으로 적는 것)는 이 실험 뒤 아직 하지 않았다 — 다음 라이브(P5 또는
  별도)에서 본다. 이 실험은 codex 를 직접 부른 관찰이며 이 PC 하나의 사실이다.
