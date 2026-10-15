"""Volume-Price Divergence screener (거래량-가격 괴리 매집 의심 종목 탐지)

조건
  ① 최근 20거래일 평균 거래량 / 직전 60거래일 평균 거래량 >= 3.0
  ② 최근 20거래일 종가 변동률(20거래일 전 종가 대비) |chg| <= 3%
대상
  KR: KOSPI200 + KOSDAQ150 (KRX 계정 없으면 시가총액 상위 200/150 근사)
  US: S&P500 + Nasdaq-100
출력
  results/latest.json, results/history/YYYY-MM-DD.json (KST 기준 날짜)
"""
from __future__ import annotations

import io
import json
import math
import os
import re
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import requests
import yfinance as yf

RECENT = 20          # 최근 구간(거래일)
BASE = 60            # 비교 구간(거래일)
VOL_MULT = 3.0       # 거래량 배수 기준
PRICE_BAND = 0.03    # 가격 변동 허용폭 (±3%)
NEAR_VOL_MULT = 2.0  # 근접 후보(참고용) 거래량 배수
MAX_NEAR = 10
SPARK_DAYS = RECENT + BASE

KST = timezone(timedelta(hours=9))
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
LOG: list[str] = []


def log(msg: str) -> None:
    print(msg, flush=True)
    LOG.append(msg)


# ---------------------------------------------------------------- universe: US
def _wiki_tables(title: str) -> list[pd.DataFrame]:
    url = f"https://en.wikipedia.org/wiki/{title}"
    r = requests.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    return pd.read_html(io.StringIO(r.text))


def _pick(tables, must: set[str], min_rows: int) -> pd.DataFrame:
    for t in tables:
        cols = {str(c).strip() for c in t.columns}
        if must <= cols and len(t) >= min_rows:
            return t
    raise RuntimeError(f"table with {must} not found")


def us_universe() -> dict[str, dict]:
    uni: dict[str, dict] = {}
    t = _pick(_wiki_tables("List_of_S%26P_500_companies"), {"Symbol", "Security"}, 400)
    for _, r in t.iterrows():
        sym = str(r["Symbol"]).strip()
        uni[sym] = {"ticker": sym, "name": str(r["Security"]).strip(),
                    "sector": str(r.get("GICS Sector", "") or ""), "index": ["S&P500"]}
    log(f"[US] S&P500 {len(t)}")
    t = _pick(_wiki_tables("Nasdaq-100"), {"Ticker"}, 90)
    name_col = "Company" if "Company" in t.columns else t.columns[0]
    sector_col = next((c for c in t.columns if "Sector" in str(c)), None)
    for _, r in t.iterrows():
        sym = str(r["Ticker"]).strip()
        if sym in uni:
            uni[sym]["index"].append("NDX100")
        else:
            uni[sym] = {"ticker": sym, "name": str(r[name_col]).strip(),
                        "sector": str(r[sector_col]) if sector_col else "", "index": ["NDX100"]}
    log(f"[US] Nasdaq-100 {len(t)} -> union {len(uni)}")
    for v in uni.values():
        v["yf"] = v["ticker"].replace(".", "-")
        v["market"] = "US"
        v["currency"] = "USD"
    return uni


# ---------------------------------------------------------------- universe: KR
ETF_PREFIX = ("KODEX", "TIGER", "KBSTAR", "RISE", "ACE", "SOL", "HANARO", "KOSEF", "ARIRANG",
              "PLUS", "KIWOOM", "TIMEFOLIO", "1Q", "BNK", "WON", "TREX", "FOCUS", "마이다스",
              "에셋플러스", "UNICORN", "히어로즈", "VITA", "DAISHIN343", "파워", "TRUSTON", "KCGI")


def _is_common(name: str) -> bool:
    n = name.strip()
    if n.startswith(ETF_PREFIX) or "ETN" in n or "스팩" in n or "리츠" in n:
        return False
    if re.search(r"(우|우B|우C|\d우B?|\(전환\))$", n):
        return False
    return True


def kr_universe_pykrx() -> tuple[dict[str, dict], str]:
    from pykrx import stock  # requires KRX_ID / KRX_PW env
    uni: dict[str, dict] = {}
    for idx, label, suffix, mkt in (("1028", "KOSPI200", ".KS", "KOSPI"),
                                     ("2203", "KOSDAQ150", ".KQ", "KOSDAQ")):
        codes = stock.get_index_portfolio_deposit_file(idx)
        if not codes or len(codes) < 100:
            raise RuntimeError(f"pykrx {label} returned {len(codes) if codes else 0}")
        for c in codes:
            uni[c] = {"ticker": c, "name": stock.get_market_ticker_name(c), "sector": "",
                      "index": [label], "yf": c + suffix, "market": mkt, "currency": "KRW"}
        log(f"[KR] pykrx {label} {len(codes)}")
    return uni, "KRX 지수 구성종목 (pykrx)"


