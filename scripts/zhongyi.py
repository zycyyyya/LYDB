"""
中意一生中意 精算数据导入 + 计算引擎
====================================
适配产品：中意一生中意（甄享版）+（福享版）终身寿险（分红型）

结构：
- 保费现价：产品代码→年度→单位现金价值（宽表→透视）
- 红利：交费期+年龄+性别→年度→红利保额/红利保额现价
- RPU：产品代码→年度→红利单位现金价值（宽表→透视）

关键差异 vs 泰赢家：
- SA增长率: 1.75% (非2%)
- SA增长真实参与计算（非仅展示）
- CV = SA × perUnitCV / 10000
- 红利保额 = SA × bonus_per_unit / 10000
- 红利CV = cum_bonus_SA × perUnitRPU / 10000
"""

import sqlite3, os
import pandas as pd

DB_PATH = os.path.join(os.path.dirname(__file__), "zhongyi.db")
SA_GROWTH = 0.0175  # 中意 SA 年增长率

def import_zhongyi(excel_path, product_name=""):
    """
    导入中意产品精算数据

    参数:
        excel_path: Excel文件路径
        product_name: 产品名称标签
    """
    conn = sqlite3.connect(DB_PATH)

    # === 1. 保费现价表 ===
    print(f"[{product_name}] 导入保费现价...")
    df_cv = pd.read_excel(excel_path, sheet_name='保费现价', header=None)
    df_cv = df_cv.iloc[1:]  # 跳过标题行
    # 透视宽表为长表: (code, year, value)
    rows = []
    for _, row in df_cv.iterrows():
        code = str(row.iloc[0])
        gp = row.iloc[1]
        for yr in range(2, len(row)):
            if pd.notna(row.iloc[yr]):
                rows.append((code, product_name, yr-2, float(row.iloc[yr]), float(gp) if pd.notna(gp) else 0))
    conn.execute("CREATE TABLE IF NOT EXISTS premium_cv (code TEXT, product TEXT, year INTEGER, cv_per_unit REAL, gp REAL)")
    conn.execute("DELETE FROM premium_cv WHERE product=?", (product_name,))
    conn.executemany("INSERT INTO premium_cv VALUES(?,?,?,?,?)", rows)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pcv ON premium_cv(code, year)")
    print(f"  → {len(rows)} rows")

    # === 2. RPU 表 ===
    print(f"[{product_name}] 导入 RPU...")
    df_rpu = pd.read_excel(excel_path, sheet_name='RPU', header=None)
    df_rpu = df_rpu.iloc[1:]
    rows_rpu = []
    for _, row in df_rpu.iterrows():
        code = str(row.iloc[0])
        for yr in range(1, len(row)):
            if pd.notna(row.iloc[yr]):
                rows_rpu.append((code, product_name, yr-1, float(row.iloc[yr])))
    conn.execute("CREATE TABLE IF NOT EXISTS rpu (code TEXT, product TEXT, year INTEGER, rpu_per_unit REAL)")
    conn.execute("DELETE FROM rpu WHERE product=?", (product_name,))
    conn.executemany("INSERT INTO rpu VALUES(?,?,?,?)", rows_rpu)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rpu ON rpu(code, year)")
    print(f"  → {len(rows_rpu)} rows")

    # === 3. 红利表 ===
    print(f"[{product_name}] 导入红利...")
    df_bonus = pd.read_excel(excel_path, sheet_name='红利', header=None)
    bonus_cols = ['保险期间','交费期','年龄','性别','保单年度','代码','红利','红利_保证','红利_红利','红利保额','红利保额现价']
    df_bonus = df_bonus.iloc[1:]
    df_bonus.columns = bonus_cols
    # 关键：红利表每行都有交费期/年龄/性别/保单年度，代码列仅首行有值
    # 不需要过滤代码列为空的行 — 那才是大部分数据行
    for c in ['交费期','年龄','保单年度','红利保额','红利保额现价']:
        df_bonus[c] = pd.to_numeric(df_bonus[c], errors='coerce')
    # 只保留数值完整的行
    df_bonus = df_bonus.dropna(subset=['交费期','年龄','保单年度','红利保额'])
    # 性别编码
    df_bonus['sex'] = df_bonus['性别'].map({'男': 1, '女': 2})
    rows_b = []
    for _, row in df_bonus.iterrows():
        rows_b.append((
            int(row['交费期']), int(row['年龄']), int(row['sex']), int(row['保单年度']),
            product_name,
            float(row['红利保额']) if pd.notna(row['红利保额']) else 0,
            float(row['红利保额现价']) if pd.notna(row['红利保额现价']) else 0,
        ))
    conn.execute("CREATE TABLE IF NOT EXISTS bonus (pay_term INTEGER, age INTEGER, sex INTEGER, pass_yr INTEGER, product TEXT, bonus_sa REAL, bonus_cv REAL)")
    conn.execute("DELETE FROM bonus WHERE product=?", (product_name,))
    conn.executemany("INSERT INTO bonus VALUES(?,?,?,?,?,?,?)", rows_b)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bonus ON bonus(pay_term, age, sex, pass_yr)")
    print(f"  → {len(rows_b)} rows")

    conn.commit()
    conn.close()
    print(f"Done: {DB_PATH}")


