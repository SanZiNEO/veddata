"""Export module — JSON response compression, field documentation, raw data packet saving."""

import json
import os


class Exporter:
    """Compress API responses, generate field docs, and save raw data packets."""

    def __init__(self, response_dir: str = "./response"):
        self.response_dir = response_dir

    def export(self, api_record: dict, format: str = "both") -> str:
        """Export an API data source.

        Args:
            api_record: A record dict from NetworkMonitor.api_records.
            format: "raw" | "compact" | "both"

        Returns:
            Status message with output details.
        """
        parts = []

        if format in ("raw", "both"):
            path = self.save_raw(api_record)
            parts.append(f"Raw data saved: {path}")

        if format in ("compact", "both"):
            doc = self.compact(api_record)
            parts.append(f"Field document:\n{doc}")

        return "\n\n".join(parts)

    def save_raw(self, api_record: dict) -> str:
        """Save the raw JSON response to a file.

        Filename is derived from the URL path (last two segments).

        Returns:
            File path of the saved JSON.
        """
        url = api_record["url"]
        api_path = url.split("?")[0]
        parts = [p for p in api_path.rstrip("/").split("/") if p]

        if len(parts) >= 2:
            filename = f"{parts[-2]}_{parts[-1]}.json"
        elif parts:
            filename = f"{parts[-1]}.json"
        else:
            filename = "api_response.json"

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

    def compact(self, api_record: dict) -> str:
        """Generate a compressed field document from an API response.

        Applies R1-R7 compression rules.

        Returns:
            Formatted text with field structure and sample values.
        """
        body = api_record["response_body"]
        lines = []

        for k in ("code", "success", "msg"):
            if k in body:
                lines.append(f"{k}: {body[k]}")
        lines.append("")

        data = body.get("data", body)
        if isinstance(data, dict):
            for k, v in data.items():
                if not isinstance(v, (list, dict)):
                    lines.append(f"data.{k}: {v}")
            lines.append("")

        self._flatten_data(data, "data", lines)

        params = api_record.get("request_params") or api_record.get("request_body", {})
        if params:
            lines.append("")
            lines.append("Pagination params:")
            for k in ("page_size", "ps", "num", "page", "pn"):
                if k in params:
                    lines.append(f"  {k} = {params[k]}")

        return "\n".join(lines)

    def _flatten_data(self, obj, prefix, lines, depth=0):
        """Recursively flatten a JSON structure, expanding arrays."""
        if not isinstance(obj, dict):
            return

        for k, v in obj.items():
            full_key = f"{prefix}.{k}"
            if isinstance(v, list) and len(v) > 0 and isinstance(v[0], dict):
                total = len(v)
                total_field = self._find_total_field(obj, k)

                header = f"{full_key}[]: count={total}"
                if total_field:
                    header += f" / total={total_field}"
                lines.append(header)

                lines.append(f"  [0] structure:")
                self._flatten_dict(v[0], "", lines, indent=2)

                if len(v) > 1:
                    lines.append(f"  [1+] diff:")
                    self._diff_items(v, lines, indent=2)

            elif isinstance(v, dict):
                self._flatten_data(v, full_key, lines, depth + 1)

    def _flatten_dict(self, obj, prefix, lines, indent=2):
        """Recursively flatten a dict, expanding arrays at [0]."""
        for k, v in obj.items():
            full_key = f"{prefix}.{k}" if prefix else k
            t = self._infer_type(v)

            if isinstance(v, dict):
                self._flatten_dict(v, full_key, lines, indent)
            elif isinstance(v, list):
                if len(v) > 0 and isinstance(v[0], dict):
                    lines.append(f"{' ' * indent}{full_key}[]: count={len(v)}")
                    self._flatten_dict(v[0], "", lines, indent + 2)
                else:
                    sample = str(v[:3])[:50]
                    lines.append(f"{' ' * indent}{full_key}: {t} = {sample}")
            else:
                sample = self._truncate(str(v))
                lines.append(f"{' ' * indent}{full_key}: {t} = {sample}")

    def _infer_type(self, val) -> str:
        if val is None:
            return "null"
        if isinstance(val, bool):
            return "bool"
        if isinstance(val, int):
            return "int"
        if isinstance(val, float):
            return "float"
        if isinstance(val, list):
            return "list"
        return "string"

    @staticmethod
    def _truncate(val: str) -> str:
        if len(val) > 46:
            return val[:46] + "..."
        return val

    @staticmethod
    def _find_total_field(obj: dict, array_key: str) -> str | None:
        for suffix in ("_count", "total_count", "all_count", "total"):
            key = array_key + suffix
            if key in obj:
                return str(obj[key])
        return None

    def _diff_items(self, items: list, lines: list, indent: int = 2):
        """Compare items[1:] with items[0], generating a diff table."""
        first = items[0]
        first_fields = self._leaf_keys(first)

        all_keys = set()
        for item in items[1:]:
            all_keys |= self._leaf_keys(item)

        diff_keys = sorted(all_keys - first_fields)
        if not diff_keys:
            diff_keys = sorted(first_fields)[:5]

        header = " | ".join(diff_keys)
        lines.append(f"{' ' * indent}| # | {header} |")
        lines.append(f"{' ' * indent}|{'---' * len(diff_keys)}|...|")
        for i, item in enumerate(items[1:6]):
            vals = [str(self._get_nested(item, k))[:15] for k in diff_keys]
            lines.append(f"{' ' * indent}| {i + 1} | {' | '.join(vals)} |")

    @staticmethod
    def _leaf_keys(obj: dict, prefix: str = "") -> set:
        """Recursively get all leaf field paths from a dict."""
        keys = set()
        for k, v in obj.items():
            full = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                keys |= Exporter._leaf_keys(v, full)
            else:
                keys.add(full)
        return keys

    @staticmethod
    def _get_nested(obj, key_path: str):
        """Get a nested value from a dict by dot-separated key path."""
        parts = key_path.split(".")
        current = obj
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return ""
        return current or ""
