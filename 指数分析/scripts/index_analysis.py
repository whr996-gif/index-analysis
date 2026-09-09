#!/usr/bin/env python3
"""
指数分析数据处理与HTML生成脚本（V2优化版）

V2优化点：
1. 指数表现分短期/长期：短期(近3月/近1年/今年以来/近1年最大回撤)，长期(近3年年化/近5年年化/近3年夏普/近3年最大回撤)
2. 指数表现下方增加近三年行情折线图
3. 行业分布描述文字按行业数量自适应（1个/2个/3个及以上）
4. 编制方法中"选样方法"改为"聚焦方向"，从选样方法文字中"从事"后提取
"""
import json
import math
import os
import re
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple


# ============================================================
# 数据类
# ============================================================

@dataclass
class IndexInfo:
    """指数基本信息"""
    name: str = ""
    code: str = ""
    publisher: str = ""
    base_date: str = ""
    base_point: str = ""
    sample_space: str = ""
    selection_method: str = ""
    focus_direction: str = ""       # 聚焦方向（从选样方法提取）
    components: List[Dict] = field(default_factory=list)


@dataclass
class LatestMarket:
    """最新行情"""
    return_1w: float = 0.0
    return_1m: float = 0.0
    turnover: float = 0.0
    latest_close: float = 0.0


@dataclass
class ShortTermPerformance:
    """短期表现"""
    return_3m: float = 0.0           # 近3个月涨跌幅 %
    return_1y: float = 0.0           # 近一年涨跌幅 %
    return_ytd: float = 0.0          # 今年以来涨跌幅 %
    max_drawdown_1y: float = 0.0     # 近一年最大回撤 %


@dataclass
class LongTermPerformance:
    """长期表现"""
    annual_return_3y: float = 0.0    # 近三年年化收益率 %
    annual_return_5y: Optional[float] = None  # 近五年年化收益率 %
    sharpe_ratio_3y: Optional[float] = None   # 近三年夏普比率
    max_drawdown_3y: float = 0.0     # 近三年最大回撤 %


@dataclass
class IndexValuation:
    """指数估值数据"""
    pe_ttm: Optional[float] = None
    pb: Optional[float] = None
    pe_percentile: Optional[float] = None
    percentile_period: str = "近10年"  # 分位周期：近10年/近5年/近3年/成立以来
    dividend_yield: Optional[float] = None


@dataclass
class TechnicalIndicators:
    """技术指标"""
    ma5: Optional[float] = None
    ma20: Optional[float] = None
    ma60: Optional[float] = None
    ma_trend: str = "数据不足"
    volume_ratio: float = 1.0
    return_20d: float = 0.0
    is_breakout_high: bool = False


@dataclass
class IndustryWeight:
    """行业权重"""
    industry: str
    weight: float


@dataclass
class ComponentStock:
    """成份股"""
    rank: int
    name: str
    code: str
    industry: str
    weight: float


@dataclass
class FundamentalQuarter:
    """单季度基本面数据"""
    quarter: str               # 季度标签，如 "2025Q3"
    revenue_yoy: float         # 单季度营业收入同比增长率 %
    net_profit_yoy: float      # 单季度归母净利润同比增长率 %


# ============================================================
# 工具函数
# ============================================================

def is_dividend_index(index_name: str) -> bool:
    keywords = ["红利", "银行", "dividend"]
    return any(kw.lower() in index_name.lower() for kw in keywords)


def parse_date(date_str: str) -> datetime:
    for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%Y-%m-%d %H:%M:%S"]:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    raise ValueError(f"无法解析日期: {date_str}")


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (ValueError, TypeError):
        return default


def extract_focus_direction(selection_method: str) -> str:
    """
    从选样方法文字中提取聚焦方向。
    规则：找到"从事"后面的内容，截取到第一个标点符号或句子结束。
    示例："选取科创板中从事集成电路设计的上市公司" → "集成电路设计"
    """
    if not selection_method:
        return ""

    # 尝试匹配"从事XXX的"或"从事XXX。"等模式
    patterns = [
        r'从事([^的。，；、\s]+(?:设计|制造|销售|服务|生产|研发|投资|运营|管理))',
        r'从事([^的。，；、]+)',
        r'聚焦([^的。，；、]+)',
        r'选取[^中从]*中([^的。，；、]+(?:设计|制造|销售|服务|生产|研发))',
    ]

    for pattern in patterns:
        match = re.search(pattern, selection_method)
        if match:
            result = match.group(1).strip()
            # 清理尾部多余的"的""等""业务""相关""领域""行业""产业""主题"字
            result = re.sub(r'(的|等|业务|相关|领域|行业|产业|主题|概念)$', '', result)
            if result and len(result) <= 30:
                return result

    # 兜底：取选样方法的前20个字
    return selection_method[:20] + "..." if len(selection_method) > 20 else selection_method


