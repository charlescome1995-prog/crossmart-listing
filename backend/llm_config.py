"""
LLM 客户端配置 - 火山引擎 Ark Coding Plan
==========================================

使用前请在环境变量里设置 ARK_API_KEY (火山方舟 Coding Plan 的 API Key)。

    Windows PowerShell:
        $env:ARK_API_KEY = "ark-c10942f0-5175-4dbb-afa9-2fde3cade1d3-f42a9"

    Windows CMD:
        set ARK_API_KEY=ark-c10942f0-5175-4dbb-afa9-2fde3cade1d3-f42a9

提供两类接口（与官方文档一致）:
    - Anthropic 协议: https://ark.cn-beijing.volces.com/api/coding
    - OpenAI 协议:   https://ark.cn-beijing.volces.com/api/coding/v3
"""

import os

# ── Provider 元信息 ─────────────────────────────────────
PROVIDER_NAME = "volcengine-ark"
PROVIDER_LABEL = "火山方舟 Coding Plan (Volcengine Ark)"

# ── Base URL ────────────────────────────────────────────
# Anthropic 协议工具 (Claude Code, Cursor, Cline 等)
ANTHROPIC_BASE_URL = "https://ark.cn-beijing.volces.com/api/coding"
# OpenAI 协议工具 (OpenAI SDK, LangChain 等)
OPENAI_BASE_URL = "https://ark.cn-beijing.volces.com/api/coding/v3"

# ── 模型 ────────────────────────────────────────────────
# 文本对话模型（coding plan 默认）
CHAT_MODEL = "ark-code-latest"
# 视觉/Embedding（仅 v3 OpenAI 协议支持）
EMBEDDING_MODEL = "doubao-embedding-vision"

# ── API Key（从环境变量读取，不在源码中硬编码）────────
API_KEY = os.environ.get("ARK_API_KEY", "").strip()


def is_configured() -> bool:
    """检查是否已配置 API Key。"""
    return bool(API_KEY)


def get_anthropic_client_kwargs() -> dict:
    """供 anthropic SDK 使用的连接参数。"""
    return {
        "base_url": ANTHROPIC_BASE_URL,
        "api_key": API_KEY,
    }


def get_openai_client_kwargs() -> dict:
    """供 openai SDK 使用的连接参数。"""
    return {
        "base_url": OPENAI_BASE_URL,
        "api_key": API_KEY,
    }


if __name__ == "__main__":
    # 快速诊断脚本：python llm_config.py
    print(f"Provider:      {PROVIDER_NAME} ({PROVIDER_LABEL})")
    print(f"Anthropic URL: {ANTHROPIC_BASE_URL}")
    print(f"OpenAI URL:    {OPENAI_BASE_URL}")
    print(f"Chat model:    {CHAT_MODEL}")
    print(f"Embedding:     {EMBEDDING_MODEL}")
    print(f"API Key set:   {'YES' if is_configured() else 'NO  (set $env:ARK_API_KEY)'}")
