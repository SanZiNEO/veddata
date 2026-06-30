# login.py — 登录检测模块

## 职责

检测页面是否需要登录，等待用户手动登录完成，处理验证弹窗。

## 依赖

- DrissionPage `ChromiumTab`
- 无额外库

## 参考代码

- **XhsCrawler `acquirer.py`** — 完整的登录检测 + 验证弹窗处理逻辑，直接复用核心代码
- [DrissionPage 访问网页](https://www.drissionpage.cn/browser_control/visit)

## 接口

```python
class LoginDetector:
    def __init__(self, tab):
        """绑定到一个 ChromiumTab"""
    
    def is_login_required(self) -> bool:
        """检测当前页面是否需要登录"""
    
    def wait_for_login(self, timeout: int = 300) -> bool:
        """等待用户手动登录完成。返回 True=成功, False=超时"""
```

## is_login_required() 逻辑

参考: XhsCrawler `acquirer.py:46-50` 的 URL 检测逻辑

```
1. 检查 URL:
   - tab.url 含 '/login' → True
   - tab.url 含 '/signin' → True
   - tab.url 含 '/auth' → True

2. 检查页面文本（从 browser.get_text() 获取）:
   - '请登录' 出现 ≥2 次 → True
   - '立即登录' 出现 → True
   - '扫码登录' 出现 → True

3. 都未命中 → False
```

## wait_for_login() 逻辑

**直接参考 XhsCrawler `acquirer.py:50-69` 的登录轮询逻辑:**

```python
def wait_for_login(self, timeout=300):
    check_interval = 1.0
    elapsed = 0.0
    
    while elapsed < timeout:
        time.sleep(check_interval)
        elapsed += check_interval
        current_url = self.tab.url
        
        # URL 不再含 /login → 登录成功
        if '/login' not in current_url and '/signin' not in current_url:
            print(f'检测到登录成功，当前页面: {current_url}')
            break
        
        if elapsed % 30 < check_interval:
            print(f'  等待登录中... ({int(elapsed)}秒)')
    else:
        return False  # 超时
    
    # === 登录成功后的处理（参考 acquirer.py:85-91 的 VERIFY_SELECTORS） ===
    
    # 1. 检测验证弹窗
    VERIFY_SELECTORS = [
        '.nc_wrapper',           # 阿里云 WAF 滑块
        'text=安全验证',          # 图片选择验证
        'text=请通过验证',        # 通用验证提示
    ]
    
    while True:
        triggered = False
        for sel in VERIFY_SELECTORS:
            el = self.tab.ele(sel, timeout=1)
            if el:
                triggered = True
                break
        if not triggered:
            break
        print('检测到安全验证弹窗，请在浏览器中手动完成验证...')
        time.sleep(2)
    
    # 2. 等待 cookie 写入
    time.sleep(3)
    
    # 3. 刷新页面
    self.tab.get(self.tab.url)
    
    return True
```

## 注意事项

- 参考代码路径: `E:\Documents\GitHub\XhsCrawler\xhs_crawler\src\cookies\acquirer.py`
- 核心逻辑已在 XhsCrawler 中经过 30 万评论的实战验证
- `tab.url` 获取当前 URL 即可，不需要 `tab.get()`
- 登录超时后不关闭浏览器
- 验证弹窗 `.nc_wrapper` 是阿里云 WAF 的滑块组件，`text=安全验证` 是小程序图片选择验证
