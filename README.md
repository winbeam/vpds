# 매집 시그널 보드 (Volume–Price Divergence Screener)

거래량은 크게 늘었는데 주가는 거의 움직이지 않은 종목을 매일 찾아냅니다.

| 항목 | 내용 |
|---|---|
| 조건 ① | 최근 20거래일 평균 거래량 ≥ 직전 60거래일 평균 거래량 × 3 |
| 조건 ② | 최근 20거래일 종가 변동(20거래일 전 종가 대비) ±3% 이내 |
| 국내 대상 | KOSPI200 + KOSDAQ150 (KRX 계정 미설정 시 [FinanceData/marcap](https://github.com/FinanceData/marcap) 기준 시가총액 상위 200/150으로 근사, 우선주·스팩·리츠 제외) |
| 미국 대상 | S&P500 + Nasdaq-100 |
| 가격 데이터 | Yahoo Finance(yfinance), 국내 누락분은 marcap(KRX 일별 시세)로 보완 |
| 미국 구성종목 | Wikipedia(S&P500), Nasdaq-100은 Wikipedia → Nasdaq API 순으로 시도, 실패 시 S&P500만 스캔 |

## 동작 흐름

1. **06:20 KST** GitHub Actions가 `screener.py`를 실행하고 `results/latest.json`을 커밋
2. **07:00 KST** Claude 예약 작업이 결과를 읽고, 탐지 종목별 기업 개요·최근 1개월 뉴스·투자 코멘트를 작성
3. `dashboard/build.py`로 HTML을 만들어 claude.ai 대시보드(고정 URL)를 갱신

## 설정 방법

1. GitHub에서 **Public** 저장소를 새로 만듭니다 (예: `vpd-screener`).
   Claude 작업 환경은 `raw.githubusercontent.com`만 읽을 수 있어 공개 저장소여야 합니다. 저장소에는 시세 계산 결과만 올라갑니다.
2. 이 폴더의 파일을 구조 그대로 업로드합니다.
   ```
   .github/workflows/screen.yml
   screener.py
   requirements.txt
   dashboard/template.html
   dashboard/build.py
   README.md
   ```
3. 저장소 **Settings → Actions → General → Workflow permissions**에서 **Read and write permissions**를 선택합니다 (결과 커밋용).
4. **Actions** 탭 → `volume-price-divergence-screen` → **Run workflow**로 한 번 수동 실행해 `results/latest.json`이 생기는지 확인합니다.
5. (선택) 실제 KOSPI200/KOSDAQ150 구성종목을 쓰려면 KRX 데이터포털(data.krx.co.kr) 계정을 **Settings → Secrets and variables → Actions**에 `KRX_ID`, `KRX_PW`로 등록합니다. 없으면 시가총액 상위 종목으로 근사합니다.
6. Claude 예약 작업(매일 07:00 KST)이 `claude_daily_prompt.md` 내용으로 실행됩니다.

## 참고

- 일요일·월요일 아침에는 새 거래일이 없어 전날과 같은 결과가 나올 수 있습니다.
- GitHub Actions 예약 실행은 부하에 따라 수십 분 늦게 시작될 수 있습니다. 07:00 분석 시점에 당일 결과가 없으면 대시보드 상단에 경고가 표시됩니다.
- 거래량-가격 괴리는 매집 외에도 M&A·공개매수, 지수 편입·편출, 블록딜, 자사주 매입 등으로 생길 수 있습니다. 투자 권유가 아닌 참고 자료입니다.
