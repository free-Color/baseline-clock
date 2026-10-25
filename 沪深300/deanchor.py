"""债锚（沪深300全收益 vs 放大后的债基基线）——拉取 2026 年数据并计算当前锚位。

背景
----
中证官网的 H00300（沪深300全收益）与 H11023（中证债券型基金指数）在 2026 年断更，
官方数据止于 2025-12-31。本脚本用可用的替代源把 2026 补齐：

    沪深300 价格指数     东财 1.000300 日线（2026-01-05 起，逐日更新）
    沪深300 全收益       价格收益 + 年内股息累积（年化约 4.5%，近似 H00300）
    债基指数             国证 399481 债券型基金指数（2026 逐日更新）
                         用它的日收益率接中证 H11023，保持长期口径不变

口径参数（与前期图表一致，勿随意改动）
----
    k       = 1.4437        债锚 = 1000 × (债基/1000)^k
    起点     2005-01-04 = 1000
    股票     沪深300全收益 H00300
    债基     中证 H11023（2004-2025）→ 国证 399481（2026 起接续）
    底部     13 个历史阶段性底部（2008-11 ~ 2025-04），k 由这些底部的对数最小二乘得出

文件
----
    输入：同级目录 ../csi_H00300_daily.csv、../csi_H11023_daily.csv
    输出：csi_2026_daily.csv、an_anchor_today.csv、deanchor_today.png（--chart）

运行
----
    python deanchor.py            # 计算并打印今日锚位
    python deanchor.py --chart    # 另存一张对数坐标主图
"""
import argparse
import csv
import json
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parent
CSV_TR = BASE.parent / "csi_H00300_daily.csv"
CSV_BOND = BASE.parent / "csi_H11023_daily.csv"
CSV_OUT = BASE / "csi_2026_daily.csv"
CSV_ANCHOR = BASE / "an_anchor_today.csv"
PNG = BASE / "deanchor_today.png"

K = 1.4437
START_BASE = 1000.0
BOND_2025_END = 3282.72          # H11023 2025-12-31 收盘
TR_2025_END = 6826.62            # H00300 2025-12-31 收盘
PX_2025_END = 4717.75            # 沪深300 价格指数 2025-12-31
DIV_ANNUAL = 0.045               # 全收益相对价格指数的年化股息差

BOTTOMS = ["2008-11-04", "2010-07-05", "2012-01-05", "2012-12-03", "2013-06-27",
           "2014-03-20", "2016-01-28", "2019-01-03", "2020-03-23", "2022-10-31",
           "2024-02-02", "2024-09-13", "2025-04-07"]

UA_CNI = {"User-Agent": "Mozilla/5.0"}
UA_EM = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
         "Referer": "https://quote.eastmoney.com/"}


# ---------------------------------------------------------------- 取数
def _get(url, params, headers, timeout=40, retries=3):
    """带重试的 GET（东财/国证接口会偶发断连）。"""
    q = urllib.parse.urlencode(params)
    full = f"{url}?{q}"
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(full, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "ignore")
        except Exception as e:          # noqa: BLE001
            last = e
            time.sleep(1.5 * (i + 1))
    raise last


