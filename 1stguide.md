각하,

아래 문서는 **“폴리마켓 고확률 즐겨찾기(Favorites)” 전략**을 실제로 **백테스트 → 검증 → 자동화**까지 구현할 수 있도록, \*\*개발자(백엔드/리서처/데브옵스)\*\*와 \*\*기획자(프로덕트/리스크/컴플라이언스)\*\*가 바로 착수할 수준의 \*\*실행 강령(Operating Protocol)\*\*을 포함한 **상세 기획안**입니다.
말 그대로 “코드를 쓰면 돌아가는” 기준으로 설계했습니다. 이 전략의 핵심은 **개별 체결가 단위로 실제 성공확률을 비모수적으로 추정**하고(버킷 평균 회피), **잔여기간·슬리피지·비용까지 반영한 순엣지 기반 랭킹**으로 매수 여부를 결정하는 것입니다.

---

## 0) 한 줄 결론(요지)

* **데이터**: 폴리마켓 CLOB의 **가격 시계열(/prices-history)**, **오더북(/book, /books)**, \*\*트레이드(Data-API)\*\*와 **Gamma/서브그래프(Goldsky)** 메타·결제 정보를 결합해 백테스트용 패널을 구성합니다. ([Polymarket Documentation][1])
* **신호**: “현재 **실제 체결가 p**에서의 **성공확률 $\hat q(p,\tau,x)$**”를 **단조(↑) 제약 Isotonic** + \*\*베타-이항(Jeffreys)\*\*로 추정(하한 사용) → **EV\_LB = LB − p − 비용**이 **양수**이면 후보.
* **집행**: 오더북 VWAP로 **실제 체결가·슬리피지**를 계산하고, **잔여기간 $\tau$** 반영 **연환산 엣지**로 랭킹 → **보수적 켈리 1/2**와 **상관·카테고리 캡**으로 자금 배분.
* **현실 제약**: 폴리마켓은 \*\*거래수수료가 문서상 ‘없음’\*\*이지만, 체결 슬리피지·가스/브리지·기회비용은 반드시 비용 모델에 반영해야 합니다. ([Polymarket Documentation][2])
* **기대값 근거**: 예측시장은 **favorite–longshot bias**가 관찰되나(칼시 대규모 데이터 연구), 시기·플랫폼별 편차가 존재 → **폴리마켓 자체 데이터로 재검증이 필수**입니다. ([University College Dublin][3])
* **정확도 참고치**: 외부 분석 기준 *만기 4시간 전* 가격은 **\~94%** 수준의 칼리브레이션이 보고됨(참고지표, 재현 필요). ([The Defiant][4])

---

## 1) 검증 가능한 가설(통계적 정의)

1. **캘리브레이션 가설**
   시점 $t$, **체결가 $p\in[0.90,1.00)$** 에서 거래된 YES의 **실제 결말 YES 빈도** $q$가 **$p$** 를 **유의하게 초과**하는가? (구간: 0.90–0.95, 0.95–0.99, 0.99–1.00 등)
2. **수익성 가설**
   “**최초 0.90 상향 돌파 시점 체결 → 만기 보유**” 규칙의 \*\*기대수익 $EV=\hat q - p - c$\*\*가 \*\*양(+)\*\*인가? (여기서 $c$=슬리피지+가스/브리지+자본비용)
3. **자본효율 가설**
   **잔여기간 $\tau$** 를 고려한 **연환산 수익률**·소르티노·샤프가 **현금성 금리·SPY·BTC** 대비 우월한가?

> *주의(악마의 변호인)*: 만기 임박 고확률 군집은 \*\*표면 승률↑\*\*이나 **단위 엣지↓**. “이기는 비율”이 아니라 **시간·비용 보정 순엣지**로 평가해야 합니다.

---

## 2) 시스템 아키텍처(데이터·컴퓨팅)

### 2.1 데이터 소스(공식 문서 기반)

