"""批量导出所有产品精算数据为JS查找表"""
import sqlite3, json, os

OUT_DIR = os.path.join(os.getcwd(), "dist", "data")
os.makedirs(OUT_DIR, exist_ok=True)

DB_CONFIGS = [
    {
        "name": "taiyingjia",
        "label": "陆家嘴国泰泰赢家2.0",
        "db": "actuarial.db",
        "tables": {
            "sa_ratio": ("sa_per_premium", "SELECT sex,PmtP,age,pass_yr,sa_per_premium FROM sa_ratio"),
            "cv":        ("cv",        "SELECT sex,PmtP,age,pass_yr,cv FROM cv"),
            "db":        ("ACC_DB",    "SELECT sex,PmtP,age,pass_yr,ACC_DB FROM db"),
            "rv":        ("rv",        "SELECT sex,PmtP,age,pass_yr,rv FROM rv"),
            "vnp":       ("vnp",       "SELECT sex,PmtP,age,pass_yr,vnp FROM vnp"),
            "rv_pvfb":   ("rv_pvfb",   "SELECT sex,PmtP,age,pass_yr,rv_pvfb FROM rv_pvfb"),
            "cv_pvfb":   ("cv_pvfb",   "SELECT sex,PmtP,age,pass_yr,cv_pvfb FROM cv_pvfb"),
            "bonus_db":  ("ACC_DB",    "SELECT sex,PmtP,age,pass_yr,ACC_DB FROM bonus_db"),
        },
        "meta": {"sa_growth": 0.02, "dividend_ratio": 0.70, "ad_r_l": 0.0175, "ad_r_m": 0.039,
                 "products": [{"name":"陆家嘴国泰泰赢家2.0", "pay_terms":[1,3,5,10], "ages":[0,70]}],
                 "calc_type": "taiyingjia"}
    },
    {
        "name": "zhongyi_zhenxiang",
        "label": "中意一生中意（甄享版）",
        "db": "zhongyi.db",
        "tables": {
            "premium_cv": ("cv_per_unit", "SELECT code,year,cv_per_unit,gp FROM premium_cv WHERE code LIKE 'BJ%'"),
            "rpu":        ("rpu_per_unit", "SELECT code,year,rpu_per_unit FROM rpu WHERE code LIKE 'BJ%'"),
            "bonus":      ("bonus_sa",   "SELECT pay_term,age,sex,pass_yr,product,bonus_sa,bonus_cv FROM bonus WHERE product='甄享版'"),
        },
        "meta": {"sa_growth": 0.0175, "dividend_ratio": 1.0, "ad_r_l": 0, "ad_r_m": 0,
                 "products": [{"name":"甄享版","code_prefix":"BJ","pay_terms":[1,3,5,6,10],"ages":[0,69]}],
                 "calc_type": "zhongyi"}
    },
    {
        "name": "zhongyi_fuxiang",
        "label": "中意一生中意（福享版）",
        "db": "zhongyi.db",
        "tables": {
            "premium_cv": ("cv_per_unit", "SELECT code,year,cv_per_unit,gp FROM premium_cv WHERE code LIKE 'AT%'"),
            "rpu":        ("rpu_per_unit", "SELECT code,year,rpu_per_unit FROM rpu WHERE code LIKE 'AT%'"),
            "bonus":      ("bonus_sa",   "SELECT pay_term,age,sex,pass_yr,product,bonus_sa,bonus_cv FROM bonus WHERE product='福享版'"),
        },
        "meta": {"sa_growth": 0.0175, "dividend_ratio": 1.0, "ad_r_l": 0, "ad_r_m": 0,
                 "products": [{"name":"福享版","code_prefix":"AT","pay_terms":[1,3,5,6,10],"ages":[0,69]}],
                 "calc_type": "zhongyi"}
    },
    {
        "name": "zhongyou",
        "label": "中邮悦享盈佳尊享版",
        "db": "zhongyou.db",
        "tables": {
            "factors": ("full", "SELECT sex,NP,age,Dt,SA,EndCV,Premres,Endres,DB,f,EndCV_jq,Endres_jq,DB_jq FROM factors"),
        },
        "meta": {"sa_growth": 0.02, "dividend_rate": 0.01575,
                 "products": [{"name":"悦享盈佳尊享版","pay_terms":[1,3,5,6,10],"ages":[0,66]}],
                 "calc_type": "zhongyou"}
    },
    {
        "name": "zhongying",
        "label": "中英人寿福满盈C款",
        "db": "zhongying.db",
        "tables": {
            "cv_base":     ("val", "SELECT sex,age,yr,val FROM cv_base"),
            "bonus_factor":("val", "SELECT sex,age,yr,val FROM bonus_factor"),
            "jq_prem":     ("val", "SELECT sex,age,yr,val FROM jq_prem"),
            "jq_bonus":    ("val", "SELECT sex,age,yr,val FROM jq_bonus"),
            "jq_cv":       ("val", "SELECT sex,age,yr,val FROM jq_cv"),
            "rate":        ("sa_per_1000", "SELECT NP,sex,age,sa_per_1000 FROM rate"),
        },
        "meta": {"sa_growth": 0.0175,
                 "products": [{"name":"福满盈C款","pay_terms":[1,3,5,6,10],"ages":[0,65]}],
                 "calc_type": "zhongying"}
    },
]

