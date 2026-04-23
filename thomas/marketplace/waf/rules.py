"""
Built-in WAF Rules

Comprehensive rule implementations for detecting common attacks:
- SQL Injection
- Cross-Site Scripting (XSS)
- Path Traversal
- Command Injection
- Protocol Violations
- File Inclusion
"""

from thomas.marketplace.waf._types import RuleAction, ThreatLevel, WAFRule


class BuiltInRules:
    """Built-in WAF rule implementations."""

    # SQL Injection Rules
    SQL_INJECTION_UNION = WAFRule(
        id="sql_001",
        name="SQL UNION SELECT Detection",
        pattern=r"(?i)\bunion\s+(?:all\s+)?select\b",
        action=RuleAction.BLOCK,
        severity=ThreatLevel.HIGH,
        category="SQL Injection",
        priority=10,
        variables=["ARGS", "REQUEST_URI", "BODY"],
    )

    SQL_INJECTION_OR = WAFRule(
        id="sql_002",
        name="SQL OR 1=1 Detection",
        pattern=r"(?i)(\'\s*or\s*[\'\"]?\s*1\s*=\s*1|\"\s*or\s*[\'\"]?\s*1\s*=\s*1)",
        action=RuleAction.BLOCK,
        severity=ThreatLevel.HIGH,
        category="SQL Injection",
        priority=11,
        variables=["ARGS", "REQUEST_URI", "BODY"],
    )

    SQL_INJECTION_DROP = WAFRule(
        id="sql_003",
        name="SQL DROP TABLE Detection",
        pattern=r"(?i)\bdrop\s+(?:table|database|schema|index)\b",
        action=RuleAction.BLOCK,
        severity=ThreatLevel.CRITICAL,
        category="SQL Injection",
        priority=9,
        variables=["ARGS", "REQUEST_URI", "BODY"],
    )

    SQL_INJECTION_EXEC = WAFRule(
        id="sql_004",
        name="SQL EXEC/EXECUTE Detection",
        pattern=r"(?i)\b(exec|execute)\s*\(",
        action=RuleAction.BLOCK,
        severity=ThreatLevel.CRITICAL,
        category="SQL Injection",
        priority=9,
        variables=["ARGS", "REQUEST_URI", "BODY"],
    )

    SQL_INJECTION_COMMENT = WAFRule(
        id="sql_005",
        name="SQL Comment Injection Detection",
        pattern=r"(?i)(--|#|/\*|\*/)",
        action=RuleAction.LOG,
        severity=ThreatLevel.MEDIUM,
        category="SQL Injection",
        priority=20,
        variables=["ARGS", "REQUEST_URI", "BODY"],
    )

    SQL_INJECTION_INTO = WAFRule(
        id="sql_006",
        name="SQL INTO OUTFILE Detection",
        pattern=r"(?i)into\s+(?:outfile|dumpfile)",
        action=RuleAction.BLOCK,
        severity=ThreatLevel.HIGH,
        category="SQL Injection",
        priority=10,
        variables=["ARGS", "REQUEST_URI", "BODY"],
    )

    # XSS Rules
    XSS_SCRIPT_TAG = WAFRule(
        id="xss_001",
        name="XSS Script Tag Detection",
        pattern=r"<\s*script[^>]*>.*?<\s*/\s*script\s*>",
        action=RuleAction.BLOCK,
        severity=ThreatLevel.HIGH,
        category="Cross-Site Scripting",
        priority=10,
        variables=["ARGS", "REQUEST_URI", "BODY"],
        transformations=["htmlDecode"],
    )

    XSS_EVENT_HANDLER = WAFRule(
        id="xss_002",
        name="XSS Event Handler Detection",
        pattern=r"on\w+\s*=\s*[\"']?[^>]*[\"']?",
        action=RuleAction.BLOCK,
        severity=ThreatLevel.HIGH,
        category="Cross-Site Scripting",
        priority=11,
        variables=["ARGS", "REQUEST_URI", "BODY"],
        transformations=["htmlDecode"],
    )

    XSS_JAVASCRIPT_URI = WAFRule(
        id="xss_003",
        name="XSS JavaScript URI Detection",
        pattern=r"(?i)javascript\s*:",
        action=RuleAction.BLOCK,
        severity=ThreatLevel.HIGH,
        category="Cross-Site Scripting",
        priority=10,
        variables=["ARGS", "REQUEST_URI", "BODY"],
    )

    XSS_DATA_URI = WAFRule(
        id="xss_004",
        name="XSS Data URI Detection",
        pattern=r"(?i)data\s*:",
        action=RuleAction.LOG,
        severity=ThreatLevel.MEDIUM,
        category="Cross-Site Scripting",
        priority=20,
        variables=["ARGS", "REQUEST_URI", "BODY"],
    )

    XSS_IMG_VECTOR = WAFRule(
        id="xss_005",
        name="XSS Image Tag Vector Detection",
        pattern=r"<\s*img[^>]*(?:on\w+|src\s*=\s*[\"']?javascript)",
        action=RuleAction.BLOCK,
        severity=ThreatLevel.HIGH,
        category="Cross-Site Scripting",
        priority=10,
        variables=["ARGS", "REQUEST_URI", "BODY"],
        transformations=["htmlDecode"],
    )

    XSS_SVG_VECTOR = WAFRule(
        id="xss_006",
        name="XSS SVG Vector Detection",
        pattern=r"<\s*svg[^>]*>",
        action=RuleAction.LOG,
        severity=ThreatLevel.MEDIUM,
        category="Cross-Site Scripting",
        priority=20,
        variables=["ARGS", "REQUEST_URI", "BODY"],
        transformations=["htmlDecode"],
    )

    XSS_IFRAME_VECTOR = WAFRule(
        id="xss_007",
        name="XSS IFrame Vector Detection",
        pattern=r"<\s*iframe[^>]*>",
        action=RuleAction.BLOCK,
        severity=ThreatLevel.HIGH,
        category="Cross-Site Scripting",
        priority=10,
        variables=["ARGS", "REQUEST_URI", "BODY"],
        transformations=["htmlDecode"],
    )

    # Path Traversal Rules
    PATH_TRAVERSAL_DOUBLE_DOT = WAFRule(
        id="pt_001",
        name="Path Traversal Double Dot Detection",
        pattern=r"\.\./",
        action=RuleAction.BLOCK,
        severity=ThreatLevel.HIGH,
        category="Path Traversal",
        priority=10,
        variables=["REQUEST_URI", "ARGS"],
    )

    PATH_TRAVERSAL_ENCODED = WAFRule(
        id="pt_002",
        name="Path Traversal Encoded Detection",
        pattern=r"(?i)(%2e%2e/|\.%2f|%252e%252e)",
        action=RuleAction.BLOCK,
        severity=ThreatLevel.HIGH,
        category="Path Traversal",
        priority=10,
        variables=["REQUEST_URI", "ARGS"],
    )

    PATH_TRAVERSAL_NULL_BYTE = WAFRule(
        id="pt_003",
        name="Path Traversal Null Byte Detection",
        pattern=r"%00|\\x00",
        action=RuleAction.BLOCK,
        severity=ThreatLevel.HIGH,
        category="Path Traversal",
        priority=9,
        variables=["REQUEST_URI", "ARGS"],
    )

    PATH_TRAVERSAL_BACKSLASH = WAFRule(
        id="pt_004",
        name="Path Traversal Backslash Detection",
        pattern=r"\.\.\\/",
        action=RuleAction.BLOCK,
        severity=ThreatLevel.HIGH,
        category="Path Traversal",
        priority=10,
        variables=["REQUEST_URI", "ARGS"],
    )

    # Command Injection Rules
    COMMAND_INJECTION_PIPE = WAFRule(
        id="cmd_001",
        name="Command Injection Pipe Detection",
        pattern=r"[^\\]\|\s*\w+",
        action=RuleAction.BLOCK,
        severity=ThreatLevel.CRITICAL,
        category="Command Injection",
        priority=9,
        variables=["ARGS", "REQUEST_URI", "BODY"],
    )

    COMMAND_INJECTION_SEMICOLON = WAFRule(
        id="cmd_002",
        name="Command Injection Semicolon Detection",
        pattern=r";\s*(?:cat|ls|whoami|id|pwd|uname)",
        action=RuleAction.BLOCK,
        severity=ThreatLevel.CRITICAL,
        category="Command Injection",
        priority=9,
        variables=["ARGS", "REQUEST_URI", "BODY"],
    )

    COMMAND_INJECTION_BACKTICK = WAFRule(
        id="cmd_003",
        name="Command Injection Backtick Detection",
        pattern=r"`[^`]*`",
        action=RuleAction.BLOCK,
        severity=ThreatLevel.CRITICAL,
        category="Command Injection",
        priority=9,
        variables=["ARGS", "REQUEST_URI", "BODY"],
    )

    COMMAND_INJECTION_DOLLAR_PAREN = WAFRule(
        id="cmd_004",
        name="Command Injection $() Detection",
        pattern=r"\$\([^)]*\)",
        action=RuleAction.BLOCK,
        severity=ThreatLevel.CRITICAL,
        category="Command Injection",
        priority=9,
        variables=["ARGS", "REQUEST_URI", "BODY"],
    )

    # Protocol Violation Rules
    HTTP_METHOD_INVALID = WAFRule(
        id="proto_001",
        name="Invalid HTTP Method Detection",
        pattern=r"^(?!GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS|TRACE|CONNECT)[\w]+$",
        action=RuleAction.LOG,
        severity=ThreatLevel.LOW,
        category="Protocol Violation",
        priority=50,
        variables=["METHOD"],
    )

    CONTENT_LENGTH_MISMATCH = WAFRule(
        id="proto_002",
        name="Content-Length Mismatch Detection",
        pattern=r"^-\d+$",
        action=RuleAction.LOG,
        severity=ThreatLevel.MEDIUM,
        category="Protocol Violation",
        priority=40,
        variables=["ARGS"],  # Placeholder
    )

    HTTP_REQUEST_SMUGGLING = WAFRule(
        id="proto_003",
        name="HTTP Request Smuggling Detection",
        pattern=r"(?i)transfer-encoding.*chunked",
        action=RuleAction.LOG,
        severity=ThreatLevel.MEDIUM,
        category="Protocol Violation",
        priority=40,
        variables=["HEADERS"],
    )

    # File Inclusion Rules
    FILE_INCLUSION_PHP_WRAPPER = WAFRule(
        id="fi_001",
        name="PHP Wrapper File Inclusion Detection",
        pattern=r"(?i)php://",
        action=RuleAction.BLOCK,
        severity=ThreatLevel.HIGH,
        category="File Inclusion",
        priority=10,
        variables=["REQUEST_URI", "ARGS"],
    )

    FILE_INCLUSION_EXPECT = WAFRule(
        id="fi_002",
        name="Expect Wrapper File Inclusion Detection",
        pattern=r"(?i)expect://",
        action=RuleAction.BLOCK,
        severity=ThreatLevel.CRITICAL,
        category="File Inclusion",
        priority=9,
        variables=["REQUEST_URI", "ARGS"],
    )

    FILE_INCLUSION_ETC_PASSWD = WAFRule(
        id="fi_003",
        name="/etc/passwd File Inclusion Detection",
        pattern=r"/etc/passwd",
        action=RuleAction.BLOCK,
        severity=ThreatLevel.HIGH,
        category="File Inclusion",
        priority=10,
        variables=["REQUEST_URI", "ARGS"],
    )

    FILE_INCLUSION_WINDOWS_HOSTS = WAFRule(
        id="fi_004",
        name="Windows Hosts File Inclusion Detection",
        pattern=r"(?i)windows/system32/drivers/etc/hosts",
        action=RuleAction.BLOCK,
        severity=ThreatLevel.HIGH,
        category="File Inclusion",
        priority=10,
        variables=["REQUEST_URI", "ARGS"],
    )

    @classmethod
    def get_all_rules(cls) -> list[WAFRule]:
        """
        Get all built-in rules.

        Returns:
            List of all WAFRule objects
        """
        rules = []
        for attr_name in dir(cls):
            attr = getattr(cls, attr_name)
            if isinstance(attr, WAFRule):
                rules.append(attr)
        return rules

    @classmethod
    def get_rules_by_category(cls, category: str) -> list[WAFRule]:
        """
        Get rules by category.

        Args:
            category: Rule category name

        Returns:
            List of matching WAFRule objects
        """
        all_rules = cls.get_all_rules()
        return [r for r in all_rules if r.category == category]

    @classmethod
    def get_rules_by_severity(cls, severity: ThreatLevel) -> list[WAFRule]:
        """
        Get rules by severity level.

        Args:
            severity: ThreatLevel to filter by

        Returns:
            List of matching WAFRule objects
        """
        all_rules = cls.get_all_rules()
        return [r for r in all_rules if r.severity == severity]
