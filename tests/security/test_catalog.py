"""安全工具 Catalog 测试（scope 门禁 / 注入拦截 / 模板渲染）"""
import pytest

from src.security.catalog import (
    CatalogEntry,
    CatalogError,
    SafeCatalogRunner,
    ScopeNotAuthorizedError,
    load_catalog,
)


@pytest.fixture
def entries():
    return [
        CatalogEntry(
            name="http-headers", description="获取HTTP头", category="recon",
            command="curl -sSI {target}", tags=["http"],
        ),
        CatalogEntry(
            name="port-scan", description="端口扫描", category="scan",
            command="nc -zv {target} {port}", dangerous=True,
        ),
        CatalogEntry(
            name="dns-lookup", description="DNS查询", category="recon",
            command="nslookup {target}", tags=["dns"],
        ),
    ]


@pytest.fixture
def runner(entries):
    r = SafeCatalogRunner(entries=entries)
    r.set_scope(["example.com", "10.0.0.0/24"])
    return r


class TestCatalogLoading:
    def test_load_builtin_catalog(self):
        entries = load_catalog()  # 内置 recon.yaml
        assert len(entries) >= 5
        names = {e.name for e in entries}
        assert "dns-lookup" in names
        assert all(e.description for e in entries)

    def test_missing_required_field(self):
        with pytest.raises(CatalogError, match="缺少必需字段"):
            CatalogEntry.from_dict({"name": "x", "description": "y"})

    def test_search(self, runner):
        assert any(e.name == "http-headers" for e in runner.search("http"))
        assert any(e.name == "dns-lookup" for e in runner.search("recon"))

    def test_by_category(self, runner):
        cats = runner.by_category()
        assert "recon" in cats and "scan" in cats


class TestScopeGate:
    def test_no_scope_blocks(self, entries):
        r = SafeCatalogRunner(entries=entries)  # 不 set_scope
        with pytest.raises(ScopeNotAuthorizedError, match="set_scope"):
            r.run("dns-lookup", target="example.com")

    def test_target_out_of_scope(self, runner):
        with pytest.raises(ScopeNotAuthorizedError, match="不在授权 scope"):
            runner.run("dns-lookup", target="evil.com")

    def test_target_in_scope_domain(self, runner):
        with pytest.raises(CatalogError, match="工具未安装"):  # nslookup 未装或走 mock
            runner.run("dns-lookup", target="sub.example.com")

    def test_cidr_scope(self, runner):
        with pytest.raises(CatalogError):
            runner.run("dns-lookup", target="10.0.0.99")  # CIDR 内，走到 binary 检查

    def test_dangerous_blocked_by_default(self, runner):
        with pytest.raises(CatalogError, match="主动攻击"):
            runner.run("port-scan", target="example.com", port="80")

    def test_dangerous_allowed_explicitly(self, runner):
        runner.allow_dangerous(True)
        with pytest.raises(CatalogError):  # nc 未装 → binary 检查报错（scope 已过）
            runner.run("port-scan", target="example.com", port="80")


class TestCommandRendering:
    def test_render_ok(self, runner):
        entry = runner.search("http-headers")[0]
        cmd = runner.render_command(entry, target="example.com")
        assert cmd == "curl -sSI example.com"

    def test_injection_blocked(self, runner):
        entry = runner.search("http-headers")[0]
        with pytest.raises(CatalogError, match="非法字符"):
            runner.render_command(entry, target="example.com; rm -rf /")

    def test_missing_param(self, runner):
        entry = runner.search("port-scan")[0]
        with pytest.raises(CatalogError, match="缺少参数"):
            runner.render_command(entry, target="example.com")  # 缺 port

    def test_unknown_param(self, runner):
        entry = runner.search("http-headers")[0]
        with pytest.raises(CatalogError, match="不允许的参数"):
            runner.render_command(entry, target="x", evil="y")

    def test_unknown_tool(self, runner):
        with pytest.raises(CatalogError, match="工具不存在"):
            runner.run("no-such-tool", target="example.com")
