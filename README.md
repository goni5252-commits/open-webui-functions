# Open WebUI Functions

Open WebUI에서 사용할 수 있는 함수를 공유합니다.

| 함수 | 편집 원본 | 배포 파일 |
| --- | --- | --- |
| OpenAI Responses | [Python](functions/openai_responses.py) | [v1.7.6 JSON](function-openai_responses-v1.7.6.json) |
| Google Gemini | [Python](functions/google_gemini.py) | [JSON](function-google_gemini.json) |
| Gemini RAG Bypass | [Python](functions/google_gemini_rag_bypass.py) | [JSON](function-google_gemini_rag_bypass.json) |

**[업데이트 내역 보기](CHANGELOG.md)** · [커밋 기록](https://github.com/goni5252-commits/open-webui-functions/commits/main/)

## 개요

OpenWebUI를 통해 OpenAI ChatGPT 및 Google Gemini API를 연결, 소규모 자체 LLM 서버를 운영하기 위해 만든 함수들을 공유합니다.


## DESIGN.md 기반 PPT 제작 (Responses v1.7.6)

최신 JSON을 OpenWebUI 함수에 가져오고 Open Terminal 연결을 선택합니다.
`ENABLE_PRESENTATION_DESIGN=True`가 기본값입니다. 별도 MCP 서버는 필요하지 않습니다.
Terminal에 Python 3, Node.js/npm/npx와 PPT 제작 라이브러리(PptxGenJS 또는 python-pptx)가 필요합니다.
getdesign 다운로드에는 npm/getdesign 네트워크 접근이 필요합니다. 기존 설치에 없는 패키지를 함수가 시작 시 자동 설치하지는 않습니다.

예시: `인공지능 활용 연수 PPT 10장을 Vercel 스타일로 만들어줘. getdesign.md의 DESIGN.md를 사용하고 PPTX 다운로드 카드로 제공해줘.`
또는 DESIGN.md를 첨부하고 `첨부 디자인을 적용해 발표자료를 만들어줘`라고 요청합니다.

새 `prepare_presentation_design` 도구는 다운로드 명령과 PPT 변환 규칙을 반환합니다.
실제 파일 다운로드·토큰 추출·PPT 제작·렌더링·display_file 호출은 모델이 연결된 Terminal 도구로 수행합니다.
이 도구 자체가 PPT 생성 엔진이거나 디자인 다운로드 완료를 보장하는 것은 아닙니다.
별도 SKILL.md 설치 없이 함수의 지침과 전용 도구로 제작/디자인 참조/변환 단계를 연결합니다.
스타일을 요청하지 않은 일반 대화에서는 디자인을 다운로드하지 않도록 안내합니다.

- getdesign 공식 CLI `npx -y getdesign@latest add <slug>`를 요청별 임시 폴더에서 실행합니다. 기존 DESIGN.md를 덮어쓰지 않습니다.
- slug는 사이트 카탈로그에서 확인한 값을 사용합니다. 예: `vercel`, `notion`, `linear.app`. Gamma 등 다른 이름의 존재는 가정하지 않습니다.
- 첨부 DESIGN.md는 첨부 원본 전달 기능으로 가져옵니다. 관리자 Terminal 및 저장된 대화 요건은 기존 v1.7.5와 같습니다.
- 디자인의 색상·타이포·여백·카드·이미지 규칙을 `ppt-theme.json`으로 정리하고, 웹 전용 효과는 제외하도록 안내합니다.
- 한글 글꼴은 Terminal에서 확인하여 적용합니다. 렌더링 도구가 없다면 시각 검증 미실시를 명시하도록 안내합니다.
- 다운로드 실패·유료 접근 제한 시 디자인을 적용했다고 주장하지 않고 첨부 파일이나 다른 스타일을 요청하도록 안내합니다.
- 임시 디자인 폴더는 자동 정리하지 않습니다. getdesign@latest의 실제 버전은 실행 시점에 따라 바뀝니다.

설치 후 위 예시로 도구 호출 → DESIGN.md 경로 → ppt-theme.json → PPTX 생성 → 파일 카드 다운로드를 확인하세요.
실제 Windows/WSL2 서버의 패키지·글꼴·네트워크 및 모델의 절차 준수는 로컬 오프라인 테스트 범위 밖입니다.
