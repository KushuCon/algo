"""
utils/report_generator.py
─────────────────────────
Generates a beautiful self-contained HTML report + CSV trade log
for any backtest run.  Called automatically from backtest.py main().

Output folder: <project_root>/reports/
File names   : backtest_<strategy>_<YYYYMMDD_HHMMSS>.html
               backtest_<strategy>_<YYYYMMDD_HHMMSS>_trades.csv
"""

from __future__ import annotations

import os
import json
import textwrap
from datetime import datetime
from pathlib import Path

import pandas as pd
import numpy as np


# ── helpers ────────────────────────────────────────────────────────────────────

def _pct(v: float, decimals: int = 2) -> str:
    return f"{v*100:+.{decimals}f}%"

def _usd(v: float) -> str:
    sign = "+" if v >= 0 else ""
    return f"{sign}${v:,.2f}"

def _color(v: float) -> str:
    return "#22c55e" if v >= 0 else "#ef4444"   # green / red


def build_trade_pairs(trades_df: pd.DataFrame) -> pd.DataFrame:
    """
    Match every buy → its corresponding exit (sell / stop_loss / take_profit /
    close_eob) per symbol in chronological order, producing one row per
    completed trade with hold_days and % gain.
    """
    if trades_df is None or trades_df.empty:
        return pd.DataFrame()

    df = trades_df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)

    EXIT_ACTIONS = {"sell", "stop_loss", "take_profit", "close_eob"}
    rows = []
    open_q: dict[str, list] = {}   # symbol → list of pending buy rows

    for _, row in df.iterrows():
        sym = row["symbol"]
        act = row["action"]

        if act == "buy":
            open_q.setdefault(sym, []).append(row)

        elif act in EXIT_ACTIONS:
            if open_q.get(sym):
                buy_row = open_q[sym].pop(0)
                hold = (row["date"] - buy_row["date"]).days
                entry = float(buy_row["price"])
                exit_ = float(row["price"])
                pct_gain = (exit_ - entry) / entry if entry else 0.0
                rows.append({
                    "symbol":     sym,
                    "buy_date":   buy_row["date"].date(),
                    "sell_date":  row["date"].date(),
                    "hold_days":  hold,
                    "entry_price":round(entry, 2),
                    "exit_price": round(exit_, 2),
                    "qty":        int(buy_row["qty"]),
                    "pnl_usd":    round(float(row["pnl"]), 2),
                    "pct_gain":   round(pct_gain * 100, 2),
                    "exit_type":  act,
                })

    return pd.DataFrame(rows)


# ── main entry point ───────────────────────────────────────────────────────────

