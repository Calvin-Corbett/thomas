"""HPACK Huffman code table (RFC 7541 Appendix B)."""

# Huffman code table: symbol -> (code, bit_length)
HUFFMAN_TABLE: dict[int, tuple[int, int]] = {
    0: (0x1FF8, 10),
    1: (0x7FFFD8, 23),
    2: (0xFFFFFE2, 28),
    3: (0xFFFFFE3, 28),
    4: (0xFFFFFE4, 28),
    5: (0xFFFFFE5, 28),
    6: (0xFFFFFE6, 28),
    7: (0xFFFFFE7, 28),
    8: (0xFFFFFE8, 28),
    9: (0xFFFFEA, 24),
    10: (0x3FFFFFFC, 30),
    11: (0xFFFFFE9, 28),
    12: (0xFFFFFEA, 28),
    13: (0x3FFFFFFD, 30),
    14: (0xFFFFFEB, 28),
    15: (0xFFFFFEC, 28),
    16: (0xFFFFFED, 28),
    17: (0xFFFFFEE, 28),
    18: (0xFFFFFEF, 28),
    19: (0xFFFFFF0, 28),
    20: (0xFFFFFF1, 28),
    21: (0xFFFFFF2, 28),
    22: (0x3FFFFFFE, 30),
    23: (0xFFFFFF3, 28),
    24: (0xFFFFFF4, 28),
    25: (0xFFFFFF5, 28),
    26: (0xFFFFFF6, 28),
    27: (0xFFFFFF7, 28),
    28: (0xFFFFFF8, 28),
    29: (0xFFFFFF9, 28),
    30: (0xFFFFFFA, 28),
    31: (0xFFFFFFB, 28),
    32: (0x14, 6),
    33: (0x3F8, 10),
    34: (0x3F9, 10),
    35: (0xFFA, 12),
    36: (0x1FF9, 13),
    37: (0x15, 6),
    38: (0xF8, 8),
    39: (0x7AF, 11),
    40: (0x3FA, 10),
    41: (0x3FB, 10),
    42: (0xF9, 8),
    43: (0x7B0, 11),
    44: (0x7B1, 11),
    45: (0x16, 6),
    46: (0x17, 6),
    47: (0x18, 6),
    48: (0x0, 5),
    49: (0x1, 5),
    50: (0x2, 5),
    51: (0x19, 6),
    52: (0x1A, 6),
    53: (0x1B, 6),
    54: (0x1C, 6),
    55: (0x1D, 6),
    56: (0x1E, 6),
    57: (0x1F, 6),
    58: (0x5C, 7),
    59: (0xFB, 8),
    60: (0x7FFC, 15),
    61: (0x20, 6),
    62: (0xFFB, 12),
    63: (0x3FC, 10),
    64: (0x1FFA, 13),
    65: (0x21, 6),
    66: (0x5D, 7),
    67: (0x5E, 7),
    68: (0x5F, 7),
    69: (0x60, 7),
    70: (0x61, 7),
    71: (0x62, 7),
    72: (0x63, 7),
    73: (0x64, 7),
    74: (0x65, 7),
    75: (0x66, 7),
    76: (0x67, 7),
    77: (0x68, 7),
    78: (0x69, 7),
    79: (0x6A, 7),
    80: (0x6B, 7),
    81: (0x6C, 7),
    82: (0x6D, 7),
    83: (0x6E, 7),
    84: (0x6F, 7),
    85: (0x70, 7),
    86: (0x71, 7),
    87: (0x72, 7),
    88: (0xFC, 8),
    89: (0x73, 7),
    90: (0xFD, 8),
    91: (0x1FFB, 13),
    92: (0x7FFF0, 19),
    93: (0x1FFC, 13),
    94: (0x3FFC, 14),
    95: (0x22, 6),
    96: (0x7FFD, 15),
    97: (0x3, 5),
    98: (0x23, 6),
    99: (0x4, 5),
    100: (0x24, 6),
    101: (0x5, 5),
    102: (0x25, 6),
    103: (0x26, 6),
    104: (0x27, 6),
    105: (0x6, 5),
    106: (0x74, 7),
    107: (0x75, 7),
    108: (0x28, 6),
    109: (0x29, 6),
    110: (0x2A, 6),
    111: (0x7, 5),
    112: (0x2B, 6),
    113: (0x76, 7),
    114: (0x2C, 6),
    115: (0x8, 5),
    116: (0x9, 5),
    117: (0x2D, 6),
    118: (0x77, 7),
    119: (0x78, 7),
    120: (0x79, 7),
    121: (0x7A, 7),
    122: (0x7B, 7),
    123: (0x7FFE, 15),
    124: (0x7C, 7),
    125: (0x20C, 10),
    126: (0x20D, 10),
    127: (0x3FFD, 14),
    128: (0x3FFFE, 15),
    129: (0xFFFFF0, 20),
    130: (0xFFFFF1, 20),
    131: (0xFFFFF2, 20),
    132: (0x3FFFF0, 22),
    133: (0x3FFFF1, 22),
    134: (0xFFFFF3, 20),
    135: (0xFFFFF4, 20),
    136: (0xFFFFF5, 20),
    137: (0x3FFFF2, 22),
    138: (0xFFFFF6, 20),
    139: (0xFFFFF7, 20),
    140: (0xFFFFF8, 20),
    141: (0xFFFFF9, 20),
    142: (0xFFFFFA, 20),
    143: (0x3FFFF3, 22),
    144: (0x3FFFF4, 22),
    145: (0xFFFFFB, 20),
    146: (0x3FFFF5, 22),
    147: (0x3FFFF6, 22),
    148: (0x3FFFF7, 22),
    149: (0x3FFFF8, 22),
    150: (0x1FFFFF0, 21),
    151: (0x3FFFF9, 22),
    152: (0x3FFFFA, 22),
    153: (0x1FFFFF1, 21),
    154: (0x1FFFFF2, 21),
    155: (0x3FFFFB, 22),
    156: (0x3FFFFC, 22),
    157: (0x1FFFFF3, 21),
    158: (0x3FFFFD, 22),
    159: (0x1FFFFF4, 21),
    160: (0x1FFFFF5, 21),
    161: (0x3FFFFE, 22),
    162: (0x1FFFFF6, 21),
    163: (0x3FFFFF0, 22),
    164: (0x1FFFFF7, 21),
    165: (0x3FFFFF1, 22),
    166: (0x1FFFFF8, 21),
    167: (0x1FFFFF9, 21),
    168: (0x3FFFFF2, 22),
    169: (0x1FFFFA, 21),
    170: (0x1FFFFB, 21),
    171: (0x3FFFFF3, 22),
    172: (0x3FFFFF4, 22),
    173: (0x1FFFFFD, 21),
    174: (0x3FFFFF5, 22),
    175: (0x1FFFFFC, 21),
    176: (0x1FFFFEE, 21),
    177: (0x3FFFFF6, 22),
    178: (0x3FFFFF7, 22),
    179: (0x7FFFF0, 23),
    180: (0x3FFFFF8, 22),
    181: (0x1FFFFEF, 21),
    182: (0x3FFFFF9, 22),
    183: (0x7FFFF1, 23),
    184: (0x3FFFFFA, 22),
    185: (0x7FFFF2, 23),
    186: (0x1FFFFCC, 21),
    187: (0x3FFFFB0, 26),
    188: (0x7FFFF3, 23),
    189: (0x3FFFFB1, 26),
    190: (0x7FFFF4, 23),
    191: (0x3FFFFB2, 26),
    192: (0x3FFFFB3, 26),
    193: (0x3FFFFB4, 26),
    194: (0x7FFFF5, 23),
    195: (0x3FFFFB5, 26),
    196: (0x3FFFFB6, 26),
    197: (0x7FFFF6, 23),
    198: (0x3FFFFB7, 26),
    199: (0x7FFFF7, 23),
    200: (0x3FFFFB8, 26),
    201: (0x3FFFFB9, 26),
    202: (0x3FFFFBA, 26),
    203: (0x3FFFFBB, 26),
    204: (0x3FFFFBC, 26),
    205: (0x7FFFF8, 23),
    206: (0x3FFFFBD, 26),
    207: (0x3FFFFBE, 26),
    208: (0x3FFFFBF, 26),
    209: (0x7FFFF9, 23),
    210: (0x3FFFFC0, 26),
    211: (0x3FFFFC1, 26),
    212: (0xFFFFFB, 20),
    213: (0x7FFFFA, 23),
    214: (0x3FFFFC2, 26),
    215: (0x3FFFFC3, 26),
    216: (0x3FFFFC4, 26),
    217: (0x3FFFFC5, 26),
    218: (0x7FFFFB, 23),
    219: (0x3FFFFC6, 26),
    220: (0x7FFFFC, 23),
    221: (0x3FFFFC7, 26),
    222: (0x3FFFFC8, 26),
    223: (0x3FFFFC9, 26),
    224: (0x3FFFFCA, 26),
    225: (0x3FFFFCB, 26),
    226: (0x3FFFFCC, 26),
    227: (0x3FFFFCD, 26),
    228: (0x7FFFFCC, 23),
    229: (0x3FFFFCE, 26),
    230: (0x3FFFFCF, 26),
    231: (0x3FFFFD0, 26),
    232: (0x3FFFFD1, 26),
    233: (0x7FFFFCD, 23),
    234: (0x3FFFFD2, 26),
    235: (0x7FFFFCE, 23),
    236: (0x7FFFFCF, 23),
    237: (0x3FFFFD3, 26),
    238: (0x3FFFFD4, 26),
    239: (0x3FFFFD5, 26),
    240: (0xFFFFFC, 20),
    241: (0x7FFFFD0, 23),
    242: (0x3FFFFD6, 26),
    243: (0x3FFFFD7, 26),
    244: (0x3FFFFD8, 26),
    245: (0x3FFFFD9, 26),
    246: (0x3FFFFD9, 26),
    247: (0x3FFFFDA, 26),
    248: (0x3FFFFDB, 26),
    249: (0x3FFFFDC, 26),
    250: (0x3FFFFDD, 26),
    251: (0x3FFFFDE, 26),
    252: (0x3FFFFDF, 26),
    253: (0x3FFFFE0, 26),
    254: (0x3FFFFE1, 26),
    255: (0xFFFFFE2, 24),
    256: (0x3FFFFE2, 26),
}


