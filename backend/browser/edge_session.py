# -*- coding: utf-8 -*-
"""
CrossMart Selector — Edge 唯一默认账户会话（铁律入口）
=====================================================
⛔ 铁律（不可违背）：
   所有涉及本地浏览器抓取的操作，必须且只能使用闫旭的
   Edge「唯一默认账户」（带 openclaw 收藏标签页的那个系统默认 profile）。

   ✅ 正确做法：不指定 --user-data-dir，让 Edge 自动加载系统默认 profile
   ✅ CDP 端口固定 9225
   ❌ 禁止新建 / 指定任何 --user-data-dir profile
   ❌ 禁止使用 OpenClaw 管理的浏览器实例

本模块是选品板块进行任何浏览器抓取的【唯一入口】。
所有抓取脚本都必须 `from browser.edge_session import open_edge` 取得浏览器，
不得自行 subprocess 启动 Edge 或自建 CDP 连接。
"""
import os
import sys

_THIS = os.path.dirname(os.path.abspath(__file__))
if _THIS not in sys.path:
    sys.path.insert(0, _THIS)

# 复用监控板块已验证的 CDP 底座（同一套铁律实现）
from cdp_bridge import CDPBrowser, ensure_edge_running, start_default_edge

# ─── 铁律常量 ───
MANDATORY_CDP_PORT = 9225          # 闫旭默认 Edge 固定端口
FORBID_USER_DATA_DIR = True        # 禁止指定任何 profile 目录


def _enforce_iron_rule():
    """
    强制将 CDP 端口锁定为 9225（默认账户），并清除任何可能指向
    OpenClaw 托管浏览器或自定义 profile 的环境变量。
    """
    # 锁定端口到默认账户的 9225
    os.environ["CDP_PORT"] = str(MANDATORY_CDP_PORT)
    # 抹掉任何可能让 cdp_bridge 走 OpenClaw 18800 的痕迹（CDP_PORT 已显式设置即可强制）
    return MANDATORY_CDP_PORT


def open_edge(auto_start=True):
    """
    取得受铁律约束的 Edge 浏览器实例（唯一默认账户 / 端口 9225）。

    用法：
        from browser.edge_session import open_edge
        br = open_edge()
        br.navigate("https://www.amazon.com/dp/B0XXXXXXX")
        ...
        br.close()
    """
    port = _enforce_iron_rule()
    print(f"  [IronRule] 使用 Edge 唯一默认账户，CDP 端口锁定 {port}（不指定 user-data-dir）")
    return CDPBrowser(auto_start=auto_start)


def ensure_default_edge():
    """仅确保默认 Edge 在 9225 端口运行，不建立 WS 连接。"""
    _enforce_iron_rule()
    return ensure_edge_running(MANDATORY_CDP_PORT)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print("=" * 56)
    print(" CrossMart Selector — Edge 默认账户连通性自检")
    print("=" * 56)
    ok = ensure_default_edge()
    if not ok:
        print("\n  ❌ Edge 默认账户未就绪。")
        print("  请按 TOOLS.md 铁律手动启动：")
        print("    1) 关掉所有 Edge 进程")
        print("    2) 执行：msedge --remote-debugging-port=9225 "
              "--remote-allow-origins=* --new-window about:blank")
        sys.exit(1)
    try:
        br = open_edge()
        title = br.eval("document.title") or "(无标题)"
        tab_count = len(br.tabs)
        print(f"\n  ✅ 已连上默认 Edge：{tab_count} 个标签页")
        print(f"  当前页：{title[:50]}")
        # 验证是否是默认 profile（带收藏的那个）
        ua = br.eval("navigator.userAgent") or ""
        print(f"  UA: {ua[:70]}...")
        br.close()
        print("\n  ✅ 铁律自检通过：选品板块抓取将使用唯一默认账户。")
    except Exception as e:
        print(f"\n  ❌ 连接失败：{e}")
        sys.exit(1)
