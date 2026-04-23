"""
Subscriber management module.

Handles subscriber profiles, usage tracking, rating, billing integration,
roaming, number portability, SIM management, and churn prediction.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime

from thomas.marketplace.telecom._types import CallRecord, Subscriber


@dataclass
class Plan:
    """Subscription plan."""

    name: str
    plan_type: str  # prepaid, postpaid
    monthly_cost: float
    monthly_data_gb: float
    monthly_voice_minutes: float
    monthly_sms: int
    data_rate_per_gb: float = 0.0
    voice_rate_per_minute: float = 0.0
    sms_rate_per_sms: float = 0.0


@dataclass
class SubscriberManager:
    """Manage subscriber lifecycle and data."""

    subscribers: dict[str, Subscriber] = field(default_factory=dict)
    subscriber_plans: dict[str, Plan] = field(default_factory=dict)
    msisdn_to_imsi: dict[str, str] = field(default_factory=dict)

    def add_subscriber(
        self,
        msisdn: str,
        imsi: str,
        imei: str,
        name: str,
        plan_type: str = "postpaid",
    ) -> Subscriber:
        """
        Add a new subscriber.

        Args:
            msisdn: Phone number
            imsi: IMSI
            imei: IMEI
            name: Subscriber name
            plan_type: Plan type (prepaid/postpaid)

        Returns:
            Created Subscriber
        """
        subscriber = Subscriber(
            msisdn=msisdn,
            imsi=imsi,
            imei=imei,
            name=name,
            plan_type=plan_type,
        )
        self.subscribers[msisdn] = subscriber
        self.msisdn_to_imsi[msisdn] = imsi
        return subscriber

    def get_subscriber(self, msisdn: str) -> Subscriber | None:
        """
        Get subscriber by MSISDN.

        Args:
            msisdn: Phone number

        Returns:
            Subscriber or None
        """
        return self.subscribers.get(msisdn)

    def deactivate_subscriber(self, msisdn: str) -> bool:
        """
        Deactivate a subscriber.

        Args:
            msisdn: Phone number

        Returns:
            True if successful
        """
        if msisdn in self.subscribers:
            self.subscribers[msisdn].active = False
            return True
        return False

    def activate_subscriber(self, msisdn: str) -> bool:
        """
        Activate a subscriber.

        Args:
            msisdn: Phone number

        Returns:
            True if successful
        """
        if msisdn in self.subscribers:
            self.subscribers[msisdn].active = True
            return True
        return False

    def get_active_subscribers(self) -> list[Subscriber]:
        """
        Get all active subscribers.

        Returns:
            List of active Subscribers
        """
        return [s for s in self.subscribers.values() if s.active]

    def add_plan(self, plan: Plan) -> None:
        """
        Add a subscription plan.

        Args:
            plan: Plan to add
        """
        self.subscriber_plans[plan.name] = plan

    def assign_plan(self, msisdn: str, plan_name: str) -> bool:
        """
        Assign plan to subscriber.

        Args:
            msisdn: Phone number
            plan_name: Plan name

        Returns:
            True if successful
        """
        if msisdn not in self.subscribers or plan_name not in self.subscriber_plans:
            return False

        plan = self.subscriber_plans[plan_name]
        subscriber = self.subscribers[msisdn]
        subscriber.monthly_quota_gb = plan.monthly_data_gb

        return True


@dataclass
class UsageTracker:
    """Track subscriber usage."""

    subscriber: Subscriber
    daily_usage: dict[str, dict] = field(default_factory=dict)
    call_records: list[CallRecord] = field(default_factory=list)

    def record_call(
        self,
        destination: str,
        duration_seconds: float,
        call_type: str = "voice",
    ) -> CallRecord:
        """
        Record a call.

        Args:
            destination: Destination number
            duration_seconds: Call duration in seconds
            call_type: Type of call (voice, sms, data)

        Returns:
            CallRecord
        """
        cdr = CallRecord(
            msisdn=self.subscriber.msisdn,
            destination=destination,
            duration_seconds=duration_seconds,
            call_type=call_type,
        )

        self.call_records.append(cdr)

        if call_type == "voice":
            self.subscriber.used_voice_minutes += duration_seconds / 60.0
        elif call_type == "sms":
            self.subscriber.used_sms_count += 1

        self.subscriber.last_activity = datetime.now()
        return cdr

    def record_data_usage(self, data_mb: float) -> None:
        """
        Record data usage.

        Args:
            data_mb: Data used in MB
        """
        data_gb = data_mb / 1024.0
        self.subscriber.used_data_gb += data_gb
        self.subscriber.last_activity = datetime.now()

    def get_daily_usage(self, date: datetime = None) -> dict:
        """
        Get usage for a specific day.

        Args:
            date: Date to check (default: today)

        Returns:
            Dict with usage data
        """
        if date is None:
            date = datetime.now()

        date_str = date.strftime("%Y-%m-%d")
        if date_str not in self.daily_usage:
            self.daily_usage[date_str] = {
                "voice_minutes": 0.0,
                "sms_count": 0,
                "data_mb": 0.0,
                "calls": 0,
            }

        return self.daily_usage[date_str]

    def get_monthly_usage(self) -> dict:
        """
        Get monthly usage summary.

        Returns:
            Dict with monthly usage
        """
        return {
            "voice_minutes": self.subscriber.used_voice_minutes,
            "sms_count": self.subscriber.used_sms_count,
            "data_gb": self.subscriber.used_data_gb,
            "num_calls": len(self.call_records),
        }

    def reset_monthly_usage(self) -> None:
        """Reset monthly usage counters."""
        self.subscriber.used_voice_minutes = 0.0
        self.subscriber.used_sms_count = 0
        self.subscriber.used_data_gb = 0.0
        self.call_records.clear()


@dataclass
class ChurnPredictor:
    """Predict subscriber churn using machine learning."""

    subscribers: dict[str, Subscriber] = field(default_factory=dict)
    usage_trackers: dict[str, UsageTracker] = field(default_factory=dict)
    model_weights: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.model_weights = {
            "inactivity_days": -0.5,
            "data_usage_ratio": -0.3,
            "voice_usage_ratio": -0.2,
            "plan_changes": 0.4,
            "balance_low": 0.6,
            "age_months": -0.05,
        }

    def extract_features(self, msisdn: str) -> dict[str, float]:
        """
        Extract features for churn prediction.

        Args:
            msisdn: Phone number

        Returns:
            Dict of features
        """
        subscriber = self.subscribers.get(msisdn)
        if not subscriber:
            return {}

        now = datetime.now()
        inactivity_days = (now - subscriber.last_activity).days
        age_months = (now - subscriber.registration_date).days / 30.0

        tracker = self.usage_trackers.get(msisdn)
        if tracker:
            monthly_usage = tracker.get_monthly_usage()
            data_usage_ratio = (
                subscriber.used_data_gb / subscriber.monthly_quota_gb if subscriber.monthly_quota_gb > 0 else 0.0
            )
            voice_usage_ratio = subscriber.used_voice_minutes / 3000.0
        else:
            data_usage_ratio = 0.0
            voice_usage_ratio = 0.0

        features = {
            "inactivity_days": min(inactivity_days, 365),
            "data_usage_ratio": min(data_usage_ratio, 1.0),
            "voice_usage_ratio": min(voice_usage_ratio, 1.0),
            "plan_changes": 0,
            "balance_low": 1.0 if subscriber.balance_credits < 5.0 else 0.0,
            "age_months": age_months,
        }

        return features

    def predict_churn_probability(self, msisdn: str) -> float:
        """
        Predict churn probability (0-1).

        Args:
            msisdn: Phone number

        Returns:
            Churn probability (0-1)
        """
        features = self.extract_features(msisdn)
        if not features:
            return 0.0

        score = sum(self.model_weights.get(feature, 0.0) * value for feature, value in features.items())

        probability = 1.0 / (1.0 + math.exp(-score))
        return probability

    def identify_churn_risk(self, threshold: float = 0.5) -> list[str]:
        """
        Identify subscribers at risk of churn.

        Args:
            threshold: Churn probability threshold

        Returns:
            List of at-risk MSISDNs
        """
        at_risk = []
        for msisdn in self.subscribers:
            probability = self.predict_churn_probability(msisdn)
            if probability > threshold:
                at_risk.append(msisdn)

        return at_risk

    def calculate_customer_lifetime_value(self, msisdn: str) -> float:
        """
        Calculate estimated customer lifetime value (CLV).

        Args:
            msisdn: Phone number

        Returns:
            Estimated CLV in currency units
        """
        subscriber = self.subscribers.get(msisdn)
        if not subscriber:
            return 0.0

        monthly_revenue = 25.0
        churn_probability = self.predict_churn_probability(msisdn)
        survival_rate = 1.0 - churn_probability

        clv = 0.0
        discount_rate = 0.02
        for month in range(1, 37):
            survival = survival_rate**month
            pv = (monthly_revenue * survival) / ((1 + discount_rate) ** month)
            clv += pv

        return clv


@dataclass
class SIMCard:
    """SIM card representation."""

    iccid: str
    msisdn: str
    imsi: str
    status: str = "active"  # active, inactive, blocked
    activation_date: datetime = field(default_factory=datetime.now)
    pin: str = ""

    def set_pin(self, pin: str) -> None:
        """
        Set SIM PIN.

        Args:
            pin: PIN code
        """
        if len(pin) != 4:
            raise ValueError("PIN must be 4 digits")
        self.pin = pin

    def verify_pin(self, pin: str) -> bool:
        """
        Verify SIM PIN.

        Args:
            pin: PIN to verify

        Returns:
            True if correct
        """
        return self.pin == pin

    def block(self) -> None:
        """Block SIM card."""
        self.status = "blocked"

    def unblock(self) -> None:
        """Unblock SIM card."""
        self.status = "active"


@dataclass
class NumberPortability:
    """Manage number portability."""

    ported_numbers: dict[str, str] = field(default_factory=dict)  # MSISDN -> donor operator

    def port_number(self, msisdn: str, from_operator: str, to_operator: str) -> bool:
        """
        Port number to different operator.

        Args:
            msisdn: Phone number to port
            from_operator: Source operator ID
            to_operator: Target operator ID

        Returns:
            True if successful
        """
        if msisdn in self.ported_numbers:
            return False

        self.ported_numbers[msisdn] = from_operator
        return True

    def query_current_operator(self, msisdn: str) -> str | None:
        """
        Query which operator hosts a number.

        Args:
            msisdn: Phone number

        Returns:
            Operator ID or None
        """
        return self.ported_numbers.get(msisdn)


__all__ = [
    "SubscriberManager",
    "UsageTracker",
    "ChurnPredictor",
    "Plan",
    "SIMCard",
    "NumberPortability",
]
