#!/usr/bin/env python3
# 2026-11-12 ユーザー「国際線用に対応させる方針で進めて」(世界のどの経路でも断面図・平面図を出すための全球の UKMET)
#   ukmo_build.py は日本付近だけを KV に置く(今のまま)。こちらは全球を間引いて 15° 四方の区画に分け、Cloudflare の R2 に置く。
#   Map は WX保存のとき、経路にかかる区画だけを取ってつなぐ(端末に入る量は今と同じくらい)。
#   格子: 10km(緯度 0.09375°・経度 0.140625°)を 緯度 3 つ・経度 2 つおきに間引く(約 0.28°、約 30km)。
#   1 区画・1 時刻 = ukmo_build.off_bytes と同じ形(UKO1: int16 [25][気温・東西風・南北風][ny][nx] + 圏界面、湿度 uint8 [25][ny][nx])。
# 使い方: python3 tools/ukmo_global.py --dry-run <フォルダ>(区画をフォルダに書き、大きさと時間を出す) / --r2(R2 に書く。R2_* の環境変数)
import argparse, datetime as dt, json, os, sys, tempfile, time
from concurrent.futures import ThreadPoolExecutor
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ukmo_build as ub

SY, SX, TILE = 3, 2, 15

def read(path, levels):
    import xarray as xr
    with xr.open_dataset(path, engine="h5netcdf", decode_times=False) as ds:
        da = ds[ub.main_var(ds)]; la, lo, pr = ub.dim_like(da, ["lat"]), ub.dim_like(da, ["lon"]), ub.dim_like(da, ["press"])
        for d in da.dims:
            if d not in (la, lo, pr) and da.sizes[d] == 1: da = da.isel({d: 0})
        if levels and pr:
            pv = np.asarray(ds[pr].values, dtype="f8"); pv = pv / 100 if pv.max() > 2000 else pv
            idx = [int(np.argmin(abs(pv - P))) for P in ub.LEVELS_HPA]
            da = da.isel({pr: idx})
        da = da.isel({la: slice(None, None, SY), lo: slice(None, None, SX)})
        lat = np.asarray(ds[la].values[::SY], dtype="f8"); lon = np.asarray(ds[lo].values[::SX], dtype="f8")
        v = np.asarray(da.transpose(*([pr] if (levels and pr) else []), la, lo).values, dtype="f4"); units = str(da.attrs.get("units", ""))
    if lat[0] > lat[-1]: lat = lat[::-1]; v = v[..., ::-1, :]
    lon = np.where(lon >= 180, lon - 360, lon); o = np.argsort(lon, kind="stable"); lon = lon[o]; v = v[..., o]
    return lat, lon, v, units

def build(run, lead, work):
    P = {}
    def get(k):
        p = os.path.join(work, f"{k}.nc"); ub.download(ub.key_of(run, lead, ub.FILES[k]), p); P[k] = p
    t0 = time.time()
    with ThreadPoolExecutor(5) as ex: list(ex.map(get, ub.FILES))
    t1 = time.time()
    lat, lon, T, uT = read(P["T"], True); _, _, S, uS = read(P["S"], True); _, _, D, _ = read(P["D"], True)
    _, _, TP, _ = read(P["TP"], False); _, _, RH, _ = read(P["RH"], True)
    for p in P.values(): os.remove(p)
    Tc = T - 273.15 if np.nanmean(T) > 150 else T
    Skt = S * ub.KT if uS.strip().lower() not in ("kt", "knots", "knot") else S
    rad = np.deg2rad(D); U, V = -Skt*np.sin(rad), -Skt*np.cos(rad)
    TPh = TP / 100 if np.nanmax(TP) > 2000 else TP
    rhb = np.frombuffer(ub.rh_bytes(RH, Tc, lead)[0], dtype="u1").reshape(RH.shape)
    ub.log(f"PT{lead:02d} 取得 {t1-t0:.0f}秒・読み {time.time()-t1:.0f}秒 格子 {len(lat)}x{len(lon)} 緯度 {lat[0]:.2f}〜{lat[-1]:.2f} 経度 {lon[0]:.2f}〜{lon[-1]:.2f}")
    return lat, lon, Tc, U, V, TPh, rhb

def tiles(lat, lon, Tc, U, V, TPh, rhb):
    out = {}
    for la0 in range(-90, 90, TILE):
        yi = np.where((lat >= la0) & (lat < la0 + TILE if la0 + TILE < 90 else lat <= 90))[0]
        for lo0 in range(-180, 180, TILE):
            xi = np.where((lon >= lo0) & (lon < lo0 + TILE))[0]
            if not len(yi) or not len(xi): continue
            sl = (slice(yi[0], yi[-1] + 1), slice(xi[0], xi[-1] + 1)); L = Tc.shape[0]; ny, nx = len(yi), len(xi)
            body = np.empty((L, 3, ny, nx), dtype="<i2")
            body[:, 0], body[:, 1], body[:, 2] = ub.q16(Tc[:, sl[0], sl[1]], 10), ub.q16(U[:, sl[0], sl[1]], 10), ub.q16(V[:, sl[0], sl[1]], 10)
            buf = body.tobytes() + ub.q16(TPh[sl[0], sl[1]], 10).tobytes()
            out[f"{la0}_{lo0}"] = (ub.off_bytes(buf, rhb[:, sl[0], sl[1]].tobytes(), nx),
                                   {"y0": int(yi[0]), "ny": ny, "x0": int(xi[0]), "nx": nx})
    return out

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--dry-run", default=""); ap.add_argument("--leads", default="")
    a = ap.parse_args()
    run = next((r for r in ub.list_runs(2) if ub.run_ready(r)), None)
    if not run: ub.log("回がありません"); return
    leads = [int(x) for x in a.leads.split(",")] if a.leads else ub.LEADS
    ub.log(f"回 {run} 予報時刻 {leads}")
    tot = 0; n = 0; t0 = time.time(); meta = None
    for lead in leads:
        with tempfile.TemporaryDirectory() as w:
            lat, lon, *rest = build(run, lead, w)
        tl = tiles(lat, lon, *rest)
        sz = sum(len(b) for b, _ in tl.values()); tot += sz; n += len(tl)
        if meta is None: meta = {"run": run, "lat0": float(lat[0]), "dlat": float((lat[-1]-lat[0])/(len(lat)-1)), "ny": len(lat),
                                 "lon0": float(lon[0]), "dlon": float((lon[-1]-lon[0])/(len(lon)-1)), "nx": len(lon), "tile": TILE, "levels": ub.LEVELS_HPA, "tiles": {k: v for k, (_, v) in tl.items()}}
        if a.dry_run:
            d = os.path.join(a.dry_run, run, f"{lead:02d}"); os.makedirs(d, exist_ok=True)
            for k, (b, _) in tl.items(): open(os.path.join(d, k + ".bin"), "wb").write(b)
        big = sorted(((len(b), k) for k, (b, _) in tl.items()), reverse=True)[:3]
        ub.log(f"PT{lead:02d} 区画 {len(tl)} 個 計 {sz/1e6:.0f}MB(大きい区画 {[(k, round(s/1e6, 2)) for s, k in big]})")
    if a.dry_run: json.dump(meta, open(os.path.join(a.dry_run, run, "meta.json"), "w"))
    ub.log(f"合計 {n} 個 {tot/1e6:.0f}MB {time.time()-t0:.0f}秒(1 回分)")

if __name__ == "__main__":
    main()
