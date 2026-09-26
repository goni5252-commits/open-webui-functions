# Open WebUI Functions

Open WebUI에서 사용할 수 있는 함수를 공유합니다.

| 함수 | 편집 원본 | 배포 파일 |
| --- | --- | --- |
| OpenAI Responses | [Python](functions/openai_responses.py) | [v1.7.9 JSON](function-openai_responses-v1.7.9.json) |
| Google Gemini | [Python](functions/google_gemini.py) | [JSON](function-google_gemini.json) |
| Gemini RAG Bypass | [Python](functions/google_gemini_rag_bypass.py) | [JSON](function-google_gemini_rag_bypass.json) |

**[업데이트 내역 보기](CHANGELOG.md)** · [커밋 기록](https://github.com/goni5252-commits/open-webui-functions/commits/main/)

## 개요

OpenWebUI를 통해 OpenAI ChatGPT 및 Google Gemini API를 연결, 소규모 자체 LLM 서버를 운영하기 위해 만든 함수들을 공유합니다.


## 간단하게 시작하기 — v1.7.9 기본 사용법

**기존 Open Terminal에서 문서 생성이 되고 있다면 함수 JSON만 업데이트하세요. 하네스 ZIP, 폴더 마운트, catalog.json, SKILL.md 설치는 필요하지 않습니다.**

1. [함수 JSON](function-openai_responses-v1.7.9.json)을 OpenWebUI 함수에 가져오고 기존 API 설정을 확인합니다.
2. 대화에서 기존 Open Terminal 연결을 선택합니다.
3. 필요한 양식을 첨부하고 원하는 작업을 요청합니다.

예시:
- `첨부한 학교 양식을 유지해서 현장체험학습 가정통신문을 HWPX로 만들어줘.`
- `두 규정을 비교하고 첨부 양식으로 신구대조표를 만들어줘.`
- `Claude 스타일의 연수 PPT 5장을 만들어줘. getdesign.md의 디자인 참조를 사용해줘.`

기존에 설치된 kordoc과 문서 제작 도구를 활용합니다. 특정 작업에 필요한 라이브러리·글꼴이 없으면 그 항목만 준비해야 합니다. getdesign 다운로드에는 npm/npx 및 네트워크 연결이 필요합니다.
학교 양식은 첨부하는 것이 가장 간단합니다. 기존 개인 AGENTS.md/스킬은 적절할 때 재사용하도록 안내하며 파일을 삭제하거나 이전하지 않습니다. 개인 지침이 다른 사용자에게 자동 공유되는 것은 아닙니다.

관리자 연결과 모델 사용 권한을 부여받은 사용자에게 같은 기본 제작 안내가 적용됩니다. 공통 제작 안내가 사용자의 개인 파일이나 실제 서버 접근 권한을 공유하는 것은 아닙니다.

기본 `DOCUMENT_WORKFLOW_MODE=simple`은 이전 ENABLE_TERMINAL_HARNESS=True 설정이 남아 있어도 하네스를 요구하지 않습니다. 기존 하네스 폴더는 그대로 둬도 됩니다. 대기 문구 정리·첨부 원본 전달·파일 카드 기능은 유지합니다.

제작은 모델이 기존 Terminal 도구로 수행합니다. 출력 품질이나 카드 성공을 지침만으로 보장하지 않으며 실제 도구 결과를 확인해야 합니다.

## 고급 선택 기능: 공통 하네스

학교별 스킬·양식을 중앙 관리하려는 경우에만 `DOCUMENT_WORKFLOW_MODE=harness`, `ENABLE_TERMINAL_HARNESS=True`로 설정합니다.
기본 사용자는 아래 파일을 설치할 필요가 없습니다.

- [고급 설치 안내](harness/open-terminal/INSTALL.md)
- [기존 지침 이전](harness/open-terminal/MIGRATION.md)
- [새 기능 추가 규약](harness/open-terminal/EXTENDING.md)
- [공통 하네스 ZIP](harness/open-terminal-harness-v1.1.0.zip)

고급 모드는 core/site의 읽기 전용 공통 자산과 사용자별 작업 폴더를 사용합니다. 하네스 1.1.0을 이미 설치했다면 재설치 없이 선택할 수 있습니다.
