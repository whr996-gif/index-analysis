# Wind 金融数据接口参考

## 指数相关接口

### 1. get_index_basicinfo - 指数基本信息
**用途**：获取指数的编制方法、成份股列表、权重等静态信息

**参数**：
```json
{
  "question": "查询[指数名称]的发布机构、基日基点、样本空间、选样方法、成份股及权重"
}
```

**返回字段**：
- 指数全称
- 发布机构
- 基日
- 基点
- 样本空间
- 选样方法
- 成份股列表（含权重）
- 成分数量

---

### 2. get_index_kline - 指数K线数据（含成交额）
**用途**：获取指数的历史点位和成交额数据，用于计算收益率、最大回撤、夏普比率、量价分析

**参数**：
```json
{
  "windcode": "000300.SH",
  "begin": "2023-08-27",
  "end": "2026-08-27",
  "period": "day"
}
```

**返回字段**：
- 日期
- 开盘价
- 收盘价
- 最高价
- 最低价
- **成交额（元）** — 用于成交额展示和量价分析

> 取数范围：从今天倒推3年（约750个交易日），满足近三年收益、夏普、最大回撤计算需求。

---

### 3. get_index_fundamentals - 指数基本面/估值数据
**用途**：获取指数的PE-TTM、PB、股息率、估值分位等估值指标

**参数**：
```json
{
  "question": "查询[指数名称]的PE-TTM、PB、近三年PE分位、股息率"
}
```

**返回字段**：
- PE-TTM（市盈率，滚动12个月）
- PB（市净率）
- **PE历史分位（近3年）** — 百分比，0-100，用于小白安全边际判断
- 股息率（仅红利类指数）
- 其他加权财务指标

> 若接口不直接返回PE分位，需通过历史PE序列自行计算（见下方"估值分位计算"）。

---

### 4. get_index_technicals - 指数技术指标
**用途**：获取指数的技术分析指标（均线、成交量等）

**参数**：
```json
{
  "question": "查询[指数名称]的MA5、MA20、MA60、近5日平均成交额、近20日平均成交额"
}
```

**返回字段**：
- MA5（5日均线）
- MA20（20日均线）
- MA60（60日均线）
- 近5日平均成交额
- 近20日平均成交额

> 若该接口不可用，可基于 get_index_kline 返回的K线数据自行计算均线和成交额均值。

---

### 5. get_index_price_indicators - 指数行情快照
**用途**：获取指数当前时刻的点位和涨跌幅

**参数**：
```json
{
  "windcode": "000300.SH",
  "indexes": "最新成交价,涨跌幅,成交额"
}
```

**返回字段**：
- 最新成交价
- 涨跌幅
- 成交额

---

## 股票相关接口

### 6. get_stock_basicinfo - 股票基本信息
**用途**：获取成分股的中证三级行业分类

**参数**：
```json
{
  "question": "查询[股票代码]的中证三级行业分类、所属行业"
}
```

**返回字段**：
- 股票名称
- 股票代码
- **中证三级行业分类**（注意：可能返回申万或其他分类，需在报告中标注实际分类）
- 上市日期
- 主营业务

---

## 关键计算逻辑

### 最新行情计算
```python
def calc_latest_market(kline_data):
    """计算近一周、近一月涨跌幅和最新成交额"""
    sorted_data = sorted(kline_data, key=lambda x: x["date"])
    latest = sorted_data[-1]
    
    # 近一周（约5个交易日前）
    one_week_ago = sorted_data[-6] if len(sorted_data) >= 6 else sorted_data[0]
    return_1w = (latest["close"] / one_week_ago["close"] - 1) * 100
    
    # 近一月（约20个交易日前）
    one_month_ago = sorted_data[-21] if len(sorted_data) >= 21 else sorted_data[0]
    return_1m = (latest["close"] / one_month_ago["close"] - 1) * 100
    
    # 最新成交额（元 → 亿元）
    turnover_yi = latest.get("amount", 0) / 100000000
    
    return round(return_1w, 2), round(return_1m, 2), round(turnover_yi, 2)
```

### 近三年收益率（年化）
```python
def calc_annual_return_3y(kline_data):
    sorted_data = sorted(kline_data, key=lambda x: x["date"])
    latest_close = sorted_data[-1]["close"]
    # 3年前（约750个交易日前，取最接近的）
    three_year_ago = sorted_data[0]  # 数据范围本身就是3年
    total_return = latest_close / three_year_ago["close"] - 1
    annual_return = ((1 + total_return) ** (1/3) - 1) * 100
    return round(annual_return, 2)
```

