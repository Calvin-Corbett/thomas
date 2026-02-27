"""
Cryptographic primitives for blockchain operations.

Implements ECDSA signing/verification on secp256k1, SHA-256 hashing,
and address generation with checksums.
"""

import hashlib
import hmac
import os
from dataclasses import dataclass

# secp256k1 curve parameters
_CURVE_P = 2**256 - 2**32 - 977
_CURVE_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
_CURVE_G_X = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
_CURVE_G_Y = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8
_CURVE_A = 0
_CURVE_B = 7


class CurvePoint:
    """Represents a point on the secp256k1 elliptic curve."""

    def __init__(self, x: int, y: int) -> None:
        """
        Initialize a point on the curve.

        Args:
            x: X coordinate (0 for point at infinity).
            y: Y coordinate (0 for point at infinity).
        """
        self.x = x % _CURVE_P if x else 0
        self.y = y % _CURVE_P if y else 0
        self._verify_on_curve()

    def _verify_on_curve(self) -> None:
        """Verify point is on the secp256k1 curve."""
        if self.x == 0 and self.y == 0:
            return  # Point at infinity
        y_squared = (self.y * self.y) % _CURVE_P
        x_cubed = (self.x * self.x * self.x) % _CURVE_P
        right = (x_cubed + _CURVE_B) % _CURVE_P
        if y_squared != right:
            raise ValueError("Point not on curve")

    def is_infinity(self) -> bool:
        """Check if this is the point at infinity."""
        return self.x == 0 and self.y == 0

    def __add__(self, other: "CurvePoint") -> "CurvePoint":
        """Add two points using elliptic curve addition."""
        if self.is_infinity():
            return CurvePoint(other.x, other.y)
        if other.is_infinity():
            return CurvePoint(self.x, self.y)

        if self.x == other.x:
            if self.y == other.y:
                return self._double()
            else:
                return CurvePoint(0, 0)  # Point at infinity

        # Compute slope
        dy = (other.y - self.y) % _CURVE_P
        dx = (other.x - self.x) % _CURVE_P
        dx_inv = pow(dx, _CURVE_P - 2, _CURVE_P)
        slope = (dy * dx_inv) % _CURVE_P

        # Compute new point
        x3 = (slope * slope - self.x - other.x) % _CURVE_P
        y3 = (slope * (self.x - x3) - self.y) % _CURVE_P

        return CurvePoint(x3, y3)

    def _double(self) -> "CurvePoint":
        """Double a point using elliptic curve doubling."""
        if self.is_infinity():
            return CurvePoint(0, 0)

        # Compute slope: slope = (3*x^2 + a) / (2*y)
        numerator = (3 * self.x * self.x + _CURVE_A) % _CURVE_P
        denominator = (2 * self.y) % _CURVE_P
        denom_inv = pow(denominator, _CURVE_P - 2, _CURVE_P)
        slope = (numerator * denom_inv) % _CURVE_P

        # Compute new point
        x3 = (slope * slope - 2 * self.x) % _CURVE_P
        y3 = (slope * (self.x - x3) - self.y) % _CURVE_P

        return CurvePoint(x3, y3)

    def scalar_mult(self, scalar: int) -> "CurvePoint":
        """
        Scalar multiplication using binary method.

        Args:
            scalar: Integer to multiply by.

        Returns:
            New CurvePoint representing scalar * self.
        """
        if scalar == 0:
            return CurvePoint(0, 0)
        if scalar < 0:
            scalar = scalar % _CURVE_N

        result = CurvePoint(0, 0)
        addend = self

        while scalar:
            if scalar & 1:
                result = result + addend
            addend = addend._double()
            scalar >>= 1

        return result


def _sha256(data: bytes) -> bytes:
    """
    Compute SHA-256 hash.

    Args:
        data: Data to hash.

    Returns:
        32-byte hash digest.
    """
    return hashlib.sha256(data).digest()


def _sha256_hex(data: bytes) -> str:
    """
    Compute SHA-256 hash and return as hex string.

    Args:
        data: Data to hash.

    Returns:
        64-character hex string.
    """
    return hashlib.sha256(data).hexdigest()


def _ripemd160(data: bytes) -> bytes:
    """
    Compute RIPEMD-160 hash (fallback to SHA256 if not available).

    Args:
        data: Data to hash.

    Returns:
        20-byte hash digest.
    """
    try:
        return hashlib.new("ripemd160", data).digest()
    except ValueError:
        # Fallback to double SHA-256 if ripemd160 unavailable
        return _sha256(_sha256(data))


@dataclass(frozen=True)
class KeyPair:
    """
    ECDSA key pair on secp256k1 curve.

    Attributes:
        private_key: Private key as integer.
        public_key_x: X coordinate of public key point.
        public_key_y: Y coordinate of public key point.
    """

    private_key: int
    public_key_x: int
    public_key_y: int

    def public_key_hex(self) -> str:
        """
        Get compressed public key in hex format.

        Returns:
            33-byte compressed public key (02/03 prefix + x coordinate).
        """
        prefix = "02" if self.public_key_y % 2 == 0 else "03"
        return prefix + format(self.public_key_x, "064x")

    def private_key_hex(self) -> str:
        """
        Get private key as hex string.

        Returns:
            64-character hex string.
        """
        return format(self.private_key, "064x")


