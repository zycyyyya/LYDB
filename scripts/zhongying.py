"""
中英人寿福满盈C款（分红型）数据导入 + 计算引擎
=============================================
结构：5张宽表 (598行×110列)，行键=term+pre+sex+age，列=保单年度
"""

import sqlite3, os, pandas as pd

DB_PATH = os.path.join(os.path.dirname(__file__), "zhongying.db")
SA_GROWTH = 0.0175  # 中英保额年增长1.75%

def import_zhongying(excel_path):
    conn = sqlite3.connect(DB_PATH)

    tables = {
        'cv_base':     '现金价值表-基本保险金额',
        'bonus_factor': '红利-红利利益-基本保险金额',
        'jq_prem':     '交清增额保险—一次性交清保险费',
        'jq_bonus':    '交清增额保险—红利因子',
        'jq_cv':       '交清增额保险-现金价值表',
    }

    for tbl_key, sheet_name in tables.items():
        print(f"导入 {sheet_name}...")
        df = pd.read_excel(excel_path, sheet_name=sheet_name, header=None)
        # Skip 5 header rows, data starts at row 5 (0-indexed row 5)
        # Col A: key, B: term, C: pre, D: sex, E: age, F+: policy years
        df = df.iloc[5:]
        rows = []
        for _, row in df.iterrows():
            term = str(row.iloc[1]) if pd.notna(row.iloc[1]) else ''
            pre = str(row.iloc[2]) if pd.notna(row.iloc[2]) else ''
            sex_str = str(row.iloc[3]) if pd.notna(row.iloc[3]) else ''
            sex = 1 if '男' in sex_str else 2
            age_val = row.iloc[4]
            if not pd.notna(age_val): continue
            age = int(float(age_val))
            # Policy years from col 5+
            for yr_offset in range(5, len(row)):
                val = row.iloc[yr_offset]
                if pd.notna(val):
                    policy_yr = yr_offset - 4  # col5 = year 1
                    rows.append((term, pre, sex, age, policy_yr, float(val)))

        conn.execute(f"DROP TABLE IF EXISTS {tbl_key}")
        conn.execute(f"CREATE TABLE {tbl_key} (term TEXT, pre TEXT, sex INT, age INT, yr INT, val REAL)")
        conn.executemany(f"INSERT INTO {tbl_key} VALUES(?,?,?,?,?,?)", rows)
        conn.execute(f"CREATE INDEX idx_{tbl_key} ON {tbl_key}(sex,age,yr)")
        print(f"  → {len(rows)} rows")

    # 费率表
    print("导入费率表...")
    df_rate = pd.read_excel(excel_path, sheet_name='费率表', header=None)
    df_rate = df_rate.iloc[8:]  # skip 8 header rows
    # 列: A=age, B=趸交男, C=趸交女, D=3年男, E=3年女, F=5年男, G=5年女, H=6年男, I=6年女, J=10年男, K=10年女
    col_map = {1:(1,1),2:(1,2),3:(3,1),4:(3,2),5:(5,1),6:(5,2),7:(6,1),8:(6,2),9:(10,1),10:(10,2)}
    rate_rows = []
    for _, row in df_rate.iterrows():
        age = int(float(row.iloc[0])) if pd.notna(row.iloc[0]) else None
        if age is None: continue
        for col_idx, (np_val, sex_val) in col_map.items():
            if pd.notna(row.iloc[col_idx]):
                rate_rows.append((np_val, sex_val, age, float(row.iloc[col_idx])))
    conn.execute("DROP TABLE IF EXISTS rate")
    conn.execute("CREATE TABLE rate (NP INT, sex INT, age INT, sa_per_1000 REAL)")
    conn.executemany("INSERT INTO rate VALUES(?,?,?,?)", rate_rows)
    conn.execute("CREATE INDEX idx_rate ON rate(NP,sex,age)")
    print(f"  → {len(rate_rows)} rows")

    conn.commit()
    conn.close()
    print(f"Done: {DB_PATH}")


