# -*- coding: utf-8 -*-
"""
智能补货建议工具
功能：
  1. 读取 SKU 近 4 周销售 CSV → 计算加权移动平均日销量
  2. 结合当前库存、在途数量、安全库存天数 → 输出建议补货量
  3. 紧急程度分级：立即补货 / 本周补货 / 暂缓补货
  4. 输出 Markdown + HTML 报告
用法：
  python replenishment_advisor.py
输入：sales_data.csv（演示数据自动生成）
输出：replenishment_report.md / replenishment_report.html
"""
import csv, os, datetime, math, html

# ========== 1. 演示数据生成（30个SKU） ==========
DEMO_SKUS = [
    # (sku, name, cat, wh, w1, w2, w3, w4, stock, intransit, lead_time, supplier)
    ("SP-001","蓝牙耳机 Pro","数码","华东仓",1050,1080,1120,950,1850,600,7,"恒达电子"),
    ("SP-002","无线充电板","数码","华东仓",720,680,700,700,320,200,5,"恒达电子"),
    ("SP-003","智能手环","数码","华南仓",920,880,950,850,60,0,7,"中芯微"),
    ("SP-004","USB-C 数据线","数码","华北仓",2100,2200,2050,2150,4200,1000,3,"中芯微"),
    ("SP-005","北欧风落地灯","家居","华东仓",120,110,115,105,1200,0,10,"光禾家居"),
    ("SP-006","记忆棉枕芯","家居","华南仓",170,165,175,170,2100,300,7,"光禾家居"),
    ("SP-007","不锈钢保温杯","家居","华北仓",310,290,300,300,340,800,5,"膳品"),
    ("SP-008","坚果礼盒装","食品","华东仓",820,790,810,780,180,600,5,"三只松"),
    ("SP-009","冻干咖啡","食品","华南仓",240,230,245,235,2800,0,7,"三只松"),
    ("SP-010","手冲滤纸","食品","华北仓",280,270,285,265,520,400,5,"三只松"),
    ("SP-011","机械键盘","数码","华东仓",460,440,450,450,50,0,7,"恒达电子"),
    ("SP-012","桌面台灯","家居","华南仓",95,90,100,95,1500,0,10,"光禾家居"),
    ("SP-013","速食燕麦","食品","华北仓",560,540,555,545,260,800,5,"三只松"),
    ("SP-014","蓝牙音箱","数码","华南仓",410,390,420,380,480,200,7,"中芯微"),
    ("SP-015","收纳整理箱","家居","华东仓",135,128,132,125,2400,0,10,"光禾家居"),
    ("SP-016","便携榨汁机","数码","华东仓",320,310,330,315,680,200,7,"恒达电子"),
    ("SP-017","保温便当袋","家居","华南仓",85,80,90,85,1800,0,10,"光禾家居"),
    ("SP-018","燕麦能量棒","食品","华北仓",680,650,670,660,140,0,3,"三只松"),
    ("SP-019","迷你投影仪","数码","华东仓",180,170,185,175,90,150,10,"恒达电子"),
    ("SP-020","加湿器","数码","华南仓",260,250,270,255,320,200,7,"中芯微"),
    ("SP-021","香薰蜡烛","家居","华东仓",70,65,75,70,950,0,10,"光禾家居"),
    ("SP-022","速溶咖啡","食品","华南仓",410,390,420,400,280,400,5,"三只松"),
    ("SP-023","运动水壶","家居","华北仓",160,150,165,155,580,300,5,"膳品"),
    ("SP-024","手机支架","数码","华东仓",520,490,510,500,1200,400,3,"中芯微"),
    ("SP-025","竹纤维毛巾","家居","华南仓",110,105,115,108,1600,0,7,"光禾家居"),
    ("SP-026","黑巧克力","食品","华北仓",340,320,345,330,210,500,5,"三只松"),
    ("SP-027","电动牙刷","数码","华东仓",290,280,295,285,160,300,7,"恒达电子"),
    ("SP-028","护颈枕","家居","华南仓",130,125,135,128,720,200,7,"光禾家居"),
    ("SP-029","坚果混合装","食品","华北仓",580,550,575,560,90,0,5,"三只松"),
    ("SP-030","蓝牙鼠标","数码","华东仓",220,210,225,215,380,150,5,"中芯微"),
]

def gen_demo_csv(path="sales_data.csv"):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["sku","name","category","warehouse","week1_sales","week2_sales","week3_sales","week4_sales","current_stock","intransit","lead_time_days","supplier"])
        for r in DEMO_SKUS:
            w.writerow(r)
    print(f"演示数据已生成: {path}（{len(DEMO_SKUS)} 个 SKU）")

