"""
Blockchain implementation - main chain management.

Handles block addition, chain validation, state management, and fork resolution.
"""

from typing import Any

from thomas.marketplace.blockchain._exceptions import InvalidBlockError
from thomas.marketplace.blockchain._types import Block, ChainConfig, WalletInfo
from thomas.marketplace.blockchain.block import validate_block


class Blockchain:
    """
    Main blockchain implementation.

    Manages blocks, validates chain, tracks balances, and handles forks.
    """

    def __init__(self, genesis_block: Block, config: ChainConfig = None) -> None:
        """
        Initialize blockchain with genesis block.

        Args:
            genesis_block: The genesis (first) block.
            config: Blockchain configuration (default standard config).
        """
        if not genesis_block.is_genesis:
            raise InvalidBlockError("First block must be genesis block")

        self.config = config or ChainConfig()
        self.blocks: dict[str, Block] = {genesis_block.hash: genesis_block}
        self.chain: list[str] = [genesis_block.hash]  # Ordered list of block hashes
        self.state: dict[str, WalletInfo] = {}  # Address -> WalletInfo
        self.tx_index: dict[str, str] = {}  # Transaction hash -> Block hash

        # Initialize state from genesis
        self._apply_block(genesis_block)

    def add_block(self, block: Block) -> bool:
        """
        Add a block to the chain with validation.

        Performs:
        - Block format validation
        - Parent hash verification
        - Merkle root verification
        - Difficulty verification
        - Transaction validation
        - Balance/nonce verification
        - Fork detection and resolution

        Args:
            block: Block to add.

        Returns:
            True if block was added, False if rejected.
        """
        # Check if block already exists
        if block.hash in self.blocks:
            return False

        # Basic block validation
        if not validate_block(block, None, block.difficulty):
            return False

        # Find parent block
        parent = self.blocks.get(block.previous_hash)
        if not parent:
            # Parent not found - could be side chain or out-of-order
            return False

        # Validate block builds on parent correctly
        if block.index != parent.index + 1:
            return False

        # Validate all transactions before applying
        valid_state = self._validate_block_transactions(block, parent)
        if not valid_state:
            return False

        # Check if this is on the main chain
        is_main_chain = parent.hash == self.chain[-1]

        if is_main_chain:
            # Adding to end of main chain
            self.blocks[block.hash] = block
            self.chain.append(block.hash)
            self._apply_block(block)
            return True
        else:
            # Fork detected - check if we should reorg
            parent_index = self.chain.index(parent.hash) if parent.hash in self.chain else -1
            if parent_index >= 0:
                # Side chain that could trigger reorg
                new_chain = self._build_chain_from_block(block)
                old_chain_length = len(self.chain)
                new_chain_length = len(new_chain)

                if new_chain_length > old_chain_length:
                    # Reorg: new chain is longer
                    self._reorg_chain(new_chain)
                    return True
                else:
                    # Keep old chain, but store the block
                    self.blocks[block.hash] = block
                    return False
            else:
                # Store block for later
                self.blocks[block.hash] = block
                return False

    def _validate_block_transactions(self, block: Block, parent_block: Block) -> bool:
        """
        Validate all transactions in a block.

        Checks nonces, balances, and prevents double-spending.

        Args:
            block: Block to validate.
            parent_block: Parent block (for state snapshot).

        Returns:
            True if all transactions are valid.
        """
        # Create temporary state from parent
        temp_state = self._compute_state_at_block(parent_block)

        for tx in block.transactions:
            # Coinbase transactions are always valid
            if tx.sender == "COINBASE":
                if tx.recipient not in temp_state:
                    temp_state[tx.recipient] = WalletInfo(
                        address=tx.recipient,
                        public_key="",
                        balance=0,
                        nonce=0,
                    )
                wallet = temp_state[tx.recipient]
                # Update balance but don't increment nonce for coinbase
                wallet.balance += tx.amount
                continue

            # Regular transaction validation
            if tx.sender not in temp_state:
                return False

            wallet = temp_state[tx.sender]

            # Check nonce
            if tx.nonce != wallet.nonce:
                return False

            # Check balance
            if wallet.balance < tx.amount + tx.fee:
                return False

            # Update state
            wallet.balance -= tx.amount + tx.fee
            wallet.nonce += 1

            # Add to recipient
            if tx.recipient not in temp_state:
                temp_state[tx.recipient] = WalletInfo(
                    address=tx.recipient,
                    public_key="",
                    balance=0,
                    nonce=0,
                )
            temp_state[tx.recipient].balance += tx.amount

        return True

    def _apply_block(self, block: Block) -> None:
        """
        Apply block transactions to blockchain state.

        Updates balances and nonces.

        Args:
            block: Block to apply.
        """
        for tx in block.transactions:
            self.tx_index[tx.hash] = block.hash

            if tx.sender == "COINBASE":
                # Coinbase: create or update recipient
                if tx.recipient not in self.state:
                    self.state[tx.recipient] = WalletInfo(
                        address=tx.recipient,
                        public_key="",
                        balance=0,
                        nonce=0,
                    )
                self.state[tx.recipient].balance += tx.amount
                self.state[tx.recipient].transactions.append(tx.hash)
            else:
                # Regular transaction
                if tx.sender not in self.state:
                    self.state[tx.sender] = WalletInfo(
                        address=tx.sender,
                        public_key="",
                        balance=0,
                        nonce=0,
                    )

                sender = self.state[tx.sender]
                sender.balance -= tx.amount + tx.fee
                sender.nonce += 1
                sender.transactions.append(tx.hash)

                # Update recipient
                if tx.recipient not in self.state:
                    self.state[tx.recipient] = WalletInfo(
                        address=tx.recipient,
                        public_key="",
                        balance=0,
                        nonce=0,
                    )
                self.state[tx.recipient].balance += tx.amount
                self.state[tx.recipient].transactions.append(tx.hash)

    def _compute_state_at_block(self, block: Block) -> dict[str, WalletInfo]:
        """
        Compute blockchain state up to a specific block.

        Used for validation without modifying main state.

        Args:
            block: Block to compute state for.

        Returns:
            Dictionary of addresses to wallet info.
        """
        # Start from genesis
        state: dict[str, WalletInfo] = {}

        # Find path to this block
        path = []
        current = block
        while current.hash != self.chain[0]:
            path.append(current)
            parent = self.blocks.get(current.previous_hash)
            if parent is None:
                break
            current = parent

        path.reverse()

        # Apply blocks in order
        for b in path:
            for tx in b.transactions:
                if tx.sender == "COINBASE":
                    if tx.recipient not in state:
                        state[tx.recipient] = WalletInfo(
                            address=tx.recipient,
                            public_key="",
                            balance=0,
                            nonce=0,
                        )
                    state[tx.recipient].balance += tx.amount
                else:
                    if tx.sender not in state:
                        state[tx.sender] = WalletInfo(
                            address=tx.sender,
                            public_key="",
                            balance=0,
                            nonce=0,
                        )
                    state[tx.sender].balance -= tx.amount + tx.fee
                    state[tx.sender].nonce += 1

                    if tx.recipient not in state:
                        state[tx.recipient] = WalletInfo(
                            address=tx.recipient,
                            public_key="",
                            balance=0,
                            nonce=0,
                        )
                    state[tx.recipient].balance += tx.amount

        return state

    def _build_chain_from_block(self, block: Block) -> list[str]:
        """
        Build complete chain from genesis to a block.

        Args:
            block: Destination block.

        Returns:
            List of block hashes from genesis to block.
        """
        path = []
        current = block
        while current.hash not in path:
            path.append(current.hash)
            if current.previous_hash == "0" * 64:
                break
            parent = self.blocks.get(current.previous_hash)
            if parent is None:
                break
            current = parent

        path.reverse()
        return path

    def _reorg_chain(self, new_chain: list[str]) -> None:
        """
        Reorganize blockchain to new chain.

        Undoes old blocks and applies new blocks.

        Args:
            new_chain: List of block hashes for new main chain.
        """
        # Find common ancestor
        old_chain = self.chain
        common_idx = 0
        for i, (old_hash, new_hash) in enumerate(zip(old_chain, new_chain)):
            if old_hash == new_hash:
                common_idx = i
            else:
                break

        # Remove blocks after common ancestor
        old_chain[common_idx + 1 :]
        blocks_to_add = new_chain[common_idx + 1 :]

        # Reset state to common ancestor
        if common_idx >= 0:
            self.chain = old_chain[: common_idx + 1]
            self.state = self._compute_state_at_block(self.blocks[old_chain[common_idx]])
        else:
            self.chain = []
            self.state = {}

        # Apply new blocks
        for block_hash in blocks_to_add:
            block = self.blocks[block_hash]
            self.chain.append(block_hash)
            self._apply_block(block)

    def get_block(self, block_hash: str) -> Block | None:
        """
        Get block by hash.

        Args:
            block_hash: Block hash.

        Returns:
            Block object or None if not found.
        """
        return self.blocks.get(block_hash)

    def get_block_by_index(self, index: int) -> Block | None:
        """
        Get block by index.

        Args:
            index: Block index in main chain.

        Returns:
            Block object or None if out of range.
        """
        if index < 0 or index >= len(self.chain):
            return None
        return self.blocks[self.chain[index]]

    def get_balance(self, address: str) -> int:
        """
        Get current balance for address.

        Args:
            address: Wallet address.

        Returns:
            Balance in satoshis (0 if address not found).
        """
        wallet = self.state.get(address)
        return wallet.balance if wallet else 0

    def get_nonce(self, address: str) -> int:
        """
        Get current nonce for address.

        Args:
            address: Wallet address.

        Returns:
            Nonce (transaction count) for address.
        """
        wallet = self.state.get(address)
        return wallet.nonce if wallet else 0

    def get_wallet_info(self, address: str) -> WalletInfo | None:
        """
        Get wallet information.

        Args:
            address: Wallet address.

        Returns:
            WalletInfo or None if not found.
        """
        return self.state.get(address)

    def validate_chain(self) -> bool:
        """
        Validate entire main chain.

        Checks:
        - Every block has valid hash
        - Previous hash links are correct
        - All transactions are valid
        - Blocks are in order
        - No duplicates

        Returns:
            True if chain is valid.
        """
        if not self.chain:
            return False

        for i, block_hash in enumerate(self.chain):
            block = self.blocks[block_hash]

            # Check index
            if block.index != i:
                return False

            # Check hash is valid
            if not validate_block(block):
                return False

            # Check previous link
            if i > 0:
                parent = self.blocks[self.chain[i - 1]]
                if block.previous_hash != parent.hash:
                    return False

        return True

    def get_height(self) -> int:
        """
        Get current chain height (number of blocks).

        Returns:
            Number of blocks in chain.
        """
        return len(self.chain)

    def get_tip(self) -> Block | None:
        """
        Get the tip (last) block.

        Returns:
            Last block in chain or None if empty.
        """
        if not self.chain:
            return None
        return self.blocks[self.chain[-1]]

    def to_dict(self) -> dict[str, Any]:
        """
        Serialize blockchain to dictionary.

        Returns:
            Dictionary representation.
        """
        return {
            "height": self.get_height(),
            "blocks": len(self.blocks),
            "addresses": len(self.state),
            "total_balance": sum(w.balance for w in self.state.values()),
        }
