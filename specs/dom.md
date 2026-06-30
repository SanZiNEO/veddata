# dom.py — DOM 扫描模块

## 职责

扫描页面 DOM 结构：交互元素列表、重复容器发现、字段提取。

## 依赖

- DrissionPage `ChromiumTab` 的 `.ele()` / `.eles()` 方法
- 不需要 `lxml` / `BeautifulSoup`（DrissionPage 内置定位能力）

## 参考文档

- [DrissionPage 查找元素](https://www.drissionpage.cn/browser_control/get_elements/intro) — 核心参考
- [定位语法](https://www.drissionpage.cn/browser_control/get_elements/syntax)
- [元素内查找](https://www.drissionpage.cn/browser_control/get_elements/find_in_object)

## 数据结构

```python
elements_cache: list[dict] = []
containers_cache: list[dict] = []

# 元素记录:
{
    "id": 1,
    "tag": "a",
    "text": "减脂餐",
    "href": "/search/...",
    "element_ref": <DrissionPage元素对象>
}

# 容器记录:
{
    "id": 1,
    "selector": ".product-card",
    "count": 20,
    "fields": [
        {"name": "title", "type": "text", "sample": "法式复古连衣裙"},
        {"name": "price", "type": "text", "sample": "¥199"},
    ]
}
```

## 接口

```python
class DOMScanner:
    def __init__(self, tab):
        """绑定到一个 ChromiumTab"""
    
    def list_elements(self) -> str:
        """扫描交互元素 + 容器，返回编号列表文本"""
    
    def click_element(self, index: int) -> str:
        """点击指定元素"""
    
    def find_containers(self) -> str:
        """相似合并：找重复容器"""
    
    def inspect_container(self, index: int) -> str:
        """展开容器内部字段"""
```

## list_elements() 逻辑

参考: https://www.drissionpage.cn/browser_control/get_elements/intro

```python
# 用 DrissionPage 的 eles() 批量查找
# 语法: tag:name=value 或 class 名 或 text 匹配
interactives = tab.eles('tag:a, tag:button, tag:input, tag:select')
clickables = tab.eles('[onclick], [role=button], [role=tab], [role=link]')
```

过滤逻辑:
```
1. 合并交互元素 + 可点击元素
2. 过滤:
   - 隐藏元素 → ele.states.is_displayed == False → 跳过
   - 导航栏 → 父级含 nav/header/footer class → 跳过
   - 无文本 → 跳过
3. 取可见文本（取前 30 字符）
4. 去重（相同 tag+text 只保留一个）
5. 限制返回 30 个
6. 按页面从上到下排序（使用 ele.rect.location）

返回格式:
  [1] a       "减脂餐"       
  [2] button  "视频"         
  [3] div     "综合排序"     
  ...
```

## find_containers() 逻辑

算法:
```
1. 用 tab.eles('css:[class]') 拿所有有 class 的元素
   比全 DOM 递归快得多

2. 对每个元素，取父元素 → 检查其直接子元素是否 ≥3 个 tag+class 相同
   DrissionPage: tab.is_in_element() 或 通过 ele.parent() 获取

3. 评分 = 兄弟数量 × 平均文本长度

4. 按分数降序，取前 5 个

5. 去重嵌套（子容器分数低于外层则跳过）

6. 提取第一个"壳"的内部字段:
   - 取容器内第一个子元素
   - 递归找所有有 class 的叶子元素
   - 字段名 = class 字符串按 space 分割
   - 短名 = class.split('-')[-1] 取最后一段
```

## 字段名推断

```python
def infer_field_name(class_attr):
    """class="video-info-title" → "video-info-title" """
    classes = class_attr.split()
    for cls in classes:
        # 跳过通用类名
        if cls in ('active', 'show', 'hide', 'selected', 'disabled'):
            continue
        return cls
    return "field"
```

## 注意事项

- `tab.eles()` 最多返回数千元素，性能可控
- 容器扫描耗时 > 1 秒时，用一个 `from DrissionPage import Chromium; tab.wait(0.5)` 等待 DOM 稳定
- 字段名冲突：同名 class 在容器内出现多次加序号
- 如果无可见文本，显示 `[无文本]`
