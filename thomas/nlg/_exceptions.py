"""Custom exceptions for NLG system."""


class NLGException(Exception):
    """Base exception for all NLG errors."""

    pass


class ContentSelectionError(NLGException):
    """Raised when content selection fails."""

    def __init__(self, message: str, content_items: int = 0) -> None:
        """Initialize content selection error.

        Args:
            message: Error message
            content_items: Number of items attempted to process
        """
        super().__init__(message)
        self.content_items = content_items


class DocumentPlanningError(NLGException):
    """Raised when document planning fails."""

    def __init__(self, message: str, stage: str = "planning") -> None:
        """Initialize document planning error.

        Args:
            message: Error message
            stage: Which planning stage failed
        """
        super().__init__(message)
        self.stage = stage


class SentencePlanningError(NLGException):
    """Raised when sentence planning fails."""

    def __init__(self, message: str, semantic_frames: int = 0) -> None:
        """Initialize sentence planning error.

        Args:
            message: Error message
            semantic_frames: Number of frames attempted to process
        """
        super().__init__(message)
        self.semantic_frames = semantic_frames


class GrammarError(NLGException):
    """Raised when grammar rules fail to apply."""

    def __init__(self, message: str, rule: str = "", category: str = "") -> None:
        """Initialize grammar error.

        Args:
            message: Error message
            rule: Grammar rule that failed
            category: Grammatical category involved
        """
        super().__init__(message)
        self.rule = rule
        self.category = category


class MorphologyError(NLGException):
    """Raised when morphological generation fails."""

    def __init__(self, message: str, lemma: str = "", form: str = "") -> None:
        """Initialize morphology error.

        Args:
            message: Error message
            lemma: Lemma that failed to inflect
            form: Target form that couldn't be generated
        """
        super().__init__(message)
        self.lemma = lemma
        self.form = form


class RealizationError(NLGException):
    """Raised when surface realization fails."""

    def __init__(self, message: str, tree_depth: int = 0) -> None:
        """Initialize realization error.

        Args:
            message: Error message
            tree_depth: Depth of syntax tree being realized
        """
        super().__init__(message)
        self.tree_depth = tree_depth
