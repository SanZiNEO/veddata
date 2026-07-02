# API 公共池架构改造计划

## 动机

当前架构每个 tab 一个 `NetworkMonitor`，存在三个问题：

1. **API 漏捕获**：一个 tab 的请求可能出现在另一个 tab 的 CDP 事件里，如果归属错了 tab，AI 查 `scout_apis(tab=2)` 可能漏掉本属于自己的 API。
2. **监听冗余**：N 个 tab 开 N 个 `monitor.start()`，每个都在独立 drain CDP 事件队列——同一个数据包可能被多个 monitor 各收一遍。
3. **编号脱钩**：自编号脱离浏览器生命周期，MCP 重启后编号冲突。

## 方案

**一个全局 NetworkPool，全量捕获，按 CDP tab ID 归标签。**

### 数据结构

```python
# state.py
_api_pool: NetworkPool | None = None   # 全局单例，所有 tab 共享
```

```python
# network_pool.py
class NetworkPool:
    api_records: list[dict]   # 所有 tab 的 API 记录合集
                               # 每条记录带 tab_id 字段
    
    def start(self):
        # 全局启动一次 CDP 监听
    
    def step(self, timeout=2.0) -> list:
        # drain CDP 队列 → filter_and_store()
        # 每条数据包按 targetId 自动归标签
    
    def get_by_tab(self, tab_id: str) -> list:
        return [r for r in self.api_records if r["tab_id"] == tab_id]
    
    def prune(self, tab_id: str):
        # tab 关闭时清理该 tab 的记录
```

### 调用链

```
scout_open(url)
  → BrowserSession 开 tab → 取 CDP tab_id
  → pool.start() 启动全局监听（第一次）
  → pool 自动按 targetId 归标签

scout_apis(tab="5F207A")
  → pool.get_by_tab("5F207A")
  → 返回该 tab 的所有 API 记录

scout_apis()  # tab 为空
  → 取当前 tab 的 CDP id → pool.get_by_tab(curr_id)

scout_search("keyword", tab="5F207A")
  → pool.search("keyword", tab_id="5F207A")

scout_inspect(3, tab="5F207A")
  → pool.get_record(3, tab_id="5F207A")
```

### 接口变化

| 工具 | 原来 | 改后 |
|------|------|------|
| `scout_apis` | `tab: int=0` | `tab: str=""`（空=当前 tab） |
| `scout_inspect` | `tab: int=0` | `tab: str=""` |
| `scout_search` | `tab: int=0` | `tab: str=""` |
| `scout_context` | `tab: int=0` | `tab: str=""` |
| `scout_export` | `tab: int=0` | `tab: str=""` |
| `scout_export_all` | `tab: int=0` | `tab: str=""` |
| `scout_tabs` | 整数编号 | CDP tab ID 前 8 位 |
| `scout_tab_switch` | `num: int` | `tab: str` |
| `scout_tab_close` | `tab: int\|None` | `tab: str=""` |

### 去重策略

同一 tab 内同 URL path → 覆盖旧记录（和现在一致）。不同 tab 同 URL path → 各自独立记录。

### 改动文件

| 文件 | 改动 |
|------|------|
| 新建 `src/web_scout/network_pool.py` | `NetworkPool` 类，单例监听 + 归标签 |
| `state.py` | `_api_pool` 替代 `_monitors` |
| `tools/navigate.py` | `open/close/tabs/switch/close` 全用 CDP ID |
| `tools/discover.py` | 6 个 API 工具改 `tab: str=""`，查 pool |
| `tools/act.py` | 从 pool 取数据 |
| `tools/scan.py` | 从 pool 取数据 |
| `tools/observe.py` | 跟踪当前 tab ID |

### 编号完全去除

DOM 不需要全局池（快照本就不跨 tab），但 key 需要和 API pool 对齐：

```python
# state.py — 全用 CDP tab ID
_api_pool: NetworkPool                    # 全局单例
_dom_scanners: dict[str, DOMScanner]      # key = CDP tab_id
_current_tab: str | None = None           # 当前活跃 tab 的 CDP ID
```

`BrowserSession` 同时去除 `_tabs` 字典里的 `num` 字段和 `_next_tab_num` 自增器。`list_tabs()` 直接从浏览器读 `tab_ids` 再取 URL/title。

**所有使用 `tab_num` 的地方迁移为 CDP tab ID：**

| 原来 | 改后 |
|------|------|
| `state.resolve_tab(tab: int)` | `state.resolve_tab(tab: str)` |
| `state.prefix(tab_num: int)` | `state.prefix(tab_id: str)` → `[5F207A] https://...` |
| `_monitors[tab_num]` | `_api_pool.get_by_tab(tab_id)` |
| `_dom_scanners[tab_num]` | `_dom_scanners[tab_id]` |
| `_browser.tab_num()` | `_browser.current_tab_id()` |
| `BrowserSession._tabs[tid]["num"]` | 字段删除 |

### GC 策略

```python
def _gc_pool():
    # 遍历 pool.api_records，移除已关闭 tab 的记录
    dead_tabs = resolve_dead_tab_ids()
    pool.api_records = [r for r in pool.api_records if r["tab_id"] not in dead_tabs]
```

每次 `scout_open` / `scout_tab_close` / `scout_close` 时触发。
