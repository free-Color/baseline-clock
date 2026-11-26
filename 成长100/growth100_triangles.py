"""国证成长100（980080）三角形周期图

三个沿基线上行的“底→顶→底”三角形，第三个尚未走完：
2013-06-25(1097) → 2015-06-12(4299) → 2019-01-03(1879)
2019-01-03(1879) → 2021-09-15(8559) → 2024-02-05(4153)
2024-02-05(4153) → 2026-06-22(17204) → 2028-04-20(约7527，推演：再跌 2.4 年、−20%)

依赖：matplotlib（自带 numpy）。数据：同目录 cni_980080_daily.csv，缺失时自动从国证指数网抓取。
运行：python growth100_triangles.py
输出：同目录 成长100_三角形周期与推演.png / .pdf
图上另标注：当前点位相对基线的偏离、以及该偏离在历史中的百分位（越低越便宜）。
"""
import csv
import json
import math
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.ticker import FixedLocator, FuncFormatter, LogLocator, NullFormatter

BASE = Path(__file__).resolve().parent
CSV_PATH = BASE / "cni_980080_daily.csv"
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
PROJ_DAYS = float(2.4 * 365.25)   # 再跌两年

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


API = "http://hq.cnindex.com.cn/market/market/getIndexDailyDataWithDataFormat"

# 实时点位：腾讯行情（qt.gtimg.cn，GBK 文本）。
# 980080 是国证自有编码，腾讯只覆盖交易所挂牌的指数（399xxx），没有 980080；
# 因此用跟踪同一指数的 易方达国证成长100ETF（159259，简称“成长ETF易方达”）的当日涨跌幅
# 折算成指数点位：今日点位 ≈ 最后一个收盘 × (1 + ETF 涨跌幅)。日线口径仍是国证官网收盘。
QUOTE_SYMBOL = "sz159259"
QUOTE_URL = "https://qt.gtimg.cn/q=" + QUOTE_SYMBOL
QUOTE_HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"}


def fetch_range(start, end):
    """抓 [start, end] 的日线，返回 [(datetime, close)]；网络异常直接抛出。"""
    q = urllib.parse.urlencode({"indexCode": "980080", "startDate": start,
                                "endDate": end, "frequency": "day"})
    req = urllib.request.Request(f"{API}?{q}", headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=40) as r:
        data = json.loads(r.read().decode("utf-8"))
    rows = [(datetime.strptime(x[0][:10], "%Y-%m-%d"), float(x[1]))
            for x in (data.get("data") or {}).get("data") or []]
    return sorted(rows)


def fetch_full():
    """全量：大区间 + 最近 60 天（接口对长区间只回到较早日期，尾部要单独补）。"""
    today = date.today().isoformat()
    rows = fetch_range("2000-01-01", today)
    rows += fetch_range((date.today() - timedelta(days=60)).isoformat(), today)
    return sorted(dict(rows).items())


def fetch_quote():
    """腾讯实时行情（ETF 代理），返回 (date, price, prev_close, hhmm)；失败抛异常。

    字段（~ 分隔）：3=现价、4=昨收、30=时间戳 yyyyMMddHHmmss。
    """
    req = urllib.request.Request(QUOTE_URL, headers=QUOTE_HEADERS)
    with urllib.request.urlopen(req, timeout=15) as r:
        txt = r.read().decode("gbk", "ignore")
    if '"' not in txt:
        raise ValueError("腾讯接口无数据")
    f = txt.split('"')[1].split("~")
    if len(f) < 33 or not f[3] or not f[4]:
        raise ValueError("腾讯接口无数据")
    price, prev = float(f[3]), float(f[4])
    if price <= 0 or prev <= 0:
        raise ValueError("腾讯行情价格异常")
    d = datetime.strptime(f[30][:8], "%Y%m%d").date()
    return d, price, prev, f[30][8:12]


