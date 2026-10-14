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

# v207 ユーザー「答え合わせに UKMET も使えるんじゃない?」→ UKMET(英国気象局の全球モデル。気象庁とは別のモデル)の回ごとに、
#   解析(T+0)と 12 時間予想(T+12)を 1° の升ごとにまとめて ukmo/<回>.json に(KV の ukmo:meta と ukmo/<回>/<予報時刻>)。新しい回が出たときだけ。
#   jet = FL300〜450 の最大風速(kt)と その FL、vws = FL250〜450 の上下の層の風の差(kt/1000ft)、ti1 = Ellrod TI1(×1e-7/s²、FL250〜450)。vws・ti1 は升の中の 90 パーセンタイルの、一番大きい層の値、
#   trop = 圏界面の FL(升の平均)、fz = 0℃ の高さ(FL、升の平均)、ice = 湿度 85% 以上・気温 0〜−15℃ の層の FL [下, 上]
#   T+0 は観測を取り込んだ直後の値なので、ジェット・シアー・圏界面の「実際に近い姿」として事後検証に使う(観測そのものではない)。T+12 は気象庁の予想と比べる 2 つ目のモデル
UK_V = 2   # まとめ方を変えたら上げる(同じ回でも作り直す)
def p2fl(p): return (1 - (np.asarray(p, float) / 1013.25) ** 0.190263) * 145442.16 / 100
def obs_ukmo(kv, d):
    import warnings; warnings.simplefilter("ignore", RuntimeWarning)   # 全部が欠けの升の nanmax
    m = kv.get("ukmo:meta")
    if not m: return
    m = json.loads(m); run = m.get("run_id"); f = os.path.join(d, "ukmo", f"{run}.json")
    if not run: return
    if os.path.exists(f):
        try:
            if json.load(open(f, encoding="utf-8")).get("v") == UK_V: return
        except Exception: pass
    g, lv = m["grid"], np.array(m["lv"], float); ny, nx, L = g["ny"], g["nx"], len(lv); FL = p2fl(lv)
    lat = g["lat0"] + g["dlat"] * np.arange(ny); lon = g["lon0"] + g["dlon"] * np.arange(nx)
    rows = {i: np.nonzero((lat >= i) & (lat < i + 1))[0] for i in range(LAT0, LAT1)}; cols = {j: np.nonzero((lon >= j) & (lon < j + 1))[0] for j in range(LON0, LON1)}
    out = {"v": UK_V, "run": m.get("run"), "model": "UKMET", "unit": {"jet": "kt・FL", "vws": "kt/1000ft", "ti1": "1e-7/s2", "trop": "FL", "fz": "FL", "ice": "FL"}}
    for s in m.get("slices", []):
        if s.get("lead") not in (0, 12): continue
        b = kv.get(s["key"]); ixb = kv.get(s["ix"]) if s.get("ix") else None; rhb = kv.get(s["rh"]) if s.get("rh") else None
        if not b: continue
        a = np.frombuffer(b, "<i2"); n3 = L * 3 * ny * nx
        X = a[:n3].reshape(L, 3, ny, nx).astype(float); X[X == -32768] = np.nan; X /= 10
        T, U, V = X[:, 0], X[:, 1], X[:, 2]; S = np.hypot(U, V)
        tp = a[n3:n3 + ny * nx].reshape(ny, nx).astype(float); tp[tp == -32768] = np.nan; tpfl = p2fl(tp / 10)
        TI = np.frombuffer(ixb, "<i2").reshape(L, 1, ny, nx)[:, 0].astype(float) / 10 if ixb else None
        RH = np.frombuffer(rhb, "u1").reshape(L, ny, nx).astype(float) if rhb else None
        up = (FL >= 300) & (FL <= 450); mid = (FL >= 250) & (FL <= 450)
        Sj = np.where(up[:, None, None], S, np.nan)
        dV = np.hypot(np.diff(U, axis=0), np.diff(V, axis=0)) / (np.diff(FL)[:, None, None] / 10)   # kt / 1000ft
        okv = (mid[:-1] & mid[1:])[:, None, None]; VW = np.where(okv, dV, np.nan)
        fzi = np.argmax(T <= 0, axis=0); fz = np.where(np.any(T <= 0, axis=0), FL[fzi], np.nan)
        ic = (RH >= 85) & (T <= 0) & (T >= -15) if RH is not None else None
        rec = {"t": s["t"], "jet": {}, "vws": {}, "ti1": {}, "trop": {}, "fz": {}, "ice": {}}
        with np.errstate(all="ignore"):
            for i, ri in rows.items():
                for j, cj in cols.items():
                    if not len(ri) or not len(cj): continue
                    k = f"{i},{j}"; sl = np.ix_(ri, cj)
                    sj = Sj[(slice(None),) + sl]
                    if np.isfinite(sj).any():
                        pl = np.nanmax(sj.reshape(L, -1), axis=1); li = int(np.nanargmax(np.where(np.isfinite(pl), pl, -1)))
                        rec["jet"][k] = [int(np.nanmax(sj)), int(round(FL[li] / 10) * 10)]
                    # シアー・TI1 は 10km の格子で 1 点だけ飛び抜けることがあるので、升の中の上位 10%(90 パーセンタイル)を層ごとに出して、一番大きい層の値
                    vw = VW[(slice(None),) + sl].reshape(VW.shape[0], -1)
                    if np.isfinite(vw).any(): rec["vws"][k] = round(float(np.nanmax(np.nanpercentile(vw, 90, axis=1))), 1)
                    if TI is not None:
                        t_ = TI[mid][(slice(None),) + sl].reshape(int(mid.sum()), -1)
                        if t_.size and np.isfinite(t_).any(): rec["ti1"][k] = round(float(np.nanmax(np.nanpercentile(t_, 90, axis=1))), 1)
                    v = np.nanmean(tpfl[sl])
                    if np.isfinite(v): rec["trop"][k] = int(round(v / 10) * 10)
                    v = np.nanmean(fz[sl])
                    if np.isfinite(v): rec["fz"][k] = int(round(v / 5) * 5)
                    if ic is not None:
                        lay = np.any(ic[(slice(None),) + sl].reshape(L, -1), axis=1)
                        if lay.any(): rec["ice"][k] = [int(FL[lay].min()), int(FL[lay].max())]
        out["t0" if s["lead"] == 0 else "f12"] = rec
    if "t0" not in out: return
    os.makedirs(os.path.dirname(f), exist_ok=True); json.dump(out, open(f, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    ud = os.path.dirname(f)
    for old in sorted(os.listdir(ud))[:-12]: os.remove(os.path.join(ud, old))   # 3 日分(1 日 4 回)
    log(f"UKMET {run}: 升 {len(out['t0']['jet'])}、最大風速 {max(v[0] for v in out['t0']['jet'].values()) if out['t0']['jet'] else '-'}kt")

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
    firs = sorted({str(s.get("firId") or s.get("icaoId")) for s in j if isinstance(s, dict)}) if isinstance(j, list) else []
    log(f"SIGMET(福岡 FIR): {len(out)} 件(全体 {len(j) if isinstance(j, list) else '?'} 件、FIR {len(firs)}: {' '.join(firs)[:300]}"
        + (f"、項目 {sorted(j[0].keys())}" if isinstance(j, list) and j and isinstance(j[0], dict) else "") + ")"); return out

def obs_pirep():
    j = awc("pirep", format="json", bbox=f"{LAT0},{LON0},{LAT1},{LON1}", age=1)
    # 2026-10-14 確かめ: 同じ書き方でアメリカは 44 通返る(書き方は正しい)。日本付近は PIREP・AIREP がほとんど流れていない(0 通が普通)
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
        if rec.get(name): continue   # 取れている物は取り直さない(空の SIGMET・PIREP は取り直す)
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
    try: obs_ukmo(KV(a.dry_kv or None), a.dir)
    except Exception as e: log(f"UKMET: まとめられませんでした {e}")
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