class ZhongyiCalculator:
    """
    中意一生中意分红险计算器

    关键公式:
        SA      = SA_BASIC × (1.0175)^(year-1)
        CV_保证  = SA_BASIC × perUnitCV / 10000
        DB_保证  = max(SA_current, CV_保证, 已交保费×年龄系数)  [简化]
        红利保额  = SA_BASIC × bonus_per_unit / 10000
        红利CV   = cum_bonus_SA × perUnitRPU / 10000
        总有效SA = cum_bonus_SA_prev + SA_current
    """
    def __init__(self, db_path=DB_PATH):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)

    def lookup_cv(self, product_code, year):
        r = self.conn.execute(
            "SELECT cv_per_unit FROM premium_cv WHERE code=? AND year=? LIMIT 1",
            (product_code, year)
        ).fetchone()
        return float(r[0]) if r else 0.0

    def lookup_rpu(self, product_code, year):
        r = self.conn.execute(
            "SELECT rpu_per_unit FROM rpu WHERE code=? AND year=? LIMIT 1",
            (product_code, year)
        ).fetchone()
        return float(r[0]) if r else 0.0

    def lookup_bonus(self, pay_term, age, sex, pass_yr, product):
        r = self.conn.execute(
            "SELECT bonus_sa, bonus_cv FROM bonus WHERE pay_term=? AND age=? AND sex=? AND pass_yr=? AND product=? LIMIT 1",
            (pay_term, age, sex, pass_yr, product)
        ).fetchone()
        return (float(r[0]), float(r[1])) if r else (0.0, 0.0)

    def calc_benefit(self, entry_age, sex, pay_term, annual_premium, sa_basic,
                     product_code, product_name, max_display=None):
        """
        参数:
            entry_age:      投保年龄
            sex:            1=男, 2=女
            pay_term:       交费年期 (1/3/5/6/10)
            annual_premium: 年交保费
            sa_basic:       基本保额 (需手动输入或用GP反算)
            product_code:   产品代码 (如 BJ8125CF, AT7330CM)
            product_name:   产品名称标签 (甄享版/福享版)
            max_display:    演示年限 (None=自动)
        """
        if max_display is None:
            r = self.conn.execute(
                "SELECT MAX(year) FROM premium_cv WHERE code=? AND cv_per_unit>0",
                (product_code,)
            ).fetchone()
            max_display = int(r[0]) if r and r[0] else 105
        max_year = min(max_display, 105 - entry_age)

        rows = []
        cum_premium = 0.0
        cum_bonus_sa = 0.0  # 累积红利保额

        for t in range(1, max_year + 1):
            current_age = entry_age + t
            prem = annual_premium if t <= pay_term else 0
            cum_premium += prem

            # 有效保额（年增长 1.75%）
            sa_current = round(sa_basic * (1 + SA_GROWTH) ** (t - 1), 0)

            # 保证现金价值
            per_unit_cv = self.lookup_cv(product_code, t)
            guaranteed_cv = round(sa_basic * per_unit_cv / 10000, 0)

            # 保证身故金
            # 缴费期内 = max(1.6×累计保费, 现金价值)
            # 缴费期后 = max(1.6×总保费, SA, 现金价值)
            total_premium_all = annual_premium * pay_term
            if current_age <= 18:
                guaranteed_db = max(round(cum_premium), guaranteed_cv)
            elif t <= pay_term:
                guaranteed_db = max(round(cum_premium * 1.6), guaranteed_cv)
            else:
                guaranteed_db = max(round(total_premium_all * 1.6), sa_current, guaranteed_cv)

            # 红利
            bonus_sa_unit, bonus_cv_unit = self.lookup_bonus(pay_term, entry_age, sex, t, product_name)
            annual_bonus_sa = round(sa_basic * bonus_sa_unit / 10000, 0)
            cum_bonus_sa += annual_bonus_sa

            # 红利现金价值
            per_unit_rpu = self.lookup_rpu(product_code, t)
            bonus_cv = round(cum_bonus_sa * per_unit_rpu / 10000, 0)

            # 总有效保额 = 上年累积红利保额 + 当年保证有效保额
            # 但 formula says cum_bonus_prev + sa_current
            prev_cum_bonus = cum_bonus_sa - annual_bonus_sa
            total_sa = round(prev_cum_bonus + sa_current, 0)
            total_cv = round(guaranteed_cv + bonus_cv, 0)
            # 总身故金（简化）
            total_db = max(total_sa, total_cv)

            rows.append(dict(
                year=t, age=current_age,
                premium=prem, cum_premium=round(cum_premium, 0),
                sa_basic=sa_basic, sa_current=sa_current,
                guaranteed_cv=guaranteed_cv, guaranteed_db=guaranteed_db,
                annual_bonus_sa=annual_bonus_sa, cum_bonus_sa=round(cum_bonus_sa, 0),
                bonus_cv=bonus_cv,
                total_sa=total_sa, total_cv=total_cv, total_db=total_db,
            ))

        return dict(
            product=product_name, sa_basic=sa_basic,
            entry_age=entry_age, sex=sex, pay_term=pay_term,
            annual_premium=annual_premium, rows=rows,
        )


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python zhongyi.py <excel_path> [product_name]")
        sys.exit(1)

    path = sys.argv[1]
    name = sys.argv[2] if len(sys.argv) > 2 else os.path.basename(path).split('.')[0]
    import_zhongyi(path, name)
