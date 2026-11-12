# 調べ用: 最新の回で 雲頂UK(v287 の作り方)とひまわりの雲頂を地図で並べ、2 つの箱(本州の南の海・台湾の北東)の湿度の縦の様子を出す
import os, sys, json, datetime as dt, tempfile
import numpy as np
sys.path.insert(0, os.path.dirname(__file__))
import ukmo_build as ub, himawari_build as hb, ct_study as cs
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
def main():
    runs = ub.list_runs(1); run = next(r for r in runs if ub.exists(ub.key_of(r, 6, ub.FILES["RH"]))[0])
    now = dt.datetime.utcnow(); r0 = dt.datetime.strptime(run, "%Y%m%dT%H%MZ")
    lead = max(0, min(21, int(round((now - r0).total_seconds()/3600/3))*3 - 3))
    valid = r0 + dt.timedelta(hours=lead); ht, hk = cs.hima_at(valid); print("回", run, "予報", lead, "ひまわり", ht, flush=True)
    with tempfile.TemporaryDirectory() as w:
        P = {}
        for k in ("T", "RH"): P[k] = os.path.join(w, k); ub.download(ub.key_of(run, lead, ub.FILES[k]), P[k])
        lat, lon, T, _, _ = ub.cut(P["T"], True); _, _, RH, _, _ = ub.cut(P["RH"], True)
        Tc = T - 273.15 if np.nanmean(T) > 150 else T
        if np.nanmax(RH) <= 1.5: RH = RH * 100
        R = cs.rh_ice(RH, Tc)
        hp = os.path.join(w, "h"); hb.download(hk, hp); H, grid, src, _ = hb.build(hp)
    t50 = cs.top_cum(R, Tc, 50); t25 = cs.top_cum(R, Tc, 25); ct = np.where(t50 > 0, t50, t25); lev = cs.top_level(R, Tc, 95, 96.25)[0]
    Hf = np.where((H > 0) & (H < 255), H * 2.0, np.where(H == 0, 0, np.nan))
    hl = grid["lat0"] + grid["dlat"] * np.arange(grid["ny"]); hlo = grid["lon0"] + grid["dlon"] * np.arange(grid["nx"])
    fig, ax = plt.subplots(1, 3, figsize=(21, 7))
    for a, (Z, la, lo, tt) in zip(ax, [(Hf, hl, hlo, "Himawari"), (ct, lat, lon, "UK v287 cum50/25"), (lev, lat, lon, "UK old lev95")]):
        Zm = np.where(Z > 0, Z, np.nan); im = a.pcolormesh(lo, la, Zm, vmin=0, vmax=450, cmap="jet", shading="auto"); a.set_title(tt); a.set_aspect(1.2); fig.colorbar(im, ax=a, shrink=.7)
        for (y0, y1, x0, x1) in ((29, 33, 133, 140), (24, 28, 122, 127)): a.plot([x0, x1, x1, x0, x0], [y0, y0, y1, y1, y0], "k-")
    os.makedirs("out", exist_ok=True); fig.savefig("out/ct_map.png", dpi=70, bbox_inches="tight")
    rep = {}
    rh_raw = RH
    for name, (y0, y1, x0, x1) in {"south_honshu": (29, 33, 133, 140), "ne_taiwan": (24, 28, 122, 127)}.items():
        m = (lat[:, None] >= y0) & (lat[:, None] <= y1) & (lon[None, :] >= x0) & (lon[None, :] <= x1)
        hm = (hl[:, None] >= y0) & (hl[:, None] <= y1) & (hlo[None, :] >= x0) & (hlo[None, :] <= x1)
        hv = Hf[hm]; hv = hv[np.isfinite(hv)]
        prof = [(int(p), round(float(np.mean(Tc[k][m])), 1), round(float(np.mean(rh_raw[k][m])), 1), round(float(np.mean(R[k][m])), 1), round(float(np.mean(cs.cf_sund(R, Tc)[k][m])), 2)) for k, p in enumerate(ub.LEVELS_HPA)]
        rep[name] = {"hima_cloud_frac": float(np.mean(hv > 0)) if hv.size else None, "hima_fl_pct": [float(np.percentile(hv[hv > 0], q)) for q in (10, 50, 90)] if np.any(hv > 0) else None,
                     "uk_cloud_frac": float(np.mean(ct[m] > 0)), "uk_fl_pct": [float(np.percentile(ct[m][ct[m] > 0], q)) for q in (10, 50, 90)] if np.any(ct[m] > 0) else None,
                     "uk_lt100_frac": float(np.mean((ct[m] > 0) & (ct[m] < 100))), "profile_p_T_RHraw_RHice_cf": prof}
    print(json.dumps(rep, indent=1), flush=True); json.dump(rep, open("out/ct_look.json", "w"), indent=1)
if __name__ == "__main__": main()
