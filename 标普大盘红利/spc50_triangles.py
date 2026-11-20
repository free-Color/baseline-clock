"""标普中国A股大盘红利低波50（全收益）三角形周期图

数据说明：标普该指数（SPCLLHCP.GI）没有公开日线接口，这里用跟踪它的
「南方标普中国A股大盘红利低波50ETF（515450）」的**净值 + 分红再投资**做全收益代理，
序列从 2020-01-17（基金成立）起。净值 ×1000 画图（成立日 = 1000）。

当日净值一般收盘后晚上才出，所以净值序列没更新到今天时，用 515450 的**成交价**
（腾讯前复权日线，当日那根是实时滚动的）把序列顺延到当天，盘中即可看到当日点位。

画法与标普红利 / 价值100 一致：对数坐标、大底基线、底→顶→底虚线三角形、每轮下跌背景色，
外加「偏离历史分位」与「追平时间」（价格不动、基线多久追上现价）。

依赖：matplotlib。数据：同目录 spc50_515450_tr.csv（缺失自动联网抓取）。
运行：python spc50_triangles.py
输出：同目录 标普大盘红利50_三角形周期.png / .pdf
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
CSV_PATH = BASE / "spc50_515450_tr.csv"
PNG = BASE / "标普大盘红利.png"
PDF = BASE / "标普大盘红利.pdf"

plt.rcParams.update({
    "font.sans-serif": ["Microsoft YaHei", "SimHei"],
    "font.family": "sans-serif",
    "axes.unicode_minus": False,
    "figure.dpi": 110,
    "savefig.dpi": 200,
})

SCALE = 1000.0  # 净值 ×1000 显示

# 底/顶交替：三轮完整三角形 + 当前上行段（2024-09-30 的 924 行情尖顶视为噪声，略）
TURNS = [("2020-03-23", "low"), ("2022-02-11", "high"), ("2022-10-31", "low"),
         ("2024-05-27", "high"), ("2024-09-13", "low"), ("2026-03-17", "high"),
         ("2026-06-30", "low")]

# 基线用的四个低点（2026-06-30 这个尚未确认）
FIT_LOWS = ["2020-03-23", "2022-10-31", "2024-09-13", "2026-06-30"]

# 每个三角形的下跌阶段（背景色）
DROPS = [("2022-02-11", "2022-10-31"), ("2024-05-27", "2024-09-13"),
         ("2026-03-17", "2026-06-30")]

C_LINE = "#2f5d8a"
C_RED = "#c00000"
C_FIT = "#8b0000"
C_PEAK = "#4d4d4d"
C_ZIG = "#8f98a3"
C_GRID = "#d9d9d9"
C_TXT = "#3a3a3a"

CYCLE_POS = [(dt(2021, 6, 1), 983), (dt(2023, 7, 1), 1140), (dt(2025, 8, 1), 1400)]
BOT_POS = [(14, -18), (-14, -34), (-10, -54), (10, -52)]

NAV_URL = "https://stock.finance.sina.com.cn/fundInfo/api/openapi.php/CaihuiFundInfoService.getNav"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"}
SYMBOL = "515450"
SYMBOL_TX = "sh515450"  # 腾讯行情代码


def fetch_nav_range(start, end, symbol=SYMBOL):
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
            w.writerow([d.strftime("%Y-%m-%d"), f"{nav:.4f}", f"{cum:.4f}", f"{tr:.6f}"])


def fetch_recent_closes(count=60):
    """腾讯前复权日线（当日那根随盘中滚动），返回 [(date, close)] 升序。"""
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={SYMBOL_TX},day,,,{count},qfq"
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=25) as r:
        payload = json.loads(r.read().decode("utf-8"))
    node = payload["data"][SYMBOL_TX]
    bars = node.get("qfqday") or node.get("day") or []
    out = [(dt.strptime(b[0][:10], "%Y-%m-%d").date(), float(b[2])) for b in bars]
    return sorted(out)


def fetch_quote():
    """最新成交：返回 (date, price, hhmm)。"""
    req = urllib.request.Request(f"https://qt.gtimg.cn/q={SYMBOL_TX}",
                                 headers={**HEADERS, "Referer": "https://finance.sina.com.cn"})
    with urllib.request.urlopen(req, timeout=20) as r:
        txt = r.read().decode("gbk", "ignore")
    f = txt.split('"')[1].split("~")
    return dt.strptime(f[30][:8], "%Y%m%d").date(), float(f[3]), f[30][8:12]


def fill_live(rows):
    """净值还没更新到当天时，用成交价（前复权）把全收益序列顺延到当天。

    做法：以最后一个净值日的收盘价为基准，逐日累乘成交价涨幅；
    分红已含在前复权里，与净值口径一致。返回 (rows, live_info or None)。
    """
    last_d = rows[-1][0].date() if hasattr(rows[-1][0], "date") else rows[-1][0]
    try:
        bars = [(d, c) for d, c in fetch_recent_closes() if c > 0]
    except Exception as e:  # noqa: BLE001
        print(f"⚠ 当日成交价获取失败（{type(e).__name__}: {e}），只用净值")
        return rows, None
    if not bars or bars[-1][0] <= last_d:
        return rows, None

    base = None
    start = None
    for i, (d, c) in enumerate(bars):
        if d <= last_d:
            base, start = c, i
    if base is None or start is None:
        print("⚠ 成交价序列未覆盖最后一个净值日，跳过顺延")
        return rows, None

    out = list(rows)
    for d, c in bars[start + 1:]:
        r = c / base - 1
        _, pn, pc, pt = out[-1]
        out.append((dt.combine(d, dt.min.time()), pn * (1 + r), pc + max(pn * r, 0.0), pt * (1 + r)))
        base = c

    last_row = out[-1][0]
    last_row = last_row.date() if hasattr(last_row, "date") else last_row
    try:
        qd, qp, qt = fetch_quote()
    except Exception:  # noqa: BLE001
        qd, qp, qt = last_row, 0.0, ""
    if qd != last_row:
        qp, qt = 0.0, ""
    live = {"date": last_row, "price": qp, "time": qt,
            "nav_date": last_d, "days": len(out) - len(rows),
            "intraday": bool(qt) and qt < "1500"}

    tag = "盘中" if live["intraday"] else "收盘价（净值未出）"
    print(f"净值截至 {last_d}，用成交价顺延 {live['days']} 天："
          f"{live['date']} {tag} {out[-1][3] * SCALE:,.0f}")
    return out, live


def load():
    """读本地 CSV 并自动补齐最新净值；净值没到今天就用成交价顺延。"""
    local = read_csv() if CSV_PATH.exists() else []

    if len(local) < 500:
        reason = "不存在" if not local else f"只有 {len(local)} 行"
        print(f"{CSV_PATH.name} {reason}，全量抓取 ...")
        last_err = ""
        for i in range(3):
            try:
                raw = fetch_nav_range("2019-01-01", date.today().isoformat())
                if len(raw) >= 500:
                    rows = build_tr(raw)
                    write_csv(rows)
                    print(f"已保存 {CSV_PATH.name}（{len(rows)} 行，截至 {rows[-1][0].date()}）")
                    return fill_live(rows)
                last_err = f"只取到 {len(raw)} 行"
            except Exception as e:  # noqa: BLE001
                last_err = f"{type(e).__name__}: {e}"
            print(f"  第 {i + 1} 次抓取失败：{last_err}")
            time.sleep(2)
        raise SystemExit(f"抓取失败（{last_err}）。请把 {CSV_PATH.name} 放到 {BASE}")

    last_d = local[-1][0]
    try:
        raw = fetch_nav_range((last_d - timedelta(days=30)).strftime("%Y-%m-%d"),
                              date.today().isoformat())
        merged = {d: (nav, cum) for d, nav, cum in local}
        before = dict(merged)
        merged.update({d: (nav, cum) for d, nav, cum in raw})
        added = len([d for d in merged if d not in before])
        rows = build_tr([(d, nav, cum) for d, (nav, cum) in sorted(merged.items())])
        write_csv(rows)
        if added == 0:
            print(f"数据已是最新（{last_d.date()}，共 {len(rows)} 行）")
        else:
            print(f"数据更新：新增 {added} 个净值日，共 {len(rows)} 行（截至 {rows[-1][0].date()}）")
    except Exception as e:  # noqa: BLE001
        print(f"⚠ 联网检查失败（{type(e).__name__}: {e}），改用本地数据，截至 {last_d.date()}")
        rows = build_tr(local)
    return fill_live(rows)


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
    rows, live = load()
    data = [(d, tr) for d, _nav, _cum, tr in rows]
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

    # 偏离分位：逐日算「价格/基线−1」，起点取第一个拟合低点
    pct_start = dt.strptime(FIT_LOWS[0], "%Y-%m-%d")
    dev_hist = [((v * SCALE) / line_at(d) - 1) * 100 for d, v in data if d >= pct_start]
    pct_rank = 100.0 * sum(1 for x in dev_hist if x <= gap) / len(dev_hist)
    dev_min, dev_max = min(dev_hist), max(dev_hist)
    dev_med = sorted(dev_hist)[len(dev_hist) // 2]

    # 追平时间（被套时间）：价格原地不动，基线要涨多久才追上现价
    # 现价在基线上方时 = 现在买入、价格不动，趋势线多久追上你的成本
    t_years = math.log(last_close / line_today) / b if last_close > line_today else 0.0
    catch_date = last_date + timedelta(days=int(round(t_years * 365.25)))
    catch_months = t_years * 12
    catch_price = line_at(catch_date)

    x_left = data[0][0] - timedelta(days=20)
    x_right = dt(2028, 12, 31)

    fig, ax = plt.subplots(figsize=(15, 8.4))
    fig.subplots_adjust(left=0.065, right=0.985, top=0.845, bottom=0.10)

    for i, (p, t) in enumerate(DROPS):
        ax.axvspan(dt.strptime(p, "%Y-%m-%d"), dt.strptime(t, "%Y-%m-%d"),
                   color=C_RED, alpha=0.05 if i < 2 else 0.03, zorder=0, lw=0)

    ax.plot([d for d, _ in data], [c * SCALE for _, c in data], color=C_LINE, lw=1.15,
            zorder=3, label="标普A股大盘红利低波50（全收益：分红再投资，515450 ×1000）")

    # 净值未更新到今天时，最后一段按当日成交价顺延（橙色虚线 + 空心点）
    if live:
        prev_d, prev_v = data[-2]
        ax.plot([prev_d, last_date], [prev_v * SCALE, last_close], color="#e07b00", lw=1.2,
                ls=(0, (3, 2)), zorder=3.4)

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
                    xytext=(0, 20), textcoords="offset points", fontsize=8.0, color=C_PEAK,
                    ha="center", va="bottom", zorder=6, linespacing=1.35,
                    bbox=dict(boxstyle="round,pad=0.28", fc="white", ec="#cfcfcf", lw=0.7, alpha=0.96),
                    arrowprops=dict(arrowstyle="-", color="#bdbdbd", lw=0.6, shrinkA=0, shrinkB=3))

    for j, idx in enumerate([0, 2, 4, 6]):
        d, v, _ = turns[idx]
        if j == 0:
            txt = f"{d.date()}　{v:,.0f}\n2020 疫情底（成立以来最低）"
        else:
            loss = (v / turns[idx - 1][1] - 1) * 100
            txt = f"{d.date()}　{v:,.0f}\n↓ {loss:.1f}%"
        dx, dy = BOT_POS[j]
        ax.annotate(txt, xy=(d, v), xytext=(dx, dy), textcoords="offset points",
                    fontsize=7.9, color=C_RED, ha="left" if dx > 0 else "center", va="top",
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

    pt_color = "#e07b00" if live else "#6f6f6f"
    ax.scatter([last_date], [last_close], s=46, facecolor="white", edgecolor=pt_color,
               zorder=8, linewidth=1.6)
    if live:
        tag = (f"盘中 {live['price']:.3f}" if live["intraday"]
               else f"收盘成交价 {live['price']:.3f}（净值未出）")
        ax.annotate(tag, xy=(last_date, last_close), xytext=(0, -16), textcoords="offset points",
                    fontsize=7.6, color="#b35c00", ha="center", va="top", zorder=9,
                    bbox=dict(boxstyle="round,pad=0.24", fc="white", ec="#f0c98a", lw=0.7, alpha=0.95))

    if last_close > line_today:
        extra = (f"跌到基线还需 {abs(need):.1f}%\n"
                 f"价格不动约 {catch_months:.0f} 个月追平（{catch_date.strftime('%Y-%m')}）")
    else:
        extra = (f"回到基线还需 {need:.1f}%（已在基线下方，不必等追平）")

    stamp = last_date.strftime("%Y-%m-%d")
    if live:
        stamp += " 盘中" if live["intraday"] else " 净值未出"

    ax.annotate(f"当前 {last_close:,.0f}（{stamp}）\n"
                f"较基线 {gap:+.1f}%｜历史 {pct_rank:.0f}% 分位\n{extra}",
                xy=(last_date, last_close), xytext=(dt(2027, 3, 10), 2270),
                textcoords="data", fontsize=8.0, color="#3a3a3a", ha="left", va="center", zorder=9,
                linespacing=1.4,
                bbox=dict(boxstyle="round,pad=0.35", fc="white", ec="#c9d3df", lw=0.8),
                arrowprops=dict(arrowstyle="-", color="#c9c9c9", lw=0.8, shrinkA=2, shrinkB=4))

    # 追平时间：从现价画一条水平虚线到基线追平的位置
    ax.plot([last_date, catch_date], [last_close, last_close], color="#9aa0a6", lw=1.0,
            ls=(0, (2, 3)), zorder=6)
    ax.scatter([catch_date], [catch_price], s=46, marker="D", facecolor="white",
               edgecolor=C_FIT, linewidth=1.4, zorder=8)
    ax.text(catch_date + timedelta(days=10), catch_price * 0.955,
            f"基线追平 {catch_date.strftime('%Y-%m')}（{catch_months:.0f} 个月后）",
            fontsize=7.6, color=C_FIT, ha="left", va="top", zorder=9)

    ax.text(0.52, 0.035,
            f"偏离分位（{pct_start.strftime('%Y-%m')} 起）：逐日算「价格/基线−1」，"
            f"当前 {gap:+.1f}% 排在 {pct_rank:.0f}% 分位\n"
            f"（历史区间 {dev_min:+.0f}% ~ {dev_max:+.0f}%，中位 {dev_med:+.0f}%）",
            transform=ax.transAxes, fontsize=7.6, color="#7a7a7a", ha="left", va="bottom",
            zorder=9, linespacing=1.4)

    ax.set_yscale("log")
    ax.set_ylim(800, 2700)
    ax.set_xlim(x_left, x_right)
    ax.yaxis.set_major_locator(FixedLocator([900, 1000, 1200, 1500, 1800, 2100, 2400]))
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
    ax.set_title("标普大盘红利50（全收益）：沿基线上行的三角形周期",
                 fontsize=16, color="#1f4e79", fontweight="bold", loc="left", pad=40)
    ax.text(0.0, 1.02,
            f"{data[0][0].date()} ~ {last_date.date()}｜标普中国A股大盘红利低波50（SPCLLHCP），"
            f"以 515450 的「分红在除息日再投资」序列为全收益代理（×1000）"
            f"｜底→顶→底 虚线连接｜基线年化 +{ann:.1f}%",
            transform=ax.transAxes, fontsize=9.0, color="#5a5a5a")
    ax.legend(loc="upper left", fontsize=8.8, frameon=True, framealpha=0.95,
              edgecolor="#cfcfcf", borderpad=0.7)

    fig.text(0.065, 0.024,
             "数据来源：新浪财经基金净值（515450，分红再投资复权）＋ 腾讯行情当日成交价（盘中顺延）"
             "　·　绘图：Python / Matplotlib",
             fontsize=8.4, color="#7a7a7a")

    fig.savefig(PNG, facecolor="white")
    fig.savefig(PDF, facecolor="white")
    print(f"saved {PNG.name} / {PDF.name}")
    print(f"年化 {ann:.2f}%｜当前 {last_close:.0f}，较基线 {gap:+.1f}%（历史 {pct_rank:.0f}% 分位）"
          f"，价格不动 {catch_months:.0f} 个月追平（{catch_date.strftime('%Y-%m')}）")


if __name__ == "__main__":
    main()
