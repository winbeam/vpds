[매집 시그널 보드 일일 갱신] 예약 실행이다. 사용자는 자리에 없으니 질문하지 말고 끝까지 진행한다.
저장소: {{REPO}}   대시보드: https://claude.ai/artifact/6zWpbQWSqqus2NLvcRBEup

1) 데이터 받기 (Bash)
mkdir -p "$PWD/vpd" && cd "$PWD/vpd" && T=$(date +%s)
curl -fsSL -o latest.json   "https://raw.githubusercontent.com/{{REPO}}/main/results/latest.json?t=$T"
curl -fsSL -o template.html "https://raw.githubusercontent.com/{{REPO}}/main/dashboard/template.html?t=$T"
curl -fsSL -o build.py      "https://raw.githubusercontent.com/{{REPO}}/main/dashboard/build.py?t=$T"
- latest.json의 generated_date_kst가 오늘(Asia/Seoul)이 아니면 report.data_warning에 "오늘 스크리닝 결과가 아직 없어 YYYY-MM-DD 결과를 표시합니다"라고 적는다. errors 배열이나 markets.*.error가 있으면 그 내용도 data_warning에 덧붙인다.
- 받기 자체가 실패하면 분석 없이 마지막 응답으로 실패 원인만 보고하고 끝낸다.

2) 분석 대상: markets.KR.hits, markets.US.hits에서 각각 vol_ratio 상위 최대 8개(이미 내림차순 정렬됨). 나머지 hit는 analysis 없이 둔다. hit가 하나도 없으면 3)을 건너뛴다.

3) 종목별 조사 (WebSearch, 필요하면 WebFetch). 국내는 한국어(종목명 + 뉴스/공시), 미국은 영어(티커·회사명 + news, 8-K, 13D/13G, tender offer)로 검색한다.
- company: 무엇을 하는 회사인지 2~3문장(주력 제품·서비스, 업종, 주요 고객/시장).
- news: 최근 1개월(해당 종목 window_start 이후) 뉴스·공시 최대 4건. 각 {date: YYYY-MM-DD, title, summary: 1문장, source, url}. 검색 결과에서 실제로 확인한 기사·공시만, 확인한 URL 그대로. 날짜를 확인할 수 없으면 넣지 않는다. 없으면 빈 배열.
- 괴리를 설명할 수 있는 이벤트를 우선 확인: M&A·공개매수(가격이 제안가 근처에 묶임), 지수 편입·편출, 블록딜·대주주 지분 매각, 자사주 매입, 유상증자·CB/BW, 보호예수 해제, 5% 대량보유 공시/13D·13G. 확인된 것만 flags에 짧게 적는다(예: "공개매수 진행 중").
- comment.view: 2~3문장. 지표(vol_ratio, price_chg_20d, max_day_share, days_over_2x, range_20d)와 확인된 뉴스로 괴리의 가능한 원인을 해석한다. 매수·매도 권유, 목표가, 수익 전망은 쓰지 않는다. 추정은 "가능성"으로 표현하고 근거를 붙인다. max_day_share ≥ 0.3이면 하루짜리 이벤트 가능성을, days_over_2x ≥ 10이면 지속적 거래 증가를 언급한다.
- comment.watch: 이후 확인할 점 2~3개(예: 대량보유 공시, 외국인·기관 수급, 다음 실적 발표일).
- comment.risks: 1~3개.
- 정확성 원칙: 검증하지 못한 사실은 쓰지 않는다. 모르면 비워 둔다.

4) vpd/analysis.json 작성 (build.py docstring 형식):
{"report":{"generated_at_kst":"YYYY-MM-DD HH:MM","summary":"오늘 결과 2~3문장 요약","data_warning":""},"items":{"KR:티커":{...},"US:티커":{...}}}

5) python3 build.py latest.json analysis.json template.html board.html

6) Artifact 도구로 갱신: 먼저 action "read"로 위 대시보드 URL을 읽고, 이어서 file_path=vpd/board.html의 절대경로, url=위 대시보드 URL로 publish한다(icon 생략). 충돌로 거절되면 같은 파일로 다시 publish한다.

7) 마지막 응답(한국어, 5줄 이내): 국내/미국 탐지 종목 수와 종목명, 눈에 띄는 플래그, 데이터 경고.
