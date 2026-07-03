"""DOM scanner module — interactive element listing, container discovery v3, Common Actions."""

LAYOUT_BLACKLIST = frozenset({
    "section", "wrapper", "main", "side", "body", "row", "col",
    "container", "grid", "layout", "content", "inner", "outer",
    "header", "footer",
})


class DOMScanner:
    """Scan page DOM: interactive elements, repeated containers (v3), common actions."""

    def __init__(self, tab):
        self.tab = tab
        self.elements_cache: list[dict] = []
        self.containers_cache: list[dict] = []
        self._next_elem_id = 1
        self._next_cont_id = 1

    def list_elements(self) -> str:
        """Scan interactive elements — unchanged from v2."""
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
            items.push({tag: el.tagName.toLowerCase(), text: text, href: el.getAttribute('href') || ''});
            if (items.length >= 30) break;
        }
        return items;
        """
        try:
            raw = self.tab.run_js(js) or []
        except Exception:
            raw = []
        for item in raw:
            self.elements_cache.append({
                "id": self._next_elem_id,
                "tag": item.get("tag", "?"),
                "text": item.get("text", ""),
                "href": item.get("href", ""),
                "element_ref": None,
            })
            self._next_elem_id += 1
        if not self.elements_cache:
            return "No interactive elements found."
        return self._format_elements()

    def _format_elements(self) -> str:
        lines = []
        for el in self.elements_cache:
            tag = el["tag"]
            text = el["text"]
            href = el["href"]
            suffix = f" → {href}" if href else ""
            lines.append(f"[{el['id']}] {tag:<8} \"{text}\"{suffix}")
        return "\n".join(lines)

    def find_containers(self) -> str:
        """Find repeated containers with v3 algorithm.

        Three improvements over v2:
        1. Filter hidden, zero-size, and layout-class elements at counting time
        2. New scoring: count × avgTextLen × headingBonus × (1 + linkRatio)
        3. h[1-4] tags mapped to 'title' field name
        """
        self.containers_cache.clear()
        self._next_cont_id = 1

        js = """
        var LAYOUT = {section:1, wrapper:1, main:1, side:1, body:1, row:1, col:1,
                      container:1, grid:1, layout:1, content:1, inner:1, outer:1,
                      header:1, footer:1};
        var map = {};
        var all = document.querySelectorAll('[class]');
        for (var i = 0; i < all.length; i++) {
            var el = all[i];
            var style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden') continue;
            var rect = el.getBoundingClientRect();
            if (rect.width < 1 || rect.height < 1) continue;
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
            if (LAYOUT[ccls]) continue;
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
            fields = self._extract_container_fields(tag, cls)
            if not fields:
                continue
            total_text_len = sum(len(f["sample"]) for f in fields)
            avg_text_len = total_text_len // len(fields) if fields else 0
            has_heading = any(f.get("name") == "title" for f in fields)
            heading_bonus = 2.0 if has_heading else 1.0
            link_count = sum(1 for f in fields if f.get("type") == "href")
            link_ratio = link_count / len(fields) if fields else 0
            score = rc["count"] * max(avg_text_len, 1) * heading_bonus * (1 + link_ratio)
            candidates.append({
                "tag": tag, "class": cls, "count": rc["count"],
                "fields": fields, "score": score,
            })

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
            self.containers_cache.append({
                "id": self._next_cont_id,
                "selector": selector, "count": c["count"], "fields": fields,
                "tag": c["tag"], "class": c["class"],
            })
            lines.append(f"[{self._next_cont_id}] .{selector}[] 共 {c['count']} 条 → {field_str}")
            self._next_cont_id += 1
        return "\n".join(lines)

    def find_common_actions(self) -> str:
        """Find common page actions: search, pagination, sort, login, etc.

        Two-layer filtering: text keyword match → semantic class-name filter.
        """
        js = """
        var keywords = {
            '搜索': ['input', 'button', 'a'],
            '下一页': ['a', 'button'],
            '上一页': ['a', 'button'],
            '登录': ['a', 'button'],
            '注册': ['a', 'button'],
            '排序': ['button', 'a'],
            '筛选': ['button', 'a'],
            '提交': ['button', 'a'],
            '换一换': ['a', 'button'],
            '刷新': ['a', 'button'],
            '加载更多': ['a', 'button']
        };
        var filters = {
            '搜索': function(el, cls) { return el.tagName.toLowerCase() === 'input' || /search|srh|keyword|query|find/.test(cls); },
            '下一页': function(el, cls) { return (el.textContent||'').length < 10 || /page|pager|btn|button|next|prev|nav/.test(cls); },
            '上一页': function(el, cls) { return (el.textContent||'').length < 10 || /page|pager|btn|button|next|prev|nav/.test(cls); },
            '登录': function(el, cls) { return (el.textContent||'').length < 10 || /login|register|auth|account|user|sign|btn/.test(cls); },
            '注册': function(el, cls) { return (el.textContent||'').length < 10 || /login|register|auth|account|user|sign|btn/.test(cls); },
            '排序': function(el, cls) { return (el.textContent||'').length < 10 || /sort|filter|order|btn|tab/.test(cls); },
            '筛选': function(el, cls) { return (el.textContent||'').length < 10 || /sort|filter|order|btn|tab/.test(cls); },
            '提交': function(el, cls) { return (el.textContent||'').length < 10 || /btn|button|submit/.test(cls); },
            '换一换': function(el, cls) { return (el.textContent||'').length < 15 || /refresh|reload|btn/.test(cls); },
            '刷新': function(el, cls) { return (el.textContent||'').length < 15 || /refresh|reload|btn/.test(cls); },
            '加载更多': function(el, cls) { return (el.textContent||'').length < 15 || /refresh|reload|btn/.test(cls); }
        };
        var all = document.querySelectorAll('input, button, a, select, textarea');
        var seen = {};
        var results = [];
        for (var i = 0; i < all.length; i++) {
            var el = all[i];
            var style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden') continue;
            var text = (el.textContent || '').trim();
            var placeholder = el.getAttribute('placeholder') || '';
            var ariaLabel = el.getAttribute('aria-label') || '';
            var title = el.getAttribute('title') || '';
            var val = el.getAttribute('value') || '';
            var combined = text + ' ' + placeholder + ' ' + ariaLabel + ' ' + title + ' ' + val;
            var tag = el.tagName.toLowerCase();
            var cls = el.getAttribute('class') || '';
            var pCls = (el.parentElement ? el.parentElement.getAttribute('class') || '' : '');
            var gpCls = (el.parentElement && el.parentElement.parentElement ? el.parentElement.parentElement.getAttribute('class') || '' : '');
            var allCls = cls + ' ' + pCls + ' ' + gpCls;
            for (var label in keywords) {
                var targetTags = keywords[label];
                if (targetTags.indexOf(tag) === -1) continue;
                var combinedLower = combined.toLowerCase();
                if (combinedLower.indexOf(label) === -1) continue;
                if (!filters[label](el, allCls)) continue;
                var key = label + ':' + text + ':' + tag;
                if (seen[key]) continue;
                seen[key] = true;
                results.push({label: label, tag: tag, text: text, cls: cls});
            }
        }
        return JSON.stringify(results);
        """
        try:
            raw = self.tab.run_js(js) or []
        except Exception:
            return ""
        import json
        try:
            actions = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            return ""
        if not actions:
            return ""
        lines = []
        for item in actions:
            label = item["label"]
            tag = item["tag"]
            text = item.get("text", "")
            cls = item.get("cls", "")
            lines.append(f"  [{label}] {tag} \"{text}\"  .{cls[:30]}")
        return "\n".join(lines)

    def scan_by_keyword(self, keyword: str) -> str:
        """Search DOM for elements containing keyword, group by parent container."""
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
            return f"Error: {e}"
        if not raw:
            return f"No elements containing '{keyword}' found."
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
            self.containers_cache.append({
                "id": self._next_cont_id,
                "selector": f"{tag}.{cls}", "count": count, "fields": [],
                "tag": tag, "class": cls,
            })
            self._next_cont_id += 1
        return "\n".join(lines)

    def inspect_container(self, index: int) -> str:
        target = None
        for c in self.containers_cache:
            if c["id"] == index:
                target = c
                break
        if not target:
            return f"Container #{index} not found."
        lines = [f"{target['tag']}.{target['class']}[]: 共 {target['count']} 条\n"]
        for i, f in enumerate(target["fields"]):
            lines.append(f"  [{i}] {f['name']:<20} : {f['type']:<6} = \"{f['sample']}\"")
        return "\n".join(lines)

    def _extract_container_fields(self, tag: str, class_: str) -> list:
        """Extract fields via JS, mapping h[1-4] → 'title'."""
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
            var tagName = leaf.tagName.toLowerCase();
            var cls = leaf.getAttribute('class') || '';
            var classes = cls.split(/\\s+/);
            var name = 'field';
            var skip = {{'active':1, 'show':1, 'hide':1, 'selected':1, 'disabled':1, 'ng-binding':1}};
            if (tagName.match(/h[1-4]/)) {{
                name = 'title';
            }} else {{
                for (var j = 0; j < classes.length; j++) {{
                    var c = classes[j];
                    if (!skip[c]) {{ name = c; break; }}
                }}
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
