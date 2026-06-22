"""
轻量 LLM 调用封装 - 火山方舟 Coding Plan
==========================================

两种调用方式（取决于你需要的协议）:

# 方式 1: OpenAI 协议（推荐, 简单）
from llm_client import chat_openai
reply = chat_openai("用一句话总结亚马逊 ASIN 监控的核心指标")
print(reply)

# 方式 2: Anthropic 协议
from llm_client import chat_anthropic
reply = chat_anthropic("用一句话总结亚马逊 ASIN 监控的核心指标")
print(reply)

依赖安装:
    pip install openai anthropic
"""

import llm_config


# ── OpenAI 协议 ─────────────────────────────────────────
def chat_openai(prompt: str, system: str = "", model: str = None,
                max_tokens: int = 1024, temperature: float = 0.3) -> str:
    """
    通过 OpenAI 协议调用火山方舟 Coding Plan。

    Args:
        prompt: 用户输入
        system: 系统提示词（可选）
        model: 模型名（默认 llm_config.CHAT_MODEL）
        max_tokens: 最大输出 token
        temperature: 0-1, 越低越确定

    Returns:
        模型回复文本
    """
    if not llm_config.is_configured():
        raise RuntimeError("ARK_API_KEY 未设置。请先在环境变量里设置后再调用。")

    from openai import OpenAI

    client = OpenAI(**llm_config.get_openai_client_kwargs())

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    resp = client.chat.completions.create(
        model=model or llm_config.CHAT_MODEL,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return resp.choices[0].message.content or ""


# ── Anthropic 协议 ──────────────────────────────────────
def chat_anthropic(prompt: str, system: str = "", model: str = None,
                   max_tokens: int = 1024, temperature: float = 0.3) -> str:
    """
    通过 Anthropic 协议调用火山方舟 Coding Plan。
    """
    if not llm_config.is_configured():
        raise RuntimeError("ARK_API_KEY 未设置。请先在环境变量里设置后再调用。")

    import anthropic

    client = anthropic.Anthropic(**llm_config.get_anthropic_client_kwargs())

    kwargs = {
        "model": model or llm_config.CHAT_MODEL,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        kwargs["system"] = system

    resp = client.messages.create(**kwargs)
    # content 是 list[TextBlock], 取首段
    if resp.content and hasattr(resp.content[0], "text"):
        return resp.content[0].text
    return str(resp.content)


# ── Embedding（仅 v3 OpenAI 协议）─────────────────────
def embed(text: str, model: str = None) -> list:
    """
    文本向量化 (doubao-embedding-vision)。
    返回 list[float]。
    """
    if not llm_config.is_configured():
        raise RuntimeError("ARK_API_KEY 未设置。")

    from openai import OpenAI

    client = OpenAI(**llm_config.get_openai_client_kwargs())
    resp = client.embeddings.create(
        model=model or llm_config.EMBEDDING_MODEL,
        input=text,
    )
    return resp.data[0].embedding


if __name__ == "__main__":
    # 快速连通性测试
    import sys
    try:
        reply = chat_openai("说'pong'回复", max_tokens=20)
        print("✅ OpenAI 协议连通:", reply)
    except Exception as e:
        print("❌ OpenAI 协议失败:", e, file=sys.stderr)
        sys.exit(1)
