"""债锚（沪深300全收益 vs 放大后的债基基线）

数据接口
--------
中证指数官网：https://www.csindex.com.cn/csindex-home/perf/index-perf
    indexCode=H00300 沪深300全收益 / H11023 中证债券型基金指数
    startDate=2004-12-31，endDate 取“远期”（如 today+3 年）

    ⚠ 关键坑：endDate 必须晚于最后一条数据，否则接口返回 0 行。
      用 endDate=2025-12-31 查 2025 年会得到空数组，改成 2030-12-31 就正常。
      一次请求即可拿到 2005 年至今的完整日线（约 5300 行），无需分段。

口径参数（与前期图表一致，勿随意改动）
----
    k       = 1.4437        债锚 = 1000 × (债基/1000)^k
    起点     2005-01-04 = 1000
    股票     沪深300全收益 H00300
    债基     中证债券型基金指数 H11023
    底部     13 个历史阶段性底部（2008-11 ~ 2025-04），k 由这些底部的对数最小二乘得出

产物（都写在脚本自己所在目录）
----
    hist_csi.csv        完整历史缓存（每次运行都会刷新）
    csi_2026_daily.csv  2026 年逐日（全收益 + 债基）
    an_anchor_today.csv 今日锚位快照，含 to_anchor（还需跌，负数=下跌比例）
    deanchor_today.png  --chart 时的对数坐标主图

运行
----
    python deanchor.py            # 计算并打印今日锚位与还需跌幅
    python deanchor.py --chart    # 另存对数坐标主图
"""
import argparse
import csv
import json
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent
CSV_HIST = BASE / "hist_csi.csv"
CSV_YEAR = BASE / "csi_2026_daily.csv"
CSV_ANCHOR = BASE / "an_anchor_today.csv"
PNG = BASE / "deanchor_today.png"

K = 1.4437
START = "2005-01-04"          # 归一起点（=1000）
HIST_START = "2004-12-31"
HIST_END_PAD = 1095           # endDate = 今天 + 3 年，绕开中证接口的 endDate 怪癖

UA = {"User-Agent": "Mozilla/5.0",
      "Referer": "https://www.csindex.com.cn/"}


# ---------------------------------------------------------------- 取数
def _get(url, params, headers, timeout=90, retries=4):
    q = urllib.parse.urlencode(params)
    full = f"{url}?{q}"
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(full, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "ignore")
        except Exception as e:              # noqa: BLE001
            last = e
            time.sleep(1.5 * (i + 1))
    raise last


def _norm_date(s):
    s = str(s)[:10]
    if "-" in s:
        return s
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) >= 8 else s


def fetch_index(code, start=HIST_START, end=None):
    """一次取全历史。end 必须晚于最后一条数据，否则中证返回空。"""
    end = end or (date.today() + timedelta(days=HIST_END_PAD)).isoformat()
    txt = _get("https://www.csindex.com.cn/csindex-home/perf/index-perf",
               {"indexCode": code, "startDate": start, "endDate": end}, UA, timeout=120)
    rows = (json.loads(txt) or {}).get("data") or []
    if not rows:
        # 再退一步：把 endDate 推得更远重试一次
        end2 = (date.today() + timedelta(days=3650)).isoformat()
        txt = _get("https://www.csindex.com.cn/csindex-home/perf/index-perf",
                   {"indexCode": code, "startDate": start, "endDate": end2}, UA, timeout=120)
        rows = (json.loads(txt) or {}).get("data") or []
    out = {}
    for r in rows:
        d = _norm_date(r.get("tradeDate"))
        c = r.get("close")
        if d and c is not None:
            out[d] = float(c)
    if len(out) < 1000:
        raise RuntimeError(f"{code} 只取到 {len(out)} 行，接口异常")
    return out


def load_all():
    """返回 [(date, tr, bond), ...]。债券指数若比股票晚更新一天，用前值补齐（≤5 天）。"""
    tr = fetch_index("H00300")
    time.sleep(0.5)
    bd = fetch_index("H11023")

    last_bond = None
    prev_date = None
    rows = []
    for d in sorted(set(tr) | set(bd)):
        if d in bd:
            last_bond, prev_date = bd[d], d
        if d not in tr or last_bond is None:
            continue
        # 债基缺当天：仅当离上一个债基日期不超过 5 天时用前值补
        if d not in bd and prev_date and (date.fromisoformat(d) - date.fromisoformat(prev_date)).days > 5:
            continue
        rows.append((d, tr[d], last_bond))
    if not rows:
        raise SystemExit("H00300 / H11023 没有交集")
    return rows


