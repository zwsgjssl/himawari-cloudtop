# 調べ: aviationweather.gov の METAR(hours=3)・TAF の JSON の形(羽田・福岡・那覇)
import json, requests
H = {"User-Agent": "approach-planner-wx/1.0 (diag)"}
for p in ("metar?format=json&ids=RJTT,RJFF,ROAH&hours=3", "taf?format=json&ids=RJTT,RJFF,ROAH"):
    r = requests.get("https://aviationweather.gov/api/data/" + p, headers=H, timeout=60); print(p, r.status_code)
    j = r.json(); print("件数", len(j))
    for x in j[:4]: print({k: x.get(k) for k in ("icaoId", "obsTime", "reportTime", "issueTime", "bulletinTime", "rawOb", "rawTAF")})
