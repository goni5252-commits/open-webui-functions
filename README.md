# Open WebUI Functions — 한글 문서와 PPT 만들기

OpenWebUI 대화에서 **학교 양식으로 HWPX를 작성하고, 디자인을 참고해 PPT를 만들어 내려받는 환경**을 구성합니다.

- OpenWebUI: 대화하는 화면
- OpenAI Responses 함수: 모델과 문서 제작 도구를 연결
- Open Terminal: 실제 파일을 만들고 보관하는 별도 실행 환경

**이미 문서 생성이 되고 있다면 재설치하지 마세요. 아래 [함수 설정](#3-openwebui에-함수-적용하기)과 [사용 예시](#5-실제로-사용해-보기)만 확인하면 됩니다.**

| 다운로드 | 용도 |
|---|---|
| [OpenAI Responses v1.8.3 JSON](function-openai_responses-v1.8.3.json) · [직접 다운로드](https://raw.githubusercontent.com/goni5252-commits/open-webui-functions/main/function-openai_responses-v1.8.3.json) | 이 안내에서 사용하는 함수 |
| [엑셀 내보내기 v0.4.0 JSON](function-엑셀로_내보내기-v0.4.0.json) | 답변의 Markdown 표를 XLSX로 저장하는 Action (Open WebUI 0.11.4+) |
| [한글 내보내기 v3.4.0 JSON](function-한글문서_내보내기-v3.4.0.json) | 기존 답변을 HWPX로 저장하는 Action (Open WebUI 0.11.4+) |
| [Google Gemini v1.24.1 JSON](function-google_gemini-v1.24.1.json) | 별도 Gemini 함수 |
| [Gemini RAG Bypass JSON](function-google_gemini_rag_bypass.json) | 별도 RAG Bypass 함수 |

[변경 내역](CHANGELOG.md) · [OpenAI 함수 Python 원본](functions/openai_responses.py)

**GPT-6.1 Sol / PDF 페이지 수에 따른 처리 (v1.8.3)**

- `gpt-6.1-sol`, `gpt-6.1-sol-auto`를 선택할 수 있으며 저장된 모델 목록에도 자동 추가됩니다. `gpt-6-auto`의 Sol 단계와 기본 fallback도 `gpt-6.1-sol`입니다. Luna/Astra 선택 기준과 직접 선택하는 기존 Sol 모델은 유지합니다.
- `PDF_NATIVE_INPUT=true`에서 PDF마다 페이지 수를 확인합니다. **49페이지까지는 PDF 원본을 OpenAI Responses에 직접 전달하고, 50페이지 이상은 Mistral OCR을 호출한 뒤 추출한 전체 텍스트·표를 전달합니다.** 여러 파일의 합계 페이지 수로 판단하지 않습니다.
- `PDF_MISTRAL_PAGE_THRESHOLD=50`이 기본이며 관리자 Valves에서 변경할 수 있습니다. `0`이면 모든 PDF 원본을 직접 전달합니다. `gpt-6-ocr` 전용 모델의 기존 Luna/Sol 전사·분할 경로는 별도로 유지됩니다.
- 긴 PDF의 OCR 결과에는 페이지 번호가 붙으며 이미지 원본은 포함하지 않습니다. 차트·도장·배치 분석이 중요하면 기준을 `0`으로 바꾸어 원본을 보내세요. OCR 텍스트도 GPT 입력 토큰으로 과금되며 RAG처럼 일부 문단만 보내는 방식은 아닙니다.
- 성공한 OCR 결과는 같은 사용자·동일 파일 내용·OCR 설정에 한해 **30분, 함수 인스턴스당 최대 8개**를 메모리에 캐시합니다. 접근 권한은 매번 재확인합니다. 재시작·다중 워커·캐시 만료/퇴출 시 재호출될 수 있으며 GPT 입력 비용까지 없어지는 것은 아닙니다.
- WebUI DB에서 접근 권한을 확인한 저장소 원본만 읽습니다. 현재 전달된 대화 메시지의 이전 첨부도 처리하며 중복 ID는 한 번만 읽습니다. 페이지 수 판별 불가·암호화·원본 누락·권한 실패·OCR 누락/실패는 명확한 오류로 알리고 원본 API 전송으로 자동 우회하지 않습니다.
- 원본 합계는 기본 50MB(`PDF_NATIVE_MAX_MB`, 낮출 수 있음), 단일 파일은 50MB 미만입니다. OCR 텍스트는 파일당 100만 문자 한도로, 초과 시 임의로 자르지 않고 분할을 요청합니다. 모델 토큰 한도와 각 API 제한도 적용됩니다. 기존 API `file_id`/URL 입력은 이 페이지 분기의 대상이 아닙니다.
- ID 없는 임시 대화 PDF와 지식 컬렉션 전체 자동 펼치기는 지원하지 않습니다. 컬렉션의 PDF는 개별 파일로 일반 대화에 첨부하세요.

**적용 순서**

1. 위 **OpenAI Responses v1.8.3 JSON**을 기존 함수에 가져옵니다.
2. 함수의 관리자 **Valves → `PDF_MISTRAL_API_KEY`**에 Mistral 키를 입력합니다. 비어 있으면 서버 환경변수 `MISTRAL_API_KEY`, `MISTRAL_OCR_API_KEY` 순으로 사용합니다. 기존 WebUI 문서 설정에 저장한 키는 자동으로 복사되지 않습니다. 키가 없을 때 짧은 PDF는 정상 전달되고, 50페이지 이상 PDF만 설정 오류로 안내합니다. 키를 채팅에 보내지 마세요.
3. `PDF_MISTRAL_PAGE_THRESHOLD=50`을 확인합니다. OCR 모델 기본값은 `mistral-ocr-latest`, 주소는 `https://api.mistral.ai/v1`입니다. 특정 OCR 버전을 쓰려면 `PDF_MISTRAL_MODEL`에 지정합니다.
4. **관리자 패널 → 설정 → 문서 → 콘텐츠 추출 엔진**은 `Mistral OCR` 대신 **`Default`**로 둡니다. 전역 Mistral 추출을 켜두면 함수가 페이지 수를 판단하기 전에 짧은 PDF도 Mistral로 보내져 이중 처리될 수 있습니다. Default는 WebUI의 로컬 추출이며 함수의 조건부 Mistral 호출과 별개입니다. 전역 엔진 변경은 다른 모델의 업로드에도 영향을 줍니다.
5. 사용할 모델의 **File Upload는 켜고, File Context는 끕니다.** File Context를 켜두면 원본/OCR 결과 외에 RAG 텍스트가 중복 주입될 수 있습니다. 새 일반 대화에서 짧은 PDF와 긴 PDF를 각각 첨부해 `PDF 전달: 원본 N개 · Mistral OCR 텍스트 N개` 상태를 확인하세요.

함수는 업로드 단계나 기존 대화에 주입된 RAG 문구를 소급 변경하지 않습니다. 이 저장소 업데이트에는 실제 서버 설치·설정 변경이 포함되지 않습니다. 다른 문서도 사용하는 경우 File Context를 끈 모델에서 해당 문서가 읽히는지 별도로 확인하세요. 페이지 판별에는 OpenWebUI의 `pypdf`가 필요합니다.

근거: [GPT-6.1 Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol), [OpenAI 파일 입력](https://developers.openai.com/api/docs/guides/file-inputs), [Mistral OCR API](https://docs.mistral.ai/api/endpoint/ocr), [OpenWebUI Mistral 설정](https://docs.openwebui.com/features/chat-conversations/rag/document-extraction/mistral-ocr/), [File Context 설정](https://docs.openwebui.com/features/chat-conversations/rag/#file-context-vs-builtin-tools).

스캔 PDF 전사는 모델 목록에서 **`gpt-6-ocr`**를 선택하세요. GPT-6 Luna(`low`)로 먼저 읽고, 출력 검사에 실패한 묶음만 GPT-6 Sol(`medium`)로 재시도합니다. 원본 PDF 전송·RAG 우회·기본 10페이지 분할을 사용합니다. 기존 `gpt-5.6-ocr` 대화도 새 경로로 연결되며, 저장된 모델 목록과 이전 OCR fallback 설정은 자동 이전됩니다. 재시도를 끈 설정은 유지됩니다. 새 설정 이름은 `OCR_SOL_FALLBACK`입니다.

## 1. 어떤 환경을 기준으로 하나요?

Windows 서버에서 **Docker Desktop의 WSL2 방식으로 OpenWebUI를 이미 실행 중**인 경우를 기준으로 합니다. 아래는 Open Terminal을 추가하는 안내이며 OpenWebUI 자체 설치 안내는 아닙니다.

프로젝트 사용자가 제공한 설치 확인 결과는 다음과 같습니다.

| 도구 | 확인된 버전/상태 | 역할 |
|---|---|---|
| kordoc | 4.14.4 | HWP/HWPX 읽기·양식 채우기·편집 |
| python-pptx | 1.0.2 | PPTX 생성·수정 |
| Node.js | v22.23.2 | kordoc 및 디자인 다운로드 도구 실행 |
| npm / npx | 10.9.8 | Node 도구 설치·실행 |
| 한글 글꼴 | 나눔고딕·나눔바른고딕 등 설치 | 한글 표시 |
| LibreOffice | 25.2.3.2 | Office 파일 변환·미리보기 보조 |

이는 **사용자 화면에서 확인한 설치 상태**입니다. 실제 서버의 Compose 파일, 포트, 메모리 한도, 볼륨 이름까지 확인한 것은 아닙니다. 아래 설정은 비슷한 환경을 새로 만드는 예시이며, 기존 서버 설정을 그대로 복제한 것은 아닙니다. PDF 출력 품질까지 검증됐다는 뜻도 아닙니다.

## 2. Open Terminal 처음 설치하기

> **기존 Open Terminal이 있다면 이 단계는 건너뛰세요.** 새 볼륨을 만들면 기존 파일이 자동으로 옮겨오지 않습니다. 기존 설치를 교체하려면 사용 중인 볼륨과 실행 설정을 먼저 보존해야 합니다.

### ① Windows 서버에서 작업 폴더 열기

Docker Desktop을 실행한 상태에서 **Windows PowerShell**을 엽니다. 다음 명령은 채팅 속 Terminal에서 실행하는 명령이 아닙니다.

```powershell
New-Item -ItemType Directory -Path C:\OpenWebUI\terminal-docs -Force | Out-Null
Set-Location C:\OpenWebUI\terminal-docs
```

이 폴더에 `Dockerfile`, `compose.yaml`, `.env` 세 파일을 준비합니다.

### ② Dockerfile 만들기

```powershell
notepad Dockerfile
```

아래 내용을 붙여 넣고 저장합니다. 파일명이 `Dockerfile.txt`가 되지 않도록 메모장의 파일 형식을 **모든 파일**로 선택하세요.

```dockerfile
FROM ghcr.io/open-webui/open-terminal:latest
USER root
RUN python3 -m pip install --no-cache-dir python-pptx==1.0.2
RUN npm install -g --omit=optional kordoc@4.14.4
RUN apt-get update && apt-get install -y --no-install-recommends fontconfig fonts-nanum fonts-noto-cjk && fc-cache -f && rm -rf /var/lib/apt/lists/*
USER user
```

이 파일은 필요한 프로그램과 글꼴을 **컨테이너를 다시 만들어도 사용할 수 있는 이미지**에 넣습니다. 공식 기본 이미지의 Node.js·LibreOffice를 활용하므로 새로 설치되는 버전이 위 표와 정확히 같지는 않을 수 있습니다. `slim`/`alpine` 이미지로 바꾸지 마세요. 이 예시는 기본 이미지용입니다. [공식 Dockerfile](https://github.com/open-webui/open-terminal/blob/main/Dockerfile)

`--omit=optional`은 HWPX 중심의 가벼운 설치입니다. kordoc의 선택 의존성을 사용하는 PDF 분석·OCR 등의 기능은 별도 의존성이 필요할 수 있습니다. [kordoc 설치 안내](https://github.com/chrisryugj/kordoc#설치)

### ③ compose.yaml 만들기

```powershell
notepad compose.yaml
```

아래 내용을 저장합니다. `compose.yaml.txt`로 저장하지 마세요.

```yaml
services:
  open-terminal:
    build: .
    image: open-terminal-docs:local
    container_name: open-terminal-docs
    restart: unless-stopped
    ports:
      - "8000:8000"
    environment:
      OPEN_TERMINAL_API_KEY: "${OPEN_TERMINAL_API_KEY:?Set OPEN_TERMINAL_API_KEY in .env}"
      OPEN_TERMINAL_MULTI_USER: "true"
    volumes:
      - terminal-docs-data:/home

volumes:
  terminal-docs-data:
```

| 설정 | 의미 |
|---|---|
| `8000:8000` | Windows 서버의 8000번 포트로 Terminal 연결 |
| `OPEN_TERMINAL_API_KEY` | Terminal 연결 암호. **OpenAI API 키와 다릅니다.** |
| `OPEN_TERMINAL_MULTI_USER=true` | 사용자별 실행 계정과 홈 폴더 사용 |
| `terminal-docs-data:/home` | 사용자 파일을 Docker 볼륨에 보관 |
| `restart: unless-stopped` | Docker가 시작되면 서비스를 다시 실행 |

8000번 포트를 이미 쓰고 있다면 왼쪽만 `8001:8000`으로 바꾸고, 아래 연결 주소도 8001로 바꿉니다. 이 예시는 새 서비스를 위한 이름/볼륨을 사용합니다.

다중 사용자 모드는 같은 신뢰 수준의 사용자가 공유하는 환경을 위한 작업 폴더 분리입니다. **서로 신뢰하지 않는 사용자 간 보안 격리를 보장하지 않습니다.** 그런 환경은 사용자별 컨테이너 구성이 필요합니다. [Open Terminal 공식 설명](https://github.com/open-webui/open-terminal#built-in-multi-user-mode)

### ④ Terminal 연결 암호 만들기

같은 PowerShell 폴더에서 아래 명령을 한 번 실행합니다. 기존 `.env`가 있으면 덮어쓰지 않고 멈춥니다.

```powershell
if (Test-Path .env) { throw '기존 .env가 있습니다. 기존 암호를 확인하세요.' }
$terminalSecret = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
Set-Content -Path .env -Encoding ascii -Value "OPEN_TERMINAL_API_KEY=$terminalSecret"
notepad .env
```

메모장에서 `OPEN_TERMINAL_API_KEY=` 뒤의 값을 복사해 두세요. 다음 단계에서 관리자 연결에 넣습니다. `.env`는 GitHub에 올리거나 일반 사용자에게 배포하지 않습니다.

### ⑤ 실행하기

```powershell
docker compose config --quiet
docker compose up -d --build
docker compose ps
```

첫 실행은 이미지 다운로드와 프로그램 설치 때문에 시간이 걸립니다. 오류가 없고 컨테이너가 실행 중이면 다음 단계로 갑니다. 실행 실패 시:

```powershell
docker compose logs --tail 80 open-terminal
```

이 새 설치 예시는 로컬에서 실제 Docker 빌드까지 검증한 구성이 아닙니다. 다운로드 실패가 있으면 오류 내용을 확인하세요. 설치 폴더의 세 파일을 보관하면 같은 방식으로 다시 만들 수 있습니다.

## 3. OpenWebUI에 함수 적용하기

1. 위의 **OpenAI Responses v1.8.3 JSON**을 저장합니다. GitHub의 Raw/다운로드를 사용하고 웹페이지 HTML을 저장하지 마세요.
2. OpenWebUI의 **워크스페이스 → 함수**에서 가져오기 기능으로 JSON을 불러옵니다. 메뉴 명칭은 버전에 따라 조금 다를 수 있습니다.
3. 함수를 활성화하고 Valve 설정에서 자신의 OpenAI API 키를 입력합니다. 이미 사용 중이면 기존 API 설정을 확인합니다.
4. 아래 설정은 기본값을 유지하면 됩니다.

| 함수 설정 | 값 | 의미 |
|---|---|---|
| `DOCUMENT_WORKFLOW_MODE` | `simple` | 추가 하네스 설치 없이 문서 제작 |
| `COMPACT_STATUS_UPDATES` | `True` | 대기·도구 실행 표시를 간결하게 |
| `ENABLE_TERMINAL_ATTACHMENT_TRANSFER` | `True` | 필요할 때 첨부 원본을 Terminal로 전달 |

**하네스 ZIP, AGENTS.md, SKILL.md, catalog.json을 새로 설치할 필요는 없습니다.** 기존에 쓰던 개인 지침 파일은 삭제하지 않아도 됩니다.

## 4. OpenWebUI와 Terminal 연결하기

OpenWebUI의 **관리자 설정 → 연동(Integrations) → Open Terminal**에서 연결을 추가합니다. 일반 도구 서버 등록 메뉴가 아닌 **Open Terminal 메뉴**를 사용합니다. [공식 연결 안내](https://github.com/open-webui/open-terminal#using-with-open-webui)

위 예시처럼 Windows Docker Desktop에서 OpenWebUI와 Terminal을 각각 실행한다면:

| 입력 항목 | 입력할 값 |
|---|---|
| 이름 | 문서 제작 Terminal 등 알아보기 쉬운 이름 |
| URL | `http://host.docker.internal:8000` |
| API Key | 앞서 `.env`에 저장한 Terminal 연결 암호 |
| 사용 권한 | 사용할 사용자 또는 그룹 |

이 주소는 **Docker 안의 OpenWebUI가 Windows 호스트의 공개 포트로 연결하는 예시**입니다. OpenWebUI 컨테이너 안의 `localhost`는 Terminal을 가리키지 않습니다.

- 두 서비스를 같은 Docker 네트워크로 운영한다면 서비스 이름으로 연결할 수도 있지만, 위 예시는 그 추가 설정을 요구하지 않습니다.
- OpenWebUI가 다른 서버에 있다면 위 주소 대신 그 서버에서 접근 가능한 Terminal 주소가 필요합니다.
- Terminal 포트를 외부에 공개할 필요는 없습니다. 공유기 포트 포워딩이나 Cloudflare 공개 주소 추가는 이 예시의 설치 단계에 포함하지 않습니다.

관리자 연결을 저장하고 사용하려는 모델도 대상 사용자에게 허용하세요. 대화 화면에서 `gpt-6-auto` 등 해당 함수의 모델과 Terminal 연결을 선택합니다. 개인 설정의 Direct 연결만 만들면 전체 사용자에게 제공되는 것이 아닙니다.

첨부 설정의 **Chat Uploads는 Default**를 유지합니다. 첨부 원본 전달 기능은 관리자 Terminal 연결과 저장된 대화에서 사용하세요. 임시 대화·개인 Direct 연결에는 같은 원본 자동 전달이 지원되지 않습니다.

## 5. 실제로 사용해 보기

### 설치 확인

Terminal을 선택한 대화에 다음을 입력합니다.

> Terminal에서 kordoc, python-pptx, Node.js, npm/npx, 한글 글꼴, LibreOffice의 설치 여부와 버전을 확인해줘. 설치하거나 수정하지 말고 없는 항목만 알려줘.

### 가정통신문

학교의 빈 HWPX 양식을 첨부하고:

> 첨부한 학교 양식을 유지해서 현장체험학습 가정통신문을 HWPX로 만들어줘. 필요한 날짜·장소 등 빠진 정보는 먼저 확인해줘. 결과를 검증하고 다운로드 카드로 제공해줘.

### 신구대조표

개정 전·후 규정과 빈 신구대조표 양식을 첨부하고:

> 개정 전과 후를 조항·표 구조 기준으로 비교하고, 첨부한 신구대조표 양식으로 작성해줘. 전후 파일이 불확실하면 먼저 물어봐줘.

### 디자인을 참고한 PPT

> getdesign.md의 Claude 디자인을 실제로 내려받아 참고하고, 인공지능 활용 연수 PPT 5장을 만들어줘. 한글은 설치된 나눔고딕을 사용하고 PPTX 다운로드 카드로 제공해줘. 디자인 다운로드에 실패하면 알려줘.

Getdesign 자료는 필요한 스타일만 내려받습니다. 모든 디자인을 미리 설치할 필요는 없습니다. 디자인 참조를 그대로 웹페이지로 만드는 것이 아니라 색상·글꼴·여백을 슬라이드에 맞게 적용하도록 안내합니다. [Getdesign](https://getdesign.md)

**완료 기준은 다운로드 카드를 눌러 실제 파일을 열어보는 것**입니다. 설치 확인만으로 문서 품질·한글 표시·카드 반환까지 확인되는 것은 아닙니다. PDF 생성·변환의 정확한 출력은 별도 시험이 필요합니다.

## 6. 여러 사람이 사용할 때

관리자가 Terminal 연결과 모델 권한을 부여하면 다른 사용자도 동일한 기본 제작 안내를 사용할 수 있습니다.

- 프로그램과 글꼴: 공통 이미지에 설치
- 학교 양식: 처음에는 각자가 첨부하는 방식이 가장 간단
- 개인 AGENTS.md/스킬: 해당 사용자 파일이며 다른 사용자에게 자동 공유되지 않음
- 사용자 결과: 사용자별 홈에 저장. 원본 양식을 덮어쓰지 않도록 요청

관리자 계정과 일반 사용자 계정에서 각각 파일을 만들어 다운로드를 시험하세요. 실제 두 대화에서 실행 사용자와 홈이 다른지 확인해야 합니다. `docker exec`의 기본 실행 계정만 보고 사용자 분리가 확인됐다고 판단하지 마세요.

학교 양식을 중앙 관리해야 할 때만 아래의 고급 하네스를 검토하면 됩니다.

## 7. 평소 관리할 것과 자주 생기는 문제

| 상황 | 먼저 확인할 것 |
|---|---|
| Terminal 연결 실패 | 컨테이너 실행 여부, URL/포트, Terminal 암호, 사용자 권한 |
| 한글이 □로 보임 | 생성 환경의 글꼴 설치와 생성 코드의 한글 글꼴 지정 |
| 파일은 있지만 카드가 없음 | `display_file` 호출 결과. 생성 성공과 카드 반환은 별도 단계 |
| 첨부 원본을 못 가져옴 | 저장된 대화인지, 관리자 Terminal 연결인지, 첨부 접근 권한 |
| Getdesign 다운로드 실패 | npm/npx 설치, 네트워크, 실제 제공되는 스타일인지 |
| 로고에서 멈춤·500 오류 | OpenWebUI 로그와 Docker 메모리/디스크 사용량. kordoc 원인으로 단정하지 않음 |
| 재생성 후 파일이 안 보임 | 기존 볼륨이 연결됐는지. 새 볼륨에는 이전 파일이 자동 복사되지 않음 |

**백업은 두 종류입니다.** 설치 폴더의 Dockerfile·compose.yaml·.env는 실행 설정이고, Docker 볼륨에는 실제 사용자 파일이 있습니다. 둘 다 보존해야 합니다. `.env` 백업은 비공개로 관리하세요. 재시작은 `docker compose restart`로 할 수 있습니다. 사용자 데이터를 지우는 `docker compose down -v`는 일반 재시작 명령이 아닙니다.

WSL2 메모리 조절이 필요하면 Windows의 `%UserProfile%\.wslconfig`에서 설정합니다. 실제 서버 RAM에 맞춰 Windows가 쓸 여유를 남기세요. `wsl --shutdown`은 모든 WSL 서비스를 중단하므로 작업 중에는 실행하지 않습니다. [Microsoft 설정 안내](https://learn.microsoft.com/en-us/windows/wsl/wsl-config)

## 선택 사항: 학교 공통 지침을 중앙 관리하기

기본 사용에는 필요하지 않습니다. 관리자가 공통 스킬·양식을 버전별로 운영하려는 경우에만 `DOCUMENT_WORKFLOW_MODE=harness`를 사용합니다.

[고급 설치](harness/open-terminal/INSTALL.md) · [기존 지침 이전](harness/open-terminal/MIGRATION.md) · [기능 확장](harness/open-terminal/EXTENDING.md)

이 저장소의 함수는 모델이 도구를 사용하는 방법을 안내하고 연결합니다. 실제 작업은 모델·Terminal·설치된 프로그램이 수행하며, 모든 문서의 결과 품질을 자동 보장하지는 않습니다.

## 한글 내보내기 Action v3.4.0

기존 답변을 HWPX로 저장하는 독립 함수입니다. Open Terminal 연결은 필요하지 않습니다. Open WebUI **0.11.4 이상**을 대상으로 하며 실제 설치 버전은 관리자 화면에서 확인하세요. 구버전이라면 이 파일을 바로 덮어쓰지 마세요.

1. 기존 한글 내보내기 함수와 설정을 먼저 내보내 백업합니다.
2. 위 v3.4.0 JSON을 다운로드해 관리자 **함수(Functions)** 화면에서 가져옵니다. 기존 함수 ID `한글문서_내보내기`를 유지하므로 중복 ID 안내가 나오면 기존 함수 편집 화면에 [Python 원본](functions/한글문서_내보내기.py)을 적용할 수 있습니다.
3. 함수를 활성화하고 대상 모델에서 Action을 사용하도록 설정합니다. 배포 JSON의 활성화·전역 적용 값은 기본적으로 꺼져 있습니다.
4. 한글 본문·표·첨부 이미지가 있는 답변에서 실행해 `.hwpx`를 내려받고 한글에서 열어 확인합니다.

기본 범위는 마지막 AI 답변이며 `export_mode=full_conversation`으로 전달된 대화 범위를 저장합니다. 사용자별 Thinking/표/이미지/범위 설정을 지원합니다. `lxml` 의존성이 필요합니다. 외부 URL 이미지는 다운로드하지 않으며, 내부 파일은 소유권·공유 읽기 권한을 검사합니다. 권한·크기·형식 문제로 제외된 이미지는 경고로 안내합니다.

브라우저 연결이 끊기거나 다운로드 확인이 실패하면 오류를 표시합니다. 서버에 사용자에게 보이지 않는 파일만 저장하고 성공으로 처리하지 않습니다. “다운로드 시작”은 브라우저 실행 응답을 확인했다는 의미이며 OS의 최종 파일 저장까지 보장하지 않습니다. 기본 제한은 본문 100만 자, 이미지당 20MB, 이미지 합계 40MB, 결과 48MB, 브라우저 응답 60초입니다. 서버 WebSocket 제한에 따라 큰 파일은 더 작은 범위로 내보내야 할 수 있습니다.

오프라인 검증 명령: `python3 -m unittest discover -s tests -p test_hwpx_export.py` (lxml, Pydantic 2 필요; 다운로드 JavaScript 검사에는 PATH의 Node 필요). 실제 한컴 한글 페이지 배치는 별도 확인이 필요합니다.

## 엑셀 내보내기 Action v0.4.0

Open WebUI **0.11.4 이상**을 대상으로 합니다. 기존 함수와 설정을 백업한 뒤 [설치용 JSON](function-엑셀로_내보내기-v0.4.0.json)을 관리자 함수 화면에서 가져와 활성화하고 대상 모델에 연결하세요. ID `엑셀로_내보내기`는 유지합니다. 중복 ID가 있으면 기존 함수 편집 화면에 [Python 원본](functions/엑셀로_내보내기.py)을 적용할 수 있습니다. 배포 JSON의 활성화·전역 적용 기본값은 꺼져 있습니다. pandas와 xlsxwriter가 필요하며 Open Terminal은 필요하지 않습니다.

- `EXPORT_SCOPE=last_message`: 클릭한 메시지를 우선합니다. `all_messages`는 요청에 전달된 현재 대화 분기의 모든 표를 처리합니다.
- `NUMBER_MODE=text`(기본): 식별번호의 앞자리 0, 긴 숫자, 날짜 문자열을 텍스트로 보존합니다. Excel 계산용 숫자가 필요하면 `safe_numbers`를 선택하세요. 이 옵션도 선행 0·15자리 초과 숫자·지수 표기·날짜를 자동 변환하지 않습니다. 수식 모양 문자열은 수식으로 실행하지 않습니다.
- `TITLE_SOURCE`: 기존 대화 제목/Markdown 제목/AI 생성 선택을 유지합니다. AI 제목 생성 실패·30초 초과 시 기본 제목으로 진행합니다.
- 기존 `ROW_HEIGHT`/`COLUMN_WIDTH` 서식 설정을 유지합니다. Markdown 강조/코드 표시의 단순 서식 변환도 유지합니다.
- 기본 제한은 입력 200만 자, 10만 셀, 100개 시트, 결과 24MB, 브라우저 응답 60초입니다. 셀 하나가 Excel 제한인 32,767자를 넘으면 오류로 안내합니다.

구분선이 있는 파이프 Markdown 표를 지원합니다. HTML 표·병합 셀·중첩 표는 지원하지 않습니다. 빈 헤더는 ColN으로 채우고 추가 열도 보존합니다. 다운로드 성공 문구는 브라우저의 실행 응답까지 확인한 상태이며 OS의 최종 저장 완료를 보장하지 않습니다. 서버 WebSocket 제한으로 큰 파일이 실패하면 범위를 줄여 다시 실행하세요.

검증: `python3 -m unittest discover -s tests -p test_excel_export.py` (pandas, xlsxwriter, openpyxl, Pydantic 2 필요; JavaScript 검사에는 PATH의 Node 필요). 실제 Excel에서의 표시·인쇄는 별도 확인이 필요합니다.


## 8. 대화 중 이미지 생성·수정

OpenAI Responses **v1.8.3**, Google Gemini **v1.24.1**부터 일반 대화 모델을 선택한 채 이미지 생성·수정을 요청할 수 있습니다. 두 함수의 최신 JSON을 각각 가져오고 활성화하세요. 별도 OpenWebUI 이미지 엔진이나 Terminal 설정은 필요하지 않습니다. GitHub 파일 업데이트가 서버에 설치된 함수를 자동 갱신하지는 않습니다.

| 설정 | OpenAI | Gemini |
|---|---|---|
| 대화형 이미지 도구 | `ENABLE_CONVERSATION_IMAGES=True` (기본) | `ENABLE_CONVERSATION_IMAGES=True` (기본) |
| 실제 이미지 API 모델 | `CONVERSATION_IMAGE_MODEL=gpt-image-2` | `AUTO_IMAGE_MODEL=gemini-3.1-flash-image` |
| 출력 설정 | 기존 `IMAGE_QUALITY`, `IMAGE_SIZE` 및 사용자 밸브 | 기존 `IMAGE_GENERATION_ASPECT_RATIO`, `IMAGE_GENERATION_RESOLUTION` |
| 메시지당 이미지 API 호출 상한 | `CONVERSATION_IMAGE_MAX_CALLS=2` | `CONVERSATION_IMAGE_MAX_CALLS=2` |

같은 공급자의 기존 API 키를 사용합니다. 설정한 이미지 모델의 접근 권한·과금이 필요하며 권한 오류 때 다른 모델로 자동 대체하지 않습니다. OpenAI에서는 함수 호출을 지원하는 대화 모델을 사용하세요. Gemini에서는 기존 UI의 legacy 도구 모드에서도 내부 이미지 도구를 제공합니다.

같은 채팅에서 다음 순서로 확인해 보세요.

1. “학교 축제 포스터를 구상하자. 파란색과 흰색을 쓰고 문구는 ‘함께 만드는 내일’로 해줘.”
2. “그 조건대로 포스터 이미지를 만들어줘.”
3. 이미지를 재첨부하지 않고 “배경만 더 밝게 바꿔줘. 문구와 배치는 유지해줘.”
4. 참고 사진을 첨부하고 “기존 포스터는 유지하고 이 사진의 색감만 적용해줘.”
5. “이번에는 완전히 새로운 숲 풍경 이미지를 만들어줘.”
6. “이미지 생성용 프롬프트만 써줘.” 또는 일반 질문으로 돌아갑니다.

대화 모델이 요청과 앞선 조건을 해석해 `conversation_image`를 호출합니다. 수정 원본과 참고 이미지를 별도로 선택하며, 과거 이미지가 있다고 모든 요청을 수정으로 처리하지 않습니다. OCR·제목 생성 등 백그라운드 작업에는 이 도구를 넣지 않습니다. 중복 실행을 막기 위해 이 경로에서는 OpenWebUI의 `generate_image`/`edit_image`와 OpenAI 내장 `image_generation` 도구를 함께 사용하지 않습니다.

이미지는 사용자 권한으로 OpenWebUI 파일 저장소에 저장하고 답변에 표시합니다. 저장 실패 시 답변의 인라인 이미지로 보존합니다. 다음 요청은 전달된 대화 분기의 이미지와 첨부 파일에서 원본을 찾아 사용하며, 서버 전체의 마지막 이미지를 공유하지 않습니다. 이미지 ID는 서버 파일 또는 이미지 데이터에서 만들어집니다. 메시지 편집·분기로 제외된 이미지, 삭제된 파일, 권한 없는 파일은 수정 원본으로 자동 대체하지 않습니다. 이전 이미지가 현재 대화 문맥에서 빠졌다면 다시 첨부해야 합니다.

이미지 원본은 축소·손실 압축 없이 읽습니다. OpenAI는 기존 편집 API의 PNG 정규화를 거칩니다. 한 번에 수정 원본 1장과 참고 이미지 최대 4장, 입력 이미지당 20 MiB까지 사용합니다. 외부 URL 이미지는 이 새 도구에서 서버가 직접 다운로드하지 않으므로 원본 파일을 첨부해 주세요. 기존 이미지 전용 모델 선택 방식도 유지됩니다.

Gemini는 이미지 도구의 안정적인 실행을 위해 일반 대화도 비스트리밍으로 처리하므로 답변이 완성된 뒤 표시될 수 있습니다. 검색 전용 설정에서는 검색 결과를 얻은 뒤 대화 모델을 한 번 더 호출해 이미지 작업 여부를 판단합니다. 따라서 검색만 하는 요청에서도 추가 텍스트 API 호출이 발생할 수 있습니다. 이미지 API 호출은 Pipe와 Google SDK 모두 자동 재시도를 끄며, 같은 도구 인자의 중복 호출은 요청 안에서 재사용합니다. 실패한 요청의 재시도는 새 사용자 메시지에서 수행하세요.

이미지 수정은 저장한 원본을 이미지 API에 다시 보내는 방식입니다. 공급자의 이미지 전용 대화 세션/생각 서명을 장기간 저장하는 구현은 아닙니다. Gemini의 같은 요청 안에서 일어나는 도구 호출은 SDK가 서명을 전달하고, 검색 후 단계에도 원래 응답의 서명을 보존합니다.

Gemini의 대화형 도구를 끄면 기존 `AUTO_IMAGE_ROUTING` 키워드 경로로 돌아갑니다. 자동 이미지 호출을 모두 끄려면 두 값을 모두 False로 설정하세요. 저장·공유 권한 처리는 [OpenWebUI 0.11.4 파일 API](https://github.com/open-webui/open-webui/blob/v0.11.4/backend/open_webui/routers/files.py)를 기준으로 대조했습니다. Google SDK에 `HttpRetryOptions`가 필요합니다. 현재 검증에 사용한 SDK는 `google-genai 2.25.0`이며, 실제 서버의 SDK 버전과 모델 접근 권한은 설치 후 확인해야 합니다.

검증은 HTTP와 OpenWebUI 저장소 경계를 모의 처리한 오프라인 테스트입니다. 실제 API의 한국어 의도 판단, 이미지 품질·수정 일관성, 비용, 서버 화면에서의 표시까지 검증한 것은 아닙니다.
