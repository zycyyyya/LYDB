# LYDB — 保险产品利益演示工具构建指南

> 将保险公司精算 Excel 转化为可在线对比的交互式网页工具，5 步全流程。

## 快速开始

```bash
# 1. 克隆仓库
git clone https://github.com/zycyyyya/LYDB.git
cd LYDB

# 2. 安装依赖（推荐虚拟环境）
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install pandas openpyxl flask

# 3. 将你的产品 Excel 放到项目根目录

# 4. 运行（所有脚本从项目根目录执行，数据库会创建在当前目录）
# 通用产品（泰赢家类）:
python scripts/import_data.py 你的产品.xlsx --auto
python scripts/app.py
# 中意系列:
python scripts/zhongyi.py 你的产品.xlsx 甄享版
# 中邮:
python scripts/zhongyou.py 你的产品.xlsx
# 中英:
python scripts/zhongying.py 你的产品.xlsx
```

## 适用场景

- 你有一份分红型/万能型终身寿险的**精算利益演示 Excel**（含 CV、DB、红利等精算表）
- 你想把它变成网页工具：输入年龄/保费 → 自动算出每个年度的现金价值、身故金、红利、IRR
- 你想支持多产品横向对比、在线分享

## 前置条件

- Python 3.9+
- 目标 Excel 需包含以下精算表（Sheet 名称可能不同，但逻辑通用）：
  - **CV 表**：现金价值因子（按 sex/PmtP/age/pass_yr 索引）
  - **DB 表**：身故保险金因子
  - **RV 表**：责任准备金因子
  - **VNP 表**：净保费因子（仅交费期内）
  - **红利 DB 表**：红利对应的身故金因子
  - **PVFB 因子表**：RV_PVFB 和 CV_PVFB
  - **保额/保费比率表**：年交保费 → 基本保额的换算率

---

## 第 1 步：解析 Excel 精算数据结构

### 目标

搞清楚三件事：
1. 有哪些 Sheet，各自存什么数据（pandas 扫一遍）
2. 每张表的**索引键**是什么（sex/PmtP/age/pass_yr 等）
3. **计算公式**在哪个 Sheet，怎么引用精算表的（openpyxl 读公式）

### 操作

```python
# 1a. 列出所有 Sheet
import pandas as pd
xls = pd.ExcelFile("产品利益演示.xlsx")
for s in xls.sheet_names:
    print(s)

# 1b. 逐个 Sheet 看前 20 行，确认列结构
df = pd.read_excel("产品利益演示.xlsx", sheet_name="CV", header=None)
print(df.iloc[:20, :15])

# 1c. 用 openpyxl 读公式（关键！）
import openpyxl
wb = openpyxl.load_workbook("产品利益演示.xlsx", data_only=False)
ws = wb["计算表"]  # 或 "利益演示"
# 检查关键单元格的公式
for col in range(1, 15):
    cell = ws.cell(row=5, column=col)
    if cell.value:
        print(f"Col {col}: {cell.value}")
```

### 关键技巧

- **`data_only=False`** 才能读到公式文本，否则只看到计算结果
- 公式中的 `VLOOKUP(E5, 'CV(009-01)'!$A:$L, 12, FALSE)` 告诉你：
  - 查哪张表（CV(009-01)）
  - 返回第几列（12 = 最后一列，即 CV 值）
  - 索引键在 E 列（通常格式如 `"5S241A5"` = PmtP + S + Sex + Age + A + Duration）
- **注意 Excel 公式中的 SA_BASIC** —— 它通常是**初始基本保额**（命名范围），不是每年 2% 增长后的值

---

## 第 2 步：导入精算数据到 SQLite

### 目标

把所有精算表抽到 SQLite，建立统一索引，方便后续任何语言调用。

### 核心脚本

见 `scripts/import_data.py`，要点：

1. **列映射**：根据第 1 步分析结果，为每张表定义列名
2. **统一索引**：`(sex, PmtP, age, pass_yr)` 作为复合查找键
3. **建索引**：`CREATE INDEX` 加速后续百万级查找
4. **大小对比**：原始 Excel 41MB → SQLite ~14MB（之后可转 JS ~6.5MB gzipped~1.5MB）

### 运行

```bash
python scripts/import_data.py
# 输出：actuarial.db
```

---

## 第 3 步：构建计算引擎

### 目标

用代码**逐行复刻** Excel 的计算逻辑。

### 核心公式（以分红型终身寿险为例）

