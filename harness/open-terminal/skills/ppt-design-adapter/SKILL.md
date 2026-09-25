---
name: ppt-design-adapter
description: 디자인 Markdown의 시각 규칙을 PPT용 테마 JSON과 슬라이드 레이아웃 선택으로 변환합니다.
---
# PPT용 디자인 변환

읽은 참조를 근거로 `ppt-theme.json`을 작성합니다. `<root>/examples/theme.json`은 스키마 예시이며 특정 브랜드 분석이 아닙니다.

- canvas/surface/ink/primary → colors.background/surface/text/accent. 값은 # 없는 6자리 RGB.
- display/body → fonts.title/body. 한글에는 doctor가 확인한 실제 한글 지원 글꼴을 사용합니다. 없는 브랜드 글꼴을 대체한 이유를 source.adaptations에 기록합니다.
- 웹 px 크기는 그대로 복사하지 않고 font_sizes_pt.title/body로 재설정합니다.
- spacing → margins_inches. 기본 16:9, 사용자 지정 크기 우선. 웹의 navigation/hover/motion/breakpoint는 제외합니다.
- 카드 → card_style.rounded, 이미지 분위기는 image_style 및 제작 코드에 반영합니다. 기본 빌더는 이미지 자동 수집/배치를 지원하지 않습니다.
- source에 URL/slug 또는 첨부 경로, adapter_defaults에 원문에 없어서 보완한 값을 기록합니다. source의 사실과 보완값을 구분합니다.

대조가 약한 원문 색 조합은 가독성을 위해 수정하고 이를 기록합니다. DESIGN.md를 기계적으로 완전 파싱하는 스크립트는 없으며, 모델이 의미를 해석하고 공통 빌더가 타입/범위를 확인합니다.