# ========== 2. 加权移动平均预测 ==========
def weighted_moving_avg(w1, w2, w3, w4):
    """4周加权移动平均，越近权重越大: 0.1/0.2/0.3/0.4"""
    total = w1 + w2 + w3 + w4
    if total == 0:
        return 0
    daily = total / 28  # 4周=28天
    # 加权：最近的周权重最高
    weighted = (w1 * 0.1 + w2 * 0.2 + w3 * 0.3 + w4 * 0.4) / 28
    return round(weighted, 1)

# ========== 3. 补货建议计算 ==========
SAFE_STOCK_DAYS = 7  # 安全库存天数
REPLENISH_CYCLE = 7  # 补货周期（天）

def calc_replenishment(row):
    """计算补货建议"""
    w1 = float(row["week1_sales"])
    w2 = float(row["week2_sales"])
    w3 = float(row["week3_sales"])
    w4 = float(row["week4_sales"])
    stock = float(row["current_stock"])
    intransit = float(row["intransit"])
    lead_time = float(row["lead_time_days"])

    daily_avg = weighted_moving_avg(w1, w2, w3, w4)
    safe_stock = daily_avg * SAFE_STOCK_DAYS
    cycle_demand = daily_avg * REPLENISH_CYCLE
    # 可用库存 = 当前库存 + 在途
    available = stock + intransit
    # 覆盖天数 = 可用库存 / 日均销量
    cover_days = round(available / daily_avg, 1) if daily_avg > 0 else 999

    # 建议补货量 = (安全库存 + 周期需求) - 可用库存
    suggest_qty = max(0, round(safe_stock + cycle_demand - available))

    # 紧急程度
    if cover_days <= 3:
        urgency = "立即补货"
        urgency_cn = "red"
    elif cover_days <= 7:
        urgency = "本周补货"
        urgency_cn = "yellow"
    else:
        urgency = "暂缓补货"
        urgency_cn = "green"

    # 周转天数（基于当前库存）
    turnover_days = round(stock / daily_avg) if daily_avg > 0 else 999
    # 滞销判定
    if turnover_days > 45:
        urgency = "暂缓补货（滞销）"
        urgency_cn = "red"
        suggest_qty = 0

    return {
        "sku": row["sku"],
        "name": row["name"],
        "category": row["category"],
        "warehouse": row["warehouse"],
        "daily_avg": daily_avg,
        "current_stock": int(stock),
        "intransit": int(intransit),
        "available": int(available),
        "safe_stock": round(safe_stock),
        "cover_days": cover_days,
        "turnover_days": turnover_days,
        "suggest_qty": suggest_qty,
        "urgency": urgency,
        "urgency_cls": urgency_cn,
        "lead_time": int(lead_time),
        "supplier": row["supplier"],
    }

