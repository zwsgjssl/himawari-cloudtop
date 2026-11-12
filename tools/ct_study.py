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
            fn = [f for f in res["files"].get(run, []) if re.search(r"cloud_amount_on_pressure_levels|cloud_volume_fraction_on_pressure", f)]
            if fn:
                p = os.path.join(w, "CA.nc"); ub.download(ub.key_of(run, lead, fn[0][:-3] if fn[0].endswith(".nc") else fn[0]), p)
                try: _, _, CA, _, _ = ub.cut(p, True); CA = CA / 100 if np.nanmax(CA) > 1.5 else CA
                except Exception as e: log("雲量の面が読めない", e); CA = None
            hp = os.path.join(w, "h.nc"); hb.download(hk, hp); H, grid, src, _ = hb.build(hp)
        # ひまわり(0.05°)を UKMET の格子の点に: 近い 3x3 の雲のある画素の平均 FL と雲の割合
        Hf = np.where((H > 0) & (H < 255), H.astype("f4") * 2, np.nan); valid_h = H < 255
        iy = np.clip(np.rint((lat - grid["lat0"]) / grid["dlat"]).astype(int), 1, grid["ny"] - 2); ix = np.clip(np.rint((lon - grid["lon0"]) / grid["dlon"]).astype(int), 1, grid["nx"] - 2)
        IY, IX = np.meshgrid(iy, ix, indexing="ij")
        st = np.stack([Hf[IY + a, IX + b] for a in (-1, 0, 1) for b in (-1, 0, 1)]); vv = np.stack([valid_h[IY + a, IX + b] for a in (-1, 0, 1) for b in (-1, 0, 1)])
        hfrac = np.sum(np.isfinite(st), 0) / np.maximum(1, np.sum(vv, 0)); hfl = np.nanmax(st, 0)
        good = np.sum(vv, 0) >= 7
        meth = {}
        for tw, ti in ((95, 96.25), (90, 92.5), (85, 88.75), (80, 85), (75, 81.25), (70, 77.5)):
            meth[f"lev{tw}"] = top_level(R, Tc, tw, ti)[0]; meth[f"int{tw}"] = top_interp(R, Tc, tw, ti)
        if CA is not None:
            for fr in (0.1, 0.3, 0.5):
                idx, has = cf_amount_top(CA, fr); meth[f"ca{int(fr*100)}"] = np.where(has, FL[idx], 0.0)
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