### 夏普比率计算
```python
import math

def calc_sharpe_ratio(kline_data, risk_free_rate=0.025):
    """
    计算近三年夏普比率
    risk_free_rate: 无风险利率，默认2.5%（中国10年期国债收益率近似值）
    """
    sorted_data = sorted(kline_data, key=lambda x: x["date"])
    closes = [item["close"] for item in sorted_data]
    
    # 日收益率序列
    daily_returns = []
    for i in range(1, len(closes)):
        daily_returns.append(closes[i] / closes[i-1] - 1)
    
    if len(daily_returns) < 2:
        return None
    
    # 年化收益率和波动率
    n = len(daily_returns)
    mean_daily = sum(daily_returns) / n
    variance = sum((r - mean_daily) ** 2 for r in daily_returns) / (n - 1)
    std_daily = math.sqrt(variance)
    
    annual_return = mean_daily * 252
    annual_vol = std_daily * math.sqrt(252)
    
    if annual_vol == 0:
        return None
    
    sharpe = (annual_return - risk_free_rate) / annual_vol
    return round(sharpe, 2)
```

### 最大回撤计算
```python
def calc_max_drawdown(kline_data):
    """计算最大回撤（百分比）"""
    if not kline_data:
        return 0.0
    
    sorted_data = sorted(kline_data, key=lambda x: x["date"])
    peak = sorted_data[0]["close"]
    max_dd = 0.0
    
    for item in sorted_data:
        price = item["close"]
        if price > peak:
            peak = price
        dd = (peak - price) / peak
        if dd > max_dd:
            max_dd = dd
    
    return round(max_dd * 100, 2)
```

### 估值分位计算
```python
def calc_pe_percentile(current_pe, historical_pe_list):
    """
    计算当前PE在历史序列中的分位
    返回 0-100 的百分比
    """
    if not historical_pe_list or current_pe is None:
        return None
    
    sorted_hist = sorted(historical_pe_list)
    count_below = sum(1 for pe in sorted_hist if pe <= current_pe)
    percentile = (count_below / len(sorted_hist)) * 100
    return round(percentile, 1)
```

### 技术指标计算
```python
def calc_technical_indicators(kline_data):
    """基于K线数据计算技术指标，返回分析用字典"""
    sorted_data = sorted(kline_data, key=lambda x: x["date"])
    closes = [item["close"] for item in sorted_data]
    amounts = [item.get("amount", 0) for item in sorted_data]
    
    # 均线
    ma5 = sum(closes[-5:]) / 5 if len(closes) >= 5 else None
    ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else None
    ma60 = sum(closes[-60:]) / 60 if len(closes) >= 60 else None
    
    # 量价
    avg_amount_5d = sum(amounts[-5:]) / 5 if len(amounts) >= 5 else 0
    avg_amount_20d = sum(amounts[-20:]) / 20 if len(amounts) >= 20 else 0
    volume_ratio = avg_amount_5d / avg_amount_20d if avg_amount_20d > 0 else 1
    
    # 近20日涨跌幅
    return_20d = (closes[-1] / closes[-21] - 1) * 100 if len(closes) >= 21 else 0
    
    # 均线排列判断
    if ma5 and ma20 and ma60:
        if ma5 > ma20 > ma60:
            ma_trend = "多头排列"
        elif ma5 < ma20 < ma60:
            ma_trend = "空头排列"
        else:
            ma_trend = "均线缠绕"
    else:
        ma_trend = "数据不足"
    
    return {
        "ma5": round(ma5, 2) if ma5 else None,
        "ma20": round(ma20, 2) if ma20 else None,
        "ma60": round(ma60, 2) if ma60 else None,
        "ma_trend": ma_trend,
        "volume_ratio": round(volume_ratio, 2),
        "return_20d": round(return_20d, 2),
        "is_breakout_high": closes[-1] >= max(closes[-60:-1]) if len(closes) >= 60 else False
    }
```

### 行业权重计算（仅饼图数据）
```python
def calc_industry_weights(components):
    """
    计算行业权重分布，返回饼图用数据
    权重小于1%的行业合并为"其他"
    """
    industry_dict = {}
    for comp in components:
        industry = comp.get("industry", "其他")
        weight = comp.get("weight", 0)
        if industry not in industry_dict:
            industry_dict[industry] = 0
        industry_dict[industry] += weight
    
    # 按权重排序
    sorted_industries = sorted(industry_dict.items(), key=lambda x: x[1], reverse=True)
    
    # 小权重合并为"其他"
    result = []
    other_weight = 0
    for name, wt in sorted_industries:
        if wt >= 1.0:
            result.append({"industry": name, "weight": round(wt, 2)})
        else:
            other_weight += wt
    
    if other_weight > 0:
        result.append({"industry": "其他", "weight": round(other_weight, 2)})
    
    return result  # 直接用于饼图，不生成明细表格
```

