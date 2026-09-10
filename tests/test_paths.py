"""paths 模块测试 —— 锁死三个不变量：

1. 默认落点都在**用户级数据根目录**下，绝不写进用户的项目目录，也**不依赖 CWD**。
   这个服务要在不同 agent / harness 平台下通用，而各家是否给子进程设 cwd、设成什么
   都不同；默认路径若跟着 CWD 走，同一个客户端换个平台就会换一份数据。
2. 配置面**只有 CLI 参数**（``--profile-dir`` / ``--response-dir``）。历史环境变量
   （``RESPONSE_DIR`` / ``USER_DATA_DIR`` / ``VEDDATA_HOME`` / ``VEDDATA_WORKSPACE``）
   已全部移除，不该再影响任何落点。
3. 程序**没有任何"启动时清空目录"的能力**。旧版本在 import 时无条件
   ``shutil.rmtree("./response")``，而 CWD 是用户的工作目录 —— 会删掉用户项目里
   恰好同名的 response/ 目录。因此整个删除能力被移除。
"""

import ast
from pathlib import Path

import pytest

from veddata import paths


@pytest.fixture(autouse=True)
def clean_cli_config(monkeypatch):
    """每个用例前后清掉模块级的 CLI 配置。"""
    monkeypatch.setattr(paths, "_profile_dir", None)
    monkeypatch.setattr(paths, "_response_dir", None)


# ---- 默认落点 -------------------------------------------------------------


def test_defaults_are_under_user_data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))

    home = paths.data_home()
    assert home.name == "veddata"
    assert home.parent in (tmp_path / "appdata", tmp_path / "xdg"), "按平台约定推导"

    assert paths.profile_dir() == home / "profile"
    assert paths.cache_dir() == home / "cache"
    for p in (paths.profile_dir(), paths.cache_dir()):
        assert p.is_absolute()
        assert home in p.parents, f"{p} 应位于用户级数据根目录下"


def test_profile_dir_is_cwd_independent(tmp_path, monkeypatch):
    """核心通用性不变量：换 CWD 不能换 profile。"""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    monkeypatch.chdir(tmp_path)
    first, first_desc = paths.profile_dir(), paths.describe()

    other = tmp_path / "elsewhere"
    other.mkdir()
    monkeypatch.chdir(other)

    assert paths.profile_dir() == first
    assert paths.describe() == first_desc, "describe() 也不该受 CWD 影响"


def test_profile_dir_cli_override(tmp_path):
    custom = tmp_path / "custom-profile"
    paths.set_profile_dir(custom)
    assert paths.profile_dir() == custom


# ---- 输出目录：没有默认值，必须显式给 --------------------------------------


def test_response_dir_has_no_default():
    assert paths.response_dir() is None, "交付物目录不该有默认值"
    with pytest.raises(paths.PathError) as exc:
        paths.resolve_response_dir()
    assert "--response-dir" in str(exc.value)


def test_response_dir_rejects_relative_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    paths.set_response_dir("relative/out")
    with pytest.raises(paths.PathError):
        paths.resolve_response_dir()


def test_response_dir_is_created_on_demand(tmp_path):
    target = tmp_path / "nested" / "out"
    paths.set_response_dir(target)
    assert paths.resolve_response_dir() == target
    assert target.is_dir()


def test_call_argument_wins_over_cli_config(tmp_path):
    configured = tmp_path / "from-cli"
    override = tmp_path / "from-call"
    paths.set_response_dir(configured)

    assert paths.resolve_response_dir(override) == override
    assert not configured.exists(), "被覆盖时不该去碰配置里的那个目录"


def test_path_pointing_at_a_file_is_rejected(tmp_path):
    existing = tmp_path / "not-a-dir"
    existing.write_text("x", encoding="utf-8")
    with pytest.raises(paths.PathError):
        paths.prepare_dir(existing)


# ---- 配置面：只有 CLI，没有环境变量 ----------------------------------------


def test_legacy_env_vars_are_ignored(tmp_path, monkeypatch):
    home = tmp_path / "appdata"
    monkeypatch.setenv("LOCALAPPDATA", str(home))
    for legacy in ("RESPONSE_DIR", "USER_DATA_DIR", "VEDDATA_HOME", "VEDDATA_WORKSPACE"):
        monkeypatch.setenv(legacy, str(tmp_path / "should-be-ignored"))

    assert paths.response_dir() is None
    assert paths.profile_dir() == home / "veddata" / "profile"


# ---- 结构回归：确认删除能力已不存在 ---------------------------------------


def test_paths_exposes_no_deletion_api():
    for name in ("reset", "claim", "OWNER_MARKER"):
        assert not hasattr(paths, name), f"paths.{name} 不应存在（会导致误删）"


def _deletion_machinery(path: Path) -> set[str]:
    """在 AST 层面找真正的删除机制。

    不 grep 源码文本 —— 注释里提到 "rmtree" 说明「为什么不能这么做」是正当的，
    不该被判为违规。只看真实的 import 与调用。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    hits: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] == "shutil":
                    hits.add("import shutil")
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] == "shutil":
                hits.add("from shutil import ...")
        elif isinstance(node, ast.Call):
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if name in {"rmtree", "rmdir"}:
                hits.add(f"{name}()")
    return hits


def test_server_module_has_no_deletion_machinery(tmp_path, monkeypatch):
    """旧版 server 在 import 时 rmtree(RESPONSE_DIR)。

    作为结构性守卫：一旦有人再把删除机制引进 server.py，这个测试会失败，
    迫使做一次有意识的决定。import 本身也不该有任何写盘副作用。
    """
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    import veddata.server  # noqa: F401

    assert _deletion_machinery(Path(veddata.server.__file__)) == set()
