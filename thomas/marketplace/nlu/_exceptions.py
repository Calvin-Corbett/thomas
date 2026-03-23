"""
Custom exceptions for the NLU module.
"""


class NLUException(Exception):
    """Base exception for NLU module."""

    pass


class TokenizationError(NLUException):
    """Raised when tokenization fails."""

    def __init__(self, message: str, text: str = "", offset: int = -1) -> None:
        """
        Initialize tokenization error.

        Args:
            message: Error message
            text: The text being tokenized
            offset: Offset in text where error occurred
        """
        self.message = message
        self.text = text
        self.offset = offset
        full_msg = message
        if offset >= 0:
            full_msg += f" at offset {offset}"
        super().__init__(full_msg)


class ParsingError(NLUException):
    """Raised when parsing fails."""

    def __init__(self, message: str, sentence: str = "", token_idx: int = -1) -> None:
        """
        Initialize parsing error.

        Args:
            message: Error message
            sentence: The sentence being parsed
            token_idx: Token index where error occurred
        """
        self.message = message
        self.sentence = sentence
        self.token_idx = token_idx
        full_msg = message
        if token_idx >= 0:
            full_msg += f" at token {token_idx}"
        super().__init__(full_msg)


class EntityExtractionError(NLUException):
    """Raised when entity extraction fails."""

    def __init__(self, message: str, entity_type: str = "") -> None:
        """
        Initialize entity extraction error.

        Args:
            message: Error message
            entity_type: Type of entity being extracted
        """
        self.message = message
        self.entity_type = entity_type
        full_msg = message
        if entity_type:
            full_msg += f" for entity type {entity_type}"
        super().__init__(full_msg)


class ClassificationError(NLUException):
    """Raised when classification fails."""

    def __init__(self, message: str, text: str = "") -> None:
        """
        Initialize classification error.

        Args:
            message: Error message
            text: The text being classified
        """
        self.message = message
        self.text = text
        super().__init__(message)


class InvalidSpanError(NLUException):
    """Raised when span is invalid."""

    pass


class InvalidDependencyError(NLUException):
    """Raised when dependency is invalid."""

    pass


class AmbiguityError(NLUException):
    """Raised when there is genuine ambiguity that cannot be resolved."""

    pass


class ModelNotTrainedError(NLUException):
    """Raised when attempting to use untrained model."""

    pass


class UnsupportedLanguageError(NLUException):
    """Raised when language is not supported."""

    def __init__(self, language: str) -> None:
        """Initialize unsupported language error."""
        self.language = language
        super().__init__(f"Language '{language}' is not supported")
