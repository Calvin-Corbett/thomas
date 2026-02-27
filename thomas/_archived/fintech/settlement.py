"""
Trade settlement and delivery.

Implements T+N settlement cycles, netting, delivery vs payment (DvP),
settlement queue management, and settlement reporting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum

from ._types import Trade


class SettlementStatus(str, Enum):
    """Status of a settlement instruction."""

    PENDING = "PENDING"
    MATCHED = "MATCHED"
    CONFIRMED = "CONFIRMED"
    DVP_INITIATED = "DVP_INITIATED"
    SETTLED = "SETTLED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class NetType(str, Enum):
    """Type of netting operation."""

    BILATERAL = "BILATERAL"
    MULTILATERAL = "MULTILATERAL"


@dataclass
class SettlementInstruction:
    """
    Settlement instruction for a trade.

    Attributes:
        id: Settlement instruction ID
        trade_id: Related trade ID
        settlement_date: Date of settlement
        status: Current settlement status
        buyer_account: Buyer account ID
        seller_account: Seller account ID
        symbol: Asset symbol
        quantity: Settlement quantity
        price: Settlement price
        amount: Settlement amount
        delivery_location: Delivery location
        reference: Reference information
    """

    id: str
    trade_id: str
    settlement_date: datetime
    status: SettlementStatus
    buyer_account: str
    seller_account: str
    symbol: str
    quantity: Decimal
    price: Decimal
    amount: Decimal
    delivery_location: str = ""
    reference: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def is_ready_to_settle(self) -> bool:
        """Check if instruction is ready to settle."""
        return self.status in (
            SettlementStatus.CONFIRMED,
            SettlementStatus.DVP_INITIATED,
        )


@dataclass
class SettlementObligation:
    """
    Settlement obligation between two parties.

    Attributes:
        id: Obligation ID
        from_account: Payer account
        to_account: Payee account
        asset: Asset being settled
        quantity: Amount to settle
        amount: Cash amount
        obligation_type: Type of obligation
        due_date: Due date
        status: Settlement status
    """

    id: str
    from_account: str
    to_account: str
    asset: str
    quantity: Decimal
    amount: Decimal
    obligation_type: str
    due_date: datetime
    status: SettlementStatus = SettlementStatus.PENDING


@dataclass
class NetPosition:
    """
    Netted position between two parties.

    Attributes:
        counterparty_a: First party
        counterparty_b: Second party
        net_quantity: Net quantity to deliver
        net_cash: Net cash to pay
        asset: Asset symbol
    """

    counterparty_a: str
    counterparty_b: str
    net_quantity: Decimal
    net_cash: Decimal
    asset: str

    def get_delivery_direction(self) -> str | None:
        """Determine direction of delivery."""
        if self.net_quantity > 0:
            return f"{self.counterparty_a} -> {self.counterparty_b}"
        elif self.net_quantity < 0:
            return f"{self.counterparty_b} -> {self.counterparty_a}"
        return None


class SettlementCycle:
    """
    Manage T+N settlement cycles.

    Handles settlement instructions and their scheduled settlement dates.
    """

    def __init__(self, settlement_days: int = 2) -> None:
        """
        Initialize settlement cycle.

        Args:
            settlement_days: Number of days (e.g., 2 for T+2)
        """
        self.settlement_days = settlement_days
        self.instructions: dict[str, SettlementInstruction] = {}
        self.settlement_queues: dict[str, list[SettlementInstruction]] = {}

    def create_instruction(
        self,
        trade: Trade,
        buyer_account: str,
        seller_account: str,
    ) -> SettlementInstruction:
        """
        Create settlement instruction from trade.

        Args:
            trade: Trade to settle
            buyer_account: Buyer account ID
            seller_account: Seller account ID

        Returns:
            Settlement instruction
        """
        settlement_date = datetime.utcnow() + timedelta(days=self.settlement_days)
        amount = trade.price * trade.quantity

        instruction = SettlementInstruction(
            id=f"SI-{trade.id}",
            trade_id=trade.id,
            settlement_date=settlement_date,
            status=SettlementStatus.PENDING,
            buyer_account=buyer_account,
            seller_account=seller_account,
            symbol=trade.symbol,
            quantity=trade.quantity,
            price=trade.price,
            amount=amount,
        )

        self.instructions[instruction.id] = instruction
        return instruction

    def confirm_instruction(self, instruction_id: str) -> bool:
        """
        Confirm a settlement instruction.

        Args:
            instruction_id: ID of instruction to confirm

        Returns:
            True if confirmed
        """
        if instruction_id not in self.instructions:
            return False

        instruction = self.instructions[instruction_id]
        instruction.status = SettlementStatus.CONFIRMED
        instruction.updated_at = datetime.utcnow()

        # Add to settlement queue
        settlement_date_key = instruction.settlement_date.date().isoformat()
        if settlement_date_key not in self.settlement_queues:
            self.settlement_queues[settlement_date_key] = []

        self.settlement_queues[settlement_date_key].append(instruction)
        return True

    def match_instruction(self, instruction_id: str, counterparty: str) -> bool:
        """
        Match an instruction with counterparty.

        Args:
            instruction_id: ID of instruction
            counterparty: Counterparty identifier

        Returns:
            True if matched
        """
        if instruction_id not in self.instructions:
            return False

        instruction = self.instructions[instruction_id]
        instruction.status = SettlementStatus.MATCHED
        instruction.updated_at = datetime.utcnow()
        return True

    def get_pending_instructions(self) -> list[SettlementInstruction]:
        """Get all pending instructions."""
        return [instr for instr in self.instructions.values() if instr.status == SettlementStatus.PENDING]

    def get_instructions_due_today(self) -> list[SettlementInstruction]:
        """Get instructions due for settlement today."""
        today = datetime.utcnow().date()
        return [
            instr
            for instr in self.instructions.values()
            if instr.settlement_date.date() == today and instr.is_ready_to_settle()
        ]


class NetHandler:
    """
    Handle bilateral and multilateral netting.

    Consolidates multiple obligations into net positions.
    """

    @staticmethod
    def bilateral_net(
        obligations: list[SettlementObligation],
        party_a: str,
        party_b: str,
        asset: str,
    ) -> NetPosition:
        """
        Calculate bilateral netting between two parties.

        Args:
            obligations: List of obligations
            party_a: First party
            party_b: Second party
            asset: Asset to net

        Returns:
            Net position
        """
        a_to_b_qty = Decimal("0")
        a_to_b_cash = Decimal("0")
        b_to_a_qty = Decimal("0")
        b_to_a_cash = Decimal("0")

        for obligation in obligations:
            if obligation.asset != asset:
                continue

            if obligation.from_account == party_a and obligation.to_account == party_b:
                a_to_b_qty += obligation.quantity
                a_to_b_cash += obligation.amount

            elif obligation.from_account == party_b and obligation.to_account == party_a:
                b_to_a_qty += obligation.quantity
                b_to_a_cash += obligation.amount

        net_qty = a_to_b_qty - b_to_a_qty
        net_cash = a_to_b_cash - b_to_a_cash

        return NetPosition(
            counterparty_a=party_a,
            counterparty_b=party_b,
            net_quantity=net_qty,
            net_cash=net_cash,
            asset=asset,
        )

    @staticmethod
    def multilateral_net(
        obligations: list[SettlementObligation],
        asset: str,
    ) -> dict[tuple[str, str], NetPosition]:
        """
        Calculate multilateral netting across multiple parties.

        Args:
            obligations: List of obligations
            asset: Asset to net

        Returns:
            Map of (party_a, party_b) to NetPosition
        """
        # Aggregate positions by party
        party_positions: dict[str, dict[str, Decimal]] = {}

        for obligation in obligations:
            if obligation.asset != asset:
                continue

            from_party = obligation.from_account
            to_party = obligation.to_account

            if from_party not in party_positions:
                party_positions[from_party] = {}
            if to_party not in party_positions:
                party_positions[to_party] = {}

            key = f"{to_party}:{from_party}"
            if key not in party_positions[from_party]:
                party_positions[from_party][key] = Decimal("0")

            party_positions[from_party][key] += obligation.amount

        # Calculate net positions
        net_positions: dict[tuple[str, str], NetPosition] = {}

        for from_party, positions in party_positions.items():
            for key, amount in positions.items():
                to_party = key.split(":")[0]
                pair = tuple(sorted([from_party, to_party]))

                if pair not in net_positions:
                    net_positions[pair] = NetPosition(
                        counterparty_a=pair[0],
                        counterparty_b=pair[1],
                        net_quantity=Decimal("0"),
                        net_cash=Decimal("0"),
                        asset=asset,
                    )

                if from_party == pair[0]:
                    net_positions[pair].net_cash += amount
                else:
                    net_positions[pair].net_cash -= amount

        return net_positions


class DeliveryVsPaymentHandler:
    """
    Delivery vs Payment (DvP) settlement.

    Ensures atomic exchange of securities and cash.
    """

    def __init__(self) -> None:
        """Initialize DvP handler."""
        self.pending_dvp: dict[str, dict] = {}

    def initiate_dvp(
        self,
        instruction: SettlementInstruction,
    ) -> bool:
        """
        Initiate DvP settlement.

        Args:
            instruction: Settlement instruction

        Returns:
            True if initiated
        """
        self.pending_dvp[instruction.id] = {
            "instruction": instruction,
            "security_delivered": False,
            "cash_delivered": False,
        }

        instruction.status = SettlementStatus.DVP_INITIATED
        return True

    def confirm_security_delivery(self, instruction_id: str) -> bool:
        """
        Confirm security leg of DvP.

        Args:
            instruction_id: Settlement instruction ID

        Returns:
            True if confirmed
        """
        if instruction_id not in self.pending_dvp:
            return False

        self.pending_dvp[instruction_id]["security_delivered"] = True
        return self._check_completion(instruction_id)

    def confirm_cash_delivery(self, instruction_id: str) -> bool:
        """
        Confirm cash leg of DvP.

        Args:
            instruction_id: Settlement instruction ID

        Returns:
            True if both legs complete
        """
        if instruction_id not in self.pending_dvp:
            return False

        self.pending_dvp[instruction_id]["cash_delivered"] = True
        return self._check_completion(instruction_id)

    def _check_completion(self, instruction_id: str) -> bool:
        """Check if both legs of DvP are complete."""
        if instruction_id not in self.pending_dvp:
            return False

        dvp_state = self.pending_dvp[instruction_id]

        if dvp_state["security_delivered"] and dvp_state["cash_delivered"]:
            instruction = dvp_state["instruction"]
            instruction.status = SettlementStatus.SETTLED
            instruction.updated_at = datetime.utcnow()
            del self.pending_dvp[instruction_id]
            return True

        return False
