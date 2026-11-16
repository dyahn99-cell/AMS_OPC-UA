# SMC 공통 장비 라이브러리 — 1단계

제품 정의를 Vendor ID + Device ID로 묶었습니다. 장비 인스턴스 ID·별칭·게이트웨이/CH/Port는 별도 구성으로 유지합니다.
같은 제품 정의와 위젯을 다른 연결 위치에서 재사용할 수 있습니다. 직접 연결 장비는 별도 어댑터 검증이 필요합니다.

## 현황

- products: 215
- definitions: 239
- multiple_revision_products: 24
- uncategorized_products: 0

위젯은 자료형에 따른 후보입니다. 단위·배율·조건을 확인하기 전 자동 연결하거나 쓰기를 허용하지 않습니다.
여러 버전은 보존하며 가장 최근 날짜라는 이유만으로 자동 적용하지 않습니다.

## 제품군별 목록

| 제품군 | 모델 이름 | Device ID | 정의 수 | 위젯 후보 |
|---|---|---:|---:|---|
| D-MH2 | D-MH2C | 675 | 1 | gauge, information, numeric, parameter_select, state_label, structured_inspector, trend |
| D-MH2 | D-MH2D | 676 | 1 | gauge, information, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M701x-xx-L2x-xxx | 366 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M701x-xx-L2x-xxx-X731 | 414 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M701x-xx-L3x-xxx | 367 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M701x-xx-L3x-xxx-X731 | 415 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M701x-xx-L4x-xxx | 368 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M701x-xx-L4x-xxx-X731 | 512 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M701x-xx-Lx-xxx | 365 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M701x-xx-Lx-xxx-X731 | 413 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M702x-xx-L2x-xxx | 370 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M702x-xx-L2x-xxx-X731 | 514 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M702x-xx-L3x-xxx | 371 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M702x-xx-L3x-xxx-X731 | 515 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M702x-xx-L4x-xxx | 372 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M702x-xx-L4x-xxx-X731 | 516 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M702x-xx-Lx-xxx | 369 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M702x-xx-Lx-xxx-X731 | 513 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M705x-xx-L2x-xxx | 374 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M705x-xx-L2x-xxx-X731 | 518 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M705x-xx-L3x-xxx | 375 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M705x-xx-L3x-xxx-X731 | 519 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M705x-xx-L4x-xxx | 376 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M705x-xx-L4x-xxx-X731 | 520 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M705x-xx-Lx-xxx | 373 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M705x-xx-Lx-xxx-X731 | 517 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M710x-xx-L2x-xxx | 378 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M710x-xx-L2x-xxx-X731 | 522 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M710x-xx-L3x-xxx | 379 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M710x-xx-L3x-xxx-X731 | 523 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M710x-xx-L4x-xxx | 380 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M710x-xx-L4x-xxx-X731 | 524 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M710x-xx-Lx-xxx | 377 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M710x-xx-Lx-xxx-X731 | 521 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M711x-xx-L2x-xxx | 390 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M711x-xx-L2x-xxx-X731 | 534 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M711x-xx-L3x-xxx | 391 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M711x-xx-L3x-xxx-X731 | 535 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M711x-xx-L4x-xxx | 392 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M711x-xx-L4x-xxx-X731 | 536 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M711x-xx-Lx-xxx | 389 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M711x-xx-Lx-xxx-X731 | 533 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M721x-xx-L2x-xxx | 572 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M721x-xx-L3x-xxx | 573 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M721x-xx-L4x-xxx | 574 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M721x-xx-Lx-xxx | 571 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M725x-xx-L2x-xxx | 382 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M725x-xx-L2x-xxx-X731 | 526 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M725x-xx-L3x-xxx | 383 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M725x-xx-L3x-xxx-X731 | 527 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M725x-xx-L4x-xxx | 384 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M725x-xx-L4x-xxx-X731 | 528 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M725x-xx-Lx-xxx | 381 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M725x-xx-Lx-xxx-X731 | 525 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M750x-xx-L2x-xxx | 386 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M750x-xx-L2x-xxx-X731 | 530 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M750x-xx-L3x-xxx | 387 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M750x-xx-L3x-xxx-X731 | 531 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M750x-xx-L4x-xxx | 388 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M750x-xx-L4x-xxx-X731 | 532 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M750x-xx-Lx-xxx | 385 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2M7 | PF2M750x-xx-Lx-xxx-X731 | 529 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2MC7 | PF2MC7102-xx-L2x-xxx | 587 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2MC7 | PF2MC7102-xx-L3x-xxx | 588 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2MC7 | PF2MC7102-xx-L4x-xxx | 589 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2MC7 | PF2MC7102-xx-Lx-xxx | 586 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2MC7 | PF2MC7202-xx-L2x-xxx | 591 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2MC7 | PF2MC7202-xx-L3x-xxx | 592 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2MC7 | PF2MC7202-xx-L4x-xxx | 593 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2MC7 | PF2MC7202-xx-Lx-xxx | 590 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2MC7 | PF2MC7501-xx-L2x-xxx | 583 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2MC7 | PF2MC7501-xx-L3x-xxx | 584 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2MC7 | PF2MC7501-xx-L4x-xxx | 585 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF2MC7 | PF2MC7501-xx-Lx-xxx | 582 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF3A7_H | PF3A704H-xx-L3x-xxx | 742 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF3A7_H | PF3A704H-xx-L4x-xxx | 743 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF3A7_H | PF3A704H-xx-Lx-xxx | 741 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF3A7_H | PF3A708H-xx-L3x-xxx | 745 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF3A7_H | PF3A708H-xx-L4x-xxx | 746 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF3A7_H | PF3A708H-xx-Lx-xxx | 744 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF3A7_H | PF3A7R5H-xx-L3x-xxx | 739 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF3A7_H | PF3A7R5H-xx-L4x-xxx | 740 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF3A7_H | PF3A7R5H-xx-Lx-xxx | 738 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF3W-Z-L | PF3W704-LT-X445 | 330 | 1 | gauge, numeric, parameter_select, state_label, trend |
| PF3W-Z-L | PF3W704x-xx-LxT-xxx | 357 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF3W-Z-L | PF3W704x-xx-Lxx-xxx | 352 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF3W-Z-L | PF3W711-LT | 331 | 1 | gauge, numeric, parameter_select, state_label, trend |
| PF3W-Z-L | PF3W711x-xx-LxT-xxx | 360 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF3W-Z-L | PF3W711x-xx-Lxx-xxx | 355 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF3W-Z-L | PF3W720-LT-X445 | 310 | 1 | gauge, numeric, parameter_select, state_label, trend |
| PF3W-Z-L | PF3W720x-xx-LxT-xxx | 358 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF3W-Z-L | PF3W720x-xx-Lxx-xxx | 353 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF3W-Z-L | PF3W721-LT | 332 | 1 | gauge, numeric, parameter_select, state_label, trend |
| PF3W-Z-L | PF3W721x-xx-LxT-xxx | 361 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF3W-Z-L | PF3W721x-xx-Lxx-xxx | 356 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF3W-Z-L | PF3W740-LT-X445 | 317 | 1 | gauge, numeric, parameter_select, state_label, trend |
| PF3W-Z-L | PF3W740x-xx-LxT-xxx | 359 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF3W-Z-L | PF3W740x-xx-Lxx-xxx | 354 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PFCA7 | PFCA710-xx-1x-xxx | 611 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PFCA7 | PFCA710-xx-2x-xxx | 612 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PFCA7 | PFCA711-xx-1x-xxx | 617 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PFCA7 | PFCA711-xx-2x-xxx | 618 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PFCA7 | PFCA725-xx-1x-xxx | 613 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PFCA7 | PFCA725-xx-2x-xxx | 614 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PFCA7 | PFCA750-xx-1x-xxx | 615 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PFCA7 | PFCA750-xx-2x-xxx | 616 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PFUW | PFUW711-L1x-xx | 671 | 1 | gauge, information, numeric, parameter_select, state_label, structured_inspector, trend |
| PFUW | PFUW711-L2x-xx | 672 | 1 | gauge, information, numeric, parameter_select, state_label, structured_inspector, trend |
| PFUW | PFUW711-L3x-xx | 673 | 1 | gauge, information, numeric, parameter_select, state_label, structured_inspector, trend |
| PFUW | PFUW711-L4x-xx | 674 | 1 | gauge, information, numeric, parameter_select, state_label, structured_inspector, trend |
| PFUW | PFUW721-L1x-xx | 760 | 1 | gauge, information, numeric, parameter_select, state_label, structured_inspector, trend |
| PFUW | PFUW721-L2x-xx | 761 | 1 | gauge, information, numeric, parameter_select, state_label, structured_inspector, trend |
| PFUW | PFUW721-L3x-xx | 762 | 1 | gauge, information, numeric, parameter_select, state_label, structured_inspector, trend |
| PFUW | PFUW721-L4x-xx | 763 | 1 | gauge, information, numeric, parameter_select, state_label, structured_inspector, trend |
| PFUW | PFUW760-L1x-xx | 667 | 1 | gauge, information, numeric, parameter_select, state_label, structured_inspector, trend |
| PFUW | PFUW760-L2x-xx | 668 | 1 | gauge, information, numeric, parameter_select, state_label, structured_inspector, trend |
| PFUW | PFUW760-L3x-xx | 669 | 1 | gauge, information, numeric, parameter_select, state_label, structured_inspector, trend |
| PFUW | PFUW760-L4x-xx | 670 | 1 | gauge, information, numeric, parameter_select, state_label, structured_inspector, trend |
| PF3A7_H | PF3A701H-xx-L3x-xxx | 395 | 2 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF3A7_H | PF3A701H-xx-L4x-xxx | 396 | 2 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF3A7_H | PF3A701H-xx-Lx-xxx | 394 | 2 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF3A7_H | PF3A702H-xx-L3x-xxx | 398 | 2 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF3A7_H | PF3A702H-xx-L4x-xxx | 399 | 2 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF3A7_H | PF3A702H-xx-Lx-xxx | 397 | 2 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF3A7_H | PF3A703H-xx-L3x-xxx | 401 | 2 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF3A7_H | PF3A703H-xx-L4x-xxx | 402 | 2 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF3A7_H | PF3A703H-xx-Lx-xxx | 400 | 2 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF3A7_H | PF3A706H-xx-L3x-xxx | 404 | 2 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF3A7_H | PF3A706H-xx-L4x-xxx | 405 | 2 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF3A7_H | PF3A706H-xx-Lx-xxx | 403 | 2 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF3A7_H | PF3A712H-xx-L3x-xxx | 407 | 2 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF3A7_H | PF3A712H-xx-L4x-xxx | 408 | 2 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PF3A7_H | PF3A712H-xx-Lx-xxx | 406 | 2 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| ITV-D | ITV-IL | 537 | 1 | digital_state, gauge, information, numeric, parameter_select, state_label, trend |
| PSH | PSH-L2 | 650 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PSH | PSH-L2 | 728 | 1 | gauge, information, numeric, parameter_select, state_label, structured_inspector, trend |
| PSH | PSH-LL | 729 | 1 | gauge, information, numeric, parameter_select, state_label, structured_inspector, trend |
| FC3W | FC3W504-xx-Lx-xx | 735 | 1 | gauge, information, numeric, parameter_select, state_label, structured_inspector, trend |
| FC3W | FC3W520-xx-Lx-xx | 736 | 1 | gauge, information, numeric, parameter_select, state_label, structured_inspector, trend |
| FC3W | FC3W540-xx-Lx-xx | 737 | 1 | gauge, information, numeric, parameter_select, state_label, structured_inspector, trend |
| IN502 | IN502-44-5/6/13/14 | 575 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| IN502 | IN502-44-7/8/15/16 | 576 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| IN502 | IN502-45-5/6/13/14 | 577 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| IN502 | IN502-45-7/8/15/16 | 578 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| IN502 | IN502-46-5/6/13/14 | 727 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| IN502 | IN502-46-7/8/15/16 | 726 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| IZS51 | IZS51-L | 666 | 1 | gauge, information, numeric, parameter_select, state_label, trend |
| IZT40-41-42 | IZTC41-Lxx-x | 581 | 1 | gauge, numeric, parameter_select, state_label, trend |
| JSY3000-L | EX260-MIL1 | 661 | 1 | digital_state, gauge, information, numeric, parameter_select, state_label, structured_inspector, trend |
| JSY3000-L | EX260-MIL1 | 662 | 1 | digital_state, gauge, information, numeric, parameter_select, state_label, structured_inspector, trend |
| JSY3000-L | EX260-MIL1 | 663 | 1 | digital_state, gauge, information, numeric, parameter_select, state_label, structured_inspector, trend |
| JSY3000-L | EX260-MIL1 | 664 | 1 | digital_state, gauge, information, numeric, parameter_select, state_label, structured_inspector, trend |
| JSY1000E | EX260-PIL1 | 687 | 1 | digital_state, gauge, information, numeric, parameter_select, state_label, structured_inspector, trend |
| JSY1000E | EX260-PIL1 | 688 | 1 | digital_state, gauge, information, numeric, parameter_select, state_label, structured_inspector, trend |
| JSY5000-H | EX430-SIL1_in/out_0/4 byte_COM2 | 568 | 1 | information, parameter_select, state_label, structured_inspector |
| JSY5000-H | EX430-SIL1_in/out_0/4 byte_COM3 | 567 | 1 | information, parameter_select, state_label, structured_inspector |
| JSY5000-H | EX430-SIL1_in/out_2/4 byte_COM2 | 570 | 1 | gauge, information, numeric, parameter_select, state_label, structured_inspector, trend |
| JSY5000-H | EX430-SIL1_in/out_2/4 byte_COM3 | 569 | 1 | gauge, information, numeric, parameter_select, state_label, structured_inspector, trend |
| D-MP | D-MP025 | 293 | 1 | gauge, information, numeric, parameter_select, state_label, structured_inspector, trend |
| D-MP | D-MP050 | 294 | 1 | gauge, information, numeric, parameter_select, state_label, structured_inspector, trend |
| D-MP | D-MP100 | 295 | 1 | gauge, information, numeric, parameter_select, state_label, structured_inspector, trend |
| D-MP | D-MP200 | 296 | 1 | gauge, information, numeric, parameter_select, state_label, structured_inspector, trend |
| D-MPG | D-MPG | 579 | 1 | gauge, information, numeric, parameter_select, state_label, structured_inspector, trend |
| ISA3-L | ISA3-F | 341 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| ISA3-L | ISA3-G | 342 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| ISA3-L | ISA3-H | 343 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| ZSE20(F)-ISE20 | ISE20B-L | 334 | 1 | gauge, numeric, parameter_select, state_label, trend |
| ZSE20(F)-ISE20 | ISE20B-L-P | 335 | 1 | gauge, numeric, parameter_select, state_label, trend |
| ZSE20(F)-ISE20 | ISE20B-T | 304 | 1 | gauge, numeric, parameter_select, state_label, trend |
| ZSE20(F)-ISE20 | ISE20C-L | 554 | 1 | gauge, numeric, parameter_select, state_label, trend |
| ZSE20(F)-ISE20 | ISE20C-L-P | 555 | 1 | gauge, numeric, parameter_select, state_label, trend |
| ZSE20(F)-ISE20 | ISE20CH-L | 560 | 1 | gauge, numeric, parameter_select, state_label, trend |
| ZSE20(F)-ISE20 | ISE20CH-L-P | 561 | 1 | gauge, numeric, parameter_select, state_label, trend |
| ISE70-71-L2 | ISE70 | 307 | 1 | gauge, numeric, parameter_select, state_label, trend |
| ISE70-71-L2 | ISE70G | 309 | 1 | gauge, numeric, parameter_select, state_label, trend |
| ISE70-71-L2 | ISE71 | 308 | 1 | gauge, numeric, parameter_select, state_label, trend |
| ISE70-71-L2 | ISE75G | 320 | 1 | gauge, numeric, parameter_select, state_label, trend |
| ISE70-71-L2 | ISE76G | 321 | 1 | gauge, numeric, parameter_select, state_label, trend |
| ISE70-71-L2 | ISE77G | 322 | 1 | gauge, numeric, parameter_select, state_label, trend |
| ISE70-71-L2 | ISE78G | 362 | 1 | gauge, numeric, parameter_select, state_label, trend |
| ISE70-71-L2 | ISE79S | 594 | 1 | gauge, numeric, parameter_select, state_label, trend |
| PSE200A | PSE202A | 340 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| ZSE20(F)-ISE20 | ZSE20B-L | 336 | 1 | gauge, numeric, parameter_select, state_label, trend |
| ZSE20(F)-ISE20 | ZSE20B-L-P | 337 | 1 | gauge, numeric, parameter_select, state_label, trend |
| ZSE20(F)-ISE20 | ZSE20B-T | 305 | 1 | gauge, numeric, parameter_select, state_label, trend |
| ZSE20(F)-ISE20 | ZSE20BF-L | 338 | 1 | gauge, numeric, parameter_select, state_label, trend |
| ZSE20(F)-ISE20 | ZSE20BF-L-P | 339 | 1 | gauge, numeric, parameter_select, state_label, trend |
| ZSE20(F)-ISE20 | ZSE20BF-T | 306 | 1 | gauge, numeric, parameter_select, state_label, trend |
| ZSE20(F)-ISE20 | ZSE20C-L | 556 | 1 | gauge, numeric, parameter_select, state_label, trend |
| ZSE20(F)-ISE20 | ZSE20C-L-P | 557 | 1 | gauge, numeric, parameter_select, state_label, trend |
| ZSE20(F)-ISE20 | ZSE20CF-L | 558 | 1 | gauge, numeric, parameter_select, state_label, trend |
| ZSE20(F)-ISE20 | ZSE20CF-L-P | 559 | 1 | gauge, numeric, parameter_select, state_label, trend |
| PSE54_ | PSE540 | 677 | 2 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PSE54_ | PSE541 | 678 | 2 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PSE54_ | PSE543 | 679 | 2 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PSE57_ | PSE570 | 680 | 2 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PSE57_ | PSE573 | 681 | 2 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PSE57_ | PSE574 | 682 | 2 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PSE57_ | PSE575 | 683 | 2 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PSE57_ | PSE576 | 684 | 2 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| PSE57_ | PSE577 | 685 | 2 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| EX260 | EX260-SIL1_in/out_0/4 byte_COM2 | 345 | 1 | parameter_select, state_label, structured_inspector |
| EX260 | EX260-SIL1_in/out_0/4 byte_COM3 | 344 | 1 | parameter_select, state_label, structured_inspector |
| EX260 | EX260-SIL1_in/out_2/4 byte_COM2 | 347 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| EX260 | EX260-SIL1_in/out_2/4 byte_COM3 | 346 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| JXCL1-IO | JXCL | 318 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| EX600 | EX600-TDX_DI | 732 | 1 | digital_state, information, parameter_select, state_label, structured_inspector |
| EX600 | EX600-TDX_DI | 733 | 1 | digital_state, information, parameter_select, state_label, structured_inspector |
| ZB, ZGS, ZK2_A, ZL112, ZQ_A | ZSE10-X148/149 | 648 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| ZB, ZGS, ZK2_A, ZL112, ZQ_A | ZSE10F-X148/149 | 649 | 1 | gauge, numeric, parameter_select, state_label, structured_inspector, trend |
| ZKJ | EX260-VIL1 | 596 | 1 | gauge, information, numeric, parameter_select, state_label, structured_inspector, trend |
| ZKJ | EX260-VIL1 | 597 | 1 | gauge, information, numeric, parameter_select, state_label, structured_inspector, trend |
| ZKJ | EX260-VIL1 | 598 | 1 | gauge, information, numeric, parameter_select, state_label, structured_inspector, trend |
| ZKJ | EX260-VIL1 | 599 | 1 | gauge, information, numeric, parameter_select, state_label, structured_inspector, trend |
| EQFS | EQ-IOLINK | 754 | 1 | gauge, information, numeric, parameter_select, state_label, structured_inspector, trend |

## 다음 단계

1. 표준 변수 정의를 결합해 식별·진단 항목을 완성합니다.
2. 조건부 PD, 단위·배율, 복합 항목을 제품군별로 검증합니다.
3. 검증된 항목에 공용 위젯 기본 구성을 연결합니다.
4. 마스터 수동 구성에서 장비 인스턴스와 제품 정의를 연결합니다.
