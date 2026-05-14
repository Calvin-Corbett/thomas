"""
Tests for blockchain cryptography module.

Tests ECDSA key generation, signing, verification, and address derivation.
"""

from thomas.marketplace.blockchain.crypto import (
    KeyPair,
    derive_address,
    generate_deterministic_keypair,
    generate_keypair,
    sign_message,
    verify_address,
    verify_signature,
)


class TestKeyPairGeneration:
    """Test key pair generation."""

    def test_generate_keypair(self) -> None:
        """Test generating random keypair."""
        keypair = generate_keypair()

        assert isinstance(keypair, KeyPair)
        assert keypair.private_key > 0
        assert keypair.public_key_x > 0
        assert keypair.public_key_y > 0

    def test_deterministic_keypair_generation(self) -> None:
        """Test deterministic keypair generation."""
        password = "test_password"
        keypair1 = generate_deterministic_keypair(password)
        keypair2 = generate_deterministic_keypair(password)

        # Same password should generate same keys
        assert keypair1.private_key == keypair2.private_key
        assert keypair1.public_key_x == keypair2.public_key_x
        assert keypair1.public_key_y == keypair2.public_key_y

    def test_different_passwords_generate_different_keys(self) -> None:
        """Test different passwords generate different keys."""
        keypair1 = generate_deterministic_keypair("password1")
        keypair2 = generate_deterministic_keypair("password2")

        assert keypair1.private_key != keypair2.private_key

    def test_keypair_with_seed(self) -> None:
        """Test generating keypair with seed."""
        seed = b"test_seed_12345678901234567890"
        keypair = generate_keypair(seed)

        assert keypair.private_key > 0
        assert keypair.public_key_x > 0


class TestSigning:
    """Test message signing."""

    def test_sign_message(self) -> None:
        """Test signing a message."""
        keypair = generate_keypair()
        message = b"Hello, blockchain!"

        signature = sign_message(message, keypair.private_key)

        assert isinstance(signature, str)
        assert len(signature) == 128  # 2 * 64 hex chars for r||s
        # Signature should be hex
        int(signature, 16)

    def test_signature_changes_with_different_messages(self) -> None:
        """Test that different messages produce different signatures."""
        keypair = generate_keypair()
        message1 = b"Message 1"
        message2 = b"Message 2"

        sig1 = sign_message(message1, keypair.private_key)
        sig2 = sign_message(message2, keypair.private_key)

        assert sig1 != sig2

    def test_signature_is_deterministic(self) -> None:
        """Test that signing is deterministic (RFC 6979)."""
        keypair = generate_keypair()
        message = b"Deterministic test"

        sig1 = sign_message(message, keypair.private_key)
        sig2 = sign_message(message, keypair.private_key)

        # RFC 6979 ensures signatures are deterministic
        assert sig1 == sig2


class TestVerification:
    """Test signature verification."""

    def test_verify_valid_signature(self) -> None:
        """Test verifying valid signature."""
        keypair = generate_keypair()
        message = b"Test message"

        signature = sign_message(message, keypair.private_key)
        is_valid = verify_signature(message, signature, keypair.public_key_x, keypair.public_key_y)

        assert is_valid

    def test_reject_invalid_signature(self) -> None:
        """Test rejecting invalid signature."""
        keypair = generate_keypair()
        message = b"Original message"

        signature = sign_message(message, keypair.private_key)

        # Tamper with signature
        tampered = "00" + signature[2:]

        is_valid = verify_signature(message, tampered, keypair.public_key_x, keypair.public_key_y)

        assert not is_valid

    def test_reject_wrong_message(self) -> None:
        """Test rejecting signature for wrong message."""
        keypair = generate_keypair()
        message = b"Original"
        wrong_message = b"Different"

        signature = sign_message(message, keypair.private_key)
        is_valid = verify_signature(wrong_message, signature, keypair.public_key_x, keypair.public_key_y)

        assert not is_valid

    def test_reject_signature_from_different_key(self) -> None:
        """Test rejecting signature from different private key."""
        keypair1 = generate_keypair()
        keypair2 = generate_keypair()
        message = b"Test message"

        signature = sign_message(message, keypair1.private_key)

        # Verify with different public key
        is_valid = verify_signature(message, signature, keypair2.public_key_x, keypair2.public_key_y)

        assert not is_valid

    def test_verify_rejects_invalid_signature_format(self) -> None:
        """Test that verify rejects malformed signatures."""
        keypair = generate_keypair()
        message = b"Test"

        # Too short
        assert not verify_signature(message, "0000", keypair.public_key_x, keypair.public_key_y)

        # Invalid hex
        assert not verify_signature(message, "ZZZZ" * 32, keypair.public_key_x, keypair.public_key_y)