# ============================================================
# 计算函数
# ============================================================

def calc_latest_market(kline_data: List[Dict]) -> LatestMarket:
    if not kline_data:
        return LatestMarket()
    sorted_data = sorted(kline_data, key=lambda x: x["date"])
    latest = sorted_data[-1]
    latest_close = safe_float(latest.get("close"))

    idx_1w = max(0, len(sorted_data) - 6)
    close_1w = safe_float(sorted_data[idx_1w].get("close"))
    return_1w = (latest_close / close_1w - 1) * 100 if close_1w else 0

    idx_1m = max(0, len(sorted_data) - 21)
    close_1m = safe_float(sorted_data[idx_1m].get("close"))
    return_1m = (latest_close / close_1m - 1) * 100 if close_1m else 0

    amount = safe_float(latest.get("amount", latest.get("volume", 0)))
    turnover_yi = amount / 100000000 if amount > 1000000 else amount

    return LatestMarket(
        return_1w=round(return_1w, 2),
        return_1m=round(return_1m, 2),
        turnover=round(turnover_yi, 2),
        latest_close=round(latest_close, 2)
    )


def calc_short_term_performance(kline_data: List[Dict]) -> ShortTermPerformance:
    """计算短期表现：近3月、近1年、今年以来、近1年最大回撤"""
    if not kline_data or len(kline_data) < 2:
        return ShortTermPerformance()

    sorted_data = sorted(kline_data, key=lambda x: x["date"])
    closes = [safe_float(item.get("close")) for item in sorted_data]
    dates = [item["date"] for item in sorted_data]
    latest_close = closes[-1]
    latest_date = parse_date(dates[-1])

    # 近3个月（约63个交易日）
    idx_3m = max(0, len(closes) - 64)
    close_3m = closes[idx_3m]
    return_3m = (latest_close / close_3m - 1) * 100 if close_3m else 0

    # 近一年（约252个交易日）
    idx_1y = max(0, len(closes) - 253)
    close_1y = closes[idx_1y]
    return_1y = (latest_close / close_1y - 1) * 100 if close_1y else 0

    # 今年以来
    year_begin = datetime(latest_date.year, 1, 1)
    ytd_close = None
    for i, d in enumerate(dates):
        if parse_date(d) >= year_begin:
            ytd_close = closes[i]
            break
    if ytd_close is None:
        ytd_close = closes[0]
    return_ytd = (latest_close / ytd_close - 1) * 100 if ytd_close else 0

    # 近一年最大回撤
    closes_1y = closes[idx_1y:] if len(closes) > 252 else closes
    peak = closes_1y[0]
    max_dd_1y = 0.0
    for price in closes_1y:
        if price > peak:
            peak = price
        if peak > 0:
            dd = (peak - price) / peak
            if dd > max_dd_1y:
                max_dd_1y = dd

    return ShortTermPerformance(
        return_3m=round(return_3m, 2),
        return_1y=round(return_1y, 2),
        return_ytd=round(return_ytd, 2),
        max_drawdown_1y=round(max_dd_1y * 100, 2)
    )


def calc_long_term_performance(kline_data: List[Dict], risk_free_rate: float = 0.025) -> LongTermPerformance:
    """计算长期表现：近3年年化、近5年年化、近3年夏普、近3年最大回撤"""
    if not kline_data or len(kline_data) < 2:
        return LongTermPerformance()

    sorted_data = sorted(kline_data, key=lambda x: x["date"])
    closes = [safe_float(item.get("close")) for item in sorted_data]
    dates = [item["date"] for item in sorted_data]
    latest_close = closes[-1]
    latest_date = parse_date(dates[-1])
    first_date = parse_date(dates[0])

    # 数据实际覆盖年数
    years_covered = (latest_date - first_date).days / 365.25

    # 近三年年化（用实际数据时长计算年化）
    first_close = closes[0]
    if first_close > 0 and years_covered > 0:
        total_return = latest_close / first_close - 1
        annual_return_3y = ((1 + total_return) ** (1 / years_covered) - 1) * 100
    else:
        annual_return_3y = 0

    # 近五年年化（数据不足5年则为None）
    annual_return_5y = None
    if years_covered >= 4.5:
        idx_5y = max(0, len(closes) - 1261)  # 约5年交易日
        close_5y = closes[idx_5y]
        if close_5y > 0:
            total_5y = latest_close / close_5y - 1
            annual_return_5y = round(((1 + total_5y) ** (1 / 5) - 1) * 100, 2)

    # 夏普比率（基于全部可用数据）
    daily_returns = []
    for i in range(1, len(closes)):
        if closes[i - 1] > 0:
            daily_returns.append(closes[i] / closes[i - 1] - 1)

    sharpe = None
    if len(daily_returns) >= 2:
        n = len(daily_returns)
        mean_daily = sum(daily_returns) / n
        variance = sum((r - mean_daily) ** 2 for r in daily_returns) / (n - 1)
        std_daily = math.sqrt(variance)
        annual_vol = std_daily * math.sqrt(252)
        if annual_vol > 0:
            ann_ret = mean_daily * 252
            sharpe = round((ann_ret - risk_free_rate) / annual_vol, 2)

    # 近三年最大回撤（用全部数据）
    peak = closes[0]
    max_dd = 0.0
    for price in closes:
        if price > peak:
            peak = price
        if peak > 0:
            dd = (peak - price) / peak
            if dd > max_dd:
                max_dd = dd

    return LongTermPerformance(
        annual_return_3y=round(annual_return_3y, 2),
        annual_return_5y=annual_return_5y,
        sharpe_ratio_3y=sharpe,
        max_drawdown_3y=round(max_dd * 100, 2)
    )