def kr_universe_naver() -> tuple[dict[str, dict], str]:
    uni: dict[str, dict] = {}
    pat = re.compile(r'code=(\d{6})"\s+class="tltle">([^<]+)</a>')
    for sosok, label, suffix, mkt, n in ((0, "KOSPI 시총상위200", ".KS", "KOSPI", 200),
                                         (1, "KOSDAQ 시총상위150", ".KQ", "KOSDAQ", 150)):
        got: list[tuple[str, str]] = []
        for page in range(1, 9):
            url = f"https://finance.naver.com/sise/sise_market_sum.naver?sosok={sosok}&page={page}"
            r = requests.get(url, headers=UA, timeout=30)
            r.encoding = "euc-kr"
            for code, name in pat.findall(r.text):
                if _is_common(name) and code not in {c for c, _ in got}:
                    got.append((code, name.strip()))
            if len(got) >= n:
                break
            time.sleep(0.3)
        got = got[:n]
        if len(got) < n * 0.8:
            raise RuntimeError(f"naver {label} only {len(got)}")
        for code, name in got:
            uni[code] = {"ticker": code, "name": name, "sector": "", "index": [label],
                         "yf": code + suffix, "market": mkt, "currency": "KRW"}
        log(f"[KR] naver {label} {len(got)}")
    return uni, "시가총액 상위 KOSPI 200 + KOSDAQ 150 (지수 근사, 우선주·ETF·스팩 제외)"


def kr_universe() -> tuple[dict[str, dict], str]:
    if os.getenv("KRX_ID") and os.getenv("KRX_PW"):
        try:
            return kr_universe_pykrx()
        except Exception as e:  # noqa: BLE001
            log(f"[KR] pykrx failed -> naver fallback: {e!r}")
    return kr_universe_naver()


