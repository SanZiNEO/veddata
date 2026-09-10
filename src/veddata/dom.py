"""DOM tree module — in-memory snapshot of the page structure.

The browser's live DOM is snapshotted once (after the page stabilizes)
into a DOMTree held in Python memory.  Searches and path lookups run
against the snapshot without touching the browser again.
"""

import time
from dataclasses import dataclass, field


# 递归遍历 DOM 生成可序列化快照。节点数上限 2000，超出截断。
SNAPSHOT_JS = """
() => {
  const MAX_NODES = 2000;
  let count = 0;
  let truncated = false;
  const ATTR_KEYS = ['href', 'src', 'placeholder', 'aria-label', 'title', 'name', 'type', 'value', 'role'];
  function walk(el, depth) {
    if (depth > 24) return null;
    if (count >= MAX_NODES) { truncated = true; return null; }
    count++;
    const tag = el.tagName ? el.tagName.toLowerCase() : '';
    const node = {
      tag: tag,
      id: el.id || '',
      classes: Array.from(el.classList || []),
      text: '',
      attrs: {},
      visible: el.offsetParent !== null || el === document.documentElement,
      rect: null,
      children: []
    };
    for (const k of ATTR_KEYS) {
      const v = el.getAttribute(k);
      if (v) node.attrs[k] = v.slice(0, 120);
    }
    if (node.visible) {
      const r = el.getBoundingClientRect();
      node.rect = { w: Math.round(r.width), h: Math.round(r.height), top: Math.round(r.top), left: Math.round(r.left) };
    }
    const kids = Array.from(el.children || []);
    if (kids.length === 0) {
      const t = (el.textContent || '').trim();
      if (t) node.text = t.slice(0, 80);
    } else {
      for (const c of kids) {
        const cn = walk(c, depth + 1);
        if (cn) node.children.push(cn);
      }
    }
    return node;
  }
  const root = walk(document.documentElement, 0);
  return { root: root, truncated: truncated };
}
"""


@dataclass
class DOMNode:
    tag: str = ""
    id: str = ""
    classes: list[str] = field(default_factory=list)
    text: str = ""
    attrs: dict = field(default_factory=dict)
    rect: dict | None = None
    children: list["DOMNode"] = field(default_factory=list)
    collapsed: bool = False
    collapsed_count: int = 0

    @property
    def selector(self) -> str:
        """Compact selector like div#app.feed or input#kw."""
        s = self.tag or "?"
        if self.id:
            s += f"#{self.id}"
        if self.classes:
            s += "." + ".".join(self.classes[:3])
        return s

    def is_interactive(self) -> bool:
        return self.tag in ("input", "button", "select") or (self.tag == "a" and "href" in self.attrs)


def _from_dict(d: dict) -> DOMNode:
    node = DOMNode(
        tag=d.get("tag", ""),
        id=d.get("id", ""),
        classes=d.get("classes", []),
        text=d.get("text", ""),
        attrs=d.get("attrs", {}),
        rect=d.get("rect"),
    )
    for c in d.get("children", []):
        node.children.append(_from_dict(c))
    return node


