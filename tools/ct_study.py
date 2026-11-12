# 調べ用(2026-11-12): UKMET の湿度から出す雲頂(雲頂UK)を、ひまわりの雲頂(NOAA AHI-L2 CHGT)と比べて、どの作り方が近いかを測る
import os, sys, re, json, time, tempfile, datetime as dt
import numpy as np, requests
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
import ukmo_build as ub, himawari_build as hb
FL = np.array([145366.45 * (1 - (p / 1013.25) ** 0.190284) / 100 for p in ub.LEVELS_HPA])
def log(*a): print(*a, flush=True)
def names(run, lead):
    valid = (dt.datetime.strptime(run, "%Y%m%dT%H%MZ") + dt.timedelta(hours=lead)).strftime("%Y%m%dT%H%MZ")
    pre = f"{ub.PREFIX}/{run}/{valid}-PT{lead:04d}H00M-"
    r = ub.s3req("GET", ub.S3 + "/", params={"list-type": "2", "prefix": pre}); r.raise_for_status()
    return sorted(set(k[len(pre):] for k in re.findall(r"<Key>([^<]+)</Key>", r.text)))
def hima_at(t):
    for dm in (0, 10, -10, 20, -20):
        tt = t + dt.timedelta(minutes=dm); pre = f"{hb.PREFIX}/{tt:%Y/%m/%d/%H%M}/"
        r = requests.get(hb.S3 + "/", params={"list-type": "2", "prefix": pre}, headers=hb.UA, timeout=60); r.raise_for_status()
        k = sorted(re.findall(r"<Key>([^<]*AHI-CHGT[^<]*\.nc)</Key>", r.text))
        if k: return tt, k[-1]
    return None, None
def rh_ice(RH, Tc):   # ukmo_build.rh_bytes と同じ(0℃ 未満は氷に対する値に)
    b, mode = ub.rh_bytes(RH, Tc, 0); return np.frombuffer(b, dtype="u1").reshape(RH.shape).astype("f4")
def top_level(R, Tc, thr_w, thr_i):   # 上から見て最初に RH ≥ しきい値の面(今のやり方)
    thr = np.where(Tc < -20, thr_i, thr_w); cl = (R >= thr) & (R != 255)
    L = R.shape[0]; idx = L - 1 - np.argmax(cl[::-1], axis=0); has = cl.any(axis=0)
    return np.where(has, FL[idx], 0.0), idx, has, thr
def top_interp(R, Tc, thr_w, thr_i):   # 上の面との間でしきい値を横切る高さを直線で
    ct, idx, has, thr = top_level(R, Tc, thr_w, thr_i); L = R.shape[0]
    up = np.minimum(idx + 1, L - 1); yy, xx = np.indices(idx.shape)
    r0, r1 = R[idx, yy, xx], R[up, yy, xx]; t0 = thr[idx, yy, xx]
    f = np.clip((r0 - t0) / np.maximum(1e-3, r0 - r1), 0, 1); f = np.where((up > idx) & (r1 < t0) & (r1 != 255), f, 0)
    return np.where(has, FL[idx] + f * (FL[up] - FL[idx]), 0.0)
def cf_amount_top(CA, frac):
    cl = CA >= frac; L = CA.shape[0]; idx = L - 1 - np.argmax(cl[::-1], axis=0); has = cl.any(axis=0)
    return idx, has
