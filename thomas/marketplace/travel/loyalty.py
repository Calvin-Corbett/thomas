"""Loyalty program management with points, tiers, and benefits."""

from datetime import datetime, timedelta
from decimal import Decimal

from thomas.marketplace.travel._exceptions import InsufficientPointsError, LoyaltyError
from thomas.marketplace.travel._types import LoyaltyTier


class PointsAccrual:
    """Manage points earning and accrual."""

    # Base earning rates by tier
    EARNING_RATES = {
        LoyaltyTier.STANDARD: 1.0,
        LoyaltyTier.SILVER: 1.25,
        LoyaltyTier.GOLD: 1.5,
        LoyaltyTier.PLATINUM: 2.0,
    }

    # Bonus multipliers for specific activities
    BONUS_MULTIPLIERS = {
        "domestic_flight": 1.0,
        "international_flight": 1.5,
        "premium_cabin": 2.0,
        "hotel_stay": 1.0,
        "car_rental": 0.5,
        "credit_card": 3.0,
    }

    def __init__(self) -> None:
        """Initialize points accrual engine."""
        self._earning_records: dict[str, list[dict]] = {}
        self._promotional_bonuses: dict[str, int] = {}

    def calculate_points_earned(
        self,
        amount_spent: Decimal,
        member_tier: LoyaltyTier,
        activity_type: str = "domestic_flight",
        is_promotional: bool = False,
    ) -> int:
        """
        Calculate points earned from spending.

        Args:
            amount_spent: Amount spent in USD
            member_tier: Member loyalty tier
            activity_type: Type of activity
            is_promotional: Whether bonus promotion applies

        Returns:
            Points earned
        """
        # Base rate calculation (1 point per dollar)
        base_points = int(amount_spent)

        # Apply tier multiplier
        tier_multiplier = self.EARNING_RATES.get(member_tier, 1.0)
        base_points = int(base_points * tier_multiplier)

        # Apply activity bonus
        activity_bonus = self.BONUS_MULTIPLIERS.get(activity_type, 1.0)
        base_points = int(base_points * activity_bonus)

        # Apply promotional bonus if applicable
        if is_promotional:
            base_points = int(base_points * 1.5)  # 50% bonus

        return base_points

    def record_earning(
        self,
        member_id: str,
        points: int,
        source: str,
        transaction_id: str | None = None,
    ) -> dict[str, any]:
        """
        Record points earning transaction.

        Args:
            member_id: Member identifier
            points: Points earned
            source: Source of earning
            transaction_id: Optional transaction identifier

        Returns:
            Earning record
        """
        if member_id not in self._earning_records:
            self._earning_records[member_id] = []

        record = {
            "date": datetime.utcnow(),
            "points": points,
            "source": source,
            "transaction_id": transaction_id,
        }

        self._earning_records[member_id].append(record)
        return record

    def get_earning_history(self, member_id: str) -> list[dict]:
        """
        Get earning history for member.

        Args:
            member_id: Member identifier

        Returns:
            List of earning records
        """
        return self._earning_records.get(member_id, [])


