"""
保险利益演示 Flask API
======================
提供 REST API 供前端调用。

启动: python app.py
访问: http://127.0.0.1:5000

前置: 先运行 import_data.py 生成 actuarial.db
"""

from flask import Flask, render_template, jsonify, request
from calculator import InsuranceCalculator

app = Flask(__name__)
calc = InsuranceCalculator()

@app.route("/")
def index():
    """主页面"""
    return render_template("index.html")

@app.route("/api/calculate", methods=["POST"])
def calculate():
    """
    利益计算 API

    POST JSON:
        age:     int   投保年龄 (0-70)
        sex:     int   1=男 2=女
        pmt_p:   int   交费年期 (1/3/5/10)
        premium: float 年交保费
        ad_r_m:  float 演示红利率 (默认 0.039)
        max_age: int   演示终止年龄 (默认 105)

    返回:
        {params: {sa_basic, ...}, rows: [...], irr_bonus: [...], irr_guaranteed: [...]}
    """
    data = request.get_json()
    result = calc.calc_benefit(
        entry_age=int(data.get("age", 41)),
        sex=int(data.get("sex", 2)),
        pmt_p=int(data.get("pmt_p", 5)),
        annual_premium=float(data.get("premium", 100000)),
        ad_r_m=float(data.get("ad_r_m", 0.039)),
        max_display=int(data.get("max_age", 105)),
    )
    irr_bonus = calc.get_irr_curve(result, use_bonus=True)
    irr_guaranteed = calc.get_irr_curve(result, use_bonus=False)
    return jsonify(dict(params=result, rows=result["rows"],
                        irr_bonus=irr_bonus, irr_guaranteed=irr_guaranteed))

if __name__ == "__main__":
    app.run(debug=True, port=5000)