def generate_keypair(seed: bytes | None = None) -> KeyPair:
    """
    Generate a new ECDSA key pair on secp256k1.

    Args:
        seed: Optional seed for deterministic generation. If None, uses random.

    Returns:
        KeyPair with valid secp256k1 key.
    """
    if seed is None:
        seed = os.urandom(32)
    else:
        seed = seed[:32]

    # Hash seed to get private key
    private_key = int.from_bytes(_sha256(seed), byteorder="big") % (_CURVE_N - 1) + 1

    # Compute public key
    g = CurvePoint(_CURVE_G_X, _CURVE_G_Y)
    pub_point = g.scalar_mult(private_key)

    return KeyPair(
        private_key=private_key,
        public_key_x=pub_point.x,
        public_key_y=pub_point.y,
    )


def generate_deterministic_keypair(password: str) -> KeyPair:
    """
    Generate a deterministic key pair from a password.

    Args:
        password: Password to derive key from.

    Returns:
        Deterministic KeyPair.
    """
    seed = hashlib.pbkdf2_hmac("sha256", password.encode(), b"thomas_blockchain", 100000)
    return generate_keypair(seed)


def sign_message(message: bytes, private_key: int) -> str:
    """
    Sign a message using ECDSA with private key.

    Uses deterministic RFC 6979 nonce generation.

    Args:
        message: Message to sign.
        private_key: Private key integer.

    Returns:
        Signature as hex string (128 characters for r||s).
    """
    # Hash message
    msg_hash = int.from_bytes(_sha256(message), byteorder="big")

    # Generate deterministic nonce (simplified RFC 6979)
    k_seed = hmac.new(b"ECDSA_NONCE", format(private_key, "064x").encode() + message, hashlib.sha256).digest()
    k = int.from_bytes(k_seed, byteorder="big") % (_CURVE_N - 1) + 1

    # Compute r
    g = CurvePoint(_CURVE_G_X, _CURVE_G_Y)
    point_r = g.scalar_mult(k)
    r = point_r.x % _CURVE_N

    if r == 0:
        # Rare case: try again with different k
        return sign_message(message, private_key)

    # Compute s
    k_inv = pow(k, _CURVE_N - 2, _CURVE_N)
    s = (k_inv * (msg_hash + r * private_key)) % _CURVE_N

    if s == 0:
        # Rare case: try again
        return sign_message(message, private_key)

    # Return DER-like format: r||s
    return format(r, "064x") + format(s, "064x")


def verify_signature(message: bytes, signature: str, public_key_x: int, public_key_y: int) -> bool:
    """
    Verify an ECDSA signature.

    Args:
        message: Original message.
        signature: Signature as hex string (128 characters).
        public_key_x: X coordinate of public key.
        public_key_y: Y coordinate of public key.

    Returns:
        True if signature is valid, False otherwise.
    """
    try:
        if len(signature) != 128:
            return False

        # Parse signature
        r = int(signature[:64], 16)
        s = int(signature[64:], 16)

        # Validate r and s are in valid range
        if r == 0 or r >= _CURVE_N or s == 0 or s >= _CURVE_N:
            return False

        # Hash message
        msg_hash = int.from_bytes(_sha256(message), byteorder="big")

        # Recover point
        g = CurvePoint(_CURVE_G_X, _CURVE_G_Y)
        pub_key = CurvePoint(public_key_x, public_key_y)

        # Compute r^-1
        r_inv = pow(r, _CURVE_N - 2, _CURVE_N)

        # Compute point: (msg_hash * G + r * Q) / r
        msg_part = g.scalar_mult(msg_hash)
        r_part = pub_key.scalar_mult(r)
        x_part = msg_part + r_part
        result = x_part.scalar_mult(r_inv)

        if result.is_infinity():
            return False

        return result.x % _CURVE_N == r

    except Exception:
        return False


def derive_address(public_key_x: int, public_key_y: int) -> str:
    """
    Derive a blockchain address from public key.

    Uses: hash160 = RIPEMD160(SHA256(pubkey))
    Then: address = "1" + base58check_encode(hash160)

    Simplified: address = hex(hash160) + checksum

    Args:
        public_key_x: X coordinate of public key.
        public_key_y: Y coordinate of public key.

    Returns:
        Blockchain address as hex string with checksum.
    """
    # Compute compressed public key
    prefix = "02" if public_key_y % 2 == 0 else "03"
    pubkey_hex = prefix + format(public_key_x, "064x")
    pubkey_bytes = bytes.fromhex(pubkey_hex)

    # Hash: SHA256 then RIPEMD160
    hash160 = _ripemd160(_sha256(pubkey_bytes))

    # Add version byte (0x00 for mainnet)
    versioned = b"\x00" + hash160

    # Compute checksum
    checksum = _sha256(_sha256(versioned))[:4]

    # Address is versioned + hash160 + checksum
    address_bytes = versioned + checksum
    return address_bytes.hex()


def verify_address(address: str) -> bool:
    """
    Verify address checksum.

    Args:
        address: Address to verify.

    Returns:
        True if address checksum is valid.
    """
    try:
        address_bytes = bytes.fromhex(address)
        if len(address_bytes) != 25:
            return False

        versioned = address_bytes[:21]
        checksum = address_bytes[21:]

        expected_checksum = _sha256(_sha256(versioned))[:4]
        return checksum == expected_checksum

    except Exception:
        return False
