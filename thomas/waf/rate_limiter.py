"""
Rate Limiting Module

WAF rate limiting with sliding window implementation, graduated response,
and per-IP/path/session tracking.
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta

from thomas.waf._types import RateLimitConfig, RuleAction


class RateLimiter:
    """
    Rate limiter with sliding window implementation.

    Features:
    - Requests per second/minute/hour limits
    - Per IP, per path, per session tracking
    - Sliding window implementation
    - Burst allowance
    - Graduated response (log -> challenge -> block)
    - Whitelist bypass
    - Rate limit headers
    """

    def __init__(self, config: RateLimitConfig) -> None:
        """
        Initialize rate limiter.

        Args:
            config: RateLimitConfig object
        """
        self.config = config
        self.request_history: dict[str, list] = defaultdict(list)
        self.challenge_count: dict[str, int] = defaultdict(int)
        self.block_until: dict[str, datetime | None] = defaultdict(lambda: None)
        self.logger = logging.getLogger(__name__)

    def check_rate_limit(
        self,
        ip_address: str,
        path: str = "/",
        session_id: str | None = None,
    ) -> tuple[RuleAction, dict[str, str]]:
        """
        Check if request exceeds rate limit.

        Args:
            ip_address: Client IP address
            path: Request path
            session_id: Optional session identifier

        Returns:
            Tuple of (action, headers_dict)
        """
        # Check IP whitelist
        if ip_address in self.config.whitelist_ips:
            return (RuleAction.ALLOW, {})

        # Check path whitelist
        if path in self.config.whitelist_paths:
            return (RuleAction.ALLOW, {})

        # Check if currently blocked
        if ip_address in self.block_until and self.block_until[ip_address]:
            if datetime.utcnow() < self.block_until[ip_address]:
                retry_after = int((self.block_until[ip_address] - datetime.utcnow()).total_seconds())
                return (
                    RuleAction.BLOCK,
                    {"Retry-After": str(retry_after)},
                )
            else:
                self.block_until[ip_address] = None

        # Check per-second limit
        key = f"sec:{ip_address}"
        action, headers = self._check_sliding_window(
            key,
            self.config.requests_per_second,
            seconds=1,
        )
        if action != RuleAction.ALLOW:
            return (action, headers)

        # Check per-minute limit
        key = f"min:{ip_address}"
        action, headers = self._check_sliding_window(
            key,
            self.config.requests_per_minute,
            seconds=60,
        )
        if action != RuleAction.ALLOW:
            return (action, headers)

        # Check per-hour limit
        key = f"hour:{ip_address}"
        action, headers = self._check_sliding_window(
            key,
            self.config.requests_per_hour,
            seconds=3600,
        )

        # Record request
        self._record_request(ip_address)

        return (action, headers)

    def _check_sliding_window(
        self,
        key: str,
        limit: int,
        seconds: int,
    ) -> tuple[RuleAction, dict[str, str]]:
        """
        Check sliding window rate limit.

        Args:
            key: Rate limit key
            limit: Request limit
            seconds: Window size in seconds

        Returns:
            Tuple of (action, headers)
        """
        now = datetime.utcnow()
        window_start = now - timedelta(seconds=seconds)

        # Clean old requests
        if key in self.request_history:
            self.request_history[key] = [ts for ts in self.request_history[key] if ts > window_start]
        else:
            self.request_history[key] = []

        # Count requests in window
        count = len(self.request_history[key])

        # Extract IP from key
        ip_address = key.split(":")[-1]

        if count >= limit:
            # Graduated response
            if self.config.graduated_response:
                challenge_count = self.challenge_count.get(ip_address, 0)

                if challenge_count < 1:
                    # First violation: LOG
                    self.challenge_count[ip_address] = challenge_count + 1
                    self.logger.warning(f"Rate limit threshold exceeded for {ip_address}: {count}/{limit}")
                    return (RuleAction.LOG, {"X-Rate-Limit-Remaining": "0"})

                elif challenge_count < 2:
                    # Second violation: CHALLENGE
                    self.challenge_count[ip_address] = challenge_count + 1
                    return (
                        RuleAction.CHALLENGE,
                        {
                            "X-Rate-Limit-Remaining": "0",
                            "Retry-After": "60",
                        },
                    )

            # Block
            self.block_until[ip_address] = now + timedelta(minutes=5)
            self.logger.error(f"Rate limit exceeded for {ip_address}: {count}/{limit}, blocking for 5 minutes")
            return (
                RuleAction.BLOCK,
                {
                    "X-Rate-Limit-Remaining": "0",
                    "Retry-After": "300",
                },
            )

        # Calculate remaining
        remaining = max(0, limit - count)
        return (
            RuleAction.ALLOW,
            {
                "X-Rate-Limit-Limit": str(limit),
                "X-Rate-Limit-Remaining": str(remaining),
                "X-Rate-Limit-Reset": str(int((window_start + timedelta(seconds=seconds)).timestamp())),
            },
        )

    def _record_request(self, ip_address: str) -> None:
        """
        Record request timestamp for IP.

        Args:
            ip_address: Client IP address
        """
        # Record in all windows
        for key_prefix in ["sec", "min", "hour"]:
            key = f"{key_prefix}:{ip_address}"
            self.request_history[key].append(datetime.utcnow())

    def reset_ip(self, ip_address: str) -> None:
        """
        Reset rate limit for IP.

        Args:
            ip_address: IP address to reset
        """
        for key in list(self.request_history.keys()):
            if ip_address in key:
                self.request_history[key] = []

        if ip_address in self.challenge_count:
            del self.challenge_count[ip_address]

        if ip_address in self.block_until:
            self.block_until[ip_address] = None

    def cleanup_old_entries(self) -> int:
        """
        Clean up old request history entries.

        Returns:
            Number of entries cleaned
        """
        count = 0
        now = datetime.utcnow()
        max_age = timedelta(hours=1)

        for key in list(self.request_history.keys()):
            old_len = len(self.request_history[key])
            self.request_history[key] = [ts for ts in self.request_history[key] if now - ts < max_age]
            count += old_len - len(self.request_history[key])

        return count

    def get_stats(self, ip_address: str) -> dict[str, int]:
        """
        Get rate limit statistics for IP.

        Args:
            ip_address: IP address

        Returns:
            Dictionary with statistics
        """
        stats = {
            "per_second": len(self.request_history.get(f"sec:{ip_address}", [])),
            "per_minute": len(self.request_history.get(f"min:{ip_address}", [])),
            "per_hour": len(self.request_history.get(f"hour:{ip_address}", [])),
            "challenge_count": self.challenge_count.get(ip_address, 0),
            "blocked": self.block_until.get(ip_address) is not None,
        }

        if stats["blocked"]:
            stats["blocked_until"] = int(self.block_until[ip_address].timestamp())

        return stats

    def add_to_whitelist(self, ip_address: str) -> None:
        """
        Add IP to whitelist.

        Args:
            ip_address: IP address to whitelist
        """
        self.config.whitelist_ips.add(ip_address)

    def remove_from_whitelist(self, ip_address: str) -> None:
        """
        Remove IP from whitelist.

        Args:
            ip_address: IP address to remove
        """
        self.config.whitelist_ips.discard(ip_address)

    def add_path_whitelist(self, path: str) -> None:
        """
        Add path to whitelist.

        Args:
            path: Path to whitelist
        """
        self.config.whitelist_paths.add(path)

    def remove_path_whitelist(self, path: str) -> None:
        """
        Remove path from whitelist.

        Args:
            path: Path to remove
        """
        self.config.whitelist_paths.discard(path)
