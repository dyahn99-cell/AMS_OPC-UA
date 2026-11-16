# SMC 전체 제품 검토 현황

범위: 제공된 ZIP 전체. 모든 패키지의 대시보드 관련 매뉴얼을 검토했습니다. 각 비주기 항목의 조건·쓰기 동작까지 전부 구현/검증했다는 의미는 아닙니다.
부분 확인을 전체 확인으로 확대하지 않습니다. 미확인 변환은 raw로 유지합니다.

- products: 215
- definitions: 239
- packages: 41
- fields: 11217
- definitions_with_pd_out: 42
- definitions_with_conditional_pd: 61
- definitions_with_compound_fields: 206
- definitions_with_unresolved_standard_refs: 239
- definitions_with_some_manual_conversion_evidence: 129
- fully_manual_reviewed_definitions: 0
- definitions_with_family_manual_review: 239

## 검토 기준

각 정의마다 모델/Device ID/버전, PD 길이·비트·부호·조건, 단위/배율/특수값, 비주기 Index/Subindex·접근권한·명령, 진단과 공용 위젯 연결을 공식 매뉴얼과 대조해야 합니다.
값을 읽지 못하는 초기 설정에서는 제품과 IODD 버전을 수동 선택합니다. 기본값은 실제 장비 설정이나 측정값으로 취급하지 않습니다.

## 모든 제품 및 버전

