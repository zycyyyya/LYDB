"""
中邮悦享盈佳（尊享版）终身寿险（分红型）数据导入 + 计算引擎
===========================================================
结构：单张因子表 (46K行×26列)，按 sex-NP-age-Dt 索引
包含：SA/CV/DB/红利计算基础/交清增额因子 全部预计算值
"""

import sqlite3, os, pandas as pd

DB_PATH = os.path.join(os.getcwd(), "zhongyou.db")
DIV_RATE = 0.01575   # 红利利差 1.575%
SA_GROWTH = 0.02       # 中邮保额年增长2%

def import_zhongyou(excel_path):
    conn = sqlite3.connect(DB_PATH)

    print("导入因子表...")
    df = pd.read_excel(excel_path, sheet_name='因子表', header=None)

    # 跳过前3行表头，第4行是数据开始
    # Col mapping (0-indexed):
    # A:key, B:sex, C:NP, D:Pt_flag, E:NB, F:Bt_flag, G:age, H:Dt
    # I:Prem, J:SA, K:PremCV, L:EndCV, M:Premres, N:Endres
    # O:SB, P:MB, Q:DB, R:f, S:SA_jq, T:PremCV_jq, U:EndCV_jq
    # V:Premres_jq, W:Endres_jq, X:SB_jq, Y:MB_jq, Z:DB_jq
    df = df.iloc[3:]  # skip 3 header rows
    df.columns = ['key','sex','NP','Pt_flag','NB','Bt_flag','age','Dt',
                  'Prem','SA','PremCV','EndCV','Premres','Endres',
                  'SB','MB','DB','f','SA_jq','PremCV_jq','EndCV_jq',
                  'Premres_jq','Endres_jq','SB_jq','MB_jq','DB_jq']

    for c in ['sex','NP','age','Dt','SA','EndCV','Premres','Endres','DB','f','EndCV_jq','Endres_jq','DB_jq']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df = df.dropna(subset=['sex','NP','age','Dt'])

    rows = []
    for _, r in df.iterrows():
        rows.append((
            int(r['sex']), int(r['NP']), int(r['age']), int(r['Dt']),
            float(r['SA']), float(r['EndCV']), float(r['Premres']), float(r['Endres']),
            float(r['DB']), float(r['f']), float(r['EndCV_jq']), float(r['Endres_jq']), float(r['DB_jq']),
        ))

    conn.execute("DROP TABLE IF EXISTS factors")
    conn.execute("""CREATE TABLE factors (
        sex INT, NP INT, age INT, Dt INT,
        SA REAL, EndCV REAL, Premres REAL, Endres REAL,
        DB REAL, f REAL, EndCV_jq REAL, Endres_jq REAL, DB_jq REAL
    )""")
    conn.executemany("INSERT INTO factors VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    conn.execute("CREATE INDEX idx_f ON factors(sex,NP,age,Dt)")
    conn.commit()
    print(f"  → {len(rows)} rows")

    # 导入缴费期映射
    try:
        df2 = pd.read_excel(excel_path, sheet_name='填写页面', header=None)
        pt_map = {}
        for r in range(4, 10):
            k, v = df2.iloc[r, 13], df2.iloc[r, 14]
            if pd.notna(k) and pd.notna(v):
                pt_map[str(k)] = int(v)
        conn.execute("CREATE TABLE IF NOT EXISTS pt_map (name TEXT, val INT)")
        for k, v in pt_map.items():
            conn.execute("INSERT OR REPLACE INTO pt_map VALUES(?,?)", (k, v))
        conn.commit()
    except:
        pass

    conn.close()
    print(f"Done: {DB_PATH}")


class ZhongyouCalculator:
    """中邮悦享盈佳计算器"""
    def __init__(self, db_path=DB_PATH):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)

    def _lookup(self, sex, NP, age, Dt):
        r = self.conn.execute(
            "SELECT SA,EndCV,Premres,Endres,DB,f,EndCV_jq,Endres_jq,DB_jq FROM factors WHERE sex=? AND NP=? AND age=? AND Dt=?",
            (sex, NP, age, Dt)
        ).fetchone()
        return dict(zip(['SA','EndCV','Premres','Endres','DB','f','EndCV_jq','Endres_jq','DB_jq'],
                        map(float, r))) if r else None

    def calc_benefit(self, entry_age, sex, pay_term, annual_premium, max_display=None):
        share = annual_premium / 1000

        f1 = self._lookup(sex, pay_term, entry_age, 1)
        if not f1: return None
        sa_basic_per_unit = f1['SA']
        sa_basic = round(sa_basic_per_unit * share, 0)

        if max_display is None:
            r = self.conn.execute("SELECT MAX(Dt) FROM factors WHERE sex=? AND NP=? AND age=?",
                                  (sex, pay_term, entry_age)).fetchone()
            max_display = int(r[0]) if r and r[0] else 105
        max_year = min(max_display, 105 - entry_age)

        rows = []
        cum_prem = 0.0
        cum_jq_sa_pu = 0.0    # 累计交清增额保额 per-unit
        prev_endres_pu = 0.0   # 上期 Endres per-unit
        prev_jq_endres_pu = 0.0 # 上期交清 reserve per-unit

        for t in range(1, max_year + 1):
            cur_age = entry_age + t
            prem = annual_premium if t <= pay_term else 0
            cum_prem += prem

            f = self._lookup(sex, pay_term, entry_age, t)
            if not f: break

            # === Per-unit calculations ===
            sa_pu = sa_basic_per_unit * (1 + SA_GROWTH) ** (t - 1)
            cv_pu = f['EndCV']
            db_pu = f['DB']

            # 主合同红利 per-unit
            diva_pu = DIV_RATE * (f['Premres'] + prev_endres_pu)
            prev_endres_pu = f['Endres']

            # 交清增额红利 per-unit
            divb_pu = DIV_RATE * prev_jq_endres_pu

            # 合计红利 per-unit → 交清增额保额
            total_div_pu = diva_pu + divb_pu
            annual_jq_sa_pu = total_div_pu / f['f'] if f['f'] > 0 else 0
            cum_jq_sa_pu += annual_jq_sa_pu

            # 下期交清 reserve per-unit
            prev_jq_endres_pu = cum_jq_sa_pu / 1000 * f['Endres_jq']

            # === Total (× share) ===
            sa_current = round(sa_pu * share, 0)
            guaranteed_cv = round(cv_pu * share, 0)
            guaranteed_db = round(db_pu * share, 0)
            annual_div = round(total_div_pu * share, 0)
            cum_jq_sa = round(cum_jq_sa_pu * share, 0)
            bonus_cv = round(cum_jq_sa / 1000 * f['EndCV_jq'], 0)
            bonus_db = round(cum_jq_sa / 1000 * f['DB_jq'], 0)
            total_cv = round(guaranteed_cv + bonus_cv, 0)
            total_db = round(guaranteed_db + bonus_db, 0)

            rows.append(dict(
                year=t, age=cur_age,
                premium=prem, cum_premium=round(cum_prem,0),
                sa_basic=sa_basic, sa_current=sa_current,
                guaranteed_cv=guaranteed_cv, guaranteed_db=guaranteed_db,
                annual_div=annual_div, cum_jq_sa=cum_jq_sa,
                bonus_cv=bonus_cv, bonus_db=bonus_db,
                total_cv=total_cv, total_db=total_db,
            ))

        return dict(sa_basic=sa_basic, entry_age=entry_age, sex=sex,
                    pay_term=pay_term, annual_premium=annual_premium, rows=rows)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python zhongyou.py <excel_path>")
        sys.exit(1)
    import_zhongyou(sys.argv[1])
