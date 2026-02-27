"""
Tests for smart contract engine.

Tests contract deployment, invocation, state, and gas metering.
"""

import pytest

from thomas.blockchain.smart_contracts import (
    ContractABI,
    ContractEngine,
)


@pytest.fixture
def contract_engine():
    """Create contract engine."""
    return ContractEngine(gas_limit=100000)


@pytest.fixture
def simple_abi():
    """Create simple contract ABI."""
    abi = ContractABI(name="SimpleContract")
    abi.add_function("transfer", ["recipient", "amount"], "bool")
    abi.add_function("balanceOf", ["address"], "int")
    abi.add_function("store", ["key", "value"], "bool")
    abi.add_function("load", ["key"], "any")
    return abi


class TestContractDeployment:
    """Test contract deployment."""

    def test_deploy_contract(self, contract_engine, simple_abi):
        """Test deploying a contract."""
        code = "contract { transfer() {...} }"
        creator = "0x1234567890abcdef"
        initial_state = {"balance": 1000}

        address = contract_engine.deploy_contract(
            code=code,
            creator=creator,
            initial_state=initial_state,
            abi=simple_abi,
            block_height=0,
        )

        assert isinstance(address, str)
        assert len(address) == 40

    def test_contract_address_deterministic(self, contract_engine, simple_abi):
        """Test contract address is deterministic."""
        code = "contract { ... }"
        creator = "creator_1"

        addr1 = contract_engine.deploy_contract(code=code, creator=creator, abi=simple_abi)
        addr2 = contract_engine.deploy_contract(code=code, creator=creator, abi=simple_abi)

        assert addr1 == addr2

    def test_different_code_different_address(self, contract_engine, simple_abi):
        """Test different code produces different addresses."""
        creator = "creator_1"

        addr1 = contract_engine.deploy_contract(code="code_1", creator=creator, abi=simple_abi)
        addr2 = contract_engine.deploy_contract(code="code_2", creator=creator, abi=simple_abi)

        assert addr1 != addr2

    def test_get_deployed_contract(self, contract_engine, simple_abi):
        """Test retrieving deployed contract."""
        code = "contract { ... }"
        creator = "creator_1"

        address = contract_engine.deploy_contract(code=code, creator=creator, abi=simple_abi)

        contract = contract_engine.get_contract(address)

        assert contract is not None
        assert contract.address == address
        assert contract.creator == creator


class TestContractInvocation:
    """Test calling contract functions."""

    def test_call_balanceOf(self, contract_engine, simple_abi):
        """Test calling balanceOf function."""
        address = contract_engine.deploy_contract(
            code="contract",
            creator="creator_1",
            initial_state={"balance": 5000},
            abi=simple_abi,
        )

        result = contract_engine.call_function(
            contract_address=address,
            function_name="balanceOf",
            args={"address": "owner"},
        )

        assert result == 5000

    def test_call_transfer(self, contract_engine, simple_abi):
        """Test calling transfer function."""
        address = contract_engine.deploy_contract(
            code="contract",
            creator="creator_1",
            initial_state={"balance": 1000},
            abi=simple_abi,
        )

        result = contract_engine.call_function(
            contract_address=address,
            function_name="transfer",
            args={"recipient": "recipient_1", "amount": 100},
        )

        assert result is True

    def test_call_transfer_insufficient_balance(self, contract_engine, simple_abi):
        """Test transfer fails with insufficient balance."""
        address = contract_engine.deploy_contract(
            code="contract",
            creator="creator_1",
            initial_state={"balance": 100},
            abi=simple_abi,
        )

        result = contract_engine.call_function(
            contract_address=address,
            function_name="transfer",
            args={"recipient": "recipient_1", "amount": 200},
        )

        assert result is False

    def test_call_store_and_load(self, contract_engine, simple_abi):
        """Test store and load functions."""
        address = contract_engine.deploy_contract(
            code="contract",
            creator="creator_1",
            abi=simple_abi,
        )

        # Store value
        result = contract_engine.call_function(
            contract_address=address,
            function_name="store",
            args={"key": "name", "value": "Alice"},
        )
        assert result is True

        # Load value
        result = contract_engine.call_function(
            contract_address=address,
            function_name="load",
            args={"key": "name"},
        )
        assert result == "Alice"

    def test_call_nonexistent_contract(self, contract_engine, simple_abi):
        """Test calling nonexistent contract fails."""
        with pytest.raises(ValueError):
            contract_engine.call_function(
                contract_address="0xdeadbeef",
                function_name="balanceOf",
                args={},
            )

    def test_call_nonexistent_function(self, contract_engine, simple_abi):
        """Test calling nonexistent function fails."""
        address = contract_engine.deploy_contract(
            code="contract",
            creator="creator_1",
            abi=simple_abi,
        )

        with pytest.raises(ValueError):
            contract_engine.call_function(
                contract_address=address,
                function_name="nonexistent_function",
                args={},
            )


class TestContractState:
    """Test contract state management."""

    def test_initial_state(self, contract_engine, simple_abi):
        """Test initial contract state."""
        initial = {"balance": 1000, "owner": "alice"}

        address = contract_engine.deploy_contract(
            code="contract",
            creator="creator_1",
            initial_state=initial,
            abi=simple_abi,
        )

        state = contract_engine.get_contract_state(address)

        assert state == initial

    def test_set_state_value(self, contract_engine, simple_abi):
        """Test setting contract state value."""
        address = contract_engine.deploy_contract(
            code="contract",
            creator="creator_1",
            abi=simple_abi,
        )

        contract_engine.set_contract_state(address, "key_1", "value_1")
        contract_engine.set_contract_state(address, "key_2", 12345)

        state = contract_engine.get_contract_state(address)

        assert state["key_1"] == "value_1"
        assert state["key_2"] == 12345

    def test_state_persistence(self, contract_engine, simple_abi):
        """Test state persists across calls."""
        address = contract_engine.deploy_contract(
            code="contract",
            creator="creator_1",
            abi=simple_abi,
        )

        # Call store
        contract_engine.call_function(
            contract_address=address,
            function_name="store",
            args={"key": "data", "value": "persistent"},
        )

        # State should persist
        contract = contract_engine.get_contract(address)
        assert contract.state["data"] == "persistent"