* **CLOB 가격 시계열**: `GET /prices-history` (토큰ID별 시계열, interval·fidelity 지원). ([Polymarket Documentation][1])
* **오더북·스프레드**: `GET /book`, `POST /books`, `GET /spread`, `POST /midpoints`. ([Polymarket Documentation][5])
* **실시간 WSS**(선택): 마켓/유저 채널. ([Polymarket Documentation][6])
* **트레이드(히스토리)**: CLOB/데이터 API(비인증 GET)로 전시장 사용자·시장 거래 조회. ([Polymarket Documentation][7])
* **메타·토큰-마켓 매핑**: **Gamma** `GET /markets`(clobTokenIds, umaResolutionStatus, bestBid/Ask 등), CLOB `GET /markets`(token pair, outcome 문자열 포함). ([Polymarket Documentation][8])
* **서브그래프(Goldsky)**: 주문·포지션·활동·OI·PnL 서브그래프(공개 GraphQL 플레이그라운드 제공). ([Polymarket Documentation][9])
* **결제·분쟁·도메인 규칙**: UMA OO/ DVM·결제·이의제기 절차 문서. ([Polymarket Documentation][10])
* **수수료 정책**: “폴리마켓은 **거래 수수료가 없다**(입·출금 포함)” 명시(※ 체결 비용·가스 등은 별도). ([Polymarket Documentation][2])

### 2.2 파이프라인 구성(모듈)

```
ingest/
  gamma_markets_loader.py     # markets 목록·clobTokenIds·메타
  clob_prices_loader.py       # /prices-history 백필·증분
  clob_books_loader.py        # /book(/books) 스냅샷 수집
  dataapi_trades_loader.py    # /trades (Data-API)
  subgraph_resolutions.py     # Goldsky GQL: 활동/포지션/결제 교차 검증
feature/
  make_labels.py              # resolved outcome 결합, 타임컷 적용
  make_features.py            # p, τ, spread, depth, Δp, cat 등
model/
  calibrate_isotonic.py       # p→q̂ 단조 회귀 + 베타-이항 신뢰구간
  gbdt_monotone.py            # (선택) p 단조 제약 GBDT + 캘리브레이션
backtest/
  engine.py                   # 워크포워드 루프, 체결/슬리피지, 포트폴리오
  cost_model.py               # 가스/슬리피지/캐시드래그
  risk.py                     # 켈리/익스포저 캡/상관 캡
report/
  metrics.py                  # 월별 PnL, MDD, 샤프, 카테고리 분해
  plots.py                    # 칼리브레이션 곡선, 손익분해
```

**데이터 스토리지(제안)**: PostgreSQL(OLTP) + Parquet(OLAP). 핵심 테이블:

* `markets(condition_id PK, slug, category, end_date, uma_status, clob_token_yes, clob_token_no, neg_risk_group, ... )` ([Polymarket Documentation][8])
* `prices(token_id, ts, price)` — `/prices-history` 원천. ([Polymarket Documentation][1])
* `books(token_id, ts, side, level, price, size)` — `/book(s)` 스냅샷. ([Polymarket Documentation][5])
* `trades(market, token_id, ts, price, size, maker/taker, ...)` — Data-API. ([Polymarket Documentation][7])
* `resolutions(condition_id, resolved_outcome, resolve_ts, dispute_flag, ...)` — 서브그래프/Gamma 결합. ([Polymarket Documentation][9])

---

## 3) 신호 설계(“개별 체결가” 접근, 버킷 평균 배제)

### 3.1 의사결정 식

* **절대 엣지**: $\displaystyle EV = \hat q(p,\tau,x) - p - c$
* **시간 보정**: $\displaystyle R_{\text{ann}} \approx (1 + EV/p)^{365/\tau_{\text{day}}} - 1$
* **켈리 분수(보수적)**: $\displaystyle f^\* = \frac{\hat q - p}{1 - p}$, 집행은 **$ \min(\lambda \cdot f^\*, f_{\max})$**, $\lambda\in[0.3, 0.5]$.

### 3.2 $\hat q(p,\tau,x)$ 추정(비모수·단조 제약)

1. **Isotonic Regression**(필수):

* **가격 p 단조(↑)** 제약을 강제.
* **잔여기간 $\tau$** 별로 곡선 분리(예: 0–1d, 1–3d, 3–7d, 7–30d, >30d).
* 스무딩은 **등빈(beta-binning) + 커널**로 희박구간 안정화.

2. **불확실성 반영(베타-이항)**:

* 구간별 성공/실패 $(s,n)$에서 **Jeffreys prior $\alpha=\beta=0.5$** 적용.
* \*\*하한(LB, 95%)\*\*을 사용: $\text{EV}_{LB} = LB - p - c$ > $\delta>0$ 일 때만 진입.

3. **미세구조/메타 특성 $x$**(선택):

