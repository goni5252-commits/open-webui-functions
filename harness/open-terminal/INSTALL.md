# Open Terminal 하네스 1.0.0 설치 / Responses 1.7.7 이전

이 패키지는 Open Terminal에 설치합니다. Windows/WSL 또는 OpenWebUI 컨테이너에만 파일을 두면 Terminal 도구에서 읽을 수 없습니다. 함수 JSON과 하네스를 둘 다 적용해야 합니다.

## 1. Windows 서버에 패키지 받기

서버 Windows PowerShell에서 실행합니다. 같은 버전이 이미 설치된 경우 기존 폴더를 덮어쓰지 말고 먼저 내용을 확인하세요.

```powershell
$harnessInstall = 'C:\OpenWebUI\harness\v1.0.0'
New-Item -ItemType Directory -Path $harnessInstall -Force | Out-Null
Invoke-WebRequest 'https://raw.githubusercontent.com/goni5252-commits/open-webui-functions/main/harness/open-terminal-harness-v1.0.0.zip' -OutFile "$harnessInstall\package.zip"
Invoke-WebRequest 'https://raw.githubusercontent.com/goni5252-commits/open-webui-functions/main/harness/open-terminal-harness-v1.0.0.zip.sha256' -OutFile "$harnessInstall\package.zip.sha256"
$expectedHash = ((Get-Content "$harnessInstall\package.zip.sha256") -split '\s+')[0]
if ((Get-FileHash "$harnessInstall\package.zip" -Algorithm SHA256).Hash -ne $expectedHash) { throw '하네스 SHA-256 불일치' }
Expand-Archive -LiteralPath "$harnessInstall\package.zip" -DestinationPath $harnessInstall
```

## 2. 기존 Open Terminal에 읽기 전용 마운트 추가

기존 Compose의 **Open Terminal 서비스** 아래 `volumes`에 항목 하나를 추가합니다. 기존 이미지, 환경 변수, 사용자 데이터 볼륨, 포트, 네트워크는 보존합니다. 아래 `open-terminal`은 예시 서비스 이름입니다.

```yaml
services:
  open-terminal:
    volumes:
      # 기존 volumes 항목도 여기에 유지
      - type: bind
        source: C:/OpenWebUI/harness/v1.0.0/openwebui-harness
        target: /opt/openwebui-harness
        read_only: true
```

Windows PowerShell에서 Docker Desktop Compose를 실행할 때의 source 예시입니다. WSL 쉘에서 Compose를 실행한다면 같은 호스트 폴더의 source를 `/mnt/c/OpenWebUI/harness/v1.0.0/openwebui-harness`로 사용합니다.

Compose 파일이 있는 폴더에서:

```text
docker compose config --quiet
docker compose up -d --no-deps open-terminal
```

Terminal 컨테이너가 재생성되므로 진행 중인 Terminal 작업을 먼저 마칩니다. `down -v`는 사용하지 않습니다. Docker run으로 운영한다면 기존 실행 옵션과 영구 볼륨을 유지하여 동일한 읽기 전용 bind mount를 추가해야 합니다. 실행 설정을 모르는 상태에서 기존 컨테이너를 삭제하지 마세요.

컨테이너 이름을 실제 이름으로 바꿔 확인합니다:

```text
docker exec open-terminal cat /opt/openwebui-harness/INDEX.md
docker exec open-terminal python3 /opt/openwebui-harness/scripts/doctor.py
```

이 경로는 공통 읽기 전용 자산입니다. 다중 사용자 Terminal에서도 각 사용자는 결과를 자신의 작업 폴더에 저장합니다. 하네스는 사용자 격리 기능 자체를 추가하지 않습니다.

## 3. 필요한 패키지 확인

doctor 결과에서 Python의 `python_pptx=true`, `npx` 경로, 한글 글꼴을 확인하세요. 기본 빌더에는 python-pptx가 필요하고 getdesign 다운로드에는 Node/npm/npx가 필요합니다. 렌더링 검수에는 LibreOffice와 이미지 도구가 추가로 필요합니다.

이미 설치돼 있으면 추가 설치하지 않습니다. 누락된 패키지는 사용 중인 이미지에 맞춰 Dockerfile에 반영하세요. Debian/Ubuntu 기반이며 기존 이미지의 실행 사용자가 `user`인 경우 예시는 다음과 같습니다(다른 이미지에서는 사용자/패키지 관리자를 맞춰야 합니다).

```dockerfile
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
USER root
RUN python3 -m pip install --no-cache-dir python-pptx==1.0.2
RUN apt-get update && apt-get install -y --no-install-recommends fontconfig fonts-noto-cjk fonts-nanum && rm -rf /var/lib/apt/lists/*
USER user
```

위 예시는 Node/npm을 설치하지 않습니다. 기존 이미지의 doctor에서 npx가 없다면 Node가 포함된 기존 기본 이미지 또는 조직의 Node 설치 방식을 사용하세요. 패키지 자동 설치를 제작 지침에 넣지 않았습니다.

## 4. 함수 업데이트

`function-openai_responses-v1.7.7.json`을 OpenWebUI 함수에 가져옵니다. 기존 Valve/API 설정을 확인하고 다음을 설정합니다.

- `ENABLE_PRESENTATION_DESIGN=True`: 하네스 연결 활성화. 이전 설정 호환을 위해 이름 유지.
- `TERMINAL_HARNESS_ROOT=/opt/openwebui-harness`
- `COMPACT_STATUS_UPDATES=True`: 짧은 진행 표시. False이면 상세 도구 상태를 표시하되 created/in_progress 중복은 제거됩니다.

Open Terminal 연결을 선택하고 새 요청으로 시험합니다. 기존 대화에 이미 저장된 중복 상태는 지우지 않습니다. 별도 PPT 스킬이 강제 템플릿을 지정한다면 그 설정도 사용자의 디자인 요청과 충돌하지 않도록 조정하세요.

> getdesign.md의 Claude 스타일로 인공지능 활용 연수 PPT 5장을 만들어줘. 먼저 설치된 Terminal 하네스를 읽고, 편집 가능한 PPTX를 파일 카드로 반환해줘.

성공 기준: get_terminal_harness → INDEX/관련 SKILL 읽기 → DESIGN.md 다운로드/읽기 → 테마·슬라이드 생성 → 검증 → display_file 카드 → 실제 다운로드. get_terminal_harness의 location_only는 설치 확인 성공을 의미하지 않습니다.

## 업데이트 / 되돌리기

새 하네스 버전은 별도 버전 폴더에 풀고 bind source를 변경합니다. 이전 폴더는 보존합니다. 1.7.6으로 되돌리려면 이전 JSON을 다시 가져옵니다. 하네스 볼륨은 남겨도 되며 사용자 작업 파일에는 영향을 주지 않습니다.

원본: https://github.com/goni5252-commits/open-webui-functions/tree/main/harness/open-terminal
getdesign 공식 CLI 예시: https://getdesign.md/vercel/design-md
