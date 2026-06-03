"""
SQLite → JavaScript 数据导出
=============================
将精算查找表导出为紧凑 JSON 格式的 JS 文件，
供纯静态前端直接加载（无需后端数据库）。

用法: python export_data.py
输出: static/actuarial_data.js (~6.5MB raw, ~1.5MB gzipped)
"""

import sqlite3, json, os

DB = os.path.join(os.path.dirname(__file__), "actuarial.db")
OUT = os.path.join(os.path.dirname(__file__), "..", "static", "actuarial_data.js")

# 需要导出的表及其值列名
TABLES = {
    "sa_ratio":  "sa_per_premium",
    "cv":        "cv",
    "db":        "ACC_DB",
    "rv":        "rv",
    "vnp":       "vnp",
    "rv_pvfb":   "rv_pvfb",
    "cv_pvfb":   "cv_pvfb",
    "bonus_db":  "ACC_DB",
}

def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    conn = sqlite3.connect(DB)
    result = {}

    for table, col in TABLES.items():
        d = {}
        cur = conn.execute(f"SELECT sex, PmtP, age, pass_yr, {col} FROM {table}")
        for row in cur:
            sex, pmtP, age, pass_yr, val = (
                int(row[0]), int(row[1]), int(row[2]), int(row[3]), row[4]
            )
            if val is not None:
                key = f"{sex}-{pmtP}-{age}-{pass_yr}"
                d[key] = round(float(val), 10)
        result[table] = d
        print(f"[{table}] {len(d)} entries")

    # 输出为 window.__LU 全局变量
    js = "window.__LU=" + json.dumps(result, separators=(',', ':')) + ";"
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write(js)

    size_kb = os.path.getsize(OUT) / 1024
    print(f"\nDone: {OUT} ({size_kb:.0f} KB)")

    # 前端查找用法提示
    print("""
前端用法:
  <script src="actuarial_data.js"></script>
  <script>
    function L(table, sex, PmtP, age, pass_yr) {
      return window.__LU[table][sex+'-'+PmtP+'-'+age+'-'+pass_yr] || 0;
    }
    // 示例: L('cv', 2, 5, 41, 1) → 0.0006524
  </script>
""")

if __name__ == "__main__":
    main()