* 스프레드·심도(최우선/누적), 오더불균형, 최근 $\Delta p$·변동성, 카테고리(정치/스포츠/크립토), 네그리스크 여부. ([Polymarket Documentation][5])
* **GBDT(단조 제약: p 양의 단조)** → 후단 Isotonic/Platt로 확률 보정.

> *비유*: **T-bill 롤다운**처럼, 만기 가까운 **\$0.99 채권**을 폭넓게 사서 **\$1.00로 수렴**하는 연소득을 모으되, **테일=0**인 사건을 분산으로 희석.

---

## 4) 체결·비용 모델(현실 오버레이)

* **실제 체결가**: 목표 수량 $Q$에 대해 오더북 **최우선 호가부터 누적**해 **VWAP $p_f(Q)$** 계산. `GET /book(s)`로 레벨·잔량 확보. ([Polymarket Documentation][5])
* **슬리피지 함수**: $(Q, p_f(Q)-\text{best\_ask}))$를 회귀화하여 **주문크기→비용** 맵핑.
* **수수료**: 문서상 **거래 수수료 없음**(입·출금 포함). 단, **가스/브리지/자본비용**·약정률(캐시 드래그) 포함. ([Polymarket Documentation][2])
* **결제 리스크**: UMA OO/챌린지 대기·분쟁 지연(향후 Chainlink 표준 통합 소식 참고) → 만기/결제 시차의 **현금성 수익 상실** 반영. ([Polymarket Documentation][10])

---

## 5) 백테스트 스펙(워크포워드, 정보누출 방지)

### 5.1 데이터 컷오프

* **진입 시각 (t^\*)** 이후의 모든 정보(가격/북/트레이드/뉴스)는 **금지**.
* \*\*라벨(결과)\*\*은 **해결 시점 이후**에만 결합.

### 5.2 시나리오 매트릭스

* **진입 임계값**: 0.85/0.90/0.92/0.95/0.97/0.99
* **잔여기간 필터**: 제한 없음 / ≥7d / ≥3d / 0–1d only
* **유동성 필터**: 스프레드 ≤1틱, 책 깊이 ≥ 주문수량×$k$, 일평균 체결량 상위 X%
* **중복·상관 제거**: 동일 **negRisk/event/group**은 **1건만** 선택. ([Polymarket Documentation][11])

### 5.3 워크포워드 루프(의사코드)

```python
for month in timeline:             # 롤링 OOS
    fit_window = last_12_months_before(month.start)
    model = fit_isotonic(data_in(fit_window))        # p→q̂, τ별
    for trade in entrants_in(month):                 # t* 시점 후보
        p_vwap = vwap_from_book(trade.token_id, trade.size, t=trade.t*)
        q_lb   = beta_isotonic_lb(model, p_vwap, tau=trade.tau, x=trade.micro)
        ev_lb  = q_lb - p_vwap - cost_model(trade)
        if ev_lb > delta and liq_filters_ok(trade):
            size = kelly_fraction(q_lb, p_vwap) * nav
            execute_virtual_fill(trade, size, price=p_vwap)
    mark_to_resolve()   # 결제 후 PnL 인식
    risk_controls.roll()  # 이벤트/카테고리/상관 캡 적용
```

### 5.4 성과·리스크 지표

* **절대/연환산 수익률**, 월별 PnL, **MDD**, 샤프/소르티노/칼마.
* **칼리브레이션 곡선**: 가격 버킷별 실제 빈도 vs 대각선(=완전 칼리브레이션).
* **카테고리 분해**(정치/스포츠/크립토) 및 **클러스터 부트스트랩**(동일 사건 변주 묶음).

---

## 6) “실행 강령(Operating Protocol)” — 트레이딩 규율

1. **진입**

   * **규칙 A(기본)**: **최초 0.90 상향 돌파** 시점 체결가 $p_f$에서 후보 생성.
   * **규칙 B(동적)**: 유동성·스프레드 양호 시 0.88까지 허용, 열악 시 0.95로 상향.
2. **랭킹 & 필터**

   * 1차: **$EV_{LB} > 0$**, 2차: **$R_{\text{ann},LB}$** 또는 **$f^\*_{LB}$** 내림차순.
   * **오더북 기반 체결 가능성**(깊이·TWAP) 필터 통과 필수.
3. **자금 배분**

   * **켈리 1/2**, **이벤트당 ≤1.5%**, **카테고리 캡(예: 정치 ≤25%)**, **negRisk 그룹 캡**. ([Polymarket Documentation][11])
