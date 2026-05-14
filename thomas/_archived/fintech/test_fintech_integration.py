"""
Integration tests for complete fintech workflow.

Full integration tests covering order matching, settlement, ledger posting,
and compliance across multiple components.
"""

from datetime import datetime
from decimal import Decimal

import pytest
from _types import (
    Order,
    OrderSide,
    OrderType,
    Trade,
    TransactionType,
)
from compliance import ComplianceMonitor, KycProfile, TradingLimits
from ledger import AccountType, FinancialStatementGenerator, GeneralLedger
from order_matching import OrderMatcher
from portfolio import PortfolioManager
from settlement import DeliveryVsPaymentHandler, SettlementCycle


class TestOrderToSettlementFlow:
    """Test complete order to settlement flow."""

    def setup_method(self):
        """Set up test fixtures."""
        self.matcher = OrderMatcher()
        self.settlement = SettlementCycle(settlement_days=2)
        self.dvp = DeliveryVsPaymentHandler()

    def test_full_order_flow(self):
        """Test complete order, settlement, and DvP flow."""
        # Create and match orders
        buy_order = Order(
            id="BUY001",
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("100"),
            price=Decimal("150.00"),
            timestamp=datetime.utcnow(),
        )

        sell_order = Order(
            id="SELL001",
            symbol="AAPL",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=Decimal("100"),
            price=Decimal("150.00"),
            timestamp=datetime.utcnow(),
        )

        self.matcher.submit_order(buy_order)
        trades = self.matcher.submit_order(sell_order)

        assert len(trades) == 1
        trade = trades[0]

        # Create settlement instruction
        instruction = self.settlement.create_instruction(
            trade=trade,
            buyer_account="BUYER_ACC",
            seller_account="SELLER_ACC",
        )

        assert instruction.status.value == "PENDING"

        # Confirm instruction
        self.settlement.confirm_instruction(instruction.id)

        # Initiate DvP
        self.dvp.initiate_dvp(instruction)

        # Deliver security
        self.dvp.confirm_security_delivery(instruction.id)

        # Deliver cash
        result = self.dvp.confirm_cash_delivery(instruction.id)

        assert result is True
        assert instruction.status.value == "SETTLED"


class TestOrderMatchingWithPortfolio:
    """Test order matching integrated with portfolio tracking."""

    def setup_method(self):
        """Set up test fixtures."""
        self.matcher = OrderMatcher()
        self.portfolio = PortfolioManager("TRADER1")

    def test_trade_portfolio_update(self):
        """Test portfolio updates from trades."""
        # Execute a trade
        buy_order = Order(
            id="BUY001",
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("100"),
            price=Decimal("150.00"),
            timestamp=datetime.utcnow(),
        )

        sell_order = Order(
            id="SELL001",
            symbol="AAPL",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=Decimal("100"),
            price=Decimal("150.00"),
            timestamp=datetime.utcnow(),
        )

        self.matcher.submit_order(buy_order)
        trades = self.matcher.submit_order(sell_order)

        # Update portfolio from trade
        if trades:
            trade = trades[0]
            self.portfolio.add_position(
                symbol=trade.symbol,
                quantity=Decimal("100"),
                price=Decimal("150.00"),
            )

        position = self.portfolio.portfolio.get_position("AAPL")
        assert position is not None
        assert position.quantity == Decimal("100")

    def test_portfolio_performance_tracking(self):
        """Test portfolio performance tracking."""
        # Buy position
        self.portfolio.add_position("AAPL", Decimal("100"), Decimal("150.00"))

        # Update price
        self.portfolio.update_prices({"AAPL": Decimal("160.00")})

        perf = self.portfolio.get_performance_summary()

        assert perf["unrealized_pnl"] == Decimal("1000")
        assert perf["return_pct"] == Decimal("6.666666666666666666666666667")


