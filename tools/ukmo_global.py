#!/usr/bin/env python3
# 2026-11-12 ユーザー「国際線用に対応させる方針で進めて」(世界のどの経路でも断面図・平面図を出すための全球の UKMET)
#   ukmo_build.py は日本付近だけを KV に置く(今のまま)。こちらは全球を間引いて 15° 四方の区画に分け、Cloudflare の R2 に置く。
#   Map は WX保存のとき、経路にかかる区画だけを取ってつなぐ(端末に入る量は今と同じくらい)。
#   格子: 10km(緯度 0.09375°・経度 0.140625°)を 緯度 3 つ・経度 2 つおきに間引く(約 0.28°、約 30km)。
#   1 区画・1 時刻 = ukmo_build.off_bytes と同じ形(UKO1: int16 [25][気温・東西風・南北風][ny][nx] + 圏界面、湿度 uint8 [25][ny][nx])。
# 使い方: python3 tools/ukmo_global.py --dry-run <フォルダ>(区画をフォルダに書き、大きさと時間を出す) / --r2(R2 に書く)
# R2(バケット skai-wx): 環境変数 R2_ACCESS_KEY_ID・R2_SECRET_ACCESS_KEY・CF_ACCOUNT_ID(GitHub の Secrets)
#   キー: gl/<回>/<予報時刻 2 桁>/<南端>_<西端>.bin、gl/<回>/meta.json、gl/latest.json(今の回と 1 つ前の回)
#   2026-11-12 ユーザー「超えそうなときに自動ストップと警告を通知する仕組みも」:
#     書く前に gl/usage-<YYYY-MM>.json(その月の書き込み回数)と、残っている回の大きさを見て、
#     書き込みが月 85 万回(無料 100 万回)・保存が 8GB(無料 10GB)を超えそうなら書かずに止める(処理は失敗 → GitHub から失敗のメール)。
#     Cloudflare の通知(Class A 70 万回・保存 7GB)とあわせて二重に守る。消すのは無料。
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

OPS_LIMIT, BYTES_LIMIT, KEEP = 850_000, 8e9, 2

class R2:
    def __init__(self):
        import boto3
        from botocore.config import Config
        acc = os.environ["CF_ACCOUNT_ID"]
        self.c = boto3.client("s3", endpoint_url=f"https://{acc}.r2.cloudflarestorage.com", region_name="auto",
                              aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"], aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
                              config=Config(retries={"max_attempts": 6, "mode": "standard"}, max_pool_connections=32))
        self.b = "skai-wx"; self.ops = 0
    def get_json(self, k):
        try: return json.loads(self.c.get_object(Bucket=self.b, Key=k)["Body"].read())
        except self.c.exceptions.NoSuchKey: return None
        except Exception as e:
            if "NoSuchKey" in str(e) or "404" in str(e): return None
            raise
    def put(self, k, body, ctype="application/octet-stream"):
        self.c.put_object(Bucket=self.b, Key=k, Body=body, ContentType=ctype); self.ops += 1
    def delete_many(self, keys):
        for i in range(0, len(keys), 1000):
            self.c.delete_objects(Bucket=self.b, Delete={"Objects": [{"Key": k} for k in keys[i:i+1000]], "Quiet": True})

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--dry-run", default=""); ap.add_argument("--leads", default=""); ap.add_argument("--r2", action="store_true")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    r2 = R2() if a.r2 else None
    run = next((r for r in ub.list_runs(2) if ub.run_ready(r)), None)
    if not run: ub.log("回がありません"); return
    leads = [int(x) for x in a.leads.split(",")] if a.leads else ub.LEADS
    ub.log(f"回 {run} 予報時刻 {leads}")
    if r2:
        latest = r2.get_json("gl/latest.json") or {}
        if latest.get("run") == run and not a.force: ub.log(f"R2 はもう {run} です。何もしません"); return
        month = dt.datetime.utcnow().strftime("%Y-%m"); uk = f"gl/usage-{month}.json"
        use = r2.get_json(uk) or {"month": month, "puts": 0}
        need = len(leads) * 288 + 4
        kept = sum((latest.get("bytes") or {}).values()) if latest else 0
        ub.log(f"今月の書き込み {use['puts']} 回(上限 {OPS_LIMIT})・今ある回の大きさ {kept/1e9:.2f}GB(上限 {BYTES_LIMIT/1e9:.0f}GB)")
        if use["puts"] + need > OPS_LIMIT: raise SystemExit(f"止めました: 今月の書き込みが {use['puts']}+{need} 回で上限 {OPS_LIMIT} を超えます(無料 100 万回)")
        if kept + 0.6e9 > BYTES_LIMIT: raise SystemExit(f"止めました: 保存が {kept/1e9:.2f}GB で上限 {BYTES_LIMIT/1e9:.0f}GB を超えそうです(無料 10GB)")
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
        if r2:
            t1 = time.time()
            with ThreadPoolExecutor(16) as ex: list(ex.map(lambda kv: r2.put(f"gl/{run}/{lead:02d}/{kv[0]}.bin", kv[1][0]), tl.items()))
            ub.log(f"PT{lead:02d} R2 に {len(tl)} 個 {time.time()-t1:.0f}秒")
        big = sorted(((len(b), k) for k, (b, _) in tl.items()), reverse=True)[:3]
        ub.log(f"PT{lead:02d} 区画 {len(tl)} 個 計 {sz/1e6:.0f}MB(大きい区画 {[(k, round(s/1e6, 2)) for s, k in big]})")
    if a.dry_run: json.dump(meta, open(os.path.join(a.dry_run, run, "meta.json"), "w"))
    if r2:
        meta["leads"] = leads; meta["bytes"] = tot
        r2.put(f"gl/{run}/meta.json", json.dumps(meta).encode(), "application/json")
        runs = [run] + [x for x in (latest.get("runs") or []) if x != run]
        sizes = dict(latest.get("bytes") or {}); sizes[run] = tot
        old = runs[KEEP:]; runs = runs[:KEEP]
        r2.put("gl/latest.json", json.dumps({"run": run, "runs": runs, "leads": leads, "tile": TILE, "bytes": {k: sizes[k] for k in runs},
                                             "at": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ")}).encode(), "application/json")
        for o in old:   # 古い回を消す(消すのは無料)
            om = r2.get_json(f"gl/{o}/meta.json") or {}
            keys = [f"gl/{o}/{l:02d}/{k}.bin" for l in (om.get("leads") or ub.LEADS) for k in (om.get("tiles") or {})] + [f"gl/{o}/meta.json"]
            r2.delete_many(keys); ub.log(f"古い回 {o} を消しました({len(keys)} 個)")
        use["puts"] += r2.ops + 1; r2.put(uk, json.dumps(use).encode(), "application/json")
        ub.log(f"今月の書き込み {use['puts']} 回")
    ub.log(f"合計 {n} 個 {tot/1e6:.0f}MB {time.time()-t0:.0f}秒(1 回分)")

if __name__ == "__main__":
    main()
