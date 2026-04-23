"""Custom exceptions for climate science module."""


class ClimateDataError(Exception):
    """Exception raised for climate data validation errors.

    Attributes:
        message: Description of the data error.
        data: Data that caused the error (optional).
    """

    def __init__(self, message: str, data: object = None) -> None:
        """Initialize ClimateDataError.

        Args:
            message: Error description.
            data: Optional data that caused error.
        """
        self.message = message
        self.data = data
        super().__init__(self.message)


class InvalidParameterError(Exception):
    """Exception raised when invalid parameters are provided.

    Attributes:
        message: Description of the parameter error.
        parameter: Name of invalid parameter.
        value: Value that was invalid.
    """

    def __init__(self, message: str, parameter: str = "", value: object = None) -> None:
        """Initialize InvalidParameterError.

        Args:
            message: Error description.
            parameter: Name of the invalid parameter.
            value: The invalid value provided.
        """
        self.message = message
        self.parameter = parameter
        self.value = value
        super().__init__(self.message)


class ModelError(Exception):
    """Exception raised for climate model errors.

    Attributes:
        message: Description of the model error.
        model_name: Name of the model that failed.
    """

    def __init__(self, message: str, model_name: str = "") -> None:
        """Initialize ModelError.

        Args:
            message: Error description.
            model_name: Name of model that encountered error.
        """
        self.message = message
        self.model_name = model_name
        super().__init__(self.message)
