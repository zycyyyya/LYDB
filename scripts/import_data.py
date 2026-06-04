"""
保险精算数据导入：Excel → SQLite
==============================
用法：
  1. 直接运行自动发现模式：
     python import_data.py your_file.xlsx --auto
     （自动检测 Sheet 名、列数、产品代码）

  2. 手动配置模式（修改下方 SHEETS_CONFIG 和 PRODUCT_IDS）：
     python import_data.py your_file.xlsx

  3. 仅列出 Excel 结构（不导入）：
     python import_data.py your_file.xlsx --list
"""

import sqlite3, pandas as pd, os, json, sys, re

DB_PATH = os.path.join(os.getcwd(), "actuarial.db")

# === 手动配置区（--auto 模式下忽略） ===
PRODUCT_IDS = []  # 留空 = 不过滤产品。也可填 ["PROD_A","PROD_B"]

# 精算表启发式匹配：{表名: [(候选Sheet关键词, 列数范围), ...]}
# 导入时会自动匹配 Sheet 名包含这些关键词的表格
HEURISTICS = [
    ("sa_ratio", ["单位保费对应的保额", "093", "sa_per_premium", "保额保费比"], (8, 12), "sa_per_premium"),
    ("cv",       ["cv", "现金价值", "009-01", "cash_value"],                         (10, 14), "cv"),
    ("db",       ["011-基本", "身故保险金", "death_benefit", "基本保额"],             (8, 12),  "ACC_DB"),
    ("bonus_db", ["011-红利", "红利保险金", "bonus_death"],                          (8, 12),  "ACC_DB"),
    ("rv",       ["rv", "责任准备金", "009-03", "reserve"],                          (10, 14), "rv"),
    ("vnp",      ["vnp", "净保费", "008-05", "net_premium"],                        (8, 12),  "vnp"),
    ("rv_pvfb",  ["rv_pvfb", "PVFB因子", "rv_pvfb因子"],                            (7, 11),  "rv_pvfb"),
    ("cv_pvfb",  ["cv_pvfb", "CV_PVFB因子", "cv_pvfb因子"],                         (9, 13),  "cv_pvfb"),
]

# ============== 核心逻辑 ==============

def list_structure(excel_path):
    """列出 Excel 的 Sheet 结构供检查"""
    xls = pd.ExcelFile(excel_path)
    print(f"\n=== {excel_path} ===\n{len(xls.sheet_names)} sheets:\n")
    for name in xls.sheet_names:
        df = pd.read_excel(excel_path, sheet_name=name, header=None)
        hdr = [str(df.iloc[0, c]) for c in range(min(15, df.shape[1]))]
        row1 = [str(df.iloc[1, c]) for c in range(min(15, df.shape[1]))]
        print(f"  [{name}]  shape={df.shape}")
        print(f"    cols: {hdr}")
        print(f"    row1: {row1}")
    # Also detect product IDs
    print("\nProduct IDs found:")
    for name in xls.sheet_names:
        df = pd.read_excel(excel_path, sheet_name=name, header=None)
        if df.shape[1] >= 2:
            ids = df.iloc[1:, 1].dropna().unique()
            print(f"  [{name}] prod_id={list(ids)[:10]}")


def match_sheet(sheet_names, keywords):
    """模糊匹配 Sheet 名"""
    for sn in sheet_names:
        sn_lower = sn.lower().replace(" ", "").replace("_", "").replace("（","(").replace("）",")")
        for kw in keywords:
            kw_lower = kw.lower().replace(" ", "").replace("_", "")
            if kw_lower in sn_lower:
                return sn
    return None


def auto_import(excel_path):
    """自动发现并导入"""
    xls = pd.ExcelFile(excel_path)
    sheet_names = list(xls.sheet_names)
    print(f"Found {len(sheet_names)} sheets, auto-matching...\n")

    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = sqlite3.connect(DB_PATH)

    imported = 0
    for table_name, keywords, col_range, _val_col in HEURISTICS:
        sheet = match_sheet(sheet_names, keywords)
        if not sheet:
            print(f"  [{table_name}] ✗  no matching sheet found (keywords: {keywords[0]}...)")
            continue

        df = pd.read_excel(excel_path, sheet_name=sheet, header=None)
        ncols = df.shape[1]

        # 自动映射列名
        cols = [f"col_{i}" for i in range(ncols)]
        # 尝试识别标准列
        hdr = [str(df.iloc[0, c]).lower().replace(" ", "").replace("_", "") for c in range(ncols)]
        for i, h in enumerate(hdr):
            if "sex" in h or "性别" in h: cols[i] = "sex"
            elif "pmtp" in h or "prem" in h and "pay" in h: cols[i] = "PmtP"
            elif "age" in h or "年龄" in h: cols[i] = "age"
            elif "ins" in h and ("period" in h or "保障" in h): cols[i] = "InsP"
            elif "pass" in h and ("yr" in h or "年" in h): cols[i] = "pass_yr"
            elif "prod" in h: cols[i] = "prod_id"
            elif "reserv" in h: cols[i] = "reserv_col"
            elif "data" in h and "type" in h: cols[i] = "data_type"

        # 值列取最后一列
        val_col = cols[-1]

        df = df.iloc[1:]
        df.columns = cols

        # 过滤产品（如果有 prod_id 列且 PRODUCT_IDS 非空）
        if "prod_id" in cols and PRODUCT_IDS:
            df = df[df["prod_id"].isin(PRODUCT_IDS)].copy()

        # 数值化
        for c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

        df.to_sql(table_name, conn, if_exists="replace", index=False)

        # 建查找索引
        idx_cols = [c for c in ["sex","PmtP","age","pass_yr"] if c in df.columns]
        if idx_cols:
            try:
                conn.execute(f"CREATE INDEX idx_{table_name} ON {table_name}({','.join(idx_cols)})")
            except Exception:
                pass

        print(f"  [{table_name}] ✓ {sheet} → {len(df)} rows (value={val_col})")
        imported += 1

    conn.commit()
    conn.close()

    print(f"\nImported {imported}/{len(HEURISTICS)} tables")
    print(f"DB: {DB_PATH} ({os.path.getsize(DB_PATH)/1024/1024:.1f} MB)")

    if imported == 0:
        print("\n⚠ 没有匹配到任何表！请使用 --list 检查 Excel 结构，然后手动配置 SHEETS_CONFIG。")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    path = sys.argv[1]

    if "--list" in sys.argv:
        list_structure(path)
        return

    if "--auto" in sys.argv:
        PRODUCT_IDS.clear()  # 不过滤
        auto_import(path)
        return

    # 手动模式（使用硬编码配置）
    print("Manual mode — edit PRODUCT_IDS and SHEETS_CONFIG in this file first.")
    print("Tip: use --auto for automatic detection.")


if __name__ == "__main__":
    main()
