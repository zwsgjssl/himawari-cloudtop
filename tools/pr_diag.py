# 調べ: GTG(WAFS の乱気流 EDR)が NOAA の公開サーバー(NOMADS)・AWS の公開データで誰でも取れるか。取れたら中身(変数・高度・日本付近の値)を見る
import re, subprocess, sys, datetime as dt, requests
S = requests.Session(); S.headers["User-Agent"] = "skai-diag"
def ls(u):
    try:
        r = S.get(u, timeout=60); print("GET", u, r.status_code, len(r.content)); return r.text if r.ok else ""
    except Exception as e: print("GET", u, "失敗", repr(e)); return ""
now = dt.datetime.utcnow(); day = now.strftime("%Y%m%d"); yday = (now - dt.timedelta(days=1)).strftime("%Y%m%d")
# 1) 新しい置き場(wafs/prod)
t = ls("https://nomads.ncep.noaa.gov/pub/data/nccf/com/wafs/prod/"); print(" ", re.findall(r'href="([^"]+)"', t)[:20])
cand = []
for d in (day, yday):
    t = ls(f"https://nomads.ncep.noaa.gov/pub/data/nccf/com/wafs/prod/wafs.{d}/"); hs = re.findall(r'href="(\d\d)/"', t); print("  回", hs)
    for h in reversed(hs):
        for sub in ("grib2/0p25/", "grib2/0p25/blending/", ""):
            t2 = ls(f"https://nomads.ncep.noaa.gov/pub/data/nccf/com/wafs/prod/wafs.{d}/{h}/{sub}")
            fs = [f for f in re.findall(r'href="([^"]+)"', t2) if f.endswith(".grib2")]
            if fs: print("   ", sub, len(fs), fs[:12]); cand += [(d, h, sub, f) for f in fs]
        if cand: break
    if cand: break
# 2) GFS の atmos(古い置き場)
for d in (day,):
    t = ls(f"https://nomads.ncep.noaa.gov/pub/data/nccf/com/gfs/prod/gfs.{d}/00/atmos/"); print("  awf/wafs:", [f for f in re.findall(r'href="([^"]+)"', t) if "awf" in f or "wafs" in f.lower()][:10])
# 3) AWS の公開データ
for b in ("noaa-gfs-bdp-pds",):
    t = ls(f"https://{b}.s3.amazonaws.com/?list-type=2&prefix=gfs.{day}/00/atmos/gfs.t00z.awf&max-keys=5"); print("  ", re.findall(r"<Key>([^<]+)</Key>", t)[:5])
    t = ls(f"https://{b}.s3.amazonaws.com/?list-type=2&prefix=wafs.{day}/&max-keys=10"); print("  ", re.findall(r"<Key>([^<]+)</Key>", t)[:10])
# 4) 取れたら 1 つ中を見る(EDR を含みそうな物)
pick = [c for c in cand if re.search(r"(edr|f00[6-9]|f01[0-2])", c[3], re.I)] or cand
if pick:
    d, h, sub, f = pick[0]; u = f"https://nomads.ncep.noaa.gov/pub/data/nccf/com/wafs/prod/wafs.{d}/{h}/{sub}{f}"
    r = S.get(u, timeout=300); print("ファイル", u, r.status_code, len(r.content)); open("/tmp/w.grib2", "wb").write(r.content)
    subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "eccodes", "eccodeslib"], check=False)
    import eccodes, numpy as np
    with open("/tmp/w.grib2", "rb") as fh:
        n = 0
        while True:
            g = eccodes.codes_grib_new_from_file(fh)
            if g is None: break
            n += 1; k = {x: eccodes.codes_get(g, x) for x in ("shortName", "name", "typeOfLevel", "level", "units")}
            try: k["dc"] = eccodes.codes_get(g, "parameterCategory"); k["pn"] = eccodes.codes_get(g, "parameterNumber"); k["ps"] = eccodes.codes_get(g, "typeOfStatisticalProcessing")
            except Exception: pass
            if n <= 60 or "dissip" in str(k["name"]).lower() or k.get("pn") in (30, 31, 32): 
                v = eccodes.codes_get_values(g); Ni = eccodes.codes_get(g, "Ni"); Nj = eccodes.codes_get(g, "Nj"); la0 = eccodes.codes_get(g, "latitudeOfFirstGridPointInDegrees")
                print(f"  {n:3d} {k}  格子 {Ni}x{Nj} 最初の緯度 {la0}  値 {np.nanmin(v):.3f}〜{np.nanmax(v):.3f}")
            eccodes.codes_release(g)
        print("メッセージ数", n)
