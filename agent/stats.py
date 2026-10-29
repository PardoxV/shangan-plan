# -*- coding: utf-8 -*-
"""
求职Agent · 评测指标引擎
========================
从 SQLite（统一实体模型）计算推送/投递/反馈漏斗与分布指标，
输出 stats_report.json 供回溯与周报。数据攒够后，指标回流到推送排序
（哪些方向命中率高 → 提权，见 rerank.py）。

用法：
  python stats.py                  # 常规指标快照
  python stats.py --weekly         # 本周周报（本周一至今）
  python stats.py --out <路径>     # 指定报告输出路径
"""
import argparse
import json
import os
import sqlite3
from collections import Counter
from datetime import date, timedelta

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jobs.db")
HERE = os.path.dirname(os.path.abspath(__file__))

# 动态日期：本周一（WEEK_START）与今天（as_of / 周报截止），不再硬编码
TODAY = date.today()
WEEK_START = (TODAY - timedelta(days=TODAY.weekday())).strftime("%Y-%m-%d")
TODAY_STR = TODAY.strftime("%Y-%m-%d")
RULES_VERSION = ""
try:
    RULES_VERSION = str(json.load(open(os.path.join(HERE, "rules.json"), encoding="utf-8")).get("version", ""))
except Exception:
    RULES_VERSION = ""


def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def counter(c, sql, params=()):
    return dict((r["k"], r["n"]) for r in c.execute(sql, params).fetchall())


def build_report():
    c = conn()

    total = c.execute("SELECT COUNT(*) n FROM jobs").fetchone()["n"]

    by_push_date = counter(c, "SELECT COALESCE(push_date,'无日期') k, COUNT(*) n FROM jobs GROUP BY k")
    by_source = counter(c, "SELECT COALESCE(NULLIF(source,''),'未标注') k, COUNT(*) n FROM jobs GROUP BY k")
    by_commute = counter(c, "SELECT commute_result k, COUNT(*) n FROM jobs GROUP BY k")
    by_status = counter(c, "SELECT COALESCE(NULLIF(status,''),'未标注') k, COUNT(*) n FROM jobs GROUP BY k")
    by_match = counter(c, "SELECT match_level k, COUNT(*) n FROM jobs GROUP BY k")

    # 投递漏斗（投递状态为权威；未投/已投/已回复/面试/婉拒/入职）
    funnel = dict((r["apply_state"], r["n"]) for r in
                  c.execute("SELECT apply_state, COUNT(*) n FROM jobs GROUP BY apply_state").fetchall())

    # 复推潜力：通勤达标/边缘 + 未投 + 状态为推荐/优先
    resend_pool = c.execute(
        """SELECT COUNT(*) n FROM jobs
           WHERE apply_state='未投' AND commute_result IN ('pass','warn')
             AND status IN ('推荐','优先')""").fetchone()["n"]

    commute_ok = sum(n for k, n in by_commute.items() if k in ("pass", "warn"))

    high_unapplied = c.execute(
        """SELECT COUNT(*) n FROM jobs WHERE match_level='high' AND apply_state='未投'""").fetchone()["n"]

    fb_total = c.execute("SELECT COUNT(*) n FROM feedback").fetchone()["n"]
    fb_types = counter(c, "SELECT feedback_type k, COUNT(*) n FROM feedback GROUP BY k")

    dated = [d for d in by_push_date if d != "无日期" and not d.startswith("test")]
    push_days = len(dated)
    avg_per_day = round(sum(by_push_date[d] for d in dated) / push_days, 1) if push_days else 0

    report = {
        "as_of": TODAY_STR,
        "rules_version": RULES_VERSION,
        "kpis": {
            "total_jobs": total,
            "commute_ok": commute_ok,
            "commute_ok_rate": round(commute_ok / total * 100, 1) if total else 0,
            "push_days": push_days,
            "avg_jobs_per_day": avg_per_day,
            "applied": funnel.get("已投", 0),
            "applied_rate": round(funnel.get("已投", 0) / total * 100, 1) if total else 0,
            "interview": funnel.get("面试", 0),
            "resend_pool": resend_pool,
            "high_match_unapplied": high_unapplied,
            "feedback_count": fb_total,
        },
        "distributions": {
            "by_push_date": by_push_date,
            "by_source": by_source,
            "by_commute": by_commute,
            "by_status": by_status,
            "by_match": by_match,
        },
        "apply_funnel": funnel,
        "feedback_types": fb_types,
        "note": "指标从 SQLite 计算（权威源=飞书多维表格的本地投影）；投递进度以表格为准，每日推送后重算",
    }

    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "stats_report.json"),
              "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)

    print("=" * 52)
    print("求职Agent 评测指标  |  %s  |  规则 v%s" % (report["as_of"], report["rules_version"]))
    print("-" * 52)
    k = report["kpis"]
    print("岗位总量      %d   通勤达标率 %.1f%% (%d/%d)" % (k["total_jobs"], k["commute_ok_rate"], k["commute_ok"], k["total_jobs"]))
    print("日均推送      %.1f 条/天（%d 个推送日）" % (k["avg_jobs_per_day"], k["push_days"]))
    print("已投          %d  (%.1f%%)   面试 %d" % (k["applied"], k["applied_rate"], k["interview"]))
    print("复推潜力池    %d   高匹配未投 %d" % (k["resend_pool"], k["high_match_unapplied"]))
    print("用户反馈      %d 条 %s" % (k["feedback_count"], dict(report["feedback_types"])))
    print("-" * 52)
    print("投递漏斗:", report["apply_funnel"])
    print("通勤分布:", report["distributions"]["by_commute"])
    print("匹配度  :", report["distributions"]["by_match"])
    c.close()


