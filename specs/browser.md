# browser.py — 浏览器模块

## 职责

管理 Chromium 浏览器生命周期，提供页面导航和文本提取。

## 依赖

- DrissionPage >= 4.1（使用 `Chromium` + `ChromiumOptions`，不是 `ChromiumPage`）

## 参考文档

- [DrissionPage 浏览器控制概述](https://www.drissionpage.cn/browser_control/intro)
- [获取网页信息](https://www.drissionpage.cn/browser_control/get_page_info)
- [XhsCrawler 参考代码](../../../xhs_crawler/src/cookies/acquirer.py) — 浏览器启动 + 登录检测
- [XhsCrawler 配置参考](../../../xhs_crawler/src/config.py) — 环境变量模式

## 接口

```python
class BrowserSession:
    def __init__(self):
        """启动浏览器。读取环境变量 HEADLESS / BROWSER_PATH / USER_DATA_DIR"""
    
    def open(self, url: str) -> dict:
        """打开 URL，返回 {title, text, api_count, is_login_required}"""
    
    def get_text(self) -> str:
        """获取当前页面的全文 Markdown"""
    
    def close(self):
        """关闭浏览器"""
```

## 启动逻辑

```python
from DrissionPage import Chromium, ChromiumOptions
import os

co = ChromiumOptions()
co.auto_port(True)                          # 自动端口

if os.environ.get("HEADLESS", "false") == "true":
    co.headless(True)

browser_path = os.environ.get("BROWSER_PATH", "")
if browser_path == "edge":
    co.set_browser_path(edge=True)
elif browser_path:
    co.set_browser_path(browser_path)

user_data = os.environ.get("USER_DATA_DIR", "")
if user_data:
    co.set_user_data_path(user_data)

browser = Chromium(co)
tab = browser.latest_tab
```

参考：[DrissionPage 连接浏览器](https://www.drissionpage.cn/browser_control/connect_browser)、[浏览器启动设置](https://www.drissionpage.cn/browser_control/browser_options)、XhsCrawler `acquirer.py:38-44`

## open(url) 逻辑

```
1. tab.get(url) → 返回 NavResult 对象（DrissionPage 4.2+）
   参考: https://www.drissionpage.cn/browser_control/visit

2. 检查打开结果:
   - 4.2+: result.status / result.url
   - 4.1: 通过 tab.url 和 tab.html 判断

3. 提取 title: tab.title
   参考: https://www.drissionpage.cn/browser_control/get_page_info

4. 提取 text: 调 get_text()

5. 返回 {title, text, api_count, is_login_required}
```

## get_text() 逻辑

```
1. 拿到完整 HTML: tab.html
   参考: https://www.drissionpage.cn/browser_control/get_page_info#html

2. 用正则去掉以下标签及其内容:
   - <script>...</script>
   - <style>...</style>
   - <nav>...</nav>   
   - <header>...</header>
   - <footer>...</footer>
   - <noscript>...</noscript>
   - SVG 全部

3. 去掉所有 HTML 标签，保留纯文本: re.sub(r'<[^>]+>', '', html)

4. re.sub(r'\n\s*\n', '\n', text) 去掉连续空白行

5. 截断到 3000 字符

6. 返回纯文本
```

简化替代方案：`pip install html2text` → `html2text.html2text(tab.html)[:3000]`

## 注意事项

- 浏览器对象全局复用，不要每次工具调用都新开
- `tab.get()` 默认超时 30 秒，可在 ChromiumOptions 设 `set_timeouts(page_load=30)`
  参考: https://www.drissionpage.cn/browser_control/browser_options#set_timeouts
- 不要用 `ChromiumPage`，用 `Chromium() + tab`
  参考: https://www.drissionpage.cn/browser_control/intro — 4.2 起 ChromiumPage 标记废弃
- `tab.html` 不包含 iframe 内容 (DrissionPage 官方文档)