def cut_h(path):
    """cloud_amount_on_height_levels → (lat, lon, CA[H,ny,nx] 0〜1, 高さ m)"""
    import xarray as xr
    with xr.open_dataset(path, engine="h5netcdf", decode_times=False) as ds:
        name = ub.main_var(ds); da = ds[name]
        la, lo = ub.dim_like(da, ["lat"]), ub.dim_like(da, ["lon"]); hz = [d for d in da.dims if d not in (la, lo) and da.sizes[d] > 1][0]
        for d in da.dims:
            if d not in (la, lo, hz) and da.sizes[d] == 1: da = da.isel({d: 0})
        lat = np.asarray(ds[la].values, dtype="f8"); lon = np.asarray(ds[lo].values, dtype="f8"); lon = np.where(lon > 180, lon - 360, lon)
        yi = np.where((lat >= ub.LAT0 - 1e-6) & (lat <= ub.LAT1 + 1e-6))[0]; xi = np.where((lon >= ub.LON0 - 1e-6) & (lon <= ub.LON1 + 1e-6))[0]; xi = xi[np.argsort(lon[xi])]
        h = np.asarray(ds[hz].values, dtype="f8") if hz in ds else np.arange(da.sizes[hz])
        arr = da.isel({la: yi, lo: xi}).transpose(hz, la, lo).values.astype("f4")
        log("高さの面", hz, list(np.round(h).astype(int)), "単位", ds[hz].attrs.get("units", "") if hz in ds else "", "値", float(np.nanmin(arr)), float(np.nanmax(arr)))
        la_s = lat[yi]; order = np.argsort(la_s)
    if np.nanmax(arr) > 1.5: arr = arr / 100
    return la_s[order], lon[xi], arr[:, order, :], h
def ca_top(CA, h, Z, frac):
    """雲量の面で、上から見て最初に雲量 ≥ frac の高さ(上の面との間で直線)→ 気圧(ジオポテンシャル高度で)→ FL"""
    cl = CA >= frac; Hn = CA.shape[0]; idx = Hn - 1 - np.argmax(cl[::-1], axis=0); has = cl.any(axis=0)
    up = np.minimum(idx + 1, Hn - 1); yy, xx = np.indices(idx.shape); c0, c1 = CA[idx, yy, xx], CA[up, yy, xx]
    f = np.where(up > idx, np.clip((c0 - frac) / np.maximum(1e-3, c0 - c1), 0, 1), 0); zt = h[idx] + f * (h[up] - h[idx])
    # Z[L,ny,nx] = 気圧面の高さ(m)。zt を挟む面で log p を直線
    lp = np.log(np.array(ub.LEVELS_HPA, dtype="f8")); fl = np.zeros(zt.shape)
    for L in range(len(ub.LEVELS_HPA) - 1):
        a, b = Z[L], Z[L + 1]; m = (zt >= a) & (zt < b)
        w = (zt - a) / np.maximum(1e-3, b - a); p = np.exp(lp[L] + w * (lp[L + 1] - lp[L]))
        fl = np.where(m, 145366.45 * (1 - (p / 1013.25) ** 0.190284) / 100, fl)
    fl = np.where(zt < Z[0], zt * 3.28084 / 100, fl); fl = np.where(zt >= Z[-1], FL[-1], fl)
    return np.where(has, fl, 0.0)