4. **리스크 컷**

   * **스톱 없음(만기 보유)** 원칙.
   * 단, **판정 리스크 플래그**(모호한 결제 근거/빈번한 정정) 발생 시 **익스포저 축소**. ([Polymarket Documentation][10])
5. **조기 청산(옵션)**

   * $p \ge 0.995$ 도달 시 **프리미엄 확정** 후 자본 회전.

---

## 7) 개발 상세(엔드포인트·예시·스키마)

### 7.1 마켓/토큰 매핑(Gamma ↔ CLOB)

* \*\*Gamma `GET /markets`\*\*에서 `clobTokenIds`, `umaResolutionStatus`, `bestBid/Ask` 등 확보. ([Polymarket Documentation][8])
* \*\*CLOB `GET /markets`\*\*에서 각 마켓의 \*\*Token\[2] (YES/NO)\*\*와 `token_id`–`outcome` 매핑 확보. ([Polymarket Documentation][12])

> **예시(개략)**
> `GET https://gamma-api.polymarket.com/markets?closed=true&limit=1000` → `conditionId`, `clobTokenIds`, `umaResolutionStatus`. ([Polymarket Documentation][8])

### 7.2 가격 시계열

* `GET https://clob.polymarket.com/prices-history?market=<token_id>&interval=1h&fidelity=1` (또는 `startTs/endTs`). 응답 `{history:[{t, p}]}`. ([Polymarket Documentation][1])

### 7.3 오더북/중간가/스프레드

* `GET /book?token_id=...`, `POST /books`, `POST /midpoints`, `GET /spread`. VWAP 계산의 입력. ([Polymarket Documentation][5])

### 7.4 트레이드(증거·깊이 보조)

* **Data-API** `GET https://data-api.polymarket.com/trades?...`(비인증, 전시장). ([Polymarket Documentation][7])

### 7.5 서브그래프(해결·포지션·OI·PnL 교차 검증)

* Goldsky 호스팅된 **Orders/Positions/Activity/OI/PNL** 서브그래프 GraphQL 엔드포인트 사용. (문서에 각 URL 제공) ([Polymarket Documentation][9])

---

## 8) 코드 뼈대(핵심 함수 설계)

```python
# 체결가 추정: 오더북 VWAP
def vwap_from_book(levels, qty):
    filled, cost = 0, 0.0
    for price, size in levels:  # best_ask부터 오름차순
        take = min(size, qty - filled)
        cost += take * price
        filled += take
        if filled >= qty: break
    assert filled == qty, "유동성 부족"
    return cost / filled

# Isotonic + Jeffreys 하한
def beta_lower_bound(success, total, alpha=0.5, beta=0.5, cl=0.95):
    # 베타분포 하한 분위수 계산(구현 or 라이브러리)
    ...

def qhat_isotonic(p_list, y_list):   # y∈{0,1}, τ 버전은 곡선 다중 학습
    iso = IsotonicRegression(y_min=0, y_max=1, increasing=True).fit(p_list, y_list)
    return iso

# 랭킹 스코어
def edge_scores(p_fill, tau, x, model, cost):
    q_mean = model.predict(p_fill, tau, x)
    q_lb   = beta_lower_bound(... near (p_fill, tau) bucket ...)
    EV_lb  = q_lb - p_fill - cost
    R_ann  = ((1 + EV_lb/p_fill)**(365/tau_days)) - 1
    f_star = max(0.0, (q_lb - p_fill)/(1 - p_fill))
    return EV_lb, R_ann, f_star
```

---

## 9) 검증·리포팅

* **리포트 템플릿**: 월간 팩트시트(수익률, 변동성, 소르티노, MDD, 승률, 체결·슬리피지, 잔고회전율, 카테고리·이벤트 분해).
* **칼리브레이션 대조**: *만기 1M/1W/1D/4h 전* 예측 정확도 곡선(외부 지표 90%/94% 대비). ([The Defiant][4])
* **벤치마크**: 현금성 금리, SPY, BTC와 동기간 비교(연환산·변동성 조정).

---

## 10) 품질·리스크 관리(Devil’s Advocate 포함)

