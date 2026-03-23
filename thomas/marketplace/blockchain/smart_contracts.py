"""
Simple smart contract engine.

Implements contract deployment, invocation, state storage, and gas metering.
"""

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class GasOperation(Enum):
    """Gas costs for operations."""

    LOAD = 1
    STORE = 2
    TRANSFER = 3
    ARITHMETIC = 1
    COMPARE = 1
    CALL = 10


@dataclass
class ContractABI:
    """Contract Application Binary Interface."""

    name: str
    functions: dict[str, dict[str, Any]] = field(default_factory=dict)
    events: dict[str, list[str]] = field(default_factory=dict)

    def add_function(self, name: str, args: list[str], returns: str = "void") -> None:
        """
        Add function to ABI.

        Args:
            name: Function name.
            args: List of argument names.
            returns: Return type.
        """
        self.functions[name] = {"args": args, "returns": returns}

    def add_event(self, name: str, fields: list[str]) -> None:
        """
        Add event to ABI.

        Args:
            name: Event name.
            fields: List of field names.
        """
        self.events[name] = fields

    def to_dict(self) -> dict:
        """Serialize ABI."""
        return {
            "name": self.name,
            "functions": self.functions,
            "events": self.events,
        }


@dataclass
class ContractEvent:
    """Event emitted by contract."""

    name: str
    data: dict[str, Any]
    block_height: int = 0
    transaction_hash: str = ""
    log_index: int = 0

    def to_dict(self) -> dict:
        """Serialize event."""
        return {
            "name": self.name,
            "data": self.data,
            "block_height": self.block_height,
            "transaction_hash": self.transaction_hash,
            "log_index": self.log_index,
        }


