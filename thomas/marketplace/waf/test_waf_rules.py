"""
Tests for WAF Built-in Rules

Tests for rule definitions and pattern matching.
"""

import pytest

from thomas.marketplace.waf._types import HTTPRequest, ThreatLevel, WAFConfig
from thomas.marketplace.waf.engine import WAFEngine
from thomas.marketplace.waf.rules import BuiltInRules


class TestBuiltInRules:
    """Test cases for built-in WAF rules."""

    def test_get_all_rules(self) -> None:
        """Test retrieving all rules."""
        rules = BuiltInRules.get_all_rules()
        assert len(rules) > 0

        # Verify all rules have required attributes
        for rule in rules:
            assert rule.id
            assert rule.name
            assert rule.pattern
            assert rule.action
            assert rule.severity
            assert rule.category

    def test_sql_injection_rules(self) -> None:
        """Test SQL injection rule patterns."""
        rule = BuiltInRules.SQL_INJECTION_UNION

        assert rule.matches("UNION SELECT * FROM users")
        assert rule.matches("union all select")
        assert not rule.matches("select from table")

    def test_sql_injection_or_rule(self) -> None:
        """Test SQL OR 1=1 rule."""
        rule = BuiltInRules.SQL_INJECTION_OR

        assert rule.matches("' OR '1'='1")
        assert rule.matches('" or "1"="1')
        assert not rule.matches("normal query")

    def test_sql_drop_table_rule(self) -> None:
        """Test SQL DROP TABLE rule."""
        rule = BuiltInRules.SQL_INJECTION_DROP

        assert rule.matches("DROP TABLE users")
        assert rule.matches("drop database mydb")
        assert not rule.matches("select table")

    def test_xss_script_tag_rule(self) -> None:
        """Test XSS script tag rule."""
        rule = BuiltInRules.XSS_SCRIPT_TAG

        assert rule.matches("<script>alert(1)</script>")
        assert rule.matches("<SCRIPT>alert('xss')</SCRIPT>")
        assert not rule.matches("normal content")

    def test_xss_event_handler_rule(self) -> None:
        """Test XSS event handler rule."""
        rule = BuiltInRules.XSS_EVENT_HANDLER

        assert rule.matches('onclick="alert(1)"')
        assert rule.matches("onload='doSomething()'")
        assert rule.matches("onmouseover=alert")

    def test_xss_javascript_uri_rule(self) -> None:
        """Test XSS JavaScript URI rule."""
        rule = BuiltInRules.XSS_JAVASCRIPT_URI

        assert rule.matches("javascript:alert(1)")
        assert rule.matches("JAVASCRIPT:void(0)")
        assert not rule.matches("http://example.com")

    def test_path_traversal_rule(self) -> None:
        """Test path traversal rule."""
        rule = BuiltInRules.PATH_TRAVERSAL_DOUBLE_DOT

        assert rule.matches("../../etc/passwd")
        assert rule.matches("../../../windows/system32")
        assert not rule.matches("/home/user/documents")

    def test_path_traversal_encoded_rule(self) -> None:
        """Test encoded path traversal rule."""
        rule = BuiltInRules.PATH_TRAVERSAL_ENCODED

        assert rule.matches("%2e%2e/etc/passwd")
        assert rule.matches(".%2f")
        assert rule.matches("%252e%252e")

    def test_command_injection_pipe_rule(self) -> None:
        """Test command injection pipe rule."""
        rule = BuiltInRules.COMMAND_INJECTION_PIPE

        assert rule.matches("test | cat")
        assert rule.matches("input | ls -la")
        assert not rule.matches("normal input")

    def test_command_injection_semicolon_rule(self) -> None:
        """Test command injection semicolon rule."""
        rule = BuiltInRules.COMMAND_INJECTION_SEMICOLON

        assert rule.matches("; cat /etc/passwd")
        assert rule.matches("; whoami")
        assert not rule.matches("normal input")

    def test_command_injection_backtick_rule(self) -> None:
        """Test command injection backtick rule."""
        rule = BuiltInRules.COMMAND_INJECTION_BACKTICK

        assert rule.matches("`whoami`")
        assert rule.matches("`ls -la`")
        assert not rule.matches("normal text")

    def test_file_inclusion_php_rule(self) -> None:
        """Test PHP wrapper file inclusion rule."""
        rule = BuiltInRules.FILE_INCLUSION_PHP_WRAPPER

        assert rule.matches("php://input")
        assert rule.matches("php://filter/read=convert.base64-encode")
        assert not rule.matches("http://example.com")

    def test_file_inclusion_etc_passwd(self) -> None:
        """Test /etc/passwd inclusion rule."""
        rule = BuiltInRules.FILE_INCLUSION_ETC_PASSWD

        assert rule.matches("/etc/passwd")
        assert rule.matches("/../../../etc/passwd")
        assert not rule.matches("/etc/profile")

    def test_get_rules_by_category(self) -> None:
        """Test filtering rules by category."""
        sql_rules = BuiltInRules.get_rules_by_category("SQL Injection")
        assert len(sql_rules) > 0

        for rule in sql_rules:
            assert rule.category == "SQL Injection"

    def test_get_rules_by_severity(self) -> None:
        """Test filtering rules by severity."""
        critical_rules = BuiltInRules.get_rules_by_severity(ThreatLevel.CRITICAL)
        assert len(critical_rules) > 0

        for rule in critical_rules:
            assert rule.severity == ThreatLevel.CRITICAL

    def test_sql_injection_in_engine(self) -> None:
        """Test SQL injection detection in engine."""
        config = WAFConfig(enable_rate_limiting=False, enable_bot_detection=False)
        engine = WAFEngine(config)

        sql_rules = BuiltInRules.get_rules_by_category("SQL Injection")
        engine.add_rules(sql_rules)

        request = HTTPRequest(
            method="GET",
            path="/search",
            headers={"User-Agent": "Mozilla/5.0"},
            body=b"",
            client_ip="192.168.1.1",
            query_params={"q": "UNION SELECT * FROM users"},
        )

        action, matches, _ = engine.evaluate(request)
        assert len(matches) > 0

    def test_xss_in_engine(self) -> None:
        """Test XSS detection in engine."""
        config = WAFConfig(enable_rate_limiting=False, enable_bot_detection=False)
        engine = WAFEngine(config)

        xss_rules = BuiltInRules.get_rules_by_category("Cross-Site Scripting")
        engine.add_rules(xss_rules)

        request = HTTPRequest(
            method="POST",
            path="/comment",
            headers={"User-Agent": "Mozilla/5.0"},
            body=b"<script>alert(1)</script>",
            client_ip="192.168.1.1",
        )

        action, matches, _ = engine.evaluate(request)
        assert len(matches) > 0

    def test_all_rules_have_patterns(self) -> None:
        """Test that all rules have valid patterns."""
        rules = BuiltInRules.get_all_rules()

        for rule in rules:
            # Try to use the pattern
            try:
                # Should not raise an exception
                rule.matches("test")
            except Exception as e:
                pytest.fail(f"Rule {rule.id} has invalid pattern: {e}")

    def test_rule_matching_case_insensitive(self) -> None:
        """Test case-insensitive pattern matching."""
        rule = BuiltInRules.SQL_INJECTION_UNION

        assert rule.matches("UNION SELECT")
        assert rule.matches("union select")
        assert rule.matches("Union Select")
        assert rule.matches("UnIoN sElEcT")

    def test_file_inclusion_windows_hosts(self) -> None:
        """Test Windows hosts file inclusion."""
        rule = BuiltInRules.FILE_INCLUSION_WINDOWS_HOSTS

        assert rule.matches("windows/system32/drivers/etc/hosts")
        assert rule.matches("WINDOWS\\System32\\drivers\\etc\\hosts")
        assert not rule.matches("C:\\Program Files")