def main():
    runs = [r for r in ub.list_runs(2)][:6]; ok = [r for r in runs if ub.exists(ub.key_of(r, 6, ub.FILES["RH"]))[0]][:2]
    log("回", ok); res = {"cases": [], "files": {}}
    for run in ok:
        res["files"][run] = names(run, 0); log("PT00 のファイル", res["files"][run])
    cases = [(r, l) for r in ok for l in (0, 3, 6)][:5]
    allA = {}
    for run, lead in cases:
        valid = dt.datetime.strptime(run, "%Y%m%dT%H%MZ") + dt.timedelta(hours=lead)
        ht, hk = hima_at(valid)
        if not hk: log(valid, "ひまわりが無い"); continue
        with tempfile.TemporaryDirectory() as w:
            P = {}
            for k in ("T", "RH"):
                P[k] = os.path.join(w, k + ".nc"); ub.download(ub.key_of(run, lead, ub.FILES[k]), P[k])
            lat, lon, T, uT, _ = ub.cut(P["T"], True); _, _, RH, _, _ = ub.cut(P["RH"], True)
            Tc = T - 273.15 if np.nanmean(T) > 150 else T
            if np.nanmax(RH) <= 1.5: RH = RH * 100
            R = rh_ice(RH, Tc)
            CA = None
            try:
                p = os.path.join(w, "CA.nc"); ub.download(ub.key_of(run, lead, "cloud_amount_on_height_levels"), p); la2, lo2, CAh, hh = cut_h(p)
                p2 = os.path.join(w, "Z.nc"); ub.download(ub.key_of(run, lead, "geopotential_height_on_pressure_levels"), p2); _, _, Zp, _, _ = ub.cut(p2, True)
                if CAh.shape[1:] == T.shape[1:]: CA = (CAh, hh, Zp)
                else: log("格子が違う", CAh.shape, T.shape)
            except Exception as e: log("雲量の面が読めない", repr(e)); CA = None
            hp = os.path.join(w, "h.nc"); hb.download(hk, hp); H, grid, src, _ = hb.build(hp)
        # ひまわり(0.05°)を UKMET の格子の点に: 近い 3x3 の雲のある画素の平均 FL と雲の割合
        Hf = np.where((H > 0) & (H < 255), H.astype("f4") * 2, np.nan); valid_h = H < 255
        iy = np.clip(np.rint((lat - grid["lat0"]) / grid["dlat"]).astype(int), 1, grid["ny"] - 2); ix = np.clip(np.rint((lon - grid["lon0"]) / grid["dlon"]).astype(int), 1, grid["nx"] - 2)
        IY, IX = np.meshgrid(iy, ix, indexing="ij")
        st = np.stack([Hf[IY + a, IX + b] for a in (-1, 0, 1) for b in (-1, 0, 1)]); vv = np.stack([valid_h[IY + a, IX + b] for a in (-1, 0, 1) for b in (-1, 0, 1)])
        hfrac = np.sum(np.isfinite(st), 0) / np.maximum(1, np.sum(vv, 0)); hfl = np.nanmedian(st, 0)
        good = np.sum(vv, 0) >= 7
        meth = {}
        for tw, ti in ((95, 96.25), (90, 92.5)):
            meth[f"lev{tw}"] = top_level(R, Tc, tw, ti)[0]; meth[f"int{tw}"] = top_interp(R, Tc, tw, ti)
        if CA is not None:
            for fr in (0.05, 0.1, 0.2, 0.3, 0.5): meth[f"ca{int(fr*100)}"] = ca_top(CA[0], CA[1], CA[2], fr)
        for tw, ti in ((98, 99), (100, 100), (102, 102), (105, 105)):
            meth[f"lev{tw}"] = top_level(R, Tc, tw, ti)[0]
        hcl = good & (hfrac >= 0.5); hclr = good & (hfrac <= 0.1)
        case = {"run": run, "lead": lead, "hima": f"{ht:%H%MZ}", "n": int(good.sum()), "hima_cloudy": float(hcl.sum() / max(1, good.sum())), "m": {}}
        for k, ct in meth.items():
            uc = ct > 0; both = hcl & uc & (hfl >= 100)
            d = (ct - hfl)[both]
            case["m"][k] = {"pod": float((hcl & uc).sum() / max(1, hcl.sum())), "far": float((hclr & uc).sum() / max(1, (good & uc).sum())),
                            "bias": float(np.mean(d)) if d.size else None, "mae": float(np.mean(np.abs(d))) if d.size else None,
                            "w30": float(np.mean(np.abs(d) <= 30)) if d.size else None, "n": int(d.size)}
            allA.setdefault(k, []).append(d)
        res["cases"].append(case); log(json.dumps(case, ensure_ascii=False))
    summ = {}
    for k, ds in allA.items():
        d = np.concatenate(ds) if ds else np.array([])
        summ[k] = {"bias": float(np.mean(d)) if d.size else None, "mae": float(np.mean(np.abs(d))) if d.size else None, "w30": float(np.mean(np.abs(d) <= 30)) if d.size else None,
                   "pod": float(np.mean([c["m"][k]["pod"] for c in res["cases"] if k in c["m"]])), "far": float(np.mean([c["m"][k]["far"] for c in res["cases"] if k in c["m"]]))}
    res["summary"] = summ; log("まとめ"); [log(k, json.dumps(v)) for k, v in summ.items()]
    os.makedirs("out", exist_ok=True); json.dump(res, open("out/ct_study.json", "w"), ensure_ascii=False, indent=1)
if __name__ == "__main__": main()