### 前十大成份股（无总市值列）
```python
def get_top_components(components, n=10):
    """
    获取前N大成份股
    表格列：排名、名称、代码、三级行业、权重（无总市值）
    """
    sorted_comps = sorted(components, key=lambda x: x.get("weight", 0), reverse=True)
    top_n = sorted_comps[:n]
    total_weight = sum(c.get("weight", 0) for c in top_n)
    
    result = []
    for i, comp in enumerate(top_n):
        result.append({
            "rank": i + 1,
            "name": comp.get("name", ""),
            "code": comp.get("code", ""),
            "industry": comp.get("industry", "其他"),
            "weight": round(comp.get("weight", 0), 2)
        })
    
    return result, round(total_weight, 2)
```

---

## 红利类指数自动识别规则
```python
def is_dividend_index(index_name):
    keywords = ["红利", "银行", "dividend"]
    return any(kw in index_name for kw in keywords)
```

---

## 小白解读话术生成规则

### 估值分位解读
```python
def valuation_interpretation(pe_percentile):
    if pe_percentile is None:
        return "估值数据有限，建议结合行业基本面综合判断。"
    if pe_percentile < 30:
        return f"当前估值处于历史{pe_percentile}%分位，比历史上{100-pe_percentile}%的时候都便宜，安全边际较高，适合分批布局。"
    elif pe_percentile < 70:
        return f"当前估值处于历史{pe_percentile}%分位，处于历史中等水平，不贵也不便宜，可正常持有。"
    else:
        return f"当前估值处于历史{pe_percentile}%分位，比历史上{pe_percentile}%的时候都贵，泡沫风险较大，需谨慎追高。"
```

### 夏普比率解读
```python
def sharpe_interpretation(sharpe):
    if sharpe is None:
        return "夏普比率数据不足，无法评估风险收益比。"
    if sharpe > 1:
        return f"夏普比率{sharpe}，收益跑赢波动，性价比不错，持有体验较好。"
    elif sharpe > 0.5:
        return f"夏普比率{sharpe}，收益与波动基本匹配，属于中等水平。"
    elif sharpe > 0:
        return f"夏普比率{sharpe}，波动较大收益偏低，持有体验一般。"
    else:
        return f"夏普比率{sharpe}，近三年收益跑输无风险利率，波动大且没赚到钱，需谨慎。"
```

### 最大回撤解读
```python
def drawdown_interpretation(max_dd):
    if max_dd > 40:
        return f"最大回撤{max_dd}%，历史上曾经跌过近一半，波动极大，要做好心理准备。"
    elif max_dd > 30:
        return f"最大回撤{max_dd}%，曾经跌过三成以上，波动较大，适合风险承受能力强的投资者。"
    elif max_dd > 15:
        return f"最大回撤{max_dd}%，波动中等，属于正常权益类资产水平。"
    else:
        return f"最大回撤{max_dd}%，走势相对稳健，回撤控制较好。"
```

### 技术分析话术
```python
def technical_analysis_text(tech):
    """根据技术指标生成一句小白友好的分析"""
    trend = tech["ma_trend"]
    vol_ratio = tech["volume_ratio"]
    ret_20d = tech["return_20d"]
    breakout = tech["is_breakout_high"]
    
    if trend == "多头排列" and vol_ratio > 1.2 and ret_20d > 0:
        return "近期向上趋势较强，量价齐升，短期动能充足，趋势投资者可关注。"
    elif trend == "空头排列" and vol_ratio < 0.8 and ret_20d < 0:
        return "近期处于下跌趋势，成交量萎缩，短期仍偏弱，建议观望等待企稳信号。"
    elif trend == "多头排列" and breakout:
        return "近期突破前期高点且均线多头排列，上涨空间可能打开，但需注意追高风险。"
    elif trend == "空头排列" and vol_ratio > 1.2:
        return "近期跌破关键位且放量下跌，短期下行压力较大，注意控制仓位。"
    elif trend == "均线缠绕":
        return "近期走势震荡，多空分歧较大，方向不明朗，建议等待突破后再操作。"
    elif ret_20d > 5 and vol_ratio > 1:
        return "近一月涨幅较大且成交活跃，短期偏强，但需警惕回调风险。"
    elif ret_20d < -5 and vol_ratio < 0.8:
        return "近一月调整较多且成交萎缩，抛压减轻，可关注是否出现企稳信号。"
    else:
        return "近期走势平稳，量价配合正常，暂无明显趋势性信号。"
```

---

## 常见Wind指数代码
| 指数名称 | Wind代码 |
|---------|---------|
| 沪深300 | 000300.SH |
| 中证500 | 000905.SH |
| 中证1000 | 000852.SH |
| 中证红利 | 000922.SH |
| 中证银行 | 399986.SZ |
| 创业板指 | 399006.SZ |
| 上证指数 | 000001.SH |
| 深证成指 | 399001.SZ |
| 科创50 | 000688.SH |
| 中证白酒 | 399997.SZ |
| 中证医疗 | 399989.SZ |

> 注意：用户通常使用指数名称而非代码，Wind接口支持通过名称查询。
