"""naming 模块测试 —— 站点名解析与输出文件名主干。

命名规则：``<站点名>_<接口名>_<YYYYMMDD-HHMMSS>``。站点名只做"简单定位"：
去掉前导 ``www.``、去掉公共后缀、取剩下最后一段，所以同一站点的子域都归到同一个名字。
"""

from datetime import datetime

from veddata import naming


def test_site_name_strips_www_and_public_suffix():
    assert naming.site_name("https://www.example.com/api/x") == "example"
    assert naming.site_name("http://example.com") == "example"
    assert naming.site_name("https://api.example.com/v2/list") == "example"
    assert naming.site_name("https://cdn.deep.example.com/x") == "example"


def test_site_name_handles_two_level_suffixes():
    assert naming.site_name("https://www.example.com.cn/a") == "example"
    assert naming.site_name("https://shop.example.co.uk/a") == "example"


def test_site_name_edge_cases():
    assert naming.site_name("") == "unknown"
    assert naming.site_name("https://127.0.0.1:8080/x") == "127.0.0.1"
    assert naming.site_name("https://localhost:3000/") == "localhost"
    assert naming.site_name("https://WWW.Example.COM/") == "example", "大小写归一"


def test_endpoint_name_uses_last_path_segment():
    assert naming.endpoint_name("https://www.example.com/api/v2/users") == "users"
    assert naming.endpoint_name("https://www.example.com/api/users?page=2") == "users"
    assert naming.endpoint_name("https://www.example.com/") == "response"


def test_stamp_is_sortable_and_filename_safe():
    assert naming.stamp(datetime(2026, 9, 10, 18, 30, 45)) == "20260910-183045"


def test_export_stem_shape():
    site, endpoint, ts = naming.export_stem("https://www.example.com/api/users").split("_")
    assert (site, endpoint) == ("example", "users")
    assert len(ts) == 15 and ts[8] == "-"


def test_shot_stem_with_and_without_prefix():
    plain = naming.shot_stem("https://www.example.com/a")
    assert plain.startswith("example_")
    assert naming.shot_stem("https://www.example.com/a", "登录页").startswith("example_")
    assert naming.shot_stem("https://www.example.com/a", "after login").startswith("after-login_example_")


def test_unique_path_avoids_collision(tmp_path):
    stem = "example_users_20260910-183045"

    first = naming.unique_path(tmp_path, stem, ".json")
    assert first.name == f"{stem}.json"

    first.write_text("{}", encoding="utf-8")
    second = naming.unique_path(tmp_path, stem, ".json")
    assert second.name == f"{stem}-2.json", "同秒重复导出才追加序号"