def fill_live(rows):
    """日线还没更新到当天时，用腾讯行情（ETF 涨跌幅）把序列顺延到当天。

    只追加“当天”这一根；中间缺的交易日由 load() 的日线增量补齐。
    返回 (rows, live_info or None)。
    """
    last_d, last_close = rows[-1][0].date(), rows[-1][1]
    try:
        qd, etf, prev, qt = fetch_quote()
    except Exception as e:  # noqa: BLE001
        print(f"[警告] 实时点位获取失败（{type(e).__name__}: {e}），只用日线")
        return rows, None
    if qd <= last_d:
        return rows, None
    if (qd - last_d).days > 5:
        print(f"[警告] 日线停在 {last_d}，实时已是 {qd}（隔 {(qd - last_d).days} 天），跳过顺延，先补日线")
        return rows, None

    chg = etf / prev - 1
    qp = last_close * (1 + chg)          # ETF 涨跌幅折算成指数点位
    out = list(rows) + [(datetime(qd.year, qd.month, qd.day), qp)]
    live = {"date": qd, "price": qp, "time": qt, "nav_date": last_d,
            "days": 1, "intraday": qt < "1500", "proxy": QUOTE_SYMBOL[-6:]}
    tag = "盘中" if live["intraday"] else "收盘价（日线未出）"
    print(f"日线截至 {last_d}，用腾讯 {QUOTE_SYMBOL[-6:]} {etf:.3f}（{chg:+.2%}）折算，"
          f"顺延 1 天：{qd} {tag} {qp:,.2f}")
    return out, live


def read_csv():
    uniq = {}
    with CSV_PATH.open(encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            try:
                uniq[datetime.strptime(r["date"][:10], "%Y-%m-%d")] = float(r["close"])
            except (ValueError, KeyError):
                continue
    return sorted(uniq.items())


def write_csv(rows):
    with CSV_PATH.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["date", "close"])
        for d, c in rows:
            w.writerow([d.strftime("%Y-%m-%d"), c])