# ---------------------------------------------------------------- prices
def _frame_for(data: pd.DataFrame, sym: str, multi: bool) -> pd.DataFrame | None:
    try:
        df = data[sym] if multi else data
    except KeyError:
        return None
    df = df[["High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
    return df if len(df) else None


def download_yf(symbols: list[str], chunk: int = 80) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for i in range(0, len(symbols), chunk):
        batch = symbols[i:i + chunk]
        for attempt in range(3):
            try:
                data = yf.download(batch, period="9mo", interval="1d", auto_adjust=True,
                                   group_by="ticker", threads=True, progress=False,
                                   multi_level_index=True)
                for s in batch:
                    df = _frame_for(data, s, True)
                    if df is not None:
                        out[s] = df
                break
            except Exception as e:  # noqa: BLE001
                log(f"  yf batch {i} attempt {attempt + 1} failed: {e!r}")
                time.sleep(5 * (attempt + 1))
        time.sleep(1.5)
    missing = [s for s in symbols if s not in out]
    for s in missing:  # single retry
        try:
            data = yf.download(s, period="9mo", interval="1d", auto_adjust=True,
                               progress=False, multi_level_index=False)
            df = _frame_for(data, s, False)
            if df is not None:
                out[s] = df
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.5)
    return out


def download_kr_fdr(codes: list[str]) -> dict[str, pd.DataFrame]:
    import FinanceDataReader as fdr
    out: dict[str, pd.DataFrame] = {}
    start = (datetime.now(KST) - timedelta(days=270)).strftime("%Y-%m-%d")
    for c in codes:
        try:
            df = fdr.DataReader(c, start)
            if len(df):
                out[c] = df[["High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.2)
    return out


# ---------------------------------------------------------------- metrics
def _f(x, nd=4):
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return None
    return round(float(x), nd)


def metrics(df: pd.DataFrame) -> dict | None:
    df = df.sort_index()
    df = df[~df.index.duplicated(keep="last")]
    if len(df) < RECENT + BASE + 1:
        return None
    win = df.iloc[-(RECENT + BASE + 1):]
    base = win.iloc[1:1 + BASE]          # 직전 60거래일
    recent = win.iloc[-RECENT:]          # 최근 20거래일
    base_close = win["Close"].iloc[BASE]  # 최근 20거래일 직전 종가
    last_close = recent["Close"].iloc[-1]
    vb, vr = base["Volume"].mean(), recent["Volume"].mean()
    if not vb or vb <= 0 or not base_close:
        return None
    spark = df.iloc[-SPARK_DAYS:]
    return {
        "as_of": recent.index[-1].strftime("%Y-%m-%d"),
        "window_start": recent.index[0].strftime("%Y-%m-%d"),
        "close": _f(last_close, 4),
        "base_close": _f(base_close, 4),
        "price_chg_20d": _f(last_close / base_close - 1, 5),
        "vol_ratio": _f(vr / vb, 3),
        "avg_vol_20": _f(vr, 0),
        "avg_vol_60": _f(vb, 0),
        "avg_turnover_20": _f((recent["Close"] * recent["Volume"]).mean(), 0),
        "range_20d": _f(recent["High"].max() / recent["Low"].min() - 1, 5),
        "max_day_share": _f(recent["Volume"].max() / recent["Volume"].sum(), 4),
        "days_over_2x": int((recent["Volume"] > 2 * vb).sum()),
        "spark_close": [_f(x, 4) for x in spark["Close"]],
        "spark_vol": [_f(x, 0) for x in spark["Volume"]],
        "spark_dates": [d.strftime("%Y-%m-%d") for d in spark.index],
    }


def screen(market: str, uni: dict[str, dict], prices: dict[str, pd.DataFrame]) -> dict:
    rows = []
    for meta in uni.values():
        df = prices.get(meta["yf"])
        if df is None:
            continue
        m = metrics(df)
        if m:
            rows.append({**{k: meta[k] for k in ("ticker", "name", "sector", "index",
                                                  "market", "currency", "yf")}, **m})
    if not rows:
        return {"scanned": 0, "hits": [], "near": [], "as_of": None}
    as_of = max(r["as_of"] for r in rows)
    stale = [r for r in rows if r["as_of"] != as_of]  # 거래정지 등으로 최신일 데이터 없음
    rows = [r for r in rows if r["as_of"] == as_of]
    hits = [r for r in rows if r["vol_ratio"] >= VOL_MULT and abs(r["price_chg_20d"]) <= PRICE_BAND]
    hits.sort(key=lambda r: r["vol_ratio"], reverse=True)
    hit_ids = {id(r) for r in hits}
    near = [r for r in rows if id(r) not in hit_ids and r["vol_ratio"] >= NEAR_VOL_MULT
            and abs(r["price_chg_20d"]) <= PRICE_BAND]
    near.sort(key=lambda r: r["vol_ratio"], reverse=True)
    for r in near:
        for k in ("spark_close", "spark_vol", "spark_dates"):
            r.pop(k, None)
    log(f"[{market}] as_of {as_of} scanned {len(rows)} (stale {len(stale)}) hits {len(hits)} near {len(near)}")
    return {"as_of": as_of, "scanned": len(rows), "stale_excluded": len(stale),
            "hits": hits, "near": near[:MAX_NEAR]}


# ---------------------------------------------------------------- main
def run_market(market: str) -> dict:
    t0 = time.time()
    if market == "US":
        uni, src = us_universe(), "S&P500 + Nasdaq-100 (Wikipedia 구성종목)"
    else:
        uni, src = kr_universe()
    syms = [v["yf"] for v in uni.values()]
    prices = download_yf(syms)
    log(f"[{market}] yfinance {len(prices)}/{len(syms)}")
    if market == "KR":
        miss = [v for v in uni.values() if v["yf"] not in prices]
        if miss:
            fd = download_kr_fdr([v["ticker"] for v in miss])
            for v in miss:
                if v["ticker"] in fd:
                    prices[v["yf"]] = fd[v["ticker"]]
            log(f"[KR] FDR fallback {len(fd)}/{len(miss)}")
    res = screen(market, uni, prices)
    res.update({"universe_source": src, "universe_count": len(uni),
                "price_coverage": len(prices), "elapsed_sec": round(time.time() - t0, 1)})
    return res


def main() -> int:
    now = datetime.now(timezone.utc)
    out = {"generated_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
           "generated_date_kst": now.astimezone(KST).strftime("%Y-%m-%d"),
           "params": {"recent_days": RECENT, "base_days": BASE, "vol_mult": VOL_MULT,
                      "price_band": PRICE_BAND, "near_vol_mult": NEAR_VOL_MULT},
           "markets": {}, "errors": []}
    for mkt in ("KR", "US"):
        try:
            out["markets"][mkt] = run_market(mkt)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            out["errors"].append(f"{mkt}: {e!r}")
            out["markets"][mkt] = {"error": repr(e), "hits": [], "near": []}
    out["log"] = LOG[-80:]
    os.makedirs("results/history", exist_ok=True)
    body = json.dumps(out, ensure_ascii=False, indent=1)
    with open("results/latest.json", "w", encoding="utf-8") as f:
        f.write(body)
    with open(f"results/history/{out['generated_date_kst']}.json", "w", encoding="utf-8") as f:
        f.write(body)
    ok = any(m.get("scanned") for m in out["markets"].values())
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
