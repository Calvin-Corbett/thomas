"""
Transaction management and validation.

Handles transaction creation, signing, verification, and serialization.
Supports both account model and UTXO model.
"""

import hashlib
from typing import Any

from thomas.marketplace.blockchain._exceptions import InvalidTransactionError
from thomas.marketplace.blockchain._types import Transaction
from thomas.marketplace.blockchain.crypto import sign_message, verify_signature


def _transaction_data_for_signing(
    sender: str,
    recipient: str,
    amount: int,
    fee: int,
    nonce: int,
) -> bytes:
    """
    Prepare transaction data for signing.

    Args:
        sender: Sender address.
        recipient: Recipient address.
        amount: Amount to transfer.
        fee: Transaction fee.
        nonce: Sender's transaction nonce.

    Returns:
        Serialized transaction data.
    """
    # Order matters: must be consistent for signature verification
    data = (
        sender.encode()
        + recipient.encode()
        + amount.to_bytes(32, byteorder="big")
        + fee.to_bytes(32, byteorder="big")
        + nonce.to_bytes(8, byteorder="big")
    )
    return data


def transaction_hash(
    sender: str,
    recipient: str,
    amount: int,
    fee: int,
    nonce: int,
    signature: str,
) -> str:
    """
    Compute transaction hash.

    Uses SHA-256 of all transaction fields including signature.

    Args:
        sender: Sender address.
        recipient: Recipient address.
        amount: Amount transferred.
        fee: Transaction fee.
        nonce: Sender's transaction nonce.
        signature: Digital signature.

    Returns:
        Transaction hash as hex string (64 characters).
    """
    data = _transaction_data_for_signing(sender, recipient, amount, fee, nonce) + signature.encode()
    return hashlib.sha256(data).hexdigest()


def create_transaction(
    sender: str,
    recipient: str,
    amount: int,
    fee: int,
    nonce: int,
    private_key: int,
) -> Transaction:
    """
    Create and sign a new transaction.

    Args:
        sender: Sender's address.
        recipient: Recipient's address.
        amount: Amount to transfer (in satoshis).
        fee: Transaction fee (in satoshis).
        nonce: Sender's transaction nonce (sequence number).
        private_key: Sender's private key for signing.

    Returns:
        Signed Transaction object.

    Raises:
        InvalidTransactionError: If transaction creation fails.
    """
    if amount < 0:
        raise InvalidTransactionError("Amount cannot be negative")
    if fee < 0:
        raise InvalidTransactionError("Fee cannot be negative")
    if not sender or not recipient:
        raise InvalidTransactionError("Sender and recipient required")
    if sender == recipient:
        raise InvalidTransactionError("Sender cannot be recipient")

    # Sign transaction
    data = _transaction_data_for_signing(sender, recipient, amount, fee, nonce)
    signature = sign_message(data, private_key)

    # Compute transaction hash
    tx_hash = transaction_hash(sender, recipient, amount, fee, nonce, signature)

    return Transaction(
        sender=sender,
        recipient=recipient,
        amount=amount,
        fee=fee,
        nonce=nonce,
        signature=signature,
        hash=tx_hash,
    )


def create_coinbase_transaction(
    recipient: str,
    block_reward: int,
    block_index: int,
    miner_address: str,
) -> Transaction:
    """
    Create a coinbase transaction (mining reward).

    Coinbase transactions have special properties:
    - No sender (sender is mining system)
    - No input transactions
    - No fee
    - Special signature

    Args:
        recipient: Address receiving the block reward.
        block_reward: Amount of reward (in satoshis).
        block_index: Block number this reward is for.
        miner_address: Address of the miner (usually same as recipient).

    Returns:
        Coinbase Transaction.
    """
    sender = "COINBASE"
    nonce = block_index  # Use block index as nonce for coinbase

    # Coinbase signature includes block info
    data = (
        sender.encode()
        + recipient.encode()
        + block_reward.to_bytes(32, byteorder="big")
        + block_index.to_bytes(32, byteorder="big")
        + miner_address.encode()
    )
    signature = hashlib.sha256(data).hexdigest()

    tx_hash = transaction_hash(sender, recipient, block_reward, 0, nonce, signature)

    return Transaction(
        sender=sender,
        recipient=recipient,
        amount=block_reward,
        fee=0,
        nonce=nonce,
        signature=signature,
        hash=tx_hash,
    )


