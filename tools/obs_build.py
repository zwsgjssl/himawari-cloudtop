#!/usr/bin/env python3
# v206 ユーザー「(事後検証)いいね!赤外やレーダーも既に取得済みのデータだから使えるね」
#   Claude の定時の解析が「前の回の予想が当たったか」を確かめるための、実際の観測の記録。毎時(nwp.yml の実行のたび)1 回分を足す。
#   ブランチ nwp-obs の obs/<YYYYMMDD>.json に { "hours": { "<HH>Z": 記録 } }(UTC。3 日分だけ残す)。sigmet/ に SIGMET の図(気象庁 QGMA98、新しくなったときだけ)
#   記録(時刻 H = その時の正時。雷は H の前 1 時間、ほかは H ごろの値。升 = 緯度・経度 1° の四角、キー "緯度,経度"(南西の角、整数)):
#     ltg   … 雷(気象庁 雷ナウキャスト liden)の数(5 分ごとの記録の合計)
#     rad   … レーダー(気象庁 hrpns、H の直前の 1 枚、z6)の升ごとの一番強い段階(1 = 1mm/h 未満 … 5 = 20〜30、6 = 30〜50、7 = 50〜80、8 = 80 以上)と、段階 5 以上の画素の数(rad20)
#     irmin … ひまわり B13 の一番低い温度(K、KV hima:latest の赤外。CB の目安: 215K 以下)、ctop … 雲頂 FL の一番高い所(同じく雲頂)
#     metar … 主な空港の METAR(aviationweather.gov)、sigmet … 福岡 FIR(RJJJ)の SIGMET(aviationweather.gov の国際 SIGMET)、pirep … 日本付近の PIREP・AIREP(乱気流・着氷)
#   どれかが取れなくても、取れた物だけで記録する(ログに理由)。同じ時刻をもう記録していれば、足りない物だけ取り直す
import argparse, datetime as dt, email.utils, gzip, io, json, math, os, sys, time
import numpy as np, requests
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nwp_build import KV, unpack, UA, log

JMA = os.environ.get("JMA_BASE", "https://www.jma.go.jp/bosai/").rstrip("/") + "/"
AWC = os.environ.get("AWC_BASE", "https://aviationweather.gov/api/data/").rstrip("/") + "/"
AIR = os.environ.get("AIRINFO_BASE", "https://www.data.jma.go.jp/airinfo/data/pict/").rstrip("/") + "/"
LAT0, LAT1, LON0, LON1 = 20, 50, 118, 152
AIRPORTS = "RJCC,RJCH,RJCB,RJEC,RJSS,RJSN,RJAA,RJTT,RJGG,RJNK,RJBB,RJOO,RJOA,RJOM,RJOT,RJFF,RJFK,RJFT,RJFM,ROAH,ROIG"
KEEP_DAYS = 3
# 気象庁のレーダーの色(Map の RAD_LV と同じ)
RAD_RGB = np.array([[242, 242, 255], [160, 210, 255], [33, 140, 255], [0, 65, 255], [250, 245, 0], [255, 153, 0], [255, 40, 0], [180, 0, 104]], float)

def box(lat, lon): return f"{int(math.floor(lat))},{int(math.floor(lon))}"
def inside(lat, lon): return LAT0 <= lat < LAT1 and LON0 <= lon < LON1
def get(url, **kw):
    r = requests.get(url, headers=UA, timeout=kw.pop("timeout", 60), **kw); r.raise_for_status(); return r
def jt(s): return dt.datetime.strptime(s, "%Y%m%d%H%M%S")

def targets(k):
    f = {"n1": "jmatile/data/nowc/targetTimes_N1.json", "n3": "jmatile/data/nowc/targetTimes_N3.json"}[k]
    return get(JMA + f, timeout=30).json()

def obs_ltg(H):
    """H の前 1 時間の雷の数(升ごと)"""
    L = [e for e in targets("n3") if e.get("basetime") == e.get("validtime") and "liden" in (e.get("elements") or [])]
    L = [e for e in L if H - dt.timedelta(hours=1) < jt(e["validtime"]) <= H]
    out, n = {}, 0
    for e in L:
        j = get(f"{JMA}jmatile/data/nowc/{e['basetime']}/none/{e['validtime']}/surf/liden/data.geojson", timeout=30).json()
        for f in j.get("features", []):
            c = (f.get("geometry") or {}).get("coordinates") or []
            if len(c) >= 2 and inside(c[1], c[0]): k = box(c[1], c[0]); out[k] = out.get(k, 0) + 1; n += 1
    log(f"雷: {len(L)} 個の記録、{n} 回")
    return {"frames": len(L), "box": out}

