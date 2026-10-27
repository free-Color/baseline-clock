"""国证成长100（980080）三角形周期图

三个沿基线上行的“底→顶→底”三角形，第三个尚未走完：
2013-06-25(1097) → 2015-06-12(4299) → 2019-01-03(1879)
2019-01-03(1879) → 2021-09-15(8559) → 2024-02-05(4153)
2024-02-05(4153) → 2026-06-22(17204) → 2028-10-20(约7952，推演：再跌 2 年、−20%)

依赖：matplotlib（自带 numpy）。数据：同目录 cni_980080_daily.csv，缺失时自动从国证指数网抓取。
运行：python growth100_triangles.py
输出：同目录 成长100_三角形周期与推演.png / .pdf
"""
import csv
import json
import math
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.ticker import FixedLocator, FuncFormatter, LogLocator, NullFormatter

BASE = Path(__file__).resolve().parent
CSV_PATH = BASE / f"cni_980080_daily_{time.strftime('%Y-%m-%d')}.csv"
PNG = BASE / "成长100_三角形周期与推演.png"
PDF = BASE / "成长100_三角形周期与推演.pdf"

plt.rcParams.update({
    "font.sans-serif": ["Microsoft YaHei", "SimHei"],
    "font.family": "sans-serif",
    "axes.unicode_minus": False,
    "figure.dpi": 110,
    "savefig.dpi": 200,
})

# 三个三角形的转折点（底/顶交替），最后一个是推演底
TURNS = [("2013-06-25", "low"), ("2015-06-12", "high"), ("2019-01-03", "low"),
         ("2021-09-15", "high"), ("2024-02-05", "low"), ("2026-06-22", "high")]
PROJ_DAYS = int(2 * 365.25)   # 再跌两年
PROJ_RET = 0.80               # 再跌 20%

C_LINE = "#2f5d8a"
C_RED = "#c00000"
C_FIT = "#8b0000"
C_PEAK = "#4d4d4d"
C_ZIG = "#8f98a3"
C_GRID = "#d9d9d9"
C_TXT = "#3a3a3a"

# 每段中点标注的位置（数据坐标），按段顺序
LEG_POS = [(datetime(2014, 4, 1), 2450), (datetime(2016, 11, 1), 3750),
           (datetime(2020, 2, 1), 4700), (datetime(2022, 10, 1), 7200),
           (datetime(2025, 3, 1), 10800)]
LEG6_POS = (datetime(2027, 7, 1), 11100)


def fetch_cni(start="2000-01-01", end=None):
    """从国证指数网抓日线（大区间只回较早日期，尾部再抓一次最近 60 天）。"""
    end = end or date.today().isoformat()
    url = "http://hq.cnindex.com.cn/market/market/getIndexDailyDataWithDataFormat"

    def once(s, e):
        q = urllib.parse.urlencode({"indexCode": "980080", "startDate": s,
                                    "endDate": e, "frequency": "day"})
        req = urllib.request.Request(f"{url}?{q}", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=40) as r:
            data = json.loads(r.read().decode("utf-8"))
        return [{"date": x[0], "close": float(x[1])}
                for x in (data.get("data") or {}).get("data") or []]

    rows = once(start, end)
    rows += once((date.today() - timedelta(days=60)).isoformat(), end)
    uniq = {r["date"]: r["close"] for r in rows}
    return [{"date": k, "close": uniq[k]} for k in sorted(uniq)]


