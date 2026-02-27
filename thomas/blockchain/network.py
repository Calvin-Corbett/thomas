"""
P2P network simulation - peer-to-peer communication.

Simulates network operations: block/transaction propagation, synchronization.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

from thomas.blockchain._types import Block, Transaction


class MessageType(Enum):
    """Network message types."""

    BLOCK = "block"
    TRANSACTION = "tx"
    GET_BLOCKS = "getblocks"
    GET_TRANSACTIONS = "gettxs"
    INVENTORY = "inv"
    PING = "ping"
    PONG = "pong"


@dataclass
class NetworkMessage:
    """P2P network message."""

    message_type: MessageType
    payload: dict
    sender: str = ""
    timestamp: int = field(default_factory=lambda: int(time.time()))

    def to_dict(self) -> dict:
        """Serialize message."""
        return {
            "type": self.message_type.value,
            "payload": self.payload,
            "sender": self.sender,
            "timestamp": self.timestamp,
        }


@dataclass
class PeerInfo:
    """Information about a connected peer."""

    peer_id: str
    host: str
    port: int
    version: str = "1.0.0"
    last_seen: int = field(default_factory=lambda: int(time.time()))
    score: int = 100  # Reliability score (0-100)
    blocks_synced: int = 0
    transactions_relayed: int = 0


class Network:
    """
    P2P network simulation.

    Simulates peer discovery, message propagation, and synchronization.
    """

    def __init__(self, node_id: str, network_name: str = "testnet") -> None:
        """
        Initialize network node.

        Args:
            node_id: Unique identifier for this node.
            network_name: Network name for peer discovery.
        """
        self.node_id = node_id
        self.network_name = network_name
        self.peers: dict[str, PeerInfo] = {}
        self.pending_messages: list[NetworkMessage] = []
        self.message_handlers: dict[MessageType, Callable] = {}
        self.partitioned = False  # Network partition flag
        self.known_blocks: set[str] = set()
        self.known_transactions: set[str] = set()

    def add_peer(self, peer_id: str, host: str, port: int) -> bool:
        """
        Add peer to network.

        Args:
            peer_id: Unique peer identifier.
            host: Peer host/IP address.
            port: Peer port number.

        Returns:
            True if peer added, False if already connected.
        """
        if peer_id in self.peers:
            return False

        peer = PeerInfo(peer_id=peer_id, host=host, port=port)
        self.peers[peer_id] = peer
        return True

    def remove_peer(self, peer_id: str) -> bool:
        """
        Remove peer from network.

        Args:
            peer_id: Peer to remove.

        Returns:
            True if removed, False if not found.
        """
        if peer_id not in self.peers:
            return False

        del self.peers[peer_id]
        return True

    def get_peers(self) -> list[PeerInfo]:
        """
        Get list of connected peers.

        Returns:
            List of PeerInfo objects.
        """
        return list(self.peers.values())

    def get_best_peers(self, count: int = 8) -> list[PeerInfo]:
        """
        Get best peers by reliability score.

        Args:
            count: Number of peers to return.

        Returns:
            List of top peers.
        """
        sorted_peers = sorted(self.peers.values(), key=lambda p: p.score, reverse=True)
        return sorted_peers[:count]

    def broadcast_block(self, block: Block, exclude_peer: str = None) -> int:
        """
        Broadcast block to all peers.

        Args:
            block: Block to broadcast.
            exclude_peer: Peer ID to exclude (usually sender).

        Returns:
            Number of peers block was sent to.
        """
        if self.partitioned:
            return 0

        message = NetworkMessage(
            message_type=MessageType.BLOCK,
            payload={"block": block.to_dict()},
            sender=self.node_id,
        )

        count = 0
        for peer_id, peer in self.peers.items():
            if exclude_peer and peer_id == exclude_peer:
                continue

            self.pending_messages.append(message)
            peer.last_seen = int(time.time())
            peer.blocks_synced += 1
            count += 1

        self.known_blocks.add(block.hash)
        return count

    def broadcast_transaction(self, transaction: Transaction, exclude_peer: str = None) -> int:
        """
        Broadcast transaction to all peers.

        Args:
            transaction: Transaction to broadcast.
            exclude_peer: Peer ID to exclude (usually sender).

        Returns:
            Number of peers transaction was sent to.
        """
        if self.partitioned:
            return 0

        message = NetworkMessage(
            message_type=MessageType.TRANSACTION,
            payload={"transaction": transaction.to_dict()},
            sender=self.node_id,
        )

        count = 0
        for peer_id, peer in self.peers.items():
            if exclude_peer and peer_id == exclude_peer:
                continue

            self.pending_messages.append(message)
            peer.last_seen = int(time.time())
            peer.transactions_relayed += 1
            count += 1

        self.known_transactions.add(transaction.hash)
        return count

    def request_blocks(self, start_index: int, end_index: int, peer_id: str = None) -> bool:
        """
        Request blocks from a peer.

        Args:
            start_index: First block index to request.
            end_index: Last block index to request.
            peer_id: Peer to request from (default best peer).

        Returns:
            True if request sent, False if no peers available.
        """
        if peer_id is None:
            best = self.get_best_peers(1)
            if not best:
                return False
            peer_id = best[0].peer_id

        if peer_id not in self.peers:
            return False

        message = NetworkMessage(
            message_type=MessageType.GET_BLOCKS,
            payload={"start": start_index, "end": end_index},
            sender=self.node_id,
        )

        self.pending_messages.append(message)
        return True

    def send_inventory(self, block_hashes: list[str], peer_id: str) -> bool:
        """
        Send inventory (list of block hashes) to peer.

        Args:
            block_hashes: List of block hashes this node has.
            peer_id: Peer to send to.

        Returns:
            True if inventory sent.
        """
        if peer_id not in self.peers:
            return False

        message = NetworkMessage(
            message_type=MessageType.INVENTORY,
            payload={"blocks": block_hashes},
            sender=self.node_id,
        )

        self.pending_messages.append(message)
        return True

    def ping(self, peer_id: str) -> bool:
        """
        Send ping to peer.

        Args:
            peer_id: Peer to ping.

        Returns:
            True if ping sent.
        """
        if peer_id not in self.peers:
            return False

        message = NetworkMessage(
            message_type=MessageType.PING,
            payload={"nonce": int(time.time())},
            sender=self.node_id,
        )

        self.pending_messages.append(message)
        return True

    def get_pending_messages(self) -> list[NetworkMessage]:
        """
        Get pending messages for processing.

        Returns:
            List of NetworkMessage objects.
        """
        messages = self.pending_messages.copy()
        self.pending_messages.clear()
        return messages

    def register_message_handler(self, message_type: MessageType, handler: Callable) -> None:
        """
        Register handler for message type.

        Args:
            message_type: Type of message to handle.
            handler: Callable that processes the message.
        """
        self.message_handlers[message_type] = handler

    def handle_message(self, message: NetworkMessage) -> None:
        """
        Process incoming message.

        Args:
            message: Message to handle.
        """
        handler = self.message_handlers.get(message.message_type)
        if handler:
            handler(message)

    def update_peer_score(self, peer_id: str, delta: int) -> bool:
        """
        Update peer reliability score.

        Args:
            peer_id: Peer to update.
            delta: Change in score (positive or negative).

        Returns:
            True if peer found and updated.
        """
        if peer_id not in self.peers:
            return False

        peer = self.peers[peer_id]
        peer.score = max(0, min(100, peer.score + delta))

        # Remove unreliable peers
        if peer.score == 0:
            self.remove_peer(peer_id)

        return True

    def create_network_partition(self) -> None:
        """Create network partition (node becomes isolated)."""
        self.partitioned = True

    def heal_network_partition(self) -> None:
        """Heal network partition (reconnect to network)."""
        self.partitioned = False

    def is_partitioned(self) -> bool:
        """Check if node is partitioned from network."""
        return self.partitioned

    def get_statistics(self) -> dict:
        """
        Get network statistics.

        Returns:
            Dictionary with network stats.
        """
        return {
            "node_id": self.node_id,
            "peer_count": len(self.peers),
            "partitioned": self.partitioned,
            "known_blocks": len(self.known_blocks),
            "known_transactions": len(self.known_transactions),
            "avg_peer_score": (sum(p.score for p in self.peers.values()) // len(self.peers) if self.peers else 0),
        }