def calc_technical_indicators(kline_data: List[Dict]) -> TechnicalIndicators:
    if not kline_data or len(kline_data) < 5:
        return TechnicalIndicators()
    sorted_data = sorted(kline_data, key=lambda x: x["date"])
    closes = [safe_float(item.get("close")) for item in sorted_data]
    amounts = [safe_float(item.get("amount", item.get("volume", 0))) for item in sorted_data]

    ma5 = sum(closes[-5:]) / 5 if len(closes) >= 5 else None
    ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else None
    ma60 = sum(closes[-60:]) / 60 if len(closes) >= 60 else None

    if ma5 and ma20 and ma60:
        if ma5 > ma20 > ma60:
            ma_trend = "多头排列"
        elif ma5 < ma20 < ma60:
            ma_trend = "空头排列"
        else:
            ma_trend = "均线缠绕"
    else:
        ma_trend = "数据不足"

    avg_5d = sum(amounts[-5:]) / 5 if len(amounts) >= 5 else 0
    avg_20d = sum(amounts[-20:]) / 20 if len(amounts) >= 20 else 0
    volume_ratio = avg_5d / avg_20d if avg_20d > 0 else 1.0

    return_20d = 0.0
    if len(closes) >= 21:
        return_20d = (closes[-1] / closes[-21] - 1) * 100 if closes[-21] > 0 else 0

    is_breakout = False
    if len(closes) >= 60:
        is_breakout = closes[-1] >= max(closes[-60:-1])

    return TechnicalIndicators(
        ma5=round(ma5, 2) if ma5 else None,
        ma20=round(ma20, 2) if ma20 else None,
        ma60=round(ma60, 2) if ma60 else None,
        ma_trend=ma_trend,
        volume_ratio=round(volume_ratio, 2),
        return_20d=round(return_20d, 2),
        is_breakout_high=is_breakout
    )


def calc_industry_weights(components: List[Dict], min_weight: float = 1.0) -> List[IndustryWeight]:
    industry_dict: Dict[str, float] = {}
    for comp in components:
        industry = comp.get("industry", "其他") or "其他"
        weight = safe_float(comp.get("weight"))
        industry_dict[industry] = industry_dict.get(industry, 0) + weight

    sorted_industries = sorted(industry_dict.items(), key=lambda x: x[1], reverse=True)

    result = []
    other_weight = 0.0
    for name, wt in sorted_industries:
        if wt >= min_weight:
            result.append(IndustryWeight(industry=name, weight=round(wt, 2)))
        else:
            other_weight += wt

    if other_weight > 0:
        result.append(IndustryWeight(industry="其他", weight=round(other_weight, 2)))

    return result


def get_top_components(components: List[Dict], n: int = 10) -> Tuple[List[ComponentStock], float]:
    sorted_comps = sorted(components, key=lambda x: safe_float(x.get("weight")), reverse=True)
    top_n = sorted_comps[:n]
    total_weight = sum(safe_float(c.get("weight")) for c in top_n)

    result = []
    for i, comp in enumerate(top_n):
        result.append(ComponentStock(
            rank=i + 1,
            name=comp.get("name", ""),
            code=comp.get("code", ""),
            industry=comp.get("industry", "其他") or "其他",
            weight=round(safe_float(comp.get("weight")), 2)
        ))

    return result, round(total_weight, 2)


