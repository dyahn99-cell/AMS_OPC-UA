# EXW1-BMTAC → IO-Link 입력 1회 읽기

코드 연결: 서버 장비 트리에서 저장 마스터 선택 → 입력 1회 읽기 →
인증된 POST /api/device-workspace/read → 저장 버전 확인 → 운영 토폴로지 대조 →
기존 endpoint lock/설정 세대 고정 → ModbusClient.read_holding_registers →
응답 바이트 변환/PD 해석 → 읽기 전용 포트 위젯.

출력 및 비주기 명령 영역은 요청하지 않는다. 반복 폴링과 연결 시 자동 읽기도 없다.
시작 주소를 브라우저에서 지정하지 않고 운영 토폴로지의 input_start를 사용한다.
SMC OM_EXW1-BMTAC_DOC1145638EN.pdf 24,37,41–42쪽을 확인했다.
입력 Holding Register 영역은 2048–2767이며 앞 채널과 진단 영역의 할당을 포함한다.
현재 경로는 max_slots=15, diagnostics=none/advanced 및 짝수 바이트 할당만 지원한다.
그 밖의 배치를 추정해서 읽지 않는다.

## 운영 설정 대조 조건

config.json의 명시적 modbus_gateways 안에 실제 베이스와 채널을 등록해야 한다.
해당 슬롯은 kind=remote_io, enabled=true이며 metadata.part_no가 계획의
EXW1-RLAPA8C 또는 EXW1-RLBPA7C와 일치해야 한다. 입출력 길이도 같아야 한다.
metadata.iolink_input_mapping에는 confirmed=true와 wordByteOrder를 명시한다.
wordByteOrder는 베이스 ByteSwap까지 확인한 high-low 또는 low-high로 지정한다.
이 확인값의 기본값은 없다. 토폴로지나 장비 설정을 자동 변경하지 않는다.

서버는 저장 구성의 revision/id만 받아 대상을 찾는다. 요청 본문의 임의 IP/주소를 사용하지 않는다.
설정 변경과의 경합은 기존 admission/endpoint lock으로 보호하고, 읽기 중 워크스페이스
저장 버전이 바뀌면 결과를 폐기한다. 실패 시 이전 표시를 비우며 성공으로 대체하지 않는다.

## 검증과 현재 상태

순수 저장소/주소 연결 테스트 10개 통과, 모의 ASGI API의 인증/버전/id 거부 및
1회 읽기 callback 횟수 검사 통과. PD/레지스터/전체 위젯 검사 통과.
실제 네트워크 대신 모의 reader를 사용했다. 운영 앱 전체 회귀/브라우저 육안 검증은 미완료다.
현재 작업 폴더에는 config.json과 저장된 device_workspace.sqlite3가 없으며
실물 대상 IP/채널도 확인되지 않아 실제 접속/서버 재시작은 수행하지 않았다.
사용자에게 실제 베이스 IP와 IO-Link 마스터 채널을 요청한 상태다.
