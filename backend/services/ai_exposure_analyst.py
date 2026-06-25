"""v1.0 AI Exposure Analyst — AI-powered theme classification and overlap analysis."""
import json, hashlib
from datetime import datetime
from services.ai_provider_deepseek import chat_completion, API_KEY

_PROMPT_TEMPLATE = """You are a fund exposure analyst. Analyze this fund's holdings and classify its primary theme.

Fund: {fund_name} ({fund_code})
Top 10 Holdings: {top10}
Industry Distribution: {industry}
Portfolio Context: {context}

Return valid JSON only:
{{
  "primary_theme": "one of: 消费/医药/科技/金融/新能源/军工/制造/混合/其他",
  "secondary_themes": ["..."],
  "theme_bucket": "消费/医药/科技/金融/新能源/军工/制造/混合/其他",
  "overlap_summary": "brief English summary of overlap risk with portfolio",
  "overlap_level": "low/medium/high",
  "confidence": "low/medium/high",
  "evidence": ["fact1", "fact2"],
  "uncertainty": ["gap1"],
  "human_review_required": true/false
}}"""


def analyze_fund_exposure(fund_data: dict, portfolio_context: str = "") -> dict:
    """AI exposure analysis. Falls back to local_rule on failure."""
    prompt = _PROMPT_TEMPLATE.format(
        fund_name=fund_data.get("fund_name", "Unknown"),
        fund_code=fund_data.get("fund_code", ""),
        top10=json.dumps(fund_data.get("top10", []), ensure_ascii=False)[:1000],
        industry=json.dumps(fund_data.get("industry_distribution", {}))[:500],
        context=portfolio_context[:500],
    )
    messages = [
        {"role": "system", "content": "You are a professional fund exposure analyst. Output JSON only."},
        {"role": "user", "content": prompt},
    ]
    prompt_hash = hashlib.md5(prompt.encode()).hexdigest()[:12]
    input_hash = hashlib.md5(json.dumps(fund_data, sort_keys=True, default=str).encode()).hexdigest()[:12]

    if not API_KEY:
        fb = _fallback("DEEPSEEK_API_KEY not set")
        fb["prompt_hash"] = prompt_hash
        fb["input_hash"] = input_hash
        return fb

    try:
        result = chat_completion(messages, json_mode=True)
        result["classification_source"] = "ai"
        result["model_name"] = "deepseek-v4-pro"
        result["model_version"] = "1.0"
        result["prompt_hash"] = prompt_hash
        result["input_hash"] = input_hash
        return result
    except Exception as e:
        fb = _fallback(str(e)[:200])
        fb["prompt_hash"] = prompt_hash
        fb["input_hash"] = input_hash
        return fb


def _fallback(reason: str = "") -> dict:
    return {
        "primary_theme": "未分类",
        "secondary_themes": [],
        "theme_bucket": "未分类",
        "overlap_summary": f"AI analysis failed, fallback to local_rule",
        "overlap_level": "unknown",
        "confidence": "low",
        "evidence": [],
        "uncertainty": [f"AI fallback: {reason}"],
        "human_review_required": True,
        "classification_source": "local_rule",
        "model_name": "fallback",
        "prompt_hash": "",
        "input_hash": "",
    }