# ---------------------------------------------------------------- 债锚
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-chart", action="store_true", help="只出数据，不画图")
    ap.add_argument("--chart", action="store_true", help="兼容旧参数（图默认就会生成）")
    args = ap.parse_args()

    data = load_all()
    print(f"数据: {data[0][0]} ~ {data[-1][0]}，{len(data)} 个交易日（中证 H00300 + H11023，单次全量）")

    # 缓存全历史
    with CSV_HIST.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["date", "tr", "bond"])
        w.writerows((f"{d}", f"{t:.4f}", f"{b:.4f}") for d, t, b in data)

    # 归一到 2005-01-04 = 1000
    base = next((r for r in data if r[0] >= START), data[0])
    tr0, bd0 = base[1], base[2]
    norm = [(d, t / tr0 * 1000.0, b / bd0 * 1000.0) for d, t, b in data]
    anchor = [(d, 1000.0 * (b / 1000.0) ** K) for d, _, b in norm]

    d_last, tr_last, bd_last = data[-1]
    trn, bdn = norm[-1][1], norm[-1][2]
    anc = anchor[-1][1]
    pos = trn / anc - 1
    to_anchor = anc / trn - 1

    print("\n=== 债锚 ===")
    print(f"日期          {d_last}")
    print(f"沪深300全收益 {tr_last:,.0f}（归一 {trn:,.0f}）")
    print(f"债基          {bd_last:,.0f}（归一 {bdn:,.0f}）")
    print(f"债锚          {anc:,.0f}")
    print(f"锚位          {pos:+.2%}")
    print(f"还需跌        {to_anchor:+.2%}   ← 到债锚还要跌这么多")

    # 2026 年逐日
    y26 = [r for r in norm if r[0] >= "2026-01-01"]
    with CSV_YEAR.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["date", "tr", "bond"])
        w.writerows(y26)

    with CSV_ANCHOR.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["date", "tr", "tr_1000", "bond", "bond_1000",
                    "anchor", "position", "to_anchor"])
        w.writerow([d_last, f"{tr_last:.2f}", f"{trn:.2f}", f"{bd_last:.2f}", f"{bdn:.2f}",
                    f"{anc:.2f}", f"{pos:.6f}", f"{to_anchor:.6f}"])
    print(f"\n已写入 {CSV_HIST.name}、{CSV_YEAR.name}、{CSV_ANCHOR.name}（均在脚本目录）")

    if not args.no_chart:
        try:
            _chart(norm, anchor, pos, to_anchor, d_last)
        except ImportError as e:
            print(f"[warn] 没装 matplotlib，跳过画图：{e}\n"
                  f"       安装：pip install matplotlib")


def _chart(norm, anchor, pos, to_anchor, d_last):
    import datetime as dt

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FixedLocator, FuncFormatter, NullFormatter

    plt.rcParams.update({"font.sans-serif": ["Microsoft YaHei", "SimHei"],
                         "font.family": "sans-serif", "axes.unicode_minus": False})

    xs = [dt.datetime.strptime(d, "%Y-%m-%d") for d, _, _ in norm]
    s = [t for _, t, _ in norm]
    b = [v for _, _, v in norm]
    adj = [a for _, a in anchor]

    fig, ax = plt.subplots(figsize=(13.8, 7.6), dpi=150)
    ax.plot(xs, s, color="#C0392B", lw=1.3, label="沪深300全收益（起点 1000）")
    ax.plot(xs, b, color="#1F6FB2", lw=0.9, alpha=0.3, ls="--", label="债基原始（起点 1000）")
    ax.plot(xs, adj, color="#1F6FB2", lw=2.1, label=f"债锚 = 1000×(债基/1000)^{K}")
    ax.fill_between(xs, [v * 0.915 for v in adj], adj, color="#1F6FB2", alpha=0.10,
                    label="历史底部跌破带（最深 -8.5%）")

    ax.scatter([xs[-1]], [s[-1]], s=95, color="#C0392B", edgecolor="black", zorder=6)
    ax.annotate("", xy=(xs[-1], adj[-1]), xytext=(xs[-1], s[-1]),
                arrowprops=dict(arrowstyle="->", color="#1a1a1a", lw=1.4, ls="--"))
    ax.scatter([xs[-1]], [adj[-1]], s=55, marker="v", color="#1F6FB2", zorder=6)
    ax.annotate(f"今日 {s[-1]:,.0f}", (xs[-1], s[-1]), xytext=(-86, 20),
                textcoords="offset points", fontsize=10, color="#7B241C", fontweight="bold")
    ax.annotate(f"债锚 {adj[-1]:,.0f}\n还需跌 {abs(to_anchor):.1%}",
                (xs[-1], adj[-1]), xytext=(-146, -58), textcoords="offset points",
                fontsize=9.5, color="#1F6FB2", fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.32", fc="white", ec="none", alpha=0.85))

    ax.set_yscale("log")
    ax.yaxis.set_major_locator(FixedLocator([1000, 1500, 2000, 3000, 5000, 7000]))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, p: f"{v:,.0f}"))
    ax.yaxis.set_minor_formatter(NullFormatter())
    ax.grid(True, which="major", alpha=0.25)
    ax.grid(True, which="minor", alpha=0.10, lw=0.5)
    ax.legend(loc="upper left", frameon=False, fontsize=9)
    ax.set_title(f"债锚（对数坐标，起点 1000，截至 {d_last}）\n"
                 f"锚位 {pos:+.1%}　还需跌 {abs(to_anchor):.1%}", fontsize=13)
    ax.xaxis.set_major_locator(mdates.YearLocator(2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    fig.tight_layout()
    fig.savefig(PNG, bbox_inches="tight")
    print(f"已保存图：{PNG.name}")


if __name__ == "__main__":
    main()