def generate_kline_chart_data(kline_data: List[Dict], max_points: int = 500) -> Dict[str, Any]:
    """
    生成近三年行情折线图数据。
    数据点过多时均匀采样。
    """
    if not kline_data:
        return {"labels": [], "data": []}

    sorted_data = sorted(kline_data, key=lambda x: x["date"])

    # 采样
    if len(sorted_data) > max_points:
        step = len(sorted_data) // max_points
        sampled = sorted_data[::step]
        if sampled[-1] != sorted_data[-1]:
            sampled.append(sorted_data[-1])
    else:
        sampled = sorted_data

    labels = []
    data = []
    for item in sampled:
        date_str = item["date"]
        # 简化日期显示：YYYY-MM
        if "T" in date_str:
            date_str = date_str.split("T")[0]
        labels.append(date_str)
        data.append(round(safe_float(item.get("close")), 2))

    return {"labels": labels, "data": data}


# ============================================================
# 小白解读话术
# ============================================================

def gen_methodology_text(info: IndexInfo) -> str:
    base = f"该指数以{info.base_date}为基日，基点{info.base_point}。" if info.base_date else ""
    sample = f"样本空间为{info.sample_space}。" if info.sample_space else ""
    focus = f"聚焦方向为{info.focus_direction}。" if info.focus_direction else ""
    plain = f"简单来说，这个指数选的是{info.focus_direction or info.name}相关的代表性公司，反映了该领域的整体表现。"
    return base + sample + focus + plain


def gen_latest_market_text(market: LatestMarket, name: str) -> str:
    dir_1w = "上涨" if market.return_1w > 0 else "下跌"
    dir_1m = "上涨" if market.return_1m > 0 else "下跌"

    if market.return_1w > 3 and market.return_1m > 5:
        trend_comment = "短期表现强劲，上涨动能充足"
    elif market.return_1w < -3 and market.return_1m < -5:
        trend_comment = "短期调整明显，仍处于弱势"
    elif abs(market.return_1w) < 1 and abs(market.return_1m) < 3:
        trend_comment = "短期走势平稳，波动不大"
    else:
        trend_comment = "短期有一定波动"

    return (
        f"最新行情方面，{name}近一周{dir_1w}{abs(market.return_1w)}%，"
        f"近一月{dir_1m}{abs(market.return_1m)}%。"
        f"一句话解读：{trend_comment}。"
    )


def gen_short_term_text(short: ShortTermPerformance, name: str) -> str:
    """短期表现解读"""
    dir_3m = "上涨" if short.return_3m > 0 else "下跌"
    dir_1y = "上涨" if short.return_1y > 0 else "下跌"
    dir_ytd = "上涨" if short.return_ytd > 0 else "下跌"

    # 近一年最大回撤解读
    if short.max_drawdown_1y > 30:
        dd_comment = f"近一年最大回撤{short.max_drawdown_1y}%，短期波动极大"
    elif short.max_drawdown_1y > 15:
        dd_comment = f"近一年最大回撤{short.max_drawdown_1y}%，短期波动中等"
    else:
        dd_comment = f"近一年最大回撤{short.max_drawdown_1y}%，短期走势较稳"

    return (
        f"短期表现方面，{name}近3个月{dir_3m}{abs(short.return_3m)}%，"
        f"近一年{dir_1y}{abs(short.return_1y)}%，"
        f"今年以来{dir_ytd}{abs(short.return_ytd)}%，{dd_comment}。"
    )


def gen_long_term_text(long: LongTermPerformance, name: str) -> str:
    """长期表现解读"""
    dir_3y = "上涨" if long.annual_return_3y > 0 else "下跌"

    # 夏普解读
    if long.sharpe_ratio_3y is None:
        sharpe_text = "夏普比率数据不足"
    elif long.sharpe_ratio_3y > 1:
        sharpe_text = f"夏普比率{long.sharpe_ratio_3y}，收益跑赢波动，性价比不错"
    elif long.sharpe_ratio_3y > 0.5:
        sharpe_text = f"夏普比率{long.sharpe_ratio_3y}，收益与波动基本匹配"
    elif long.sharpe_ratio_3y > 0:
        sharpe_text = f"夏普比率{long.sharpe_ratio_3y}，波动较大收益偏低"
    else:
        sharpe_text = f"夏普比率{long.sharpe_ratio_3y}，收益跑输无风险利率"

    # 最大回撤解读
    if long.max_drawdown_3y > 40:
        dd_text = f"最大回撤{long.max_drawdown_3y}%，曾经跌过近一半，波动极大"
    elif long.max_drawdown_3y > 30:
        dd_text = f"最大回撤{long.max_drawdown_3y}%，曾经跌过三成以上，波动较大"
    elif long.max_drawdown_3y > 15:
        dd_text = f"最大回撤{long.max_drawdown_3y}%，波动中等"
    else:
        dd_text = f"最大回撤{long.max_drawdown_3y}%，走势相对稳健"

    # 近五年
    five_year_text = ""
    if long.annual_return_5y is not None:
        dir_5y = "上涨" if long.annual_return_5y > 0 else "下跌"
        five_year_text = f"近五年年化{dir_5y}{abs(long.annual_return_5y)}%，"
    else:
        five_year_text = "（指数成立不足5年，无近五年数据）"

    return (
        f"长期表现方面，{name}近三年年化{dir_3y}{abs(long.annual_return_3y)}%，"
        f"{five_year_text}{sharpe_text}，{dd_text}。"
    )


