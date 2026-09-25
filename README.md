# Open WebUI Functions

Open WebUI에서 사용할 수 있는 함수를 공유합니다.

| 함수 | 편집 원본 | 배포 파일 |
| --- | --- | --- |
| OpenAI Responses | [Python](functions/openai_responses.py) | [v1.7.4 JSON](function-openai_responses-v1.7.4.json) |
| Google Gemini | [Python](functions/google_gemini.py) | [JSON](function-google_gemini.json) |
| Gemini RAG Bypass | [Python](functions/google_gemini_rag_bypass.py) | [JSON](function-google_gemini_rag_bypass.json) |

**[업데이트 내역 보기](CHANGELOG.md)** · [커밋 기록](https://github.com/goni5252-commits/open-webui-functions/commits/main/)

[최신 Responses JSON](function-openai_responses.json)도 v1.7.4입니다. OpenWebUI에서 JSON 파일을 가져오거나 Python 원본으로 기존 함수 코드를 교체할 수 있습니다. [이전 v1.6.8](function-openai_responses-v1.6.8.json)은 보관합니다.

오프라인 회귀 테스트는 Python 3.11 이상과 Pydantic 2에서 `python3 -m unittest discover -s tests -v`로 실행합니다. OpenWebUI와 HTTP 호출은 모의 객체로 대체합니다.

## Codex에서 수정하고 공유하기

이 저장소를 Codex 프로젝트로 열고 함수를 수정해 달라고 요청하세요. `AGENTS.md`에 작업 완료 시 Python 원본 수정, JSON 생성, 관련 테스트, 변경 내역 작성, GitHub push를 수행하는 절차가 있습니다. 이는 Codex의 작업 절차이며 파일 저장을 감시하는 백그라운드 서비스는 아닙니다. Git 인증과 네트워크 권한이 필요하며, 업로드 실패 시 Codex가 미완료 상태를 보고합니다.

수동으로 같은 절차를 실행하려면 Python 3.9 이상과 Git을 사용합니다. 함수 원본의 version을 올리고 수정한 후:

```sh
python3 scripts/build_exports.py openai_responses
python3 scripts/build_exports.py --check
# 관련 동작 테스트 실행 후 CHANGELOG.md에 변경점과 검증 결과 기록
bash scripts/publish.sh "fix: 변경 사항 설명" functions/openai_responses.py function-openai_responses.json function-openai_responses-v새버전.json CHANGELOG.md
```

생성기는 기존 JSON의 배포 형식을 유지하며 사용자 ID를 새 배포 파일에서 제외합니다. 기존 버전별 파일의 내용을 변경하려 하면 중단합니다. 다른 함수는 `google_gemini`, `google_gemini_rag_bypass`를 지정하세요.

게시 스크립트는 main에서 지정된 파일만 커밋하며, 원격 변경이 있으면 중단합니다. push 실패 시 로컬 커밋은 남으므로 원인 해결 후 `git push origin main`으로 다시 전송합니다. 변경 내역은 CHANGELOG와 커밋 기록에서 확인합니다. GitHub Releases 생성 및 OpenWebUI 서버 자동 설치는 포함하지 않습니다.
