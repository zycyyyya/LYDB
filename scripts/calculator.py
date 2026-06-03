"""
保险产品利益演示计算引擎
========================
复刻 Excel 精算公式，支持现金价值、身故保险金、红利、IRR 计算。

适用产品：分红型终身寿险（如陆家嘴国泰泰赢家2.0）
可适配其他分红型产品，核心公式通用。

用法：
    from calculator import InsuranceCalculator
    calc = InsuranceCalculator("actuarial.db")
    result = calc.calc_benefit(age=41, sex=2, pmt_p=5, premium=100000)
"""

import sqlite3, os

DB_PATH = os.path.join(os.path.dirname(__file__), "actuarial.db")
SA_UNIT = 0.01          # 保额单位
SA_GROWTH = 0.02        # 保额年增长率（仅展示用）
DIVIDEND_RATIO = 0.70   # 红利分配比例

class InsuranceCalculator:
    """
    精算计算器

    参数:
        db_path: SQLite 数据库路径（由 import_data.py 生成）

    关键常量:
        SA_UNIT (0.01): 保额计算单位
        DIVIDEND_RATIO (0.70): 可分配盈余的 70% 用于分红
    """

    def __init__(self, db_path=DB_PATH):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row

    def lookup(self, table, col, sex, pmt_p, age, pass_yr):
        """
        精算因子查找

        参数:
            table: 表名 (cv/db/rv/vnp/rv_pvfb/cv_pvfb/bonus_db/sa_ratio)
            col:   列名
            sex:   1=男, 2=女
            pmt_p: 交费年期 (1/3/5/10)
            age:   投保年龄 (0-70)
            pass_yr: 经过年数

        返回:
            float 因子值，查不到返回 0
        """
        row = self.conn.execute(
            f"SELECT {col} FROM {table} WHERE sex=? AND PmtP=? AND age=? AND pass_yr=? LIMIT 1",
            (sex, pmt_p, age, pass_yr)
        ).fetchone()
        return float(row[col]) if row and row[col] is not None else 0.0

    def calc_benefit(self, entry_age, sex, pmt_p, annual_premium,
                     ad_r_l=0.0175, ad_r_m=0.039, max_display=105):
        """
        计算完整利益演示

        参数:
            entry_age:       投保年龄 (0-70)
            sex:             1=男, 2=女
            pmt_p:           交费年期 (1=趸交, 3, 5, 10)
            annual_premium:  年交保费（元）
            ad_r_l:          年度红利率-低档 (default 0.0175)
            ad_r_m:          年度红利率-中档 (default 0.039)
            max_display:     演示终止年龄 (default 105)

        返回:
            dict:
                sa_basic:      基本保额
                entry_age:     投保年龄
                sex:           性别
                pmt_p:         交费年期
                annual_premium: 年交保费
                rows: [         逐年利益数据
                    year:       保单年度
                    age:        被保险人年龄
                    premium:    当年度保费
                    cum_premium: 累计保费
                    sa_basic:   基本保额
                    sa_display: 展示保额（含2%增长）
                    guaranteed_cv:   保证现金价值
                    guaranteed_db:   保证身故保险金
                    annual_dividend: 当年度红利
                    bonus_face_inc:  当年度增加红利保额
                    cum_bonus_face:  累积红利保额
                    bonus_db:        红利对应的身故保险金
                    bonus_cv:        红利对应的现金价值
                    total_db:        总身故保险金（保证+红利）
                    total_cv:        总现金价值（保证+红利）
                ]

        核心公式说明:
            保证现金价值 = cv_factor × SA_BASIC / SA_UNIT
            保证身故金   = MAX(db_factor × SA_BASIC / SA_UNIT, 保证现金价值)
            年度红利     = ((prev_RV + VNP) × SA_BASIC / SA_UNIT
                          + cum_bonus × prev_RV_PVFB / SA_UNIT)
                          × (演示利率 - 低档利率) × 70%
            ** 关键：所有计算使用初始 SA_BASIC（非每年2%递增值）**
        """
        # 保额保费比
        sa_ratio = self.lookup("sa_ratio", "sa_per_premium", sex, pmt_p, entry_age, 0)
        sa_basic = round(annual_premium * sa_ratio / 100, 1)

        max_year = max_display - entry_age
        rows = []
        cum_premium = 0.0
        cum_bonus_face = 0.0  # 累积红利保额

        for t in range(1, max_year + 1):
            current_age = entry_age + t
            prem = annual_premium if t <= pmt_p else 0
            cum_premium += prem
            sa_display = round(sa_basic * (1 + SA_GROWTH) ** (t - 1), 1)

            # ---- 精算因子查找 ----
            cv_factor = self.lookup("cv", "cv", sex, pmt_p, entry_age, t)
            db_factor = self.lookup("db", "ACC_DB", sex, pmt_p, entry_age, t)
            rv_factor = self.lookup("rv", "rv", sex, pmt_p, entry_age, t)
            vnp_factor = self.lookup("vnp", "vnp", sex, pmt_p, entry_age, t) if t <= pmt_p else 0.0
            rv_pvfb = self.lookup("rv_pvfb", "rv_pvfb", sex, pmt_p, entry_age, t)
            cv_pvfb = self.lookup("cv_pvfb", "cv_pvfb", sex, pmt_p, entry_age, t)
            bonus_db_factor = self.lookup("bonus_db", "ACC_DB", sex, pmt_p, entry_age, t)

            prev_rv = self.lookup("rv", "rv", sex, pmt_p, entry_age, max(t - 1, 0))
            prev_rv_pvfb = self.lookup("rv_pvfb", "rv_pvfb", sex, pmt_p, entry_age, max(t - 1, 0))

            # ---- 保证利益（使用初始 SA_BASIC） ----
            guaranteed_cv = round(cv_factor * sa_basic / SA_UNIT, 1)
            guaranteed_db = max(round(db_factor * sa_basic / SA_UNIT, 1), guaranteed_cv)

            # ---- 红利计算（中档） ----
            vnp_term = 0.0 if pmt_p == 1 else vnp_factor
            annual_dividend = round(
                ((prev_rv + vnp_term) * sa_basic / SA_UNIT +
                 cum_bonus_face * prev_rv_pvfb / SA_UNIT) *
                (ad_r_m - ad_r_l) * DIVIDEND_RATIO, 1
            )

            bonus_face_inc = 0.0
            if rv_pvfb > 0:
                bonus_face_inc = round(annual_dividend / rv_pvfb * SA_UNIT, 1)
            cum_bonus_face += bonus_face_inc

            bonus_cv = round(cum_bonus_face * cv_pvfb / SA_UNIT, 1)
            bonus_db = max(round(bonus_db_factor * cum_bonus_face / SA_UNIT, 1), bonus_cv)

            total_db = guaranteed_db + bonus_db
            total_cv = guaranteed_cv + bonus_cv

            rows.append(dict(
                year=t, age=current_age,
                premium=prem, cum_premium=round(cum_premium, 0),
                sa_basic=sa_basic, sa_display=sa_display,
                guaranteed_cv=guaranteed_cv, guaranteed_db=guaranteed_db,
                annual_dividend=annual_dividend, bonus_face_inc=bonus_face_inc,
                cum_bonus_face=round(cum_bonus_face, 1),
                bonus_db=bonus_db, bonus_cv=bonus_cv,
                total_db=total_db, total_cv=total_cv,
            ))

        return dict(
            sa_basic=sa_basic, entry_age=entry_age, sex=sex,
            pmt_p=pmt_p, annual_premium=annual_premium, rows=rows,
        )

    def calc_irr(self, cashflows):
        """
        稳健 IRR 计算（二分法定位 + Newton 精调）

        参数:
            cashflows: [CF0, CF1, CF2, ...]  现金流序列（支出为负，收入为正）

        返回:
            float | None  年化收益率，无法收敛返回 None
        """
        if not cashflows or len(cashflows) < 2:
            return None

        # 二分法定位零点
        lo, hi = -0.999, 2.0
        flo = sum(cf / (1 + lo) ** i for i, cf in enumerate(cashflows))
        fhi = sum(cf / (1 + hi) ** i for i, cf in enumerate(cashflows))
        if flo * fhi > 0:
            return None  # 同号，无零点

        for _ in range(60):
            mid = (lo + hi) / 2
            fmid = sum(cf / (1 + mid) ** i for i, cf in enumerate(cashflows))
            if abs(fmid) < 1e-6:
                lo = hi = mid; break
            if flo * fmid < 0:
                hi = mid
            else:
                lo = mid
            if hi - lo < 1e-10:
                break

        rate = (lo + hi) / 2

        # Newton 精调
        for _ in range(30):
            npv, dnpv = 0.0, 0.0
            for i, cf in enumerate(cashflows):
                d = (1 + rate) ** i
                npv += cf / d
                dnpv += -i * cf / (1 + rate) ** (i + 1)
            if abs(dnpv) < 1e-15:
                break
            new_rate = rate - npv / dnpv
            if abs(new_rate - rate) < 1e-10:
                rate = new_rate; break
            rate = new_rate

        return rate if -0.95 < rate < 1.5 else None

    def get_irr_curve(self, result, use_bonus=True):
        """
        逐年 IRR 曲线

        参数:
            result:     calc_benefit() 的返回值
            use_bonus:  True=含红利, False=仅保证

        返回:
            [{year, age, irr}, ...]  irr 为百分比（如 3.14），无法计算则为 None
        """
        rows = result["rows"]
        irr_data = []
        for i, row in enumerate(rows):
            years = i + 1
            if years < 2:
                irr_data.append(dict(year=row["year"], age=row["age"], irr=None))
                continue
            val = row["total_cv"] if use_bonus else row["guaranteed_cv"]
            cfs = ([-result["annual_premium"]] * min(years, result["pmt_p"])
                   + [0] * max(0, years - result["pmt_p"]))
            cfs[-1] += val
            irr = self.calc_irr(cfs)
            irr_data.append(dict(
                year=row["year"], age=row["age"],
                irr=round(irr * 100, 4) if irr is not None else None
            ))
        return irr_data
