# 저장소 관리 및 게시 절차

- 작업 시작 시 `git status`로 사용자 변경을 확인한다. main이 깨끗하면 `git pull --ff-only origin main`으로 동기화한다.
- 함수 원본은 `functions/<함수 ID>.py`, 배포 파일은 `function-<함수 ID>.json` 하나씩 유지한다. 버전별 JSON과 누적 CHANGELOG는 만들지 않는다. 이전 버전은 Git 기록으로 관리한다.
- 실행 코드 변경은 헤더 version을 올린다. 설명·주석만 정리할 때는 실행 AST가 같음을 검증하고 버전을 유지할 수 있다. 작성자·라이선스·의존성 정보를 보존한다.
- 수정 후 `python3 scripts/build_exports.py <함수 ID>`를 실행한다. README에는 최신 기능·버전·필수 설정만 간단히 유지한다. 코드 헤더에 누적 변경 내역을 넣지 않는다.
- 관련 동작 테스트, `python3 scripts/build_exports.py --check`, `python3 scripts/build_harness.py --check`, `git diff --check`를 수행한다. 실제 API/서버 미검증 사항은 정확히 알린다.
- diff와 삭제 목록을 확인하고 필요한 경로만 지정해 `bash scripts/publish.sh "구체적인 커밋 메시지" <파일 경로...>`로 게시한다. 추적된 삭제 파일도 명시한다. 사용자 요청이 초안/로컬 작업이면 게시하지 않는다.
- 게시 후 `git ls-remote origin refs/heads/main`과 로컬 HEAD가 같은지 확인한다. force push/과거 Git 기록 재작성은 하지 않는다.
- publish.sh는 main 전용이다. 작업 브랜치에서는 PR 절차를 따른다. 인증·네트워크 실패를 성공으로 보고하지 않으며 토큰을 채팅으로 요청하지 않는다.
- GitHub 업로드는 OpenWebUI 서버 설치를 포함하지 않는다.
