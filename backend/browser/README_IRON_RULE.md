# 🔥 铁律：浏览器抓取只用 Edge 唯一默认账户

> 选品板块（crossmart-selector）所有涉及本地浏览器抓取的操作，**必须且只能**
> 使用闫旭的 Edge「唯一默认账户」——就是那个带 **openclaw 收藏标签页** 的系统默认 profile。

## 规则

| ✅ 必须 | ❌ 禁止 |
|--------|--------|
| 不指定 `--user-data-dir`，让 Edge 自动加载系统默认 profile | 新建或指定任何 `--user-data-dir` profile |
| CDP 端口固定 **9225** | 使用 OpenClaw 托管的浏览器实例（18800/18802） |
| 所有抓取都开新标签页，复用同一个 Edge 实例 | 自行 `subprocess` 启动 Edge / 自建 CDP 连接 |

## 唯一入口

任何抓取脚本都必须通过 `browser/edge_session.py` 取得浏览器：

```python
from browser.edge_session import open_edge

br = open_edge()              # 自动锁定端口 9225 + 默认 profile
br.navigate("https://www.amazon.com/dp/B0XXXXXXX")
# ... 抓取 ...
br.close()
```

不允许直接 `import cdp_bridge` 然后自己 `CDPBrowser()`，因为那样可能漏掉端口锁定。
`edge_session.open_edge()` 内部会强制 `os.environ["CDP_PORT"]="9225"`，杜绝走错实例。

## 手动启动 Edge（首次/重启后）

```
1) 关掉所有 Edge 进程
2) 执行：
   msedge --remote-debugging-port=9225 --remote-allow-origins=* --new-window about:blank
   （不指定 --user-data-dir，让 Edge 自动用系统默认 profile）
```

## 自检

```
python backend\browser\edge_session.py
```

输出里能看到标签页里有 `OpenClaw Control`，即确认连的是带 openclaw 标签页的默认账户。
