# Open WebUI Functions

OpenWebUI에서 대화, 이미지 생성, 한글 OCR과 문서 내보내기를 사용하는 함수 모음입니다. 아래 JSON은 항상 최신 버전입니다.

| 함수 | 버전 | 간단한 설명 | 다운로드 |
|---|---|---|---|
| OpenAI Responses | 1.8.7 | 자동 모델 선택, 이미지 생성·편집, PDF/OCR, Terminal 문서 제작 | [JSON](function-openai_responses.json) |
| Google Gemini | 1.26.1 | Hydrogen 자동 추론·이미지 생성·한글 OCR | [JSON](function-google_gemini.json) |
| Gemini RAG Bypass | 1.0.1 | 백엔드 RAG 검색을 우회하고 첨부 원본을 Gemini에 전달하는 필터 | [JSON](function-google_gemini_rag_bypass.json) |
| EXAONE Auto | 1.0.0 | K-EXAONE 2.5 텍스트 대화의 low/high/max 자동 추론 선택 | [JSON](function-exaone_auto.json) |
| 한글 문서 내보내기 | 3.4.0 | 답변의 표·수식·이미지 등을 HWPX로 저장 | [JSON](function-한글문서_내보내기.json) |
| 엑셀로 내보내기 | 0.4.0 | 답변의 Markdown 표를 XLSX로 저장 | [JSON](function-엑셀로_내보내기.json) |

## 설치

1. 사용할 JSON을 다운로드해 OpenWebUI 관리자 패널의 함수에서 가져오고 활성화합니다.
2. API 연결 함수의 Valves에 API 키와 필요한 설정을 입력합니다.
3. 기존 함수 ID와 대화 연결을 유지하려면 [Python 원본](functions/)의 코드를 기존 함수 편집 화면에 붙여 넣고 저장합니다.

각 함수 헤더의 OpenWebUI 최소 버전과 의존성을 확인하세요. 헤더의 `requirements` 자동 설치를 꺼두었다면 서버에 직접 설치해야 합니다. Gemini는 `google-genai==3.3.0`을 사용하며, 이미 다른 SDK가 로드되어 있었다면 설치 후 서버를 재시작하세요. GitHub 업데이트만으로 서버 함수가 바뀌지는 않습니다.

## Gemini Hydrogen

- 일반 대화: `gemini-4-hydrogen`. `AUTO_THINKING=true`이면 요청에 따라 low/medium/high를 로컬 판단하며 xhigh는 high로 제한합니다. 대화별 추론 설정이 우선합니다.
- 이미지 생성·편집: `ENABLE_CONVERSATION_IMAGES=true`, `CONVERSATION_IMAGE_SMART_SELECTION=true`. 요청에 맞춰 `AUTO_IMAGE_MODEL`(기본 `gemini-3.1-flash-image`)을 호출합니다. 일반 대화에서는 불필요한 이미지 도구를 제외하고 스트리밍을 유지합니다.
- 한글 OCR: **Gemini 4 Hydrogen 한글 OCR (High-Res)** / `gemini-4-hydrogen-ocr`. 기본 고해상도·low 추론으로 원문을 전사하며 검색·이미지 생성 도구를 제외합니다. 기존 Flash OCR과 `OCR_*` 설정을 공유합니다.
- RAG 우회: **Gemini RAG Bypass 필터를 활성화하고 사용할 Gemini 모델에 적용**하세요. 기본 접두사는 `google_gemini`이며 함수 ID를 바꾸었다면 필터의 `MODEL_ID_PREFIXES`도 맞추세요. OCR은 원본 PDF 전달에 실패하면 일부 추출 텍스트로 대체하지 않습니다.
- 모델 목록을 제한했다면 `MODEL_WHITELIST`에 사용할 모델 ID를 추가하세요. OCR 표시에는 `ENABLE_OCR_VIRTUAL_MODEL=true`가 필요합니다.

자동 판단에는 별도 분류 API 호출이 없습니다. 실제 추론·이미지 생성·검색에는 시간과 비용이 들며, OCR 정확도와 응답 속도를 보장하지 않습니다.

## OpenAI · EXAONE

- OpenAI의 `gpt-6-auto`는 요청에 따라 Terra/Sol/Astra와 추론 강도를 선택합니다. 이미지 생성, `gpt-6-ocr`, Terminal 파일 도구를 지원합니다.
- 일반 PDF는 기본 50페이지 미만이면 원본 전달, 이상이면 Mistral OCR을 사용합니다. 긴 PDF에는 `PDF_MISTRAL_API_KEY` 또는 서버 환경변수의 키가 필요합니다. `PDF_MISTRAL_PAGE_THRESHOLD=0`이면 원본 전달을 사용합니다. 해당 모델의 File Upload를 켜고 File Context를 꺼 중복 RAG 주입을 방지하세요.
- EXAONE Auto는 텍스트 전용이며 자동 모드에서 분류와 답변 API를 각각 호출합니다. 첨부·도구·이미지는 지원하지 않습니다.

## 문서 제작과 내보내기

HWPX/XLSX Action은 기존 답변을 파일로 저장합니다. 새 문서·PPT 제작에는 별도 Open Terminal 연결이 필요합니다. 고급 문서 작업은 최신 [Open Terminal 하네스 v1.2.0](harness/open-terminal-harness-v1.2.0.zip)과 [설치 안내](harness/open-terminal/INSTALL.md)를 참고하세요.

## 저장소 구성

- `functions/`: 최신 Python 원본
- `function-*.json`: 함수별 최신 배포 파일 1개
- `tests/`, `scripts/`: 동작 검증 및 배포 도구
- `harness/`: 최신 Terminal 하네스와 사용 문서

이전 버전은 Git 기록에서 확인할 수 있습니다. 실제 서버 설치·계정 접근 권한·유료 API 품질은 사용자 환경에서 확인해야 합니다.
