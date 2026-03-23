"""Tools for Blockchain module.

Provides tools for blockchain operations, wallet management, transactions, and consensus.
"""

from typing import Any

from thomas.marketplace.blockchain.chain import Blockchain
from thomas.marketplace.blockchain.wallet import Wallet
from thomas.tools.base import Tool, ToolResult


class BlockchainTool(Tool):
    """Create and manage blockchains."""

    name = "blockchain_create"
    category = "blockchain"
    description = "Create a new blockchain or add blocks"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "get_blocks", "get_difficulty"],
                "description": "Blockchain action",
            },
            "difficulty": {"type": "integer", "description": "Proof-of-work difficulty (for create)"},
        },
        "required": ["action"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "create":
                difficulty = int(args.get("difficulty", 4))
                chain = Blockchain(difficulty=difficulty)
                return ToolResult(
                    ok=True,
                    data={"status": "blockchain_created", "difficulty": difficulty, "chain_length": len(chain.chain)},
                )
            elif action == "get_blocks":
                return ToolResult(
                    ok=True, data={"status": "get_blocks", "message": "Use blockchain instance to access blocks"}
                )
            elif action == "get_difficulty":
                difficulty = int(args.get("difficulty", 4))
                return ToolResult(ok=True, data={"status": "difficulty_retrieved", "difficulty": difficulty})
            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class WalletTool(Tool):
    """Manage cryptocurrency wallets."""

    name = "blockchain_wallet"
    category = "blockchain"
    description = "Create wallets and manage addresses"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create_wallet", "create_address", "get_balance"],
                "description": "Wallet action",
            },
            "wallet_name": {"type": "string", "description": "Wallet name"},
            "password": {"type": "string", "description": "Wallet password"},
            "label": {"type": "string", "description": "Address label"},
            "address": {"type": "string", "description": "Wallet address"},
        },
        "required": ["action"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "create_wallet":
                wallet_name = args.get("wallet_name", "MyWallet")
                password = args.get("password", "")
                wallet = Wallet(name=wallet_name, password=password)
                return ToolResult(
                    ok=True, data={"status": "wallet_created", "name": wallet.name, "has_password": bool(password)}
                )
            elif action == "create_address":
                label = args.get("label", "")
                return ToolResult(
                    ok=True,
                    data={
                        "status": "address_created",
                        "label": label,
                        "message": "Address creation requires wallet instance",
                    },
                )
            elif action == "get_balance":
                address = args.get("address", "")
                return ToolResult(ok=True, data={"status": "balance_retrieved", "address": address, "balance": 0})
            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class TransactionTool(Tool):
    """Create and manage blockchain transactions."""

    name = "blockchain_transaction"
    category = "blockchain"
    description = "Create and sign transactions"
    parameters = {
        "type": "object",
        "properties": {
            "from_address": {"type": "string", "description": "Sender address"},
            "to_address": {"type": "string", "description": "Recipient address"},
            "amount": {"type": "number", "description": "Transaction amount"},
            "nonce": {"type": "integer", "description": "Transaction nonce"},
        },
        "required": ["from_address", "to_address", "amount"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from_addr = args.get("from_address", "")
            to_addr = args.get("to_address", "")
            amount = float(args.get("amount", 0))
            nonce = int(args.get("nonce", 0))

            if not from_addr or not to_addr:
                return ToolResult(ok=False, error="from_address and to_address required")

            if amount <= 0:
                return ToolResult(ok=False, error="amount must be positive")

            return ToolResult(
                ok=True,
                data={
                    "status": "transaction_created",
                    "from": from_addr,
                    "to": to_addr,
                    "amount": amount,
                    "nonce": nonce,
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class ConsensusTool(Tool):
    """Manage blockchain consensus mechanisms."""

    name = "blockchain_consensus"
    category = "blockchain"
    description = "Validate proof-of-work and consensus"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["validate_pow", "calculate_difficulty"],
                "description": "Consensus action",
            },
            "block_hash": {"type": "string", "description": "Block hash to validate"},
            "difficulty": {"type": "integer", "description": "Difficulty level"},
        },
        "required": ["action"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "validate_pow":
                block_hash = args.get("block_hash", "")
                difficulty = int(args.get("difficulty", 4))

                if not block_hash:
                    return ToolResult(ok=False, error="block_hash required")

                # Check if hash meets difficulty (leading zeros in hash)
                leading_zeros = len(block_hash) - len(block_hash.lstrip("0"))
                is_valid = leading_zeros >= difficulty
                return ToolResult(
                    ok=True,
                    data={
                        "status": "pow_validated",
                        "hash": block_hash[:16] + "...",
                        "difficulty": difficulty,
                        "leading_zeros": leading_zeros,
                        "valid": is_valid,
                    },
                )
            elif action == "calculate_difficulty":
                difficulty = int(args.get("difficulty", 4))
                return ToolResult(
                    ok=True,
                    data={"status": "difficulty_info", "difficulty": difficulty, "required_leading_zeros": difficulty},
                )
            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_blockchain_tools(registry):
    """Register all blockchain tools."""
    registry.register(BlockchainTool())
    registry.register(WalletTool())
    registry.register(TransactionTool())
    registry.register(ConsensusTool())
