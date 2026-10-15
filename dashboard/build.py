"""스크리닝 결과 + Claude 분석을 대시보드 HTML로 합칩니다.

usage: python build.py latest.json analysis.json template.html out.html

analysis.json
{
  "report": {"generated_at_kst": "2026-10-16 07:05", "summary": "...", "data_warning": ""},
  "items": {
    "KR:005930": {
      "company": "기업 개요 2~3문장",
      "news": [{"date": "2026-10-02", "title": "...", "summary": "...", "source": "연합뉴스", "url": "https://..."}],
      "comment": {"view": "...", "watch": ["..."], "risks": ["..."]},
      "flags": ["공개매수 진행"]
    }
  }
}
"""
import json
import sys


def main(latest, analysis, template, out):
    data = json.load(open(latest, encoding="utf-8"))
    ana = json.load(open(analysis, encoding="utf-8"))
    items = ana.get("items", {})
    for mkt, m in data.get("markets", {}).items():
        for h in m.get("hits", []):
            a = items.get(f"{mkt}:{h['ticker']}")
            if a:
                h["analysis"] = a
    data["report"] = ana.get("report", {})
    data.pop("log", None)
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = open(template, encoding="utf-8").read()
    token = '"__VPD_DATA__"'
    if html.count(token) != 1:
        raise SystemExit("template placeholder not found")
    open(out, "w", encoding="utf-8").write(html.replace(token, payload))
    n = sum(len(m.get("hits", [])) for m in data.get("markets", {}).values())
    k = sum(1 for m in data.get("markets", {}).values() for h in m.get("hits", []) if "analysis" in h)
    print(f"built {out}: hits {n}, analyzed {k}")


if __name__ == "__main__":
    main(*sys.argv[1:5])