* **제로섬·용량**: 얇은 호가에서 규모를 키우면 우리 주문이 가격을 끌어올려 **엣지 소멸**.
* **동시 붕괴**: 정치/거시 이벤트 동시 변동 → **동상관 MDD 확대**.
* **판정 리스크**: **UMA OO**의 분쟁/정정·모호한 부속문구(ancillary data) 위험. **결제 지연**은 자본비용. ([Polymarket Documentation][10])
* **정책 변화**: 결제 스택(예: Chainlink 표준 통합) 변화 시 **정책·지연·데이터 정의** 재점검 필요. ([The Defiant][13])
* **가설 약화**: 즐겨찾기 편향은 공개·채굴되면 약화될 수 있음(칼시 연구 참조). ([University College Dublin][3])

---

## 11) 기획·컴플라이언스 주의

* **ETF 상장 구조**: 현행 규제·자산성격(베팅/암호화)상 **정규 ETF는 현실적으로 곤란**. MVP는 **온체인 볼트(ERC‑4626)** 또는 **사모 운용노트**가 현실적.
* **내부통제**: 전략 파라미터(임계값/캡/리스크 규율) 변경 시 **변경로그·사전 승인** 필수.
* **시장 룰 숙지**: “가격=확률” 표준 설명, 분쟁/50-50 등 특수 결제 케이스. ([Polymarket Documentation][14])

---

## 12) 납품 산출물(Deliverables) & 수용 기준(Acceptance)

**필수 산출물**

1. **데이터 백필 스크립트**: Gamma `GET /markets`, CLOB `/prices-history`, `/book(s)`, Data-API `/trades` 수집 + 스키마에 적재. ([Polymarket Documentation][8])
2. **라벨러**: 결제·결과 조인(서브그래프/Gamma 교차검증) + 타임컷 적용. ([Polymarket Documentation][9])
3. **모델**: Isotonic + Jeffreys 하한 추정기(τ-버킷), 선택적 GBDT(단조).
4. **백테스트 엔진**: 워크포워드 + VWAP 체결 + 비용 모델 + 리스크 캡.
5. **리포트**: 칼리브레이션 곡선, 월별 손익, 카테고리 분해, 용량·슬리피지 분석.

**수용 기준**

* (정합성) 임의 샘플 30개 시장의 **체결가·오더북 재현** 오차 ≤ 1틱.
* (통계) OOS 칼리브레이션 곡선의 **Brier Score**가 **동기간 단순 p=mid** 대비 개선.
* (리스크) 이벤트/카테고리/negRisk 캡이 엔진에서 **강제**되는지 단위테스트 통과.
* (재현성) 전체 파이프라인 **원클릭 재실행**으로 동일 결과 재현(시드 고정).

---

## 13) 운영 체크리스트(착수 당일 바로 수행)

* [ ] **Gamma `GET /markets`** 풀덤프(최근 24–36개월), `clobTokenIds`, `umaResolutionStatus`, `closed`, `endDateIso`. ([Polymarket Documentation][8])
* [ ] 각 **token\_id**에 대해 **`/prices-history`** 백필(시간해상도: 1m/5m/1h 3종). ([Polymarket Documentation][1])
* [ ] 주요 시장 **`/book(s)`** 스냅샷 수집(최소 5레벨), VWAP 함수 검증. ([Polymarket Documentation][5])
* [ ] **Data-API `/trades`** 샘플링 수집(깊이/체결 가능성 보조). ([Polymarket Documentation][7])
* [ ] \*\*서브그래프(Goldsky)\*\*로 포지션/해결 교차 확인(스키마 확인). ([Polymarket Documentation][9])
* [ ] **타임컷 유효성 테스트**(정보누출 탐지 유닛테스트).
* [ ] **Isotonic + Jeffreys**로 p→q̂ 곡선 학습(τ-버킷).
* [ ] **워크포워드** 2023–2024 학습 / 2025 검증 루프 실행.
* [ ] **리포트** 생성 및 벤치마크 대비.

---

## 14) 부록 — 참조 쿼리/엔드포인트

* **Gamma Markets**
  `GET https://gamma-api.polymarket.com/markets?closed=true&limit=1000`
  (응답 필드: `conditionId`, `clobTokenIds`, `bestBid`, `bestAsk`, `umaResolutionStatus` 등) ([Polymarket Documentation][8])
* **CLOB Markets(토큰 페어)**
  `GET https://clob.polymarket.com/markets?next_cursor=` (응답: Token\[2]{token\_id, outcome}) ([Polymarket Documentation][12])
* **Prices History**
  `GET https://clob.polymarket.com/prices-history?market=<token_id>&interval=1h` ([Polymarket Documentation][1])
