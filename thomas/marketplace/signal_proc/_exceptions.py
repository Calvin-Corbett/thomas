"""
Custom exceptions for signal processing module.
"""


class SignalError(Exception):
    """
    Raised for general signal processing errors.

    This is the base exception for signal-related issues such as invalid
    signal properties or incompatible signal dimensions.
    """

    pass


class FilterError(Exception):
    """
    Raised for filter design and application errors.

    This exception is raised when filter design fails (e.g., invalid
    cutoff frequencies) or filter application fails (e.g., stability issues).
    """

    pass


class FFTError(Exception):
    """
    Raised for FFT computation errors.

    This exception is raised when FFT computation fails, such as when
    input length is not appropriate for the algorithm used.
    """

    pass