def merc_x(lon, n): return (lon + 180) / 360 * n
def merc_y(lat, n): r = math.radians(lat); return (1 - math.log(math.tan(r) + 1 / math.cos(r)) / math.pi) / 2 * n
def obs_rad(H):
    """H の直前のレーダー 1 枚(z6)の升ごとの一番強い段階と、20mm/h 以上の画素の数"""
    from PIL import Image
    L = [e for e in targets("n1") if e.get("basetime") == e.get("validtime") and "hrpns" in (e.get("elements") or []) and jt(e["validtime"]) <= H]
    if not L: return None
    e = max(L, key=lambda x: x["validtime"]); z = 6; n = 2 ** z
    X0, X1, Y0, Y1 = int(merc_x(122, n)), int(merc_x(150, n)), int(merc_y(47, n)), int(merc_y(24, n))
    mx, c20 = {}, {}
    for tx in range(X0, X1 + 1):
        for ty in range(Y0, Y1 + 1):
            try: r = get(f"{JMA}jmatile/data/nowc/{e['basetime']}/none/{e['validtime']}/surf/hrpns/{z}/{tx}/{ty}.png", timeout=30)
            except requests.HTTPError: continue
            a = np.asarray(Image.open(io.BytesIO(r.content)).convert("RGBA")).astype(float)
            m = a[..., 3] > 100
            if not m.any(): continue
            px = a[..., :3][m]; d = ((px[:, None, :] - RAD_RGB[None, :, :]) ** 2).sum(-1); lv = d.argmin(1) + 1; lv[d.min(1) > 90 * 90] = 0
            yy, xx = np.nonzero(m)
            lon = (tx * 256 + xx + 0.5) / (256 * n) * 360 - 180
            lat = np.degrees(np.arctan(np.sinh(math.pi * (1 - 2 * (ty * 256 + yy + 0.5) / (256 * n)))))
            for la, lo, v in zip(np.floor(lat).astype(int), np.floor(lon).astype(int), lv):
                if v == 0 or not inside(la, lo): continue
                k = f"{la},{lo}"
                if v > mx.get(k, 0): mx[k] = int(v)
                if v >= 5: c20[k] = c20.get(k, 0) + 1
    log(f"レーダー: {e['validtime']} 升 {len(mx)}、20mm/h 以上の升 {len(c20)}")
    return {"t": e["validtime"], "max": mx, "c20": c20}

def obs_hima(kv):
    """KV hima:latest の赤外(I)の升ごとの一番低い温度、雲頂(L)の一番高い FL"""
    b = kv.get("hima:latest")
    if not b: return None, None
    head, parts = unpack(b); ir = ct = None
    if "I" in parts and head.get("ir_grid") and head.get("ir"):
        g = head["ir_grid"]; a = np.frombuffer(gzip.decompress(parts["I"]), "u1").reshape(g["ny"], g["nx"]).astype(int)
        ok = (a > 0) & (a < 255); K = np.where(ok, a + 150, 999)
        lat = g["lat0"] + g["dlat"] * np.arange(g["ny"]); lon = g["lon0"] + g["dlon"] * np.arange(g["nx"])
        out = {}
        for i in range(LAT0, LAT1):
            r = (lat >= i) & (lat < i + 1)
            if not r.any(): continue
            for j in range(LON0, LON1):
                c = (lon >= j) & (lon < j + 1)
                if not c.any(): continue
                v = int(K[np.ix_(r, c)].min())
                if v < 999: out[f"{i},{j}"] = v
        ir = {"t": head["ir"][0]["t"], "box": out}
    if "L" in parts and head.get("grid") and head.get("times"):
        g = head["grid"]; n = g["ny"] * g["nx"]; a = np.frombuffer(parts["L"][:n], "u1").reshape(g["ny"], g["nx"]).astype(int)
        F = np.where((a > 0) & (a < 255), a * 2, -1)
        lat = g["lat0"] + g["dlat"] * np.arange(g["ny"]); lon = g["lon0"] + g["dlon"] * np.arange(g["nx"])
        out = {}
        for i in range(LAT0, LAT1):
            r = (lat >= i) & (lat < i + 1)
            if not r.any(): continue
            for j in range(LON0, LON1):
                c = (lon >= j) & (lon < j + 1)
                if not c.any(): continue
                v = int(F[np.ix_(r, c)].max())
                if v > 0: out[f"{i},{j}"] = v
        ct = {"t": head["times"][0]["t"], "box": out}
    log(f"赤外 {ir and ir['t']}・雲頂 {ct and ct['t']}")
    return ir, ct

def awc(path, **params):
    r = requests.get(AWC + path, params=params, headers=UA, timeout=60)
    if r.status_code == 204: return []
    r.raise_for_status(); return r.json()

def obs_metar():
    j = awc("metar", ids=AIRPORTS, format="json", hours=1)
    out = [{"id": m.get("icaoId"), "t": m.get("reportTime") or m.get("obsTime"), "raw": m.get("rawOb"), "lat": m.get("lat"), "lon": m.get("lon"),
            "wdir": m.get("wdir"), "wspd": m.get("wspd"), "wgst": m.get("wgst"), "wx": m.get("wxString")} for m in j if isinstance(m, dict)]
    log(f"METAR: {len(out)} 通"); return out