| 제품 | 식별 키 | 버전 | 패키지 | PD IN/OUT 항목 | 비주기 항목 | 조건부 레이아웃 | 복합 항목 | 변환 근거 항목 | 매뉴얼 전체 검토 |
|---|---|---|---|---:|---:|---:|---:|---:|---|
| D-MH2C | iolink:131:675 | V1.0 | current/IODD for D-MH2.zip | 10/0 | 11 | 0 | 3 | 0 | 미완료 |
| D-MH2D | iolink:131:676 | V1.0 | current/IODD for D-MH2.zip | 10/0 | 12 | 0 | 4 | 0 | 미완료 |
| PF2M701x-xx-L2x-xxx | iolink:131:366 | V1.00 | current/PF2M_IO-Link_IODD.zip | 6/0 | 33 | 0 | 10 | 1 | 미완료 |
| PF2M701x-xx-L2x-xxx-X731 | iolink:131:414 | V1.00 | current/PF2M_X731_IODD.zip | 6/0 | 33 | 0 | 10 | 0 | 미완료 |
| PF2M701x-xx-L3x-xxx | iolink:131:367 | V1.00 | current/PF2M_IO-Link_IODD.zip | 6/0 | 34 | 0 | 11 | 1 | 미완료 |
| PF2M701x-xx-L3x-xxx-X731 | iolink:131:415 | V1.00 | current/PF2M_X731_IODD.zip | 6/0 | 33 | 0 | 11 | 0 | 미완료 |
| PF2M701x-xx-L4x-xxx | iolink:131:368 | V1.00 | current/PF2M_IO-Link_IODD.zip | 6/0 | 33 | 0 | 11 | 1 | 미완료 |
| PF2M701x-xx-L4x-xxx-X731 | iolink:131:512 | V1.00 | current/PF2M_X731_IODD.zip | 6/0 | 32 | 0 | 11 | 0 | 미완료 |
| PF2M701x-xx-Lx-xxx | iolink:131:365 | V1.00 | current/PF2M_IO-Link_IODD.zip | 6/0 | 31 | 0 | 10 | 1 | 미완료 |
| PF2M701x-xx-Lx-xxx-X731 | iolink:131:413 | V1.00 | current/PF2M_X731_IODD.zip | 6/0 | 31 | 0 | 10 | 0 | 미완료 |
| PF2M702x-xx-L2x-xxx | iolink:131:370 | V1.00 | current/PF2M_IO-Link_IODD.zip | 6/0 | 32 | 0 | 10 | 1 | 미완료 |
| PF2M702x-xx-L2x-xxx-X731 | iolink:131:514 | V1.00 | current/PF2M_X731_IODD.zip | 6/0 | 32 | 0 | 10 | 0 | 미완료 |
| PF2M702x-xx-L3x-xxx | iolink:131:371 | V1.00 | current/PF2M_IO-Link_IODD.zip | 6/0 | 33 | 0 | 11 | 1 | 미완료 |
| PF2M702x-xx-L3x-xxx-X731 | iolink:131:515 | V1.00 | current/PF2M_X731_IODD.zip | 6/0 | 32 | 0 | 11 | 0 | 미완료 |
| PF2M702x-xx-L4x-xxx | iolink:131:372 | V1.00 | current/PF2M_IO-Link_IODD.zip | 6/0 | 32 | 0 | 11 | 1 | 미완료 |
| PF2M702x-xx-L4x-xxx-X731 | iolink:131:516 | V1.00 | current/PF2M_X731_IODD.zip | 6/0 | 31 | 0 | 11 | 0 | 미완료 |
| PF2M702x-xx-Lx-xxx | iolink:131:369 | V1.00 | current/PF2M_IO-Link_IODD.zip | 6/0 | 30 | 0 | 10 | 1 | 미완료 |
| PF2M702x-xx-Lx-xxx-X731 | iolink:131:513 | V1.00 | current/PF2M_X731_IODD.zip | 6/0 | 30 | 0 | 10 | 0 | 미완료 |
| PF2M705x-xx-L2x-xxx | iolink:131:374 | V1.00 | current/PF2M_IO-Link_IODD.zip | 6/0 | 32 | 0 | 10 | 1 | 미완료 |
| PF2M705x-xx-L2x-xxx-X731 | iolink:131:518 | V1.00 | current/PF2M_X731_IODD.zip | 6/0 | 32 | 0 | 10 | 0 | 미완료 |
| PF2M705x-xx-L3x-xxx | iolink:131:375 | V1.00 | current/PF2M_IO-Link_IODD.zip | 6/0 | 33 | 0 | 11 | 1 | 미완료 |
| PF2M705x-xx-L3x-xxx-X731 | iolink:131:519 | V1.00 | current/PF2M_X731_IODD.zip | 6/0 | 32 | 0 | 11 | 0 | 미완료 |
| PF2M705x-xx-L4x-xxx | iolink:131:376 | V1.00 | current/PF2M_IO-Link_IODD.zip | 6/0 | 32 | 0 | 11 | 1 | 미완료 |
| PF2M705x-xx-L4x-xxx-X731 | iolink:131:520 | V1.00 | current/PF2M_X731_IODD.zip | 6/0 | 31 | 0 | 11 | 0 | 미완료 |
| PF2M705x-xx-Lx-xxx | iolink:131:373 | V1.00 | current/PF2M_IO-Link_IODD.zip | 6/0 | 30 | 0 | 10 | 1 | 미완료 |
| PF2M705x-xx-Lx-xxx-X731 | iolink:131:517 | V1.00 | current/PF2M_X731_IODD.zip | 6/0 | 30 | 0 | 10 | 0 | 미완료 |
| PF2M710x-xx-L2x-xxx | iolink:131:378 | V1.00 | current/PF2M_IO-Link_IODD.zip | 6/0 | 33 | 0 | 10 | 1 | 미완료 |
| PF2M710x-xx-L2x-xxx-X731 | iolink:131:522 | V1.00 | current/PF2M_X731_IODD.zip | 6/0 | 33 | 0 | 10 | 0 | 미완료 |
| PF2M710x-xx-L3x-xxx | iolink:131:379 | V1.00 | current/PF2M_IO-Link_IODD.zip | 6/0 | 34 | 0 | 11 | 1 | 미완료 |
| PF2M710x-xx-L3x-xxx-X731 | iolink:131:523 | V1.00 | current/PF2M_X731_IODD.zip | 6/0 | 33 | 0 | 11 | 0 | 미완료 |
| PF2M710x-xx-L4x-xxx | iolink:131:380 | V1.00 | current/PF2M_IO-Link_IODD.zip | 6/0 | 33 | 0 | 11 | 1 | 미완료 |
| PF2M710x-xx-L4x-xxx-X731 | iolink:131:524 | V1.00 | current/PF2M_X731_IODD.zip | 6/0 | 32 | 0 | 11 | 0 | 미완료 |
| PF2M710x-xx-Lx-xxx | iolink:131:377 | V1.00 | current/PF2M_IO-Link_IODD.zip | 6/0 | 31 | 0 | 10 | 1 | 미완료 |
| PF2M710x-xx-Lx-xxx-X731 | iolink:131:521 | V1.00 | current/PF2M_X731_IODD.zip | 6/0 | 31 | 0 | 10 | 0 | 미완료 |
| PF2M711x-xx-L2x-xxx | iolink:131:390 | V1.00 | current/PF2M_IO-Link_IODD.zip | 6/0 | 33 | 0 | 10 | 1 | 미완료 |
| PF2M711x-xx-L2x-xxx-X731 | iolink:131:534 | V1.00 | current/PF2M_X731_IODD.zip | 6/0 | 33 | 0 | 10 | 0 | 미완료 |
| PF2M711x-xx-L3x-xxx | iolink:131:391 | V1.00 | current/PF2M_IO-Link_IODD.zip | 6/0 | 34 | 0 | 11 | 1 | 미완료 |
| PF2M711x-xx-L3x-xxx-X731 | iolink:131:535 | V1.00 | current/PF2M_X731_IODD.zip | 6/0 | 33 | 0 | 11 | 0 | 미완료 |
| PF2M711x-xx-L4x-xxx | iolink:131:392 | V1.00 | current/PF2M_IO-Link_IODD.zip | 6/0 | 33 | 0 | 11 | 1 | 미완료 |
| PF2M711x-xx-L4x-xxx-X731 | iolink:131:536 | V1.00 | current/PF2M_X731_IODD.zip | 6/0 | 32 | 0 | 11 | 0 | 미완료 |
| PF2M711x-xx-Lx-xxx | iolink:131:389 | V1.00 | current/PF2M_IO-Link_IODD.zip | 6/0 | 31 | 0 | 10 | 1 | 미완료 |
| PF2M711x-xx-Lx-xxx-X731 | iolink:131:533 | V1.00 | current/PF2M_X731_IODD.zip | 6/0 | 31 | 0 | 10 | 0 | 미완료 |
| PF2M721x-xx-L2x-xxx | iolink:131:572 | V1.00 | current/PF2M_IO-Link_IODD.zip | 6/0 | 32 | 0 | 10 | 0 | 미완료 |
| PF2M721x-xx-L3x-xxx | iolink:131:573 | V1.00 | current/PF2M_IO-Link_IODD.zip | 6/0 | 33 | 0 | 11 | 0 | 미완료 |
| PF2M721x-xx-L4x-xxx | iolink:131:574 | V1.00 | current/PF2M_IO-Link_IODD.zip | 6/0 | 32 | 0 | 11 | 0 | 미완료 |
| PF2M721x-xx-Lx-xxx | iolink:131:571 | V1.00 | current/PF2M_IO-Link_IODD.zip | 6/0 | 30 | 0 | 10 | 0 | 미완료 |
| PF2M725x-xx-L2x-xxx | iolink:131:382 | V1.00 | current/PF2M_IO-Link_IODD.zip | 6/0 | 32 | 0 | 10 | 1 | 미완료 |
| PF2M725x-xx-L2x-xxx-X731 | iolink:131:526 | V1.00 | current/PF2M_X731_IODD.zip | 6/0 | 32 | 0 | 10 | 0 | 미완료 |
| PF2M725x-xx-L3x-xxx | iolink:131:383 | V1.00 | current/PF2M_IO-Link_IODD.zip | 6/0 | 33 | 0 | 11 | 1 | 미완료 |
| PF2M725x-xx-L3x-xxx-X731 | iolink:131:527 | V1.00 | current/PF2M_X731_IODD.zip | 6/0 | 32 | 0 | 11 | 0 | 미완료 |
| PF2M725x-xx-L4x-xxx | iolink:131:384 | V1.00 | current/PF2M_IO-Link_IODD.zip | 6/0 | 32 | 0 | 11 | 1 | 미완료 |
| PF2M725x-xx-L4x-xxx-X731 | iolink:131:528 | V1.00 | current/PF2M_X731_IODD.zip | 6/0 | 31 | 0 | 11 | 0 | 미완료 |
| PF2M725x-xx-Lx-xxx | iolink:131:381 | V1.00 | current/PF2M_IO-Link_IODD.zip | 6/0 | 30 | 0 | 10 | 1 | 미완료 |
| PF2M725x-xx-Lx-xxx-X731 | iolink:131:525 | V1.00 | current/PF2M_X731_IODD.zip | 6/0 | 30 | 0 | 10 | 0 | 미완료 |
| PF2M750x-xx-L2x-xxx | iolink:131:386 | V1.00 | current/PF2M_IO-Link_IODD.zip | 6/0 | 32 | 0 | 10 | 1 | 미완료 |
| PF2M750x-xx-L2x-xxx-X731 | iolink:131:530 | V1.00 | current/PF2M_X731_IODD.zip | 6/0 | 32 | 0 | 10 | 0 | 미완료 |
| PF2M750x-xx-L3x-xxx | iolink:131:387 | V1.00 | current/PF2M_IO-Link_IODD.zip | 6/0 | 33 | 0 | 11 | 1 | 미완료 |
| PF2M750x-xx-L3x-xxx-X731 | iolink:131:531 | V1.00 | current/PF2M_X731_IODD.zip | 6/0 | 32 | 0 | 11 | 0 | 미완료 |
| PF2M750x-xx-L4x-xxx | iolink:131:388 | V1.00 | current/PF2M_IO-Link_IODD.zip | 6/0 | 32 | 0 | 11 | 1 | 미완료 |
| PF2M750x-xx-L4x-xxx-X731 | iolink:131:532 | V1.00 | current/PF2M_X731_IODD.zip | 6/0 | 31 | 0 | 11 | 0 | 미완료 |
| PF2M750x-xx-Lx-xxx | iolink:131:385 | V1.00 | current/PF2M_IO-Link_IODD.zip | 6/0 | 30 | 0 | 10 | 1 | 미완료 |
| PF2M750x-xx-Lx-xxx-X731 | iolink:131:529 | V1.00 | current/PF2M_X731_IODD.zip | 6/0 | 30 | 0 | 10 | 0 | 미완료 |
| PF2MC7102-xx-L2x-xxx | iolink:131:587 | V1.00 | current/PF2MC7.zip | 6/0 | 32 | 0 | 13 | 0 | 미완료 |
| PF2MC7102-xx-L3x-xxx | iolink:131:588 | V1.00 | current/PF2MC7.zip | 6/0 | 33 | 0 | 14 | 0 | 미완료 |
| PF2MC7102-xx-L4x-xxx | iolink:131:589 | V1.00 | current/PF2MC7.zip | 6/0 | 32 | 0 | 14 | 0 | 미완료 |
| PF2MC7102-xx-Lx-xxx | iolink:131:586 | V1.00 | current/PF2MC7.zip | 6/0 | 30 | 0 | 13 | 0 | 미완료 |
| PF2MC7202-xx-L2x-xxx | iolink:131:591 | V1.00 | current/PF2MC7.zip | 6/0 | 32 | 0 | 13 | 0 | 미완료 |
| PF2MC7202-xx-L3x-xxx | iolink:131:592 | V1.00 | current/PF2MC7.zip | 6/0 | 33 | 0 | 14 | 0 | 미완료 |
| PF2MC7202-xx-L4x-xxx | iolink:131:593 | V1.00 | current/PF2MC7.zip | 6/0 | 32 | 0 | 14 | 0 | 미완료 |
| PF2MC7202-xx-Lx-xxx | iolink:131:590 | V1.00 | current/PF2MC7.zip | 6/0 | 30 | 0 | 13 | 0 | 미완료 |
| PF2MC7501-xx-L2x-xxx | iolink:131:583 | V1.00 | current/PF2MC7.zip | 6/0 | 32 | 0 | 13 | 0 | 미완료 |
| PF2MC7501-xx-L3x-xxx | iolink:131:584 | V1.00 | current/PF2MC7.zip | 6/0 | 33 | 0 | 14 | 0 | 미완료 |
| PF2MC7501-xx-L4x-xxx | iolink:131:585 | V1.00 | current/PF2MC7.zip | 6/0 | 32 | 0 | 14 | 0 | 미완료 |
| PF2MC7501-xx-Lx-xxx | iolink:131:582 | V1.00 | current/PF2MC7.zip | 6/0 | 30 | 0 | 13 | 0 | 미완료 |
| PF3A704H-xx-L3x-xxx | iolink:131:742 | V1.00 | current/PF3A7HM.zip | 6/0 | 42 | 0 | 13 | 1 | 미완료 |
| PF3A704H-xx-L4x-xxx | iolink:131:743 | V1.00 | current/PF3A7HM.zip | 6/0 | 41 | 0 | 13 | 1 | 미완료 |
| PF3A704H-xx-Lx-xxx | iolink:131:741 | V1.00 | current/PF3A7HM.zip | 6/0 | 37 | 0 | 12 | 1 | 미완료 |
| PF3A708H-xx-L3x-xxx | iolink:131:745 | V1.00 | current/PF3A7HM.zip | 6/0 | 42 | 0 | 13 | 1 | 미완료 |
| PF3A708H-xx-L4x-xxx | iolink:131:746 | V1.00 | current/PF3A7HM.zip | 6/0 | 41 | 0 | 13 | 1 | 미완료 |
| PF3A708H-xx-Lx-xxx | iolink:131:744 | V1.00 | current/PF3A7HM.zip | 6/0 | 37 | 0 | 12 | 1 | 미완료 |
| PF3A7R5H-xx-L3x-xxx | iolink:131:739 | V1.00 | current/PF3A7HM.zip | 6/0 | 42 | 0 | 13 | 1 | 미완료 |
| PF3A7R5H-xx-L4x-xxx | iolink:131:740 | V1.00 | current/PF3A7HM.zip | 6/0 | 41 | 0 | 13 | 1 | 미완료 |
| PF3A7R5H-xx-Lx-xxx | iolink:131:738 | V1.00 | current/PF3A7HM.zip | 6/0 | 37 | 0 | 12 | 1 | 미완료 |
| PF3W704-LT-X445 | iolink:131:330 | V1.02 | current/PF3W7-X445_IO-Link_IODD_V1.1.zip | 14/0 | 64 | 2 | 0 | 4 | 미완료 |
| PF3W704x-xx-LxT-xxx | iolink:131:357 | V1.10 | current/PF3W_IO-Link_IODD_V1.10.zip | 14/0 | 61 | 2 | 5 | 4 | 미완료 |
| PF3W704x-xx-Lxx-xxx | iolink:131:352 | V1.10 | current/PF3W_IO-Link_IODD_V1.10.zip | 12/0 | 47 | 2 | 5 | 2 | 미완료 |
| PF3W711-LT | iolink:131:331 | V1.02 | current/PF3W7-X445_IO-Link_IODD_V1.1.zip | 14/0 | 64 | 2 | 0 | 4 | 미완료 |
| PF3W711x-xx-LxT-xxx | iolink:131:360 | V1.10 | current/PF3W_IO-Link_IODD_V1.10.zip | 14/0 | 61 | 2 | 5 | 4 | 미완료 |
| PF3W711x-xx-Lxx-xxx | iolink:131:355 | V1.10 | current/PF3W_IO-Link_IODD_V1.10.zip | 12/0 | 47 | 2 | 5 | 2 | 미완료 |
| PF3W720-LT-X445 | iolink:131:310 | V1.02 | current/PF3W7-X445_IO-Link_IODD_V1.1.zip | 14/0 | 64 | 2 | 0 | 4 | 미완료 |
| PF3W720x-xx-LxT-xxx | iolink:131:358 | V1.10 | current/PF3W_IO-Link_IODD_V1.10.zip | 14/0 | 61 | 2 | 5 | 4 | 미완료 |
| PF3W720x-xx-Lxx-xxx | iolink:131:353 | V1.10 | current/PF3W_IO-Link_IODD_V1.10.zip | 12/0 | 47 | 2 | 5 | 2 | 미완료 |
| PF3W721-LT | iolink:131:332 | V1.02 | current/PF3W7-X445_IO-Link_IODD_V1.1.zip | 14/0 | 64 | 2 | 0 | 4 | 미완료 |
| PF3W721x-xx-LxT-xxx | iolink:131:361 | V1.10 | current/PF3W_IO-Link_IODD_V1.10.zip | 14/0 | 61 | 2 | 5 | 4 | 미완료 |
| PF3W721x-xx-Lxx-xxx | iolink:131:356 | V1.10 | current/PF3W_IO-Link_IODD_V1.10.zip | 12/0 | 47 | 2 | 5 | 2 | 미완료 |
| PF3W740-LT-X445 | iolink:131:317 | V1.02 | current/PF3W7-X445_IO-Link_IODD_V1.1.zip | 14/0 | 64 | 2 | 0 | 4 | 미완료 |
| PF3W740x-xx-LxT-xxx | iolink:131:359 | V1.10 | current/PF3W_IO-Link_IODD_V1.10.zip | 14/0 | 61 | 2 | 5 | 4 | 미완료 |
| PF3W740x-xx-Lxx-xxx | iolink:131:354 | V1.10 | current/PF3W_IO-Link_IODD_V1.10.zip | 12/0 | 47 | 2 | 5 | 2 | 미완료 |
| PFCA710-xx-1x-xxx | iolink:131:611 | V1.00 | current/PFCA_IODD.zip | 14/1 | 38 | 0 | 4 | 2 | 미완료 |
| PFCA710-xx-2x-xxx | iolink:131:612 | V1.00 | current/PFCA_IODD.zip | 14/1 | 37 | 0 | 4 | 2 | 미완료 |
| PFCA711-xx-1x-xxx | iolink:131:617 | V1.00 | current/PFCA_IODD.zip | 14/1 | 38 | 0 | 4 | 2 | 미완료 |
| PFCA711-xx-2x-xxx | iolink:131:618 | V1.00 | current/PFCA_IODD.zip | 14/1 | 37 | 0 | 4 | 2 | 미완료 |
| PFCA725-xx-1x-xxx | iolink:131:613 | V1.00 | current/PFCA_IODD.zip | 14/1 | 37 | 0 | 4 | 2 | 미완료 |
| PFCA725-xx-2x-xxx | iolink:131:614 | V1.00 | current/PFCA_IODD.zip | 14/1 | 36 | 0 | 4 | 2 | 미완료 |
| PFCA750-xx-1x-xxx | iolink:131:615 | V1.00 | current/PFCA_IODD.zip | 14/1 | 37 | 0 | 4 | 2 | 미완료 |
| PFCA750-xx-2x-xxx | iolink:131:616 | V1.00 | current/PFCA_IODD.zip | 14/1 | 36 | 0 | 4 | 2 | 미완료 |
| PFUW711-L1x-xx | iolink:131:671 | V1.1 | current/PFUW-Series-IODD-File.zip | 14/0 | 39 | 0 | 6 | 2 | 미완료 |
| PFUW711-L2x-xx | iolink:131:672 | V1.1 | current/PFUW-Series-IODD-File.zip | 14/0 | 42 | 0 | 6 | 2 | 미완료 |
| PFUW711-L3x-xx | iolink:131:673 | V1.1 | current/PFUW-Series-IODD-File.zip | 14/0 | 41 | 0 | 6 | 2 | 미완료 |
| PFUW711-L4x-xx | iolink:131:674 | V1.1 | current/PFUW-Series-IODD-File.zip | 14/0 | 40 | 0 | 6 | 2 | 미완료 |
| PFUW721-L1x-xx | iolink:131:760 | V1.0 | current/PFUW-Series-IODD-File.zip | 14/0 | 39 | 0 | 6 | 2 | 미완료 |
| PFUW721-L2x-xx | iolink:131:761 | V1.0 | current/PFUW-Series-IODD-File.zip | 14/0 | 42 | 0 | 6 | 2 | 미완료 |
| PFUW721-L3x-xx | iolink:131:762 | V1.0 | current/PFUW-Series-IODD-File.zip | 14/0 | 41 | 0 | 6 | 2 | 미완료 |
| PFUW721-L4x-xx | iolink:131:763 | V1.0 | current/PFUW-Series-IODD-File.zip | 14/0 | 40 | 0 | 6 | 2 | 미완료 |
| PFUW760-L1x-xx | iolink:131:667 | V1.1 | current/PFUW-Series-IODD-File.zip | 14/0 | 39 | 0 | 6 | 2 | 미완료 |
| PFUW760-L2x-xx | iolink:131:668 | V1.1 | current/PFUW-Series-IODD-File.zip | 14/0 | 42 | 0 | 6 | 2 | 미완료 |
| PFUW760-L3x-xx | iolink:131:669 | V1.1 | current/PFUW-Series-IODD-File.zip | 14/0 | 41 | 0 | 6 | 2 | 미완료 |
| PFUW760-L4x-xx | iolink:131:670 | V1.1 | current/PFUW-Series-IODD-File.zip | 14/0 | 40 | 0 | 6 | 2 | 미완료 |
| PF3A701H-xx-L3x-xxx | iolink:131:395 | V2.00 | current/PF3A7HM.zip | 6/0 | 42 | 0 | 13 | 1 | 미완료 |
| PF3A701H-xx-L3x-xxx | iolink:131:395 | V1.00 | historical/PF3A7_H-L-M_IODD.zip | 6/0 | 39 | 0 | 13 | 1 | 미완료 |
| PF3A701H-xx-L4x-xxx | iolink:131:396 | V2.00 | current/PF3A7HM.zip | 6/0 | 41 | 0 | 13 | 1 | 미완료 |
| PF3A701H-xx-L4x-xxx | iolink:131:396 | V1.00 | historical/PF3A7_H-L-M_IODD.zip | 6/0 | 38 | 0 | 13 | 1 | 미완료 |
| PF3A701H-xx-Lx-xxx | iolink:131:394 | V2.00 | current/PF3A7HM.zip | 6/0 | 37 | 0 | 12 | 1 | 미완료 |
| PF3A701H-xx-Lx-xxx | iolink:131:394 | V1.00 | historical/PF3A7_H-L-M_IODD.zip | 6/0 | 34 | 0 | 12 | 1 | 미완료 |
| PF3A702H-xx-L3x-xxx | iolink:131:398 | V2.00 | current/PF3A7HM.zip | 6/0 | 42 | 0 | 13 | 1 | 미완료 |
| PF3A702H-xx-L3x-xxx | iolink:131:398 | V1.00 | historical/PF3A7_H-L-M_IODD.zip | 6/0 | 39 | 0 | 13 | 1 | 미완료 |
| PF3A702H-xx-L4x-xxx | iolink:131:399 | V2.00 | current/PF3A7HM.zip | 6/0 | 41 | 0 | 13 | 1 | 미완료 |
| PF3A702H-xx-L4x-xxx | iolink:131:399 | V1.00 | historical/PF3A7_H-L-M_IODD.zip | 6/0 | 38 | 0 | 13 | 1 | 미완료 |
| PF3A702H-xx-Lx-xxx | iolink:131:397 | V2.00 | current/PF3A7HM.zip | 6/0 | 37 | 0 | 12 | 1 | 미완료 |
| PF3A702H-xx-Lx-xxx | iolink:131:397 | V1.00 | historical/PF3A7_H-L-M_IODD.zip | 6/0 | 34 | 0 | 12 | 1 | 미완료 |
| PF3A703H-xx-L3x-xxx | iolink:131:401 | V2.00 | current/PF3A7H.zip | 6/0 | 42 | 0 | 13 | 1 | 미완료 |
| PF3A703H-xx-L3x-xxx | iolink:131:401 | V1.00 | historical/PF3A7H_IO-Link_IODD_V1.00.zip | 6/0 | 39 | 0 | 13 | 1 | 미완료 |
| PF3A703H-xx-L4x-xxx | iolink:131:402 | V2.00 | current/PF3A7H.zip | 6/0 | 41 | 0 | 13 | 1 | 미완료 |
| PF3A703H-xx-L4x-xxx | iolink:131:402 | V1.00 | historical/PF3A7H_IO-Link_IODD_V1.00.zip | 6/0 | 38 | 0 | 13 | 1 | 미완료 |
| PF3A703H-xx-Lx-xxx | iolink:131:400 | V1.00 | current/PF3A7H.zip | 6/0 | 37 | 0 | 12 | 1 | 미완료 |
| PF3A703H-xx-Lx-xxx | iolink:131:400 | V1.00 | historical/PF3A7H_IO-Link_IODD_V1.00.zip | 6/0 | 34 | 0 | 12 | 1 | 미완료 |
| PF3A706H-xx-L3x-xxx | iolink:131:404 | V2.00 | current/PF3A7H.zip | 6/0 | 42 | 0 | 13 | 1 | 미완료 |
| PF3A706H-xx-L3x-xxx | iolink:131:404 | V1.00 | historical/PF3A7H_IO-Link_IODD_V1.00.zip | 6/0 | 39 | 0 | 13 | 1 | 미완료 |
| PF3A706H-xx-L4x-xxx | iolink:131:405 | V2.00 | current/PF3A7H.zip | 6/0 | 41 | 0 | 13 | 1 | 미완료 |
| PF3A706H-xx-L4x-xxx | iolink:131:405 | V1.00 | historical/PF3A7H_IO-Link_IODD_V1.00.zip | 6/0 | 38 | 0 | 13 | 1 | 미완료 |
| PF3A706H-xx-Lx-xxx | iolink:131:403 | V2.00 | current/PF3A7H.zip | 6/0 | 37 | 0 | 12 | 1 | 미완료 |
| PF3A706H-xx-Lx-xxx | iolink:131:403 | V1.00 | historical/PF3A7H_IO-Link_IODD_V1.00.zip | 6/0 | 34 | 0 | 12 | 1 | 미완료 |
| PF3A712H-xx-L3x-xxx | iolink:131:407 | V2.00 | current/PF3A7H.zip | 6/0 | 42 | 0 | 13 | 1 | 미완료 |
| PF3A712H-xx-L3x-xxx | iolink:131:407 | V1.00 | historical/PF3A7H_IO-Link_IODD_V1.00.zip | 6/0 | 39 | 0 | 13 | 1 | 미완료 |
| PF3A712H-xx-L4x-xxx | iolink:131:408 | V2.00 | current/PF3A7H.zip | 6/0 | 41 | 0 | 13 | 1 | 미완료 |
| PF3A712H-xx-L4x-xxx | iolink:131:408 | V1.00 | historical/PF3A7H_IO-Link_IODD_V1.00.zip | 6/0 | 38 | 0 | 13 | 1 | 미완료 |
| PF3A712H-xx-Lx-xxx | iolink:131:406 | V2.00 | current/PF3A7H.zip | 6/0 | 37 | 0 | 12 | 1 | 미완료 |
| PF3A712H-xx-Lx-xxx | iolink:131:406 | V1.00 | historical/PF3A7H_IO-Link_IODD_V1.00.zip | 6/0 | 34 | 0 | 12 | 1 | 미완료 |
| ITV-IL | iolink:131:537 | V1.00 | current/SMC-ITV-IL.zip | 15/1 | 8 | 0 | 0 | 0 | 미완료 |
| PSH-L2 | iolink:131:650 | V1.00 | current/IODD FILE.zip | 9/0 | 34 | 0 | 14 | 0 | 미완료 |
| PSH-L2 | iolink:131:728 | V1.0 | current/IODD FILE.zip | 10/0 | 36 | 0 | 15 | 2 | 미완료 |
| PSH-LL | iolink:131:729 | V1.1 | current/IODD FILE.zip | 10/0 | 36 | 0 | 15 | 2 | 미완료 |
| FC3W504-xx-Lx-xx | iolink:131:735 | V1.7 | current/FC3W_IODD.zip | 12/3 | 15 | 0 | 4 | 0 | 미완료 |
| FC3W520-xx-Lx-xx | iolink:131:736 | V1.3 | current/FC3W_IODD.zip | 12/3 | 15 | 0 | 4 | 0 | 미완료 |
| FC3W540-xx-Lx-xx | iolink:131:737 | V1.4 | current/FC3W_IODD.zip | 12/3 | 15 | 0 | 4 | 0 | 미완료 |
| IN502-44-5/6/13/14 | iolink:131:575 | V1.00 | current/IN502.zip | 11/1 | 30 | 0 | 6 | 0 | 미완료 |
| IN502-44-7/8/15/16 | iolink:131:576 | V1.00 | current/IN502.zip | 11/1 | 28 | 0 | 6 | 0 | 미완료 |
| IN502-45-5/6/13/14 | iolink:131:577 | V1.00 | current/IN502.zip | 11/1 | 30 | 0 | 6 | 0 | 미완료 |
| IN502-45-7/8/15/16 | iolink:131:578 | V1.00 | current/IN502.zip | 11/1 | 28 | 0 | 6 | 0 | 미완료 |
| IN502-46-5/6/13/14 | iolink:131:727 | V1.00 | current/IN502.zip | 11/1 | 30 | 0 | 6 | 0 | 미완료 |
| IN502-46-7/8/15/16 | iolink:131:726 | V1.00 | current/IN502.zip | 11/1 | 28 | 0 | 6 | 0 | 미완료 |
| IZS51-L | iolink:131:666 | V1.7 | current/SMC-IZS51-L-20240920.zip | 10/4 | 14 | 0 | 0 | 0 | 미완료 |
| IZTC41-Lxx-x | iolink:131:581 | V1.00 | current/SMC-IZTC41-Lxx-x.zip | 41/9 | 33 | 0 | 0 | 0 | 미완료 |
| EX260-MIL1 | iolink:131:661 | V1.0.0 | current/SMC-EX260-MIL1.zip | 5/4 | 14 | 0 | 6 | 0 | 미완료 |
| EX260-MIL1 | iolink:131:662 | V1.0.0 | current/SMC-EX260-MIL1.zip | 5/8 | 15 | 0 | 7 | 0 | 미완료 |
| EX260-MIL1 | iolink:131:663 | V1.0.0 | current/SMC-EX260-MIL1.zip | 5/12 | 16 | 0 | 8 | 0 | 미완료 |
| EX260-MIL1 | iolink:131:664 | V1.0.0 | current/SMC-EX260-MIL1.zip | 5/16 | 17 | 0 | 9 | 0 | 미완료 |
| EX260-PIL1 | iolink:131:687 | V1.0.0 | current/SMC-EX260-PIL1.zip | 28/3 | 30 | 0 | 15 | 0 | 미완료 |
| EX260-PIL1 | iolink:131:688 | V1.0.0 | current/SMC-EX260-PIL1.zip | 33/3 | 30 | 0 | 15 | 0 | 미완료 |
| EX430-SIL1_in/out_0/4 byte_COM2 | iolink:131:568 | V1.02 | current/SMC-EX430-SIL1.zip | 0/32 | 10 | 0 | 8 | 0 | 미완료 |
| EX430-SIL1_in/out_0/4 byte_COM3 | iolink:131:567 | V1.02 | current/SMC-EX430-SIL1.zip | 0/32 | 10 | 0 | 8 | 0 | 미완료 |
| EX430-SIL1_in/out_2/4 byte_COM2 | iolink:131:570 | V1.02 | current/SMC-EX430-SIL1.zip | 2/32 | 10 | 0 | 8 | 0 | 미완료 |
| EX430-SIL1_in/out_2/4 byte_COM3 | iolink:131:569 | V1.02 | current/SMC-EX430-SIL1.zip | 2/32 | 10 | 0 | 8 | 0 | 미완료 |
| D-MP025 | iolink:131:293 | V1.3 | current/SMC-D-MPx.zip | 5/0 | 18 | 0 | 13 | 0 | 미완료 |
| D-MP050 | iolink:131:294 | V1.3 | current/SMC-D-MPx.zip | 5/0 | 18 | 0 | 13 | 0 | 미완료 |
| D-MP100 | iolink:131:295 | V1.3 | current/SMC-D-MPx.zip | 5/0 | 18 | 0 | 13 | 0 | 미완료 |
| D-MP200 | iolink:131:296 | V1.3 | current/SMC-D-MPx.zip | 5/0 | 18 | 0 | 13 | 0 | 미완료 |
| D-MPG | iolink:131:579 | V1.7 | current/SMC-D-MPG-20240604-IODD1.1.zip | 10/0 | 40 | 0 | 23 | 0 | 미완료 |
| ISA3-F | iolink:131:341 | V1.00 | current/SMC-ISA3-F.zip | 33/0 | 31 | 3 | 17 | 0 | 미완료 |
| ISA3-G | iolink:131:342 | V1.00 | current/SMC-ISA3-G.zip | 33/0 | 31 | 3 | 17 | 0 | 미완료 |
| ISA3-H | iolink:131:343 | V1.00 | current/SMC-ISA3-H.zip | 33/0 | 31 | 3 | 17 | 0 | 미완료 |
| ISE20B-L | iolink:131:334 | V1.00 | current/SMC-ZSE20B_ISE20B-L.zip | 20/0 | 47 | 5 | 0 | 7 | 미완료 |
| ISE20B-L-P | iolink:131:335 | V1.00 | current/SMC-ZSE20B_ISE20B-L.zip | 20/0 | 47 | 5 | 0 | 7 | 미완료 |
| ISE20B-T | iolink:131:304 | V1.00 | current/SMC-ZSE20B_ISE20B-X101.zip | 20/0 | 47 | 5 | 0 | 5 | 미완료 |
| ISE20C-L | iolink:131:554 | V1.00 | current/ZSE20C-ISE20C-L_IODD.zip | 20/0 | 47 | 5 | 0 | 7 | 미완료 |
| ISE20C-L-P | iolink:131:555 | V1.00 | current/ZSE20C-ISE20C-L_IODD.zip | 20/0 | 47 | 5 | 0 | 7 | 미완료 |
| ISE20CH-L | iolink:131:560 | V1.00 | current/ZSE20C-ISE20C-L_IODD.zip | 20/0 | 47 | 5 | 0 | 7 | 미완료 |
| ISE20CH-L-P | iolink:131:561 | V1.00 | current/ZSE20C-ISE20C-L_IODD.zip | 20/0 | 47 | 5 | 0 | 7 | 미완료 |
| ISE70 | iolink:131:307 | V1.01 | current/SMC-ISE70_71-L2.zip | 20/0 | 47 | 5 | 0 | 4 | 미완료 |
| ISE70G | iolink:131:309 | V1.01 | current/ISE7.zip | 20/0 | 47 | 5 | 0 | 4 | 미완료 |
| ISE71 | iolink:131:308 | V1.01 | current/SMC-ISE70_71-L2.zip | 20/0 | 47 | 5 | 0 | 3 | 미완료 |
| ISE75G | iolink:131:320 | V1.01 | current/ISE7.zip | 20/0 | 47 | 5 | 0 | 5 | 미완료 |
| ISE76G | iolink:131:321 | V1.01 | current/ISE7.zip | 16/0 | 47 | 4 | 0 | 4 | 미완료 |
| ISE77G | iolink:131:322 | V1.01 | current/ISE7.zip | 20/0 | 47 | 5 | 0 | 4 | 미완료 |
| ISE78G | iolink:131:362 | V1.01 | current/ISE7.zip | 20/0 | 47 | 5 | 0 | 4 | 미완료 |
| ISE79S | iolink:131:594 | V1.01 | current/SMC-ISE79G.zip | 20/0 | 47 | 5 | 0 | 4 | 미완료 |
| PSE202A | iolink:131:340 | V1.00 | current/SMC-PSE202A.zip | 17/0 | 77 | 0 | 34 | 0 | 미완료 |
| ZSE20B-L | iolink:131:336 | V1.00 | current/SMC-ZSE20B_ISE20B-L.zip | 28/0 | 47 | 7 | 0 | 9 | 미완료 |
| ZSE20B-L-P | iolink:131:337 | V1.00 | current/SMC-ZSE20B_ISE20B-L.zip | 28/0 | 47 | 7 | 0 | 9 | 미완료 |
| ZSE20B-T | iolink:131:305 | V1.00 | current/SMC-ZSE20B_ISE20B-X101.zip | 28/0 | 47 | 7 | 0 | 7 | 미완료 |
| ZSE20BF-L | iolink:131:338 | V1.00 | current/SMC-ZSE20B_ISE20B-L.zip | 28/0 | 47 | 7 | 0 | 9 | 미완료 |
| ZSE20BF-L-P | iolink:131:339 | V1.00 | current/SMC-ZSE20B_ISE20B-L.zip | 28/0 | 47 | 7 | 0 | 9 | 미완료 |
| ZSE20BF-T | iolink:131:306 | V1.00 | current/SMC-ZSE20B_ISE20B-X101.zip | 28/0 | 47 | 7 | 0 | 7 | 미완료 |
| ZSE20C-L | iolink:131:556 | V1.00 | current/ZSE20C-ISE20C-L_IODD.zip | 28/0 | 47 | 7 | 0 | 9 | 미완료 |
| ZSE20C-L-P | iolink:131:557 | V1.00 | current/ZSE20C-ISE20C-L_IODD.zip | 28/0 | 47 | 7 | 0 | 9 | 미완료 |
| ZSE20CF-L | iolink:131:558 | V1.00 | current/ZSE20C-ISE20C-L_IODD.zip | 28/0 | 47 | 7 | 0 | 9 | 미완료 |
| ZSE20CF-L-P | iolink:131:559 | V1.00 | current/ZSE20C-ISE20C-L_IODD.zip | 28/0 | 47 | 7 | 0 | 9 | 미완료 |
| PSE540 | iolink:131:677 | V0.01 | current/IODD File for PSE54-L.zip | 12/0 | 17 | 2 | 5 | 0 | 미완료 |
| PSE540 | iolink:131:677 | V0.01 | current/IODD File for PSE54-L.zip | 42/0 | 17 | 7 | 5 | 0 | 미완료 |
| PSE541 | iolink:131:678 | V0.01 | current/IODD File for PSE54-L.zip | 12/0 | 17 | 2 | 5 | 0 | 미완료 |
| PSE541 | iolink:131:678 | V0.01 | current/IODD File for PSE54-L.zip | 42/0 | 17 | 7 | 5 | 0 | 미완료 |
| PSE543 | iolink:131:679 | V0.01 | current/IODD File for PSE54-L.zip | 12/0 | 17 | 2 | 5 | 0 | 미완료 |
| PSE543 | iolink:131:679 | V0.01 | current/IODD File for PSE54-L.zip | 42/0 | 17 | 7 | 5 | 0 | 미완료 |
| PSE570 | iolink:131:680 | V0.01 | current/IODD File for PSE57-L.zip | 12/0 | 18 | 2 | 6 | 0 | 미완료 |
| PSE570 | iolink:131:680 | V0.01 | current/IODD File for PSE57-L.zip | 30/0 | 18 | 5 | 6 | 0 | 미완료 |
| PSE573 | iolink:131:681 | V0.01 | current/IODD File for PSE57-L.zip | 12/0 | 18 | 2 | 6 | 0 | 미완료 |
| PSE573 | iolink:131:681 | V0.01 | current/IODD File for PSE57-L.zip | 42/0 | 18 | 7 | 6 | 0 | 미완료 |
| PSE574 | iolink:131:682 | V0.01 | current/IODD File for PSE57-L.zip | 12/0 | 18 | 2 | 6 | 0 | 미완료 |
| PSE574 | iolink:131:682 | V0.01 | current/IODD File for PSE57-L.zip | 30/0 | 18 | 5 | 6 | 0 | 미완료 |
| PSE575 | iolink:131:683 | V0.01 | current/IODD File for PSE57-L.zip | 12/0 | 18 | 2 | 6 | 0 | 미완료 |
| PSE575 | iolink:131:683 | V0.01 | current/IODD File for PSE57-L.zip | 30/0 | 18 | 5 | 6 | 0 | 미완료 |
| PSE576 | iolink:131:684 | V0.01 | current/IODD File for PSE57-L.zip | 12/0 | 18 | 2 | 6 | 0 | 미완료 |
| PSE576 | iolink:131:684 | V0.01 | current/IODD File for PSE57-L.zip | 30/0 | 18 | 5 | 6 | 0 | 미완료 |
| PSE577 | iolink:131:685 | V0.01 | current/IODD File for PSE57-L.zip | 12/0 | 18 | 2 | 6 | 0 | 미완료 |
| PSE577 | iolink:131:685 | V0.01 | current/IODD File for PSE57-L.zip | 30/0 | 18 | 5 | 6 | 0 | 미완료 |
| EX260-SIL1_in/out_0/4 byte_COM2 | iolink:131:345 | V1.02 | current/SMC-EX260-SIL1.zip | 0/32 | 8 | 0 | 8 | 0 | 미완료 |
| EX260-SIL1_in/out_0/4 byte_COM3 | iolink:131:344 | V1.02 | current/SMC-EX260-SIL1.zip | 0/32 | 8 | 0 | 8 | 0 | 미완료 |
| EX260-SIL1_in/out_2/4 byte_COM2 | iolink:131:347 | V1.02 | current/SMC-EX260-SIL1.zip | 2/32 | 8 | 0 | 8 | 0 | 미완료 |
| EX260-SIL1_in/out_2/4 byte_COM3 | iolink:131:346 | V1.02 | current/SMC-EX260-SIL1.zip | 2/32 | 8 | 0 | 8 | 0 | 미완료 |
| JXCL | iolink:131:318 | V1.00 | current/SMC-JXCL.zip | 15/20 | 73 | 0 | 71 | 0 | 미완료 |
| EX600-TDX_DI | iolink:131:732 | V1.0.0 | current/SMC-EX600-TDXx.zip | 32/0 | 32 | 0 | 26 | 0 | 미완료 |
| EX600-TDX_DI | iolink:131:733 | V1.0.1 | current/SMC-EX600-TDXx.zip | 16/0 | 24 | 0 | 18 | 0 | 미완료 |
| ZSE10-X148/149 | iolink:131:648 | V1.01 | current/ZSE10-X148_149.zip | 13/5 | 27 | 0 | 6 | 0 | 미완료 |
| ZSE10F-X148/149 | iolink:131:649 | V1.01 | current/ZSE10-X148_149.zip | 13/5 | 27 | 0 | 6 | 0 | 미완료 |
| EX260-VIL1 | iolink:131:596 | V1.1.0 | current/SMC-EX260-VIL1.zip | 3/2 | 25 | 0 | 17 | 0 | 미완료 |
| EX260-VIL1 | iolink:131:597 | V1.1.0 | current/SMC-EX260-VIL1.zip | 3/2 | 25 | 0 | 17 | 0 | 미완료 |
| EX260-VIL1 | iolink:131:598 | V1.1.0 | current/SMC-EX260-VIL1.zip | 3/2 | 25 | 0 | 17 | 0 | 미완료 |
| EX260-VIL1 | iolink:131:599 | V1.1.0 | current/SMC-EX260-VIL1.zip | 3/2 | 25 | 0 | 17 | 0 | 미완료 |
| EQ-IOLINK | iolink:131:754 | V1.00 | current/EQ-BL_IODD_20250616.zip | 9/8 | 14 | 0 | 6 | 0 | 미완료 |

