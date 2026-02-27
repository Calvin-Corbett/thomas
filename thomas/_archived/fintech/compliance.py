"""
Regulatory compliance and monitoring.

Implements KYC (Know Your Customer) validation, AML (Anti-Money Laundering)
transaction monitoring, trading limits enforcement, pattern detection,
and regulatory reporting structures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum

from ._exceptions import ComplianceError
from ._types import Order, Trade


class KycStatus(str, Enum):
    """KYC verification status."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"


class AmlRiskLevel(str, Enum):
    """AML risk level classification."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class SuspiciousActivityType(str, Enum):
    """Types of suspicious activities."""

    UNUSUAL_VOLUME = "UNUSUAL_VOLUME"
    RAPID_TRANSACTIONS = "RAPID_TRANSACTIONS"
    ROUND_TRIP = "ROUND_TRIP"
    STRUCTURING = "STRUCTURING"
    WASH_TRADE = "WASH_TRADE"
    PATTERN_DAY_TRADER = "PATTERN_DAY_TRADER"
    HIGH_FREQUENCY = "HIGH_FREQUENCY"
    SUSPICIOUS_PRICE = "SUSPICIOUS_PRICE"


@dataclass
class KycProfile:
    """
    KYC profile for a customer.

    Attributes:
        customer_id: Unique customer identifier
        full_name: Customer name
        date_of_birth: Date of birth
        id_type: Identification type
        id_number: Identification number
        address: Residential address
        country: Country of residence
        status: KYC approval status
        risk_level: Customer risk level
        approved_at: Approval timestamp
        expires_at: Expiration timestamp
    """

    customer_id: str
    full_name: str
    date_of_birth: datetime
    id_type: str
    id_number: str
    address: str
    country: str
    status: KycStatus = KycStatus.PENDING
    risk_level: AmlRiskLevel = AmlRiskLevel.MEDIUM
    approved_at: datetime | None = None
    expires_at: datetime | None = None

    def is_approved(self) -> bool:
        """Check if KYC is approved."""
        return self.status == KycStatus.APPROVED

    def is_valid(self, current_date: datetime = None) -> bool:
        """Check if KYC is valid and not expired."""
        if current_date is None:
            current_date = datetime.utcnow()

        if self.status != KycStatus.APPROVED:
            return False

        if self.expires_at and current_date > self.expires_at:
            return False

        return True


@dataclass
class SuspiciousActivity:
    """
    Record of suspicious activity detection.

    Attributes:
        id: Activity ID
        account_id: Account involved
        activity_type: Type of suspicious activity
        risk_level: Risk level assessment
        details: Description of activity
        detected_at: Detection timestamp
        reviewed: Whether it has been reviewed
        reviewed_by: Reviewer ID
        action_taken: Action taken
    """

    id: str
    account_id: str
    activity_type: SuspiciousActivityType
    risk_level: AmlRiskLevel
    details: str
    detected_at: datetime = field(default_factory=datetime.utcnow)
    reviewed: bool = False
    reviewed_by: str | None = None
    action_taken: str | None = None


@dataclass
class TradingLimits:
    """
    Trading limits for an account.

    Attributes:
        account_id: Account identifier
        max_daily_trades: Maximum trades per day
        max_daily_volume: Maximum trading volume per day
        max_position_size: Maximum position size
        max_order_size: Maximum order size
        max_daily_loss: Maximum daily loss
        restricted_symbols: Set of restricted symbols
    """

    account_id: str
    max_daily_trades: int = 1000
    max_daily_volume: Decimal = Decimal("1000000")
    max_position_size: Decimal = Decimal("100000")
    max_order_size: Decimal = Decimal("50000")
    max_daily_loss: Decimal = Decimal("10000")
    restricted_symbols: set[str] = field(default_factory=set)

    def is_symbol_restricted(self, symbol: str) -> bool:
        """Check if symbol is restricted."""
        return symbol in self.restricted_symbols


class ComplianceMonitor:
    """
    Monitor accounts for compliance violations.

    Tracks trading activity and detects patterns indicative of suspicious behavior.
    """

    def __init__(self) -> None:
        """Initialize compliance monitor."""
        self.kyc_profiles: dict[str, KycProfile] = {}
        self.trading_limits: dict[str, TradingLimits] = {}
        self.suspicious_activities: list[SuspiciousActivity] = []
        self.activity_counter = 0
        # Track for suspicious pattern detection
        self.trade_history: dict[str, list[Trade]] = {}
        self.order_history: dict[str, list[Order]] = {}

    def register_kyc(self, profile: KycProfile) -> None:
        """
        Register KYC profile.

        Args:
            profile: KYC profile to register
        """
        self.kyc_profiles[profile.customer_id] = profile

    def approve_kyc(self, customer_id: str) -> bool:
        """
        Approve KYC profile.

        Args:
            customer_id: Customer to approve

        Returns:
            True if approved
        """
        if customer_id not in self.kyc_profiles:
            return False

        profile = self.kyc_profiles[customer_id]
        profile.status = KycStatus.APPROVED
        profile.approved_at = datetime.utcnow()
        return True

    def set_trading_limits(self, limits: TradingLimits) -> None:
        """
        Set trading limits for account.

        Args:
            limits: Trading limits
        """
        self.trading_limits[limits.account_id] = limits

    def check_kyc_compliance(self, customer_id: str) -> bool:
        """
        Check KYC compliance for customer.

        Args:
            customer_id: Customer ID

        Returns:
            True if customer is KYC compliant

        Raises:
            ComplianceError: If customer is not approved
        """
        if customer_id not in self.kyc_profiles:
            raise ComplianceError(
                "KYC_MISSING",
                f"No KYC profile for {customer_id}",
            )

        profile = self.kyc_profiles[customer_id]
        if not profile.is_valid():
            raise ComplianceError(
                "KYC_INVALID",
                f"KYC not approved or expired for {customer_id}",
            )

        return True

    def check_trading_limits(self, account_id: str, order: Order) -> bool:
        """
        Check if order complies with trading limits.

        Args:
            account_id: Account ID
            order: Order to check

        Returns:
            True if order is compliant

        Raises:
            ComplianceError: If order violates limits
        """
        if account_id not in self.trading_limits:
            return True

        limits = self.trading_limits[account_id]

        # Check restricted symbols
        if limits.is_symbol_restricted(order.symbol):
            raise ComplianceError(
                "RESTRICTED_SYMBOL",
                f"{order.symbol} is restricted for {account_id}",
            )

        # Check order size
        notional = order.get_notional_value() if order.price else Decimal("0")
        if notional > limits.max_order_size:
            raise ComplianceError(
                "ORDER_SIZE_EXCEEDED",
                f"Order notional {notional} exceeds max {limits.max_order_size}",
            )

        return True

    def record_trade(self, account_id: str, trade: Trade) -> None:
        """
        Record trade for monitoring.

        Args:
            account_id: Account ID
            trade: Trade to record
        """
        if account_id not in self.trade_history:
            self.trade_history[account_id] = []

        self.trade_history[account_id].append(trade)

    def record_order(self, account_id: str, order: Order) -> None:
        """
        Record order for monitoring.

        Args:
            account_id: Account ID
            order: Order to record
        """
        if account_id not in self.order_history:
            self.order_history[account_id] = []

        self.order_history[account_id].append(order)

    def detect_wash_trades(self, account_id: str, lookback_minutes: int = 60) -> list[tuple]:
        """
        Detect potential wash trades (buying and selling same security rapidly).

        Args:
            account_id: Account to check
            lookback_minutes: Time window in minutes

        Returns:
            List of (trade1, trade2) tuples that are potential wash trades
        """
        if account_id not in self.trade_history:
            return []

        trades = self.trade_history[account_id]
        suspicious_pairs = []
        cutoff_time = datetime.utcnow().timestamp() - (lookback_minutes * 60)

        for i, trade1 in enumerate(trades):
            if trade1.timestamp.timestamp() < cutoff_time:
                continue

            for trade2 in trades[i + 1 :]:
                if trade2.timestamp.timestamp() < cutoff_time:
                    continue

                # Same symbol, opposite sides, within time window
                if (
                    trade1.symbol == trade2.symbol
                    and trade1.price == trade2.price
                    and trade1.timestamp.timestamp() - trade2.timestamp.timestamp() <= lookback_minutes * 60
                ):
                    suspicious_pairs.append((trade1, trade2))

        return suspicious_pairs

    def detect_pattern_day_trader(self, account_id: str, lookback_days: int = 5) -> bool:
        """
        Detect pattern day trader (4+ round trips in 5 days).

        Args:
            account_id: Account to check
            lookback_days: Look back period in days

        Returns:
            True if account appears to be pattern day trader
        """
        if account_id not in self.trade_history:
            return False

        trades = self.trade_history[account_id]
        cutoff_time = datetime.utcnow().timestamp() - (lookback_days * 86400)

        round_trip_count = 0
        processed = set()

        for i, trade1 in enumerate(trades):
            if trade1.timestamp.timestamp() < cutoff_time:
                continue

            if trade1.id in processed:
                continue

            # Find corresponding opposite trade
            for j, trade2 in enumerate(trades[i + 1 :], i + 1):
                if trade2.timestamp.timestamp() < cutoff_time:
                    continue

                if trade1.symbol == trade2.symbol and trade1.timestamp <= trade2.timestamp:
                    round_trip_count += 1
                    processed.add(trade1.id)
                    processed.add(trade2.id)
                    break

        return round_trip_count >= 4

    def flag_suspicious_activity(
        self,
        account_id: str,
        activity_type: SuspiciousActivityType,
        risk_level: AmlRiskLevel,
        details: str,
    ) -> SuspiciousActivity:
        """
        Flag suspicious activity.

        Args:
            account_id: Account involved
            activity_type: Type of activity
            risk_level: Risk level
            details: Description

        Returns:
            Suspicious activity record
        """
        self.activity_counter += 1
        activity = SuspiciousActivity(
            id=f"SAR-{self.activity_counter:08d}",
            account_id=account_id,
            activity_type=activity_type,
            risk_level=risk_level,
            details=details,
        )

        self.suspicious_activities.append(activity)
        return activity

    def get_suspicious_activities(
        self,
        account_id: str | None = None,
        reviewed: bool | None = None,
    ) -> list[SuspiciousActivity]:
        """
        Get suspicious activities.

        Args:
            account_id: Optional account filter
            reviewed: Optional reviewed status filter

        Returns:
            List of suspicious activities
        """
        activities = self.suspicious_activities

        if account_id:
            activities = [a for a in activities if a.account_id == account_id]

        if reviewed is not None:
            activities = [a for a in activities if a.reviewed == reviewed]

        return activities
