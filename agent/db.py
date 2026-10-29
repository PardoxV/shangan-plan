# -*- coding: utf-8 -*-
"""
求职Agent · 统一实体模型（SQLite）
==================================
把散落在十几个 JSON 的岗位/公司/投递/反馈收拢为一张本地数据库，
作为"确定性计算层"：查询、去重、统计、评测都从这里取数。
权威源仍是飞书多维表格（用户可见、可改），SQLite 是它的本地投影与计算副本。

表结构：
  jobs      岗位主表，唯一键 (title, company)
  companies 公司表（背调状态沉淀）
  feedback  用户反馈表（评价回流 → 评测指标）

用法：
  python db.py init          # 从本地历史数据初始化（72条快照+推送日期）
  python db.py dump [N]      # 打印前 N 条岗位（默认10）
  python db.py count         # 各表计数
"""
import json
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from filter import load_rules, JobRules

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jobs.db")
DATA_DIR = r"<PROJECT_ROOT>\jobs_data"

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    salary TEXT DEFAULT '',
    loc TEXT DEFAULT '',
    source TEXT DEFAULT '',
    worktime TEXT DEFAULT '',
    status TEXT DEFAULT '',
    note TEXT DEFAULT '',
    link TEXT DEFAULT '',
    apply_state TEXT DEFAULT '未投',
    apply_date TEXT DEFAULT '',
    commute_result TEXT DEFAULT 'unmeasured',
    match_level TEXT DEFAULT 'other',
    push_date TEXT DEFAULT '',
    UNIQUE(title, company)
);
CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    checked INTEGER DEFAULT 0,
    check_note TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER,
    feedback_type TEXT NOT NULL,
    note TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (job_id) REFERENCES jobs(id)
);
"""


def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    c = conn()
    c.executescript(SCHEMA)
    c.commit()
    return c


# ---------------------------------------------------------------- 数据读取
def _load_ndjson(path):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def _load_daily_dates():
    """从 daily_*.json 倒推每岗的推送日期。返回 {(title, company): date}"""
    mapping = {}
    if not os.path.isdir(DATA_DIR):
        return mapping
    for fn in os.listdir(DATA_DIR):
        m = re.match(r"daily_(.+)\.json$", fn)
        if not m:
            continue
        date_tag = m.group(1)  # 2026-09-14 / 2026-09-15 / 2026-09-15_evening / test_20260917 等
        path = os.path.join(DATA_DIR, fn)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        if isinstance(data, dict):
            jobs = data.get("jobs") or []
        else:
            jobs = data
        if not isinstance(jobs, list):
            continue
        for j in jobs:
            title = j.get("title") or j.get("职位名") or ""
            company = j.get("company") or j.get("公司") or ""
            if title and company:
                mapping[(title.strip(), company.strip())] = date_tag
    return mapping


def normalize_commute(note):
    if not note:
        return "unmeasured"
    if "❌" in note:
        return "fail"
    if "✅" in note:
        return "pass"
    if "⚠️" in note:
        return "warn"
    if "⏳" in note:
        return "unknown"
    return "unmeasured"


def _cell(v):
    """多维表格 CellValue 归一：list 取首个，其余原样。"""
    if isinstance(v, list):
        return v[0] if v else ""
    return v if v is not None else ""


def import_from_local():
    """从 base_final_commute.ndjson（72条权威快照）初始化 jobs，并回填推送日期。"""
    c = init_db()
    rules = load_rules()
    engine = JobRules(rules)
    nd = _load_ndjson(os.path.join(DATA_DIR, "base_final_commute.ndjson"))
    daily_map = _load_daily_dates()

    inserted = 0
    for r in nd:
        title = (r.get("职位名") or "").strip()
        company = (r.get("公司") or "").strip()
        if not title or not company:
            continue
        note = r.get("备注") or ""
        key = (title, company)
        push_date = daily_map.get(key, "")
        c.execute(
            """INSERT INTO jobs
               (title, company, salary, loc, source, worktime, status, note, link,
                apply_state, commute_result, match_level, push_date)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(title, company) DO UPDATE SET
                 salary=excluded.salary, loc=excluded.loc, source=excluded.source,
                 worktime=excluded.worktime, status=excluded.status, note=excluded.note,
                 link=excluded.link, commute_result=excluded.commute_result,
                 match_level=excluded.match_level, push_date=excluded.push_date
               -- 不覆盖 apply_state/apply_date：用户投递进度以权威表为准""",
            (
                title,
                company,
                _cell(r.get("薪资")),
                _cell(r.get("地点")),
                _cell(r.get("来源")),
                _cell(r.get("作息")),
                _cell(r.get("状态")),
                note,
                _cell(r.get("投递链接")),
                _cell(r.get("投递状态")) or "未投",
                normalize_commute(note),
                engine.match_level(title),
                push_date,
            ),
        )
    # companies 派生
    c.execute("INSERT OR IGNORE INTO companies(name) SELECT DISTINCT company FROM jobs")
    c.commit()
    n = c.execute("SELECT COUNT(*) n FROM jobs").fetchone()["n"]
    nc = c.execute("SELECT COUNT(*) n FROM companies").fetchone()["n"]
    print("初始化完成: jobs=%d (新增%d) | companies=%d" % (n, inserted, nc))
    c.close()


# ---------------------------------------------------------------- 工具
def count_all():
    c = conn()
    for t in ("jobs", "companies", "feedback"):
        n = c.execute("SELECT COUNT(*) n FROM %s" % t).fetchone()["n"]
        print("%-10s %d" % (t, n))
    c.close()


def dump(n=10):
    c = conn()
    rows = c.execute(
        "SELECT title, company, salary, commute_result, apply_state, push_date FROM jobs ORDER BY id LIMIT ?",
        (n,),
    ).fetchall()
    for r in rows:
        print("[%s] %s | %s | %s | 通勤:%s 投递:%s" % (
            r["push_date"] or "无日期", r["title"][:20], r["company"][:14],
            r["salary"], r["commute_result"], r["apply_state"]))
    c.close()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "count"
    if cmd == "init":
        import_from_local()
    elif cmd == "count":
        count_all()
    elif cmd == "dump":
        dump(int(sys.argv[2]) if len(sys.argv) > 2 else 10)
    else:
        print(__doc__)
