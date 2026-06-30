# monitor.py — 网络监听模块

## 职责

监听浏览器所有 XHR/Fetch 网络请求，过滤 JSON API，存储、去重、查询。

## 依赖

- DrissionPage `ChromiumTab.listen` API（4.1 起原生支持）
- 不需要 `requests` 库

## 参考文档

- [DrissionPage 监听网络数据完整文档](https://www.drissionpage.cn/browser_control/listener) — 核心参考
- [XhsCrawler test_comment_page.py](../../../TEST/test_comment_page.py) — xhshow 签名 + requests.Session 发请求示例

## 数据结构

```python
api_records: list[dict] = []

# 每条记录格式:
{
    "id": 1,                   # 编号（从 1 开始）
    "url": "https://...",      # 完整 URL
    "path": "/api/search",     # URL path 部分（？之前）
    "method": "GET" | "POST",  # 请求方法
    "count": 2,                # 同一 path+method 的请求次数
    "request_headers": {},     # 最近一次请求的 headers
    "request_body": {},        # 最近一次请求的 body（POST）
    "request_params": {},      # 最近一次请求的 query params（GET）
    "response_status": 200,    # 最近一次响应状态码
    "response_body": {},       # 最近一次响应 JSON body
    "field_count": 20,         # 响应中叶子字段数量
}
```

## 接口

```python
class NetworkMonitor:
    def __init__(self, tab):
        """绑定到一个 ChromiumTab"""
    
    def start(self):
        """开始监听。tab.listen.start()"""
    
    def stop(self):
        """停止监听"""
    
    def step(self, timeout: float = 2.0) -> list:
        """步进获取新数据包。调用 tab.listen.steps(timeout=2, gap=5) → 一次返回多个数据包"""
    
    def filter_and_store(self, packet) -> bool:
        """判断是否 JSON API → 存储或更新记录。返回 True 表示是 JSON API"""
    
    def list_apis(self) -> str:
        """列出 API。返回编号+URL+字段数的文本"""
    
    def get_api(self, api_id: int) -> str:
        """获取指定 API 的完整请求+响应详情文本"""
```

## start() 逻辑

参考: https://www.drissionpage.cn/browser_control/listener#listenstart

```python
def start(self):
    # 监听所有 URL 的 GET 和 POST 请求
    self.tab.listen.start()
    # 或指定 URL 模式: self.tab.listen.start('api')
```

## step() — 关键改动

不同于之前设想的 `wait_new()`，应改用 `steps()` 实时获取，更灵活：

```python
def step(self, timeout=2.0):
    """
    步进获取数据包。用 tab.listen.steps() 实时取数据包。
    gap=5 表示每捕获 5 个请求才返回一次，减少轮询开销
    """
    new_packets = []
    for packet in self.tab.listen.steps(timeout=timeout, gap=5):
        if self.filter_and_store(packet):
            new_packets.append(packet)
    return new_packets
```

参考: https://www.drissionpage.cn/browser_control/listener#listensteps

## filter_and_store() 逻辑

DataPacket 对象结构参考: https://www.drissionpage.cn/browser_control/listener#datapacket

```
1. 从 packet 获取:
   - packet.url → 完整 URL
   - packet.method → 'GET' 或 'POST'
   - packet.request.headers → 请求头（CaseInsensitiveDict）
   - packet.request.params → GET 的 query 参数（dict）
   - packet.request.postData → POST 的 body（str 或 dict）
   - packet.response.status → 状态码
   - packet.response.headers → 响应头
   - packet.response.body → 响应体（JSON 自动转为 dict）
   - packet.resourceType → 'XHR' 或 'Fetch'

2. 检查:
   - packet.response.headers['content-type'] 是否含 'application/json'
   - 不含 → return False
   - 请求失败 (packet.is_failed == True) → return False

3. 检查 body 类型:
   - 已是 dict → 直接用
   - 是 str → 尝试 json.loads()
   - 解析失败 → return False

4. 提取 path = url.split('?')[0]
   如: https://edith.xiaohongshu.com/api/sns/web/v2/comment/page?note_id=xxx
   → path = "https://edith.xiaohongshu.com/api/sns/web/v2/comment/page"
   → 短名 = "/api/sns/web/v2/comment/page"

5. 查找去重: 是否已有同 path+method 的记录
   - 有 → count += 1，更新最近一次数据
   - 无 → 创建新记录，分配 id

6. 计算 field_count（递归统计叶子字段数）

7. return True
```

## list_apis() 逻辑

```
返回格式（文本）:
  [1] POST /api/sns/web/v1/search/notes  2 次 → 20 fields
  [2] GET  /api/sns/web/v2/comment/page   1 次 → 15 fields

实现:
  遍历 api_records → 格式化为字符串
```

## get_api() 逻辑

```
返回格式（文本）:
  === 请求 ===
  URL: https://edith.xiaohongshu.com/api/search/notes
  Method: POST
  Headers: (关键 headers)
    Content-Type: application/json
    Referer: https://www.xiaohongshu.com/
    Cookie: a1=abc...xyz; web_session=def...uvw

  Body:
    {"keyword": "减脂餐", "page": 1, "page_size": 20}

  === 响应 ===
  Status: 200
  Body（前 2000 字符）:
    {"code": 0, "data": {"items": [...]}}
```

注意事项:
- Cookie 值截断处理（>30 字符取前后各 15）
- JSON body 格式化（json.dumps(indent=2)）
- 响应体截断到 2000 字符

## 注意事项

- 监听需在 `tab.get()` **之前** start，否则之前的请求漏掉
  参考: https://www.drissionpage.cn/browser_control/listener 开头的注意事项
- `listen.stop()` 清空队列但不影响已存储的记录
- `listen.start()` 在监听未停止时调用会清空队列，不要重复调
- packet.request.headers 是 `CaseInsensitiveDict`，访问时大小写不敏感
- 响应 body 可能很大，存储时做截断（5000 字符）
