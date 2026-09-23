## Commonality 분석 

### 정의
: 수율 변화, fab parameter 중심값, 산포변화,defect 등 예측과 다른 결과가 나왔을 때, 양호와 불량 그룹을 정의하고 data 분석을 통해 각 집단간의 공정 path나 parameter 차이점을 찾아 불량 원인을 규명하는 활동 -> 불량 유발 원인을 찾아 멈추는 활동 

### 기본 FLOW
1. **Test issue 파악** : dut성, 가로줄성, test 장비/card 의존성 
2. **Map 특징 파악** : 불량 이름 지정, area 성 파악, fail bin trend 변동 파악 
    - 주의점 
        - map 유형에 의한 선입견 배제 
        - area 성 내 bin 변화 파악 (hard성 only 또는 hard성 + margin성 혼재여부) 
    - 특징별 불량 
        - random vs area 
        - 가로줄성, 세로줄성, shot성, sanding 주기성, dut성 
        - 환형, middle 환형, edge, center성, 우상단, 좌상단 
        - 회오리, 바람개비, 방사형 
        - 특정 모양을 지칭하기 위해 사용된 용어 : 그뭄달, 두루미, 환풍기, 야구공, 부분일식, 모래성, 호빵, 검버섯, 빗살, 횃불, 두눈, 부메랑, 구슬 등 - 좌우 대칭 vs 비대칭 - 규칙적, 반복적 area성 vs 불규칙 area성 
3. **양호/불량의 정의** : 양불 lot/wafer 구분, 대용특성 파악 
    - 불량 구분 
        - 불량 vs 양호 
        - 약불 vs 강불 vs 중불 
        - 양/불 chip, shot, wafer, lot, batch 
        - 수치화할 수 있는 불량, 할 수 없는 불량 
        - 낱장 불량 
        - eds, et, cd/thickness/profile 불량, 산포불량 
        - visual, non-visual 불량 
        - spec in, spec out 불량 (기존 경향을 벗어나는 lot이 불량일 가능성 높음) 
    - 양호/불량 구분 기준 명확히 : 양호와 불량을 정확히 구별할 수 있다면 절만은 성공 
    - 불량 정도 수치화 : 양불 구분보다 불량 정도 수치 표현이 훨씬 유리 
    - 불량 정도 수치화 안될 땐 가능한 대용 특성 찾는다 (cd, et, thickness 등) 
    - 수치화, 대용특성 둘 다 안되면 최대한 구별하여 그룹화 (약불, 중불, 강불) 
    - 전체 wafer 불량률에 변동을 주지 않는 작은 area성 불량 경우 단순 양불 wafer구분 뿐만 아니라 위치와 각도에 따른 불량 구분 
4. **Fab 이력 분석** : 이력 파악, fab comment, ein/ecn, 불발통, 이발통, split 이력 
5. **규칙성 분석** : 주기성, 반복성, 상/하향성 
    - lot 내 wafer간 주기성 발생 가능 케이스 
        - multi ch : dry eytch, peox, hdp, photo, barrier metal, scrubber 
        - 1ch multl wafer : ashing, fsd - 일명 땅콩 ch 
        - 1ch multi chuck or multi head : WSi, cmp 
        - wafer 로딩 순서에 의한 주기성 : diff 5주기 
        - tkin/out시 wafer 회전에 의한 주기성 : etch 후 언로딩 시 두 방향으로 
        - wet clean 시 lot 간 wafer병 마주보는 타입의 장비 
    - fail률의 주기성 
        - 2,3,4주기 
    - measure 값에서 주기성 
        - eds fail률만 보고 판단하년 주기성 측징 파악 못할 수 있음, measure값 검토 가능시 반드시 확인 
    - 주기성 위반 케이스 : 주기성의 규칙이 일시적으로 틀어졌을 때 결정적 단서가 될 수 있음 
    - eds 맵 내 주기성 - lot 내 특정 wafer에서만 발생 