class TierManagement:
    """Manage loyalty tier progression."""

    # Tier requirements (qualifying points in calendar year)
    TIER_REQUIREMENTS = {
        LoyaltyTier.SILVER: 25000,
        LoyaltyTier.GOLD: 50000,
        LoyaltyTier.PLATINUM: 100000,
    }

    # Alternative requirements (segments or miles)
    SEGMENT_REQUIREMENTS = {
        LoyaltyTier.SILVER: 25,
        LoyaltyTier.GOLD: 50,
        LoyaltyTier.PLATINUM: 100,
    }

    def __init__(self) -> None:
        """Initialize tier management."""
        self._tier_changes: dict[str, list[dict]] = {}
        self._elite_qualifications: dict[str, dict] = {}

    def determine_tier(
        self,
        qualifying_points: int,
        segments_flown: int,
    ) -> LoyaltyTier:
        """
        Determine tier based on qualifying activity.

        Args:
            qualifying_points: Qualifying points earned
            segments_flown: Number of flight segments

        Returns:
            Appropriate LoyaltyTier
        """
        # Check platinum first (highest tier)
        if (
            qualifying_points >= self.TIER_REQUIREMENTS[LoyaltyTier.PLATINUM]
            or segments_flown >= self.SEGMENT_REQUIREMENTS[LoyaltyTier.PLATINUM]
        ):
            return LoyaltyTier.PLATINUM

        if (
            qualifying_points >= self.TIER_REQUIREMENTS[LoyaltyTier.GOLD]
            or segments_flown >= self.SEGMENT_REQUIREMENTS[LoyaltyTier.GOLD]
        ):
            return LoyaltyTier.GOLD

        if (
            qualifying_points >= self.TIER_REQUIREMENTS[LoyaltyTier.SILVER]
            or segments_flown >= self.SEGMENT_REQUIREMENTS[LoyaltyTier.SILVER]
        ):
            return LoyaltyTier.SILVER

        return LoyaltyTier.STANDARD

    def process_tier_change(
        self,
        member_id: str,
        old_tier: LoyaltyTier,
        new_tier: LoyaltyTier,
    ) -> dict[str, any]:
        """
        Process tier upgrade or downgrade.

        Args:
            member_id: Member identifier
            old_tier: Previous tier
            new_tier: New tier

        Returns:
            Tier change record
        """
        if member_id not in self._tier_changes:
            self._tier_changes[member_id] = []

        change = {
            "date": datetime.utcnow(),
            "old_tier": old_tier,
            "new_tier": new_tier,
            "tier_expiry": datetime.utcnow() + timedelta(days=365),
        }

        self._tier_changes[member_id].append(change)
        return change

    def get_tier_history(self, member_id: str) -> list[dict]:
        """
        Get tier change history.

        Args:
            member_id: Member identifier

        Returns:
            List of tier changes
        """
        return self._tier_changes.get(member_id, [])

    def calculate_elite_benefits(self, tier: LoyaltyTier) -> dict[str, any]:
        """
        Calculate elite benefits for tier.

        Args:
            tier: Loyalty tier

        Returns:
            Benefits dictionary
        """
        benefits = {
            LoyaltyTier.STANDARD: {
                "lounge_access": False,
                "priority_boarding": False,
                "free_baggage": 1,
                "seat_upgrade_priority": False,
                "companion_upgrade": False,
            },
            LoyaltyTier.SILVER: {
                "lounge_access": False,
                "priority_boarding": True,
                "free_baggage": 2,
                "seat_upgrade_priority": True,
                "companion_upgrade": False,
            },
            LoyaltyTier.GOLD: {
                "lounge_access": True,
                "priority_boarding": True,
                "free_baggage": 3,
                "seat_upgrade_priority": True,
                "companion_upgrade": True,
                "lounge_guests": 1,
            },
            LoyaltyTier.PLATINUM: {
                "lounge_access": True,
                "priority_boarding": True,
                "free_baggage": 4,
                "seat_upgrade_priority": True,
                "companion_upgrade": True,
                "lounge_guests": 2,
                "concierge_service": True,
            },
        }

        return benefits.get(tier, benefits[LoyaltyTier.STANDARD])


class PointsRedemption:
    """Manage points redemption for awards."""

    def __init__(self) -> None:
        """Initialize redemption engine."""
        self._redemption_history: dict[str, list[dict]] = {}
        self._award_pricing: dict[str, int] = {}
        self._load_default_awards()

    def _load_default_awards(self) -> None:
        """Load default award pricing in miles."""
        self._award_pricing = {
            "domestic_economy": 25000,
            "domestic_business": 50000,
            "international_economy": 60000,
            "international_business": 120000,
            "hotel_night": 10000,
            "car_rental_day": 5000,
        }

    def get_award_price(self, award_type: str) -> int:
        """
        Get points required for award.

        Args:
            award_type: Type of award

        Returns:
            Points/miles required
        """
        return self._award_pricing.get(award_type, 0)

    def redeem_points(
        self,
        member_id: str,
        points: int,
        award_type: str,
        member_miles: int,
    ) -> dict[str, any]:
        """
        Redeem points for award.

        Args:
            member_id: Member identifier
            points: Points to redeem
            award_type: Type of award
            member_miles: Member's current miles balance

        Returns:
            Redemption record

        Raises:
            InsufficientPointsError: If insufficient points
        """
        required = self.get_award_price(award_type)

        if member_miles < required:
            raise InsufficientPointsError(f"Insufficient miles: {member_miles} < {required}")

        if member_id not in self._redemption_history:
            self._redemption_history[member_id] = []

        redemption = {
            "date": datetime.utcnow(),
            "award_type": award_type,
            "miles_used": required,
            "confirmation_number": self._generate_confirmation(),
        }

        self._redemption_history[member_id].append(redemption)
        return redemption

    def get_redemption_history(self, member_id: str) -> list[dict]:
        """
        Get redemption history.

        Args:
            member_id: Member identifier

        Returns:
            List of redemptions
        """
        return self._redemption_history.get(member_id, [])

    def _generate_confirmation(self) -> str:
        """
        Generate redemption confirmation number.

        Returns:
            Confirmation number
        """
        import random
        import string

        return "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