def gen_valuation_text(val: IndexValuation, name: str) -> str:
    parts = []

    if val.pe_ttm is not None:
        parts.append(f"当前PE-TTM为{val.pe_ttm}倍")

    if val.pe_percentile is not None:
        p = val.pe_percentile
        period = val.percentile_period or "近10年"
        if p < 30:
            parts.append(
                f"处于{period}{p}%分位，比历史上{100-p}%的时候都便宜，安全边际较高，适合分批布局"
            )
        elif p < 70:
            parts.append(f"处于{period}{p}%分位，估值处于历史中等水平，不贵也不便宜")
        else:
            parts.append(
                f"处于{period}{p}%分位，比历史上{p}%的时候都贵，泡沫风险较大，需谨慎追高"
            )
    elif val.pe_ttm is not None:
        if val.pe_ttm < 20:
            parts.append("从绝对估值看处于较低水平，安全边际相对较高")
        elif val.pe_ttm < 40:
            parts.append("从绝对估值看处于合理区间")
        else:
            parts.append("从绝对估值看处于较高水平，需注意估值风险")

    if val.dividend_yield is not None:
        if val.dividend_yield > 3:
            parts.append(f"股息率{val.dividend_yield}%，分红收益不错")
        else:
            parts.append(f"股息率{val.dividend_yield}%，分红水平一般")

    if not parts:
        return "估值数据暂无法获取。"

    return "从估值水平来看，" + "，".join(parts) + "。"


def gen_technical_text(tech: TechnicalIndicators) -> str:
    trend = tech.ma_trend
    vol_ratio = tech.volume_ratio
    ret_20d = tech.return_20d
    breakout = tech.is_breakout_high

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


def gen_industry_text(industries: List[IndustryWeight], name: str) -> str:
    """
    行业分布描述文字，按行业数量自适应：
    - 1个行业：XX指数集中于XX行业
    - 2个行业：XX指数聚集于XX行业和XX行业
    - 3个及以上：前三大行业分别为...
    """
    if not industries:
        return "行业分布数据暂无法获取。"

    n = len(industries)

    if n == 1:
        ind = industries[0]
        return (
            f"从行业分布来看，{name}集中于{ind.industry}行业，"
            f"占比{ind.weight}%。"
            f"一句话解读：行业高度集中，指数涨跌完全取决于{ind.industry}板块的整体表现。"
        )

    elif n == 2:
        i1, i2 = industries[0], industries[1]
        total = i1.weight + i2.weight
        return (
            f"从行业分布来看，{name}聚集于{i1.industry}和{i2.industry}两大行业，"
            f"分别占比{i1.weight}%和{i2.weight}%，合计{round(total, 2)}%。"
            f"一句话解读：行业较为集中，指数涨跌主要看这两大行业的表现。"
        )

    else:
        top3 = industries[:3]
        top3_text = "、".join([f"{w.industry}（{w.weight}%）" for w in top3])
        top3_sum = sum(w.weight for w in top3)

        if top3[0].weight > 30:
            concentration = "行业集中度较高，涨跌主要看前几大行业"
        elif top3_sum > 60:
            concentration = "行业有一定集中度，前三大行业影响较大"
        else:
            concentration = "行业较为分散，单一行业影响小，走势更稳"

        return (
            f"从行业分布来看，{name}前三大行业分别为{top3_text}，"
            f"合计占比{round(top3_sum, 2)}%。"
            f"一句话解读：{concentration}。"
        )


def gen_components_text(top_comps: List[ComponentStock], total_weight: float, name: str) -> str:
    if not top_comps:
        return "成份股数据暂无法获取。"

    top1 = top_comps[0]

    if total_weight > 50:
        concentration = "龙头效应明显，指数涨跌 heavily 依赖大公司"
    elif total_weight > 30:
        concentration = "集中度适中，龙头公司有一定影响但不至于独大"
    else:
        concentration = "成分分散，单只股票影响小，走势更能反映整体"

    return (
        f"前十大成份股合计权重为{total_weight}%。"
        f"一句话解读：{concentration}。"
        f"其中{top1.name}以{top1.weight}%权重位居第一，属于{top1.industry}行业。"
    )


