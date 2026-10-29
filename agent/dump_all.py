# -*- coding: utf-8 -*-
"""分页拉取全部记录，解析为结构化行，导出 all_records_raw.json（原子写 + 时间戳副本）

并发安全（2026-10-24 加固）：
- 先写 all_records_raw.json.tmp，再 os.replace 原子替换 -> 任何读取方永远读到完整文件，
  不会再出现"写一半被读到 / 记录时有时无"。
- 同时保留 all_records_raw_<ts>.json 时间戳副本（最近 7 份，更旧的自动清理），供审计回溯。
"""
import subprocess, json, sys, os, glob, datetime

BASE = "YOUR_BASE_TOKEN"
TABLE = "YOUR_TABLE_ID"

def run(offset=0):
    cmd = ["lark-cli", "base", "+record-list",
           "--base-token", BASE, "--table-id", TABLE,
           "--page-size", "100", "--offset", str(offset), "--format", "json"]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    s = r.stdout.find("{")
    return json.loads(r.stdout[s:])

def cell_text(v):
    if v is None: return ""
    if isinstance(v, str): return v
    if isinstance(v, list):
        out = []
        for x in v:
            if isinstance(x, dict):
                out.append(x.get("text") or x.get("name") or x.get("link") or "")
            else:
                out.append(str(x))
        return " ".join(t for t in out if t)
    if isinstance(v, dict):
        return v.get("text") or v.get("name") or ""
    return str(v)

rows = []
offset = 0
while True:
    d = run(offset)["data"]
    fields = d["fields"]
    for rid, row in zip(d["record_id_list"], d["data"]):
        rec = {"record_id": rid}
        for name, val in zip(fields, row):
            rec[name] = cell_text(val)
        rows.append(rec)
    if not d.get("has_more"):
        break
    offset += len(d["data"])

body = json.dumps(rows, ensure_ascii=False, indent=1)
# 1) 时间戳副本（审计/回溯，保留最近 7 份）
ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
snap_path = f"all_records_raw_{ts}.json"
with open(snap_path, "w", encoding="utf-8", newline="\n") as f:
    f.write(body)
old_snaps = sorted(glob.glob("all_records_raw_*.json"))
for p in old_snaps[:-7]:
    try:
        os.remove(p)
    except OSError:
        pass
# 2) 主文件原子替换（tmp -> os.replace），读取方永不见半截文件
tmp_path = "all_records_raw.json.tmp"
with open(tmp_path, "w", encoding="utf-8", newline="\n") as f:
    f.write(body)
os.replace(tmp_path, "all_records_raw.json")
print(f"total: {len(rows)}")
print(f"snapshot: {snap_path}")
for r in rows:
    print(f'{r["record_id"]} | {r.get("职位名","")[:22]} | {r.get("公司","")[:18]} | 投={r.get("投递状态","")} | 反馈={r.get("投递反馈","")} | 日期={r.get("投递日期","")[:10]}')