def obs_sigmet():
    j = awc("isigmet", format="json")
    out = []
    for s in j if isinstance(j, list) else []:
        if not isinstance(s, dict): continue
        fir = str(s.get("firId") or s.get("icaoId") or "") + " " + str(s.get("firName") or "")
        if "RJJJ" not in fir and "FUKUOKA" not in fir.upper(): continue
        out.append({k: s.get(k) for k in ("firId", "seriesId", "hazard", "qualifier", "base", "top", "validTimeFrom", "validTimeTo", "dir", "spd", "chng", "coords", "rawSigmet") if k in s})
    log(f"SIGMET(福岡 FIR): {len(out)} 件(全体 {len(j) if isinstance(j, list) else '?'} 件)"); return out

def obs_pirep():
    j = awc("pirep", format="json", bbox=f"{LAT0},{LON0},{LAT1},{LON1}", age=1)
    out = []
    for p in j if isinstance(j, list) else []:
        if not isinstance(p, dict): continue
        lat, lon = p.get("lat"), p.get("lon")
        if lat is None or lon is None or not inside(float(lat), float(lon)): continue
        q = {k: p.get(k) for k in ("obsTime", "lat", "lon", "fltLvl", "acType", "tbInt1", "tbType1", "tbBas1", "tbTop1", "icgInt1", "icgBas1", "icgTop1", "wxString", "rawOb", "pirepType") if p.get(k) not in (None, "")}
        out.append(q)
    log(f"PIREP・AIREP(日本付近): {len(out)} 通"); return out

def sigmet_png(d):
    """気象庁の SIGMET の図(新しくなったときだけ保存。8 枚まで)"""
    r = get(AIR + "sigmet/QGMA98.png", timeout=60)
    lm = r.headers.get("Last-Modified"); t = email.utils.parsedate_to_datetime(lm).astimezone(dt.timezone.utc).strftime("%Y%m%d%H%M") if lm else dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d%H%M")
    sd = os.path.join(d, "sigmet"); os.makedirs(sd, exist_ok=True); f = os.path.join(sd, f"QGMA98_{t}.png")
    if not os.path.exists(f): open(f, "wb").write(r.content); log(f"SIGMET の図: {t}")
    for old in sorted(os.listdir(sd))[:-8]: os.remove(os.path.join(sd, old))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="ブランチ nwp-obs の中身のフォルダ(書き足す)")
    ap.add_argument("--dry-kv", default="", help="KV の代わりのフォルダ(試験用)")
    a = ap.parse_args()
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None); H = now.replace(minute=0, second=0, microsecond=0)
    od = os.path.join(a.dir, "obs"); os.makedirs(od, exist_ok=True)
    f = os.path.join(od, H.strftime("%Y%m%d") + ".json")
    day = json.load(open(f, encoding="utf-8")) if os.path.exists(f) else {"hours": {}}
    rec = day["hours"].get(H.strftime("%HZ"), {})
    jobs = [("ltg", lambda: obs_ltg(H)), ("rad", lambda: obs_rad(H)), ("metar", obs_metar), ("sigmet", obs_sigmet), ("pirep", obs_pirep)]
    for name, fn in jobs:
        if name in rec: continue
        try:
            v = fn()
            if v is not None: rec[name] = v
        except Exception as e: log(f"{name}: 取れませんでした {e}")
    if "irmin" not in rec or "ctop" not in rec:
        try:
            ir, ct = obs_hima(KV(a.dry_kv or None))
            if ir: rec["irmin"] = ir
            if ct: rec["ctop"] = ct
        except Exception as e: log(f"赤外・雲頂: 取れませんでした {e}")
    try: sigmet_png(a.dir)
    except Exception as e: log(f"SIGMET の図: 取れませんでした {e}")
    rec["at"] = now.strftime("%Y-%m-%dT%H:%MZ")
    day["hours"][H.strftime("%HZ")] = rec
    json.dump(day, open(f, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    for old in sorted(os.listdir(od)):   # 3 日より古い日を消す
        if old.endswith(".json") and old[:8] < (H - dt.timedelta(days=KEEP_DAYS)).strftime("%Y%m%d"): os.remove(os.path.join(od, old))
    open(os.path.join(a.dir, "README.md"), "w", encoding="utf-8").write("事後検証用の観測の記録(tools/obs_build.py が毎時に書き足す。3 日分)。obs/<UTC の日>.json の hours.<HH>Z\n")
    log(f"{f} に {H.strftime('%HZ')} を記録: " + ", ".join(k for k in rec if k != "at"))

if __name__ == "__main__":
    main()