class ZhongyingCalculator:
    """中英福满盈C款计算器"""
    def __init__(self, db_path=DB_PATH):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)

    def _lookup(self, table, sex, age, yr):
        r = self.conn.execute(f"SELECT val FROM {table} WHERE sex=? AND age=? AND yr=? LIMIT 1",
                              (sex, age, yr)).fetchone()
        return float(r[0]) if r else 0.0

    def _lookup_rate(self, NP, sex, age):
        r = self.conn.execute("SELECT sa_per_1000 FROM rate WHERE NP=? AND sex=? AND age=?",
                              (NP, sex, age)).fetchone()
        return float(r[0]) if r else 0.0

    def calc_benefit(self, entry_age, sex, pay_term, annual_premium, max_display=None):
        # SA per 1000 premium
        sa_per_1000 = self._lookup_rate(pay_term, sex, entry_age)
        if sa_per_1000 <= 0: return None
        share = annual_premium / 1000
        sa_basic = round(sa_per_1000 * share, 0)

        if max_display is None:
            r = self.conn.execute("SELECT MAX(yr) FROM cv_base WHERE sex=? AND age=?",
                                  (sex, entry_age)).fetchone()
            max_display = int(r[0]) if r and r[0] else 105
        max_year = min(max_display, 105 - entry_age)

        rows = []
        cum_prem = 0.0
        cum_jq_sa = 0.0    # 累计交清增额保额
        prev_jq_bonus_base = 0.0  # 上期交清红利计算基础

        for t in range(1, max_year + 1):
            cur_age = entry_age + t
            prem = annual_premium if t <= pay_term else 0
            cum_prem += prem

            # 查基本保额对应因子
            cv_pu = self._lookup('cv_base', sex, entry_age, t)  # 每千元保费
            bonus_pu = self._lookup('bonus_factor', sex, entry_age, t)  # 每千元保额
            jq_prem_pu = self._lookup('jq_prem', sex, entry_age, t)  # 每千元交清增额
            jq_bonus_pu = self._lookup('jq_bonus', sex, entry_age, t)  # 每千元交清增额
            jq_cv_pu = self._lookup('jq_cv', sex, entry_age, t)  # 每千元交清增额

            # 保证利益
            sa_current = round(sa_basic * (1 + SA_GROWTH) ** (t - 1), 0)
            guaranteed_cv = round(cv_pu * share, 0)
            # DB: simplified — Excel has complex age-dependent logic
            guaranteed_db = max(sa_current, guaranteed_cv)

            # 红利: 基本保额红利 + 交清增额红利
            div_base = bonus_pu * sa_basic / 1000  # 基本保额对应的当年度红利
            div_jq = jq_bonus_pu * cum_jq_sa / 1000  # 交清增额对应的当年度红利
            total_div = round(div_base + div_jq, 0)

            # 交清增额保额 = 红利 / 一次性交清保险费 * 1000
            annual_jq_sa = round(total_div / jq_prem_pu * 1000, 0) if jq_prem_pu > 0 else 0
            cum_jq_sa += annual_jq_sa

            # 交清增额现价和身故金
            bonus_cv = round(cum_jq_sa / 1000 * jq_cv_pu, 0)
            # 交清增额有效保额（年增长1.75%）
            jq_effective_sa = round(cum_jq_sa * (1 + SA_GROWTH) ** (t - 1), 0)
            bonus_db = max(jq_effective_sa, bonus_cv)

            total_cv = round(guaranteed_cv + bonus_cv, 0)
            total_db = round(guaranteed_db + bonus_db, 0)

            rows.append(dict(
                year=t, age=cur_age,
                premium=prem, cum_premium=round(cum_prem,0),
                sa_basic=sa_basic, sa_current=sa_current,
                guaranteed_cv=guaranteed_cv, guaranteed_db=guaranteed_db,
                annual_div=total_div, cum_jq_sa=round(cum_jq_sa,0),
                bonus_cv=bonus_cv, bonus_db=bonus_db,
                total_cv=total_cv, total_db=total_db,
            ))

        return dict(sa_basic=sa_basic, entry_age=entry_age, sex=sex,
                    pay_term=pay_term, annual_premium=annual_premium, rows=rows)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python zhongying.py <excel_path>")
        sys.exit(1)
    import_zhongying(sys.argv[1])