def gen_fundamental_text(fundamentals: List[FundamentalQuarter], name: str) -> str:
    """基本面分析话术（小白友好）"""
    if not fundamentals:
        return "基本面数据暂无法获取。"

    latest = fundamentals[-1]
    n = len(fundamentals)

    # 营收趋势判断
    rev_trend = ""
    if n >= 2:
        if fundamentals[-1].revenue_yoy > fundamentals[-2].revenue_yoy:
            rev_trend = "营收增速持续提升"
        elif fundamentals[-1].revenue_yoy < fundamentals[-2].revenue_yoy:
            rev_trend = "营收增速有所放缓"
        else:
            rev_trend = "营收增速保持稳定"

    # 净利趋势判断
    profit_trend = ""
    if n >= 2:
        if fundamentals[-1].net_profit_yoy > fundamentals[-2].net_profit_yoy:
            profit_trend = "净利润增速加速增长"
        elif fundamentals[-1].net_profit_yoy < fundamentals[-2].net_profit_yoy:
            profit_trend = "净利润增速有所回落"
        else:
            profit_trend = "净利润增速保持稳定"

    # 利润弹性判断
    if latest.net_profit_yoy > latest.revenue_yoy * 1.5:
        elasticity = "净利润增速远超营收增速，说明盈利能力大幅提升，利润弹性很大"
    elif latest.net_profit_yoy > latest.revenue_yoy:
        elasticity = "净利润增速高于营收增速，盈利能力在改善"
    else:
        elasticity = "净利润增速低于营收增速，需关注盈利能力变化"

    # 增速高低判断
    if latest.revenue_yoy > 50:
        rev_level = "营收高速增长"
    elif latest.revenue_yoy > 20:
        rev_level = "营收较快增长"
    elif latest.revenue_yoy > 0:
        rev_level = "营收正增长"
    else:
        rev_level = "营收下滑"

    return (
        f"从基本面来看，{name}最新季度（{latest.quarter}）"
        f"营收同比增长{latest.revenue_yoy:.2f}%，{rev_level}；"
        f"归母净利润同比增长{latest.net_profit_yoy:.2f}%。"
        f"趋势上，{rev_trend}，{profit_trend}。"
        f"一句话解读：{elasticity}，行业景气度较高。"
    )


def gen_summary_text(
    fundamentals: List[FundamentalQuarter],
    top_comps: List[ComponentStock],
    total_weight: float,
    val: IndexValuation,
    tech: TechnicalIndicators,
    long: LongTermPerformance,
) -> str:
    """
    生成总结分析（不超过30字）。
    选取各模块中提示信号最强的2个正向信号拼接。
    信号强度：基本面景气(5) / 龙头效应(5) > 短期趋势(4) / 长期性价比(4) > 估值(3)
    """
    signals = []
    # 基本面信号（景气度）
    if fundamentals:
        latest = fundamentals[-1]
        if latest.net_profit_yoy > 100:
            signals.append((5, "基本面景气度高"))
        elif latest.net_profit_yoy > 30:
            signals.append((4, "基本面持续改善"))
        elif latest.net_profit_yoy > 0:
            signals.append((2, "基本面稳步回暖"))
    # 龙头效应信号（前十大权重集中度）
    if total_weight > 60:
        signals.append((5, "龙头效应明显"))
    elif total_weight > 40:
        signals.append((3, "龙头集中度较高"))
    # 估值信号（分位）
    if val.pe_percentile is not None:
        if val.pe_percentile < 20:
            signals.append((5, "估值安全边际高"))
        elif val.pe_percentile < 40:
            signals.append((3, "估值处于历史低位"))
    # 技术信号（趋势）
    if tech.ma_trend == "多头排列" and tech.volume_ratio > 1.1:
        signals.append((4, "短期上行趋势较强"))
    elif tech.ma_trend == "空头排列":
        signals.append((-4, "短期趋势偏弱"))
    # 长期信号（夏普）
    if long.sharpe_ratio_3y is not None and long.sharpe_ratio_3y > 1:
        signals.append((4, "长期性价比高"))
    # 取最高分的2个正向信号
    positive = [s for s in signals if s[0] > 0]
    positive.sort(key=lambda x: x[0], reverse=True)
    top = positive[:2]
    if not top:
        return "市场震荡，建议观望"
    summary = "，".join([t for _, t in top])
    # 超过30字则只保留最强信号
    if len(summary) > 30:
        summary = top[0][1]
    return summary


# ============================================================
# HTML 生成
# ============================================================

def _css_class_for_value(value: float) -> str:
    if value > 0:
        return "up"
    elif value < 0:
        return "down"
    return "neutral"


def _format_number(value: Optional[float], suffix: str = "", decimals: int = 2) -> str:
    if value is None:
        return "N/A"
    return f"{value:.{decimals}f}{suffix}"


