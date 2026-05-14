"""
Audio codecs for file I/O and format conversion.

Supports WAV, AIFF, raw PCM, and compression formats like mu-law and ADPCM.
"""

import struct
from typing import BinaryIO

import numpy as np
from numpy.typing import NDArray

from thomas.marketplace.audio_engine._exceptions import CodecError


class WAVCodec:
    """WAV file reader/writer supporting PCM format.

    Attributes:
        sample_rate: Sample rate in Hz
        num_channels: Number of audio channels
        bit_depth: Bits per sample (8, 16, 24, 32)
    """

    def __init__(self) -> None:
        """Initialize WAV codec."""
        self.sample_rate = 44100
        self.num_channels = 2
        self.bit_depth = 16

    def read(self, filename: str) -> tuple[NDArray[np.float32], int, int]:
        """Read WAV file.

        Args:
            filename: Path to WAV file

        Returns:
            Tuple of (audio_data, sample_rate, num_channels)

        Raises:
            CodecError: If file is invalid
        """
        try:
            with open(filename, "rb") as f:
                # Read RIFF header
                riff_header = f.read(4)
                if riff_header != b"RIFF":
                    raise CodecError("Invalid WAV file: missing RIFF header")

                struct.unpack("<I", f.read(4))[0]
                wave_header = f.read(4)
                if wave_header != b"WAVE":
                    raise CodecError("Invalid WAV file: missing WAVE header")

                # Find fmt chunk
                fmt_found = False
                while True:
                    chunk_id = f.read(4)
                    if not chunk_id:
                        break

                    chunk_size = struct.unpack("<I", f.read(4))[0]

                    if chunk_id == b"fmt ":
                        # Parse format chunk
                        audio_format = struct.unpack("<H", f.read(2))[0]
                        num_channels = struct.unpack("<H", f.read(2))[0]
                        sample_rate = struct.unpack("<I", f.read(4))[0]
                        struct.unpack("<I", f.read(4))[0]
                        struct.unpack("<H", f.read(2))[0]
                        bits_per_sample = struct.unpack("<H", f.read(2))[0]

                        self.sample_rate = sample_rate
                        self.num_channels = num_channels
                        self.bit_depth = bits_per_sample

                        if audio_format != 1:
                            raise CodecError("Only PCM WAV format supported")

                        fmt_found = True
                        # Skip remaining fmt bytes
                        f.read(chunk_size - 16)

                    elif chunk_id == b"data":
                        if not fmt_found:
                            raise CodecError("fmt chunk must come before data chunk")

                        # Read audio data
                        num_samples = chunk_size // (self.bit_depth // 8) // self.num_channels
                        audio_data = self._read_pcm_data(f, self.bit_depth, self.num_channels, num_samples)
                        return audio_data, self.sample_rate, self.num_channels

                    else:
                        # Skip unknown chunk
                        f.read(chunk_size)

                raise CodecError("No data chunk found")

        except (OSError, struct.error) as e:
            raise CodecError(f"Error reading WAV file: {e}")

    def write(self, filename: str, audio_data: NDArray[np.float32], sample_rate: int, num_channels: int) -> None:
        """Write WAV file.

        Args:
            filename: Output filename
            audio_data: Audio samples (normalized to [-1.0, 1.0])
            sample_rate: Sample rate in Hz
            num_channels: Number of channels

        Raises:
            CodecError: If write fails
        """
        try:
            bit_depth = 16
            bytes_per_sample = bit_depth // 8
            num_samples = len(audio_data) if audio_data.ndim == 1 else len(audio_data)
            byte_rate = sample_rate * num_channels * bytes_per_sample
            block_align = num_channels * bytes_per_sample
            data_size = num_samples * num_channels * bytes_per_sample

            with open(filename, "wb") as f:
                # Write RIFF header
                f.write(b"RIFF")
                f.write(struct.pack("<I", 36 + data_size))
                f.write(b"WAVE")

                # Write fmt chunk
                f.write(b"fmt ")
                f.write(struct.pack("<I", 16))  # Chunk size
                f.write(struct.pack("<H", 1))  # Audio format (1 = PCM)
                f.write(struct.pack("<H", num_channels))
                f.write(struct.pack("<I", sample_rate))
                f.write(struct.pack("<I", byte_rate))
                f.write(struct.pack("<H", block_align))
                f.write(struct.pack("<H", bit_depth))

                # Write data chunk
                f.write(b"data")
                f.write(struct.pack("<I", data_size))

                # Write audio data
                self._write_pcm_data(f, audio_data, bit_depth, num_channels)

        except (OSError, struct.error) as e:
            raise CodecError(f"Error writing WAV file: {e}")

    @staticmethod
    def _read_pcm_data(file: BinaryIO, bit_depth: int, num_channels: int, num_samples: int) -> NDArray[np.float32]:
        """Read PCM audio data from file.

        Args:
            file: File object
            bit_depth: Bits per sample
            num_channels: Number of channels
            num_samples: Number of samples per channel

        Returns:
            Audio data normalized to [-1.0, 1.0]
        """
        bytes_per_sample = bit_depth // 8
        total_bytes = num_samples * num_channels * bytes_per_sample
        data = file.read(total_bytes)

        if bit_depth == 16:
            samples = np.frombuffer(data, dtype=np.int16)
            audio = samples.astype(np.float32) / 32768.0
        elif bit_depth == 32:
            samples = np.frombuffer(data, dtype=np.int32)
            audio = samples.astype(np.float32) / 2147483648.0
        else:
            raise CodecError(f"Unsupported bit depth: {bit_depth}")

        # Reshape to (num_samples, num_channels)
        if num_channels > 1:
            audio = audio.reshape(num_samples, num_channels)

        return audio.astype(np.float32)

    @staticmethod
    def _write_pcm_data(file: BinaryIO, audio: NDArray[np.float32], bit_depth: int, num_channels: int) -> None:
        """Write PCM audio data to file.

        Args:
            file: File object
            audio: Audio samples
            bit_depth: Bits per sample
            num_channels: Number of channels
        """
        # Ensure correct shape
        if audio.ndim == 1:
            audio = np.column_stack([audio] * num_channels)

        # Convert to PCM
        if bit_depth == 16:
            audio_int = (audio * 32767.0).astype(np.int16)
        elif bit_depth == 32:
            audio_int = (audio * 2147483647.0).astype(np.int32)
        else:
            raise CodecError(f"Unsupported bit depth: {bit_depth}")

        # Flatten and write
        file.write(audio_int.flatten().tobytes())


