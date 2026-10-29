# -*- coding: utf-8 -*-
"""P2-3 UI数据自动重建（薄壳）：读权威快照 -> 重写 index.html 的 JOBS 数据 -> 复发布
构建逻辑已收口到 job-workbench/jobs_build.py（与 build_workbench.py 共享同一实现）。
用法: python rebuild_ui.py [--publish]   (不带 --publish 只重建本地HTML不发布)
"""
import os, sys, subprocess, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "job-workbench"))
from jobs_build import build_from_snapshot

UI_DIR = r"<PROJECT_ROOT>\job-radar-ui"
SNAP = r"<PROJECT_ROOT>\job-agent\all_jobs_snapshot.ndjson"
INDEX = os.path.join(UI_DIR, "index.html")
APP_ID = "YOUR_APP_ID"

def main():
    try:
        n, changed = build_from_snapshot(SNAP, INDEX)
    except RuntimeError as e:
        print("!! %s" % e); return 1
    print(("[幂等] JOBS 已是快照最新，本地无需改写" if not changed else
           "UI数据已重建: %d 条 @ %s" % (n, datetime.datetime.now().strftime("%H:%M:%S"))))
    if "--publish" not in sys.argv:
        print("[preview] 未发布。加 --publish 复发布。"); return 0
    r = subprocess.run(["lark-cli", "apps", "+deploy", "--dir", ".", "--app-id", APP_ID, "--as", "user"],
                       cwd=UI_DIR, capture_output=True, text=True, encoding="utf-8")
    out = (r.stdout or "") + (r.stderr or "")
    m = re_search_id(out)
    if m:
        rid = m.group(1)
        print("发布受理 release_id =", rid)
        import time; time.sleep(5)
        r2 = subprocess.run(["lark-cli", "apps", "+release-get", "--app-id", APP_ID, "--release-id", rid, "--as", "user"],
                            cwd=UI_DIR, capture_output=True, text=True, encoding="utf-8")
        out2 = (r2.stdout or "") + (r2.stderr or "")
        st = re_search_status(out2)
        url = re_search_url(out2)
        print("发布状态:", st.group(1) if st else "?")
        print("在线链接:", url.group(1) if url else "（不变）")
    else:
        print("发布输出:", out[:300])
    return 0

def re_search_id(out):
    import re
    return re.search(r'"release_id": "(\d+)"', out)

def re_search_status(out):
    import re
    return re.search(r'"status":\s*"(\w+)"', out)

def re_search_url(out):
    import re
    return re.search(r'"online_url":\s*"([^"]+)"', out)

if __name__ == "__main__":
    sys.exit(main())
