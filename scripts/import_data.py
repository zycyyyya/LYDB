"""
保险精算数据导入：Excel → SQLite
==============================
将分红型终身寿险利益演示 Excel 中的精算表提取到 SQLite 数据库。

用法：
  1. 修改 EXCEL_PATH 指向你的产品 Excel
  2. 修改 SHEETS_CONFIG 匹配你的 Sheet 名和列结构
     （用第 1 步的方法分析 Excel 结构）
  3. 修改 PRODUCT_IDS 为你的产品代码
  4. 运行: python import_data.py
"""

import sqlite3, pandas as pd, os, json

# === 配置区：根据你的 Excel 修改以下内容 ===

EXCEL_PATH = "你的产品利益演示.xlsx"  # ← 改为你的文件路径
DB_PATH = os.path.join(os.path.dirname(__file__), "actuarial.db")

# 产品代码过滤（Excel 中 prod_id 列的不同值）
PRODUCT_IDS = ["AZK", "AZL"]  # ← 改为你的产品代码

# 精算表配置：{表名: {sheet, cols, value_col}}
# cols 必须与 Excel 的实际列数完全匹配
SHEETS_CONFIG = {
    "cv":       {"sheet": "CV(009-01)",       "cols": ["index","prod_id","sex","PmtP","InsP","age","reserv_col","data_type","sick_yr","pass_yr","inc_ann_index","cv"], "value_col":"cv"},
    "db":       {"sheet": "011-基本",          "cols": ["index","prod_id","sex","PmtP","InsP","age","reserv_col","pass_yr","FACE_AMT","ACC_DB"],                        "value_col":"ACC_DB"},
    "bonus_db": {"sheet": "011-红利",          "cols": ["index","prod_id","sex","PmtP","InsP","age","reserv_col","pass_yr","FACE_AMT","ACC_DB"],                        "value_col":"ACC_DB"},
    "rv":       {"sheet": "RV(009-03)",        "cols": ["index","prod_id","sex","PmtP","InsP","age","reserv_col","data_type","sick_yr","pass_yr","inc_ann_index","rv"], "value_col":"rv"},
    "vnp":      {"sheet": "VNP(008-05)",       "cols": ["index","prod_id","sex","PmtP","InsP","age","reserv_col","data_type","pass_yr","vnp"],                          "value_col":"vnp"},
    "rv_pvfb":  {"sheet": "RV_PVFB因子（新）",  "cols": ["index","prod_id","sex","PmtP","InsP","age","pass_yr","reserv_col","rv_pvfb"],                                  "value_col":"rv_pvfb"},
    "cv_pvfb":  {"sheet": "CV_PVFB因子（新)",  "cols": ["index","prod_id","sex","PmtP","InsP","age","pass_yr","reserv_col","cv_pvfb","dummy1","dummy2"],                 "value_col":"cv_pvfb"},
    "sa_ratio": {"sheet": "093",               "cols": ["index","prod_id","sex","PmtP","InsP","age","reserv_col","data_type","pass_yr","sa_per_premium","dummy"],       "value_col":"sa_per_premium"},
}

# ============== 核心逻辑（通常不需要修改） ==============

def main():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    
    for table, cfg in SHEETS_CONFIG.items():
        sheet_name, target_cols = cfg["sheet"], cfg["cols"]
        print(f"[{table}] Reading {sheet_name}...")
        
        df = pd.read_excel(EXCEL_PATH, sheet_name=sheet_name, header=None)
        df = df.iloc[1:]                         # 跳过标题行
        df = df.iloc[:, :len(target_cols)]       # 截取需要的列
        df.columns = target_cols
        
        # 过滤产品
        df = df[df["prod_id"].isin(PRODUCT_IDS)].copy()
        
        # 数值化
        for c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        
        df.to_sql(table, conn, if_exists="replace", index=False)
        
        # 建立复合索引加速查找
        idx_cols = [c for c in ["sex","PmtP","age","pass_yr"] if c in df.columns]
        if idx_cols:
            conn.execute(f"CREATE INDEX idx_{table} ON {table}({','.join(idx_cols)})")
        
        print(f"  → {len(df)} rows")

    # 导入 GP 参数表（可选）
    try:
        gp = pd.read_excel(EXCEL_PATH, sheet_name="GP", header=None)
        conn.execute("CREATE TABLE IF NOT EXISTS params (key TEXT PRIMARY KEY, value TEXT)")
        for i in range(len(gp)):
            key = gp.iloc[i, 0]
            if pd.notna(key) and key not in (None, ""):
                vals = [gp.iloc[i,j] for j in range(1,len(gp.columns)) if pd.notna(gp.iloc[i,j])]
                conn.execute("INSERT OR REPLACE INTO params VALUES(?,?)", (str(key), json.dumps(vals)))
    except Exception:
        pass  # GP sheet optional
    
    conn.commit()
    conn.close()
    print(f"\nDone: {DB_PATH} ({os.path.getsize(DB_PATH)/1024/1024:.1f} MB)")

if __name__ == "__main__":
    main()
