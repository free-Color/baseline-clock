"""国证价值100（980081）三角形周期图

与成长100同款画法：对数坐标、大底基线、底→顶→底虚线三角形、每轮下跌背景色。
四个三角形（第四个尚未确认）：
2013-06-27(834) → 2015-06-12(2330) → 2016-01-28(1372)
2016-01-28(1372) → 2018-02-02(2872) → 2019-01-03(2003)
2019-01-03(2003) → 2021-09-13(3230) → 2022-10-31(2488)
2022-10-31(2488) → 2026-03-12(4965) → 2026-06-30(4118，未确认)

基线：7 个回撤低点的对数线性拟合（剔除 2013-06-27、2015-02-06 两个最偏离点），年化约 +10.5%。

依赖：matplotlib。数据：同目录 cni_980081_daily.csv。
运行：python value100_triangles.py
输出：同目录 价值100_三角形周期.png / .pdf
"""
import csv
import json
import math
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta
from datetime import datetime as dt
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.ticker import FixedLocator, FuncFormatter, LogLocator, NullFormatter

BASE = Path(__file__).resolve().parent
CSV_PATH = BASE / "cni_980081_daily.csv"
PNG = BASE / "价值100_三角形周期.png"
PDF = BASE / "价值100_三角形周期.pdf"

plt.rcParams.update({
    "font.sans-serif": ["Microsoft YaHei", "SimHei"],
    "font.family": "sans-serif",
    "axes.unicode_minus": False,
    "figure.dpi": 110,
    "savefig.dpi": 200,
})

# 底/顶交替；最后一个底为“本轮已知低点、未确认”
TURNS = [("2013-06-27", "low"), ("2015-06-12", "high"), ("2016-01-28", "low"),
         ("2018-02-02", "high"), ("2019-01-03", "low"), ("2021-09-13", "high"),
         ("2022-10-31", "low"), ("2026-03-12", "high"), ("2026-06-30", "low")]

# 基线用的 7 个回撤低点（剔除两个最偏离点）
FIT_LOWS = ["2016-01-28", "2019-01-03", "2022-10-31", "2023-12-20",
            "2024-09-11", "2025-04-07", "2026-06-30"]

C_LINE = "#2f5d8a"
C_RED = "#c00000"
C_FIT = "#8b0000"
C_PEAK = "#4d4d4d"
C_ZIG = "#8f98a3"
C_GRID = "#d9d9d9"
C_TXT = "#3a3a3a"

# 每个三角形的时间标签位置（数据坐标）
CYCLE_POS = [(dt(2014, 8, 1), 2150), (dt(2017, 6, 1), 2600),
             (dt(2020, 7, 1), 3100), (dt(2025, 4, 1), 4300)]


def fetch_cni(start="2000-01-01", end=None):
    """抓国证日线；单次大区间只回到较早日期，所以再补抓最近 60 天。失败自动重试 3 次。"""
    end = end or date.today().isoformat()
    url = "http://hq.cnindex.com.cn/market/market/getIndexDailyDataWithDataFormat"

    def once(s, e):
        q = urllib.parse.urlencode({"indexCode": "980081", "startDate": s,
                                    "endDate": e, "frequency": "day"})
        req = urllib.request.Request(f"{url}?{q}", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=40) as r:
            data = json.loads(r.read().decode("utf-8"))
        return [{"date": x[0], "close": float(x[1])}
                for x in (data.get("data") or {}).get("data") or []]

    rows = once(start, end) + once((date.today() - timedelta(days=60)).isoformat(), end)
    uniq = {r["date"]: r["close"] for r in rows}
    return [{"date": k, "close": uniq[k]} for k in sorted(uniq)]


def read_csv():
    out = []
    with CSV_PATH.open(encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            try:
                out.append((dt.strptime(r["date"][:10], "%Y-%m-%d"), float(r["close"])))
            except (ValueError, KeyError):
                continue
    out.sort()
    return out


def write_csv(rows):
    with CSV_PATH.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["date", "close"])
        w.writeheader()
        w.writerows(rows)


def load():
    """优先读本目录的 CSV；缺失或行数太少就联网抓取并存回本目录（不依赖当前工作目录）。"""
    if CSV_PATH.exists():
        rows = read_csv()
        if len(rows) >= 800:
            return rows
        print(f"{CSV_PATH.name} 只有 {len(rows)} 行，数据不完整，重新联网抓取 ...")
    else:
        print(f"{CSV_PATH.name} 不存在，联网抓取 ...")

    last_err = ""
    for i in range(3):
        try:
            rows = fetch_cni()
            if len(rows) >= 800:
                write_csv(rows)
                print(f"已保存 {CSV_PATH}（{len(rows)} 行）")
                return read_csv()
            last_err = f"只取到 {len(rows)} 行"
        except Exception as e:  # noqa: BLE001
            last_err = f"{type(e).__name__}: {e}"
        print(f"  第 {i + 1} 次抓取失败：{last_err}")
        time.sleep(2)

    raise SystemExit(
        f"\n数据抓取失败（{last_err}）。\n"
        f"请检查网络后重跑，或把 {CSV_PATH.name} 手动放到：{BASE}\n"
    )