# ========== 4. 报告生成 ==========
def generate_report(results, output_md="replenishment_report.md", output_html="replenishment_report.html"):
    # 汇总
    total_skus = len(results)
    urgent = [r for r in results if "立即" in r["urgency"]]
    weekly = [r for r in results if "本周" in r["urgency"]]
    hold = [r for r in results if "暂缓" in r["urgency"]]
    total_suggest = sum(r["suggest_qty"] for r in results)

    # Markdown
    lines = []
    lines.append("# 智能补货建议报告\n")
    lines.append(f"生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
    lines.append(f"分析 SKU 数: {total_skus}\n")
    lines.append(f"- 立即补货: {len(urgent)} 个")
    lines.append(f"- 本周补货: {len(weekly)} 个")
    lines.append(f"- 暂缓补货: {len(hold)} 个")
    lines.append(f"- 建议补货总量: {total_suggest} 件\n")
    lines.append("\n## 明细\n")
    lines.append("| SKU | 名称 | 日均销量 | 库存 | 在途 | 覆盖天数 | 周转天数 | 建议补货量 | 紧急程度 | 供应商 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for r in sorted(results, key=lambda x: x["cover_days"]):
        lines.append(f"| {r['sku']} | {r['name']} | {r['daily_avg']} | {r['current_stock']} | {r['intransit']} | {r['cover_days']}天 | {r['turnover_days']}天 | {r['suggest_qty']} | {r['urgency']} | {r['supplier']} |")
    lines.append("\n---")
    lines.append("本报告由智能补货建议工具自动生成 | github.com/46bzvs7m64-gif/replenishment-advisor")

    with open(output_md, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"Markdown 报告: {output_md}")

    # HTML
    color_map = {"red": "#dc2626", "yellow": "#d97706", "green": "#059669"}
    bg_map = {"red": "#fee2e2", "yellow": "#fef3c7", "green": "#d1fae5"}
    rows_html = ""
    for r in sorted(results, key=lambda x: x["cover_days"]):
        c = color_map[r["urgency_cls"]]
        bg = bg_map[r["urgency_cls"]]
        rows_html += f"""<tr>
          <td>{r['sku']}</td><td>{html.escape(r['name'])}</td><td>{r['category']}</td><td>{r['warehouse']}</td>
          <td>{r['daily_avg']}</td><td>{r['current_stock']}</td><td>{r['intransit']}</td><td>{r['available']}</td>
          <td>{r['cover_days']}天</td><td>{r['turnover_days']}天</td>
          <td style="text-align:right;font-weight:700;">{r['suggest_qty']}</td>
          <td><span style="background:{bg};color:{c};padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;">{r['urgency']}</span></td>
          <td>{r['supplier']}</td>
        </tr>\n"""

    h = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><title>智能补货建议报告</title>
<style>
  *{{margin:0;padding:0;box-sizing:border-box}}
  body{{font-family:"Microsoft YaHei",sans-serif;color:#1a1a2e;background:#f4f5f9;padding:16px}}
  .container{{max-width:1100px;margin:0 auto}}
  h1{{font-size:20px;margin-bottom:4px}}
  .meta{{font-size:12px;color:#888;margin-bottom:16px}}
  .kpi-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:16px}}
  .kpi{{background:#fff;border-radius:10px;padding:14px;text-align:center}}
  .kpi .label{{font-size:11px;color:#888}}.kpi .value{{font-size:24px;font-weight:700;margin:4px 0}}
  .section{{background:#fff;border-radius:10px;padding:16px;margin-bottom:16px;overflow-x:auto}}
  table{{width:100%;border-collapse:collapse;font-size:12px}}
  th{{text-align:left;padding:8px 6px;border-bottom:2px solid #e5e7eb;color:#6b7280;font-size:11px}}
  td{{padding:7px 6px;border-bottom:1px solid #f3f4f6}}
  .footer{{text-align:center;font-size:11px;color:#999;margin-top:16px}}
</style></head><body>
<div class="container">
  <h1>智能补货建议报告</h1>
  <div class="meta">生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} | 分析 SKU 数: {total_skus}</div>
  <div class="kpi-grid">
    <div class="kpi"><div class="label">立即补货</div><div class="value" style="color:#dc2626">{len(urgent)}</div><div class="label" style="color:#dc2626">≤3天覆盖</div></div>
    <div class="kpi"><div class="label">本周补货</div><div class="value" style="color:#d97706">{len(weekly)}</div><div class="label" style="color:#d97706">4-7天覆盖</div></div>
    <div class="kpi"><div class="label">暂缓补货</div><div class="value" style="color:#059669">{len(hold)}</div><div class="label" style="color:#059669">>7天覆盖</div></div>
    <div class="kpi"><div class="label">建议补货总量</div><div class="value">{total_suggest}</div><div class="label">件</div></div>
  </div>
  <div class="section">
    <h2 style="font-size:14px;margin-bottom:10px;">补货明细（按覆盖天数升序）</h2>
    <table>
      <thead><tr><th>SKU</th><th>名称</th><th>品类</th><th>仓库</th><th>日均销量</th><th>库存</th><th>在途</th><th>可用</th><th>覆盖天数</th><th>周转天数</th><th>建议补货量</th><th>紧急程度</th><th>供应商</th></tr></thead>
      <tbody>{rows_html}</tbody>
    </table>
  </div>
  <div class="footer">智能补货建议报告 · 演示数据集 · github.com/46bzvs7m64-gif/replenishment-advisor</div>
</div></body></html>"""

    with open(output_html, "w", encoding="utf-8") as f:
        f.write(h)
    print(f"HTML 报告: {output_html}")

# ========== 5. 主流程 ==========
def main():
    csv_path = "sales_data.csv"
    if not os.path.exists(csv_path):
        gen_demo_csv(csv_path)
    else:
        print(f"使用已有数据: {csv_path}")

    results = []
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            results.append(calc_replenishment(row))

    generate_report(results)

    # 汇总
    urgent = [r for r in results if "立即" in r["urgency"]]
    print(f"\n汇总: 共 {len(results)} 个 SKU")
    print(f"  立即补货: {len(urgent)} 个")
    print(f"  本周补货: {len([r for r in results if '本周' in r['urgency']])} 个")
    print(f"  暂缓补货: {len([r for r in results if '暂缓' in r['urgency']])} 个")
    print(f"  建议补货总量: {sum(r['suggest_qty'] for r in results)} 件")
    print("\n示例（覆盖天数最短的5个）:")
    for r in sorted(results, key=lambda x: x["cover_days"])[:5]:
        print(f"  {r['sku']} {r['name']} | 覆盖{r['cover_days']}天 | 建议{r['suggest_qty']}件 | {r['urgency']}")

if __name__ == "__main__":
    main()
