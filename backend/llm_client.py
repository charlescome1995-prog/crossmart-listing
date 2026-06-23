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


# ── 图像生成（Seedream 4.0，标准 ark v3 端点）──
def gen_image(prompt: str, size: str = "1024x1024", model: str = None,
              timeout: int = 60) -> str:
    """调用火山方舟 Seedream 文生图，返回图片 URL。

    Args:
        prompt: 英文画面描述
        size: 尺寸，如 1024x1024 / 2048x2048 / 1024x1536
        model: 模型名（默认 llm_config.IMAGE_MODEL）
    Returns:
        图片 URL（临时，需及时下载）；失败抛出异常
    """
    if not llm_config.is_configured():
        raise RuntimeError("ARK_API_KEY 未设置。")
    import json as _json, urllib.request, urllib.error
    body = _json.dumps({
        "model": model or llm_config.IMAGE_MODEL,
        "prompt": prompt,
        "size": size,
        "n": 1,
    }).encode("utf-8")
    req = urllib.request.Request(
        llm_config.IMAGE_API_URL, data=body, method="POST",
        headers={"Authorization": f"Bearer {llm_config.API_KEY}",
                 "Content-Type": "application/json"})
    resp = urllib.request.urlopen(req, timeout=timeout)
    data = _json.loads(resp.read().decode("utf-8"))
    items = data.get("data") or []
    if not items:
        raise RuntimeError(f"图像生成返回空：{str(data)[:200]}")
    return items[0].get("url") or items[0].get("b64_json", "")


def download_image(url: str, dest_path: str, timeout: int = 60) -> str:
    """下载图片 URL 到本地（Seedream 返回的 URL 有时效，必须及时落盘）。"""
    import urllib.request, os as _os
    _os.makedirs(_os.path.dirname(dest_path), exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    with open(dest_path, "wb") as f:
        f.write(data)
    return dest_path


if __name__ == "__main__":
    # 快速连通性测试
    import sys
    try:
        reply = chat_openai("说'pong'回复", max_tokens=20)
        print("✅ OpenAI 协议连通:", reply)
    except Exception as e:
        print("❌ OpenAI 协议失败:", e, file=sys.stderr)
        sys.exit(1)
