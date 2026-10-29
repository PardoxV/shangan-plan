# -*- coding: utf-8 -*-
"""高德通勤实测：YOUR_HOME_PLACE3栋(YOUR_LNG,YOUR_LAT) -> 岗位门址，输出骑行/公交分钟"""
import json, io, sys, urllib.parse, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
KEY = "YOUR_AMAP_KEY"
ORIGIN = "YOUR_LNG,YOUR_LAT"
CITY = "成都"

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))

def geocode(addr):
    q = urllib.parse.quote(addr)
    d = get("https://restapi.amap.com/v3/geocode/geo?address=%s&city=%s&key=%s" % (q, urllib.parse.quote(CITY), KEY))
    if d.get("status") == "1" and d.get("geocodes"):
        g = d["geocodes"][0]
        return g["location"], g.get("level", ""), g.get("formatted_address", "")
    # POI 文本搜索兜底
    p = get("https://restapi.amap.com/v3/place/text?keywords=%s&city=%s&key=%s&offset=5" % (urllib.parse.quote(addr[:30]), urllib.parse.quote(CITY), KEY))
    if p.get("status") == "1" and p.get("pois"):
        g = p["pois"][0]
        return g["location"], "poi:" + g.get("type", ""), g.get("address", "") or g.get("name", "")
    return None, "", ""

def ride(dest):
    d = get("https://restapi.amap.com/v3/direction/bicycling?origin=%s&destination=%s&key=%s" % (ORIGIN, dest, KEY))
    if d.get("status") == "1" and d.get("route", {}).get("paths"):
        return float(d["route"]["paths"][0]["duration"]) / 60.0
    return None

def transit(dest):
    d = get("https://restapi.amap.com/v3/direction/transit/integrated?origin=%s&destination=%s&city=%s&key=%s" % (ORIGIN, dest, urllib.parse.quote(CITY), KEY))
    if d.get("status") == "1" and d.get("route", {}).get("transits"):
        t = d["route"]["transits"][0]
        return float(t["duration"]) / 60.0, t.get("walking_distance", "")
    return None, ""

def measure(addr):
    loc, lvl, fa = geocode(addr)
    if not loc:
        return {"地址精度": "失败", "备注": "geocode失败: " + addr[:40]}
    out = {"地址精度": lvl, "标准地址": fa}
    r = ride(loc)
    if r is not None:
        out["骑行分钟"] = round(r, 1)
        out["骑行结论"] = "达标" if r <= 30 else "超标"
    t, wd = transit(loc)
    if t is not None:
        out["公交分钟"] = round(t, 1)
        out["步行米"] = wd
        out["公交结论"] = "达标" if t <= 60 else "超标"
    if r is None and t is None:
        out["备注"] = "高德路由无结果"
    return out

if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "scan_20261022_platform.json"
    out = sys.argv[2] if len(sys.argv) > 2 else "commute_20261022.json"
    with io.open(src, encoding="utf-8") as f:
        scan = json.load(f)
    res = []
    for c in scan.get("candidates", []):
        addr = (c.get("工作地址") or "").strip()
        item = {"职位名": c.get("职位名", ""), "公司": c.get("公司", "")}
        if not addr:
            item["地址精度"] = "无门址"
            item["备注"] = "详情页未提供具体门址，fail-closed 待核"
        else:
            item.update(measure(addr))
        res.append(item)
    with io.open(out, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    for r in res:
        print("%s | %s | 精度=%s | 骑行=%s | 公交=%s" % (r["公司"], r["职位名"][:20], r.get("地址精度", ""), r.get("骑行分钟", ""), r.get("公交分钟", "")))
