# Polymoly — Polymarket Favorites Backtest

> English and Korean instructions are provided side by side so both teams can
> operate the pipeline without guesswork.

## English Guide

### What this project does
- Implements the favorites strategy described in `1stguide.md` using real
  Polymarket endpoints or the bundled fixtures for offline testing.
- Covers ingestion (Gamma, CLOB, Data API, Goldsky), label generation, feature
  engineering, isotonic calibration, Kelly-style execution, and reporting.
- Ships a minimal CLI (`run_backtest.py`) that can pull live data, run a
  walk-forward backtest, and print calibration and PnL diagnostics.

### Repository layout
```
backtest/               # Cost model, risk controls, walk-forward engine
feature/                # Labeling and feature engineering utilities
ingest/                 # CSV loaders, API client, data bundle assembly
model/                  # Isotonic calibrator with Jeffreys lower bounds
report/                 # Metrics for performance and calibration tables
data/                  # Synthetic fixtures used by the test suite
docs/                  # Mermaid diagrams and operator guides
run_backtest.py         # CLI entry point
```

Sample data schema (mirrors the APIs so code can swap sources easily):

| File | Description |
| ---- | ----------- |
| `gamma_markets_sample.json` | Market metadata including condition id, slug, category, end date, token ids, neg-risk group. |
| `subgraph_resolutions.csv` | Resolution outcome, timestamp, and dispute flag per market. |
| `dataapi_trades.csv` | YES trade history pulled from the Data API with executed price/size. |
| `clob_books.csv` | Order-book snapshots (bid/ask ladder) aligned to trade timestamps. |
| `prices_history.csv` | `/prices-history` extracts for simple momentum and reference features. |

### Getting started
1. **Install dependencies** (Python 3.11+):
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
2. **Run with local fixtures** (fast regression check):
   ```bash
   python run_backtest.py --source local
   ```
3. **Run against live APIs** (requires unrestricted network access):
   ```bash
   python run_backtest.py --source api \
       --start 2024-01-01T00:00:00Z \
       --end 2024-03-31T23:59:59Z \
       --goldsky-url https://<goldsky-endpoint>
   ```
   - `--start/--end` define the historical window for markets, trades, and
     prices; omit them to download the full public history.
   - Provide a Goldsky GraphQL URL to fetch authoritative resolutions; without
     it the client falls back to Gamma metadata and unresolved markets are
     dropped.
   - The client currently reuses a live order book snapshot for every trade per
     market. For production-grade studies schedule a process that archives real
     historical books and replace the synthetic fallback in
     `ingest/data_bundle.py`.

### Tests
- Execute the suite before committing: `pytest -q`
- Tests rely on the fixtures under `data/` and do not hit external APIs.

### Documentation
- `docs/pipeline_overview.md`: visual pipeline walkthrough (Mermaid).
- `docs/data_operations.md`: operator-friendly backfill guide.

### Troubleshooting
- *Gamma or trade download failures*: check network access and Polymarket rate
  limits; rerun with a smaller window.
- *"Failed to download resolution data"*: pass `--goldsky-url` or set the
  `POLYMOLY_GOLDSKY_URL` environment variable.
- *Synthetic books warning*: plan a data-capture job for order books if precise
  slippage modelling is required.

## 한국어 가이드

### 프로젝트 개요
- `1stguide.md`에서 정의한 즐겨찾기 전략을 폴리마켓 공개 API 또는 번들된
  샘플 데이터로 재현합니다.
- 데이터 수집(Gamma, CLOB, Data API, Goldsky), 라벨링, 특징 생성, 아이소토닉
  보정, 켈리 기반 집행, 리포트 생성까지 전 과정을 포함합니다.
- `run_backtest.py` CLI 하나로 실데이터를 당겨와 워크포워드 백테스트를
  수행하고, PnL·칼리브레이션 지표를 출력할 수 있습니다.

### 저장소 구성
```
backtest/               # 비용 모델, 리스크 관리, 워크포워드 엔진
feature/                # 라벨링·피처 엔지니어링 유틸리티
ingest/                 # CSV 로더, API 클라이언트, 데이터 번들 조립
model/                  # 제프리스 하한을 적용한 아이소토닉 보정기
report/                 # 성과·칼리브레이션 요약 지표
data/                   # 테스트용 합성 데이터 묶음
docs/                   # Mermaid 다이어그램과 운영 가이드
run_backtest.py         # CLI 진입점
```

샘플 데이터 스키마(실제 API와 동일한 형태로 구성):

| 파일 | 설명 |
| ---- | ---- |
| `gamma_markets_sample.json` | 마켓 메타데이터: condition id, 슬러그, 카테고리, 종료일, 토큰 id, neg-risk 그룹. |
| `subgraph_resolutions.csv` | 시장별 결제 결과, 타임스탬프, 분쟁 플래그. |
| `dataapi_trades.csv` | Data API에서 추출한 YES 체결 이력(가격·수량 포함). |
| `clob_books.csv` | 체결 시점에 맞춘 호가 스냅샷(매수/매도 스택). |
| `prices_history.csv` | `/prices-history`에서 추출한 모멘텀·레퍼런스용 가격. |

### 시작하기
1. **필수 패키지 설치** (Python 3.11 이상):
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
2. **샘플 데이터로 실행** (빠른 회귀 테스트):
   ```bash
   python run_backtest.py --source local
   ```
3. **실제 API로 실행** (네트워크 접근 필요):
   ```bash
   python run_backtest.py --source api \
       --start 2024-01-01T00:00:00Z \
       --end 2024-03-31T23:59:59Z \
       --goldsky-url https://<goldsky-endpoint>
   ```
   - `--start/--end`는 수집할 히스토리 범위를 지정합니다. 생략하면 전체
     공개 이력을 내려받습니다.
   - 골드스카이 GraphQL URL을 제공해야 확정 결제 정보를 안정적으로 받을
     수 있습니다. 미제공 시 Gamma 메타데이터를 사용하며 미결 시장은 제외됩니다.
   - 현재는 각 토큰당 하나의 실시간 오더북 스냅샷을 모든 트레이드에
     재사용합니다. 정밀 슬리피지 분석이 필요하면 실시간 오더북을 별도
     저장하고 `ingest/data_bundle.py`의 합성 로직을 교체하세요.

### 테스트
- 커밋 전 `pytest -q`를 실행해 파이프라인 연결이 깨지지 않았는지 확인합니다.
- 테스트는 `data/` 내 고정 샘플을 사용하며 외부 API를 호출하지 않습니다.

### 문서
- `docs/pipeline_overview.md`: 전체 파이프라인 흐름과 Mermaid 다이어그램.
- `docs/data_operations.md`: 비개발자용 데이터 백필 가이드.

### 문제 해결
- *Gamma/트레이드 다운로드 실패*: 네트워크 상태와 폴리마켓 레이트 리밋을
  확인하고, 기간을 좁혀서 재시도하세요.
- *"Failed to download resolution data" 메시지*: `--goldsky-url` 옵션을
  지정하거나 `POLYMOLY_GOLDSKY_URL` 환경 변수를 세팅합니다.
- *합성 오더북 경고*: 정밀도가 필요하면 실시간 호가 기록을 별도 파이프라인으로 수집하세요.
