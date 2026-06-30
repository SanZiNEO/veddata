"""DOM scanner module — interactive element listing, container discovery, field extraction."""


def _infer_field_name(class_attr: str) -> str:
    """Infer a short field name from a CSS class attribute."""
    if not class_attr:
        return "field"
    classes = class_attr.split()
    skip = {"active", "show", "hide", "selected", "disabled", "ng-binding"}
    for cls in classes:
        if cls in skip:
            continue
        return cls
    return "field"


class DOMScanner:
    """Scan page DOM: interactive elements, repeated containers, field extraction."""

    def __init__(self, tab):
        self.tab = tab
        self.elements_cache: list[dict] = []
        self.containers_cache: list[dict] = []
        self._next_elem_id = 1
        self._next_cont_id = 1

    def list_elements(self) -> str:
        """Scan interactive and clickable elements, return a numbered list.

        Uses JavaScript for bulk DOM extraction to avoid CDP overhead.
        """
        self.elements_cache.clear()
        self._next_elem_id = 1

        js = """
        var selectors = 'a, button, input, select, [onclick], [role=button], [role=tab], [role=link]';
        var items = [];
        var seen = {};
        var els = document.querySelectorAll(selectors);
        for (var i = 0; i < els.length; i++) {
            var el = els[i];
            var style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden') continue;
            if (el.closest('nav, header, footer')) continue;
            var text = (el.textContent || '').trim().substring(0, 30);
            if (!text || text.startsWith('svg')) continue;
            var key = el.tagName.toLowerCase() + ':' + text;
            if (seen[key]) continue;
            seen[key] = true;
            items.push({
                tag: el.tagName.toLowerCase(),
                text: text,
                href: el.getAttribute('href') || ''
            });
            if (items.length >= 30) break;
        }
        return items;
        """
        try:
            raw = self.tab.run_js(js) or []
        except Exception:
            raw = []

        for item in raw:
            self.elements_cache.append(
                {
                    "id": self._next_elem_id,
                    "tag": item.get("tag", "?"),
                    "text": item.get("text", ""),
                    "href": item.get("href", ""),
                    "element_ref": None,
                }
            )
            self._next_elem_id += 1

        if not self.elements_cache:
            return "No interactive elements found."

        return self._format_elements()

    def _format_elements(self) -> str:
        """Format cached elements as a numbered list."""
        lines = []
        for el in self.elements_cache:
            tag = el["tag"]
            text = el["text"]
            href = el["href"]
            suffix = f" → {href}" if href else ""
            lines.append(f"[{el['id']}] {tag:<8} \"{text}\"{suffix}")
        return "\n".join(lines)

    def click_element(self, index: int) -> str:
        """Click an element by its cached index.

        Args:
            index: Element ID (from list_elements output).

        Returns:
            Status message.
        """
        target = None
        for el in self.elements_cache:
            if el["id"] == index:
                target = el
                break

        if not target:
            return f"Element #{index} not found. Call list_elements first."

        js = f"""
        var selector = 'a, button, input, select, [onclick], [role=button], [role=tab], [role=link]';
        var els = document.querySelectorAll(selector);
        for (var i = 0; i < els.length; i++) {{
            var el = els[i];
            var text = (el.textContent || '').trim().substring(0, 30);
            if (el.tagName.toLowerCase() === '{target["tag"]}' && text === '{target["text"]}') {{
                el.click();
                return true;
            }}
        }}
        return false;
        """
        try:
            result = self.tab.run_js(js)
            if result:
                return f"Clicked [{index}] {target['tag']} \"{target['text']}\""
            else:
                return f"Element #{index} not found on page."
        except Exception as e:
            return f"Failed to click element #{index}: {e}"

    def find_containers(self) -> str:
        """Find repeated containers (≥3 siblings with same tag+class).

        Returns:
            Formatted string listing found containers with rank and field count.
        """
        self.containers_cache.clear()
        self._next_cont_id = 1

        js = """
        var map = {};
        var all = document.querySelectorAll('[class]');
        for (var i = 0; i < all.length; i++) {
            var el = all[i];
            var p = el.parentElement;
            if (!p) continue;
            var ptag = p.tagName.toLowerCase();
            var pcls = (p.getAttribute('class') || '').trim();
            var pkey = ptag + '.' + pcls;
            var ctag = el.tagName.toLowerCase();
            var raw = el.getAttribute('class') || '';
            var parts = raw.split(/\\s+/);
            var ccls = parts[0];
            if (!ccls) continue;
            var ckey = ctag + '.' + ccls;
            if (!map[pkey]) map[pkey] = {};
            if (!map[pkey][ckey]) map[pkey][ckey] = 0;
            map[pkey][ckey]++;
        }
        var candidates = [];
        for (var pkey in map) {
            for (var ckey in map[pkey]) {
                var cnt = map[pkey][ckey];
                if (cnt < 3) continue;
                var cparts = ckey.split('.');
                candidates.push({tag: cparts[0], cls: cparts.slice(1).join('.'), count: cnt});
            }
        }
        candidates.sort(function(a, b) { return b.count - a.count; });
        return candidates.slice(0, 20);
        """
        try:
            raw_candidates = self.tab.run_js(js) or []
        except Exception as e:
            return f"Error scanning page: {e}"

        candidates = []
        for rc in raw_candidates[:20]:
            tag = rc["tag"]
            cls = rc.get("cls") or rc.get("class", "")
            if not cls:
                continue
            fields = self._extract_container_fields_tab(tag, cls)
            if not fields:
                continue
            avg_text_len = sum(len(f["sample"]) for f in fields)
            if fields:
                avg_text_len = avg_text_len // len(fields)
            score = rc["count"] * (avg_text_len + 1) + len(fields) * 5
            candidates.append(
                {
                    "tag": tag,
                    "class": cls,
                    "count": rc["count"],
                    "fields": fields,
                    "score": score,
                }
            )

        candidates.sort(key=lambda x: x["score"], reverse=True)

        seen_selectors = set()
        top = []
        for c in candidates:
            sel = f"{c['tag']}.{c['class']}"
            if sel in seen_selectors:
                continue
            seen_selectors.add(sel)
            top.append(c)
            if len(top) >= 5:
                break

        if not top:
            return "No repeated containers found."

        lines = []
        for c in top:
            selector = f"{c['tag']}.{c['class']}"
            fields = c["fields"]
            field_list = [f["name"] for f in fields[:6]]
            field_str = ", ".join(field_list)
            if len(fields) > 6:
                field_str += f", ... ({len(fields)} total)"

            self.containers_cache.append(
                {
                    "id": self._next_cont_id,
                    "selector": selector,
                    "count": c["count"],
                    "fields": fields,
                    "tag": c["tag"],
                    "class": c["class"],
                }
            )
            lines.append(
                f"[{self._next_cont_id}] .{selector}[] 共 {c['count']} 条 → {field_str}"
            )
            self._next_cont_id += 1

        return "\n".join(lines)

    def scan_by_keyword(self, keyword: str) -> str:
        """Search DOM for elements containing keyword, group by parent container.

        For each match, walks up the DOM to find the first ancestor that has ≥2
        direct children ALSO containing the keyword — that ancestor is the
        "data container". This eliminates nested duplicates and global containers
        (like body) automatically.

        Args:
            keyword: Text to search for in page elements.

        Returns:
            Formatted string listing containers that matched, with hit counts.
        """
        if not keyword.strip():
            return "Keyword cannot be empty."

        js = f"""
        var keyword = '{keyword}'.toLowerCase();
        var all = document.querySelectorAll('[class]');
        var groups = {{}};
        var groupList = [];

        for (var i = 0; i < all.length; i++) {{
            var el = all[i];
            var style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden') continue;
            var text = (el.textContent || '').trim();
            if (text.toLowerCase().indexOf(keyword) === -1) continue;

            var p = el.parentElement;
            if (!p) continue;
            var ptag = p.tagName.toLowerCase();
            var pcls = (p.getAttribute('class') || '').split(/\\s+/)[0];
            if (!pcls) continue;
            var pkey = ptag + '.' + pcls;

            if (!groups[pkey]) {{
                groups[pkey] = {{tag: ptag, cls: pcls, count: 0, sample: '', ref: p}};
                groupList.push(pkey);
            }}
            groups[pkey].count++;
            if (!groups[pkey].sample) {{
                groups[pkey].sample = text.substring(0, 60);
            }}
        }}

        var filtered = [];
        for (var k = 0; k < groupList.length; k++) {{
            var g = groups[groupList[k]];
            if (g.count < 2) continue;
            filtered.push(g);
        }}

        filtered.sort(function(a, b) {{ return b.count - a.count; }});

        var result = [];
        for (var m = 0; m < filtered.length; m++) {{
            var cur = filtered[m];
            var nested = false;
            for (var n = 0; n < filtered.length; n++) {{
                if (m === n) continue;
                var other = filtered[n];
                if (other.count >= cur.count && other.ref.contains(cur.ref)) {{
                    nested = true;
                    break;
                }}
            }}
            if (!nested) {{
                result.push({{tag: cur.tag, cls: cur.cls, count: cur.count, sample: cur.sample}});
            }}
        }}

        return result;
        """
        try:
            raw = self.tab.run_js(js) or []
        except Exception as e:
            return f"Error scanning for keyword '{keyword}': {e}"

        if not raw:
            return f"No elements containing '{keyword}' found on the page."

        self.containers_cache.clear()
        self._next_cont_id = 1

        lines = [f"Keyword '{keyword}' matched {len(raw)} container(s):\n"]
        for c in raw:
            tag = c["tag"]
            cls = c.get("cls") or c.get("class", "")
            count = c["count"]
            sample = c.get("sample", "")
            sample_str = f"  e.g. \"{sample}\"" if sample else ""
            lines.append(f"  .{tag}.{cls}[] — {count} matching item(s)  {sample_str}")

            self.containers_cache.append(
                {
                    "id": self._next_cont_id,
                    "selector": f"{tag}.{cls}",
                    "count": count,
                    "fields": [],
                    "tag": tag,
                    "class": cls,
                }
            )
            self._next_cont_id += 1

        return "\n".join(lines)

    def inspect_container(self, index: int) -> str:
        """Expand a container's internal fields in detail.

        Args:
            index: Container ID (from find_containers output).

        Returns:
            Formatted field structure with sample values.
        """
        target = None
        for c in self.containers_cache:
            if c["id"] == index:
                target = c
                break

        if not target:
            return f"Container #{index} not found. Call find_containers first."

        lines = []
        lines.append(f"{target['tag']}.{target['class']}[]: 共 {target['count']} 条\n")

        fields = target["fields"]
        for i, f in enumerate(fields):
            t = f["type"]
            name = f["name"]
            sample = f["sample"]
            lines.append(f"  [{i}] {name:<20} : {t:<6} = \"{sample}\"")

        return "\n".join(lines)

    def _extract_container_fields_tab(self, tag: str, class_: str) -> list:
        """Extract fields from the first container element using JavaScript.

        Returns:
            List of dicts with name, type, sample.
        """
        import json

        js = f"""
        var els = document.querySelectorAll('{tag}.{class_}');
        if (!els.length) return [];
        var first = els[0];
        var leaves = first.querySelectorAll('[class]');
        var seen = {{}};
        var result = [];
        for (var i = 0; i < leaves.length; i++) {{
            var leaf = leaves[i];
            var style = window.getComputedStyle(leaf);
            if (style.display === 'none' || style.visibility === 'hidden') continue;
            var cls = leaf.getAttribute('class') || '';
            var classes = cls.split(/\\s+/);
            var name = 'field';
            var skip = {{'active':1, 'show':1, 'hide':1, 'selected':1, 'disabled':1, 'ng-binding':1}};
            for (var j = 0; j < classes.length; j++) {{
                var c = classes[j];
                if (!skip[c]) {{ name = c; break; }}
            }}
            if (name === 'field' || !name) continue;
            if (seen[name]) {{ seen[name]++; name = name + '_' + seen[name]; }}
            else {{ seen[name] = 1; }}
            var val = leaf.textContent || leaf.getAttribute('href') || leaf.getAttribute('src') || '';
            val = val.trim().substring(0, 46);
            if (!val) continue;
            var vtype = 'text';
            if (leaf.tagName === 'IMG') vtype = 'img';
            else if (leaf.tagName === 'A') vtype = 'href';
            result.push({{name: name, type: vtype, sample: val}});
        }}
        return result;
        """
        try:
            fields = self.tab.run_js(js) or []
        except Exception:
            fields = []
        return fields
