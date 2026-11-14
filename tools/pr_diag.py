# 診断: 日本付近の公開 AIREP/PIREP(aviationweather.gov の Data API)がどれくらいあるか
import json, requests, collections
UA = {"User-Agent": "skai-pirep-check/1.0"}; B = "https://aviationweather.gov/api/data"
tries = [
  ("pirep bbox 24h", "/pirep", {"format": "json", "bbox": "20,118,50,152", "age": 24}),
  ("pirep bbox 96h", "/pirep", {"format": "json", "bbox": "20,118,50,152", "age": 96}),
  ("aircraftreport bbox", "/aircraftreport", {"format": "json", "bbox": "20,118,50,152", "age": 24}),
  ("pirep id RJTT 500", "/pirep", {"format": "json", "id": "RJTT", "distance": 500, "age": 24}),
  ("pirep global 24h", "/pirep", {"format": "json", "age": 24}),
]
for name, path, q in tries:
    try:
        r = requests.get(B + path, params=q, headers=UA, timeout=60); print("==", name, r.status_code, r.url, len(r.content))
        try: d = r.json()
        except Exception: print(r.text[:300]); continue
        if isinstance(d, dict): print(list(d.keys())[:10]); d = d.get("data") or d.get("features") or []
        print("件数", len(d))
        if d: print("例", json.dumps(d[0], ensure_ascii=False)[:700])
        JP = [x for x in d if isinstance(x, dict) and x.get("lat") is not None and 20 <= x["lat"] <= 50 and 118 <= x["lon"] <= 152]
        print("日本付近", len(JP))
        c = collections.Counter((x.get("pirepType") or x.get("reportType"), bool(x.get("tbInt1"))) for x in JP); print(c)
        for x in JP[:8]: print("  ", x.get("obsTime"), x.get("receiptTime"), x.get("acType"), x.get("lat"), x.get("lon"), x.get("fltLvl"), x.get("tbInt1"), (x.get("rawOb") or "")[:120])
        if JP: print("タービュランスあり", sum(1 for x in JP if x.get("tbInt1")))
    except Exception as e: print(name, "ERR", e)