class EliteBenefitsManager:
    """Manage elite benefits and privileges."""

    def __init__(self) -> None:
        """Initialize benefits manager."""
        self._priority_boarding_list: dict[str, list[str]] = {}
        self._lounge_access_list: dict[str, list[str]] = {}
        self._seat_upgrades: dict[str, list[dict]] = {}

    def grant_priority_boarding(
        self,
        member_id: str,
        flight_id: str,
    ) -> bool:
        """
        Grant priority boarding for member on flight.

        Args:
            member_id: Member identifier
            flight_id: Flight identifier

        Returns:
            True if granted
        """
        if flight_id not in self._priority_boarding_list:
            self._priority_boarding_list[flight_id] = []

        self._priority_boarding_list[flight_id].append(member_id)
        return True

    def grant_lounge_access(
        self,
        member_id: str,
        lounge_id: str,
        num_guests: int = 0,
    ) -> dict[str, any]:
        """
        Grant lounge access to member.

        Args:
            member_id: Member identifier
            lounge_id: Lounge identifier
            num_guests: Number of complimentary guests

        Returns:
            Lounge access record
        """
        if lounge_id not in self._lounge_access_list:
            self._lounge_access_list[lounge_id] = []

        self._lounge_access_list[lounge_id].append(member_id)

        return {
            "member_id": member_id,
            "lounge_id": lounge_id,
            "complimentary_guests": num_guests,
            "access_date": datetime.utcnow(),
            "valid_until": datetime.utcnow() + timedelta(days=365),
        }

    def process_seat_upgrade(
        self,
        member_id: str,
        booking_pnr: str,
        from_class: str,
        to_class: str,
    ) -> dict[str, any]:
        """
        Process automatic seat upgrade for elite member.

        Args:
            member_id: Member identifier
            booking_pnr: Booking PNR
            from_class: Original cabin class
            to_class: Upgraded cabin class

        Returns:
            Upgrade record
        """
        if member_id not in self._seat_upgrades:
            self._seat_upgrades[member_id] = []

        upgrade = {
            "booking_pnr": booking_pnr,
            "from_class": from_class,
            "to_class": to_class,
            "upgrade_date": datetime.utcnow(),
        }

        self._seat_upgrades[member_id].append(upgrade)
        return upgrade

    def get_lounge_access(self, member_id: str) -> list[str]:
        """
        Get lounge access for member.

        Args:
            member_id: Member identifier

        Returns:
            List of accessible lounge IDs
        """
        accessible = []
        for lounge_id, members in self._lounge_access_list.items():
            if member_id in members:
                accessible.append(lounge_id)
        return accessible


