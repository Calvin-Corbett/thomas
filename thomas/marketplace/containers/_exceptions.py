"""Exception types for container runtime."""


class ContainerException(Exception):
    """Base exception for container operations."""

    pass


class ContainerNotFound(ContainerException):
    """Raised when a container cannot be found."""

    def __init__(self, container_id: str) -> None:
        """Initialize ContainerNotFound exception.

        Args:
            container_id: The ID or name of the container that was not found.
        """
        self.container_id = container_id
        super().__init__(f"Container not found: {container_id}")


class ImageNotFound(ContainerException):
    """Raised when an image cannot be found."""

    def __init__(self, image_name: str) -> None:
        """Initialize ImageNotFound exception.

        Args:
            image_name: The name of the image that was not found.
        """
        self.image_name = image_name
        super().__init__(f"Image not found: {image_name}")


class NetworkNotFound(ContainerException):
    """Raised when a network cannot be found."""

    def __init__(self, network_id: str) -> None:
        """Initialize NetworkNotFound exception.

        Args:
            network_id: The ID or name of the network that was not found.
        """
        self.network_id = network_id
        super().__init__(f"Network not found: {network_id}")


class VolumeNotFound(ContainerException):
    """Raised when a volume cannot be found."""

    def __init__(self, volume_name: str) -> None:
        """Initialize VolumeNotFound exception.

        Args:
            volume_name: The name of the volume that was not found.
        """
        self.volume_name = volume_name
        super().__init__(f"Volume not found: {volume_name}")


class RegistryException(ContainerException):
    """Raised for registry-related errors."""

    pass


class InvalidConfiguration(ContainerException):
    """Raised for invalid container configuration."""

    pass


class InsufficientResources(ContainerException):
    """Raised when insufficient resources are available."""

    pass


class HealthCheckFailed(ContainerException):
    """Raised when a health check fails."""

    def __init__(self, container_id: str, check_type: str) -> None:
        """Initialize HealthCheckFailed exception.

        Args:
            container_id: The ID of the container.
            check_type: The type of health check that failed.
        """
        self.container_id = container_id
        self.check_type = check_type
        super().__init__(f"Health check failed for {container_id}: {check_type}")


class DockerfileParseError(ContainerException):
    """Raised when parsing a Dockerfile fails."""

    def __init__(self, line_number: int, message: str) -> None:
        """Initialize DockerfileParseError exception.

        Args:
            line_number: The line number where the error occurred.
            message: Description of the parsing error.
        """
        self.line_number = line_number
        self.message = message
        super().__init__(f"Dockerfile parse error at line {line_number}: {message}")
