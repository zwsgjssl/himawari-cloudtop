#!/usr/bin/env python3
# 会社経路の上の CAT の抜けを探す(2026-10-19 ユーザー「羽田千歳便、花巻の手前まで FL350〜390 くらいまでかなり揺れてる。AI は予想してないよね?」)。
#   AI が天気図で目立つ所ごとに claims の箱を作ると、箱と箱の間(東北の内陸など)に落ちた強い所が抜ける。
#   claims を書いた後に動かし、会社経路の上で UKMET のシアーが強く Ri が小さい層(既定: シアー 9kt/1000ft 以上かつ Ri 0.5 未満、FL250〜430)があるのに、
#   その高さに cat の claim が掛かっていない所を出す(v2026-10-20 ユーザー「TI1 廃止で Ri とシアーでいい」。前は TI1 の上位 2%)。
# 使い方: python3 tools/nwp_route_check.py --routes <approach-planner-private>/docs/routes_for_ai.json --ukmo /tmp/obs/ukmo --ai nwp_ai/ai.json
#   出力: 抜けている升(1° 四方)ごとに、時刻・TI1(順位)・シアー・芯・通る路線と FIX。何も無ければ「抜けなし」。
#   経路の文字列(RTE)は出さない(公開リポジトリの ai.json などに写さないため)。路線名・FIX 名だけ。
import argparse, datetime as dt, glob, json, math, os, sys

def T(s): return dt.datetime.strptime(s[:16], "%Y-%m-%dT%H:%M")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--routes", required=True); ap.add_argument("--ukmo", required=True); ap.add_argument("--ai", required=True)
    ap.add_argument("--vws", type=float, default=9.0, help="この シアー(kt/1000ft)以上"); ap.add_argument("--ri", type=float, default=0.5, help="この Ri 未満")
    a = ap.parse_args()
    R = json.load(open(a.routes)); R = R.get("routes", R)
    f = sorted(glob.glob(os.path.join(a.ukmo, "*.json")))
    if not f: sys.exit("UKMET のまとめがありません")
    U = json.load(open(f[-1])); ai = json.load(open(a.ai))
    cats = [c for c in ai.get("claims", []) if c.get("kind") == "cat" and c.get("box") and c.get("fl")]
    # 升ごとに、通る路線と FIX(区間を 10NM ごとに)
    cell = {}
    for pair, lst in R.items():
        for r in lst:
            P = r["pts"]
            for (n0, la0, lo0), (n1, la1, lo1) in zip(P, P[1:]):
                d = math.hypot(la1 - la0, (lo1 - lo0) * math.cos(math.radians((la0 + la1) / 2))) * 60
                k = max(1, int(d / 10))
                for i in range(k + 1):
                    la, lo = la0 + (la1 - la0) * i / k, lo0 + (lo1 - lo0) * i / k
                    c = cell.setdefault((math.floor(la), math.floor(lo)), {"routes": set(), "segs": set(), "pts": []})
                    c["routes"].add(r["name"]); c["segs"].add(f"{n0}〜{n1}"); c["pts"].append((la, lo))
    out = []
    for tk in ("t0", "f12"):
        s = U.get(tk)
        if not s: continue
        t = T(s["t"])
        if ai.get("base") and t < T(ai["base"]): continue   # 解析の回より前の時刻は見ない
        RF = U.get("ri_fl") or []
        for (i, j), c in sorted(cell.items()):
            k = f"{i},{j}"; vz, rz = (s.get("vwz") or {}).get(k), (s.get("riz") or {}).get(k)
            if not vz or not rz: continue
            hit = [(RF[q], vz[q], rz[q]) for q in range(min(len(RF), len(vz), len(rz))) if 250 <= RF[q] <= 430 and vz[q] is not None and rz[q] is not None and vz[q] >= a.vws and rz[q] < a.ri]
            if not hit: continue
            miss = []
            for fl_, v_, r_ in hit:
                ok = False
                for cl in cats:
                    b = cl["box"]; fl = cl["fl"]
                    if not (T(cl["from"]) <= t <= T(cl["to"])): continue
                    if not (min(fl) - 10 <= fl_ <= max(fl) + 10): continue
                    if any(b[0] <= la <= b[1] and b[2] <= lo <= b[3] for la, lo in c["pts"]): ok = True; break
                if not ok: miss.append((fl_, v_, r_))
            if not miss: continue
            out.append(f"{s['t']} 北緯 {i}〜{i+1}・東経 {j}〜{j+1}: " + "・".join(f"FL{f:03d} シアー {v} Ri {r}" for f, v, r in miss) + f"・芯 {s['jet'].get(k)}"
                       f" → {'・'.join(sorted(c['routes'])[:8])}{' ほか' if len(c['routes']) > 8 else ''}の {'・'.join(sorted(c['segs'])[:4])}")
    print(f"UKMET {U.get('run')}・ai.json {ai.get('base')}: 会社経路の上でシアー {a.vws:g} 以上・Ri {a.ri:g} 未満の層なのに、その高さに cat の claim が無い所" + ("" if U.get("ri_fl") else "(このまとめには高さごとの値がありません。次の回から)"))
    print("\n".join(out) if out else "抜けなし")

if __name__ == "__main__":
    main()
