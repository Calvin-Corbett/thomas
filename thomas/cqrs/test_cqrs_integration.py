"""
Integration tests for complete CQRS system.

Tests end-to-end workflows combining commands, queries, events,
aggregates, projections, and sagas.
"""

import asyncio
from typing import Any

import pytest

from . import (
    AggregateId,
    AggregateRepository,
    AggregateRoot,
    Command,
    CommandBus,
    CommandResult,
    Event,
    EventStore,
    Metadata,
    ProjectionManager,
    Query,
    QueryBus,
    QueryResult,
    ReadModelStore,
    SagaBase,
    SagaStep,
)


# Domain objects
class AccountCreated(Event):
    def __init__(self, account_id: str, owner: str):
        super().__init__()
        self.account_id = account_id
        self.owner = owner


class MoneyDeposited(Event):
    def __init__(self, amount: float):
        super().__init__()
        self.amount = amount


class MoneyWithdrawn(Event):
    def __init__(self, amount: float):
        super().__init__()
        self.amount = amount


class CreateAccountCmd(Command):
    def __init__(self, account_id: str, owner: str):
        super().__init__()
        self.account_id = account_id
        self.owner = owner


class DepositCmd(Command):
    def __init__(self, account_id: str, amount: float):
        super().__init__()
        self.account_id = account_id
        self.amount = amount


class WithdrawCmd(Command):
    def __init__(self, account_id: str, amount: float):
        super().__init__()
        self.account_id = account_id
        self.amount = amount


class GetAccountQuery(Query):
    def __init__(self, account_id: str):
        super().__init__()
        self.account_id = account_id


class ListAccountsQuery(Query):
    pass


class Account(AggregateRoot):
    """Account aggregate."""

    def __init__(self, aggregate_id: AggregateId):
        super().__init__(aggregate_id)
        self.owner: str = ""
        self.balance: float = 0.0

    def create(self, owner: str) -> None:
        self.raise_event(AccountCreated(self.aggregate_id.value, owner))

    def on_AccountCreated(self, event: AccountCreated) -> None:
        self.owner = event.owner

    def deposit(self, amount: float) -> None:
        self.raise_event(MoneyDeposited(amount))

    def on_MoneyDeposited(self, event: MoneyDeposited) -> None:
        self.balance += event.amount

    def withdraw(self, amount: float) -> None:
        if amount > self.balance:
            raise ValueError("Insufficient funds")
        self.raise_event(MoneyWithdrawn(amount))

    def on_MoneyWithdrawn(self, event: MoneyWithdrawn) -> None:
        self.balance -= event.amount

    def to_snapshot_state(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "owner": self.owner,
            "balance": self.balance,
        }

    def restore_from_snapshot(self, state: dict[str, Any]) -> None:
        self.version = state.get("version", 0)
        self.owner = state.get("owner", "")
        self.balance = state.get("balance", 0.0)