def export_db(config):
    db_path = os.path.join(os.getcwd(), config["db"])
    if not os.path.exists(db_path):
        print(f"  SKIP: {config['db']} not found")
        return

    conn = sqlite3.connect(db_path)
    data = {"meta": config["meta"]}

    for tbl, (val_col, sql) in config["tables"].items():
        d = {}
        cur = conn.execute(sql)
        n = 0
        for row in cur:
            if tbl == "factors":
                sex, NP, age, Dt = int(row[0]), int(row[1]), int(row[2]), int(row[3])
                vals = [round(float(v), 6) if v is not None else 0 for v in row[4:]]
                d[f"{sex}-{NP}-{age}-{Dt}"] = vals
            elif tbl == "bonus":
                pay_term, age, sex, pass_yr = int(row[0]), int(row[1]), int(row[2]), int(row[3])
                product, bonus_sa, bonus_cv = row[4], round(float(row[5]),6) if row[5] else 0, round(float(row[6]),6) if row[6] else 0
                d[f"{product}|{pay_term}-{sex}-{age}-{pass_yr}"] = [bonus_sa, bonus_cv]
            elif tbl == "premium_cv":
                code, year = row[0], int(row[1])
                d[f"{code}-{year}"] = [round(float(row[2]),6), round(float(row[3]),6)]
            elif tbl == "rpu":
                code, year = row[0], int(row[1])
                d[f"{code}-{year}"] = round(float(row[2]),6)
            elif tbl == "rate":
                NP, sex, age = int(row[0]), int(row[1]), int(row[2])
                d[f"{NP}-{sex}-{age}"] = round(float(row[3]),6)
            else:
                keys = [str(int(r)) if isinstance(r, float) else str(r) for r in row[:-1]]
                d["-".join(keys)] = round(float(row[-1]), 6)
            n += 1
        data[tbl] = d
        print(f"    {tbl}: {n} entries")

    conn.close()

    out_path = os.path.join(OUT_DIR, f"{config['name']}.js")
    js = f"window.__{config['name']}=" + json.dumps(data, separators=(',',':')) + ";"
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(js)
    size = os.path.getsize(out_path) / 1024
    print(f"  → {config['name']}.js ({size:.0f} KB)")

def main():
    for cfg in DB_CONFIGS:
        print(f"\n[{cfg['label']}]")
        export_db(cfg)
    print(f"\nDone: {OUT_DIR}")
    # Generate product catalog
    catalog = [{"name": c["name"], "label": c["label"], "meta": c["meta"]} for c in DB_CONFIGS]
    with open(os.path.join(OUT_DIR, "catalog.js"), 'w', encoding='utf-8') as f:
        f.write("window.__CATALOG=" + json.dumps(catalog, ensure_ascii=False, separators=(',',':')) + ";")

if __name__ == "__main__":
    main()
