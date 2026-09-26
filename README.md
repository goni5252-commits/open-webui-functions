# Open WebUI Functions

Open WebUI에서 사용할 수 있는 함수를 공유합니다.

| 함수 | 편집 원본 | 배포 파일 |
| --- | --- | --- |
| OpenAI Responses | [Python](functions/openai_responses.py) | [v1.7.8 JSON](function-openai_responses-v1.7.8.json) |
| Google Gemini | [Python](functions/google_gemini.py) | [JSON](function-google_gemini.json) |
| Gemini RAG Bypass | [Python](functions/google_gemini_rag_bypass.py) | [JSON](function-google_gemini_rag_bypass.json) |

**[업데이트 내역 보기](CHANGELOG.md)** · [커밋 기록](https://github.com/goni5252-commits/open-webui-functions/commits/main/)

## 개요

OpenWebUI를 통해 OpenAI ChatGPT 및 Google Gemini API를 연결, 소규모 자체 LLM 서버를 운영하기 위해 만든 함수들을 공유합니다.


## 모든 사용자용 공통 하네스 (Responses v1.7.8 / Harness 1.1.0)

공통 `AGENTS.md → catalog.json → 필요한 SKILL.md` 구조입니다. 새 기능을 catalog에 등록하면 함수에 기능별 지침을 추가하지 않아도 됩니다. 실제 적용 범위는 모델/관리자 Terminal 연결 권한을 가진 사용자입니다.

| 계층 | 기본 경로 | 내용 |
|---|---|---|
| core | `/opt/openwebui-harness` | 공개 공통 지침·스킬·스크립트, 읽기 전용 |
| site | `/opt/openwebui-site` | 학교 내부 공통 지침·기존 스킬·양식, 읽기 전용 |
| workspace | 현재 OS 계정 홈 아래 `.openwebui-workspaces/task-*` | 요청별 원본 복사본·중간 파일·결과 |

- **[하네스 ZIP](harness/open-terminal-harness-v1.1.0.zip)** · [SHA-256](harness/open-terminal-harness-v1.1.0.zip.sha256)
- **[설치·전체 사용자 적용 안내](harness/open-terminal/INSTALL.md)**
- **[기존 개인 kordoc 지침 이전](harness/open-terminal/MIGRATION.md)**
- [새 기능 추가 규약](harness/open-terminal/EXTENDING.md) · [공통 진입점](harness/open-terminal/AGENTS.md)

PPT / getdesign 참조 / PPT 테마 변환 / HWPX / 가정통신문 / 규정 신구대조표의 여섯 기본 스킬을 포함합니다.
가정통신문·신구대조표 지침은 새 공통 기본 지침입니다. 기존 서버의 실제 지침을 복제한 것은 아니므로 MIGRATION 안내에 따라 검토 후 site override로 등록하세요. 실제 학교 양식이나 개인정보는 패키지에 포함하지 않습니다.

학교 site는 core 업데이트와 별도로 유지됩니다. site catalog는 명시적 override와 기능 비활성화를 지원하며 중복 ID·외부 경로·누락 파일을 검사합니다. 동작하는 함수 서버에서 Terminal 파일을 직접 읽지 않고 모델이 Terminal 도구로 필요한 지침을 읽습니다.

설정: `ENABLE_TERMINAL_HARNESS=True`, `TERMINAL_HARNESS_ROOT=/opt/openwebui-harness`, `TERMINAL_HARNESS_ENTRYPOINT=AGENTS.md`, `TERMINAL_HARNESS_SITE_ROOT=/opt/openwebui-site`.
이전 `ENABLE_PRESENTATION_DESIGN` 값은 새 이름으로 이전되며 새 값이 있으면 우선합니다. 하네스 패키지와 함수 JSON을 함께 업데이트하세요.

v1.7.7의 대기 문구 중복 제거, `COMPACT_STATUS_UPDATES`, 첨부 원본 전달, 파일 카드 처리는 유지합니다.
공유 컨테이너의 사용자별 홈은 강한 사용자 간 보안 경계가 아닙니다. 실제 전체 사용자 연결/격리는 서버 운영 구성으로 확인해야 합니다. 다른 모델 함수에는 같은 진입점 읽기 연결이 별도로 필요합니다.