기계 판독용 JSON에는 239개 정의의 모든 항목과 해당 항목의 근거 유무를 보존합니다.
PD 항목 수는 바이트 길이가 아닙니다. 정확한 비트 길이는 JSON layouts.directions.bits에 있습니다.
동일 제품의 구버전도 별도 검토 대상이며 최신 파일로 자동 대체하지 않습니다.

## 패키지별 매뉴얼 검토 결과

### IODD for D-MH2.zip

근거: [OM_D-MH2_DOC1094990EN-1.pdf](https://static.smc.eu/binaries/content/assets/smc_global/product-documentation/operation-manuals/en/om_d-mh2_doc1094990en-1.pdf), PDF 페이지 38, 48, 49, 50, 64.

4-byte 입력의 위치 원시값과 스위치·진단을 분리. 2점/3점 형식과 SP/폭/히스테리시스 상호 제약을 보존. 위치값에 mm 단위를 임의 부여하지 않음.

남은 확인: 비주기 복합 설정 상호 제약 구현.

### SMC-D-MPx.zip

근거: [OM_D-MP_OMU0002EN-B.pdf](https://static.smc.eu/binaries/content/assets/smc_global/product-documentation/operation-manuals/en/om_d-mp_omu0002en-b.pdf), PDF 페이지 17, 18, 21, 22.

2-byte 입력. 상위 12-bit 위치와 하위 4개 BDC를 구분. 비주기 위치/qualifier와 PD는 별도 정의. 측정범위와 teaching 채널을 수동 구성.

남은 확인: PD 위치 배율과 측정범위 선택 검증; 비주기 30000 범위 밖 코드 처리.

### SMC-D-MPG-20240604-IODD1.1.zip

근거: [OM_D-MPG_DOC1073785EN-3.pdf](https://static.smc.eu/binaries/content/assets/smc_global/product-documentation/operation-manuals/en/om_d-mpg_doc1073785en-3.pdf), PDF 페이지 19, 21, 23, 24, 25.

4-byte 입력에 위치, MDC-Scale, 8개 SSC가 포함됨. D-MP의 2-byte 해석 재사용 금지. 스케일과 측정영역 설정을 별도로 보존.

남은 확인: MDC-Scale 기반 해석; SSC 복합 설정과 teaching 처리.

### PF2M_IO-Link_IODD.zip, PF2M_X731_IODD.zip

근거: [OM_PF2M7_OMW0007EN-G.pdf](https://static.smc.eu/binaries/content/assets/smc_global/product-documentation/operation-manuals/en/om_pf2m7_omw0007en-g.pdf), PDF 페이지 14, 73, 74, 75, 77, 83.

signed 16-bit 유량, 고정출력과 측정진단 분리. 정격별 배율 사용. X731 혼합가스 설정은 본문에 있지만 Device ID 표는 일반형이므로 특수형 동일성 확인이 추가로 필요.

남은 확인: 200 L 정격이 범위표에는 있으나 계수표에는 없음; X731 Device ID 및 전용 사양 일치 확인; 누적값 단위와 리셋 정책.

### PF2MC7.zip

근거: [OM_PF2MC7_OMZ0002EN-D.pdf](https://static.smc.eu/binaries/content/assets/smc_global/product-documentation/operation-manuals/en/om_pf2mc7_omz0002en-d.pdf), PDF 페이지 78, 79, 80, 81.

4-byte 입력 유량 구조. 500/1000/2000 L 정격과 원시값 범위를 대조. 변환 계수표의 정격 표기 4/16/40 L는 앞쪽 범위표와 불일치.

남은 확인: 계수표 정격 오기 확인 전 자동 변환 보류.

### PF3A7HM.zip, PF3A7_H-L-M_IODD.zip

근거: [OM_PFA3A7xx_DOC1057506EN-2.pdf](https://static.smc.eu/binaries/content/assets/smc_global/product-documentation/operation-manuals/en/om_pfa3a7xx_doc1057506en-2.pdf), PDF 페이지 74, 75, 76, 77, 78, 79.

500/1000/2000/4000/8000 L 정격별 유량 배율. 고정출력은 실제 측정 상태와 구분. 구버전에도 현재 매뉴얼 전체 기능을 일괄 적용하지 않음.

남은 확인: 구버전 비주기 변경 이력 대조; 누적값·기준 상태 해석.

### PF3A7H.zip, PF3A7H_IO-Link_IODD_V1.00.zip

근거: [OM_PF3A7xH-L_OMX0002EN-G.pdf](https://static.smc.eu/binaries/content/assets/smc_global/product-documentation/operation-manuals/en/om_pf3a7xh-l_omx0002en-g.pdf), PDF 페이지 73, 74, 75, 76, 77, 78.

3000/6000/12000 L 정격별 배율. 현행 PD는 4-byte로 기재됨. 각 구버전 IODD의 길이와 필드는 별도로 보존.

남은 확인: 구버전 레이아웃·기능 차이; 누적값·기준 상태 해석.

### PF3W7-X445_IO-Link_IODD_V1.1.zip

근거: [OM_PF3W7-X445_OMV0006EN-C.pdf](https://static.smc.eu/binaries/content/assets/smc_global/product-documentation/operation-manuals/en/om_pf3w7-x445_omv0006en-c.pdf), PDF 페이지 74, 75, 76, 77, 78, 84.

6-byte 입력 유량/온도, 정격별 유량과 0.1°C 변환. 현행 PF3W와 진단 비트 위치가 다름. 계산 예제의 부호/소수점 불일치 때문에 계수표를 근거로 사용.

남은 확인: 누적 지수 설정과 비주기 값 결합.

### PF3W_IO-Link_IODD_V1.10.zip

근거: [OM_PF3W7_OMW0010EN-I.pdf](https://static.smc.eu/binaries/content/assets/smc_global/product-documentation/operation-manuals/en/om_pf3w7_omw0010en-i.pdf), PDF 페이지 72, 73, 74, 76, 77.

유량 bit32, 온도 bit16. 온도 센서 없는 모델의 온도 영역은 미사용. X445 진단 비트표 재사용 금지.

남은 확인: 비주기 누적·피크값과 단위 조건.

### PFCA_IODD.zip

근거: [OM_PFCA7_OMA1002EN-A.pdf](https://static.smc.eu/binaries/content/assets/smc_global/product-documentation/operation-manuals/en/om_pfca7_oma1002en-a.pdf), PDF 페이지 55, 56, 57, 58, 59, 60, 65.

순간 signed16와 누적 unsigned32, 출력 유량 명령 분리. 누적 배율은 정격/단위별로 다름. local/remote·자동 차단·고정출력 상태가 별도 필요.

남은 확인: 출력 명령 및 자동 차단 동작 연결; 비주기 설정의 모드 의존성.

### PFUW-Series-IODD-File.zip

근거: [OM_PFUW7_DOC1066729EN-2.pdf](https://static.smc.eu/binaries/content/assets/smc_global/product-documentation/operation-manuals/om_pfuw7_doc1066729en-2.pdf), PDF 페이지 84, 85, 87, 88, 89, 95.

8-byte 입력. 누적값은 bit32..63 전체 unsigned32로 IODD와 대조하며 16-bit 반쪽을 각각 32-bit로 해석하지 않음. 초음파 레벨/측정오류/단위 bit를 함께 표시.

남은 확인: 수신 PD 단위 bit와 수동 구성 불일치 처리; 비주기 배관·유체 구성.

### SMC-ITV-IL.zip

근거: [OM_ITV2_00145_EN-B.pdf](https://static.smc.eu/binaries/content/assets/smc_global/product-documentation/operation-manuals/en/om_itv2_00145_en-b.pdf), PDF 페이지 8, 9, 10, 11, 12.

입력4/출력2 byte. 4095가 100%인 관계는 F_1/F_2 조건을 전제로 함. 모델 정격과 설정을 모르면서 MPa로 고정 변환하면 안 됨.

남은 확인: 정격·F_1·F_2 기반 변환; hold/clear 통신 이상 동작.

### IODD FILE.zip

근거: [OM_PSH_DOC1060358EN-2.pdf](https://static.smc.eu/binaries/content/assets/smc_global/product-documentation/operation-manuals/en/om_psh_doc1060358en-2.pdf), PDF 페이지 75, 76, 77, 78.

습도와 온도 signed16 각각 0.1 SI 배율. 매뉴얼은 ID728/729, ZIP에는 ID650도 있어 구형에 자동 적용하지 않음. 화씨 offset26.24는 섭씨/화씨 범위표와 불일치.

남은 확인: ID650 전용 매뉴얼; 화씨 변환 불일치 확인.

### FC3W_IODD.zip

근거: [OM_FC3W5_OMA1018EN-C.pdf](https://static.smc.eu/binaries/content/assets/smc_global/product-documentation/operation-manuals/en/om_fc3w5_oma1018en-c.pdf), PDF 페이지 27, 28, 29, 30, 31, 32, 33.

입력6/출력6 byte. 유량 제어·밸브 개도·원점복귀를 구분. 원점 검출 전 개도 값은 정상 개도 측정값으로 취급하지 않음.

남은 확인: 원점/모드 의존 품질 처리; 명령 범위 검증과 비주기 설정.

### IN502.zip

근거: [OM_IN502-44-45_OMZ1003EN-A.pdf](https://static.smc.eu/binaries/content/assets/smc_global/product-documentation/operation-manuals/en/om_in502-44-45_omz1003en-a.pdf), PDF 페이지 53, 54, 55, 56, 57.

입력8/출력2 byte. 유량/압력/온도와 유량 명령 분리. 확보 문서는 ID575..578의 44/45를 명시하고 46은 누락. bit11은 진단과 예약에 중복 기재됨.

남은 확인: IN502-46 통신 매뉴얼; bit11 표 불일치; 온도는 참고값으로 표시.

### SMC-IZS51-L-20240920.zip

근거: [OM_IZS51_doc1092338EN-1.pdf](https://static.smc.eu/binaries/content/assets/smc_global/product-documentation/operation-manuals/en/om_izs51_doc1092338en-1.pdf), PDF 페이지 40, 43, 44.

입력3/출력2 byte. 10-bit signed 이온 밸런스와 이온/공기 공급 상태. 출력 유효 bit와 설정값을 분리. 이벤트별로 운전 지속/정지가 다름.

남은 확인: 밸런스 물리 단위와 비주기 운전 시간; 정비/오류별 상태 표시.

### SMC-IZTC41-Lxx-x.zip

근거: [OM_IZT-L_OMZ0045EN-A.pdf](https://static.smc.eu/binaries/content/assets/smc_global/product-documentation/operation-manuals/en/om_izt-l_omz0045en-a.pdf), PDF 페이지 10, 11, 14, 16.

ID581, 4개 CH 이온 상태/초기 설정/밸런스. 출력 유효 bit71과 CH별 명령 구분. 초기 설정·리셋·운전시간 초기화는 일반 수치 설정과 다른 명령.

남은 확인: 입력 16-bit 영역과 10-bit signed 표기 대조; 채널별 초기 설정 상태·명령 처리.

### SMC-EX260-MIL1.zip

근거: [OM_EX260-MIL1_DOC1057882EN.pdf](https://static.smc.eu/binaries/content/assets/smc_global/product-documentation/operation-manuals/en/om_ex260-mil1_doc1057882en.pdf), PDF 페이지 21, 22, 23, 24, 25, 26.

입력1 byte, 매니폴드 규모에 따라 출력4/8/12/16 byte. 32..128개 출력과 단락·구성 변경·카운터·전원 상태를 분리.

남은 확인: 밸브 배치/인스턴스 연결; 비주기 출력 카운터와 진단.

### SMC-EX260-PIL1.zip

근거: [OM_EX260-PIL1_DOC1070047EN-2.pdf](https://static.smc.eu/binaries/content/assets/smc_global/product-documentation/operation-manuals/en/om_ex260-pil1_doc1070047en-2.pdf), PDF 페이지 24, 25, 26, 27.

입력4 또는14/출력3 byte. 5개 센서의 압력 포함 여부가 Device ID에 따름. p24와 p26에서 해당 ID 설명이 반대로 기재되어 충돌.

남은 확인: 압력 PD Device ID 표 충돌; 압력 상하한은 포화 의미이며 정확값과 구분.

### SMC-EX260-SIL1.zip

근거: [OM_EX260-IO-LINK_EN-C.pdf](https://static.smc.eu/binaries/content/assets/smc_global/product-documentation/operation-manuals/en/om_ex260-io-link_en-c.pdf), PDF 페이지 14, 15, 24, 27.

COM2/3와 입력0/2·출력4 byte 조합별 IODD 선택. byte-array 기반으로 센서형 전체 워드 스왑 가정 금지. PD 미포함 상태는 ISDU 상태 조회 후보.

남은 확인: 상위 통신별 바이트 매핑; DIP 설정 수동 일치 확인.

### SMC-EX430-SIL1.zip

근거: [OM_EX430-SIL1_OMY0021EN-A.pdf](https://static.smc.eu/binaries/content/assets/smc_global/product-documentation/operation-manuals/en/om_ex430-sil1_omy0021en-a.pdf), PDF 페이지 15, 24, 27.

ID567..570에 COM2/3, 입력0/2·출력4 byte 조합. byte-array 기반. EX260과 기능 형태가 같아도 식별과 매핑은 별도.

남은 확인: 상위 통신별 바이트 매핑; DIP 설정 수동 일치 확인.

### SMC-EX260-VIL1.zip

근거: [OM_EX260-VIL_OMZ0018EN-B.pdf](https://static.smc.eu/binaries/content/assets/smc_global/product-documentation/operation-manuals/en/om_ex260-vil_omz0018en-b.pdf), PDF 페이지 12, 22, 23, 24.

4/8/12/16연에 입력4/5/6/7·출력2/3/4/5 byte. 압력은 출력에서 선택한 CH 한 개의 값. 0x8000은 이상이며 채널 전환과 수신 시점 일치가 필요.

남은 확인: CH 전환 동기화; 포화·미사용·이상 코드; 비주기 채널별 설정.

### SMC-EX600-TDXx.zip

근거: [OM_EX600-TDX_O-Link_DOC1113170EN-1.pdf](https://static.smc.eu/binaries/content/assets/smc_global/product-documentation/operation-manuals/en/om_ex600-tdx_o-link_doc1113170en-1.pdf), PDF 페이지 15, 26, 27.

TDX1은32점/4 byte, TDX2는16점/2 byte 입력. 핀/채널 배치가 다름. 숫자 게이지 대신 입력 상태 격자에 연결할 대상.

남은 확인: 배열 하위 비트 디코더; 비주기 전원/단락 진단.

### SMC-ISA3-F.zip, SMC-ISA3-G.zip, SMC-ISA3-H.zip

근거: [OM_ISA3-L_OMW0009EN-E.pdf](https://static.smc.eu/binaries/content/assets/smc_global/product-documentation/operation-manuals/en/om_isa3-l_omw0009en-e.pdf), PDF 페이지 91, 92, 93, 94, 95.

거리 가이드 표시와 SUP/OUT 압력을 분리. F/G/H 거리 배율 .02/.1/.2. 압력 음수 범위가 있으나 p91의 부호 설명이 일관되지 않음.

남은 확인: signed 설명 충돌과 IODD 대조; 거리 가이드값의 단위 표현; 비주기 임계값·압력 설정.

### SMC-ISE70_71-L2.zip

근거: [OM_ISE7x-L2_OMV0004EN-J.pdf](https://static.smc.eu/binaries/content/assets/smc_global/product-documentation/operation-manuals/en/om_ise7x-l2_omv0004en-j.pdf), PDF 페이지 62, 63, 64, 65, 66, 70.

unsigned13 압력과 상태 bit3개. ISE70/71 및 단위별 offset 포함 변환. 진단 bit는 F0 설정에 의존.

남은 확인: 비주기 peak/bottom 변환 및 진단 선택.

### ISE7.zip

근거: [OM_ISE70Gx-L2_OMV0009EN-I.pdf](https://static.smc.eu/binaries/content/assets/smc_global/product-documentation/operation-manuals/en/om_ise70gx-l2_omv0009en-i.pdf), PDF 페이지 65, 66, 67, 68, 69.

70G/75G/76G/77G/78G 정격별 압력 계수를 개별 적용. 같은13-bit라고 동일 배율을 사용하지 않음.

남은 확인: 비주기 변환·진단 선택.

### SMC-ISE79G.zip

근거: [OM_ISE79S-L2_MY0007EN-E.pdf](https://static.smc.eu/binaries/content/assets/smc_global/product-documentation/operation-manuals/en/om_ise79s-l2_my0007en-e.pdf), PDF 페이지 63, 64, 65, 66, 67.

ZIP 이름은 ISE79G지만 IODD 모델은 ISE79S. ISE79S 매뉴얼의50 MPa 계수 사용. 패키지명으로 모델을 결정하지 않음.

남은 확인: 비주기 변환·진단 선택.

### SMC-ZSE20B_ISE20B-L.zip

근거: [OM_ZSE20B-L_ISE20B-L_OMU0006EN-H.pdf](https://static.smc.eu/binaries/content/assets/smc_global/product-documentation/operation-manuals/en/om_zse20b-l_ise20b-l_omu0006en-h.pdf), PDF 페이지 76, 77, 78, 79, 80.

양압/진공/연성의 배율과 offset이 다름. 진공 음의 기울기 보존. L/L-P 각각의 조건부 IODD 정의 사용.

남은 확인: 비주기 임계값과 진단 선택.

### ZSE20C-ISE20C-L_IODD.zip

근거: [OM_ZSE20C-L_ISE20C-L_OMX0002EN-F.pdf](https://static.smc.eu/binaries/content/assets/smc_global/product-documentation/operation-manuals/en/om_zse20c-l_ise20c-l_omx0002en-f.pdf), PDF 페이지 66, 67, 68, 69, 70.

ISE20CH 2 MPa를 ISE20C 1 MPa와 구분. 진공/연성 및 단위별 변환을 별도 등록.

남은 확인: 비주기 임계값과 진단 선택.

### SMC-ZSE20B_ISE20B-X101.zip

근거: [PSxx-PSV0007](https://www.smcworld.com/upfiles/_manual/e/PSxx-PSV0007.pdf), PDF 페이지 2, 3, 4, 5, 6, 7, 8, 9.

X101 전용 문서의 ID304/305/306 및2-byte unsigned13 압력 확인. 일반 L형 문서를 대신 적용하지 않음.

남은 확인: 원본 PDF 로컬 다운로드403; 공식 웹 PDF 텍스트로 검토; 비주기 설정 전체 적용.

### SMC-PSE202A.zip

근거: [OM_PSE200A_OMW0012EN-F.pdf](https://static.smc.eu/binaries/content/assets/smc_global/product-documentation/operation-manuals/en/om_pse200a_omw0012en-f.pdf), PDF 페이지 77, 78, 79, 81, 83, 84, 85.

4개 CH signed16 측정값. 각 CH 센서 정격·단위·사용자 범위가 별도이므로 전역 단위 하나로 해석 불가. 진공 계수도 다른 센서와 다름.

남은 확인: CH별 수동 센서 정격·단위·사용자 범위 구성; 계수표 inchHg와 다른 표의 불일치 확인.

### IODD File for PSE54-L.zip

근거: [OM_PSE54_DOC1056909EN-4.pdf](https://static.smc.eu/binaries/content/assets/smc_global/product-documentation/operation-manuals/en/om_pse54_doc1056909en-4.pdf), PDF 페이지 19, 20, 21, 22, 23.

signed16 압력이고 offset0. PSE540/541/543 정격 및 진공의 음의 기울기를 구분. ISE unsigned13 변환 재사용 금지.

남은 확인: 단위 고정/선택 IODD별 표시 조건; 비주기 설정 변환.

### IODD File for PSE57-L.zip

근거: [OM_PSE57_DOC1056914EN-4.pdf](https://static.smc.eu/binaries/content/assets/smc_global/product-documentation/operation-manuals/en/om_pse57_doc1056914en-4.pdf), PDF 페이지 23, 24, 26, 27, 28.

signed16 압력과 정격별 offset0 변환.5 MPa 표시범위 표가 동일 페이지 정격/계수표와 불일치.

남은 확인: 5 MPa 표시범위 불일치 확인; 단위 고정/선택 IODD별 조건; 비주기 설정 변환.

### ZSE10-X148_149.zip

근거: [OM_ZK2-ZB1-ZL3-ZQ_DOC1051887EN-3.pdf](https://static.smc.eu/binaries/content/assets/smc_global/product-documentation/operation-manuals/en/om_zk2-zb1-zl3-zq_doc1051887en-3.pdf), PDF 페이지 20, 21, 22, 23, 24.

입력4/출력2 byte의 진공 제어. 공급/파기 지령과 상태를 구분. p20 unsigned 설명과 음수 예제/표가 충돌하므로 부호 해석 확인 필요.

남은 확인: signed/unsigned 표 충돌; 에너지 절감·밸브 보호·자동 파기 설정.

### SMC-JXCL.zip

근거: [OM_JXCL1_IO-Link_OMV0005EN-D.pdf](https://static.smc.eu/binaries/content/assets/smc_global/product-documentation/operation-manuals/en/om_jxcl1_io-link_omv0005en-d.pdf), PDF 페이지 29, 30, 31, 32, 33, 34, 35, 36, 83.

출력22 byte의 단계/수치 지령. 위치0.01mm와 속도mm/s 등 항목별 단위. 시작 플래그와 데이터 갱신 순서 제약이 있어 일반 쓰기 버튼으로 취급 불가. 입력 14-byte: 현재/목표 위치 0.01 mm, 속도 1 mm/s, 힘 1%. BUSY=OFF라도 밀기 힘 유지 중일 수 있으며 INP 의미는 동작 모드에 따라 다름.

남은 확인: 연결 액추에이터별 스트로크/속도 한계; TriggerLV 단위 표 불일치; 명령 시퀀스와 입력 모니터링.

### EQ-BL_IODD_20250616.zip

근거: [OM_EQ_DOC1138459EN-1.pdf](https://static.smc.eu/binaries/content/assets/smc_global/product-documentation/operation-manuals/en/om_eq_doc1138459en-1.pdf), PDF 페이지 20, 22, 36, 37, 40.

입력4/출력2 byte. 현재 위치0.1mm와 OUT폭0.01mm를 구분. JOG·알람리셋·위치 명령에 운전 조건이 있음.

남은 확인: 액추에이터별 한계와 명령 시퀀스; 비주기 스텝/상태 모니터.