class PartnerEarningBurning:
    """Manage partner earning and burning of points."""

    def __init__(self) -> None:
        """Initialize partner program."""
        self._partner_transfers: dict[str, list[dict]] = {}
        self._partners: dict[str, dict] = {}

    def add_partner(
        self,
        partner_id: str,
        partner_name: str,
        earning_rate: float,
    ) -> None:
        """
        Add partner program.

        Args:
            partner_id: Partner identifier
            partner_name: Partner name
            earning_rate: Points earning rate
        """
        self._partners[partner_id] = {
            "name": partner_name,
            "earning_rate": earning_rate,
        }

    def transfer_points(
        self,
        member_id: str,
        partner_id: str,
        points: int,
    ) -> dict[str, any]:
        """
        Transfer points to partner.

        Args:
            member_id: Member identifier
            partner_id: Partner identifier
            points: Points to transfer

        Returns:
            Transfer record

        Raises:
            LoyaltyError: If partner not found
        """
        if partner_id not in self._partners:
            raise LoyaltyError(f"Partner {partner_id} not found")

        if member_id not in self._partner_transfers:
            self._partner_transfers[member_id] = []

        # Transfers typically have a conversion rate
        conversion_rate = 0.75  # 3 points = 2 partner points
        partner_points = int(points * conversion_rate)

        transfer = {
            "date": datetime.utcnow(),
            "partner_id": partner_id,
            "partner_name": self._partners[partner_id]["name"],
            "points_transferred": points,
            "partner_points_received": partner_points,
            "confirmation_number": self._generate_confirmation(),
        }

        self._partner_transfers[member_id].append(transfer)
        return transfer

    def get_transfer_history(self, member_id: str) -> list[dict]:
        """
        Get partner transfer history.

        Args:
            member_id: Member identifier

        Returns:
            List of transfers
        """
        return self._partner_transfers.get(member_id, [])

    def _generate_confirmation(self) -> str:
        """
        Generate transfer confirmation number.

        Returns:
            Confirmation number
        """
        import random
        import string

        return "".join(random.choices(string.ascii_uppercase + string.digits, k=8))


class PointsExpiryTracking:
    """Track points expiry and manage expiration policies."""

    # Points expire after 36 months of inactivity
    EXPIRY_PERIOD_DAYS = 365 * 3

    def __init__(self) -> None:
        """Initialize expiry tracking."""
        self._expiry_dates: dict[str, datetime] = {}
        self._expired_points: dict[str, int] = {}

    def set_expiry_date(self, member_id: str, expiry_date: datetime) -> None:
        """
        Set expiry date for member's points.

        Args:
            member_id: Member identifier
            expiry_date: Points expiry date
        """
        self._expiry_dates[member_id] = expiry_date

    def get_expiry_date(self, member_id: str) -> datetime | None:
        """
        Get expiry date for member.

        Args:
            member_id: Member identifier

        Returns:
            Expiry date, or None
        """
        return self._expiry_dates.get(member_id)

    def calculate_expiry_date(self, last_activity_date: datetime) -> datetime:
        """
        Calculate expiry date based on last activity.

        Args:
            last_activity_date: Last activity date

        Returns:
            Points expiry date
        """
        return last_activity_date + timedelta(days=self.EXPIRY_PERIOD_DAYS)

    def get_points_at_expiry(self, member_id: str) -> int:
        """
        Get points that will expire.

        Args:
            member_id: Member identifier

        Returns:
            Points expiring
        """
        return self._expired_points.get(member_id, 0)


class LoyaltyAnalytics:
    """Analytics for loyalty program metrics."""

    def __init__(self) -> None:
        """Initialize analytics."""
        self._member_metrics: dict[str, dict] = {}

    def calculate_lifetime_value(
        self,
        member_id: str,
        total_spent: Decimal,
        years_member: int,
        tier: LoyaltyTier,
    ) -> Decimal:
        """
        Calculate member lifetime value.

        Args:
            member_id: Member identifier
            total_spent: Total amount spent
            years_member: Years as member
            tier: Current tier

        Returns:
            Estimated lifetime value
        """
        # LTV = total spent * retention rate * tier multiplier
        tier_multiplier = {
            LoyaltyTier.STANDARD: 1.0,
            LoyaltyTier.SILVER: 1.3,
            LoyaltyTier.GOLD: 1.7,
            LoyaltyTier.PLATINUM: 2.5,
        }.get(tier, 1.0)

        retention_multiplier = min(years_member / 5.0, 2.0)  # Max 2x over 5 years

        ltv = total_spent * Decimal(tier_multiplier * retention_multiplier)

        return ltv

    def record_metrics(
        self,
        member_id: str,
        metrics: dict[str, any],
    ) -> None:
        """
        Record member metrics.

        Args:
            member_id: Member identifier
            metrics: Metrics dictionary
        """
        self._member_metrics[member_id] = {
            **self._member_metrics.get(member_id, {}),
            **metrics,
            "last_updated": datetime.utcnow(),
        }

    def get_metrics(self, member_id: str) -> dict[str, any]:
        """
        Get member metrics.

        Args:
            member_id: Member identifier

        Returns:
            Metrics dictionary
        """
        return self._member_metrics.get(member_id, {})