class RawPCMCodec:
    """Raw PCM file reader/writer without headers."""

    def read(
        self, filename: str, sample_rate: int = 44100, num_channels: int = 2, bit_depth: int = 16
    ) -> tuple[NDArray[np.float32], int]:
        """Read raw PCM file.

        Args:
            filename: Path to file
            sample_rate: Sample rate in Hz
            num_channels: Number of channels
            bit_depth: Bits per sample

        Returns:
            Tuple of (audio_data, sample_rate)

        Raises:
            CodecError: If read fails
        """
        try:
            bytes_per_sample = bit_depth // 8
            with open(filename, "rb") as f:
                data = f.read()

            num_samples = len(data) // (bytes_per_sample * num_channels)

            if bit_depth == 16:
                samples = np.frombuffer(data, dtype=np.int16)[: num_samples * num_channels]
                audio = samples.astype(np.float32) / 32768.0
            elif bit_depth == 32:
                samples = np.frombuffer(data, dtype=np.int32)[: num_samples * num_channels]
                audio = samples.astype(np.float32) / 2147483648.0
            else:
                raise CodecError(f"Unsupported bit depth: {bit_depth}")

            # Reshape
            if num_channels > 1:
                audio = audio.reshape(num_samples, num_channels)

            return audio.astype(np.float32), sample_rate

        except OSError as e:
            raise CodecError(f"Error reading raw PCM: {e}")

    def write(self, filename: str, audio: NDArray[np.float32], bit_depth: int = 16) -> None:
        """Write raw PCM file.

        Args:
            filename: Output filename
            audio: Audio samples
            bit_depth: Bits per sample

        Raises:
            CodecError: If write fails
        """
        try:
            if bit_depth == 16:
                audio_int = (audio * 32767.0).astype(np.int16)
            elif bit_depth == 32:
                audio_int = (audio * 2147483647.0).astype(np.int32)
            else:
                raise CodecError(f"Unsupported bit depth: {bit_depth}")

            with open(filename, "wb") as f:
                f.write(audio_int.flatten().tobytes())

        except OSError as e:
            raise CodecError(f"Error writing raw PCM: {e}")


class CompandingCodec:
    """Mu-law and A-law audio companding."""

    @staticmethod
    def mu_law_encode(samples: NDArray[np.float32], mu: float = 255.0) -> NDArray[np.uint8]:
        """Encode using mu-law companding.

        Args:
            samples: Input samples (normalized to [-1.0, 1.0])
            mu: Companding parameter (typically 255)

        Returns:
            8-bit mu-law encoded samples
        """
        safe_samples = np.clip(samples, -1.0, 1.0)
        magnitude = np.abs(safe_samples)
        signal = np.sign(safe_samples) * np.log(1.0 + mu * magnitude) / np.log(1.0 + mu)
        quantized = ((signal + 1.0) / 2.0 * 255.0).astype(np.uint8)
        return quantized

    @staticmethod
    def mu_law_decode(encoded: NDArray[np.uint8], mu: float = 255.0) -> NDArray[np.float32]:
        """Decode mu-law companded samples.

        Args:
            encoded: 8-bit mu-law encoded samples
            mu: Companding parameter

        Returns:
            Float samples (normalized to [-1.0, 1.0])
        """
        signal = encoded.astype(np.float32) / 255.0 * 2.0 - 1.0
        magnitude = np.abs(signal)
        decoded = np.sign(signal) * (1.0 / mu) * ((1.0 + mu) ** magnitude - 1.0)
        return np.clip(decoded, -1.0, 1.0)

    @staticmethod
    def a_law_encode(samples: NDArray[np.float32], a: float = 87.6) -> NDArray[np.uint8]:
        """Encode using A-law companding.

        Args:
            samples: Input samples
            a: Companding parameter (typically 87.6)

        Returns:
            8-bit A-law encoded samples
        """
        safe_samples = np.clip(samples, -1.0, 1.0)
        magnitude = np.abs(safe_samples)

        encoded = np.zeros_like(safe_samples)
        mask = magnitude < 1.0 / a
        encoded[mask] = a * magnitude[mask]
        encoded[~mask] = 1.0 + np.log(a * magnitude[~mask])
        encoded = encoded / (1.0 + np.log(a))
        encoded = encoded * np.sign(safe_samples)

        quantized = ((encoded + 1.0) / 2.0 * 255.0).astype(np.uint8)
        return quantized

    @staticmethod
    def a_law_decode(encoded: NDArray[np.uint8], a: float = 87.6) -> NDArray[np.float32]:
        """Decode A-law companded samples.

        Args:
            encoded: 8-bit A-law encoded samples
            a: Companding parameter

        Returns:
            Float samples
        """
        signal = encoded.astype(np.float32) / 255.0 * 2.0 - 1.0
        magnitude = np.abs(signal)

        decoded = np.zeros_like(signal)
        mask = magnitude < 1.0 / (1.0 + np.log(a))
        decoded[mask] = magnitude[mask] / a
        decoded[~mask] = np.exp(magnitude[~mask] * (1.0 + np.log(a)) - 1.0) / a
        decoded = decoded * np.sign(signal)

        return np.clip(decoded, -1.0, 1.0)


