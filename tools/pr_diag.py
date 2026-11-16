# 調べ 2: WAFS(GTG)の置き場の候補を順に見る(403 の理由・別の置き場・AWS の別のバケット)
import re, datetime as dt, requests
S = requests.Session(); S.headers["User-Agent"] = "Mozilla/5.0 (skai-diag)"
def ls(u, show=400):
    try:
        r = S.get(u, timeout=60); print("GET", u, r.status_code, len(r.content)); 
        if not r.ok: print("   ", r.text[:show].replace("\n", " "))
        return r.text if r.ok else ""
    except Exception as e: print("GET", u, "失敗", repr(e)); return ""
day = dt.datetime.now(dt.UTC).strftime("%Y%m%d")
t = ls("https://nomads.ncep.noaa.gov/pub/data/nccf/com/"); print("  com/ の中:", [h for h in re.findall(r'href="([^"]+)"', t)][:80])
for u in ("https://ftpprd.ncep.noaa.gov/data/nccf/com/wafs/prod/", "https://ftpprd.ncep.noaa.gov/data/nccf/com/", "https://nomads.ncep.noaa.gov/pub/data/nccf/com/wafs/", "https://nomads.ncep.noaa.gov/pub/data/nccf/com/wafs/v7.0/"):
    t = ls(u); print("   ", [h for h in re.findall(r'href="([^"]+)"', t)][:40])
for b in ("noaa-wafs-pds", "noaa-wafs-bdp-pds", "noaa-nws-wafs-pds", "noaa-gfs-bdp-pds"):
    t = ls(f"https://{b}.s3.amazonaws.com/?list-type=2&delimiter=/&max-keys=30", 200); print("  ", b, re.findall(r"<Prefix>([^<]+)</Prefix>", t)[:30])
