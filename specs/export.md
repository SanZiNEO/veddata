# export.py — 导出模块

## 职责

JSON 响应压缩、字段文档生成、原始数据包保存。

## 依赖

- 纯标准库（`json`, `os`, `re`）
- 无外部依赖

## 参考

- [Python json 模块文档](https://docs.python.org/3/library/json.html)
- [XhsCrawler response/ 目录](../../../response/comment.json) — 参考真实 API 响应结构
- [XhsCrawler response/字段说明.md](../../../response/字段说明.md) — 参考字段文档输出格式

## 接口

```python
class Exporter:
    def __init__(self, response_dir: str = "./response"):
        """response_dir: 原始数据包保存目录"""
    
    def export(self, api_record: dict, format: str = "both") -> str:
        """
        导出 API 数据源。
        format: "raw" | "compact" | "both"
        返回结果文本
        """
    
    def save_raw(self, api_record: dict) -> str:
        """保存原始 JSON 到文件，返回文件路径"""
    
    def compact(self, api_record: dict) -> str:
        """生成压缩字段文档，返回文本"""
```

## compact() 核心算法

```python
def compact(self, api_record: dict) -> str:
    body = api_record["response_body"]
    lines = []
    
    # R1: 顶层元信息
    for k in ("code", "success", "msg"):
        if k in body:
            lines.append(f"{k}: {body[k]}")
    lines.append("")
    
    # R2: data 级标量
    data = body.get("data", body)
    if isinstance(data, dict):
        for k, v in data.items():
            if not isinstance(v, (list, dict)):
                lines.append(f"data.{k}: {v}")
        lines.append("")
    
    # R3-R5: 数组字段
    self._flatten_data(data, "data", lines)
    
    # 分页参数
    params = api_record.get("request_params") or api_record.get("request_body", {})
    if params:
        lines.append("")
        lines.append("分页参数:")
        for k in ("page_size", "ps", "num", "page", "pn"):
            if k in params:
                lines.append(f"  {k} = {params[k]}")
    
    return "\n".join(lines)
```

## _flatten_data() 核心

```python
def _flatten_data(self, obj, prefix, lines, depth=0):
    if isinstance(obj, dict):
        # 检查是否包含数组
        for k, v in obj.items():
            full_key = f"{prefix}.{k}"
            if isinstance(v, list) and len(v) > 0 and isinstance(v[0], dict):
                # 数组 → 展开第一项
                first = v[0]
                total = len(v)
                total_field = self._find_total_field(obj, k)  # 找关联的 _count / total_* 字段
                
                header = f"{full_key}[]: 本次={total}"
                if total_field:
                    header += f" / 总计={total_field}"
                lines.append(header)
                
                # 展开第一项的字段
                lines.append(f"  [0] 结构:")
                self._flatten_dict(first, "", lines, indent=2)
                
                # 差异表（R3）
                if len(v) > 1:
                    lines.append(f"  [1+] 差异:")
                    self._diff_items(v, lines, indent=2)
            
            elif isinstance(v, dict):
                self._flatten_data(v, full_key, lines, depth + 1)
```

## _flatten_dict() 核心

```python
def _flatten_dict(self, obj, prefix, lines, indent=2):
    """递归展开一个 dict，遇到数组只取 [0]"""
    for k, v in obj.items():
        full_key = f"{prefix}.{k}" if prefix else k
        t = self._infer_type(v)
        
        if isinstance(v, dict):
            self._flatten_dict(v, full_key, lines, indent)
        elif isinstance(v, list):
            if len(v) > 0 and isinstance(v[0], dict):
                # 嵌套数组: 取第一项再展开
                lines.append(f"{' '*indent}{full_key}[]: 本次={len(v)}")
                self._flatten_dict(v[0], "", lines, indent + 2)
            else:
                # 简单列表: 直接显示
                sample = str(v[:3])[:50]
                lines.append(f"{' '*indent}{full_key}: {t} = {sample}")
        else:
            sample = self._truncate(str(v))
            lines.append(f"{' '*indent}{full_key}: {t} = {sample}")
```

## 辅助函数

```python
def _infer_type(self, val) -> str:
    if val is None: return "null"
    if isinstance(val, bool): return "bool"
    if isinstance(val, int): return "int"
    if isinstance(val, float): return "float"
    if isinstance(val, list): return "list"
    return "string"

def _truncate(self, val: str) -> str:
    if len(val) > 46:
        return val[:46] + "..."
    return val

def _find_total_field(self, obj: dict, array_key: str) -> str | None:
    """在 obj 中查找关联的总数字段"""
    for suffix in ("_count", "total_count", "all_count", "total"):
        key = array_key + suffix
        if key in obj:
            return str(obj[key])
    return None

def _diff_items(self, items: list, lines: list, indent: int = 2):
    """对比 items[1:] 与 items[0]，生成差异表"""
    first = items[0]
    first_fields = set(self._leaf_keys(first))
    
    # 收集后续 item 中与 first 不同的字段
    all_keys = set()
    for item in items[1:]:
        all_keys |= set(self._leaf_keys(item))
    
    diff_keys = sorted(all_keys - first_fields)
    if not diff_keys:  # 完全一致 → 取前几个字段作表格
        diff_keys = sorted(first_fields)[:5]
    
    # 生成表格
    lines.append(f"{' '*indent}| # | {' | '.join(diff_keys)} |")
    lines.append(f"{' '*indent}|{'---'*len(diff_keys)}|...|")
    for i, item in enumerate(items[1:6]):  # 最多显示 5 行
        vals = [str(self._get_nested(item, k))[:15] for k in diff_keys]
        lines.append(f"{' '*indent}| {i+1} | {' | '.join(vals)} |")

def _leaf_keys(self, obj: dict, prefix="") -> set:
    """递归获取所有叶子字段的路径"""
    keys = set()
    for k, v in obj.items():
        full = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            keys |= self._leaf_keys(v, full)
        else:
            keys.add(full)
    return keys
```

## save_raw() 核心

```python
def save_raw(self, api_record: dict) -> str:
    url = api_record["url"]
    api_path = url.split("?")[0]  # 去掉查询参数
    parts = [p for p in api_path.rstrip("/").split("/") if p]
    
    # 取最后两段
    if len(parts) >= 2:
        filename = f"{parts[-2]}_{parts[-1]}.json"
    elif parts:
        filename = f"{parts[-1]}.json"
    else:
        filename = "api_response.json"
    
    # 同文件追加 _page2 后缀
    filepath = os.path.join(self.response_dir, filename)
    base, ext = os.path.splitext(filepath)
    counter = 1
    while os.path.exists(filepath):
        counter += 1
        filepath = f"{base}_page{counter}{ext}"
    
    os.makedirs(self.response_dir, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(api_record["response_body"], f, ensure_ascii=False, indent=2)
    
    return filepath
```

## 注意事项

- 压缩算法默认不做深度截断（`content` 字段不截断到 20 字符，保持 readable）
- 差异表如果字段太多（>8 个），只选前 5 个
- 原始数据包文件编码用 UTF-8
