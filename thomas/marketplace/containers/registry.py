"""Container image registry management."""

import base64
import hashlib
from dataclasses import dataclass, field
from datetime import datetime

from thomas.marketplace.containers._exceptions import ImageNotFound, RegistryException
from thomas.marketplace.containers._types import Image


@dataclass
class RegistryCredentials:
    """Registry authentication credentials."""

    username: str
    password: str
    email: str | None = None

    def encode_auth(self) -> str:
        """Encode credentials for authentication header.

        Returns:
            Base64 encoded credentials.
        """
        credentials = f"{self.username}:{self.password}"
        return base64.b64encode(credentials.encode()).decode()


@dataclass
class ImageManifest:
    """Docker image manifest."""

    config_digest: str
    layers: list[dict[str, str]] = field(default_factory=list)
    architecture: str = "amd64"
    os: str = "linux"
    created_at: datetime = field(default_factory=datetime.utcnow)


class ContainerRegistry:
    """Manages container image registry operations."""

    def __init__(self, registry_root: str = "/var/lib/containers/registry") -> None:
        """Initialize container registry.

        Args:
            registry_root: Root directory for registry storage.
        """
        self.registry_root = registry_root
        self._images: dict[str, Image] = {}
        self._repositories: dict[str, set[str]] = {}
        self._manifests: dict[str, ImageManifest] = {}
        self._credentials: dict[str, RegistryCredentials] = {}
        self._layer_refs: dict[str, set[str]] = {}

    def set_credentials(self, registry_host: str, credentials: RegistryCredentials) -> None:
        """Set registry credentials.

        Args:
            registry_host: Registry hostname.
            credentials: Authentication credentials.
        """
        self._credentials[registry_host] = credentials

    def push_image(
        self,
        image: Image,
        registry_host: str = "localhost:5000",
        tag_override: str | None = None,
    ) -> str:
        """Push image to registry.

        Args:
            image: Image to push.
            registry_host: Registry hostname.
            tag_override: Override image tag.

        Returns:
            Fully qualified image name pushed to registry.

        Raises:
            RegistryException: If push fails.
        """
        # Simulate push operation
        tag = tag_override or image.tag
        full_name = f"{registry_host}/{image.name}:{tag}"

        # Store image in registry
        self._images[image.digest] = image
        self._manifests[image.digest] = self._create_manifest(image)

        # Update repository index
        repo_key = f"{registry_host}/{image.name}"
        if repo_key not in self._repositories:
            self._repositories[repo_key] = set()
        self._repositories[repo_key].add(tag)

        # Track layer references
        for layer in image.layers:
            if layer.digest not in self._layer_refs:
                self._layer_refs[layer.digest] = set()
            self._layer_refs[layer.digest].add(image.digest)

        return full_name

    def pull_image(
        self,
        registry_host: str,
        image_name: str,
        tag: str = "latest",
    ) -> Image:
        """Pull image from registry.

        Args:
            registry_host: Registry hostname.
            image_name: Image name.
            tag: Image tag.

        Returns:
            Pulled image.

        Raises:
            ImageNotFound: If image not found in registry.
        """
        repo_key = f"{registry_host}/{image_name}"

        if repo_key not in self._repositories or tag not in self._repositories[repo_key]:
            raise ImageNotFound(f"{repo_key}:{tag}")

        # Find image by name and tag
        for image_digest, image in self._images.items():
            if image.name == image_name and image.tag == tag:
                return image

        raise ImageNotFound(f"{repo_key}:{tag}")

    def list_images(
        self,
        registry_host: str | None = None,
        repository: str | None = None,
    ) -> list[tuple[str, list[str]]]:
        """List images in registry.

        Args:
            registry_host: Filter by registry host.
            repository: Filter by repository name.

        Returns:
            List of (repository, tags) tuples.
        """
        results = []

        for repo_key, tags in self._repositories.items():
            if registry_host and not repo_key.startswith(registry_host):
                continue
            if repository and repository not in repo_key:
                continue

            results.append((repo_key, sorted(list(tags))))

        return results

    def list_image_tags(self, registry_host: str, image_name: str) -> list[str]:
        """List all tags for an image.

        Args:
            registry_host: Registry hostname.
            image_name: Image name.

        Returns:
            List of tags.
        """
        repo_key = f"{registry_host}/{image_name}"
        return sorted(list(self._repositories.get(repo_key, set())))

    def remove_image(self, digest: str) -> None:
        """Remove image from registry.

        Args:
            digest: Image digest.

        Raises:
            ImageNotFound: If image not found.
        """
        if digest not in self._images:
            raise ImageNotFound(digest)

        image = self._images[digest]

        # Remove from repository index
        for repo_key, tags in list(self._repositories.items()):
            tags.discard(image.tag)
            if not tags:
                del self._repositories[repo_key]

        del self._images[digest]
        if digest in self._manifests:
            del self._manifests[digest]

    def get_image_manifest(self, digest: str) -> ImageManifest:
        """Get image manifest.

        Args:
            digest: Image digest.

        Returns:
            Image manifest.

        Raises:
            ImageNotFound: If image not found.
        """
        if digest not in self._manifests:
            raise ImageNotFound(digest)

        return self._manifests[digest]

    def garbage_collect(self) -> list[str]:
        """Remove unreferenced layers.

        Returns:
            List of removed layer digests.
        """
        removed = []

        # Find unreferenced layers
        referenced_digests = set()
        for image_digest in self._images:
            if image_digest in self._layer_refs:
                referenced_digests.update(self._layer_refs[image_digest])

        # Remove unreferenced
        for layer_digest in list(self._layer_refs.keys()):
            if not self._layer_refs[layer_digest]:
                removed.append(layer_digest)
                del self._layer_refs[layer_digest]

        return removed

    def get_registry_stats(self) -> dict:
        """Get registry statistics.

        Returns:
            Registry statistics dictionary.
        """
        total_size = sum(img.size_bytes for img in self._images.values())
        total_layers = sum(len(img.layers) for img in self._images.values())

        return {
            "image_count": len(self._images),
            "repository_count": len(self._repositories),
            "total_size_bytes": total_size,
            "total_layers": total_layers,
            "unreferenced_layers": sum(1 for refs in self._layer_refs.values() if not refs),
        }

    def search_images(self, query: str) -> list[dict]:
        """Search images in registry.

        Args:
            query: Search query.

        Returns:
            List of matching images.
        """
        results = []

        for repo_key, tags in self._repositories.items():
            if query.lower() in repo_key.lower():
                for tag in tags:
                    results.append(
                        {
                            "repository": repo_key,
                            "tag": tag,
                            "name": f"{repo_key}:{tag}",
                        }
                    )

        return results

    def _create_manifest(self, image: Image) -> ImageManifest:
        """Create image manifest from image.

        Args:
            image: Image to create manifest for.

        Returns:
            Image manifest.
        """
        layers = [
            {
                "digest": layer.digest,
                "size": layer.size,
            }
            for layer in image.layers
        ]

        config_data = f"{image.name}:{image.tag}".encode()
        config_digest = "sha256:" + hashlib.sha256(config_data).hexdigest()

        return ImageManifest(
            config_digest=config_digest,
            layers=layers,
        )

    def authenticate(self, registry_host: str) -> bool:
        """Authenticate with registry.

        Args:
            registry_host: Registry hostname.

        Returns:
            True if authenticated successfully.

        Raises:
            RegistryException: If authentication fails.
        """
        if registry_host not in self._credentials:
            raise RegistryException(f"No credentials for registry: {registry_host}")

        # Simulate authentication
        credentials = self._credentials[registry_host]
        if not credentials.username or not credentials.password:
            raise RegistryException("Invalid credentials")

        return True