6. **기조 조사** : cd, thickness, et, eqp, ch 
    - cd, thk, et : 반드시 trend 상에서 데이터검토 
        - 기존 트렌드 벗어나는지 
        - 트렌드 상 중심치, 산포 등의 변경점의 시작이 불량 lot인지 
        - 알수없는 원인으로 인해 중심치가 이동하여 타겟에 근접하거나 산포가 좋아져도 주의 
    - ch분석 
        - 특정 ch 불량 trace시 전후 lot을 확인할 경우 그 ch의 실제 사용 여부 확인 
        - 숨은 ch 주의 (barrier metal) 
        - 특정 ch 직전 진행lot 주의 
    - zone별 유의차 분석 
        - zone은 절대위치가 아닌 상대적 개념으로 판단 
        - 윗쪽에 놓은 lot의 영향을 받을 경우 특정 zone과 매칭되지 않음 
    - 장비별 유의차 
        - 가장 기본적 유의차 분석 
        - 불량 설비에서도 양호 나올 수 있음 
        - 불량 설비에하도 전후 랏이 양호일 수 있음 
        - 동일 장비라도 직전 lot이 무엇인지, 연속진행 비연속진행에 따라 전혀 다른 설비 컨디션 
        - 장비별 차이 분석, 장비군별 차이분석, ppid 변경점 분석 
7. **정체 시간** 
    - 정체시간 
        - lot내 step간 정체시간 비교 
        - 특정 설비에서 전후 lot 간 정체 시간 비교 (연속 비연속 차이점) 
        - wafer간 process time 또는 정체시간 비교 
        -> wafer no상 앞뒤간 선형적인 감소, 증가 또는 앞 장 몇매만 불량일 경우 동일 설비네 lot간 연속/비연속 진행 이력과 관련될 관련될 가능성 큼 
    - 현재 관리대상이 아닌 공정, 스텝이 원인 가능상 높음 
    - 과거 동일 수준 정체lot과 비교 지양 
    - tkin ~ process 시작 동안 상당시간 대기하는 경우 많음 
    - 타 lot 대비 공정시간이 길거나 짧은 lot 주목 (wafer 매수 고려) 
    - 각 lot 별 계측에 걸리는 time 비교가 문제 실마리인 경우 있음 
    - 각 wafer 별 정체시간, process time 분석은 저수율 분석 trace 시 매우 결정적인 단서 종종 제공 
8. **원자재**
    - pr, thinner 등 특정 lot/bottle 불량 : 동일 유형의 불량이 다수 장비에서 동시에 나타나는 경우 
    - wafer vendor : 동일 공당에서 특정 vendor에만 
9. **Input parameter** 
    - input parameter : 관리항목이 아니거나 spec 이내 변동과 관련될 가능성 큼 
    - 분석포인트 
        - wafer 별 process, 정체시간 분석 
        - fdc erd trend : 낱장 분석, 또는 불량 장비에서 양불 lot 공존 시 유용 
        - parts 교치 주기 : 장비간 차이 없으나 교체주기에 따른 양불 사이클 
        - pm 주기에 따른 불량 
10. **정황분석** : 특이한 상황에 발생 
    - 특정 상황이서만 발생하는 불량 
    - 대표사례 
        - diff 상위 zone의 특정 lot 영향성 
        - 특정 제품 혹은 특정 공정 직후 lot에서 불량 
        - wet 공정 시 동일 batch lot과의 영향성 
        - 특정한 이력을 가진 lot에서의 불량 (full map dc 측정) 
        - 설비 idle 상태 후 첫 lot에서의 불량 (연속, 비연속) 
        - 제품군 변경 후 첫째 lot에서의 불량 - 특정 event 직후 발생 (호빵) 
11. **빈도분석** 
    - 특정 장비가 다수 step에서 불량을 일으키는 분석 (step,eqp 별 commonality 분석으로 원인 찾기 어려운 케이스)