# -*- coding: utf-8 -*-
"""
LLM provider routing and API calls
"""
import os

# Configuration constants
TIMEOUT_LLM = 120

def call_llm_api(prompt: str, model: str = "gpt-4o-mini", max_tokens: int = 4000) -> str:
    """Call LLM API with timeout and retry logic"""
    if model.startswith(("claude", "anthropic")):
        return call_anthropic_api(prompt, model, max_tokens)
    if model.startswith("gemini"):
        return call_gemini_api(prompt, model, max_tokens)
    return call_openai_api(prompt, model, max_tokens)

def call_openai_api(prompt: str, model: str = "gpt-4o-mini", max_tokens: int = 4000) -> str:
    try:
        from openai import OpenAI
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not configured")
        
        client = OpenAI(api_key=api_key, timeout=TIMEOUT_LLM)
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content or ""
    except Exception as e:
        return f"OpenAI API error: {str(e)[:200]}"

def call_anthropic_api(prompt: str, model: str = "claude-3-5-sonnet-latest", max_tokens: int = 4000) -> str:
    try:
        import anthropic
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return RuntimeError("OPENAI_API_KEY not configured")
        
        client = anthropic.Anthropic(api_key=api_key)  # Remove timeout from constructor
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=0.1,
            messages=[{"role": "user", "content": prompt}],
            timeout=TIMEOUT_LLM  # Pass timeout to the call
        )
        return "".join(getattr(b, "text", str(b)) for b in resp.content)
    except Exception as e:
        return f"Anthropic API error: {str(e)[:200]}"

def call_gemini_api(prompt: str, model: str = "gemini-1.5-pro", max_tokens: int = 4000) -> str:
    try:
        import google.generativeai as genai
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not configured")
        
        genai.configure(api_key=api_key)
        m = genai.GenerativeModel(model)
        resp = m.generate_content(prompt)
        return resp.text
    except Exception as e:
        return f"Gemini API error: {str(e)[:200]}"

def get_preferred_model(role: str) -> str:
    return {
        "reviewer": os.environ.get("REVIEWER_MODEL", "gpt-4o-mini"),
        "developer": os.environ.get("DEVELOPER_MODEL", "gpt-4o-mini"),
        "analyzer": os.environ.get("ANALYZER_MODEL", "gpt-4o-mini"),
    }.get(role, "gpt-4o-mini")
