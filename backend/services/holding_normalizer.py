"""v1.1 Holding Normalizer — unify stock names across data sources."""
import re

_STOCK_ALIASES = {
    "贵州茅台": ["贵州茅台","贵州茅台股份有限公司","kweichow moutai","Kweichow Moutai","MOUTAI"],
    "五粮液": ["五粮液","五粮液股份有限公司","宜宾五粮液"],
    "泸州老窖": ["泸州老窖","泸州老窖股份有限公司"],
    "美的集团": ["美的集团","美的集团股份有限公司","美的"],
    "格力电器": ["格力电器","格力电器股份有限公司","格力"],
    "招商银行": ["招商银行","招商银行股份有限公司","招行"],
    "中国平安": ["中国平安","中国平安保险","平安"],
    "比亚迪": ["比亚迪","比亚迪股份有限公司"],
    "宁德时代": ["宁德时代","宁德时代新能源","CATL"],
    "海天味业": ["海天味业","海天"],
    "伊利股份": ["伊利股份","伊利"],
    "迈瑞医疗": ["迈瑞医疗"],
    "恒瑞医药": ["恒瑞医药"],
    "药明康德": ["药明康德"],
    "爱尔眼科": ["爱尔眼科"],
    "腾讯控股": ["腾讯控股","腾讯","Tencent"],
    "万科A": ["万科A","万科"],
}

_STOCK_TO_NAME = {}
for canonical, aliases in _STOCK_ALIASES.items():
    for a in aliases:
        _STOCK_TO_NAME[a.lower()] = canonical


def normalize_stock_name(name: str) -> str:
    """Return canonical stock name, or cleaned original."""
    if not name: return ""
    clean = re.sub(r"[（(].*?[)）]", "", name).strip()
    lowered = clean.lower()
    if lowered in _STOCK_TO_NAME:
        return _STOCK_TO_NAME[lowered]
    # Fuzzy match: check if any alias is contained
    for alias, canonical in _STOCK_TO_NAME.items():
        if alias in lowered:
            return canonical
    return clean


def normalize_holding(holding: dict) -> dict:
    """Add normalized_name to a holding dict."""
    name = holding.get("name", holding.get("stock_name", ""))
    return {**holding, "name": name, "normalized_name": normalize_stock_name(name)}


def normalize_top10(top10: list) -> list:
    """Normalize all holdings in a top10 list."""
    return [normalize_holding(h) for h in top10] if top10 else []
