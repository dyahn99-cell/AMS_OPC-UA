# 차콜 운영 테마 · 2026-10-14

전체 시스템, 채널·포트, 모니터링, 디지털·아날로그 리모트, 출력, 구성·점검, 별도 설정 표와 대화상자를 동일한 어두운 테마로 변경했다.

- 배경 #13171c, 패널 #1c2128, 본문 #f0f3f7, 보조 정보 #b5c0cc.
- SMC 블루는 주요 조작과 선택 강조에 사용한다. 수신·ON은 녹색, 경고는 황색, 오류는 적색, 시험 프리뷰는 회색으로 구분한다.
- 전체 시스템 요약 숫자는 배경 카드와 테두리를 줄여 정보 중심으로 표시한다.
- 주요 측정값은 밝게 강조하고 대표 지표 패널과 보조 정보의 명도를 구분한다.
- CAD 제품 선화는 흰색 표시 영역을 유지한다. 설명·회전 옵션·버튼은 어두운 테마로 통일한다.
- 조회 전 미확인, 채널별 할당과 설정 분리, 출력 조회·허용·적용 및 재조회 절차 유지.

검증: check_iodd_system, check_iodd_product_experience, check_iodd_workspace_acceptance, check_iodd_remote_experience, check_iodd_user_settings 통과. 설정 페이지 데스크톱/모바일 가로 넘침 없음. 상태별 색상 차이, 실제 값 표시, 포트별 설정 분리 및 모의 일괄 적용 검증. 장비 요청은 모의 응답을 사용했으며 실제 하드웨어 출력 쓰기는 하지 않았다.

미리보기: system-map.png, product-experience-channel-2026-10-14.png, theme-monitor.png, theme-settings.png.