def load():
    if not CSV_PATH.exists():
        print(f"{CSV_PATH.name} 不存在，联网抓取中 ...")
        rows = fetch_cni()
        with CSV_PATH.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=["date", "close"])
            w.writeheader()
            w.writerows(rows)
        print(f"已保存 {CSV_PATH.name}（{len(rows)} 行）")

    out = []
    with CSV_PATH.open(encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            try:
                out.append((datetime.strptime(r["date"][:10], "%Y-%m-%d"),
                            float(r["close"])))
            except (ValueError, KeyError):
                continue
    out.sort()
    return out


def years(a, b):
    return (b - a).days / 365.25


def fit_line(xs, ys):
    """最小二乘 y = a + b*x（这里 y = ln(close)）。"""
    n = len(xs)
    sx = sum(xs)
    sy = sum(ys)
    sxx = sum(x * x for x in xs)
    sxy = sum(x * y for x, y in zip(xs, ys))
    b = (n * sxy - sx * sy) / (n * sxx - sx * sx)
    return (sy - b * sx) / n, b


def main():
    data = load()
    if len(data) < 100:
        raise SystemExit("数据太少，检查 cni_980080_daily.csv")
    t0 = data[0][0]
    last_date, last_close = data[-1]

    turns = []
    for ds, kind in TURNS:
        d = datetime.strptime(ds, "%Y-%m-%d")
        v = next(c for dd, c in data if dd == d)
        turns.append((d, v, kind))
    bottoms = [t for t in turns if t[2] == "low"]

    xs = [years(t0, t[0]) for t in bottoms]
    ys = [math.log(t[1]) for t in bottoms]
    a, b = fit_line(xs, ys)
    ann = (math.exp(b) - 1) * 100

    def line_at(d):
        return math.exp(a + b * years(t0, d))

    line_today = line_at(last_date)
    gap = (last_close / line_today - 1) * 100

    proj_date = last_date + timedelta(days=PROJ_DAYS)
    proj_price = last_close * PROJ_RET
    line_proj = line_at(proj_date)

    x_left = data[0][0] - timedelta(days=45)
    x_right = datetime(2029, 6, 30)

    fig, ax = plt.subplots(figsize=(15, 8.4))
    fig.subplots_adjust(left=0.065, right=0.985, top=0.845, bottom=0.10)

    # 每轮下跌阶段的背景色（第三个为推演，颜色更浅）
    for i in (1, 3):
        ax.axvspan(turns[i][0], turns[i + 1][0], color=C_RED, alpha=0.05, zorder=0, lw=0)
    ax.axvspan(turns[-1][0], proj_date, color=C_RED, alpha=0.03, zorder=0, lw=0)

    ax.plot([d for d, _ in data], [c for _, c in data], color=C_LINE, lw=1.15, zorder=3,
            label="国证成长100 收盘价")

    # 三个三角形的虚线边
    zx = [t[0] for t in turns] + [proj_date]
    zy = [t[1] for t in turns] + [proj_price]
    ax.plot(zx, zy, color=C_ZIG, lw=1.15, ls=(0, (5, 3)), zorder=2.6, alpha=0.9)
    ax.plot([turns[-1][0], proj_date], [turns[-1][1], proj_price], color=C_ZIG, lw=1.15,
            ls=(0, (2, 3)), zorder=2.6, alpha=0.75)

    # 大底基线
    x_fit_l = max(x_left, datetime(2012, 12, 31))
    ax.plot([x_fit_l, x_right], [line_at(x_fit_l), line_at(x_right)], color=C_FIT, lw=2.3,
            zorder=4, solid_capstyle="round",
            label=f"三个大底的对数线性拟合（年化 +{ann:.1f}%）")

    # 转折点
    for d, v, kind in turns:
        if kind == "low":
            ax.scatter([d], [v], s=72, color=C_RED, zorder=5, edgecolor="white", linewidth=1.4)
        else:
            ax.scatter([d], [v], s=66, marker="^", color=C_PEAK, zorder=5,
                       edgecolor="white", linewidth=1.2)
    ax.scatter([proj_date], [proj_price], s=64, facecolor="white", edgecolor=C_RED,
               zorder=5, linewidth=1.5, linestyle="--")

    # 顶部：点位 + 本轮涨幅
    for i, (d, v, kind) in enumerate(turns):
        if kind != "high":
            continue
        gain = (v / turns[i - 1][1] - 1) * 100
        ax.annotate(f"{d.date()}　{v:,.0f}\n↑ +{gain:.1f}%", xy=(d, v),
                    xytext=(0, 26), textcoords="offset points", fontsize=8.3, color=C_PEAK,
                    ha="center", va="bottom", zorder=6, linespacing=1.35,
                    bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#cfcfcf", lw=0.7, alpha=0.96),
                    arrowprops=dict(arrowstyle="-", color="#bdbdbd", lw=0.6, shrinkA=0, shrinkB=3))

    # 底部：点位 + 本轮跌幅
    bot_pos = {0: ((20, -18), "left"), 1: ((-18, -32), "right"), 2: ((-18, -34), "right")}
    for j, idx in enumerate([0, 2, 4]):
        d, v, _ = turns[idx]
        if j == 0:
            txt = f"{d.date()}　{v:,.0f}\n首个低点（基期 1,000）"
        else:
            loss = (v / turns[idx - 1][1] - 1) * 100
            txt = f"{d.date()}　{v:,.0f}\n↓ {loss:.1f}%"
        (dx, dy), ha = bot_pos[j]
        ax.annotate(txt, xy=(d, v), xytext=(dx, dy), textcoords="offset points",
                    fontsize=8.3, color=C_RED, ha=ha, va="top", zorder=6, linespacing=1.35,
                    bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#e8b4b4", lw=0.7, alpha=0.96),
                    arrowprops=dict(arrowstyle="-", color="#e0a0a0", lw=0.6, shrinkA=0, shrinkB=4))

    # 推演底
    ax.annotate(f"{proj_date.strftime('%Y-%m')}　约 {proj_price:,.0f}（预计低点）",
                xy=(proj_date, proj_price), xytext=(-12, -22), textcoords="offset points",
                fontsize=8.2, color=C_RED, ha="right", va="top", zorder=6,
                bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#e0a0a0", lw=0.7, alpha=0.96),
                arrowprops=dict(arrowstyle="-", color="#e0a0a0", lw=0.6, shrinkA=0, shrinkB=4))

    # 每段中点：时间段 + 年数
    legs = list(zip(turns[:-1], turns[1:])) + [(turns[-1], (proj_date, proj_price, "proj"))]
    for i, ((d0, _, _), (d1, _, _)) in enumerate(legs):
        span = f"{d0.strftime('%Y-%m')} → {d1.strftime('%Y-%m')}　{years(d0, d1):.1f} 年"
        if i < len(LEG_POS):
            px, py = LEG_POS[i]
            ax.text(px, py, span, fontsize=8.0, color="#4a4a4a", ha="center", va="center",
                    zorder=7, bbox=dict(boxstyle="round,pad=0.28", fc="#f7f9fc", ec="#cdd8e6",
                                        lw=0.7, alpha=0.95))
        else:
            px, py = LEG6_POS
            ax.text(px, py, span + "\n（第三个三角形，未完）", fontsize=8.0, color="#7a5a3a",
                    ha="center", va="center", zorder=7, linespacing=1.4,
                    bbox=dict(boxstyle="round,pad=0.3", fc="#fdf6ee", ec="#dcc3a3",
                              lw=0.7, alpha=0.95))

    # 当前点位
    ax.scatter([last_date], [last_close], s=44, facecolor="white", edgecolor="#6f6f6f",
               zorder=8, linewidth=1.4)
    ax.annotate(f"当前 {last_close:,.0f}（{last_date.date()}）\n"
                f"较基线 +{gap:.0f}%｜本轮 {(last_close / turns[-1][1] - 1) * 100:.1f}%",
                xy=(last_date, last_close), xytext=(datetime(2026, 11, 25), 15600),
                textcoords="data", fontsize=8.3, color="#3a3a3a", ha="left", va="center", zorder=9,
                linespacing=1.5,
                bbox=dict(boxstyle="round,pad=0.4", fc="white", ec="#c9d3df", lw=0.8),
                arrowprops=dict(arrowstyle="-", color="#c9c9c9", lw=0.8, shrinkA=2, shrinkB=4))

    ax.set_yscale("log")
    ax.set_ylim(820, 24000)
    ax.set_xlim(x_left, x_right)
    ax.yaxis.set_major_locator(FixedLocator([1000, 1500, 2000, 3000, 5000, 8000, 12000, 17000]))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, p: f"{v:,.0f}"))
    ax.yaxis.set_minor_locator(LogLocator(base=10, subs=(2, 3, 4, 5, 6, 7, 8, 9)))
    ax.yaxis.set_minor_formatter(NullFormatter())
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.tick_params(axis="x", labelsize=9.0, colors=C_TXT)
    ax.tick_params(axis="y", labelsize=9.5, colors=C_TXT)
    ax.grid(axis="y", which="major", color=C_GRID, lw=0.7, ls="--", zorder=0)
    ax.grid(axis="y", which="minor", color="#ececec", lw=0.45, ls=":", zorder=0)
    ax.grid(axis="x", which="major", color="#efefef", lw=0.6, zorder=0)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#9a9a9a")

    ax.set_ylabel("指数点位（对数坐标）", fontsize=10.5, color=C_TXT, labelpad=10)
    ax.set_title("国证成长100指数（980080）：沿基线上行的三个三角形，第三个尚未走完",
                 fontsize=16, color="#1f4e79", fontweight="bold", loc="left", pad=40)
    ax.text(0.0, 1.02,
            f"{data[0][0].date()} ~ {last_date.date()}｜底→顶→底 用虚线连接，第三个三角形的下行边按"
            f"“再跌 2 年、−20%”推演｜虚线为周期示意、非价格路径｜基线年化 +{ann:.1f}%",
            transform=ax.transAxes, fontsize=9.0, color="#5a5a5a")
    ax.legend(loc="upper left", fontsize=8.9, frameon=True, framealpha=0.95,
              edgecolor="#cfcfcf", borderpad=0.7)

    fig.text(0.065, 0.024, "数据来源：国证指数网（cnindex.com.cn）官方日行情　·　绘图：Python / Matplotlib",
             fontsize=8.4, color="#7a7a7a")

    fig.savefig(PNG, facecolor="white")
    fig.savefig(PDF, facecolor="white")
    print(f"saved {PNG.name} / {PDF.name}")
    print(f"基线年化 {ann:.2f}%｜当前 {last_close:.2f}，较基线 {gap:+.1f}%")
    print(f"推演底 {proj_date.date()} 约 {proj_price:.0f}，基线届时 {line_proj:.0f}")


if __name__ == "__main__":
    main()
