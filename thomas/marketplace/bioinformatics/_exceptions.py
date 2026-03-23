"""
Custom exceptions for the bioinformatics module.

Provides specific exception types for common errors in sequence analysis,
alignment, and other bioinformatics operations.
"""


class BioError(Exception):
    """
    Base exception for all bioinformatics errors.

    This is the parent class for all domain-specific exceptions in the
    bioinformatics module.
    """

    pass


class InvalidSequenceError(BioError):
    """
    Raised when a sequence contains invalid characters or structure.

    This exception is raised when:
    - A DNA sequence contains non-ACGT characters
    - An RNA sequence contains non-ACGU characters
    - A protein sequence contains invalid amino acid codes
    - A sequence is empty or None
    - A sequence type is not recognized
    """

    pass


class AlignmentError(BioError):
    """
    Raised when sequence alignment operations fail.

    This exception is raised when:
    - Alignment scoring fails
    - Sequences are incompatible for alignment
    - Invalid gap penalties are provided
    - Traceback fails in alignment algorithms
    - Substitution matrix is invalid
    """

    pass
