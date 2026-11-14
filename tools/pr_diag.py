# 診断: 気象庁 bosai の nowc / jmatile にエコー頂高度のような要素があるか
import json, requests
UA = {"User-Agent": "skai-diag/1.0"}; B = "https://www.jma.go.jp/bosai/jmatile/data"
for f in ("nowc/targetTimes_N1.json", "nowc/targetTimes_N2.json", "nowc/targetTimes_N3.json", "rasrf/targetTimes.json", "rasnow/targetTimes.json", "radar/targetTimes.json", "echotop/targetTimes.json", "hrpns/targetTimes.json"):
    r = requests.get(f"{B}/{f}", headers=UA, timeout=30); print("==", f, r.status_code)
    if r.ok:
        try:
            L = r.json(); els = sorted({x for e in L for x in e.get("elements", [])}); print("  件数", len(L), "要素", els)
        except Exception as e: print("  ", r.text[:200])
