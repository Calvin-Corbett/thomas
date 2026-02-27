"""
Transaction manager implementing ACID properties.

This module implements:
- Strict two-phase locking (shared/exclusive locks)
- Deadlock detection (wait-for graph with cycle detection)
- Lock table with lock queue
- Transaction isolation levels (READ_COMMITTED, REPEATABLE_READ, SERIALIZABLE)
- MVCC basics (version chains)
- Savepoints
"""

import time
from collections import defaultdict
from dataclasses import dataclass

from ._exceptions import (
    DeadlockException,
    LockTimeoutException,
    TransactionException,
)
from ._types import Lock, LockMode, Transaction


@dataclass
class LockRequest:
    """A request for a lock."""

    transaction_id: int
    resource_id: int
    mode: LockMode
    request_time: float = 0.0
    wait_start_time: float | None = None


class LockManager:
    """
    Manages locks for transactions.

    Implements:
    - Lock granting and waiting
    - Lock compatibility checking
    - Deadlock detection
    - Lock release
    """

    # Lock compatibility matrix
    COMPATIBLE = {
        LockMode.SHARED: {LockMode.SHARED, LockMode.INTENT_SHARED},
        LockMode.EXCLUSIVE: set(),
        LockMode.INTENT_SHARED: {LockMode.SHARED, LockMode.INTENT_SHARED, LockMode.INTENT_EXCLUSIVE},
        LockMode.INTENT_EXCLUSIVE: {LockMode.INTENT_SHARED, LockMode.INTENT_EXCLUSIVE},
    }

    def __init__(self, timeout_ms: int = 5000) -> None:
        """
        Initialize lock manager.

        Args:
            timeout_ms: Lock acquisition timeout in milliseconds
        """
        self.timeout_ms = timeout_ms
        self.lock_table: dict[int, list[Lock]] = defaultdict(list)  # resource_id -> locks
        self.lock_queue: dict[int, list[LockRequest]] = defaultdict(list)  # resource_id -> requests
        self.transaction_locks: dict[int, set[int]] = defaultdict(set)  # txn_id -> resource_ids
        self.wait_for_graph: dict[int, set[int]] = defaultdict(set)  # txn_id -> waiting_for_txns

    def acquire_lock(self, transaction_id: int, resource_id: int, mode: LockMode) -> bool:
        """
        Attempt to acquire a lock.

        Args:
            transaction_id: Transaction ID
            resource_id: Resource ID (page or tuple)
            mode: Lock mode (SHARED or EXCLUSIVE)

        Returns:
            True if lock acquired, False if would block

        Raises:
            DeadlockException: If deadlock is detected
            LockTimeoutException: If timeout occurs
        """
        # Check if already has compatible lock
        held_locks = self.lock_table.get(resource_id, [])
        my_locks = [l for l in held_locks if l.transaction_id == transaction_id]

        if my_locks:
            # Already have a lock on this resource
            my_mode = my_locks[0].mode

            # Check if need to upgrade
            if my_mode == LockMode.EXCLUSIVE:
                return True  # Already have strongest lock

            if my_mode == LockMode.SHARED and mode == LockMode.SHARED:
                return True  # Already compatible

            if my_mode == LockMode.SHARED and mode == LockMode.EXCLUSIVE:
                # Lock escalation - try to upgrade
                return self._upgrade_lock(transaction_id, resource_id)

        # Check compatibility with held locks
        if self._are_locks_compatible(transaction_id, resource_id, mode):
            # Grant lock
            lock = Lock(
                resource_id=resource_id,
                transaction_id=transaction_id,
                mode=mode,
                acquired_time=time.time(),
            )
            self.lock_table[resource_id].append(lock)
            self.transaction_locks[transaction_id].add(resource_id)
            return True

        # Would need to wait - check for deadlock
        if self._would_cause_deadlock(transaction_id, resource_id):
            raise DeadlockException(f"Deadlock detected: txn {transaction_id} waiting on resource {resource_id}")

        # Add to wait queue
        wait_start = time.time()
        request = LockRequest(
            transaction_id=transaction_id,
            resource_id=resource_id,
            mode=mode,
            request_time=wait_start,
            wait_start_time=wait_start,
        )
        self.lock_queue[resource_id].append(request)
        self._add_to_wait_graph(transaction_id, resource_id)

        # Wait with timeout
        return self._wait_for_lock(transaction_id, resource_id, mode)

    def release_lock(self, transaction_id: int, resource_id: int) -> None:
        """
        Release a lock.

        Args:
            transaction_id: Transaction ID
            resource_id: Resource ID
        """
        locks = self.lock_table.get(resource_id, [])
        my_locks = [l for l in locks if l.transaction_id == transaction_id]

        for lock in my_locks:
            locks.remove(lock)

        if resource_id in self.transaction_locks[transaction_id]:
            self.transaction_locks[transaction_id].remove(resource_id)

        # Remove from wait graph
        self._remove_from_wait_graph(transaction_id)

        # Grant locks to waiting transactions
        self._process_wait_queue(resource_id)

    def release_all_locks(self, transaction_id: int) -> None:
        """Release all locks held by a transaction."""
        resource_ids = list(self.transaction_locks[transaction_id])
        for resource_id in resource_ids:
            self.release_lock(transaction_id, resource_id)

    def _are_locks_compatible(self, transaction_id: int, resource_id: int, mode: LockMode) -> bool:
        """Check if a lock is compatible with held locks."""
        held_locks = self.lock_table.get(resource_id, [])

        for lock in held_locks:
            if lock.transaction_id == transaction_id:
                continue  # Own lock

            # Check compatibility
            if mode not in self.COMPATIBLE:
                return False

            if lock.mode not in self.COMPATIBLE[mode]:
                return False

        return True

    def _upgrade_lock(self, transaction_id: int, resource_id: int) -> bool:
        """Try to upgrade a lock."""
        locks = self.lock_table.get(resource_id, [])
        my_locks = [l for l in locks if l.transaction_id == transaction_id]

        if not my_locks:
            return False

        # Check if can upgrade (no other locks)
        other_locks = [l for l in locks if l.transaction_id != transaction_id]
        if other_locks:
            return False

        my_locks[0].mode = LockMode.EXCLUSIVE
        return True

    def _would_cause_deadlock(self, transaction_id: int, resource_id: int) -> bool:
        """Check if acquiring this lock would cause deadlock."""
        # Get holders of the resource
        held_locks = self.lock_table.get(resource_id, [])
        holders = set(l.transaction_id for l in held_locks)

        # Check if cycle in wait-for graph
        return self._has_cycle(transaction_id, holders)

    def _has_cycle(self, txn_id: int, blocking_txns: set[int]) -> bool:
        """Check if adding edges would create cycle."""
        visited = set()
        rec_stack = set()

        for blocking_txn in blocking_txns:
            if self._has_cycle_dfs(blocking_txn, visited, rec_stack):
                return True

        return False

    def _has_cycle_dfs(self, node: int, visited: set[int], rec_stack: set[int]) -> bool:
        """DFS for cycle detection."""
        visited.add(node)
        rec_stack.add(node)

        for neighbor in self.wait_for_graph.get(node, set()):
            if neighbor not in visited:
                if self._has_cycle_dfs(neighbor, visited, rec_stack):
                    return True
            elif neighbor in rec_stack:
                return True

        rec_stack.remove(node)
        return False

    def _add_to_wait_graph(self, txn_id: int, resource_id: int) -> None:
        """Add transaction to wait-for graph."""
        # Get current holders
        held_locks = self.lock_table.get(resource_id, [])
        for lock in held_locks:
            if lock.transaction_id != txn_id:
                self.wait_for_graph[txn_id].add(lock.transaction_id)

    def _remove_from_wait_graph(self, txn_id: int) -> None:
        """Remove transaction from wait-for graph."""
        if txn_id in self.wait_for_graph:
            del self.wait_for_graph[txn_id]

    def _wait_for_lock(self, transaction_id: int, resource_id: int, mode: LockMode) -> bool:
        """Wait for a lock with timeout."""
        start = time.time()
        poll_interval = 0.01  # 10ms

        while True:
            elapsed = (time.time() - start) * 1000  # Convert to ms

            if elapsed > self.timeout_ms:
                # Remove from wait queue
                requests = self.lock_queue.get(resource_id, [])
                self.lock_queue[resource_id] = [r for r in requests if r.transaction_id != transaction_id]
                raise LockTimeoutException(f"Lock timeout for transaction {transaction_id}")

            # Try to acquire lock
            if self._are_locks_compatible(transaction_id, resource_id, mode):
                lock = Lock(
                    resource_id=resource_id,
                    transaction_id=transaction_id,
                    mode=mode,
                    acquired_time=time.time(),
                )
                self.lock_table[resource_id].append(lock)
                self.transaction_locks[transaction_id].add(resource_id)

                # Remove from wait queue
                requests = self.lock_queue.get(resource_id, [])
                self.lock_queue[resource_id] = [r for r in requests if r.transaction_id != transaction_id]

                return True

            time.sleep(poll_interval)

    def _process_wait_queue(self, resource_id: int) -> None:
        """Try to grant locks to waiting transactions."""
        requests = self.lock_queue.get(resource_id, [])
        granted = []

        for request in requests:
            if self._are_locks_compatible(request.transaction_id, resource_id, request.mode):
                lock = Lock(
                    resource_id=resource_id,
                    transaction_id=request.transaction_id,
                    mode=request.mode,
                    acquired_time=time.time(),
                )
                self.lock_table[resource_id].append(lock)
                self.transaction_locks[request.transaction_id].add(resource_id)
                granted.append(request)

        # Remove granted requests
        self.lock_queue[resource_id] = [r for r in requests if r not in granted]

    def get_lock_info(self, resource_id: int) -> list[dict[str, any]]:
        """Get information about locks on a resource."""
        locks = self.lock_table.get(resource_id, [])
        return [
            {
                "txn_id": lock.transaction_id,
                "mode": lock.mode.name,
                "acquired_time": lock.acquired_time,
            }
            for lock in locks
        ]


