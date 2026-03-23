"""
Wallet implementation - key management and transaction creation.

Manages keys, addresses, balances, and transaction signing.
"""

import hashlib
from dataclasses import dataclass, field

from thomas.marketplace.blockchain.crypto import (
    KeyPair,
    derive_address,
    generate_keypair,
)
from thomas.marketplace.blockchain.transaction import (
    Transaction,
    create_transaction,
)


@dataclass
class Address:
    """Wallet address with associated information."""

    address: str
    public_key: str
    private_key_encrypted: str = ""  # Encrypted private key
    balance: int = 0
    nonce: int = 0
    label: str = ""  # User-friendly name
    transactions: list[str] = field(default_factory=list)


class Wallet:
    """
    Cryptocurrency wallet.

    Manages multiple addresses, signing, balance tracking, and transaction creation.
    """

    def __init__(self, name: str = "MyWallet", password: str = "") -> None:
        """
        Initialize wallet.

        Args:
            name: Wallet name.
            password: Optional password for encryption.
        """
        self.name = name
        self.password = password
        self.addresses: dict[str, Address] = {}
        self.address_book: dict[str, str] = {}  # address -> label
        self.transaction_history: list[dict] = []

    def create_address(self, label: str = "", seed: bytes = None) -> str:
        """
        Create new address in wallet.

        Args:
            label: Optional label for address.
            seed: Optional seed for deterministic generation.

        Returns:
            New address string.
        """
        # Generate key pair
        if seed:
            keypair = generate_keypair(seed)
        else:
            keypair = generate_keypair()

        # Derive address
        address = derive_address(keypair.public_key_x, keypair.public_key_y)

        # Store address
        public_key = keypair.public_key_hex()
        encrypted_private = self._encrypt_private_key(keypair.private_key_hex(), self.password)

        self.addresses[address] = Address(
            address=address,
            public_key=public_key,
            private_key_encrypted=encrypted_private,
            label=label or f"Address {len(self.addresses) + 1}",
        )

        if label:
            self.address_book[address] = label

        return address

    def import_keypair(self, keypair: KeyPair, label: str = "") -> str:
        """
        Import existing keypair into wallet.

        Args:
            keypair: KeyPair to import.
            label: Optional label.

        Returns:
            Imported address string.
        """
        address = derive_address(keypair.public_key_x, keypair.public_key_y)
        public_key = keypair.public_key_hex()
        encrypted_private = self._encrypt_private_key(keypair.private_key_hex(), self.password)

        self.addresses[address] = Address(
            address=address,
            public_key=public_key,
            private_key_encrypted=encrypted_private,
            label=label or "Imported Address",
        )

        return address

    def get_addresses(self) -> list[str]:
        """
        Get all addresses in wallet.

        Returns:
            List of address strings.
        """
        return list(self.addresses.keys())

    def get_address_info(self, address: str) -> Address | None:
        """
        Get information about an address.

        Args:
            address: Address to query.

        Returns:
            Address info or None if not found.
        """
        return self.addresses.get(address)

    def get_balance(self, address: str = None) -> int:
        """
        Get balance for address or all addresses.

        Args:
            address: Specific address (default all).

        Returns:
            Balance in satoshis.
        """
        if address:
            addr = self.addresses.get(address)
            return addr.balance if addr else 0
        else:
            return sum(addr.balance for addr in self.addresses.values())

    def get_total_balance(self) -> int:
        """
        Get total balance across all addresses.

        Returns:
            Total balance in satoshis.
        """
        return sum(addr.balance for addr in self.addresses.values())

    def update_balance(self, address: str, balance: int) -> bool:
        """
        Update balance for address (from blockchain sync).

        Args:
            address: Address to update.
            balance: New balance in satoshis.

        Returns:
            True if updated, False if address not found.
        """
        if address not in self.addresses:
            return False

        self.addresses[address].balance = balance
        return True

    def get_nonce(self, address: str) -> int:
        """
        Get transaction nonce for address.

        Args:
            address: Address to query.

        Returns:
            Current nonce (transaction count).
        """
        addr = self.addresses.get(address)
        return addr.nonce if addr else 0

    def update_nonce(self, address: str, nonce: int) -> bool:
        """
        Update nonce for address.

        Args:
            address: Address to update.
            nonce: New nonce value.

        Returns:
            True if updated.
        """
        if address not in self.addresses:
            return False

        self.addresses[address].nonce = nonce
        return True

    def create_transaction(
        self,
        sender: str,
        recipient: str,
        amount: int,
        fee: int,
    ) -> Transaction | None:
        """
        Create and sign a transaction.

        Args:
            sender: Sender address (must be in wallet).
            recipient: Recipient address.
            amount: Amount to send (in satoshis).
            fee: Transaction fee (in satoshis).

        Returns:
            Signed Transaction or None if sender not in wallet.

        Raises:
            ValueError: If sender not found or insufficient balance.
        """
        if sender not in self.addresses:
            raise ValueError(f"Address {sender} not in wallet")

        addr_info = self.addresses[sender]

        # Check balance
        if addr_info.balance < amount + fee:
            raise ValueError(f"Insufficient balance: {addr_info.balance} < {amount + fee}")

        # Get private key
        private_key = self._decrypt_private_key(addr_info.private_key_encrypted, self.password)
        private_key_int = int(private_key, 16)

        # Create transaction
        tx = create_transaction(
            sender=sender,
            recipient=recipient,
            amount=amount,
            fee=fee,
            nonce=addr_info.nonce,
            private_key=private_key_int,
        )

        return tx

    def add_to_transaction_history(self, transaction: Transaction) -> None:
        """
        Add transaction to wallet history.

        Args:
            transaction: Transaction to record.
        """
        record = {
            "hash": transaction.hash,
            "sender": transaction.sender,
            "recipient": transaction.recipient,
            "amount": transaction.amount,
            "fee": transaction.fee,
            "timestamp": None,
        }

        self.transaction_history.append(record)

        # Track transaction for relevant addresses
        if transaction.sender in self.addresses:
            self.addresses[transaction.sender].transactions.append(transaction.hash)
        if transaction.recipient in self.addresses:
            self.addresses[transaction.recipient].transactions.append(transaction.hash)

    def get_transaction_history(self, address: str = None) -> list[dict]:
        """
        Get transaction history.

        Args:
            address: Filter by address (optional).

        Returns:
            List of transaction records.
        """
        if address:
            return [tx for tx in self.transaction_history if tx["sender"] == address or tx["recipient"] == address]
        return self.transaction_history

    def add_contact(self, address: str, label: str) -> bool:
        """
        Add address to contact book.

        Args:
            address: Address to add.
            label: Contact label.

        Returns:
            True if added.
        """
        self.address_book[address] = label
        return True

    def get_contact(self, label: str) -> str | None:
        """
        Get address for contact label.

        Args:
            label: Contact label.

        Returns:
            Address or None if not found.
        """
        for addr, lbl in self.address_book.items():
            if lbl == label:
                return addr
        return None

    def _encrypt_private_key(self, private_key_hex: str, password: str) -> str:
        """
        Encrypt private key with password.

        Uses simple XOR with key derivation (NOT production-grade).

        Args:
            private_key_hex: Private key as hex string.
            password: Encryption password.

        Returns:
            Encrypted key as hex string.
        """
        if not password:
            return private_key_hex

        # Derive encryption key from password
        key = hashlib.pbkdf2_hmac("sha256", password.encode(), b"wallet_encryption", 10000)

        # XOR encrypt
        key_bytes = bytes.fromhex(private_key_hex)
        encrypted = bytes(a ^ b for a, b in zip(key_bytes, key * (len(key_bytes) // len(key) + 1)))

        return encrypted.hex()

    def _decrypt_private_key(self, encrypted_hex: str, password: str) -> str:
        """
        Decrypt private key with password.

        Args:
            encrypted_hex: Encrypted key as hex string.
            password: Decryption password.

        Returns:
            Decrypted private key as hex string.
        """
        if not password:
            return encrypted_hex

        # Derive decryption key
        key = hashlib.pbkdf2_hmac("sha256", password.encode(), b"wallet_encryption", 10000)

        # XOR decrypt
        encrypted_bytes = bytes.fromhex(encrypted_hex)
        decrypted = bytes(a ^ b for a, b in zip(encrypted_bytes, key * (len(encrypted_bytes) // len(key) + 1)))

        return decrypted.hex()

    def export(self) -> dict:
        """
        Export wallet to dictionary.

        Returns:
            Serialized wallet data.
        """
        return {
            "name": self.name,
            "addresses": [
                {
                    "address": addr.address,
                    "public_key": addr.public_key,
                    "label": addr.label,
                    "balance": addr.balance,
                    "nonce": addr.nonce,
                }
                for addr in self.addresses.values()
            ],
            "address_book": self.address_book,
            "transaction_count": len(self.transaction_history),
        }

    def get_statistics(self) -> dict:
        """
        Get wallet statistics.

        Returns:
            Dictionary with wallet stats.
        """
        return {
            "name": self.name,
            "address_count": len(self.addresses),
            "total_balance": self.get_total_balance(),
            "transaction_count": len(self.transaction_history),
            "contacts": len(self.address_book),
        }
