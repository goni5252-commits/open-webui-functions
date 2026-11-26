# Open WebUI Functions

OpenWebUI에서 대화, 이미지 생성, 한글 OCR과 문서 내보내기를 사용하는 함수 모음입니다. 아래 JSON은 항상 최신 버전입니다.

| 함수 | 버전 | 간단한 설명 | 다운로드 |
|---|---|---|---|
| OpenAI Responses | 1.9.7 | 자동 모델 선택, 이미지 생성·편집, PDF/OCR, Terminal 문서 제작 | [JSON](function-openai_responses.json) |
| Google Gemini | 1.27.1 | Hydrogen·Neon 자동 추론·이미지 생성·한글 OCR | [JSON](function-google_gemini.json) |
| Gemini RAG Bypass | 1.0.1 | 백엔드 RAG 검색을 우회하고 첨부 원본을 Gemini에 전달하는 필터 | [JSON](function-google_gemini_rag_bypass.json) |
| EXAONE Auto | 1.0.0 | K-EXAONE 2.5 텍스트 대화의 low/high/max 자동 추론 선택 | [JSON](function-exaone_auto.json) |
| 한글 문서 내보내기 | 3.4.0 | 답변의 표·수식·이미지 등을 HWPX로 저장 | [JSON](function-한글문서_내보내기.json) |
| 엑셀로 내보내기 | 0.4.0 | 답변의 Markdown 표를 XLSX로 저장 | [JSON](function-엑셀로_내보내기.json) |

## 설치

1. 사용할 JSON을 다운로드해 OpenWebUI 관리자 패널의 함수에서 가져오고 활성화합니다.
2. API 연결 함수의 Valves에 API 키와 필요한 설정을 입력합니다.
3. 기존 함수 ID와 대화 연결을 유지하려면 [Python 원본](functions/)의 코드를 기존 함수 편집 화면에 붙여 넣고 저장합니다.

각 함수 헤더의 OpenWebUI 최소 버전과 의존성을 확인하세요. 헤더의 `requirements` 자동 설치를 꺼두었다면 서버에 직접 설치해야 합니다. Gemini는 `google-genai==3.3.0`을 사용하며, 이미 다른 SDK가 로드되어 있었다면 설치 후 서버를 재시작하세요. GitHub 업데이트만으로 서버 함수가 바뀌지는 않습니다.

## Gemini Hydrogen · Neon

- OpenWebUI 0.13.4 내장 시각화(`render_visualization`)의 완료된 호출·결과를 화면에 보존합니다. 모델에서 시각화 도구를 활성화하세요. HTML 임베드와 Terminal 파일 표시도 지원합니다.
- 일반 대화: `gemini-4-hydrogen`, `gemini-4-neon`. `AUTO_THINKING=true`이면 요청에 따라 low/medium/high를 로컬 판단하며 xhigh는 high로 제한합니다. 대화별 추론 설정이 우선합니다.
- 이미지 생성·편집: `ENABLE_CONVERSATION_IMAGES=true`, `CONVERSATION_IMAGE_SMART_SELECTION=true`. 요청에 맞춰 `AUTO_IMAGE_MODEL`(기본 `gemini-3.1-flash-image`)을 호출합니다. 일반 대화에서는 불필요한 이미지 도구를 제외하고 스트리밍을 유지합니다.
- HWPX 제작: 일반 Gemini 모델에 Open Terminal을 연결하고 native 도구 호출을 사용하세요. Terminal에 설치된 kordoc으로 문서를 생성하고 확인한 뒤 파일 카드로 반환하도록 안내합니다.
- 한글 OCR: **Gemini 4 Hydrogen / Neon 한글 OCR (High-Res)**: `gemini-4-hydrogen-ocr`, `gemini-4-neon-ocr`. 기본 고해상도·low 추론으로 원문을 전사하며 검색·이미지 생성 도구를 제외합니다. 기존 Flash OCR과 `OCR_*` 설정을 공유합니다.
- RAG 우회: **Gemini RAG Bypass 필터를 활성화하고 사용할 Gemini 모델에 적용**하세요. 기본 접두사는 `google_gemini`이며 함수 ID를 바꾸었다면 필터의 `MODEL_ID_PREFIXES`도 맞추세요. OCR은 원본 PDF 전달에 실패하면 일부 추출 텍스트로 대체하지 않습니다.
- Vertex AI 429/일시적 서버 오류는 일반 대화·OCR에서 `RETRY_COUNT`(기본 2)만큼 재시도합니다. 429는 약 4초·8초에 무작위 지연을 더해 대기합니다. 스트림의 첫 데이터 수신 전 오류도 처리하며, 수신 이후·네이티브 도구 작업·이미지 생성 요청은 전체 재실행하지 않습니다. Google 측 용량이나 할당량 문제 자체를 해결하지는 않습니다.
- 기존에 저장된 `MODEL_ADDITIONAL` 설정에도 Hydrogen과 Neon을 자동 등록합니다. 모델 표시가 API 접근 권한을 보장하지는 않으며 실제 사용에는 해당 모델을 호출할 수 있는 Gemini API 키가 필요합니다.
- 모델 목록을 제한했다면 `MODEL_WHITELIST`에 사용할 모델 ID를 추가하세요. OCR 표시에는 `ENABLE_OCR_VIRTUAL_MODEL=true`가 필요합니다.

