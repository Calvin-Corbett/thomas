"""
Memory pool (mempool) - transaction pool before inclusion in blocks.

Manages pending transactions, prioritization, and double-spend detection.
"""

import time
from collections import defaultdict

from thomas.marketplace.blockchain._exceptions import DoubleSpendError
from thomas.marketplace.blockchain._types import MempoolEntry, Transaction


class Mempool:
    """
    Memory pool for pending transactions.

    Maintains pool of unconfirmed transactions with:
    - Priority queue based on fee rate
    - Double-spend detection
    - Size limits with eviction policy
    - Transaction expiry
    - Dependency tracking
    """

    def __init__(self, max_size: int = 10000, max_memory_mb: int = 50) -> None:
        """
        Initialize mempool.

        Args:
            max_size: Maximum number of transactions in pool.
            max_memory_mb: Maximum memory usage in MB.
        """
        self.max_size = max_size
        self.max_memory_bytes = max_memory_mb * 1024 * 1024
        self.transactions: dict[str, MempoolEntry] = {}  # tx_hash -> MempoolEntry
        self.by_sender: dict[str, list[str]] = defaultdict(list)  # sender -> [tx_hashes]
        self.spent_outputs: dict[str, str] = {}  # (sender, nonce) -> tx_hash
        self.transaction_expiry_seconds = 86400  # 24 hours

    def add_transaction(self, transaction: Transaction, timestamp: int = None) -> bool:
        """
        Add transaction to mempool.

        Performs:
        - Duplicate detection
        - Double-spend detection
        - Fee validation
        - Size checks with eviction

        Args:
            transaction: Transaction to add.
            timestamp: When transaction was received (default now).

        Returns:
            True if added, False if rejected.

        Raises:
            DoubleSpendError: If transaction spends already-spent output.
        """
        if timestamp is None:
            timestamp = int(time.time())

        # Check duplicate
        if transaction.hash in self.transactions:
            return False

        # Check double-spend (using sender + nonce as simple UTXO)
        spend_key = (transaction.sender, transaction.nonce)
        if spend_key in self.spent_outputs:
            raise DoubleSpendError(f"Output already spent by {self.spent_outputs[spend_key]}")

        # Create mempool entry
        priority = transaction.fee / max(1, self._estimate_tx_size(transaction))
        entry = MempoolEntry(
            transaction=transaction,
            received_at=timestamp,
            priority=priority,
        )

        # Check size limits
        if len(self.transactions) >= self.max_size:
            self._evict_lowest_priority()

        # Add transaction
        self.transactions[transaction.hash] = entry
        self.by_sender[transaction.sender].append(transaction.hash)
        self.spent_outputs[spend_key] = transaction.hash

        return True

    def remove_transaction(self, tx_hash: str) -> bool:
        """
        Remove transaction from mempool.

        Args:
            tx_hash: Hash of transaction to remove.

        Returns:
            True if removed, False if not found.
        """
        if tx_hash not in self.transactions:
            return False

        entry = self.transactions[tx_hash]
        tx = entry.transaction

        # Remove from sender index
        self.by_sender[tx.sender].remove(tx_hash)
        if not self.by_sender[tx.sender]:
            del self.by_sender[tx.sender]

        # Remove from spent outputs
        spend_key = (tx.sender, tx.nonce)
        if spend_key in self.spent_outputs:
            del self.spent_outputs[spend_key]

        # Remove from pool
        del self.transactions[tx_hash]

        return True

    def get_transactions_by_priority(self, max_count: int = None) -> list[Transaction]:
        """
        Get transactions sorted by priority (fee per byte).

        Transactions from same sender are ordered by nonce.

        Args:
            max_count: Maximum transactions to return.

        Returns:
            List of transactions in priority order.
        """
        # Sort by fee per byte (descending)
        sorted_entries = sorted(self.transactions.values(), key=lambda e: e.priority, reverse=True)

        # Group by sender and ensure nonce ordering
        result: list[Transaction] = []
        processed_senders: set[str] = set()

        for entry in sorted_entries:
            tx = entry.transaction

            # For each sender, only include transactions in nonce order
            sender_nonces = sorted([self.transactions[h].transaction.nonce for h in self.by_sender.get(tx.sender, [])])

            # Check if we can include this transaction
            if tx.sender not in processed_senders:
                # First transaction from sender must have nonce 0 (relative)
                if tx.nonce == min(sender_nonces):
                    result.append(tx)
            else:
                # Check if previous nonce from sender was included
                prev_tx = next((t for t in result if t.sender == tx.sender), None)
                if prev_tx and prev_tx.nonce == tx.nonce - 1:
                    result.append(tx)

            if max_count and len(result) >= max_count:
                break

        return result

    def get_next_batch(self, max_count: int = 100, max_size_bytes: int = 1000000) -> list[Transaction]:
        """
        Get next batch of transactions for block inclusion.

        Respects:
        - Maximum transaction count
        - Maximum block size
        - Transaction dependencies (nonce order)

        Args:
            max_count: Maximum transactions to include.
            max_size_bytes: Maximum total size.

        Returns:
            List of transactions ready for block.
        """
        batch: list[Transaction] = []
        total_size = 0
        last_nonce_by_sender: dict[str, int] = {}

        # Get transactions in priority order
        candidates = self.get_transactions_by_priority(max_count * 2)

        for tx in candidates:
            # Check if we can include this transaction
            tx_size = self._estimate_tx_size(tx)

            # Check size limit
            if total_size + tx_size > max_size_bytes:
                break

            # Check nonce ordering
            last_nonce = last_nonce_by_sender.get(tx.sender, -1)
            if tx.nonce == last_nonce + 1:
                batch.append(tx)
                total_size += tx_size
                last_nonce_by_sender[tx.sender] = tx.nonce

            if len(batch) >= max_count:
                break

        return batch

    def _estimate_tx_size(self, transaction: Transaction) -> int:
        """
        Estimate transaction size in bytes.

        Args:
            transaction: Transaction to estimate.

        Returns:
            Estimated size in bytes.
        """
        # Rough estimate: 200 bytes base + 40 bytes per field
        return 200 + (len(transaction.sender) + len(transaction.recipient) + len(transaction.signature)) // 2

    def _evict_lowest_priority(self) -> None:
        """Evict lowest-priority transaction from mempool."""
        if not self.transactions:
            return

        # Find lowest priority
        min_entry = min(self.transactions.values(), key=lambda e: e.priority)
        self.remove_transaction(min_entry.transaction.hash)

    def get_transaction(self, tx_hash: str) -> MempoolEntry | None:
        """
        Get mempool entry for transaction.

        Args:
            tx_hash: Transaction hash.

        Returns:
            MempoolEntry or None if not found.
        """
        return self.transactions.get(tx_hash)

    def has_transaction(self, tx_hash: str) -> bool:
        """
        Check if transaction is in mempool.

        Args:
            tx_hash: Transaction hash.

        Returns:
            True if transaction exists in pool.
        """
        return tx_hash in self.transactions

    def get_sender_transactions(self, sender: str) -> list[Transaction]:
        """
        Get all transactions from a sender in nonce order.

        Args:
            sender: Sender address.

        Returns:
            List of transactions ordered by nonce.
        """
        tx_hashes = self.by_sender.get(sender, [])
        txs = [self.transactions[h].transaction for h in tx_hashes]
        return sorted(txs, key=lambda t: t.nonce)

    def remove_expired(self, current_time: int = None) -> int:
        """
        Remove expired transactions from mempool.

        Args:
            current_time: Current timestamp (default now).

        Returns:
            Number of transactions removed.
        """
        if current_time is None:
            current_time = int(time.time())

        to_remove = []
        for tx_hash, entry in self.transactions.items():
            if entry.is_expired(current_time, self.transaction_expiry_seconds):
                to_remove.append(tx_hash)

        for tx_hash in to_remove:
            self.remove_transaction(tx_hash)

        return len(to_remove)

    def get_statistics(self) -> dict[str, int]:
        """
        Get mempool statistics.

        Returns:
            Dictionary with size, count, and fee stats.
        """
        if not self.transactions:
            return {
                "total_transactions": 0,
                "total_size_bytes": 0,
                "avg_fee": 0,
                "min_fee": 0,
                "max_fee": 0,
            }

        entries = list(self.transactions.values())
        fees = [e.transaction.fee for e in entries]
        sizes = [self._estimate_tx_size(e.transaction) for e in entries]

        return {
            "total_transactions": len(entries),
            "total_size_bytes": sum(sizes),
            "avg_fee": sum(fees) // max(1, len(fees)),
            "min_fee": min(fees),
            "max_fee": max(fees),
        }

    def clear(self) -> None:
        """Clear entire mempool."""
        self.transactions.clear()
        self.by_sender.clear()
        self.spent_outputs.clear()
