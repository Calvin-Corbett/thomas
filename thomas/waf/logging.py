"""
WAF Logging Module

Request/response logging, alert logging, audit trails, and log rotation.
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from thomas.waf._types import HTTPRequest, RuleAction, RuleMatch


class WAFLogger:
    """
    WAF logging for requests, responses, and alerts.

    Features:
    - Request/response logging
    - Alert logging with severity
    - Audit log trails
    - Multiple log formats (JSON, Apache combined)
    - Log rotation
    - Sensitive data redaction
    - Log statistics
    """

    # Patterns for sensitive data redaction
    SENSITIVE_PATTERNS = [
        (r"(?i)password['\"]?\s*[:=]\s*['\"]?[^'\"&\s]+['\"]?", "password=[REDACTED]"),
        (r"(?i)api[_-]?key['\"]?\s*[:=]\s*['\"]?[^'\"&\s]+['\"]?", "api_key=[REDACTED]"),
        (r"(?i)auth[_-]?token['\"]?\s*[:=]\s*['\"]?[^'\"&\s]+['\"]?", "auth_token=[REDACTED]"),
        (r"(?i)credit[_-]?card['\"]?\s*[:=]\s*['\"]?\d{4}-?\d{4}-?\d{4}-?\d{4}", "credit_card=[REDACTED]"),
        (r"\b\d{3}-\d{2}-\d{4}\b", "[REDACTED_SSN]"),
        (r"Bearer\s+[^\s]+", "Bearer [REDACTED]"),
    ]

    def __init__(self, log_dir: str = "./logs") -> None:
        """
        Initialize WAF logger.

        Args:
            log_dir: Directory for log files
        """
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.request_log_path = self.log_dir / "waf_requests.log"
        self.alert_log_path = self.log_dir / "waf_alerts.log"
        self.audit_log_path = self.log_dir / "waf_audit.log"

        self.request_logger = logging.getLogger("waf.requests")
        self.alert_logger = logging.getLogger("waf.alerts")
        self.audit_logger = logging.getLogger("waf.audit")

        self._setup_loggers()

        self.stats = {
            "requests_logged": 0,
            "alerts_logged": 0,
            "blocked_requests": 0,
            "challenged_requests": 0,
        }

    def _setup_loggers(self) -> None:
        """Setup logger handlers."""
        # Request logger
        request_handler = logging.FileHandler(self.request_log_path)
        request_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        self.request_logger.addHandler(request_handler)
        self.request_logger.setLevel(logging.INFO)

        # Alert logger
        alert_handler = logging.FileHandler(self.alert_log_path)
        alert_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s - [%(levelname)s] - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        self.alert_logger.addHandler(alert_handler)
        self.alert_logger.setLevel(logging.WARNING)

        # Audit logger
        audit_handler = logging.FileHandler(self.audit_log_path)
        audit_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        self.audit_logger.addHandler(audit_handler)
        self.audit_logger.setLevel(logging.INFO)

    def log_request(
        self,
        request: HTTPRequest,
        action: RuleAction,
        matches: list[RuleMatch],
    ) -> None:
        """
        Log HTTP request.

        Args:
            request: HTTP request
            action: Action taken
            matches: Matched rules
        """
        # Build log entry
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "method": request.method,
            "path": request.path,
            "client_ip": request.client_ip,
            "user_agent": request.user_agent,
            "action": action.value,
            "matched_rules": len(matches),
        }

        if matches:
            log_entry["rules"] = [
                {
                    "id": m.rule_id,
                    "name": m.rule_name,
                    "severity": m.severity.name,
                }
                for m in matches
            ]

        # Log as JSON
        self.request_logger.info(json.dumps(log_entry))
        self.stats["requests_logged"] += 1

        # Track action types
        if action == RuleAction.BLOCK:
            self.stats["blocked_requests"] += 1
        elif action == RuleAction.CHALLENGE:
            self.stats["challenged_requests"] += 1

    def log_alert(
        self,
        ip_address: str,
        alert_type: str,
        severity: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        Log security alert.

        Args:
            ip_address: Client IP
            alert_type: Type of alert
            severity: Alert severity (INFO, WARNING, ERROR, CRITICAL)
            message: Alert message
            details: Additional details dictionary
        """
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "ip": ip_address,
            "type": alert_type,
            "severity": severity,
            "message": message,
        }

        if details:
            log_entry["details"] = details

        level = {
            "INFO": logging.INFO,
            "WARNING": logging.WARNING,
            "ERROR": logging.ERROR,
            "CRITICAL": logging.CRITICAL,
        }.get(severity, logging.WARNING)

        self.alert_logger.log(level, json.dumps(log_entry))
        self.stats["alerts_logged"] += 1

    def log_audit(
        self,
        action: str,
        user: str,
        resource: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        Log audit trail entry.

        Args:
            action: Action performed
            user: User performing action
            resource: Resource affected
            details: Additional details
        """
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "action": action,
            "user": user,
            "resource": resource,
        }

        if details:
            log_entry["details"] = details

        self.audit_logger.info(json.dumps(log_entry))

    def redact_sensitive_data(self, text: str) -> str:
        """
        Redact sensitive data from text.

        Args:
            text: Text to redact

        Returns:
            Text with sensitive data redacted
        """
        result = text

        for pattern, replacement in self.SENSITIVE_PATTERNS:
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

        return result

    def get_apache_combined_log(
        self,
        request: HTTPRequest,
        status_code: int = 200,
        response_size: int = 0,
    ) -> str:
        """
        Format log entry in Apache combined log format.

        Args:
            request: HTTP request
            status_code: Response status code
            response_size: Response size in bytes

        Returns:
            Formatted log line
        """
        timestamp = datetime.utcnow().strftime("%d/%b/%Y %H:%M:%S %z")

        log_line = (
            f"{request.client_ip} - - [{timestamp}] "
            f'"{request.method} {request.path} HTTP/1.1" '
            f"{status_code} {response_size} "
            f'"-" "{request.user_agent}"'
        )

        return log_line

    def rotate_logs(self) -> dict[str, bool]:
        """
        Rotate log files.

        Returns:
            Dictionary indicating which logs were rotated
        """
        rotated = {
            "requests": False,
            "alerts": False,
            "audit": False,
        }

        # Simple rotation: rename current log and create new one
        if self.request_log_path.exists():
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            backup = self.request_log_path.with_name(f"waf_requests_{timestamp}.log")
            self.request_log_path.rename(backup)
            rotated["requests"] = True

        if self.alert_log_path.exists():
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            backup = self.alert_log_path.with_name(f"waf_alerts_{timestamp}.log")
            self.alert_log_path.rename(backup)
            rotated["alerts"] = True

        if self.audit_log_path.exists():
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            backup = self.audit_log_path.with_name(f"waf_audit_{timestamp}.log")
            self.audit_log_path.rename(backup)
            rotated["audit"] = True

        # Reinitialize loggers
        self._setup_loggers()

        return rotated

    def get_statistics(self) -> dict[str, int]:
        """
        Get logging statistics.

        Returns:
            Statistics dictionary
        """
        return self.stats.copy()

    def clear_statistics(self) -> None:
        """Clear statistics."""
        for key in self.stats:
            self.stats[key] = 0