def generate_html_report(
    info: IndexInfo,
    market: LatestMarket,
    short_perf: ShortTermPerformance,
    long_perf: LongTermPerformance,
    val: IndexValuation,
    tech: TechnicalIndicators,
    industries: List[IndustryWeight],
    top_comps: List[ComponentStock],
    total_weight: float,
    kline_chart: Dict[str, Any],
    fundamentals: List[FundamentalQuarter],
    output_path: str,
    template_path: Optional[str] = None,
    display_name: Optional[str] = None,
    summary: Optional[str] = None
) -> str:
    """生成HTML分析报告
    display_name: 报告展示名（ETF分析时传ETF名称，如"科创芯片设计ETF"）
    summary: 顶部总结分析（不超过30字），不传时自动生成
    """

    if summary is None:
        summary = gen_summary_text(fundamentals, top_comps, total_weight, val, tech, long_perf)
    if display_name is None:
        display_name = info.name

    analysis = {
        "methodology": gen_methodology_text(info),
        "latest_market": gen_latest_market_text(market, info.name),
        "short_term": gen_short_term_text(short_perf, info.name),
        "long_term": gen_long_term_text(long_perf, info.name),
        "valuation": gen_valuation_text(val, info.name),
        "technical": gen_technical_text(tech),
        "industry": gen_industry_text(industries, info.name),
        "components": gen_components_text(top_comps, total_weight, info.name),
        "fundamental": gen_fundamental_text(fundamentals, info.name),
    }

    template_content = None
    if template_path and os.path.exists(template_path):
        with open(template_path, "r", encoding="utf-8") as f:
            template_content = f.read()

    if template_content:
        html = _render_template(template_content, info, market, short_perf, long_perf,
                                 val, tech, industries, top_comps, total_weight,
                                 kline_chart, fundamentals, analysis,
                                 display_name=display_name, summary=summary)
    else:
        html = _generate_builtin_html(info, market, short_perf, long_perf,
                                       val, tech, industries, top_comps, total_weight,
                                       kline_chart, analysis)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return output_path