* **Order Book(s)**
  `GET /book?token_id=...`, `POST /books`(배치) ([Polymarket Documentation][5])
* **Midpoints/Spread**
  `POST /midpoints`, `GET /spread` ([Polymarket Documentation][15])
* **Trades(Data-API)**
  `GET https://data-api.polymarket.com/trades?limit=...` ([Polymarket Documentation][7])
* **Subgraph(Goldsky)**
  문서의 공개 GraphQL 플레이그라운드 URL 사용(Orders/Positions/Activity/OI/PNL). ([Polymarket Documentation][9])
* **결제/분쟁 규정**
  UMA OO·DVM 연동 및 결제·디스퓨트 가이드. ([Polymarket Documentation][10])
* **수수료 정책**
  “폴리마켓은 거래 수수료 없음(입/출금 포함)” FAQ. ([Polymarket Documentation][2])
* **정확도 레퍼런스**
  1M 전 \~90%, 4h 전 \~94% 분석 기사(참고지표). ([The Defiant][4])

---

## 15) 마무리 — 각하께 드리는 냉정한 권고

* **핵심은 “버킷 평균”이 아니라 “개별 체결가”입니다.** 각 체결에서의 $p$·$\tau$·미세구조 $x$로 \*\*$\hat q$\*\*를 직접 추정하고, **EV 하한 기준**으로만 진입하십시오.
* **정확도는 시점 의존**입니다. *만기 임박*에서의 칼리브레이션이 높다고 해서 **수익성이 자동 보장되진 않습니다**(슬리피지·용량·자본비용).
* **첫 단계 목표는 ‘진짜 알파가 있는가’의 판정**입니다. **워크포워드** + **용량 시뮬**로 **현실 수익률**을 따져보고, 살아 있다면 그때 **온체인 볼트(ERC‑4626) MVP**로 확장하십시오.

필요하시면, 각하. 위 스펙에 맞춘 **초기 리포지터리(스키마/로더/엔진/리포트)** 골격과 **샘플 스크립트**를 바로 드리겠습니다.
과대해석을 경계하고, **데이터가 말하게** 하겠습니다.

[1]: https://docs.polymarket.com/api-reference/pricing/get-price-history-for-a-traded-token "Get price history for a traded token - Polymarket Documentation"
[2]: https://docs.polymarket.com/polymarket-learn/FAQ/is-polymarket-the-house "Is Polymarket The House? - Polymarket Documentation"
[3]: https://www.ucd.ie/economics/t4media/WP2025_19.pdf?utm_source=chatgpt.com "The Economics of the Kalshi Prediction Market"
[4]: https://thedefiant.io/news/research-and-opinion/polymarket-is-up-to-94-accurate-in-predicting-outcomes-analysis?utm_source=chatgpt.com "Polymarket is Up to 94% Accurate In Predicting Outcomes"
[5]: https://docs.polymarket.com/developers/CLOB/prices-books/get-book?utm_source=chatgpt.com "Get Book"
[6]: https://docs.polymarket.com/developers/CLOB/websocket/wss-overview?utm_source=chatgpt.com "WSS Overview"
[7]: https://docs.polymarket.com/developers/CLOB/trades/trades-data-api?utm_source=chatgpt.com "Get Trades (Data-API)"
[8]: https://docs.polymarket.com/developers/gamma-markets-api/get-markets "Get Markets - Polymarket Documentation"
[9]: https://docs.polymarket.com/developers/subgraph/overview "Overview - Polymarket Documentation"
[10]: https://docs.polymarket.com/developers/resolution/UMA?utm_source=chatgpt.com "Resolution"
[11]: https://docs.polymarket.com/developers/neg-risk/overview?utm_source=chatgpt.com "Overview - Polymarket Documentation"
[12]: https://docs.polymarket.com/developers/CLOB/markets/get-markets?utm_source=chatgpt.com "Get Markets"
[13]: https://thedefiant.io/news/defi/polymarket-taps-chainlink-to-settle-price-bets?utm_source=chatgpt.com "Polymarket Taps Chainlink to Settle Price Bets"
[14]: https://docs.polymarket.com/?utm_source=chatgpt.com "Polymarket Documentation: What is Polymarket?"
[15]: https://docs.polymarket.com/developers/CLOB/prices-books/get-midpoint?utm_source=chatgpt.com "Get Midpoint(s)"