@dataclass
class SmartContract:
    """Deployed smart contract."""

    address: str
    code: str  # Contract bytecode or source
    creator: str
    created_at_block: int
    balance: int = 0
    state: dict[str, Any] = field(default_factory=dict)
    abi: ContractABI = field(default_factory=lambda: ContractABI("Contract"))
    events_log: list[ContractEvent] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize contract."""
        return {
            "address": self.address,
            "code": self.code,
            "creator": self.creator,
            "created_at_block": self.created_at_block,
            "balance": self.balance,
            "state": self.state,
            "abi": self.abi.to_dict(),
            "events": [e.to_dict() for e in self.events_log],
        }


class ContractEngine:
    """
    Simple smart contract execution engine.

    Manages contract deployment, execution, state, and gas metering.
    """

    def __init__(self, gas_limit: int = 1000000) -> None:
        """
        Initialize contract engine.

        Args:
            gas_limit: Maximum gas per transaction.
        """
        self.contracts: dict[str, SmartContract] = {}
        self.gas_limit = gas_limit
        self.gas_used = 0
        self.call_stack: list[str] = []

    def deploy_contract(
        self,
        code: str,
        creator: str,
        initial_state: dict[str, Any] = None,
        abi: ContractABI = None,
        block_height: int = 0,
    ) -> str:
        """
        Deploy a new smart contract.

        Args:
            code: Contract code/bytecode.
            creator: Creator address.
            initial_state: Initial contract state.
            abi: Contract ABI.
            block_height: Block where contract was deployed.

        Returns:
            Contract address (hash of code + creator).
        """
        # Generate contract address
        address = self._generate_contract_address(code, creator)

        # Create contract
        contract = SmartContract(
            address=address,
            code=code,
            creator=creator,
            created_at_block=block_height,
            state=initial_state or {},
            abi=abi or ContractABI("Contract"),
        )

        self.contracts[address] = contract
        return address

    def _generate_contract_address(self, code: str, creator: str) -> str:
        """
        Generate contract address.

        Args:
            code: Contract code.
            creator: Creator address.

        Returns:
            Contract address as hex string.
        """
        data = code.encode() + creator.encode()
        return hashlib.sha256(data).hexdigest()[:40]

    def call_function(
        self,
        contract_address: str,
        function_name: str,
        args: dict[str, Any],
        caller: str = "",
        value: int = 0,
    ) -> Any:
        """
        Call contract function.

        Args:
            contract_address: Address of contract.
            function_name: Function to call.
            args: Function arguments.
            caller: Address calling the function.
            value: ETH/tokens sent with call.

        Returns:
            Function return value.

        Raises:
            ValueError: If contract/function not found.
        """
        contract = self.contracts.get(contract_address)
        if not contract:
            raise ValueError(f"Contract {contract_address} not found")

        # Simulate function execution
        self.gas_used = 0
        result = self._execute_function(contract, function_name, args)

        # Update contract balance if value sent
        if value > 0:
            contract.balance += value

        return result

    def _execute_function(self, contract: SmartContract, function_name: str, args: dict[str, Any]) -> Any:
        """
        Execute contract function (simplified).

        Args:
            contract: Contract instance.
            function_name: Function name.
            args: Arguments.

        Returns:
            Return value.
        """
        # Check if function exists in ABI
        if function_name not in contract.abi.functions:
            raise ValueError(f"Function {function_name} not found")

        # Simulate execution with gas metering
        self._charge_gas(GasOperation.CALL)

        # Execute different functions
        if function_name == "transfer":
            return self._execute_transfer(contract, args)
        elif function_name == "balanceOf":
            return self._execute_balance_of(contract, args)
        elif function_name == "store":
            return self._execute_store(contract, args)
        elif function_name == "load":
            return self._execute_load(contract, args)
        else:
            return None

    def _execute_transfer(self, contract: SmartContract, args: dict) -> bool:
        """
        Execute transfer function.

        Args:
            contract: Contract.
            args: Arguments (recipient, amount).

        Returns:
            True if successful.
        """
        self._charge_gas(GasOperation.TRANSFER)

        if "recipient" not in args or "amount" not in args:
            return False

        amount = args["amount"]
        if contract.balance >= amount:
            contract.balance -= amount
            return True
        return False

    def _execute_balance_of(self, contract: SmartContract, args: dict) -> int:
        """
        Get account balance.

        Args:
            contract: Contract.
            args: Arguments (address).

        Returns:
            Balance.
        """
        self._charge_gas(GasOperation.LOAD)
        return contract.balance

    def _execute_store(self, contract: SmartContract, args: dict) -> bool:
        """
        Store value in contract state.

        Args:
            contract: Contract.
            args: Arguments (key, value).

        Returns:
            True if successful.
        """
        self._charge_gas(GasOperation.STORE)

        if "key" not in args or "value" not in args:
            return False

        key = args["key"]
        value = args["value"]
        contract.state[key] = value
        return True

    def _execute_load(self, contract: SmartContract, args: dict) -> Any:
        """
        Load value from contract state.

        Args:
            contract: Contract.
            args: Arguments (key).

        Returns:
            Stored value or None.
        """
        self._charge_gas(GasOperation.LOAD)

        if "key" not in args:
            return None

        return contract.state.get(args["key"])

    def _charge_gas(self, operation: GasOperation) -> None:
        """
        Charge gas for operation.

        Args:
            operation: Operation type.

        Raises:
            ValueError: If gas limit exceeded.
        """
        cost = operation.value
        self.gas_used += cost

        if self.gas_used > self.gas_limit:
            raise ValueError(f"Gas limit exceeded: {self.gas_used} > {self.gas_limit}")

    def emit_event(
        self,
        contract_address: str,
        event_name: str,
        data: dict[str, Any],
        block_height: int = 0,
        tx_hash: str = "",
    ) -> bool:
        """
        Emit contract event.

        Args:
            contract_address: Contract address.
            event_name: Event name.
            data: Event data.
            block_height: Block height.
            tx_hash: Transaction hash.

        Returns:
            True if successful.
        """
        contract = self.contracts.get(contract_address)
        if not contract:
            return False

        # Validate event is in ABI
        if event_name not in contract.abi.events:
            return False

        event = ContractEvent(
            name=event_name,
            data=data,
            block_height=block_height,
            transaction_hash=tx_hash,
            log_index=len(contract.events_log),
        )

        contract.events_log.append(event)
        return True

    def get_contract(self, address: str) -> SmartContract | None:
        """
        Get contract by address.

        Args:
            address: Contract address.

        Returns:
            Contract or None if not found.
        """
        return self.contracts.get(address)

    def get_contract_state(self, address: str) -> dict | None:
        """
        Get contract state.

        Args:
            address: Contract address.

        Returns:
            State dictionary or None.
        """
        contract = self.contracts.get(address)
        return contract.state if contract else None

    def set_contract_state(self, address: str, key: str, value: Any) -> bool:
        """
        Set contract state value.

        Args:
            address: Contract address.
            key: State key.
            value: Value to set.

        Returns:
            True if successful.
        """
        contract = self.contracts.get(address)
        if not contract:
            return False

        contract.state[key] = value
        return True

    def get_contract_events(self, address: str, event_name: str = None) -> list[ContractEvent]:
        """
        Get contract events.

        Args:
            address: Contract address.
            event_name: Filter by event name (optional).

        Returns:
            List of events.
        """
        contract = self.contracts.get(address)
        if not contract:
            return []

        if event_name:
            return [e for e in contract.events_log if e.name == event_name]

        return contract.events_log

    def get_statistics(self) -> dict:
        """
        Get contract engine statistics.

        Returns:
            Statistics dictionary.
        """
        return {
            "contract_count": len(self.contracts),
            "total_balance": sum(c.balance for c in self.contracts.values()),
            "gas_used": self.gas_used,
            "gas_limit": self.gas_limit,
            "total_events": sum(len(c.events_log) for c in self.contracts.values()),
        }