def fetch_csi300_price(start="2026-01-01", end=None):
    """沪深300 价格指数日线。主源东财，兜底新浪。返回 [(date, close), ...] 升序。"""
    end = end or date.today().isoformat()
    try:
        txt = _get("https://push2his.eastmoney.com/api/qt/stock/kline/get",
                   {"secid": "1.000300", "fields1": "f1,f2,f3,f4,f5",
                    "fields2": "f51,f53", "klt": "101", "fqt": "1",
                    "beg": start.replace("-", ""), "end": end.replace("-", "")}, UA_EM)
        kl = (json.loads(txt).get("data") or {}).get("klines") or []
        out = [(row.split(",")[0][:10], float(row.split(",")[1])) for row in kl]
        if out:
            return sorted(out)
    except Exception as e:              # noqa: BLE001
        print(f"[warn] 东财失败（{type(e).__name__}），改用新浪")

    txt = _get("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
               "CN_MarketData.getKLineData",
               {"symbol": "sh000300", "scale": "240", "ma": "no", "datalen": "400"},
               {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn/"})
    data = json.loads(txt[txt.index("["):txt.rindex("]") + 1])
    out = [(x["day"][:10], float(x["close"])) for x in data if x["day"][:10] >= start]
    return sorted(out)


def fetch_cni_daily(code, start="2005-01-01", end=None):
    """国证指数日线。返回 [(date, close), ...] 升序。"""
    end = end or date.today().isoformat()
    txt = _get("http://hq.cnindex.com.cn/market/market/getIndexDailyDataWithDataFormat",
               {"indexCode": code, "startDate": start, "endDate": end, "frequency": "day"},
               UA_CNI, timeout=60)
    rows = (json.loads(txt).get("data") or {}).get("data") or []
    out = [(x[0][:10], float(x[1])) for x in rows if x[1] is not None]
    return sorted(out)


def read_csv_close(path):
    out = []
    with path.open(encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            try:
                out.append((r["date"][:10], float(r["close"])))
            except (KeyError, ValueError):
                continue
    return sorted(out)


# ---------------------------------------------------------------- 拼接 2026
def build_2026():
    """返回 [(date, tr_abs, bond_abs), ...]：2026 年的全收益与债基绝对值。"""
    price = fetch_csi300_price()
    if not price:
        raise SystemExit("东财 2026 数据为空")
    bond_ref = fetch_cni_daily("399481", start="2025-12-01")
    if len(bond_ref) < 2:
        raise SystemExit("国证 399481 数据为空")

    # 债基：用 399481 相对 2025-12-31 的累计涨幅，接到中证 H11023 的 3282.72 上
    base = next((v for k, v in bond_ref if k == "2025-12-31"), None)
    if base is None:                     # 参考序列没有 12-31 时退化为首个
        base = bond_ref[0][1]
    j = 0
    out = []
    for d, px in price:
        while j + 1 < len(bond_ref) and bond_ref[j + 1][0] <= d:
            j += 1
        bond = BOND_2025_END * bond_ref[j][1] / base
        days = (date.fromisoformat(d) - date(2025, 12, 31)).days
        tr = TR_2025_END * (1 + (px / PX_2025_END - 1)) * (1 + DIV_ANNUAL * days / 365.25)
        out.append((d, tr, bond))
    return out


# ---------------------------------------------------------------- 债锚
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chart", action="store_true", help="另存一张对数坐标主图")
    args = ap.parse_args()

    tr_hist = dict(read_csv_close(CSV_TR))
    bd_hist = dict(read_csv_close(CSV_BOND))
    common = sorted(set(tr_hist) & set(bd_hist))
    if not common:
        raise SystemExit("历史 CSV 为空")
    tr0, bd0 = tr_hist[common[0]], bd_hist[common[0]]
    print(f"历史（中证）: {common[0]} ~ {common[-1]}，{len(common)} 行")

    y = build_2026()
    print(f"2026（拼接）: {y[0][0]} ~ {y[-1][0]}，{len(y)} 行")

    with CSV_OUT.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["date", "tr", "bond"])
        w.writerows(y)

    d_last, tr_last, bd_last = y[-1]
    trn = tr_last / TR_2025_END * 6946.0          # 2025 末 = 6946（2005 起点 1000 口径）
    bdn = bd_last / BOND_2025_END * 3168.0
    anchor = START_BASE * (bdn / START_BASE) ** K
    pos = trn / anchor - 1

    print("\n=== 债锚 ===")
    print(f"日期          {d_last}")
    print(f"沪深300全收益 {tr_last:,.0f}（归一 {trn:,.0f}）")
    print(f"债基          {bd_last:,.0f}（归一 {bdn:,.0f}）")
    print(f"债锚          {anchor:,.0f}")
    print(f"锚位          {pos:+.2%}")
    print(f"距债锚还需跌  {anchor / trn - 1:+.2%}")

    with CSV_ANCHOR.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["date", "tr", "tr_1000", "bond", "bond_1000", "anchor", "position"])
        w.writerow([d_last, f"{tr_last:.2f}", f"{trn:.2f}", f"{bd_last:.2f}",
                    f"{bdn:.2f}", f"{anchor:.2f}", f"{pos:.6f}"])

    if args.chart:
        _chart(common, tr_hist, bd_hist, tr0, bd0, y, anchor, pos, d_last)


def _chart(common, tr_hist, bd_hist, tr0, bd0, y, anchor, pos, d_last):
    import datetime as dt

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FixedLocator, FuncFormatter, NullFormatter

    plt.rcParams.update({"font.sans-serif": ["Microsoft YaHei", "SimHei"],
                         "font.family": "sans-serif", "axes.unicode_minus": False})

    xs = [dt.datetime.strptime(d, "%Y-%m-%d") for d in common]
    s = [tr_hist[d] / tr0 * 1000.0 for d in common]
    b = [bd_hist[d] / bd0 * 1000.0 for d in common]
    for d, tr, bd in y:
        xs.append(dt.datetime.strptime(d, "%Y-%m-%d"))
        s.append(tr / TR_2025_END * 6946.0)
        b.append(bd / BOND_2025_END * 3168.0)
    adj = [1000.0 * (v / 1000.0) ** K for v in b]

    fig, ax = plt.subplots(figsize=(13.8, 7.4), dpi=150)
    ax.plot(xs, s, color="#C0392B", lw=1.3, label="沪深300全收益（起点 1000）")
    ax.plot(xs, b, color="#1F6FB2", lw=0.9, alpha=0.3, ls="--", label="债基原始（起点 1000）")
    ax.plot(xs, adj, color="#1F6FB2", lw=2.1, label=f"债锚 = 1000×(债基/1000)^{K}")
    ax.fill_between(xs, [v * 0.915 for v in adj], adj, color="#1F6FB2", alpha=0.10,
                    label="历史底部跌破带（最深 -8.5%）")
    ax.scatter([xs[-1]], [s[-1]], s=90, color="#C0392B", edgecolor="black", zorder=5)
    ax.annotate(f"今日 {s[-1]:,.0f}", (xs[-1], s[-1]), xytext=(-78, 18),
                textcoords="offset points", fontsize=10, color="#7B241C", fontweight="bold")
    ax.set_yscale("log")
    ax.yaxis.set_major_locator(FixedLocator([1000, 1500, 2000, 3000, 5000, 7000]))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, p: f"{v:,.0f}"))
    ax.yaxis.set_minor_formatter(NullFormatter())
    ax.grid(True, alpha=0.25)
    ax.legend(loc="upper left", frameon=False, fontsize=9.5)
    ax.set_title(f"债锚（对数坐标，起点 1000，截至 {d_last}，锚位 {pos:+.1%}）", fontsize=13)
    ax.xaxis.set_major_locator(mdates.YearLocator(2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    fig.tight_layout()
    fig.savefig(PNG, bbox_inches="tight")
    print(f"\n已保存图：{PNG.name}")


if __name__ == "__main__":
    main()
