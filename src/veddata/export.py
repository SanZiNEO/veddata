"""Export module — JSON response compression, field documentation, raw data packet saving."""

import json
from pathlib import Path

from veddata import naming, paths


class Exporter:
    """Compress API responses, generate field docs, and save raw data packets."""

    def __init__(self, response_dir: str | None = None):
        # 显式给的那个目录；没给就用 --response-dir（都在 resolve_dir 里落地）
        self.response_dir = Path(response_dir) if response_dir else None

    def resolve_dir(self, output_dir: str | None = None) -> Path:
        """本次写盘落到哪个目录：调用参数 > ``--response-dir``；都没有则报错。

        Raises:
            paths.PathError: 未配置输出目录，或路径非法（相对路径/指向文件/建不了）。
        """
        return paths.resolve_response_dir(output_dir or self.response_dir)

    def export(self, api_record: dict, format: str = "both", output_dir: str | None = None) -> str:
        """Export an API data source.

        Args:
            api_record: A record dict from NetworkMonitor.api_records.
            format: "raw" | "compact" | "both"
            output_dir: Override save directory for this call (default: --response-dir).

        Returns:
            Status message with output details.

        Raises:
            paths.PathError: format 含 raw 但没配置输出目录时。
        """
        parts = []

        if format in ("raw", "both"):
            path = self.save_raw(api_record, output_dir)
            parts.append(f"Raw data saved: {path}")

        if format in ("compact", "both"):
            doc = self.compact(api_record)
            parts.append(f"Field document:\n{doc}")

        return "\n\n".join(parts)

    def save_raw(self, api_record: dict, output_dir: str | None = None) -> str:
        """Save the raw JSON response to a file.

        文件名：``<站点名>_<接口名>_<YYYYMMDD-HHMMSS>.json``（见 veddata.naming）。

        Args:
            output_dir: Override save directory (default: --response-dir).

        Returns:
            Absolute path of the saved JSON.

        Raises:
            paths.PathError: 没配置输出目录，或路径非法。
        """
        save_dir = self.resolve_dir(output_dir)
        filepath = naming.unique_path(save_dir, naming.export_stem(api_record["url"]), ".json")

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(api_record["response_body"], f, ensure_ascii=False, indent=2)

        return str(filepath)

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