class TestLedgerIntegration:
    """Test ledger integration with trades."""

    def setup_method(self):
        """Set up test fixtures."""
        self.ledger = GeneralLedger()
        self.generator = FinancialStatementGenerator(self.ledger)

        # Create chart of accounts
        self.ledger.create_account("1000", "Cash", AccountType.ASSET)
        self.ledger.create_account("1100", "Securities", AccountType.ASSET)
        self.ledger.create_account("3000", "Equity", AccountType.EQUITY)
        self.ledger.create_account("4000", "Investment Income", AccountType.REVENUE)
        self.ledger.create_account("5000", "Trading Fees", AccountType.EXPENSE)

    def test_trade_ledger_entry(self):
        """Test posting trade to ledger."""
        now = datetime.utcnow()

        # Buy trade
        self.ledger.create_and_post_entry(
            date=now,
            description="Buy 100 AAPL @ 150",
            debits={"1100": Decimal("15000")},
            credits={"1000": Decimal("15000")},
            transaction_type=TransactionType.TRADE,
        )

        # Post fee
        self.ledger.create_and_post_entry(
            date=now,
            description="Trading fee",
            debits={"5000": Decimal("50")},
            credits={"1000": Decimal("50")},
            transaction_type=TransactionType.FEE,
        )

        assert self.ledger.get_account_balance("1000") == Decimal("-15050")
        assert self.ledger.get_account_balance("1100") == Decimal("15000")
        assert self.ledger.get_account_balance("5000") == Decimal("50")

    def test_income_statement_from_trades(self):
        """Test income statement generation from trades."""
        now = datetime.utcnow()

        # Sell at profit
        self.ledger.create_and_post_entry(
            date=now,
            description="Sell 100 AAPL @ 160",
            debits={"1000": Decimal("16000")},
            credits={"1100": Decimal("15000")},
            transaction_type=TransactionType.TRADE,
        )

        # Record gain
        self.ledger.create_and_post_entry(
            date=now,
            description="Investment gain",
            debits={"1000": Decimal("1000")},
            credits={"4000": Decimal("1000")},
            transaction_type=TransactionType.TRADE,
        )

        statement = self.generator.generate_income_statement(
            now.replace(hour=0, minute=0, second=0),
            now.replace(hour=23, minute=59, second=59),
        )

        assert statement["revenues"] == Decimal("1000")


class TestComplianceWithTrading:
    """Test compliance monitoring during trading."""

    def setup_method(self):
        """Set up test fixtures."""
        self.matcher = OrderMatcher()
        self.compliance = ComplianceMonitor()

    def test_kyc_requirement(self):
        """Test KYC requirement for trading."""
        customer_id = "CUST001"

        # Customer not KYC'd
        from _exceptions import ComplianceError

        with pytest.raises(ComplianceError):
            self.compliance.check_kyc_compliance(customer_id)

        # Register and approve KYC
        profile = KycProfile(
            customer_id=customer_id,
            full_name="John Doe",
            date_of_birth=datetime(1990, 1, 1),
            id_type="PASSPORT",
            id_number="123456789",
            address="123 Main St",
            country="US",
        )

        self.compliance.register_kyc(profile)
        self.compliance.approve_kyc(customer_id)

        # Now should pass
        assert self.compliance.check_kyc_compliance(customer_id) is True

    def test_trading_limits(self):
        """Test trading limits enforcement."""
        account_id = "ACC001"

        limits = TradingLimits(
            account_id=account_id,
            max_order_size=Decimal("50000"),
        )

        self.compliance.set_trading_limits(limits)

        # Order within limit
        order1 = Order(
            id="O1",
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("100"),
            price=Decimal("150.00"),
            timestamp=datetime.utcnow(),
        )

        assert self.compliance.check_trading_limits(account_id, order1) is True

        # Order exceeding limit
        order2 = Order(
            id="O2",
            symbol="MSFT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("500"),
            price=Decimal("300.00"),
            timestamp=datetime.utcnow(),
        )

        from _exceptions import ComplianceError

        with pytest.raises(ComplianceError):
            self.compliance.check_trading_limits(account_id, order2)

    def test_wash_trade_detection(self):
        """Test wash trade detection."""
        account_id = "ACC001"

        # Record matching trades
        trade1 = Trade(
            id="TRADE001",
            buy_order_id="BUY001",
            sell_order_id="SELL001",
            symbol="AAPL",
            price=Decimal("150.00"),
            quantity=Decimal("100"),
            timestamp=datetime.utcnow(),
        )

        trade2 = Trade(
            id="TRADE002",
            buy_order_id="SELL001",
            sell_order_id="BUY001",
            symbol="AAPL",
            price=Decimal("150.00"),
            quantity=Decimal("100"),
            timestamp=datetime.utcnow(),
        )

        self.compliance.record_trade(account_id, trade1)
        self.compliance.record_trade(account_id, trade2)

        # Detect wash trades
        wash_trades = self.compliance.detect_wash_trades(account_id)

        # Should detect potential wash trades
        assert len(wash_trades) > 0

    def test_pattern_day_trader_detection(self):
        """Test pattern day trader detection."""
        account_id = "ACC001"
        now = datetime.utcnow()

        # Create multiple round trips
        for i in range(5):
            # Buy trade
            buy_trade = Trade(
                id=f"BUY{i}",
                buy_order_id=f"BUY_ORDER_{i}",
                sell_order_id=f"SELL_ORDER_{i}",
                symbol="AAPL",
                price=Decimal("150.00"),
                quantity=Decimal("100"),
                timestamp=now,
            )

            # Sell trade
            sell_trade = Trade(
                id=f"SELL{i}",
                buy_order_id=f"SELL_ORDER_{i}",
                sell_order_id=f"BUY_ORDER_{i}",
                symbol="AAPL",
                price=Decimal("151.00"),
                quantity=Decimal("100"),
                timestamp=now,
            )

            self.compliance.record_trade(account_id, buy_trade)
            self.compliance.record_trade(account_id, sell_trade)

        # Check pattern day trader
        is_pdt = self.compliance.detect_pattern_day_trader(account_id)

        assert is_pdt is True


