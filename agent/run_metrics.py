# -*- coding: utf-8 -*-
"""
求职Agent · 推送后评测一键跑（P0-a 闭环入口）
=============================================
每日推送完成后执行：同步反馈 → 常规指标 → 周报 → 反馈回流建议。
用法：python run_metrics.py
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def run(script, *args):
    print("\n===== %s %s =====" % (script, " ".join(args)))
    r = subprocess.run([sys.executable, os.path.join(HERE, script)] + list(args),
                       capture_output=True, text=True, encoding="utf-8")
    if r.stdout:
        print(r.stdout)
    if r.returncode != 0 and r.stderr:
        print("!! stderr:", r.stderr[:500])
    return r.returncode == 0


if __name__ == "__main__":
    ok = True
    ok &= run("sync_bitable.py")          # 多维表格 → SQLite（含投递反馈回流）
    ok &= run("stats.py")                 # 常规评测指标快照
    ok &= run("stats.py", "--weekly")     # 本周周报
    ok &= run("rerank.py")                # 反馈回流关键词权重建议
    print("\n" + ("=" * 52))
    print("推送后评测完成 ✅" if ok else "部分步骤失败，请检查上方输出 ⚠️")
    print("周报: job-agent/weekly_report.json | 指标: job-agent/stats_report.json | 权重建议: job-agent/rerank_suggestions.json")
