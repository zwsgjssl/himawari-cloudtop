# 調べ: aviationweather.gov の国際 SIGMET(isigmet)の中身の形と、日本付近の物
import json, time, requests
S = requests.Session(); S.headers["User-Agent"] = "approach-planner-wx/1.0 (diag)"
for u in ("https://aviationweather.gov/api/data/isigmet?format=json", "https://aviationweather.gov/api/data/isigmet?format=json&level=0"):
    r = S.get(u, timeout=60); print("GET", u, r.status_code, len(r.content), r.headers.get("content-type"))
    if not r.ok: print(r.text[:300]); continue
    j = r.json(); print("件数", len(j))
    if j: print("キー", sorted(j[0].keys())); print("1 件目", json.dumps(j[0], ensure_ascii=False)[:1500])
    print("FIR", sorted(set(str(s.get("firId")) for s in j)))
    now = time.time()
    for s in j:
        f = str(s.get("firId") or "")
        if f[:2] in ("RJ", "RK", "RC", "ZS", "ZJ", "RP", "UH", "ZG", "ZP", "ZB", "ZY") or f in ("KZAK", "PAZA"):
            print(f, s.get("seriesId"), s.get("hazard"), s.get("qualifier"), s.get("base"), s.get("top"), repr(s.get("validTimeFrom")), repr(s.get("validTimeTo")), "coords", type(s.get("coords")).__name__, str(s.get("coords"))[:120])