def build_weekly():
    """本周周报（本周一至今天，动态计算）。"""
    c = conn()
    w = {"week_start": WEEK_START, "week_end": TODAY_STR}

    # 本周推送（push_date 以周一起且非 test）
    week_jobs = c.execute(
        """SELECT COUNT(*) n FROM jobs WHERE push_date >= ? AND push_date <= ?""",
        (WEEK_START, w["week_end"])).fetchone()["n"]
    by_day = counter(c,
        """SELECT COALESCE(push_date,'无日期') k, COUNT(*) n FROM jobs
           WHERE push_date >= ? AND push_date <= ? GROUP BY k""",
        (WEEK_START, w["week_end"]))
    # 本周新增但没标日期的（测试轮等）按全部计
    week_sources = counter(c,
        """SELECT COALESCE(NULLIF(source,''),'未标注') k, COUNT(*) n FROM jobs
           WHERE push_date >= ? AND push_date <= ? GROUP BY k""",
        (WEEK_START, w["week_end"]))

    # 投递进展（本周更新的，apply_date 在本周或已投）
    funnel = dict((r["apply_state"], r["n"]) for r in
                  c.execute("SELECT apply_state, COUNT(*) n FROM jobs GROUP BY apply_state").fetchall())

    fb = c.execute("SELECT COUNT(*) n FROM feedback").fetchone()["n"]
    fb_types = counter(c, "SELECT feedback_type k, COUNT(*) n FROM feedback GROUP BY k")

    # 复推/精华候选
    resend = c.execute(
        """SELECT COUNT(*) n FROM jobs WHERE apply_state='未投'
           AND commute_result IN ('pass','warn') AND status IN ('推荐','优先')""").fetchone()["n"]

    report = {
        "title": "求职Agent 周报",
        "period": "%s ~ %s" % (w["week_start"], w["week_end"]),
        "pushed_this_week": week_jobs,
        "by_day": by_day,
        "by_source": week_sources,
        "apply_funnel": funnel,
        "resend_pool": resend,
        "feedback_count": fb,
        "feedback_types": dict(fb_types),
        "takeaway": "",
    }
    # 一句话结论
    applied = funnel.get("已投", 0)
    if week_jobs == 0:
        report["takeaway"] = "本周暂无推送记录，请检查定时任务运行状态"
    elif applied == 0:
        report["takeaway"] = "本周推送 %d 条但尚无投递——高匹配未投 %d 个，建议尽快行动" % (week_jobs, resend)
    else:
        rate = round(applied / week_jobs * 100, 1)
        report["takeaway"] = "本周推送 %d 条、已投 %d（%.1f%%），继续扩大投递覆盖面" % (week_jobs, applied, rate)

    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "weekly_report.json"),
              "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)

    print("=" * 52)
    print(report["title"], " | ", report["period"])
    print("-" * 52)
    print("本周推送    %d 条  %s" % (week_jobs, dict(by_day)))
    print("投递漏斗    %s" % report["apply_funnel"])
    print("复推潜力池  %d   反馈 %d 条 %s" % (resend, fb, dict(fb_types)))
    print("一句话结论: %s" % report["takeaway"])
    print("周报已写入: weekly_report.json")
    c.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--weekly", action="store_true", help="输出本周周报")
    args = ap.parse_args()
    if args.weekly:
        build_weekly()
    else:
        build_report()