class HuffmanDecoder:
    """Decoder for HPACK Huffman-encoded data."""

    def __init__(self) -> None:
        """Initialize the decoder by building the decode tree."""
        self.root = self._build_decode_tree()

    def _build_decode_tree(self) -> dict:
        """Build binary tree for Huffman decoding.

        Returns:
            Root node of the decode tree.
        """
        root: dict = {"0": {}, "1": {}, "sym": None}

        for symbol, (code, length) in HUFFMAN_TABLE.items():
            node = root
            # Traverse the tree, creating nodes as needed
            for i in range(length - 1, -1, -1):
                bit = "1" if (code >> i) & 1 else "0"
                if bit not in node:
                    node[bit] = {"0": {}, "1": {}, "sym": None}
                node = node[bit]
            node["sym"] = symbol

        return root

    def decode(self, data: bytes) -> bytes:
        """Decode Huffman-encoded data.

        Args:
            data: Huffman-encoded bytes.

        Returns:
            Decoded bytes.

        Raises:
            ValueError: If data is invalid or ends with EOS padding.
        """
        result = []
        node = self.root
        bits = 0
        bit_count = 0

        for byte in data:
            bits = (bits << 8) | byte
            bit_count += 8

            while bit_count >= 1:
                bit = (bits >> (bit_count - 1)) & 1
                bit_count -= 1
                bit_str = "1" if bit else "0"

                if bit_str in node:
                    node = node[bit_str]
                    if node["sym"] is not None:
                        symbol = node["sym"]
                        # Check for EOS padding (symbol 256)
                        if symbol == 256:
                            if bit_count > 0:
                                raise ValueError("Padding bits before EOS")
                            break
                        result.append(symbol)
                        node = self.root
                else:
                    raise ValueError("Invalid Huffman sequence")

        # Validate final state
        if node != self.root:
            # All remaining bits should be 1 (EOS padding)
            while bit_count > 0:
                bit = (bits >> (bit_count - 1)) & 1
                bit_count -= 1
                if bit != 1:
                    raise ValueError("Invalid padding bits")

        return bytes(result)


class HuffmanEncoder:
    """Encoder for HPACK Huffman compression."""

    def encode(self, data: bytes) -> bytes:
        """Encode data using Huffman compression.

        Args:
            data: Data to encode.

        Returns:
            Huffman-encoded bytes.
        """
        bits = 0
        bit_count = 0
        result = []

        for byte in data:
            if byte >= len(HUFFMAN_TABLE):
                raise ValueError(f"Invalid symbol: {byte}")

            code, length = HUFFMAN_TABLE[byte]
            bits = (bits << length) | code
            bit_count += length

            # Extract complete bytes
            while bit_count >= 8:
                bit_count -= 8
                byte_val = (bits >> bit_count) & 0xFF
                result.append(byte_val)
                bits &= (1 << bit_count) - 1

        # Flush remaining bits with EOS padding
        if bit_count > 0:
            eos_code, eos_length = HUFFMAN_TABLE[256]
            bits = (bits << (8 - bit_count)) | (eos_code >> (eos_length - (8 - bit_count)))
            result.append(bits & 0xFF)

        return bytes(result)