자동 판단에는 별도 분류 API 호출이 없습니다. 실제 추론·이미지 생성·검색에는 시간과 비용이 들며, OCR 정확도와 응답 속도를 보장하지 않습니다.

## OpenAI · EXAONE

- OpenAI의 최종 파일은 `deliver_terminal_files`가 Terminal `display_file`로 확인하여 전달합니다. 같은 작업실·같은 경로의 카드는 현재 응답 안에서 최신 결과 하나로 갱신합니다. Terminal 작업 후 카드 없이 응답을 끝내려 하면 호출 횟수 한도 내에서 한 차례 전달 보완을 시도합니다. 이때 추가 모델 호출이 발생할 수 있으며, 원본·스크립트·중간 파일은 최종 산출물에서 제외하도록 안내합니다. 표시 실패 시 원래 도구 결과와 파일 존재 여부를 모델에 전달하여 경로·백그라운드 작업 완료 상태를 확인하게 합니다. 실패를 성공으로 처리하지 않습니다.

- OpenAI는 최신 `base_user_prompt`와 기존 `user_prompt`를 지원합니다. `Logs`의 `Tool diagnostics`, `Tool execution`, `File display diagnostics`에서 도구 전달·호출·파일 표시 단계를 확인할 수 있습니다. 진단에는 도구 인수나 파일 내용을 기록하지 않습니다.
- OpenAI는 OpenWebUI의 `machine` 도구·프록시·파일 표시 이벤트를 지원하고 기존 `terminal` 연동도 유지합니다.

- OpenAI는 대화 기록의 `content: null` 메시지를 빈 내용으로 처리하며, 요청 실패 시 서버 로그에 traceback을 남깁니다.
- OpenWebUI 0.13.4 내장 시각화(`render_visualization`)의 완료된 호출·결과를 화면에 전달합니다. 모델에서 시각화 도구를 활성화해야 하며, HTML 임베드와 Terminal 파일 표시도 지원합니다.
- OpenAI의 `gpt-6.2-auto`는 학습지·반복 자료 제작에 Luna/medium을 사용하고, 생기부 분석 등 근거 중심 작업에는 최대 GPT-6.2 Sol/medium을 사용합니다. 명확한 학습지 제작·생기부 요청은 별도 분류 API 호출을 생략합니다. 이미지 생성, `gpt-6-ocr`, Terminal 파일 도구를 지원합니다. 기존 `gpt-6-auto` 모델 목록은 새 이름으로 이전되며 기존 대화의 호출도 호환됩니다.
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
