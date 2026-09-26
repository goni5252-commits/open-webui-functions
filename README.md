# Open WebUI Functions — 한글 문서와 PPT 만들기

OpenWebUI 대화에서 **학교 양식으로 HWPX를 작성하고, 디자인을 참고해 PPT를 만들어 내려받는 환경**을 구성합니다.

- OpenWebUI: 대화하는 화면
- OpenAI Responses 함수: 모델과 문서 제작 도구를 연결
- Open Terminal: 실제 파일을 만들고 보관하는 별도 실행 환경

**이미 문서 생성이 되고 있다면 재설치하지 마세요. 아래 [함수 설정](#3-openwebui에-함수-적용하기)과 [사용 예시](#5-실제로-사용해-보기)만 확인하면 됩니다.**

| 다운로드 | 용도 |
|---|---|
| [OpenAI Responses v1.7.9 JSON](function-openai_responses-v1.7.9.json) · [직접 다운로드](https://raw.githubusercontent.com/goni5252-commits/open-webui-functions/main/function-openai_responses-v1.7.9.json) | 이 안내에서 사용하는 함수 |
| [Google Gemini v1.23.6 JSON](function-google_gemini.json) | 별도 Gemini 함수 |
| [Gemini RAG Bypass JSON](function-google_gemini_rag_bypass.json) | 별도 RAG Bypass 함수 |

[변경 내역](CHANGELOG.md) · [OpenAI 함수 Python 원본](functions/openai_responses.py)

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

1. 위의 **OpenAI Responses v1.7.9 JSON**을 저장합니다. GitHub의 Raw/다운로드를 사용하고 웹페이지 HTML을 저장하지 마세요.
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
