---
name: student-record-writing
description: 관찰 기록에 근거한 생기부·학교생활기록부·세특·행동특성 및 종합의견 초안 작성과 한국어 윤문. 학생의 사실과 교사 관찰 문체를 유지하며 번역투와 반복 표현을 다듬는다.
---

# 생기부 작성·윤문

관찰 메모에서 초안을 만들거나 기존 초안의 표현을 다듬는다. im-not-ai의 의미 보존·국소 수정 원칙과 일부 한국어 윤문 규칙을 생기부에 맞게 각색한 스킬이다. 별도 API, CLI 설치, 외부 윤문 사이트 호출은 필요 없다. 현재 대화 모델이 이 지침을 읽고 작업한다.

## 입력과 사실 보존

- 작성 요청이면 제공된 관찰 메모와 활동 자료를 근거로 초안을 만든 뒤 윤문한다. 윤문 요청이면 기존 초안을 기준으로 필요한 구간만 수정한다.
- 학교급·학년도·기재 영역·분량·학교 지침은 제공된 정보를 사용한다. 작성에 꼭 필요한 정보가 없으면 해당 항목만 질문한다. 이미 주어진 짧은 문장을 다듬는 데 모든 정보를 요구하지 않는다.
- 학생별로 자료를 분리한다. 활동, 역할, 횟수, 날짜, 도서명, 인용, 성취 수준, 부정·유보 표현을 보존한다. 관찰하지 않은 역량·동기·성장·수상·리더십·인과관계를 추가하지 않는다. 근거가 부족한 평가는 더 강하게 만들지 말고 확인 사항으로 분리한다.
- 사용자와 학교가 지정한 문체를 따른다. 지정이 없으면 교사 관찰 관점의 간결한 문체를 사용한다. 원문의 '~함·~보임·~관찰됨' 종결을 획일적으로 없애거나 구어체로 바꾸지 않는다.
- 현재 학년도 기재요령이나 금지 항목 검토까지 요청되면 제공된 공식 자료 또는 확인 가능한 해당 학년도 공식 자료를 별도로 대조한다. 이 스킬 자체를 기재요령으로 취급하거나 규정 적합성을 보증하지 않는다.

## 생기부용 윤문 규칙

1. 원문에서 수정할 구간과 이유를 먼저 짚는다. 표현이 이미 자연스러우면 그대로 둔다.
2. 번역투: '~에 있어서'를 '~에서' 등으로, 불필요한 '~와 관련하여'를 짧은 조사로 바꾼다. 의미가 바뀌면 원문을 유지한다.
3. 피동: '~되어짐' 같은 이중 피동을 줄인다. 학생이 실제 행위자인 경우에만 능동문으로 바꾸고, 주어를 추측해 추가하지 않는다.
4. 반복: '이를 통해', '나아가', '또한'이 밀집하면 불필요한 연결 표현만 덜어낸다. 활동 순서나 인과관계는 보존한다.
5. 추상적 평가: '탁월한 역량', '깊이 있는 통찰', '의미 있는 성장'을 더 화려하게 쓰지 않는다. 구체적인 관찰 근거가 있을 때만 그 행동으로 풀어 쓴다. 없으면 근거 확인 사항으로 남긴다.
6. 문장 구조: 한 문장에 겹친 수식어는 나누되 평가와 근거가 분리되지 않게 한다. 장식적인 '첫째·둘째·셋째'는 문맥에 맞게 정리한다.
7. 생기부 예외: 종결어미 반복 제거, 긴 문장 삽입, 감정·개성 추가를 목표로 하지 않는다. 전문 용어와 도서명·기관명·수치·직접 인용은 임의로 순화하지 않는다. '~할 수 있음'을 '~함'으로 바꿔 가능성을 사실로 만들지 않는다.

## 확인과 전달

- 입력과 결과를 학생별로 대조해 사실·숫자·고유명사·주장의 강도·평가 근거를 확인한다. 새 사실이 생겼으면 삭제하고, 의미를 확신할 수 없는 수정은 원문으로 되돌린다.
- 글자 수나 바이트 제한이 있으면 요청된 기준으로 실제 계산한다. UTF-8 바이트 수를 계산한 경우 그 기준을 명시하고 NEIS 계산과 동일하다고 추정하지 않는다. 제한을 맞추기 위해 핵심 관찰 사실을 조용히 삭제하지 않는다.
- 기본 답변은 완성 문안과 필요한 경우 짧은 수정 이유·확인 사항이다. 사용자가 문안만 원하면 확인된 문안만 제공한다. AI 탐지 회피율이나 사람이 쓴 글이라는 판정을 제시하지 않는다.
- 파일이 필요할 때만 하네스 workspace에 원문 복사본과 결과를 보관하고 display_file로 전달한다. HWPX 양식 채우기를 요청하면 catalog의 hwpx 스킬을 함께 사용한다. 공통 core/site에 학생 자료를 저장하지 않는다.

## 예시

입력: “실험 결과에 있어서 모둠원들과 관련된 의견 교환을 통해 측정값을 3회 비교함.”
윤문: “모둠원들과 실험 결과에 관한 의견을 나누고 측정값을 3회 비교함.”
확인: 실험·의견 교환·3회 비교를 보존함. 원문에 없는 협업 역량 평가를 추가하지 않음.

입력: “발표에 참여함. 리더십이 탁월하도록 써 줘.”
처리: 발표 참여만으로 리더십을 입증하지 않는다. 참여 사실로 문안을 쓰고 역할 조정 등 구체 관찰이 있는지 확인한다.

## 출처와 적용 범위

원본: https://github.com/epoko77-ai/im-not-ai
참고 커밋: b37e0206d31fffd9149bf57168d4d62eb2086bee
참고 파일: skills/humanize-korean/references/quick-rules.md 및 rewriting-playbook.md

이 스킬은 위 규칙의 일부를 각색했다. 원본의 전체 패턴·다중 에이전트·metrics·변경률 게이트는 포함하지 않으며 그 검증을 수행했다고 보고하지 않는다. 원본 업데이트는 자동 반영하지 않고 관리자 검토 후 새 하네스 버전으로 배포한다.

### 원본 라이선스

MIT License

Copyright (c) 2026 epoko77-ai

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