class DOMTree:
    """In-memory DOM snapshot with search / locate / format operations."""

    def __init__(self, root: DOMNode, tab_id: str, page_url: str):
        self.root = root
        self.tab_id = tab_id
        self.captured_at = time.time()
        self.page_url = page_url
        self.truncated = False

    # ---- 折叠（连续同类兄弟合并；无信息量节点删除） ----

    def collapse(self):
        self._collapse_node(self.root)

    @classmethod
    def _collapse_node(cls, node: DOMNode) -> None:
        if not node.children:
            return
        merged: list[DOMNode] = []
        for child in node.children:
            if merged and cls._same_shape(merged[-1], child):
                merged[-1].collapsed = True
                merged[-1].collapsed_count += 1
                continue
            merged.append(child)
        node.children = merged
        for child in node.children:
            cls._collapse_node(child)

    @staticmethod
    def _same_shape(a: DOMNode, b: DOMNode) -> bool:
        return (
            a.tag == b.tag
            and a.classes == b.classes
            and not a.id and not b.id
            and not a.attrs and not b.attrs
        )

    def prune_empty(self):
        """删除不可见且无文本且无标识且无子节点的节点。"""
        self._prune_node(self.root)

    def _prune_node(self, node: DOMNode) -> None:
        kept = []
        for child in node.children:
            self._prune_node(child)
            if child.children or child.text or child.id or child.classes or child.attrs or child.collapsed:
                kept.append(child)
        node.children = kept

    # ---- 查询 ----

    def search(self, text: str) -> list[tuple[str, DOMNode]]:
        """DFS 搜索文本/属性/id 包含关键字（大小写不敏感），返回 (路径, 节点)。"""
        kw = text.lower()
        results: list[tuple[str, DOMNode]] = []

        def dfs(node: DOMNode, path: str):
            haystack = (node.text + " " + node.id + " " + " ".join(str(v) for v in node.attrs.values())).lower()
            if kw in haystack:
                results.append((path, node))
            for child in node.children:
                dfs(child, f"{path} > {child.selector}")

        dfs(self.root, self.root.selector or "html")
        return results

    def find_tag(self, tag: str) -> list[DOMNode]:
        out: list[DOMNode] = []

        def dfs(node: DOMNode):
            if node.tag == tag:
                out.append(node)
            for c in node.children:
                dfs(c)

        dfs(self.root)
        return out

    def find_attr(self, key: str, value: str = "") -> list[DOMNode]:
        out: list[DOMNode] = []

        def dfs(node: DOMNode):
            v = node.attrs.get(key)
            if v is not None and (not value or value in v):
                out.append(node)
            for c in node.children:
                dfs(c)

        dfs(self.root)
        return out

    def locate(self, path: str) -> DOMNode | None:
        """路径定位：`div.content > div.post-list > article:nth-child(3)`。

        段格式 `tag[.class][#id][:nth-child(n)]`，`>` 分隔。
        """
        segments = [s.strip() for s in path.split(">") if s.strip()]
        if not segments:
            return None

        def match(node: DOMNode, spec: str) -> bool:
            rest = spec
            tag = rest.split(".", 1)[0].split("#", 1)[0].split(":", 1)[0]
            if tag and node.tag != tag:
                return False
            rest = rest[len(tag):]
            if rest.startswith("."):
                cls = rest[1:].split("#", 1)[0].split(":", 1)[0]
                if cls not in node.classes:
                    return False
                rest = rest[len(cls) + 1:]
            if rest.startswith("#"):
                nid = rest[1:].split(":", 1)[0]
                if node.id != nid:
                    return False
                rest = rest[len(nid) + 1:]
            if rest.startswith(":nth-child(") and rest.endswith(")"):
                try:
                    n = int(rest[len(":nth-child("):-1])
                except ValueError:
                    n = None
                if n is not None and n >= 1:
                    parent = self._parent_of(node)
                    if parent is None or n > len(parent.children) or parent.children[n - 1] is not node:
                        return False
            return True

        def find(nodes: list[DOMNode], spec: str) -> DOMNode | None:
            for n in nodes:
                if match(n, spec):
                    return n
            return None

        current: DOMNode | None = None
        for spec in segments:
            if current is None:
                current = find([self.root], spec)
            else:
                current = find(current.children, spec)
            if current is None:
                return None
        return current

    def _parent_of(self, node: DOMNode) -> DOMNode | None:
        def dfs(n: DOMNode) -> DOMNode | None:
            for c in n.children:
                if c is node:
                    return n
                r = dfs(c)
                if r:
                    return r
            return None
        return dfs(self.root)

    # ---- 输出 ----

    def format(self, depth: int = 4) -> str:
        lines: list[str] = []
        self._format_node(self.root, "", "", 0, depth, lines)
        if self.truncated:
            lines.append("... (truncated)")
        return "\n".join(lines)

    def _format_node(self, node: DOMNode, prefix: str, connector: str, level: int, depth: int, lines: list[str]):
        if level >= depth and node is not self.root:
            return
        line = prefix + connector + node.selector
        if node.collapsed and node.collapsed_count >= 1:
            line += f"  [x{node.collapsed_count + 1}]"
        if node.text:
            line += f'  "{node.text}"'
        if node.is_interactive():
            line += f"  [{node.tag}]"
        lines.append(line)

        child_prefix = prefix + ("    " if connector == "└── " else "│   ")
        for i, child in enumerate(node.children):
            last = (i == len(node.children) - 1)
            c = "└── " if last else "├── "
            self._format_node(child, child_prefix, c, level + 1, depth, lines)


async def snapshot_tree(page) -> DOMTree:
    """Evaluate SNAPSHOT_JS on the page and build a DOMTree."""
    data = await page.evaluate(SNAPSHOT_JS)
    root_dict = (data or {}).get("root")
    if not root_dict:
        root_dict = {"tag": "html", "id": "", "classes": [], "text": "", "attrs": {}, "children": []}
    try:
        page_url = page.url
    except Exception:
        page_url = ""
    tree = DOMTree(_from_dict(root_dict), "", page_url)
    tree.truncated = bool((data or {}).get("truncated"))
    tree.collapse()
    tree.prune_empty()
    return tree
