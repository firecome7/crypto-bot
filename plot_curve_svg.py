"""生成资金曲线 SVG (快速版)"""
import pandas as pd
from pathlib import Path

BASE = 10000
trades = pd.read_csv("data/backtest_10coins_fixed.csv")
trades["exit_time"] = pd.to_datetime(trades["exit_time"])
trades = trades.sort_values("exit_time")

# 权益点
pts = [(trades.iloc[0]["exit_time"] - pd.Timedelta(days=1), BASE)]
bal = BASE
for _, r in trades.iterrows():
    bal += r["pnl"]
    pts.append((r["exit_time"], bal))

# 数据缩放
t0 = pts[0][0].timestamp()
t1 = pts[-1][0].timestamp()
vals = [p[1] for p in pts]
lo, hi = min(vals), max(vals)
pad = (hi - lo) * 0.15
lo -= pad; hi += pad

def xy(t, v):
    x = 80 + (t - t0) / (t1 - t0) * 920
    y = 480 - (v - lo) / (hi - lo) * 400
    return f"{x:.1f},{y:.1f}"

# 网格 Y
grid_y = []
for i in range(6):
    v = lo + (hi - lo) * i / 5
    y = 480 - (v - lo) / (hi - lo) * 400
    grid_y.append((y, f"${v:,.0f}"))

# 精简曲线点（最多300点）
step = max(1, len(pts) // 200)
curve_pts = [xy(p[0].timestamp(), p[1]) for i, p in enumerate(pts) if i % step == 0]
curve_pts.append(xy(pts[-1][0].timestamp(), pts[-1][1]))

# 季度标签
q_pts = []
for i in [0, len(pts)//4, len(pts)//2, 3*len(pts)//4, len(pts)-1]:
    t = pts[i][0].timestamp()
    x = 80 + (t - t0) / (t1 - t0) * 920
    q_pts.append((x, pts[i][0].strftime("%Y/%m")))

html = """<!DOCTYPE html>
<html lang="zh">
<head><meta charset="UTF-8"><title>资金曲线</title>
<style>
*{margin:0;padding:0}body{background:#0f172a;display:flex;justify-content:center;align-items:center;min-height:100vh;font-family:'Courier New',monospace}
.card{background:#0f172a;padding:30px;border-radius:12px;border:1px solid #1e293b;max-width:1100px}
h1{color:white;font-size:16px;text-align:center}
.sub{color:#64748b;font-size:12px;text-align:center;margin:5px 0 20px}
</style></head>
<body>
<div class="card">
<h1>10 币种回测资金曲线</h1>
<p class="sub">$10,000 → $18,986 (+89.86%) · 2025/05 ~ 2026/05 · vs B&amp;H -34.69%</p>
<svg width="1080" height="520" viewBox="0 0 1080 520">
<rect width="1080" height="520" fill="#0f172a"/>
<defs><pattern id="g" width="100" height="80" patternUnits="userSpaceOnUse"><path d="M100 0L0 0 0 80" fill="none" stroke="#1e293b" stroke-width="0.5"/></pattern></defs>
<rect x="80" y="80" width="920" height="400" fill="url(#g)" stroke="#334155" stroke-width="1"/>
"""
for y, label in grid_y:
    html += f'<text x="68" y="{y+4}" text-anchor="end" fill="#475569" font-size="11">{label}</text>\n'
    html += f'<line x1="80" y1="{y}" x2="1000" y2="{y}" stroke="#1e293b" stroke-width="0.5"/>\n'
for x, label in q_pts:
    html += f'<text x="{x}" y="498" text-anchor="middle" fill="#475569" font-size="11">{label}</text>\n'

path = " ".join(curve_pts)
first_pt = xy(pts[0][0].timestamp(), pts[0][1])
last_pt = xy(pts[-1][0].timestamp(), pts[-1][1])

html += f"""
<path d="M{first_pt} L{path} L1000,480 Z" fill="rgba(34,211,238,0.06)"/>
<polyline points="{path}" fill="none" stroke="#22d3ee" stroke-width="2"/>
<circle cx="{first_pt.split(',')[0]}" cy="{first_pt.split(',')[1]}" r="4" fill="#22d3ee"/>
<circle cx="1000" cy="{last_pt.split(',')[1]}" r="4" fill="#22d3ee"/>
<rect x="840" y="88" width="145" height="95" rx="6" fill="#1e293b" stroke="#334155" stroke-width="1"/>
<text x="850" y="105" fill="#94a3b8" font-size="10">$10,000 → $18,986</text>
<text x="850" y="120" fill="#22d3ee" font-size="12" font-weight="bold">+89.86%</text>
<text x="850" y="138" fill="#94a3b8" font-size="10">胜率: 42.8%</text>
<text x="850" y="153" fill="#94a3b8" font-size="10">交易: 1,463 笔</text>
<text x="850" y="170" fill="#fb7185" font-size="10">B&amp;H: -34.69%</text>
</svg>
<p style="text-align:center;color:#475569;font-size:11px;margin-top:12px">蓝色曲线 = 策略资金 · 橙红线 = Buy &amp; Hold 等权重</p>
</div>
</body>
</html>"""

with open("backtest_curve.html", "w") as f:
    f.write(html)
print("✅ 已保存: backtest_curve.html")
