# 雷予想の答え合わせ(2026-11-13、ユーザー「雷と降水って正確?」→「よろしく」)
# 3 時間ごとに: 今に近い UKMET の予報時刻の 対流性の雨・雪・CAPE・CIN・対流雲の量 と、その前後 30 分の気象庁の雷(雷監視 liden)を比べ、
# いくつかの決め方ごとに 当たり・空振り・見逃し を数えて ブランチ ltg-data の data/<日付>.jsonl に足す。数日たまったら一番当たる決め方を Map に入れる
import os, sys, json, re, datetime as dt, tempfile
import numpy as np, requests
sys.path.insert(0, os.path.dirname(__file__))
import ukmo_build as ub
UA = {"User-Agent": "skai-ltg-eval/1.0"}
NOWC = "https://www.jma.go.jp/bosai/jmatile/data/nowc"
def liden(t0, t1):
    tt = requests.get(NOWC + "/targetTimes_N3.json", headers=UA, timeout=30).json(); pts = []; used = []
    for e in tt:
        v = dt.datetime.strptime(e["validtime"], "%Y%m%d%H%M%S")
        if not (t0 <= v <= t1): continue
        r = requests.get(f"{NOWC}/{e['basetime']}/none/{e['validtime']}/surf/liden/data.geojson", headers=UA, timeout=30)
        if r.status_code != 200: continue
        used.append(e["validtime"])
        for f in r.json().get("features", []) if isinstance(r.json(), dict) else r.json():
            g = f.get("geometry") or {}
            if g.get("type") == "Point": pts.append(g["coordinates"][:2])
    return pts, used