class TestAddressDerivation:
    """Test blockchain address derivation."""

    def test_derive_address(self) -> None:
        """Test deriving address from public key."""
        keypair = generate_keypair()
        address = derive_address(keypair.public_key_x, keypair.public_key_y)

        assert isinstance(address, str)
        assert len(address) == 50  # 25 bytes * 2 hex chars
        # Check it's valid hex
        bytes.fromhex(address)

    def test_address_is_deterministic(self) -> None:
        """Test that address derivation is deterministic."""
        keypair = generate_keypair()
        address1 = derive_address(keypair.public_key_x, keypair.public_key_y)
        address2 = derive_address(keypair.public_key_x, keypair.public_key_y)

        assert address1 == address2

    def test_different_keys_produce_different_addresses(self) -> None:
        """Test that different keys produce different addresses."""
        keypair1 = generate_keypair()
        keypair2 = generate_keypair()

        address1 = derive_address(keypair1.public_key_x, keypair1.public_key_y)
        address2 = derive_address(keypair2.public_key_x, keypair2.public_key_y)

        assert address1 != address2

    def test_address_checksum_validation(self) -> None:
        """Test address checksum validation."""
        keypair = generate_keypair()
        address = derive_address(keypair.public_key_x, keypair.public_key_y)

        # Valid address should verify
        assert verify_address(address)

    def test_reject_tampered_address(self) -> None:
        """Test rejecting tampered address."""
        keypair = generate_keypair()
        address = derive_address(keypair.public_key_x, keypair.public_key_y)

        # Tamper with address
        tampered = "00" + address[2:-4] + "1234"

        assert not verify_address(tampered)


class TestPublicKeyFormat:
    """Test public key formatting."""

    def test_public_key_hex_format(self) -> None:
        """Test public key hex encoding."""
        keypair = generate_keypair()
        pubkey_hex = keypair.public_key_hex()

        # Compressed format: 1 byte prefix (02/03) + 32 bytes x coordinate
        assert len(pubkey_hex) == 66
        assert pubkey_hex[0] in ["0"]  # First char of 02 or 03

    def test_public_key_prefix_even_odd(self) -> None:
        """Test public key prefix reflects Y coordinate parity."""
        # Generate many keypairs to find even and odd Y coords
        for _ in range(20):
            keypair = generate_keypair()
            pubkey_hex = keypair.public_key_hex()

            prefix = int(pubkey_hex[:2], 16)
            y_even = keypair.public_key_y % 2 == 0

            if y_even:
                assert prefix == 0x02
            else:
                assert prefix == 0x03

    def test_private_key_hex_format(self) -> None:
        """Test private key hex encoding."""
        keypair = generate_keypair()
        privkey_hex = keypair.private_key_hex()

        # 32 bytes = 64 hex chars
        assert len(privkey_hex) == 64
        # Should be valid hex
        int(privkey_hex, 16)


class TestIntegration:
    """Integration tests combining multiple operations."""

    def test_full_signing_workflow(self) -> None:
        """Test complete signing workflow."""
        # Generate keypair
        keypair = generate_keypair()

        # Derive address
        address = derive_address(keypair.public_key_x, keypair.public_key_y)
        assert verify_address(address)

        # Sign message
        message = b"Transaction: send 100 tokens"
        signature = sign_message(message, keypair.private_key)

        # Verify signature
        assert verify_signature(message, signature, keypair.public_key_x, keypair.public_key_y)

    def test_deterministic_workflow(self) -> None:
        """Test deterministic key generation and signing."""
        password = "my_secure_password"

        # Generate keypair deterministically
        keypair = generate_deterministic_keypair(password)
        derive_address(keypair.public_key_x, keypair.public_key_y)

        # Sign message
        message = b"Deterministic message"
        signature = sign_message(message, keypair.private_key)

        # Verify signature
        assert verify_signature(message, signature, keypair.public_key_x, keypair.public_key_y)

        # Same password should produce same signature
        keypair2 = generate_deterministic_keypair(password)
        assert keypair.private_key == keypair2.private_key
