#!/usr/bin/env python3
# 会社経路の上の CAT の抜けを探す(2026-10-19 ユーザー「羽田千歳便、花巻の手前まで FL350〜390 くらいまでかなり揺れてる。AI は予想してないよね?」)。
#   AI が天気図で目立つ所ごとに claims の箱を作ると、箱と箱の間(東北の内陸など)に落ちた強い所が抜ける。
#   claims を書いた後に動かし、会社経路の上で UKMET の TI1 が日本付近の上位 2% 以上なのに、cat の claim が掛かっていない所を出す。
# 使い方: python3 tools/nwp_route_check.py --routes <approach-planner-private>/docs/routes_for_ai.json --ukmo /tmp/obs/ukmo --ai nwp_ai/ai.json
#   出力: 抜けている升(1° 四方)ごとに、時刻・TI1(順位)・シアー・芯・通る路線と FIX。何も無ければ「抜けなし」。
#   経路の文字列(RTE)は出さない(公開リポジトリの ai.json などに写さないため)。路線名・FIX 名だけ。
import argparse, datetime as dt, glob, json, math, os, sys

def T(s): return dt.datetime.strptime(s[:16], "%Y-%m-%dT%H:%M")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--routes", required=True); ap.add_argument("--ukmo", required=True); ap.add_argument("--ai", required=True)
    ap.add_argument("--pct", default="98", help="この順位(上位 2% = 98)以上を見る")
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
        th = U["ti1_dist"][tk]["pct"]; lim = th[a.pct]; t = T(s["t"])
        if ai.get("base") and t < T(ai["base"]): continue   # 解析の回より前の時刻は見ない
        for (i, j), c in sorted(cell.items()):
            k = f"{i},{j}"; v = s["ti1"].get(k)
            if v is None or v < lim: continue
            covered = False
            for cl in cats:
                b = cl["box"]; fl = cl["fl"]
                if not (T(cl["from"]) <= t <= T(cl["to"])): continue
                if max(fl) < 300: continue   # 巡航の高さに掛かっていない
                if any(b[0] <= la <= b[1] and b[2] <= lo <= b[3] for la, lo in c["pts"]): covered = True; break
            if covered: continue
            tier = "上位 0.5% 超" if v >= th["99.5"] else "上位 1%" if v >= th["99"] else "上位 2%"
            out.append(f"{s['t']} 北緯 {i}〜{i+1}・東経 {j}〜{j+1}: TI1 {v}({tier})・シアー {s['vws'].get(k)}・芯 {s['jet'].get(k)}"
                       f" → {'・'.join(sorted(c['routes'])[:8])}{' ほか' if len(c['routes']) > 8 else ''}の {'・'.join(sorted(c['segs'])[:4])}")
    print(f"UKMET {U.get('run')}・ai.json {ai.get('base')}: 会社経路の上で TI1 上位 {100 - float(a.pct):g}% 以上なのに cat の claim が無い所")
    print("\n".join(out) if out else "抜けなし")

if __name__ == "__main__":
    main()