class TestEndToEndFlow:
    """Test complete end-to-end workflow."""

    def test_complete_trading_cycle(self):
        """Test complete trading cycle."""
        # Setup components
        matcher = OrderMatcher()
        settlement = SettlementCycle()
        ledger = GeneralLedger()
        compliance = ComplianceMonitor()
        portfolio = PortfolioManager("TRADER1")

        # Setup ledger
        ledger.create_account("1000", "Cash", AccountType.ASSET)
        ledger.create_account("1100", "Securities", AccountType.ASSET)
        ledger.create_account("3000", "Equity", AccountType.EQUITY)
        ledger.create_account("5000", "Fees", AccountType.EXPENSE)

        # Setup compliance
        kyc = KycProfile(
            customer_id="CUST001",
            full_name="Trader",
            date_of_birth=datetime(1990, 1, 1),
            id_type="ID",
            id_number="123",
            address="Street",
            country="US",
        )
        compliance.register_kyc(kyc)
        compliance.approve_kyc("CUST001")

        # Execute order flow
        buy_order = Order(
            id="BUY001",
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("100"),
            price=Decimal("150.00"),
            timestamp=datetime.utcnow(),
        )

        sell_order = Order(
            id="SELL001",
            symbol="AAPL",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=Decimal("100"),
            price=Decimal("150.00"),
            timestamp=datetime.utcnow(),
        )

        # Check compliance
        compliance.check_kyc_compliance("CUST001")
        compliance.check_trading_limits("ACC001", buy_order)

        # Execute orders
        matcher.submit_order(buy_order)
        trades = matcher.submit_order(sell_order)

        assert len(trades) == 1

        # Update portfolio
        portfolio.add_position("AAPL", Decimal("100"), Decimal("150.00"))

        # Create settlement
        settlement.create_instruction(
            trades[0],
            "BUYER",
            "SELLER",
        )

        # Post to ledger
        now = datetime.utcnow()
        ledger.create_and_post_entry(
            date=now,
            description="Buy securities",
            debits={"1100": Decimal("15000")},
            credits={"1000": Decimal("15000")},
            transaction_type=TransactionType.TRADE,
        )

        # Verify all systems
        assert matcher.get_order("BUY001").status.value == "FILLED"
        assert portfolio.get_total_value() == Decimal("0")  # No cash change yet
        assert ledger.verify_trial_balance() is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