def _render_template(
    template: str,
    info: IndexInfo,
    market: LatestMarket,
    short: ShortTermPerformance,
    long: LongTermPerformance,
    val: IndexValuation,
    tech: TechnicalIndicators,
    industries: List[IndustryWeight],
    top_comps: List[ComponentStock],
    total_weight: float,
    kline_chart: Dict[str, Any],
    fundamentals: List[FundamentalQuarter],
    analysis: Dict[str, str],
    display_name: str = "",
    summary: str = ""
) -> str:
    """模板变量替换"""

    industry_labels = json.dumps([w.industry for w in industries], ensure_ascii=False)
    industry_data = json.dumps([w.weight for w in industries], ensure_ascii=False)
    kline_labels = json.dumps(kline_chart.get("labels", []), ensure_ascii=False)
    kline_data = json.dumps(kline_chart.get("data", []), ensure_ascii=False)

    comp_rows = ""
    for c in top_comps:
        rank_class = "top3" if c.rank <= 3 else ""
        comp_rows += (
            f'<tr><td><span class="rank {rank_class}">{c.rank}</span></td>'
            f'<td title="{c.name}">{c.name}</td>'
            f'<td class="mono">{c.code}</td>'
            f'<td title="{c.industry}">{c.industry}</td>'
            f'<td class="mono">{c.weight}%</td></tr>'
        )

    dividend_card = ""
    if val.dividend_yield is not None:
        dividend_card = (
            f'<div class="metric-card"><div class="label">股息率</div>'
            f'<div class="value neutral">{val.dividend_yield}%</div></div>'
        )

    tech_items = ""
    if tech.ma5:
        tech_items += f'<div class="tech-item"><span class="tech-label">MA5</span><span class="tech-value mono">{tech.ma5}</span></div>'
    if tech.ma20:
        tech_items += f'<div class="tech-item"><span class="tech-label">MA20</span><span class="tech-value mono">{tech.ma20}</span></div>'
    if tech.ma60:
        tech_items += f'<div class="tech-item"><span class="tech-label">MA60</span><span class="tech-value mono">{tech.ma60}</span></div>'
    tech_items += f'<div class="tech-item"><span class="tech-label">均线趋势</span><span class="tech-value">{tech.ma_trend}</span></div>'
    tech_items += f'<div class="tech-item"><span class="tech-label">量比(5/20日)</span><span class="tech-value mono">{tech.volume_ratio}</span></div>'
    tech_items += f'<div class="tech-item"><span class="tech-label">近20日涨跌</span><span class="tech-value {_css_class_for_value(tech.return_20d)} mono">{tech.return_20d:+.2f}%</span></div>'

    replacements = {
        "{{REPORT_TITLE}}": f"{display_name or info.name}分析报告",
        "{{DISPLAY_NAME}}": display_name or info.name,
        "{{SUMMARY}}": summary,
        "{{INDEX_NAME}}": info.name,
        "{{INDEX_CODE}}": info.code,
        "{{PUBLISHER}}": info.publisher,
        "{{BASE_DATE}}": info.base_date,
        "{{SAMPLE_SPACE}}": info.sample_space,
        "{{FOCUS_DIRECTION}}": info.focus_direction,
        "{{METHODOLOGY_ANALYSIS}}": analysis["methodology"],

        "{{RETURN_1W}}": f"{market.return_1w:+.2f}",
        "{{RETURN_1W_CLASS}}": _css_class_for_value(market.return_1w),
        "{{RETURN_1M}}": f"{market.return_1m:+.2f}",
        "{{RETURN_1M_CLASS}}": _css_class_for_value(market.return_1m),
        "{{LATEST_MARKET_ANALYSIS}}": analysis["latest_market"],

        "{{RETURN_3M}}": f"{short.return_3m:+.2f}",
        "{{RETURN_3M_CLASS}}": _css_class_for_value(short.return_3m),
        "{{RETURN_1Y}}": f"{short.return_1y:+.2f}",
        "{{RETURN_1Y_CLASS}}": _css_class_for_value(short.return_1y),
        "{{RETURN_YTD}}": f"{short.return_ytd:+.2f}",
        "{{RETURN_YTD_CLASS}}": _css_class_for_value(short.return_ytd),
        "{{MAX_DD_1Y}}": f"{short.max_drawdown_1y:.2f}",
        "{{SHORT_TERM_ANALYSIS}}": analysis["short_term"],

        "{{ANNUAL_RETURN_3Y}}": f"{long.annual_return_3y:+.2f}",
        "{{ANNUAL_RETURN_3Y_CLASS}}": _css_class_for_value(long.annual_return_3y),
        "{{ANNUAL_RETURN_5Y}}": _format_number(long.annual_return_5y, suffix="%"),
        "{{ANNUAL_RETURN_5Y_CLASS}}": _css_class_for_value(long.annual_return_5y or 0),
        "{{SHARPE_RATIO}}": _format_number(long.sharpe_ratio_3y),
        "{{MAX_DD_3Y}}": f"{long.max_drawdown_3y:.2f}",
        "{{LONG_TERM_ANALYSIS}}": analysis["long_term"],

        "{{KLINE_LABELS_JSON}}": kline_labels,
        "{{KLINE_DATA_JSON}}": kline_data,

        "{{FUND_LABELS_JSON}}": json.dumps([f.quarter for f in fundamentals], ensure_ascii=False),
        "{{FUND_REVENUE_JSON}}": json.dumps([round(f.revenue_yoy, 2) for f in fundamentals]),
        "{{FUND_PROFIT_JSON}}": json.dumps([round(f.net_profit_yoy, 2) for f in fundamentals]),
        "{{FUNDAMENTAL_ANALYSIS}}": analysis["fundamental"],

        "{{PE_TTM}}": _format_number(val.pe_ttm),
        "{{PB}}": _format_number(val.pb),
        "{{PE_PERCENTILE}}": _format_number(val.pe_percentile, suffix="%"),
        "{{PERCENTILE_PERIOD}}": val.percentile_period or "近10年",
        "{{DIVIDEND_CARD}}": dividend_card,
        "{{VALUATION_ANALYSIS}}": analysis["valuation"],

        "{{TECH_ITEMS}}": tech_items,
        "{{TECHNICAL_ANALYSIS}}": analysis["technical"],

        "{{INDUSTRY_LABELS_JSON}}": industry_labels,
        "{{INDUSTRY_DATA_JSON}}": industry_data,
        "{{INDUSTRY_ANALYSIS}}": analysis["industry"],

        "{{COMPONENT_ROWS}}": comp_rows,
        "{{TOTAL_WEIGHT}}": f"{total_weight:.2f}",
        "{{COMPONENTS_ANALYSIS}}": analysis["components"],

        "{{GENERATE_TIME}}": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    result = template
    for key, value in replacements.items():
        result = result.replace(key, str(value))

    return result


def _generate_builtin_html(*args, **kwargs):
    """兜底HTML生成（简化版，完整样式以模板为准）"""
    return "<html><body><p>请使用模板文件生成完整报告</p></body></html>"


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="指数分析工具（V2）")
    parser.add_argument("--index", required=True, help="指数名称或代码")
    parser.add_argument("--output", default="report.html", help="输出HTML路径")
    args = parser.parse_args()
    print(f"指数分析工具 V2")
    print(f"目标指数: {args.index}")
    print(f"输出文件: {args.output}")
    print("V2优化：短期/长期表现分离、行情折线图、行业文字自适应、聚焦方向")