def years(a, b):
    return (b - a).days / 365.25


def fit_line(xs, ys):
    n = len(xs)
    sx, sy = sum(xs), sum(ys)
    sxx = sum(x * x for x in xs)
    sxy = sum(x * y for x, y in zip(xs, ys))
    b = (n * sxy - sx * sy) / (n * sxx - sx * sx)
    return (sy - b * sx) / n, b


def main():
    data = load()
    close = dict(data)
    t0 = data[0][0]
    last_date, last_close = data[-1]

    # 校验关键日期是否都在数据里（数据被截断时给出明确提示，而不是 KeyError）
    need = [dt.strptime(d, "%Y-%m-%d") for d, _ in TURNS] + \
           [dt.strptime(d, "%Y-%m-%d") for d in FIT_LOWS]
    missing = [d.date().isoformat() for d in need if d not in close]
    if missing:
        raise SystemExit(f"数据缺少这些日期：{missing}\n请删除 {CSV_PATH} 后重跑，让它重新联网抓取。")

    turns = []
    for ds, kind in TURNS:
        d = dt.strptime(ds, "%Y-%m-%d")
        turns.append((d, close[d], kind))
    bottoms = [t for t in turns if t[2] == "low"]

    xs = [years(t0, dt.strptime(d, "%Y-%m-%d")) for d in FIT_LOWS]
    ys = [math.log(close[dt.strptime(d, "%Y-%m-%d")]) for d in FIT_LOWS]
    a, b = fit_line(xs, ys)
    ann = (math.exp(b) - 1) * 100

    def line_at(d):
        return math.exp(a + b * years(t0, d))

    line_today = line_at(last_date)
    gap = (last_close / line_today - 1) * 100
    drop_to_line = (line_today / last_close - 1) * 100

    x_left = data[0][0] - timedelta(days=45)
    x_right = dt(2028, 12, 31)

    fig, ax = plt.subplots(figsize=(15, 8.4))
    fig.subplots_adjust(left=0.065, right=0.985, top=0.845, bottom=0.10)

    # 每个三角形下跌阶段的背景色（最后一轮颜色浅，表示未确认）
    for i in (1, 3, 5):
        ax.axvspan(turns[i][0], turns[i + 1][0], color=C_RED, alpha=0.05, zorder=0, lw=0)
    ax.axvspan(turns[7][0], turns[8][0], color=C_RED, alpha=0.03, zorder=0, lw=0)

    ax.plot([d for d, _ in data], [c for _, c in data], color=C_LINE, lw=1.1, zorder=3,
            label="国证价值100 收盘价")

    ax.plot([t[0] for t in turns], [t[1] for t in turns], color=C_ZIG, lw=1.15,
            ls=(0, (5, 3)), zorder=2.6, alpha=0.9)

    x_fit_l = max(x_left, dt(2012, 12, 31))
    ax.plot([x_fit_l, x_right], [line_at(x_fit_l), line_at(x_right)], color=C_FIT, lw=2.3,
            zorder=4, solid_capstyle="round",
            label=f"7 个低点的对数线性拟合（年化 +{ann:.1f}%）")

    for d, v, kind in turns:
        if kind == "low":
            ax.scatter([d], [v], s=62, color=C_RED, zorder=5, edgecolor="white", linewidth=1.4)
        else:
            ax.scatter([d], [v], s=58, marker="^", color=C_PEAK, zorder=5,
                       edgecolor="white", linewidth=1.2)

    # 顶部：点位 + 涨幅
    for i, (d, v, kind) in enumerate(turns):
        if kind != "high":
            continue
        gain = (v / turns[i - 1][1] - 1) * 100
        ax.annotate(f"{d.date()}　{v:,.0f}\n↑ +{gain:.1f}%", xy=(d, v),
                    xytext=(0, 22), textcoords="offset points", fontsize=8.0, color=C_PEAK,
                    ha="center", va="bottom", zorder=6, linespacing=1.35,
                    bbox=dict(boxstyle="round,pad=0.28", fc="white", ec="#cfcfcf", lw=0.7, alpha=0.96),
                    arrowprops=dict(arrowstyle="-", color="#bdbdbd", lw=0.6, shrinkA=0, shrinkB=3))

    # 底部：点位 + 跌幅
    bot_pos = {0: ((18, -16), "left"), 1: ((-18, -26), "right"), 2: ((-18, -28), "right"),
               3: ((-18, -28), "right"), 4: ((-18, -30), "right")}
    for j, idx in enumerate([0, 2, 4, 6, 8]):
        d, v, _ = turns[idx]
        if j == 0:
            txt = f"{d.date()}　{v:,.0f}\n首个低点（基期 1,000）"
        elif j == 4:
            loss = (v / turns[idx - 1][1] - 1) * 100
            txt = f"{d.date()}　{v:,.0f}\n↓ {loss:.1f}%（未确认）"
        else:
            loss = (v / turns[idx - 1][1] - 1) * 100
            txt = f"{d.date()}　{v:,.0f}\n↓ {loss:.1f}%"
        (dx, dy), ha = bot_pos[j]
        if j == 4:
            ax.annotate(txt, xy=(d, v), xytext=(dt(2026, 9, 1), 3700), textcoords="data",
                        fontsize=8.0, color=C_RED, ha="left", va="center", zorder=6,
                        linespacing=1.35,
                        bbox=dict(boxstyle="round,pad=0.28", fc="white", ec="#e8b4b4", lw=0.7, alpha=0.96),
                        arrowprops=dict(arrowstyle="-", color="#e0a0a0", lw=0.6, shrinkA=0, shrinkB=4))
            continue
        ax.annotate(txt, xy=(d, v), xytext=(dx, dy), textcoords="offset points",
                    fontsize=8.0, color=C_RED, ha=ha, va="top", zorder=6, linespacing=1.35,
                    bbox=dict(boxstyle="round,pad=0.28", fc="white", ec="#e8b4b4", lw=0.7, alpha=0.96),
                    arrowprops=dict(arrowstyle="-", color="#e0a0a0", lw=0.6, shrinkA=0, shrinkB=4))

    # 每个三角形的时间跨度
    for i in range(4):
        d0, _, _ = turns[2 * i]
        d1, _, _ = turns[2 * i + 2]
        px, py = CYCLE_POS[i]
        ax.text(px, py, f"{d0.strftime('%Y-%m')} → {d1.strftime('%Y-%m')}　{years(d0, d1):.1f} 年",
                fontsize=7.9, color="#4a4a4a", ha="center", va="center", zorder=7,
                bbox=dict(boxstyle="round,pad=0.26", fc="#f7f9fc", ec="#cdd8e6", lw=0.7, alpha=0.95))

    # 当前点位
    ax.scatter([last_date], [last_close], s=42, facecolor="white", edgecolor="#6f6f6f",
               zorder=8, linewidth=1.4)
    ax.annotate(f"当前 {last_close:,.0f}（{last_date.date()}）\n"
                f"较基线 +{gap:.1f}%｜跌到基线还需 {drop_to_line:.1f}%",
                xy=(last_date, last_close), xytext=(dt(2027, 2, 1), 5050),
                textcoords="data", fontsize=8.0, color="#3a3a3a", ha="left", va="center", zorder=9,
                linespacing=1.4,
                bbox=dict(boxstyle="round,pad=0.35", fc="white", ec="#c9d3df", lw=0.8),
                arrowprops=dict(arrowstyle="-", color="#c9c9c9", lw=0.8, shrinkA=2, shrinkB=4))

    ax.set_yscale("log")
    ax.set_ylim(700, 6200)
    ax.set_xlim(x_left, x_right)
    ax.yaxis.set_major_locator(FixedLocator([800, 1000, 1500, 2000, 3000, 4000, 5000]))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, p: f"{v:,.0f}"))
    ax.yaxis.set_minor_locator(LogLocator(base=10, subs=(2, 3, 4, 5, 6, 7, 8, 9)))
    ax.yaxis.set_minor_formatter(NullFormatter())
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.tick_params(axis="x", labelsize=9.5, colors=C_TXT)
    ax.tick_params(axis="y", labelsize=9.5, colors=C_TXT)
    ax.grid(axis="y", which="major", color=C_GRID, lw=0.7, ls="--", zorder=0)
    ax.grid(axis="y", which="minor", color="#ececec", lw=0.45, ls=":", zorder=0)
    ax.grid(axis="x", which="major", color="#efefef", lw=0.6, zorder=0)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#9a9a9a")

    ax.set_ylabel("指数点位（对数坐标）", fontsize=10.5, color=C_TXT, labelpad=10)
    ax.set_title("国证价值100指数（980081）：四个沿基线上行的三角形，第四个尚未确认",
                 fontsize=16, color="#1f4e79", fontweight="bold", loc="left", pad=40)
    ax.text(0.0, 1.02,
            f"{data[0][0].date()} ~ {last_date.date()}｜底→顶→底 用虚线连接；"
            f"第四轮下跌进行中、低点未确认｜基线年化 +{ann:.1f}%",
            transform=ax.transAxes, fontsize=9.0, color="#5a5a5a")
    ax.legend(loc="upper left", fontsize=8.9, frameon=True, framealpha=0.95,
              edgecolor="#cfcfcf", borderpad=0.7)

    fig.text(0.065, 0.024, "数据来源：国证指数网（cnindex.com.cn）官方日行情　·　绘图：Python / Matplotlib",
             fontsize=8.4, color="#7a7a7a")

    fig.savefig(PNG, facecolor="white")
    fig.savefig(PDF, facecolor="white")
    print(f"saved {PNG.name} / {PDF.name}")
    print(f"基线年化 {ann:.2f}%｜当前 {last_close:.2f}，较基线 {gap:+.1f}%")


if __name__ == "__main__":
    main()