```python
SA_UNIT = 0.01   # 保额单位
SA_BASIC = premium × sa_ratio / 100

for year in range(1, max_year + 1):
    # 查精算因子
    cv_factor = lookup("cv", sex, PmtP, age, year)
    db_factor = lookup("db", sex, PmtP, age, year)
    rv_factor = lookup("rv", sex, PmtP, age, year)
    ...

    # 保证利益 —— 注意！用初始 SA_BASIC，非递增值
    guaranteed_cv = round(cv_factor × SA_BASIC / SA_UNIT, 1)
    guaranteed_db = max(round(db_factor × SA_BASIC / SA_UNIT, 1), guaranteed_cv)

    # 红利计算（中档演示利率）
    annual_dividend = round(
        ((prev_rv + vnp) × SA_BASIC / SA_UNIT +
         cum_bonus × prev_rv_pvfb / SA_UNIT) ×
        (演示利率 - 低档利率) × 0.7, 1
    )

    bonus_face_inc = round(annual_dividend / rv_pvfb × SA_UNIT, 1)
    cum_bonus += bonus_face_inc
    bonus_cv = round(cum_bonus × cv_pvfb / SA_UNIT, 1)
```

### 常见坑

| 问题 | 原因 | 解决 |
|------|------|------|
| Year 1 对但后续年偏差越来越大 | 用了递增值而非初始 SA_BASIC | 全部计算用初始 SA_BASIC |
| 红利偏差 | prev_rv/vnp 的年份偏移逻辑错误 | 严格按 Excel 的行偏移公式 |
| IRR 曲线第一年爆炸 | Newton 法对负 IRR 发散 | 二分法定位 + Newton 精调 |

### 完整引擎

见 `scripts/calculator.py`

---

## 第 4 步：构建 Web 工具

### 方案选择

| 方案 | 适用场景 | 复杂度 |
|------|---------|--------|
| **Flask + SQLite** | 本地/内网使用，需 Python 环境 | 低 |
| **纯静态 HTML + JS** | 在线部署，零依赖，任何人可打开 | 中 |
| **Streamlit** | 快速原型 | 低 |

### Flask 版（本地）

```python
# app.py
from flask import Flask, render_template, request, jsonify
from calculator import InsuranceCalculator

app = Flask(__name__)
calc = InsuranceCalculator("actuarial.db")

@app.route("/api/calculate", methods=["POST"])
def calculate():
    data = request.get_json()
    result = calc.calc_benefit(
        entry_age=int(data["age"]),
        sex=int(data["sex"]),
        pmt_p=int(data["pmt_p"]),
        annual_premium=float(data["premium"]),
    )
    return jsonify(result)
```

### 纯静态版（在线部署）

关键转换：
1. **SQLite → JS 对象**：导出为 `"sex-PmtP-age-pass_yr": value` 格式的 JSON
2. **Python 计算 → JS 计算**：完全相同的公式逻辑，换语法
3. **Chart.js CDN**：图表不需要后端渲染
4. **部署**：任意静态托管（CloudStudio / GitHub Pages / Vercel）

数据导出脚本见 `scripts/export_data.py`，静态页面模板见 `templates/index.html`。

---

## 第 5 步：验证与对比

### 验证方法

选一个 Excel 中已有的案例（如 41 岁女 5 年交 10 万），逐年对比以下值：

```
年度  保证CV     Excel值    偏差   保证DB     Excel值    偏差   累积红利保额  Excel值    偏差
1     29233.3    29233.3    ✓      140000     140000     ✓      1307.1      1307.1     ✓
2     87928.5    87928.5    ✓      280000     280000     ✓      4007.8      4007.8     ✓
5     392216.7   392216.7   ✓      700000     700000     ✓      20435.9     20435.9    ✓
10    530120.5   530120.5   ✓      700000     700000     ✓      56263.0     56263.0    ✓
20    628610.5   628610.5   ✓      700000     700000     ✓      136148.7    136148.7   ✓
```

### 如果对不上

1. 先对齐 Year 1 —— 是最容易的，公式最简单
2. 检查 SA_BASIC 是否用了初始值（最常见的错误）
3. 检查因子查找的年份是否有 ±1 偏移
4. 用手算验证一个中间年份的公式链

---

## 文件清单

```
LYDB.skill/
├── README.md                  # 本文档（5 步完整指南）
├── scripts/
│   ├── import_data.py         # 第 2 步：Excel → SQLite
│   ├── calculator.py          # 第 3 步：计算引擎
│   ├── export_data.py         # 第 4 步：SQLite → JS 数据
│   └── app.py                 # 第 4 步：Flask 入口
├── templates/
│   └── index.html             # 第 4 步：纯静态前端模板
└── .gitignore
```

## 常见问题

**Q: 我的 Excel 结构不完全一样怎么办？**
A: 核心逻辑不变。重点找到：① 现金价值因子在哪张表（通常是带 CV 的 Sheet）；② 身故金因子在哪；③ 红利计算公式在哪个 Sheet。然后用第 1 步的方法分析公式引用关系。

**Q: 能支持多产品对比吗？**
A: 可以的。每个产品一个 SQLite/JS 数据文件，前端加产品下拉框，切换产品时加载对应数据。

**Q: 在线加载 6.5MB 数据会不会太慢？**
A: Gzip 压缩后约 1.5MB，首次加载 2-3 秒。后续浏览器缓存，秒开。也可进一步精简（去掉全零条目）。

## License

MIT — 自由使用、修改、分发。精算数据版权归原保险公司所有，仅供学习研究。
