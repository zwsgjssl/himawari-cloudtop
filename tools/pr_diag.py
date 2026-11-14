# 診断: Met Office 全球 10km(AWS)の 1 つの予報時刻にあるファイル名の一覧と、気圧面・高度面の段の数
import os, sys, re, tempfile, requests
sys.path.insert(0, os.path.dirname(__file__)); import ukmo_build as ub
run = [r for r in ub.list_runs(2) if ub.exists(ub.key_of(r, 6, ub.FILES["RH"]))[0]][0]
r = ub.s3req("GET", f"{ub.S3}/?list-type=2&prefix={ub.PREFIX}/{run}/&max-keys=1000"); keys = re.findall(r"<Key>([^<]+)</Key>", r.text)
names = sorted({re.sub(r"^.*PT\d{4}H00M-", "", k).replace(".nc", "") for k in keys if "PT0006H" in k}); print(run, "ファイル", len(names))
for n in names: print("  ", n)
import xarray as xr
with tempfile.TemporaryDirectory() as w:
    for n in names:
        if "height_levels" in n and ("wind" in n or "temperature" in n) or n == "temperature_on_pressure_levels":
            p = os.path.join(w, "x.nc"); ub.download(ub.key_of(run, 6, n), p)
            with xr.open_dataset(p, engine="h5netcdf", decode_times=False) as ds:
                for c in ds.coords:
                    if ds[c].ndim == 1 and ds[c].size < 200 and c not in ("latitude", "longitude"): print("  ", n, c, ds[c].size, [float(x) for x in ds[c].values][:80])
