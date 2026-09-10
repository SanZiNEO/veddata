"""veddata（斥候）— 给 AI 用的网页数据源发现的 MCP 服务。

中文名「斥候」取自古代军事侦察兵；英文名 veddata = ved（vedette，军事术语
"骑马斥候"）+ data，表示"派出去把数据来源摸清楚"。
"""

from importlib.metadata import PackageNotFoundError, version

try:
    # 单一真源：安装元数据（来自 pyproject.toml 的 version）
    __version__ = version("veddata")
except PackageNotFoundError:  # 未安装时（直接从源码运行）
    __version__ = "1.0.0"

__all__ = ["__version__"]
