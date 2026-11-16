# 가독성 수정 · 2026-10-14

- 9–12px에 집중된 기존 UI 글자 크기를 올림: 주요 본문·버튼 14–16px, 제품명·접점 제목 15–20px, 주소 등 보조 정보 12–13px.
- 네이비 본문과 짙은 회색 설명의 공통 대비 기준 적용. 기존 important 규칙으로 옅게 남던 채널 할당·수신 설명 수정.
- 전체 시스템의 채널·포트 카드, IO-Link 제품 화면, 모니터링, 출력, 구성·점검, 별도 설정 표·대화상자에 적용.
- 제품명, 측정값, ON/OFF를 강조하고 메타데이터는 크기·간격으로 구분. 모바일 접점은 2열로 배치하여 큰 글씨 유지.
- 설정 표의 행 간격과 조회 버튼 크기 확대. 범위·선택지, 읽기 전 잠금 및 적용 절차 유지.

검증: check_iodd_system, check_iodd_product_experience, check_iodd_remote_experience, check_iodd_user_settings, check_iodd_workspace_acceptance 통과. 설정 페이지 1500px/390px 가로 넘침 없음. 실제 장비 요청·출력 쓰기는 하지 않았으며 모든 장비 테스트는 모의 응답.

화면 확인: system-map.png, theme-settings.png, remote-digital-experience-mock.png, remote-analog-experience-mock.png.