class TestCQRSIntegration:
    """Integration tests."""

    @pytest.mark.asyncio
    async def test_complete_account_workflow(self):
        """Test complete account creation and transaction workflow."""
        # Setup
        event_store = EventStore()
        repo = AggregateRepository(event_store)
        command_bus = CommandBus()
        query_bus = QueryBus()
        read_model = ReadModelStore()

        # Register handlers
        async def create_account_handler(cmd: CreateAccountCmd) -> CommandResult:
            agg_id = AggregateId(cmd.account_id, "Account")
            account = Account(agg_id)
            account.create(cmd.owner)
            await repo.save(account, Metadata(user_id="system"))

            # Update read model
            await read_model.create(
                cmd.account_id,
                {"owner": cmd.owner, "balance": 0.0},
            )

            return CommandResult.ok(account.get_uncommitted_events())

        async def deposit_handler(cmd: DepositCmd) -> CommandResult:
            agg_id = AggregateId(cmd.account_id, "Account")
            account = await repo.get_by_id(agg_id, Account)
            account.deposit(cmd.amount)
            await repo.save(account, Metadata(user_id="system"))

            # Update read model
            await read_model.update(cmd.account_id, {"balance": account.balance})

            return CommandResult.ok(account.get_uncommitted_events())

        async def get_account_handler(query: GetAccountQuery) -> QueryResult:
            doc = await read_model.get(query.account_id)
            if doc:
                return QueryResult(data=doc.data)
            return QueryResult(data=None)

        command_bus.register_handler(CreateAccountCmd, create_account_handler)
        command_bus.register_handler(DepositCmd, deposit_handler)
        query_bus.register_handler(GetAccountQuery, get_account_handler)

        # Execute workflow
        create_result = await command_bus.execute(CreateAccountCmd("acc1", "Alice"))
        assert create_result.success

        deposit_result = await command_bus.execute(DepositCmd("acc1", 100.0))
        assert deposit_result.success

        query_result = await query_bus.execute(GetAccountQuery("acc1"))
        assert query_result.data["balance"] == 100.0
        assert query_result.data["owner"] == "Alice"

    @pytest.mark.asyncio
    async def test_event_sourcing_full_cycle(self):
        """Test event sourcing: save and reload aggregate."""
        event_store = EventStore()
        repo = AggregateRepository(event_store)

        # Create account
        agg_id = AggregateId("acc1", "Account")
        account1 = Account(agg_id)
        account1.create("Bob")
        account1.deposit(500.0)
        account1.withdraw(100.0)

        await repo.save(account1, Metadata())

        # Reload account
        account2 = await repo.get_by_id(agg_id, Account)

        assert account2.owner == "Bob"
        assert account2.balance == 400.0
        assert account2.version == 3

    @pytest.mark.asyncio
    async def test_projection_from_events(self):
        """Test projection building from events."""
        event_store = EventStore()
        repo = AggregateRepository(event_store)
        projection_manager = ProjectionManager(event_store)

        # Create simple projection
        from . import InMemoryProjection

        class AccountProjection(InMemoryProjection):
            def __init__(self):
                super().__init__("accounts")
                self._accounts: dict[str, dict] = {}
                self.register_handler("AccountCreated", self._on_created)
                self.register_handler("MoneyDeposited", self._on_deposited)

            async def _on_created(self, event) -> None:
                self._accounts[event.aggregate_id.value] = {
                    "owner": event.event.owner,
                    "balance": 0.0,
                }

            async def _on_deposited(self, event) -> None:
                agg_id = event.aggregate_id.value
                if agg_id in self._accounts:
                    self._accounts[agg_id]["balance"] += event.event.amount

            async def get_accounts(self) -> dict[str, dict]:
                return self._accounts.copy()

        projection = AccountProjection()
        await projection_manager.register_projection(projection)

        # Create account via repository
        agg_id = AggregateId("acc1", "Account")
        account = Account(agg_id)
        account.create("Charlie")
        account.deposit(250.0)
        await repo.save(account, Metadata())

        # Catch up projection
        await projection_manager.catch_up("accounts")

        # Check projection
        accounts = await projection.get_accounts()
        assert "acc1" in accounts
        assert accounts["acc1"]["owner"] == "Charlie"
        assert accounts["acc1"]["balance"] == 250.0

    @pytest.mark.asyncio
    async def test_saga_coordination(self):
        """Test saga coordinating multiple operations."""
        repo = AggregateRepository(EventStore())
        command_bus = CommandBus()

        # Register handlers
        async def create_handler(cmd: CreateAccountCmd) -> CommandResult:
            agg_id = AggregateId(cmd.account_id, "Account")
            account = Account(agg_id)
            account.create(cmd.owner)
            await repo.save(account, Metadata())
            return CommandResult.ok()

        async def deposit_handler(cmd: DepositCmd) -> CommandResult:
            agg_id = AggregateId(cmd.account_id, "Account")
            account = await repo.get_by_id(agg_id, Account)
            account.deposit(cmd.amount)
            await repo.save(account, Metadata())
            return CommandResult.ok()

        command_bus.register_handler(CreateAccountCmd, create_handler)
        command_bus.register_handler(DepositCmd, deposit_handler)

        # Create saga
        class SetupAccountSaga(SagaBase):
            def __init__(self, command_bus: CommandBus):
                super().__init__()
                self.command_bus = command_bus

                class CreateStep(SagaStep):
                    def __init__(self, bus):
                        super().__init__("create")
                        self.bus = bus

                    async def execute(self, context: dict[str, Any]) -> Any:
                        await self.bus.execute(CreateAccountCmd("acc1", "Diana"))
                        return "created"

                    async def compensate(self, context: dict[str, Any]) -> None:
                        pass

                class DepositStep(SagaStep):
                    def __init__(self, bus):
                        super().__init__("deposit")
                        self.bus = bus

                    async def execute(self, context: dict[str, Any]) -> Any:
                        await self.bus.execute(DepositCmd("acc1", 500.0))
                        return "deposited"

                    async def compensate(self, context: dict[str, Any]) -> None:
                        pass

                self.add_step(CreateStep(command_bus))
                self.add_step(DepositStep(command_bus))

        saga = SetupAccountSaga(command_bus)
        await saga.execute()

        assert saga.is_complete()

        # Verify result
        agg_id = AggregateId("acc1", "Account")
        account = await repo.get_by_id(agg_id, Account)
        assert account.owner == "Diana"
        assert account.balance == 500.0

    @pytest.mark.asyncio
    async def test_concurrent_operations(self):
        """Test handling concurrent operations."""
        event_store = EventStore()
        repo = AggregateRepository(event_store)
        command_bus = CommandBus()

        async def deposit_handler(cmd: DepositCmd) -> CommandResult:
            agg_id = AggregateId(cmd.account_id, "Account")
            try:
                account = await repo.get_by_id(agg_id, Account)
            except Exception:  # REVIEWED: async context
                account = Account(agg_id)
                account.create("Test")

            account.deposit(cmd.amount)
            await repo.save(account, Metadata())
            return CommandResult.ok()

        command_bus.register_handler(DepositCmd, deposit_handler)

        # Create account
        agg_id = AggregateId("acc1", "Account")
        account = Account(agg_id)
        account.create("Eve")
        await repo.save(account, Metadata())

        # Execute multiple deposits concurrently
        tasks = [command_bus.execute(DepositCmd("acc1", 10.0)) for _ in range(5)]

        results = await asyncio.gather(*tasks, return_exceptions=True)
        successful = [r for r in results if not isinstance(r, Exception)]
        assert len(successful) >= 1

        # Check final balance
        final_account = await repo.get_by_id(agg_id, Account)
        # At least one deposit should have succeeded
        assert final_account.balance > 0

    @pytest.mark.asyncio
    async def test_snapshot_optimization(self):
        """Test snapshot optimization during reload."""
        event_store = EventStore()
        repo = AggregateRepository(event_store)

        agg_id = AggregateId("acc1", "Account")
        account1 = Account(agg_id)
        account1.create("Frank")

        # Add many events
        for i in range(20):
            account1.deposit(10.0)

        await repo.save(account1, Metadata())

        # Save snapshot
        await repo.save_snapshot(account1, frequency=1)

        # Add more events after snapshot
        account1.deposit(50.0)
        await repo.save(account1, Metadata())

        # Reload - should use snapshot and replay remaining events
        account2 = await repo.get_by_id(agg_id, Account)

        assert account2.version == 22  # 1 create + 20 deposits + 1 final
        assert account2.balance == 250.0
        assert account2.owner == "Frank"

    @pytest.mark.asyncio
    async def test_read_model_consistency(self):
        """Test read model stays consistent with events."""
        event_store = EventStore()
        repo = AggregateRepository(event_store)
        read_model = ReadModelStore()
        command_bus = CommandBus()

        async def deposit_handler(cmd: DepositCmd) -> CommandResult:
            agg_id = AggregateId(cmd.account_id, "Account")
            try:
                account = await repo.get_by_id(agg_id, Account)
            except Exception:  # REVIEWED: async context
                account = Account(agg_id)
                account.create("Test")

            account.deposit(cmd.amount)
            await repo.save(account, Metadata())

            # Update read model
            doc = await read_model.get(cmd.account_id)
            if doc:
                await read_model.update(cmd.account_id, {"balance": account.balance})
            else:
                await read_model.create(cmd.account_id, {"balance": account.balance})

            return CommandResult.ok()

        command_bus.register_handler(DepositCmd, deposit_handler)

        # Create account
        agg_id = AggregateId("acc1", "Account")
        account = Account(agg_id)
        account.create("Grace")
        await repo.save(account, Metadata())
        await read_model.create("acc1", {"balance": 0.0})

        # Execute deposits
        await command_bus.execute(DepositCmd("acc1", 100.0))
        await command_bus.execute(DepositCmd("acc1", 50.0))

        # Check consistency
        agg = await repo.get_by_id(agg_id, Account)
        doc = await read_model.get("acc1")

        assert agg.balance == 150.0
        assert doc.data["balance"] == 150.0
