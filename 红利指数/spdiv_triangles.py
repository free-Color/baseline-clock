"""标普中国A股红利机会指数（全收益）三角形周期图

数据说明：标普该指数没有公开的日线接口，这里用跟踪它的
「华宝标普中国A股红利机会指数A（501029）」的**累计净值**做全收益代理
（累计净值 = 单位净值 + 累计分红，近似红利再投资的总收益），序列从 2017-01-19 起。
为便于阅读，净值 ×1000 画图（2017-01-19 = 1000）。

画法与价值100一致：对数坐标、大底基线、底→顶→底虚线三角形、每轮下跌背景色。

依赖：matplotlib。数据：同目录 spdiv_501029_nav.csv（缺失自动联网抓取）。
运行：python spdiv_triangles.py
输出：同目录 标普红利_三角形周期.png / .pdf
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
CSV_PATH = BASE / "spdiv_501029_tr.csv"
PNG = BASE / "标普红利_三角形周期.png"
PDF = BASE / "标普红利_三角形周期.pdf"

plt.rcParams.update({
    "font.sans-serif": ["Microsoft YaHei", "SimHei"],
    "font.family": "sans-serif",
    "axes.unicode_minus": False,
    "figure.dpi": 110,
    "savefig.dpi": 200,
})

SCALE = 1000.0  # 净值 ×1000 显示

# 底/顶交替（只保留三次主要下跌；2024-10→2025-04 那次 −10.9% 的中级回撤忽略）
TURNS = [("2018-10-18", "low"), ("2022-04-06", "high"), ("2022-10-31", "low"),
         ("2024-05-29", "high"), ("2024-09-13", "low"), ("2026-02-11", "high"),
         ("2026-06-30", "low")]

# 基线用的低点（四个三角形底，最后一个未确认）
FIT_LOWS = ["2018-10-18", "2022-10-31", "2024-09-13", "2026-06-30"]

# 每个三角形的下跌阶段（背景色）
DROPS = [("2018-01-26", "2018-10-18"), ("2022-04-06", "2022-10-31"),
         ("2024-05-29", "2024-09-13"), ("2026-02-11", "2026-06-30")]

C_LINE = "#2f5d8a"
C_RED = "#c00000"
C_FIT = "#8b0000"
C_PEAK = "#4d4d4d"
C_ZIG = "#8f98a3"
C_GRID = "#d9d9d9"
C_TXT = "#3a3a3a"

CYCLE_POS = [(dt(2019, 9, 1), 1600), (dt(2023, 6, 1), 1600), (dt(2025, 3, 1), 1960)]
BOT_POS = [(20, -18), (-20, -26), (-20, -28), (20, -26)]


NAV_URL = "https://stock.finance.sina.com.cn/fundInfo/api/openapi.php/CaihuiFundInfoService.getNav"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"}


def fetch_nav_range(start, end, symbol="501029"):
    """抓 [start, end] 的单位净值 + 累计净值，返回 [(date, nav, cum)]，按日期升序。"""
    raw, page = [], 1
    while True:
        q = urllib.parse.urlencode({"symbol": symbol, "datefrom": start, "dateto": end,
                                    "page": page, "num": 100})
        req = urllib.request.Request(f"{NAV_URL}?{q}", headers=HEADERS)
        with urllib.request.urlopen(req, timeout=40) as r:
            payload = json.loads(r.read().decode("utf-8"))["result"]["data"]
        batch = payload["data"]
        if not batch:
            break
        raw += [(dt.strptime(x["fbrq"][:10], "%Y-%m-%d"), float(x["jjjz"]), float(x["ljjz"]))
                for x in batch]
        if len(raw) >= int(payload["total_num"]):
            break
        page += 1
        time.sleep(0.2)
    uniq = {}
    for d, n, c in raw:
        uniq[d] = (n, c)
    return [(d, n, c) for d, (n, c) in sorted(uniq.items())]


def build_tr(raw):
    """把 (date, nav, cum) 链式复权成 (date, nav, cum, tr)：分红在除息日按当日净值再投资。"""
    rows = []
    tr = raw[0][1]
    rows.append((raw[0][0], raw[0][1], raw[0][2], tr))
    for i in range(1, len(raw)):
        div = (raw[i][2] - raw[i][1]) - (raw[i - 1][2] - raw[i - 1][1])
        tr *= (raw[i][1] + max(div, 0.0)) / raw[i - 1][1]
        rows.append((raw[i][0], raw[i][1], raw[i][2], tr))
    return rows


def read_csv():
    """读本地 CSV，返回 [(date, nav, cum)]，按日期去重（同日多行时保留最后一行）。"""
    uniq = {}
    with CSV_PATH.open(encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            try:
                uniq[dt.strptime(r["date"][:10], "%Y-%m-%d")] = (float(r["nav"]), float(r["cum"]))
            except (ValueError, KeyError):
                continue
    return [(d, nav, cum) for d, (nav, cum) in sorted(uniq.items())]


def write_csv(rows):
    with CSV_PATH.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["date", "nav", "cum", "tr"])
        for d, nav, cum, tr in rows:
            w.writerow([d.strftime("%Y-%m-%d"), nav, cum, tr])


def load():
    """读本目录 CSV，并在每次运行时自动检查/补齐最新净值：

    - 文件缺失或行数太少  → 全量抓（重试 3 次）
    - 已有数据            → 抓最近 30 天并合并，然后**从头重算**分红再投资序列
                            （同时修掉重复行、补上中间缺口）
    - 联网失败            → 只报警告，继续用本地数据（不会让脚本跑不起来）
    """
    local = read_csv() if CSV_PATH.exists() else []

    if len(local) < 500:
        reason = "不存在" if not local else f"只有 {len(local)} 行"
        print(f"{CSV_PATH.name} {reason}，全量抓取 ...")
        last_err = ""
        for i in range(3):
            try:
                raw = fetch_nav_range("2000-01-01", date.today().isoformat())
                if len(raw) >= 500:
                    rows = build_tr(raw)
                    write_csv(rows)
                    print(f"已保存 {CSV_PATH}（{len(rows)} 行，截至 {rows[-1][0].date()}）")
                    return rows
                last_err = f"只取到 {len(raw)} 行"
            except Exception as e:  # noqa: BLE001
                last_err = f"{type(e).__name__}: {e}"
            print(f"  第 {i + 1} 次抓取失败：{last_err}")
            time.sleep(2)
        raise SystemExit(f"抓取失败（{last_err}）。请把 {CSV_PATH.name} 放到 {BASE}")

    # —— 增量检查：合并后整条重算，天然去重、补缺口 ——
    last_d = local[-1][0]
    try:
        raw = fetch_nav_range((last_d - timedelta(days=30)).strftime("%Y-%m-%d"),
                              date.today().isoformat())
        merged = {d: (nav, cum) for d, nav, cum in local}
        before = dict(merged)
        merged.update({d: (nav, cum) for d, nav, cum in raw})
        added = len([d for d in merged if d not in before])
        fixed = len(before) - len({d for d in before if d in merged and merged[d] == before[d]})
        rows = build_tr([(d, nav, cum) for d, (nav, cum) in sorted(merged.items())])
        write_csv(rows)          # 每次都重写：顺便把重复行/乱序清掉
        if added == 0 and fixed == 0:
            print(f"数据已是最新（{last_d.date()}，共 {len(rows)} 行）")
        else:
            print(f"数据更新：新增 {added} 个净值日，修正 {fixed} 行，"
                  f"共 {len(rows)} 行（截至 {rows[-1][0].date()}）")
        return rows
    except Exception as e:  # noqa: BLE001
        print(f"⚠ 联网检查失败（{type(e).__name__}: {e}），改用本地数据，截至 {last_d.date()}")
        return build_tr(local)


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
    rows = load()
    data = [(d, tr) for d, _nav, _cum, tr in rows]   # 只用全收益序列画图
    close = dict(data)
    t0 = data[0][0]
    last_date, last_close = data[-1]
    last_close *= SCALE

    turns = [(dt.strptime(d, "%Y-%m-%d"), close[dt.strptime(d, "%Y-%m-%d")] * SCALE, k)
             for d, k in TURNS]

    xs = [years(t0, dt.strptime(d, "%Y-%m-%d")) for d in FIT_LOWS]
    ys = [math.log(close[dt.strptime(d, "%Y-%m-%d")] * SCALE) for d in FIT_LOWS]
    a, b = fit_line(xs, ys)
    ann = (math.exp(b) - 1) * 100

    def line_at(d):
        return math.exp(a + b * years(t0, d))

    line_today = line_at(last_date)
    gap = (last_close / line_today - 1) * 100
    need = (line_today / last_close - 1) * 100

    x_left = data[0][0] - timedelta(days=30)
    x_right = dt(2028, 6, 30)

    fig, ax = plt.subplots(figsize=(15, 8.4))
    fig.subplots_adjust(left=0.065, right=0.985, top=0.845, bottom=0.10)

    for i, (p, t) in enumerate(DROPS):
        ax.axvspan(dt.strptime(p, "%Y-%m-%d"), dt.strptime(t, "%Y-%m-%d"),
                   color=C_RED, alpha=0.05 if i < 4 else 0.03, zorder=0, lw=0)

    ax.plot([d for d, _ in data], [c * SCALE for _, c in data], color=C_LINE, lw=1.15,
            zorder=3, label="标普A股红利（全收益：分红再投资，501029 ×1000）")

    ax.plot([t[0] for t in turns], [t[1] for t in turns], color=C_ZIG, lw=1.15,
            ls=(0, (5, 3)), zorder=2.6, alpha=0.9)

    ax.plot([x_left, x_right], [line_at(x_left), line_at(x_right)], color=C_FIT, lw=2.3,
            zorder=4, solid_capstyle="round",
            label=f"{len(FIT_LOWS)} 个低点的对数线性拟合（年化 +{ann:.1f}%）")

    for d, v, kind in turns:
        if kind == "low":
            ax.scatter([d], [v], s=62, color=C_RED, zorder=5, edgecolor="white", linewidth=1.4)
        else:
            ax.scatter([d], [v], s=58, marker="^", color=C_PEAK, zorder=5,
                       edgecolor="white", linewidth=1.2)

    for i, (d, v, kind) in enumerate(turns):
        if kind != "high":
            continue
        gain = (v / turns[i - 1][1] - 1) * 100
        ax.annotate(f"{d.date()}　{v:,.0f}\n↑ +{gain:.1f}%", xy=(d, v),
                    xytext=(0, 22), textcoords="offset points", fontsize=8.0, color=C_PEAK,
                    ha="center", va="bottom", zorder=6, linespacing=1.35,
                    bbox=dict(boxstyle="round,pad=0.28", fc="white", ec="#cfcfcf", lw=0.7, alpha=0.96),
                    arrowprops=dict(arrowstyle="-", color="#bdbdbd", lw=0.6, shrinkA=0, shrinkB=3))

    for j, idx in enumerate([0, 2, 4, 6]):
        d, v, _ = turns[idx]
        if j == 0:
            txt = f"{d.date()}　{v:,.0f}\n2018 熊市底（自 2018-01 高点 −28.7%）"
        elif j == 3:
            loss = (v / turns[idx - 1][1] - 1) * 100
            txt = f"{d.date()}　{v:,.0f}\n↓ {loss:.1f}%（未确认）"
        else:
            loss = (v / turns[idx - 1][1] - 1) * 100
            txt = f"{d.date()}　{v:,.0f}\n↓ {loss:.1f}%"
        dx, dy = BOT_POS[j]
        ax.annotate(txt, xy=(d, v), xytext=(dx, dy), textcoords="offset points",
                    fontsize=7.9, color=C_RED, ha="left" if dx > 0 else "right", va="top",
                    zorder=6, linespacing=1.35,
                    bbox=dict(boxstyle="round,pad=0.28", fc="white", ec="#e8b4b4", lw=0.7, alpha=0.96),
                    arrowprops=dict(arrowstyle="-", color="#e0a0a0", lw=0.6, shrinkA=0, shrinkB=4))

    for i in range(3):
        d0, _, _ = turns[2 * i]
        d1, _, _ = turns[2 * i + 2]
        px, py = CYCLE_POS[i]
        ax.text(px, py, f"{d0.strftime('%Y-%m')} → {d1.strftime('%Y-%m')}　{years(d0, d1):.1f} 年",
                fontsize=7.8, color="#4a4a4a", ha="center", va="center", zorder=7,
                bbox=dict(boxstyle="round,pad=0.26", fc="#f7f9fc", ec="#cdd8e6", lw=0.7, alpha=0.95))

    ax.scatter([last_date], [last_close], s=42, facecolor="white", edgecolor="#6f6f6f",
               zorder=8, linewidth=1.4)
    ax.annotate(f"当前 {last_close:,.0f}（{last_date.date()}）\n"
                f"较基线 {gap:+.1f}%｜跌到基线还需 {need:.1f}%",
                xy=(last_date, last_close), xytext=(dt(2026, 11, 20), 2300),
                textcoords="data", fontsize=8.0, color="#3a3a3a", ha="left", va="center", zorder=9,
                linespacing=1.4,
                bbox=dict(boxstyle="round,pad=0.35", fc="white", ec="#c9d3df", lw=0.8),
                arrowprops=dict(arrowstyle="-", color="#c9c9c9", lw=0.8, shrinkA=2, shrinkB=4))

    ax.set_yscale("log")
    ax.set_ylim(720, 2600)
    ax.set_xlim(x_left, x_right)
    ax.yaxis.set_major_locator(FixedLocator([800, 1000, 1200, 1500, 1800, 2100]))
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

    ax.set_ylabel("全收益净值 ×1000（对数坐标）", fontsize=10.5, color=C_TXT, labelpad=10)
    ax.set_title("标普中国A股红利机会指数（全收益）：沿基线上行的三角形周期",
                 fontsize=16, color="#1f4e79", fontweight="bold", loc="left", pad=40)
    ax.text(0.0, 1.02,
            f"{data[0][0].date()} ~ {last_date.date()}｜以 501029 的「分红在除息日再投资」序列为全收益代理（×1000）"
            f"｜底→顶→底 虚线连接｜基线年化 +{ann:.1f}%",
            transform=ax.transAxes, fontsize=9.0, color="#5a5a5a")
    ax.legend(loc="upper left", fontsize=8.8, frameon=True, framealpha=0.95,
              edgecolor="#cfcfcf", borderpad=0.7)

    fig.text(0.065, 0.024,
             "数据来源：新浪财经基金净值（501029，分红再投资复权）　·　绘图：Python / Matplotlib",
             fontsize=8.4, color="#7a7a7a")

    fig.savefig(PNG, facecolor="white")
    fig.savefig(PDF, facecolor="white")
    print(f"saved {PNG.name} / {PDF.name}")
    print(f"年化 {ann:.2f}%｜当前 {last_close:.0f}，较基线 {gap:+.1f}%，跌到基线 {need:.1f}%")


if __name__ == "__main__":
    main()
