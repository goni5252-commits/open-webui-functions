# 기존 개인 kordoc 지침을 공유 구조로 이전

확인된 기존 구조:
- /home/u52a58cd5/AGENTS.md
- /home/u52a58cd5/.agents/skills/regulation-comparison-generator/SKILL.md
- /home/u52a58cd5/.agents/skills/family-letter-generator/SKILL.md
- /home/templates/regulation_comparison_template.hwpx
- /home/templates/family_letter_template.hwpx

현재 배포의 같은 이름 core 스킬은 새 기본 지침입니다. 위 파일의 실제 내용을 읽어 복제한 것이 아닙니다. 기존 규칙을 그대로 쓰려면 아래 이전을 수행해야 합니다. 원본은 삭제/수정하지 않습니다.

## 관리자 개인 검토 폴더로 복사

서버 PowerShell에서 실제 컨테이너 이름으로 실행합니다. 다른 사용자에게 아직 공개하지 않는 폴더를 사용합니다.

```powershell
$legacyReview = 'C:\OpenWebUI\migration-review'
New-Item -ItemType Directory -Path $legacyReview -Force | Out-Null
docker cp open-terminal:/home/u52a58cd5/AGENTS.md "$legacyReview\AGENTS.md"
docker cp open-terminal:/home/u52a58cd5/.agents/skills/regulation-comparison-generator "$legacyReview\regulation-comparison-generator"
docker cp open-terminal:/home/u52a58cd5/.agents/skills/family-letter-generator "$legacyReview\family-letter-generator"
docker cp open-terminal:/home/templates/regulation_comparison_template.hwpx "$legacyReview\regulation_comparison_template.hwpx"
docker cp open-terminal:/home/templates/family_letter_template.hwpx "$legacyReview\family_letter_template.hwpx"
```

존재하지 않는 파일은 중단하고 실제 경로를 확인합니다. 학교 스킬이 다른 scripts/references/assets를 참조하면 그것도 관리자 검토 후 옮깁니다.

## 검토 후 site에 활성화

- 개인 이름·개인 경로·인증 정보·개인 작업 기록은 공통 지침에 포함하지 않습니다.
- 기존 AGENTS.md 전체를 덮어쓰지 말고 학교에 필요한 공통 규칙을 site/AGENTS.md에 병합합니다.
- 검토한 두 스킬 폴더를 site/skills/ 아래 복사합니다. 개인 홈 경로는 현재 계정 작업 폴더와 catalog가 반환하는 양식 경로로 바꿉니다.
- 검토한 빈 학교 양식을 site/templates/ 아래 복사합니다. 작성된 학생 개인정보가 들어간 문서는 공통 템플릿으로 배포하지 않습니다.
- site/catalog.json에 다음처럼 명시적으로 등록합니다:

```json
{
  "schema_version":1,
  "version":"school-1",
  "skills":[
    {"id":"regulation-comparison-generator","description":"학교 기존 규정 신구대조표 지침","entrypoint":"skills/regulation-comparison-generator/SKILL.md","enabled":true,"override":true},
    {"id":"family-letter-generator","description":"학교 기존 가정통신문 지침","entrypoint":"skills/family-letter-generator/SKILL.md","enabled":true,"override":true}
  ],
  "templates":[
    {"id":"regulation-comparison","path":"templates/regulation_comparison_template.hwpx"},
    {"id":"family-letter","path":"templates/family_letter_template.hwpx"}
  ]
}
```

빈 site 스캐폴드에는 양식이 포함돼 있지 않습니다. 실제 파일을 옮긴 후 위 등록을 적용합니다. core의 PPT 스킬들은 별도 복사 없이 계속 함께 발견됩니다.

검증 명령을 통과한 뒤 관리자와 일반 사용자 각각 새 대화에서 목록과 실제 가정통신문/신구대조표 결과를 확인합니다. 기존 개인 스킬과 개인 작업 폴더는 보존합니다. 문제가 있으면 site override를 비활성화하거나 이전 site 백업으로 복원합니다.
