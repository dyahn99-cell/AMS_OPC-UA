"""Resolve an explicit saved topology to read-only BMTAC process input addresses."""
import time


def resolve(config, topology):
    gateway = topology.gateway(config['base'])
    if gateway.diagnostics not in ('none', 'advanced') or gateway.max_slots != 15:
        raise ValueError('현재 읽기 연결은 15채널 None/Advanced 진단 배치만 검증되었습니다')
    slot = next((s for s in topology.slots if s.gateway_id == config['base'] and s.channel == config['channel']), None)
    if slot is None or not slot.enabled or slot.kind != 'remote_io' or slot.metadata.get('part_no') != config['model']:
        raise ValueError('운영 토폴로지의 채널에 동일한 EXW1-RL 모델을 명시해야 합니다')
    mapping = slot.metadata.get('iolink_input_mapping', {})
    if not isinstance(mapping, dict) or mapping.get('confirmed') is not True or mapping.get('wordByteOrder') not in ('high-low', 'low-high'):
        raise ValueError('베이스 ByteSwap을 포함한 입력 바이트 순서 확인이 필요합니다')
    if slot.input_bytes != config['input'] or slot.output_bytes != config['output']:
        raise ValueError('운영 채널과 마스터 계획의 입출력 할당이 다릅니다')
    if config['input'] % 2:
        raise ValueError('현재 운영 토폴로지는 짝수 바이트 할당만 지원합니다')
    count = config['input'] // 2
    if not 2048 <= slot.input_start or slot.input_start + count > 2768 or not 1 <= count <= 125:
        raise ValueError('BMTAC 입력 영역 범위 오류')
    return {'confirmed': True, 'base': config['base'], 'channel': config['channel'],
            'functionCode': 3, 'address': slot.input_start, 'count': count,
            'wordByteOrder': mapping['wordByteOrder'], 'byteOffset': 0}


def read(config, topology, read_words):
    mapping = resolve(config, topology)
    words = read_words(mapping['address'], mapping['count'])
    if not isinstance(words, list) or len(words) != mapping['count'] or any(type(w) is not int or not 0 <= w <= 65535 for w in words):
        raise ValueError('잘못된 레지스터 응답')
    return {'mapping': mapping, 'response': {**mapping, 'connected': True,
            'timestamp': int(time.time() * 1000), 'words': words}}