class TestGasMetering:
    """Test gas metering."""

    def test_gas_cost_load(self, contract_engine, simple_abi):
        """Test gas cost for load operation."""
        address = contract_engine.deploy_contract(
            code="contract",
            creator="creator_1",
            abi=simple_abi,
        )

        initial_gas = contract_engine.gas_used

        contract_engine.call_function(
            contract_address=address,
            function_name="load",
            args={"key": "test"},
        )

        # Load should cost gas
        assert contract_engine.gas_used > initial_gas

    def test_gas_cost_store(self, contract_engine, simple_abi):
        """Test gas cost for store operation."""
        address = contract_engine.deploy_contract(
            code="contract",
            creator="creator_1",
            abi=simple_abi,
        )

        initial_gas = contract_engine.gas_used

        contract_engine.call_function(
            contract_address=address,
            function_name="store",
            args={"key": "test", "value": "data"},
        )

        # Store should cost gas
        assert contract_engine.gas_used > initial_gas

    def test_gas_limit_exceeded(self, contract_engine, simple_abi):
        """Test exceeding gas limit."""
        # Create engine with low limit
        engine = ContractEngine(gas_limit=10)

        address = engine.deploy_contract(
            code="contract",
            creator="creator_1",
            abi=simple_abi,
        )

        # Call many functions to exceed limit
        with pytest.raises(ValueError):
            for i in range(100):
                engine.call_function(
                    contract_address=address,
                    function_name="load",
                    args={"key": "test"},
                )


class TestContractABI:
    """Test contract ABI."""

    def test_create_abi(self, simple_abi):
        """Test creating ABI."""
        assert simple_abi.name == "SimpleContract"
        assert "transfer" in simple_abi.functions

    def test_add_function_to_abi(self):
        """Test adding functions to ABI."""
        abi = ContractABI(name="TestABI")

        abi.add_function("test_fn", ["arg1", "arg2"], "string")

        assert "test_fn" in abi.functions
        assert abi.functions["test_fn"]["args"] == ["arg1", "arg2"]
        assert abi.functions["test_fn"]["returns"] == "string"

    def test_add_event_to_abi(self):
        """Test adding events to ABI."""
        abi = ContractABI(name="TestABI")

        abi.add_event("Transfer", ["from", "to", "amount"])

        assert "Transfer" in abi.events
        assert abi.events["Transfer"] == ["from", "to", "amount"]

    def test_abi_serialization(self, simple_abi):
        """Test ABI serialization."""
        abi_dict = simple_abi.to_dict()

        assert abi_dict["name"] == "SimpleContract"
        assert "transfer" in abi_dict["functions"]


class TestContractEvents:
    """Test contract events."""

    def test_emit_event(self, contract_engine, simple_abi):
        """Test emitting contract event."""
        address = contract_engine.deploy_contract(
            code="contract",
            creator="creator_1",
            abi=simple_abi,
        )

        # Add event to ABI
        simple_abi.add_event("Transfer", ["from", "to", "amount"])

        result = contract_engine.emit_event(
            contract_address=address,
            event_name="Transfer",
            data={"from": "alice", "to": "bob", "amount": 100},
        )

        assert result is True

    def test_get_contract_events(self, contract_engine, simple_abi):
        """Test retrieving contract events."""
        simple_abi.add_event("Transfer", ["from", "to", "amount"])

        address = contract_engine.deploy_contract(
            code="contract",
            creator="creator_1",
            abi=simple_abi,
        )

        # Emit events
        contract_engine.emit_event(
            contract_address=address,
            event_name="Transfer",
            data={"from": "alice", "to": "bob", "amount": 100},
        )

        contract_engine.emit_event(
            contract_address=address,
            event_name="Transfer",
            data={"from": "bob", "to": "charlie", "amount": 50},
        )

        events = contract_engine.get_contract_events(address)

        assert len(events) == 2

    def test_filter_events_by_name(self, contract_engine, simple_abi):
        """Test filtering events by name."""
        simple_abi.add_event("Transfer", ["from", "to", "amount"])
        simple_abi.add_event("Approval", ["owner", "spender", "amount"])

        address = contract_engine.deploy_contract(
            code="contract",
            creator="creator_1",
            abi=simple_abi,
        )

        # Emit different events
        contract_engine.emit_event(
            contract_address=address,
            event_name="Transfer",
            data={"from": "alice", "to": "bob", "amount": 100},
        )

        contract_engine.emit_event(
            contract_address=address,
            event_name="Approval",
            data={"owner": "alice", "spender": "bob", "amount": 200},
        )

        # Get only Transfer events
        events = contract_engine.get_contract_events(address, "Transfer")

        assert len(events) == 1
        assert events[0].name == "Transfer"


class TestContractStatistics:
    """Test contract statistics."""

    def test_get_statistics(self, contract_engine, simple_abi):
        """Test getting engine statistics."""
        # Deploy a few contracts
        for i in range(3):
            contract_engine.deploy_contract(
                code=f"contract_{i}",
                creator="creator_1",
                abi=simple_abi,
            )

        stats = contract_engine.get_statistics()

        assert stats["contract_count"] == 3
        assert "gas_used" in stats
        assert "gas_limit" in stats
