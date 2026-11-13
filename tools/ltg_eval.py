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
    res = {"run": run, "lead": lead, "valid": V.strftime("%Y-%m-%dT%H:%MZ"), "n_ltg": len(pts), "frames": len(used), "obs_cells": int((O & dom).sum()), "c": {}}
    for k, M in cands.items():
        Fn = grow(M, 3)
        h = int((M & On & dom).sum()); f = int((M & ~On & dom).sum()); m = int((O & ~Fn & dom).sum()); ho = int((O & Fn & dom).sum())
        res["c"][k] = [h, f, ho, m, int((M & dom).sum())]   # 予報の升で当たり・空振り、雷の升で拾えた・見逃し、予報の升の数
    print(json.dumps(res), flush=True)
    os.makedirs("out", exist_ok=True); open("out/line.json", "w").write(json.dumps(res) + "\n")
if __name__ == "__main__": main()
