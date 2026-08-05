from __future__ import annotations

PROHIBITED_PHRASES = [
    "满仓",
    "梭哈",
    "必涨",
    "稳赚",
    "抄底",
    "逃顶",
    "内幕",
    "庄家",
    "主力吸筹",
    "主力出货",
    "明天一定上涨",
    "强烈买入",
    "强烈卖出",
]

REQUIRED_HEADINGS = [
    "报告状态与数据源",
    "今日市场基础状态",
    "可识别资金证据总览",
    "参与者与对手关系",
    "路径假设与历史条件概率",
    "字段级数据来源",
    "后续确认条件",
    "可证伪清单",
    "风险与限制声明",
]


def validate_report(text: str) -> list[str]:
    errors: list[str] = []
    for phrase in PROHIBITED_PHRASES:
        if phrase in text:
            errors.append(f"包含禁用表达：{phrase}")
    for heading in REQUIRED_HEADINGS:
        if heading not in text:
            errors.append(f"缺少必备章节：{heading}")
    if "不构成投资建议" not in text:
        errors.append("缺少风险声明")
    if "替代解释" not in text:
        errors.append("缺少替代解释")
    if "样本不足时不显示概率" not in text:
        errors.append("缺少历史概率样本门槛说明")
    return errors