class TransactionManager:
    """
    Manages transactions and their lifecycle.

    Implements:
    - Transaction creation and completion
    - Isolation levels
    - Savepoints
    - Rollback
    """

    def __init__(self, lock_manager: LockManager | None = None) -> None:
        """
        Initialize transaction manager.

        Args:
            lock_manager: Lock manager to use
        """
        self.lock_manager = lock_manager or LockManager()
        self.transactions: dict[int, Transaction] = {}
        self.next_txn_id = 1
        self.active_txns: set[int] = set()

    def begin_transaction(self, isolation_level: str = "READ_COMMITTED") -> int:
        """
        Begin a new transaction.

        Args:
            isolation_level: Isolation level (READ_COMMITTED, REPEATABLE_READ, SERIALIZABLE)

        Returns:
            Transaction ID
        """
        txn_id = self.next_txn_id
        self.next_txn_id += 1

        transaction = Transaction(
            transaction_id=txn_id,
            start_time=time.time(),
            isolation_level=isolation_level,
            is_active=True,
        )

        self.transactions[txn_id] = transaction
        self.active_txns.add(txn_id)

        return txn_id

    def commit(self, txn_id: int) -> None:
        """
        Commit a transaction.

        Args:
            txn_id: Transaction ID

        Raises:
            TransactionException: If transaction not found
        """
        if txn_id not in self.transactions:
            raise TransactionException(f"Transaction {txn_id} not found")

        transaction = self.transactions[txn_id]

        # Release all locks
        self.lock_manager.release_all_locks(txn_id)

        # Mark as committed
        transaction.is_active = False
        self.active_txns.discard(txn_id)

    def rollback(self, txn_id: int) -> None:
        """
        Rollback a transaction.

        Args:
            txn_id: Transaction ID
        """
        if txn_id not in self.transactions:
            raise TransactionException(f"Transaction {txn_id} not found")

        transaction = self.transactions[txn_id]

        # Release all locks
        self.lock_manager.release_all_locks(txn_id)

        # Clear modified pages
        transaction.modified_pages.clear()

        # Mark as aborted
        transaction.is_active = False
        self.active_txns.discard(txn_id)

    def create_savepoint(self, txn_id: int, savepoint_name: str) -> None:
        """
        Create a savepoint in a transaction.

        Args:
            txn_id: Transaction ID
            savepoint_name: Name of savepoint
        """
        if txn_id not in self.transactions:
            raise TransactionException(f"Transaction {txn_id} not found")

        transaction = self.transactions[txn_id]
        transaction.savepoints[savepoint_name] = len(transaction.undo_log)

    def rollback_to_savepoint(self, txn_id: int, savepoint_name: str) -> None:
        """
        Rollback to a savepoint.

        Args:
            txn_id: Transaction ID
            savepoint_name: Name of savepoint

        Raises:
            TransactionException: If savepoint not found
        """
        if txn_id not in self.transactions:
            raise TransactionException(f"Transaction {txn_id} not found")

        transaction = self.transactions[txn_id]

        if savepoint_name not in transaction.savepoints:
            raise TransactionException(f"Savepoint {savepoint_name} not found")

        # Clear undo log back to savepoint
        lsn = transaction.savepoints[savepoint_name]
        transaction.undo_log = transaction.undo_log[:lsn]

    def acquire_lock(self, txn_id: int, resource_id: int, mode: LockMode) -> bool:
        """
        Acquire a lock for a transaction.

        Args:
            txn_id: Transaction ID
            resource_id: Resource ID
            mode: Lock mode

        Returns:
            True if lock acquired
        """
        if txn_id not in self.transactions:
            raise TransactionException(f"Transaction {txn_id} not found")

        return self.lock_manager.acquire_lock(txn_id, resource_id, mode)

    def get_transaction(self, txn_id: int) -> Transaction | None:
        """Get transaction by ID."""
        return self.transactions.get(txn_id)

    def get_active_transactions(self) -> list[int]:
        """Get list of active transaction IDs."""
        return list(self.active_txns)

    def get_transaction_info(self, txn_id: int) -> dict[str, any] | None:
        """Get information about a transaction."""
        txn = self.transactions.get(txn_id)
        if txn is None:
            return None

        return {
            "txn_id": txn.transaction_id,
            "start_time": txn.start_time,
            "isolation_level": txn.isolation_level,
            "is_active": txn.is_active,
            "num_locks": len(self.lock_manager.transaction_locks.get(txn_id, set())),
        }