class ADPCMCodec:
    """IMA ADPCM codec with step table."""

    # IMA ADPCM step table
    STEP_TABLE = [
        7,
        8,
        9,
        10,
        11,
        12,
        13,
        14,
        16,
        17,
        19,
        21,
        23,
        25,
        28,
        31,
        34,
        37,
        41,
        45,
        50,
        55,
        60,
        66,
        73,
        80,
        88,
        97,
        107,
        118,
        130,
        143,
        157,
        173,
        190,
        209,
        230,
        253,
        279,
        307,
        337,
        371,
        408,
        449,
        494,
        544,
        598,
        658,
        724,
        796,
        873,
        957,
        1049,
        1149,
        1257,
        1374,
        1502,
        1640,
        1791,
        1956,
        2139,
        2342,
        2566,
        2816,
        3096,
        3409,
        3759,
        4148,
        4581,
        5060,
        5589,
        6171,
        6812,
        7512,
        8283,
        9129,
        10000,
        10960,
        12014,
        13176,
        14456,
        15863,
        17405,
        19209,
        21170,
        23436,
        25856,
        28540,
        31405,
        34543,
        37985,
        41762,
        45894,
        50385,
        55277,
        60594,
        66340,
        72592,
        79365,
        86816,
        94885,
        103682,
        113313,
        123888,
        135541,
        148406,
        162621,
        178353,
        195777,
        215062,
        236434,
        259960,
    ]

    INDEX_TABLE = [-1, -1, -1, -1, 2, 4, 6, 8]

    def encode(self, samples: NDArray[np.float32]) -> NDArray[np.uint8]:
        """Encode to IMA ADPCM.

        Args:
            samples: Input samples

        Returns:
            ADPCM encoded data
        """
        safe_samples = np.clip(samples, -1.0, 1.0) * 32767.0
        encoded = []
        step_index = 0
        predicted = 0

        for sample in safe_samples:
            delta = int(sample) - predicted
            step = self.STEP_TABLE[step_index]

            # Quantize
            code = 0
            if delta < 0:
                code = 8
                delta = -delta

            for i in range(3):
                if delta >= step:
                    code |= 1 << i
                    delta -= step
                step >>= 1

            # Update predicted value
            step = self.STEP_TABLE[step_index]
            diff = step >> 3
            if code & 1:
                diff += step >> 2
            if code & 2:
                diff += step >> 1
            if code & 4:
                diff += step

            if code & 8:
                predicted -= diff
            else:
                predicted += diff

            predicted = np.clip(predicted, -32768, 32767)

            # Update step index
            step_index += self.INDEX_TABLE[code & 7]
            step_index = np.clip(step_index, 0, len(self.STEP_TABLE) - 1)

            encoded.append(code)

        return np.array(encoded, dtype=np.uint8)

    def decode(self, encoded: NDArray[np.uint8]) -> NDArray[np.float32]:
        """Decode IMA ADPCM.

        Args:
            encoded: ADPCM encoded data

        Returns:
            Decoded audio samples
        """
        decoded = []
        step_index = 0
        predicted = 0

        for code in encoded:
            step = self.STEP_TABLE[step_index]
            diff = step >> 3

            if code & 1:
                diff += step >> 2
            if code & 2:
                diff += step >> 1
            if code & 4:
                diff += step

            if code & 8:
                predicted -= diff
            else:
                predicted += diff

            predicted = np.clip(predicted, -32768, 32767)
            step_index += self.INDEX_TABLE[code & 7]
            step_index = np.clip(step_index, 0, len(self.STEP_TABLE) - 1)

            decoded.append(predicted / 32768.0)

        return np.array(decoded, dtype=np.float32)