def main():
    now = dt.datetime.utcnow()
    run = next(r for r in ub.list_runs(1) if ub.exists(ub.key_of(r, 6, ub.FILES["RH"]))[0])
    r0 = dt.datetime.strptime(run, "%Y%m%dT%H%MZ"); lead = int(round((now - r0).total_seconds() / 3600 / 3)) * 3
    while lead > 0 and r0 + dt.timedelta(hours=lead) > now - dt.timedelta(minutes=35): lead -= 3   # 前後 30 分の雷が出そろっている時刻
    V = r0 + dt.timedelta(hours=lead)
    pts, used = liden(V - dt.timedelta(minutes=30), V + dt.timedelta(minutes=30))
    print("回", run, "予報", lead, "時刻", V, "雷の点", len(pts), "画面", len(used), flush=True)
    F = {}
    names = {"cape": "CAPE_most_unstable_below_500hPa", "cin": "CIN_most_unstable_below_500hPa", "rc": "rainfall_rate_from_convection", "sc": "snowfall_rate_from_convection", "cc": "cloud_amount_of_total_convective_cloud", "pr": "precipitation_rate"}
    with tempfile.TemporaryDirectory() as w:
        for k, nm in names.items():
            p = os.path.join(w, k); ub.download(ub.key_of(run, lead, nm), p); lat, lon, a, u, _ = ub.cut(p, False)
            if k in ("rc", "sc", "pr"): a = ub.pr_mmh(a, u)
            if k == "cc" and np.nanmax(a) > 1.5: a = a / 100
            F[k] = np.nan_to_num(a); print(k, u, float(np.nanmax(a)), flush=True)
        # 2026-11-15 ユーザー「CAPE 以外の指標を組み合わせて推測するのは?」→ 気圧面の気温・湿度・風・鉛直流も取り、組み合わせの候補を足す(取れなければ候補なしで続ける)
        P3 = {}
        for k, nm in (("T", ub.FILES["T"]), ("RH", ub.FILES["RH"]), ("S", ub.FILES["S"]), ("D", ub.FILES["D"]), ("W", "wind_vertical_velocity_on_pressure_levels")):
            try:
                p = os.path.join(w, k); ub.download(ub.key_of(run, lead, nm), p); la3, lo3, a, u, _ = ub.cut(p, True); os.remove(p)
                if a.shape[1:] != F["cape"].shape: raise RuntimeError(f"格子が違う {a.shape}")
                P3[k] = a; P3[k + "_u"] = u; print(k, u, float(np.nanmin(a)), float(np.nanmax(a)), flush=True)
            except Exception as e: print("取れなかった", k, repr(e), flush=True)
    ny, nx = len(lat), len(lon); dlat, dlon = (lat[-1] - lat[0]) / (ny - 1), (lon[-1] - lon[0]) / (nx - 1)
    O = np.zeros((ny, nx), bool)
    for lo, la in pts:
        j, i = int(round((la - lat[0]) / dlat)), int(round((lo - lon[0]) / dlon))
        if 0 <= j < ny and 0 <= i < nx: O[j, i] = True
    # 気象庁の雷が届く範囲(日本の陸と近海)だけで数える: 雷の点が出せる範囲 = 北緯 24〜46・東経 123〜146 のうち、日本から 300km
    LA, LO = np.meshgrid(lat, lon, indexing="ij"); dom = (LA >= 24) & (LA <= 46) & (LO >= 123) & (LO <= 146)
    def grow(M, r):   # r 升(約 10km)の近く
        out = M.copy()
        for dj in range(-r, r + 1):
            for di in range(-r, r + 1):
                if dj*dj + di*di <= r*r: out |= np.roll(np.roll(M, dj, 0), di, 1)
        return out
    On = grow(O, 3)   # 雷から 30km 以内
    cp = F["rc"] + F["sc"]
    cands = {}
    for c in (50, 100, 200, 500, 1000): cands[f"cape{c}"] = F["cape"] >= c
    for t in (0.1, 0.3, 1, 3): cands[f"conv{t}"] = cp >= t
    for c in (0, 50, 100, 200, 500):
        for t in (0.1, 0.3, 1):
            cands[f"cape{c}_conv{t}"] = (F["cape"] >= c) & (cp >= t)
    for c in (0.3, 0.5): cands[f"cc{c}"] = F["cc"] >= c
    for c in (50, 100): cands[f"cape{c}_cc0.3"] = (F["cape"] >= c) & (F["cc"] >= 0.3)
    for c in (100,): cands[f"cape{c}_conv0.3_cin50"] = (F["cape"] >= c) & (cp >= 0.3) & (np.abs(F["cin"]) <= 50)
    # ---- 2026-11-15 組み合わせの候補(土台 = CAPE 100 か 500 以上 かつ 対流性の雨 0.3mm/h 以上)----
    #   ct20 = 雲(氷に対する湿度 95%、−20℃ 未満は 96.25% 以上)が −20℃ より冷たい高さまである(雲の中で氷・あられができる高さまで伸びている)
    #   w0.1/w0.2 = 700〜400hPa の上昇流の最大が 0.1・0.2 m/s 以上(持ち上げるきっかけ)、cv = 925・850hPa の収束 ×1e-5/s、rhm70 = 700〜500hPa の湿度の平均 70% 以上
    #   cin25 = CIN が 25 J/kg 以下、cxp = CAPE × 対流性の雨(J/kg × mm/h。雷の数の目安 Romps 2014)
    for t in (500, 2000, 5000): cands[f"cxp{t}"] = F["cape"]*cp >= t
    LV = np.array(ub.LEVELS_HPA, float); ex = {"cin25": np.abs(F["cin"]) <= 25}
    if "T" in P3 and "RH" in P3:
        Tc = P3["T"] - 273.15 if np.nanmean(P3["T"]) > 150 else P3["T"]; RH = P3["RH"]*100 if np.nanmax(P3["RH"]) <= 1.5 else P3["RH"].copy()
        cold = Tc < -40; p999 = float(np.nanpercentile(RH[cold], 99.9)) if cold.any() else 100.0
        if p999 < 95: RH = np.where(Tc < 0, RH*np.exp(17.67*Tc/(Tc + 243.5))/np.exp(22.46*Tc/(Tc + 272.62)), RH)   # ukmo_build.rh_bytes と同じ
        cl = RH >= np.where(Tc < -20, 96.25, 95.0)
        ex["ct20"] = np.any(cl & (Tc <= -20), axis=0)
        mi = (LV <= 700) & (LV >= 500); ex["rhm70"] = np.nanmean(RH[mi], axis=0) >= 70
    if "W" in P3:
        wi = (LV <= 700) & (LV >= 400); Wm = np.nanmax(P3["W"][wi], axis=0); ex["w0.1"] = Wm >= 0.1; ex["w0.2"] = Wm >= 0.2
    if "S" in P3 and "D" in P3:
        rad = np.deg2rad(P3["D"]); Uw, Vw = -P3["S"]*np.sin(rad), -P3["S"]*np.cos(rad)   # V は予報時刻なので別の名前
        if str(P3.get("S_u", "")).strip().lower() in ("kt", "knots", "knot"): Uw, Vw = Uw*0.5144, Vw*0.5144
        Rr = 6371e3; dy = Rr*np.deg2rad(dlat); dx = Rr*np.cos(np.deg2rad(lat))[:, None]*np.deg2rad(dlon)
        li = [k for k, p_ in enumerate(LV) if p_ in (925, 850)]
        dv = np.mean([np.gradient(Uw[k], axis=1)/dx + np.gradient(Vw[k], axis=0)/dy for k in li], axis=0)
        ex["cv1"] = -dv >= 1e-5; ex["cv3"] = -dv >= 3e-5
    for c in (100, 500):
        B = (F["cape"] >= c) & (cp >= 0.3)
        for k, M in ex.items(): cands[f"cape{c}_conv0.3_{k}"] = B & M
        for a_, b_ in (("ct20", "w0.1"), ("ct20", "rhm70"), ("ct20", "cin25"), ("w0.1", "rhm70")):
            if a_ in ex and b_ in ex: cands[f"cape{c}_conv0.3_{a_}_{b_}"] = B & ex[a_] & ex[b_]
    res = {"run": run, "lead": lead, "valid": V.strftime("%Y-%m-%dT%H:%MZ"), "n_ltg": len(pts), "frames": len(used), "obs_cells": int((O & dom).sum()), "c": {}}
    # 2026-11-15 陸と海を分けても数える(海の上は CAPE があっても雷になりにくい)。cl = 陸の升だけ、cs = 海の升だけ(同じ並び)
    land = None
    try:
        from global_land_mask import globe; land = globe.is_land(LA, np.where(LO > 180, LO - 360, LO))
        res["obs_land"] = int((O & dom & land).sum()); res["cl"] = {}; res["cs"] = {}
    except Exception as e: print("陸と海の区別なし", repr(e), flush=True)
    for k, M in cands.items():
        Fn = grow(M, 3)
        cnt = lambda D: [int((M & On & D).sum()), int((M & ~On & D).sum()), int((O & Fn & D).sum()), int((O & ~Fn & D).sum()), int((M & D).sum())]
        res["c"][k] = cnt(dom)   # 予報の升で当たり・空振り、雷の升で拾えた・見逃し、予報の升の数
        if land is not None: res["cl"][k] = cnt(dom & land); res["cs"][k] = cnt(dom & ~land)
    # 2026-11-24 ユーザー「(雷の点の場所も残すのは)いいね」→ 海域ごとに当たったか見られるように、雷のあった升を [経度, 緯度, Map の今の決まりの 30km 以内か(1/0)] で残す。
    #   Map の今の決まり = v349 の cape100_conv0.3_cv3。升の中心を 0.01° に丸める(同じ升は 1 つ)
    Mm = cands.get("cape100_conv0.3_cv3"); Fm = grow(Mm, 3) if Mm is not None else None
    jj, ii = np.where(O & dom)
    res["pts"] = [[round(float(lon[i]), 2), round(float(lat[j]), 2), int(bool(Fm[j, i])) if Fm is not None else -1] for j, i in zip(jj, ii)]
    print(json.dumps(res), flush=True)
    os.makedirs("out", exist_ok=True); open("out/line.json", "w").write(json.dumps(res) + "\n")
if __name__ == "__main__": main()
