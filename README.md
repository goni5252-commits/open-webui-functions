# Open WebUI Functions

Open WebUI에서 사용할 수 있는 함수를 공유합니다.

| 함수 | 편집 원본 | 배포 파일 |
| --- | --- | --- |
| OpenAI Responses | [Python](functions/openai_responses.py) | [v1.7.7 JSON](function-openai_responses-v1.7.7.json) |
| Google Gemini | [Python](functions/google_gemini.py) | [JSON](function-google_gemini.json) |
| Gemini RAG Bypass | [Python](functions/google_gemini_rag_bypass.py) | [JSON](function-google_gemini_rag_bypass.json) |

**[업데이트 내역 보기](CHANGELOG.md)** · [커밋 기록](https://github.com/goni5252-commits/open-webui-functions/commits/main/)

## 개요

OpenWebUI를 통해 OpenAI ChatGPT 및 Google Gemini API를 연결, 소규모 자체 LLM 서버를 운영하기 위해 만든 함수들을 공유합니다.


## Open Terminal 하네스 기반 PPT 제작 (Responses v1.7.7)

상세 제작 지침을 함수에서 분리했습니다. **함수 JSON과 Terminal 하네스 패키지를 함께 적용**하세요.

- [하네스 1.0.0 ZIP](harness/open-terminal-harness-v1.0.0.zip) · [SHA-256](harness/open-terminal-harness-v1.0.0.zip.sha256)
- [Windows / WSL2 / Docker 설치·이전 안내](harness/open-terminal/INSTALL.md)
- [하네스 원본](harness/open-terminal) · [작업 목록](harness/open-terminal/INDEX.md)

권장 구성은 서버의 버전별 하네스 폴더를 Terminal의 `/opt/openwebui-harness`에 읽기 전용으로 bind mount하는 것입니다. 기존 사용자 데이터 볼륨은 유지하고 결과물은 사용자별 작업 폴더에 저장합니다.

`ENABLE_PRESENTATION_DESIGN=True`(이름은 기존 설정 호환), `TERMINAL_HARNESS_ROOT=/opt/openwebui-harness`를 설정합니다.
새 `get_terminal_harness`는 INDEX.md 읽기 명령만 반환하며, 설치 확인이나 파일 읽기를 함수 서버에서 하지 않습니다.
모델이 Terminal을 통해 INDEX와 필요한 지침을 읽고 실행합니다. 하네스가 없으면 설치 필요를 알리도록 안내합니다.

패키지에는 PPT 제작 / 디자인 참조 / PPT 디자인 변환의 세 SKILL과 환경 진단, 격리된 getdesign 다운로드, 기본 편집형 PPTX 빌더, 구조·경계 검증 스크립트 및 예제가 있습니다.
모델이 DESIGN.md 의미를 해석하여 테마를 만듭니다. 고정 파서가 모든 웹 디자인을 자동 재현하는 기능은 아닙니다.
기본 빌더에는 python-pptx, 다운로드에는 Node/npm/npx가 필요합니다. 패키지나 글꼴을 자동 설치하지 않습니다.
학교 HWPX/PDF 제작 기능은 이번 하네스에 포함하지 않았습니다.

예시: `getdesign.md의 Claude 스타일로 인공지능 활용 연수 PPT 5장을 만들어줘. 설치된 Terminal 하네스를 읽고 PPTX 파일 카드로 제공해줘.`

`COMPACT_STATUS_UPDATES=True`는 진행 상태의 긴 도구 인자·결과를 줄입니다. 실제 모델에 전달되는 도구 결과와 파일 카드는 그대로 유지됩니다.
created/in_progress의 같은 대기 문구는 제거했고, 기본 모드에서는 도구 후속 요청마다 대기 문구를 다시 쌓지 않습니다.
45초간 표시 활동이 없을 때 같은 대기 구간에서 한 번 안내합니다. 상세 모드(False)에서도 한 API 요청의 lifecycle 중복은 제거됩니다.
이전에 저장된 대화 상태 기록은 수정하지 않습니다.

검증은 오프라인 회귀 및 로컬 PPTX 생성/구조 검사 범위입니다. 실제 OpenWebUI/Windows/WSL2 서비스, CLI 네트워크 다운로드와 렌더링 시각 품질은 서버 적용 후 확인해야 합니다.
