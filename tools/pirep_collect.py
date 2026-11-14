# 公開の PIREP / AIREP を集める(2026-11-14 ユーザー「CAT の精度を上げたい」→「PIREP をまず集める仕組みから」)
# aviationweather.gov(米国気象局)の Data API の公開データだけ。会社の PIREP は使わない。
# 6 時間ごとに直近 30 時間分を取り、すでに持っている報告(生の文 + 観測時刻)は足さない。ブランチ pirep-data の data/<年月>.jsonl に 1 行 1 報告
import os, sys, json, glob, datetime as dt, requests
UA = {"User-Agent": "skai-pirep-collect/1.0"}
URL = "https://aviationweather.gov/api/data/pirep"
BOX = "20,110,55,160"   # 南,西,北,東: 日本付近と北太平洋の入り口(国際線の出発・到着の区間も)
def key(x): return (x.get("rawOb") or "") + "|" + str(x.get("obsTime"))
def main(d):
    r = requests.get(URL, params={"format": "json", "bbox": BOX, "age": int(os.environ.get("AGE") or 30)}, headers=UA, timeout=90); r.raise_for_status()
    L = r.json(); L = L if isinstance(L, list) else (L.get("data") or [])
    have = set()
    for f in glob.glob(os.path.join(d, "*.jsonl")):
        for ln in open(f, encoding="utf-8"):
            try: have.add(key(json.loads(ln)))
            except Exception: pass
    new = {}
    for x in L:
        if not isinstance(x, dict) or x.get("obsTime") is None or key(x) in have: continue
        have.add(key(x)); m = dt.datetime.utcfromtimestamp(int(x["obsTime"])).strftime("%Y%m")
        new.setdefault(m, []).append(x)
    os.makedirs(d, exist_ok=True)
    for m, a in new.items():
        a.sort(key=lambda x: x["obsTime"])
        with open(os.path.join(d, m + ".jsonl"), "a", encoding="utf-8") as f:
            for x in a: f.write(json.dumps(x, ensure_ascii=False, separators=(",", ":")) + "\n")
    n = sum(len(a) for a in new.values()); tb = sum(1 for a in new.values() for x in a if x.get("tbInt1"))
    print(f"取得 {len(L)} 件、新しく {n} 件(揺れの記載あり {tb})、持っている合計 {len(have)}")
if __name__ == "__main__": main(sys.argv[1] if len(sys.argv) > 1 else "data")