def load():
    """读本目录 CSV，并在每次运行时自动检查/补齐最新数据：

    - 文件缺失或行数太少  → 全量抓取（重试 3 次）
    - 已有数据            → 只抓最近 30 天，与本地最后日期比对，缺几天补几天
    - 联网失败            → 只报警告，继续用本地数据（不会让脚本跑不起来）
    """
    local = read_csv() if CSV_PATH.exists() else []

    if len(local) < 800:
        reason = "不存在" if not local else f"只有 {len(local)} 行"
        print(f"{CSV_PATH.name} {reason}，全量抓取 ...")
        last_err = ""
        for i in range(3):
            try:
                rows = fetch_full()
                if len(rows) >= 800:
                    write_csv(rows)
                    print(f"已保存 {CSV_PATH}（{len(rows)} 行，截至 {rows[-1][0].date()}）")
                    return rows
                last_err = f"只取到 {len(rows)} 行"
            except Exception as e:  # noqa: BLE001
                last_err = f"{type(e).__name__}: {e}"
            print(f"  第 {i + 1} 次抓取失败：{last_err}")
            time.sleep(2)
        raise SystemExit(
            f"\n数据抓取失败（{last_err}）。\n"
            f"请检查网络后重跑，或把 {CSV_PATH.name} 手动放到：{BASE}\n"
        )

    # —— 增量检查：合并后整条重写，天然去重、补缺口 ——
    last_date_local = local[-1][0]
    try:
        recent = fetch_range((last_date_local - timedelta(days=10)).strftime("%Y-%m-%d"),
                             date.today().isoformat())
        merged = dict(local)
        merged.update(dict(recent))
        rows = sorted(merged.items())
        write_csv(rows)
        added = len([d for d in rows if d[0] > last_date_local])
        if added:
            print(f"数据更新：补 {added} 个交易日 → 共 {len(rows)} 行（截至 {rows[-1][0].date()}）")
        else:
            print(f"数据已是最新（{last_date_local.date()}，共 {len(rows)} 行）")
        return rows
    except Exception as e:  # noqa: BLE001
        print(f"[警告] 联网检查失败（{type(e).__name__}: {e}），改用本地数据，截至 {last_date_local.date()}")
        return local


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
    data, live = fill_live(load())
    if len(data) < 100:
        raise SystemExit("数据太少，检查 cni_980080_daily.csv")
    t0 = data[0][0]
    last_date, last_close = data[-1]
    cur_tag = "｜盘中" if (live and live["intraday"]) else ""

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

    # 偏离的历史分位：逐日算「价格/基线−1」，看当前偏离排在历史的第几百分位（越低越便宜）
    # 起点取第一个拟合低点（2013-06），不把基线在数据之前的推演段算进分布
    pct_start = datetime.strptime(TURNS[0][0], "%Y-%m-%d")
    dev_hist = [(v / line_at(d) - 1) * 100 for d, v in data if d >= pct_start]
    pct_rank = 100.0 * sum(1 for x in dev_hist if x <= gap) / len(dev_hist)
    dev_min, dev_max = min(dev_hist), max(dev_hist)
    dev_med = sorted(dev_hist)[len(dev_hist) // 2]

    # 被套时间：价格原地不动，基线要涨多久才追上现价
    t_years = math.log(last_close / line_today) / b if last_close > line_today else 0.0
    catch_date = last_date + timedelta(days=int(round(t_years * 365.25)))
    catch_months = t_years * 12

    proj_date = last_date + timedelta(days=PROJ_DAYS)
    proj_price = line_at(proj_date)

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

    # 当前点位（位置随现价自适应，不再写死坐标）
    ax.scatter([last_date], [last_close], s=44, facecolor="white", edgecolor="#6f6f6f",
               zorder=8, linewidth=1.4)
    label_x = last_date + timedelta(days=12)
    label_y = max(last_close * 1.55, 15000)
    ax.annotate(f"当前 {last_close:,.0f}（{last_date.date()}）{cur_tag}\n"
                f"较基线 {gap:+.0f}%｜历史 {pct_rank:.0f}% 分位｜本轮 {(last_close / turns[-1][1] - 1) * 100:.1f}%",
                xy=(last_date, last_close), xytext=(label_x, label_y),
                textcoords="data", fontsize=8.3, color="#3a3a3a", ha="left", va="center", zorder=9,
                linespacing=1.5,
                bbox=dict(boxstyle="round,pad=0.4", fc="white", ec="#c9d3df", lw=0.8),
                arrowprops=dict(arrowstyle="-", color="#c9c9c9", lw=0.8, shrinkA=2, shrinkB=4))

    # 偏离分位的说明（右下角空白处）
    ax.text(0.575, 0.035,
            f"偏离分位（{pct_start.strftime('%Y-%m')} 起）：逐日算「价格/基线−1」，"
            f"当前 {gap:+.1f}% 排在 {pct_rank:.0f}% 分位\n"
            f"（历史区间 {dev_min:+.0f}% ~ {dev_max:+.0f}%，中位 {dev_med:+.0f}%；越低越便宜）",
            transform=ax.transAxes, fontsize=7.6, color="#7a7a7a", ha="left", va="bottom",
            zorder=9, linespacing=1.4)

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
    live_note = "｜当日为盘中实时点位，收盘后以日线为准" if (live and live["intraday"]) else ""
    ax.text(0.0, 1.02,
            f"{data[0][0].date()} ~ {last_date.date()}｜底→顶→底 用虚线连接，第三个三角形的下行边按"
            f"“再跌 2 年、−20%”推演｜虚线为周期示意、非价格路径｜基线年化 +{ann:.1f}%{live_note}",
            transform=ax.transAxes, fontsize=9.0, color="#5a5a5a")
    ax.legend(loc="upper left", fontsize=8.9, frameon=True, framealpha=0.95,
              edgecolor="#cfcfcf", borderpad=0.7)

    fig.text(0.065, 0.024, "数据来源：国证指数网（cnindex.com.cn）官方日行情　·　盘中顺延按腾讯行情 159259 折算　·　绘图：Python / Matplotlib",
             fontsize=8.4, color="#7a7a7a")

    fig.savefig(PNG, facecolor="white")
    fig.savefig(PDF, facecolor="white")
    print(f"saved {PNG.name} / {PDF.name}")
    print(f"基线年化 {ann:.2f}%｜当前 {last_close:.0f}，较基线 {gap:+.1f}%（历史 {pct_rank:.0f}% 分位）"
          f"，价格不动 {catch_months:.0f} 个月追平（{catch_date.strftime('%Y-%m')}）")
    print(f"推演底 {proj_date.date()} 约 {proj_price:.0f}，基线届时 {proj_price:.0f}")


if __name__ == "__main__":
    main()