def verify_transaction(
    transaction: Transaction,
    public_key_x: int,
    public_key_y: int,
) -> bool:
    """
    Verify a transaction signature.

    Args:
        transaction: Transaction to verify.
        public_key_x: Sender's public key X coordinate.
        public_key_y: Sender's public key Y coordinate.

    Returns:
        True if signature is valid.
    """
    if transaction.sender == "COINBASE":
        # Coinbase transactions are always valid
        return True

    data = _transaction_data_for_signing(
        transaction.sender,
        transaction.recipient,
        transaction.amount,
        transaction.fee,
        transaction.nonce,
    )

    return verify_signature(data, transaction.signature, public_key_x, public_key_y)


def verify_transaction_hash(transaction: Transaction) -> bool:
    """
    Verify transaction hash is correct.

    Args:
        transaction: Transaction to verify.

    Returns:
        True if hash is valid.
    """
    expected_hash = transaction_hash(
        transaction.sender,
        transaction.recipient,
        transaction.amount,
        transaction.fee,
        transaction.nonce,
        transaction.signature,
    )
    return transaction.hash == expected_hash


class UTXOInput:
    """Represents an input to a transaction (UTXO model)."""

    def __init__(self, txid: str, output_index: int, amount: int) -> None:
        """
        Create a UTXO input.

        Args:
            txid: Transaction hash this input references.
            output_index: Output index in that transaction.
            amount: Amount from that output.
        """
        self.txid = txid
        self.output_index = output_index
        self.amount = amount

    def to_dict(self) -> dict[str, Any]:
        """Serialize input."""
        return {
            "txid": self.txid,
            "output_index": self.output_index,
            "amount": self.amount,
        }


class UTXOOutput:
    """Represents an output of a transaction (UTXO model)."""

    def __init__(self, recipient: str, amount: int) -> None:
        """
        Create a UTXO output.

        Args:
            recipient: Recipient address.
            amount: Amount for recipient.
        """
        self.recipient = recipient
        self.amount = amount
        self.spent = False

    def to_dict(self) -> dict[str, Any]:
        """Serialize output."""
        return {
            "recipient": self.recipient,
            "amount": self.amount,
            "spent": self.spent,
        }


class UTXOTransaction:
    """
    Transaction using UTXO (Unspent Transaction Output) model.

    Used by Bitcoin-like blockchains.
    """

    def __init__(
        self,
        inputs: list[UTXOInput],
        outputs: list[UTXOOutput],
        fee: int = 0,
        nonce: int = 0,
    ) -> None:
        """
        Create UTXO transaction.

        Args:
            inputs: List of inputs (UTXOs being spent).
            outputs: List of outputs (new UTXOs created).
            fee: Transaction fee.
            nonce: Sequence number.
        """
        self.inputs = inputs
        self.outputs = outputs
        self.fee = fee
        self.nonce = nonce
        self.signature = ""
        self.hash = ""

    @property
    def total_input(self) -> int:
        """Get total input amount."""
        return sum(inp.amount for inp in self.inputs)

    @property
    def total_output(self) -> int:
        """Get total output amount."""
        return sum(out.amount for out in self.outputs)

    def sign(self, private_key: int) -> str:
        """
        Sign UTXO transaction.

        Args:
            private_key: Sender's private key.

        Returns:
            Signature hex string.
        """
        data = b""
        for inp in self.inputs:
            data += inp.txid.encode() + inp.output_index.to_bytes(4, "big")
        for out in self.outputs:
            data += out.recipient.encode() + out.amount.to_bytes(32, "big")
        data += self.fee.to_bytes(32, "big")

        self.signature = sign_message(data, private_key)
        self.hash = hashlib.sha256(data + self.signature.encode()).hexdigest()
        return self.signature

    def to_dict(self) -> dict[str, Any]:
        """Serialize UTXO transaction."""
        return {
            "inputs": [inp.to_dict() for inp in self.inputs],
            "outputs": [out.to_dict() for out in self.outputs],
            "fee": self.fee,
            "nonce": self.nonce,
            "signature": self.signature,
            "hash": self.hash,
        }
