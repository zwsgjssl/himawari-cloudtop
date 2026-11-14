# 診断: 降水短時間予報の targetTimes の中身(immed / none の回と要素)を 10 分おきに 4 回見る
import json, time, requests, collections
UA = {"User-Agent": "skai-diag/1.0"}; B = "https://www.jma.go.jp/bosai/jmatile/data/rasrf/targetTimes.json"
for k in range(4):
    L = requests.get(B, headers=UA, timeout=30).json(); g = collections.defaultdict(list)
    for e in L: g[(e["basetime"], e["member"])].append(e)
    print("== 取得", time.strftime("%H:%M:%SZ", time.gmtime()), "件数", len(L))
    for (b, m), a in sorted(g.items())[-8:]:
        els = sorted({x for e in a for x in e["elements"]}); print("  ", b, m, len(a), min(e["validtime"] for e in a)[8:12], "→", max(e["validtime"] for e in a)[8:12], els)
    if k < 3: time.sleep(600)
