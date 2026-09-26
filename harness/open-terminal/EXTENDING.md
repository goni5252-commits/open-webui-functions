# 기능 확장 규약

## 세 계층

| 계층 | 기본 경로 | 관리/사용 |
|---|---|---|
| core | /opt/openwebui-harness | 공개 공통 패키지. 운영 중 읽기 전용 |
| site | /opt/openwebui-site | 학교 내부 지침/스킬/양식. 공개 저장소에 업로드하지 않음. 읽기 전용 |
| workspace | 현재 OS 계정 홈/.openwebui-workspaces/task-* | 사용자 실행 계정이 작업별로 생성. 입력 복사본·중간 파일·결과 |

AGENTS.md는 공통 실행 규칙, catalog.json은 기능 요약/경로, SKILL.md는 기능별 절차입니다.
원본 스킬 내 scripts/references/assets는 해당 스킬 폴더에 함께 보관합니다.
site의 AGENTS.md는 학교 공통 보완 규칙이며 개인 홈의 AGENTS.md를 자동 취합하지 않습니다.

## 새 기능 등록 (관리자 작업)

1. site/skills/<고유-id>/SKILL.md를 작성합니다. name/description YAML 헤더와 실제 작업 절차를 포함합니다.
2. catalog.json의 skills 배열에 추가합니다:

```json
{"id":"attendance-report","description":"출결 데이터를 학교 보고 양식으로 작성","entrypoint":"skills/attendance-report/SKILL.md","enabled":true}
```

3. 같은 core id의 기존 개인 스킬을 이전할 때만 `"override":true`를 명시합니다. 예: `family-letter-generator`. 명시하지 않은 중복은 오류입니다.
4. 기능 비활성화는 `{"id":"family-letter-generator","enabled":false,"override":true}`처럼 등록합니다. needs는 관련 스킬 안내이며 자동 실행/자동 로딩이 아닙니다.
5. 양식은 templates 배열에 등록합니다:

```json
{"id":"family-letter","path":"templates/family_letter_template.hwpx"}
```

6. 실제 Terminal에서 `python3 /opt/openwebui-harness/scripts/harness.py validate --site-root /opt/openwebui-site`를 실행하고 일반 사용자 계정으로 새 작업을 시험합니다.

경로는 해당 catalog가 있는 root 기준 상대 경로이며 외부 경로·외부로 향하는 심볼릭 링크는 허용하지 않습니다. 공통 템플릿 파일이 없으면 검증이 실패합니다. 새 기능을 위한 별도 API 키/패키지/권한은 관리자가 준비해야 하며 catalog 등록이 권한을 부여하지 않습니다.

다른 모델/함수에도 사용하려면 해당 모델의 관리 지침에서 같은 core/AGENTS.md와 catalog 명령을 읽도록 연결해야 합니다. 이번 자동 연결은 OpenAI Responses 함수에 적용됩니다.
