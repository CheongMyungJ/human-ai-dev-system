# 연속 검토 중 기술 확인과 검증 과제

확인일: 2026-09-20. 공식 문서에 근거한 호환성 설계 참고이다. 제품의 구현 완료·설치 검증·성능 측정 결과를 뜻하지 않는다.

## Windows와 코딩 CLI

- Codex 공식 Windows 문서는 네이티브 실행과 Windows sandbox를 설명한다. 설치한 CLI 버전의 인터페이스·권한·중단 동작은 별도 실험으로 확인해야 한다. 공식 영문 주소는 조회 시 404여서 실제 조회 가능한 공식 번역 문서를 참고했다. [공식 Windows sandbox 문서](https://developers.openai.com/es-419/docs/windows/windows-sandbox)
- Claude Code는 Windows 네이티브 설치를 지원하지만 내장 sandbox는 Windows 네이티브에서 지원하지 않고 WSL2에서는 지원한다고 안내한다. Windows 네이티브 공통 모드에서 세 CLI의 OS 격리 수준이 같다고 주장할 수 없다. [공식 설치 안내](https://code.claude.com/docs/en/setup)
- OpenCode는 Windows 설치 방법을 제공하면서 WSL 사용을 권장한다. 사용자 요청에 따라 미설치 상태로 문서 기반 어댑터를 먼저 작성하는 범위이며, 네이티브에서 실제 실행 검증을 완료했다고 표시하지 않는다. [공식 안내](https://opencode.ai/docs/)
- 현재 도구 프로세스의 PATH 조회에서 codex.exe가 확인되었다. 다른 CLI가 PATH에서 조회되지 않았다는 사실만으로 PC에 설치되지 않았다고 판단하지 않는다. 로그인·인증 정보 원문은 조회하지 않았다.

## 제어 서비스와 저장소 제안

Python/FastAPI·SQLite·React/TypeScript 구성은 D-53에서 채택했다. 아래 배치·검증 방법은 공식 문서 사실을 바탕으로 한 상세 설계 제안이다.

- Python/FastAPI 제어 서비스는 모듈형 단일 서비스로 시작하고 Runner는 별도 프로세스로 둔다. 장시간 업무의 유일한 복구 수단으로 웹 요청의 BackgroundTasks를 사용하지 않는다. 업무 배정·외부 게시를 DB에 영속적으로 남긴다. [FastAPI BackgroundTasks](https://fastapi.tiangolo.com/tutorial/background-tasks/)
- 개인용·소규모 서버는 제어 서비스 호스트의 로컬 SQLite 파일을 사용할 수 있다. 원격 Runner가 네트워크 공유 DB 파일을 직접 여는 구조는 피한다. 동시 쓰기 경쟁과 복구는 검증 과제이다. [SQLite 사용 범위](https://www.sqlite.org/whentouse.html)
- 여러 제어 프로세스 또는 동시 쓰기 요구가 커지면 PostgreSQL을 검토한다. 서버 설치라는 이유만으로 PostgreSQL을 반드시 요구하지 않는다. [PostgreSQL 구조](https://www.postgresql.org/docs/current/tutorial-arch.html)
- 브라우저 UI는 React/TypeScript를 사용한다. Python 서버가 빌드된 정적 UI를 제공하고 제어·실행은 Python 중심으로 구성한다. 서버 템플릿 대안과 비교 후 사용자 선택을 반영했다. [FastAPI 템플릿](https://fastapi.tiangolo.com/advanced/templates/)
- Windows 자식 프로세스 실행에서 스트림 소비·출력 크기·프로세스 트리 정리를 검증해야 한다. 부모 프로세스 종료를 모든 자식·외부 작업의 종료로 간주하지 않는다. [Python asyncio subprocess](https://docs.python.org/3/library/asyncio-subprocess.html)

## 구현 착수 전 기술 검증 목록

| 항목 | 확인해야 할 결과 | 실패 시 처리 |
|---|---|---|
| CLI 도구 경계 일시 중지 | 단절 감지 후 현재 호출 다음 도구를 배정하지 않고 상태를 보존 | 해당 실행 모드 미지원 표시. 사용자의 단절 정책을 몰래 완화하지 않음 |
| 권한 통제 | 읽기 전용 조사·허용된 쓰기·외부 반영의 분리가 선택한 OS/CLI 구성에서 실제 작동 | 사용 가능한 제한 모드 또는 추가 실행 환경을 명시하고 정책 선택에 연결 |
| Windows 자식 프로세스 | 큰 출력·종료·충돌·자식 잔류를 탐지하고 결과 불명을 보존 | 무조건 성공/중단으로 표기하지 않고 상태 대조 |
| 중복 배정과 늦은 결과 | 연결 단절·응답 유실·재시작 중 같은 변경이 이중 실행되지 않음 | 정지 확인 전 재배정 보류, 기존 실행 결과 대조 |
| DB와 산출물 복원 | 업무 상태·승인·아티팩트 참조가 일치하는 백업에서 복구 | 불완전한 복원은 완료로 표시하지 않고 복구 상태 제시 |
| 승인 대상 일치 | 사용자가 본 내용·대상·버전만 적용 | 중요 변경 시 기존 승인을 재사용하지 않음 |

기술 검증 계획이 존재하는 것과 검증 통과를 구분한다. OpenCode는 문서 계약 검증과 추후 설치된 환경의 실증 검증을 별도로 표시한다.