def generate_report(
    strategy_name: str,
    symbols: list[str],
    results: dict,
    metrics: dict,
    days: int,
    output_dir: str | Path | None = None,
) -> str:
    """
    Build the HTML report and companion CSV.

    Returns the path to the HTML file.
    """
    # ── Setup paths ────────────────────────────────────────────────────────────
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = strategy_name.replace(" ", "_").lower()

    if output_dir is None:
        # Resolve relative to this file → <project>/reports/
        here = Path(__file__).resolve().parent.parent
        output_dir = here / "reports"

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    html_path = output_dir / f"backtest_{safe_name}_{ts}.html"
    csv_path  = output_dir / f"backtest_{safe_name}_{ts}_trades.csv"

    # ── Build trade pairs ──────────────────────────────────────────────────────
    pairs = build_trade_pairs(results.get("trades", pd.DataFrame()))

    # ── Save CSV ───────────────────────────────────────────────────────────────
    if not pairs.empty:
        pairs.to_csv(csv_path, index=False)

    # ── Equity curve data for chart ────────────────────────────────────────────
    eq = results["equity_curve"]["equity"]
    eq_dates  = [str(d)[:10] for d in eq.index]
    eq_values = [round(float(v), 2) for v in eq.values]

    # ── Per-symbol summary ─────────────────────────────────────────────────────
    sym_rows_html = ""
    if not pairs.empty:
        sym_grp = (
            pairs.groupby("symbol")
            .agg(
                trades=("pnl_usd", "count"),
                wins=("pnl_usd", lambda x: (x > 0).sum()),
                total_pnl=("pnl_usd", "sum"),
                avg_hold=("hold_days", "mean"),
                best_pct=("pct_gain", "max"),
                worst_pct=("pct_gain", "min"),
            )
            .reset_index()
        )
        sym_grp["win_rate"] = (sym_grp["wins"] / sym_grp["trades"] * 100).round(1)
        sym_grp["avg_hold"] = sym_grp["avg_hold"].round(1)
        sym_grp["total_pnl"] = sym_grp["total_pnl"].round(2)

        for _, r in sym_grp.iterrows():
            pnl_color = _color(r["total_pnl"])
            best_color = _color(r["best_pct"])
            worst_color = _color(r["worst_pct"])
            sym_rows_html += f"""
            <tr>
              <td class="sym">{r['symbol']}</td>
              <td>{int(r['trades'])}</td>
              <td>{r['win_rate']}%</td>
              <td style="color:{pnl_color};font-weight:600">${r['total_pnl']:,.2f}</td>
              <td>{r['avg_hold']}d</td>
              <td style="color:{best_color}">{r['best_pct']:+.2f}%</td>
              <td style="color:{worst_color}">{r['worst_pct']:+.2f}%</td>
            </tr>"""

    # ── Trade log rows ─────────────────────────────────────────────────────────
    trade_rows_html = ""
    if not pairs.empty:
        sorted_pairs = pairs.sort_values("buy_date")
        for _, r in sorted_pairs.iterrows():
            pnl_color = _color(r["pnl_usd"])
            pct_color = _color(r["pct_gain"])

            exit_badge = {
                "take_profit": '<span class="badge green">✓ Target</span>',
                "stop_loss":   '<span class="badge red">✗ Stop</span>',
                "sell":        '<span class="badge blue">→ Sell</span>',
                "close_eob":   '<span class="badge gray">⏹ EOB</span>',
            }.get(r["exit_type"], r["exit_type"])

            trade_rows_html += f"""
            <tr>
              <td class="sym">{r['symbol']}</td>
              <td>{r['buy_date']}</td>
              <td>{r['sell_date']}</td>
              <td><strong>{r['hold_days']}d</strong></td>
              <td>${r['entry_price']:,.2f}</td>
              <td>${r['exit_price']:,.2f}</td>
              <td>{r['qty']}</td>
              <td style="color:{pct_color};font-weight:700">{r['pct_gain']:+.2f}%</td>
              <td style="color:{pnl_color};font-weight:600">${r['pnl_usd']:,.2f}</td>
              <td>{exit_badge}</td>
            </tr>"""

    # ── Summary stats ──────────────────────────────────────────────────────────
    m = metrics
    initial     = results["initial"]
    final       = results["final"]
    total_pnl   = final - initial
    avg_hold    = round(pairs["hold_days"].mean(), 1) if not pairs.empty else "–"
    max_hold    = int(pairs["hold_days"].max()) if not pairs.empty else "–"
    avg_win_pnl = round(pairs[pairs["pnl_usd"] > 0]["pnl_usd"].mean(), 2) if not pairs.empty else 0
    avg_los_pnl = round(pairs[pairs["pnl_usd"] < 0]["pnl_usd"].mean(), 2) if not pairs.empty else 0
    best_trade  = pairs.loc[pairs["pct_gain"].idxmax()] if not pairs.empty else None
    worst_trade = pairs.loc[pairs["pct_gain"].idxmin()] if not pairs.empty else None

    best_str  = f"{best_trade['symbol']} {best_trade['pct_gain']:+.2f}% in {best_trade['hold_days']}d" if best_trade is not None else "–"
    worst_str = f"{worst_trade['symbol']} {worst_trade['pct_gain']:+.2f}% in {worst_trade['hold_days']}d" if worst_trade is not None else "–"

    ret_color  = _color(m["total_return"])
    pnl_color  = _color(total_pnl)

    # ── HTML ───────────────────────────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Backtest Report — {strategy_name.upper()}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  :root {{
    --bg: #0f172a; --card: #1e293b; --border: #334155;
    --text: #e2e8f0; --muted: #94a3b8; --accent: #6366f1;
    --green: #22c55e; --red: #ef4444; --yellow: #f59e0b; --blue: #38bdf8;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: 'Segoe UI', system-ui, sans-serif; font-size: 14px; line-height: 1.6; }}
  .page {{ max-width: 1280px; margin: 0 auto; padding: 24px 20px; }}

  /* header */
  .header {{ display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 28px; flex-wrap: wrap; gap: 12px; }}
  .header h1 {{ font-size: 26px; font-weight: 700; letter-spacing: -.5px; }}
  .header h1 span {{ color: var(--accent); }}
  .meta {{ color: var(--muted); font-size: 12px; margin-top: 4px; }}
  .badge-run {{ background: var(--accent); color: #fff; border-radius: 6px; padding: 4px 12px; font-size: 12px; font-weight: 600; }}

  /* KPI grid */
  .kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 14px; margin-bottom: 28px; }}
  .kpi {{ background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 16px 18px; }}
  .kpi .label {{ font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: .6px; margin-bottom: 6px; }}
  .kpi .value {{ font-size: 22px; font-weight: 700; }}
  .kpi .sub {{ font-size: 11px; color: var(--muted); margin-top: 2px; }}

  /* chart card */
  .card {{ background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 20px; margin-bottom: 24px; }}
  .card-title {{ font-size: 15px; font-weight: 600; margin-bottom: 14px; color: var(--text); }}
  .chart-wrap {{ position: relative; height: 280px; }}

  /* tables */
  .table-wrap {{ overflow-x: auto; }}
  table {{ width: 100%; border-collapse: collapse; }}
  thead tr {{ background: #0f172a; }}
  th {{ padding: 10px 12px; text-align: left; font-size: 11px; text-transform: uppercase; letter-spacing: .5px; color: var(--muted); border-bottom: 1px solid var(--border); white-space: nowrap; }}
  td {{ padding: 9px 12px; border-bottom: 1px solid #1e293b; font-size: 13px; white-space: nowrap; }}
  tr:hover td {{ background: rgba(99,102,241,.07); }}
  td.sym {{ font-weight: 700; color: var(--accent); font-size: 14px; }}

  /* badges */
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 99px; font-size: 11px; font-weight: 600; }}
  .badge.green {{ background: rgba(34,197,94,.15); color: var(--green); }}
  .badge.red   {{ background: rgba(239,68,68,.15);  color: var(--red);   }}
  .badge.blue  {{ background: rgba(56,189,248,.15); color: var(--blue);  }}
  .badge.gray  {{ background: rgba(148,163,184,.1); color: var(--muted); }}

  /* highlights row */
  .highlights {{ display: flex; gap: 14px; flex-wrap: wrap; margin-bottom: 24px; }}
  .hl {{ background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 12px 18px; flex: 1; min-width: 180px; }}
  .hl .hl-label {{ font-size: 11px; color: var(--muted); text-transform: uppercase; margin-bottom: 4px; }}
  .hl .hl-val   {{ font-size: 15px; font-weight: 700; }}

  /* footer */
  footer {{ text-align: center; color: var(--muted); font-size: 11px; margin-top: 32px; padding-top: 16px; border-top: 1px solid var(--border); }}
</style>
</head>
<body>
<div class="page">

  <!-- Header -->
  <div class="header">
    <div>
      <h1>Backtest Report — <span>{strategy_name.upper()}</span></h1>
      <div class="meta">
        Symbols: {' · '.join(symbols)} &nbsp;|&nbsp;
        Period: {days}d &nbsp;|&nbsp;
        Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
      </div>
    </div>
    <span class="badge-run">algo v1</span>
  </div>

  <!-- KPI Grid -->
  <div class="kpi-grid">
    <div class="kpi">
      <div class="label">Total Return</div>
      <div class="value" style="color:{_color(m['total_return'])}">{_pct(m['total_return'])}</div>
      <div class="sub">${initial:,.0f} → ${final:,.0f}</div>
    </div>
    <div class="kpi">
      <div class="label">Net P&amp;L</div>
      <div class="value" style="color:{pnl_color}">{_usd(total_pnl)}</div>
      <div class="sub">absolute dollars</div>
    </div>
    <div class="kpi">
      <div class="label">Annual Return</div>
      <div class="value" style="color:{_color(m['annual_return'])}">{_pct(m['annual_return'])}</div>
      <div class="sub">annualised</div>
    </div>
    <div class="kpi">
      <div class="label">Sharpe Ratio</div>
      <div class="value">{m['sharpe']:.3f}</div>
      <div class="sub">risk-adjusted</div>
    </div>
    <div class="kpi">
      <div class="label">Calmar Ratio</div>
      <div class="value">{m['calmar']:.3f}</div>
      <div class="sub">return / max-dd</div>
    </div>
    <div class="kpi">
      <div class="label">Max Drawdown</div>
      <div class="value" style="color:var(--red)">{_pct(m['max_drawdown'])}</div>
      <div class="sub">peak → trough</div>
    </div>
    <div class="kpi">
      <div class="label">Win Rate</div>
      <div class="value">{m['win_rate']:.1%}</div>
      <div class="sub">{int(m['win_rate']*m['n_trades'])} / {m['n_trades']} trades</div>
    </div>
    <div class="kpi">
      <div class="label">Avg Hold</div>
      <div class="value">{avg_hold}d</div>
      <div class="sub">max {max_hold}d</div>
    </div>
  </div>

  <!-- Equity Curve -->
  <div class="card">
    <div class="card-title">📈 Equity Curve</div>
    <div class="chart-wrap">
      <canvas id="eqChart"></canvas>
    </div>
  </div>

  <!-- Trade Highlights -->
  <div class="highlights">
    <div class="hl">
      <div class="hl-label">🏆 Best Trade</div>
      <div class="hl-val" style="color:var(--green)">{best_str}</div>
    </div>
    <div class="hl">
      <div class="hl-label">💥 Worst Trade</div>
      <div class="hl-val" style="color:var(--red)">{worst_str}</div>
    </div>
    <div class="hl">
      <div class="hl-label">💰 Avg Win P&amp;L</div>
      <div class="hl-val" style="color:var(--green)">${avg_win_pnl:,.2f}</div>
    </div>
    <div class="hl">
      <div class="hl-label">📉 Avg Loss P&amp;L</div>
      <div class="hl-val" style="color:var(--red)">${avg_los_pnl:,.2f}</div>
    </div>
  </div>

  <!-- Per-Symbol Summary -->
  <div class="card">
    <div class="card-title">📊 Per-Symbol Performance</div>
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th>Symbol</th><th>Trades</th><th>Win Rate</th>
          <th>Total P&amp;L</th><th>Avg Hold</th>
          <th>Best %</th><th>Worst %</th>
        </tr></thead>
        <tbody>{sym_rows_html}</tbody>
      </table>
    </div>
  </div>

  <!-- Full Trade Log -->
  <div class="card">
    <div class="card-title">📋 Full Trade Log</div>
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th>Symbol</th><th>Entry Date</th><th>Exit Date</th>
          <th>Hold</th><th>Entry $</th><th>Exit $</th>
          <th>Qty</th><th>% Gain</th><th>P&amp;L</th><th>Exit Type</th>
        </tr></thead>
        <tbody>{trade_rows_html}</tbody>
      </table>
    </div>
  </div>

  <footer>
    Report: backtest_{safe_name}_{ts}.html &nbsp;·&nbsp;
    CSV: backtest_{safe_name}_{ts}_trades.csv
  </footer>
</div>

<script>
const labels = {json.dumps(eq_dates)};
const values = {json.dumps(eq_values)};
const initial = {initial};

const ctx = document.getElementById('eqChart').getContext('2d');
const gradient = ctx.createLinearGradient(0, 0, 0, 280);
gradient.addColorStop(0, 'rgba(99,102,241,0.35)');
gradient.addColorStop(1, 'rgba(99,102,241,0.00)');

new Chart(ctx, {{
  type: 'line',
  data: {{
    labels,
    datasets: [{{
      label: 'Portfolio Value',
      data: values,
      borderColor: '#6366f1',
      backgroundColor: gradient,
      borderWidth: 2,
      pointRadius: 0,
      fill: true,
      tension: 0.3,
    }}, {{
      label: 'Initial Capital',
      data: labels.map(() => initial),
      borderColor: 'rgba(148,163,184,0.3)',
      borderWidth: 1,
      borderDash: [4,4],
      pointRadius: 0,
      fill: false,
    }}]
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    interaction: {{ mode: 'index', intersect: false }},
    plugins: {{
      legend: {{ labels: {{ color: '#94a3b8', font: {{ size: 12 }} }} }},
      tooltip: {{
        backgroundColor: '#1e293b',
        borderColor: '#334155',
        borderWidth: 1,
        titleColor: '#e2e8f0',
        bodyColor: '#94a3b8',
        callbacks: {{
          label: ctx => ' $' + ctx.parsed.y.toLocaleString(undefined, {{minimumFractionDigits:2, maximumFractionDigits:2}})
        }}
      }}
    }},
    scales: {{
      x: {{
        ticks: {{ color: '#64748b', maxTicksLimit: 10, font: {{ size: 11 }} }},
        grid:  {{ color: 'rgba(51,65,85,0.4)' }}
      }},
      y: {{
        ticks: {{
          color: '#64748b', font: {{ size: 11 }},
          callback: v => '$' + v.toLocaleString()
        }},
        grid: {{ color: 'rgba(51,65,85,0.4)' }}
      }}
    }}
  }}
}});
</script>
</body>
</html>"""

    html_path.write_text(html, encoding="utf-8")
    print(f"\n{'─'*60}")
    print(f"  📄 HTML Report : {html_path}")
    if not pairs.empty:
        print(f"  📊 CSV Trades  : {csv_path}")
    print(f"{'─'*60}\n")

    return str(html_path)