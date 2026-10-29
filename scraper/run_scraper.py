# -*- coding: utf-8 -*-
"""
阶段一主入口：一键抓取 5 个公开渠道 → 统一清洗 → scan_auto_<date>.json
=====================================================================
用法：
  python run_scraper.py                 # 抓取今天（含完整渠道受限说明输出）
  python run_scraper.py --date 20261030 # 指定日期
  python run_scraper.py --limit 80      # 每渠道最多条数（防超时）

输出：
  raw_jobs/<channel>_<date>.ndjson   # 原始岗位库（逐渠道）
  scan_auto_<date>.json              # 统一候选文件（push_pipeline 直接消费）

接入现有体系：
  推送编排 job-agent/push_pipeline.py --candidates job-scraper/scan_auto_<date>.json
  即可把"搜岗"环节替换为全自动抓取（规则过滤/去重/写表/卡片全部复用）。
"""
import argparse, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common

def main():
    ap = argparse.ArgumentParser(description="阶段一公开渠道全自动抓取")
    ap.add_argument("--date", default=None, help="YYYYMMDD，默认今天")
    ap.add_argument("--limit", type=int, default=80, help="每渠道上限")
    args = ap.parse_args()

    d = common.today() if not args.date else args.date
    print("=" * 60)
    print("阶段一全自动抓取  date=%s  每渠道上限=%d" % (d, args.limit))
    print("=" * 60)

    res = common.run_all(limit=args.limit)
    total = 0
    for ch, r in res.items():
        if ch.startswith("_") or not isinstance(r, dict):
            continue
        total += r.get("count", 0)
        flag = "OK " if r.get("ok") else "受限"
        print("[%s] %s  抓取=%d  写出=%s" % (ch, flag, r.get("count", 0), r.get("raw", "")))
    print("-" * 60)
    print("合计抓取 %d 条 → scan=%s" % (total, res.get("_aggregate", {}).get("scan", "")))
    print("受限渠道说明见各渠道 stdout；公众号渠道当前为人工清单模式（搜狗反爬）")

if __name__ == "__main__":
    main()
