"""Docker image management and Dockerfile parsing."""

from dataclasses import dataclass

from thomas.containers._exceptions import DockerfileParseError, ImageNotFound
from thomas.containers._types import Image, Layer


@dataclass
class DockerfileInstruction:
    """Parsed Dockerfile instruction."""

    name: str
    args: list[str]
    raw: str


class DockerfileParser:
    """Parser for Dockerfile format.

    Supports: FROM, RUN, COPY, ENV, EXPOSE, CMD, WORKDIR, ENTRYPOINT, ARG, LABEL
    """

    def __init__(self) -> None:
        """Initialize Dockerfile parser."""
        self.base_image: str | None = None
        self.base_tag: str = "latest"
        self.instructions: list[DockerfileInstruction] = []
        self.build_args: dict[str, str] = {}

    def parse(self, dockerfile_content: str) -> list[DockerfileInstruction]:
        """Parse Dockerfile content.

        Args:
            dockerfile_content: Dockerfile text content.

        Returns:
            List of parsed instructions.

        Raises:
            DockerfileParseError: If parsing fails.
        """
        self.instructions = []
        lines = dockerfile_content.split("\n")
        line_number = 0

        for line_number, line in enumerate(lines, 1):
            # Remove comments
            if "#" in line and not line.strip().startswith("#"):
                line = line[: line.index("#")]

            line = line.strip()
            if not line or line.startswith("#"):
                continue

            try:
                parts = line.split(None, 1)
                if not parts:
                    continue

                instruction = parts[0].upper()
                args_str = parts[1] if len(parts) > 1 else ""

                if instruction == "FROM":
                    self._parse_from(args_str)
                elif instruction == "RUN":
                    self._parse_run(args_str)
                elif instruction == "ENV":
                    self._parse_env(args_str)
                elif instruction == "WORKDIR":
                    self._parse_workdir(args_str)
                elif instruction == "EXPOSE":
                    self._parse_expose(args_str)
                elif instruction == "CMD":
                    self._parse_cmd(args_str)
                elif instruction == "ENTRYPOINT":
                    self._parse_entrypoint(args_str)
                elif instruction == "COPY":
                    self._parse_copy(args_str)
                elif instruction == "LABEL":
                    self._parse_label(args_str)
                elif instruction == "ARG":
                    self._parse_arg(args_str)
                else:
                    raise DockerfileParseError(line_number, f"Unknown instruction: {instruction}")

                self.instructions.append(
                    DockerfileInstruction(
                        name=instruction,
                        args=self._split_args(args_str),
                        raw=line,
                    )
                )

            except DockerfileParseError:
                raise
            except Exception as e:
                raise DockerfileParseError(line_number, str(e))

        if self.base_image is None:
            raise DockerfileParseError(1, "No FROM instruction found")

        return self.instructions

    def _parse_from(self, args: str) -> None:
        """Parse FROM instruction."""
        parts = args.split(":", 1)
        self.base_image = parts[0].strip()
        self.base_tag = parts[1].strip() if len(parts) > 1 else "latest"

    def _parse_run(self, args: str) -> None:
        """Parse RUN instruction."""
        if not args.strip():
            raise DockerfileParseError(0, "RUN requires arguments")

    def _parse_env(self, args: str) -> None:
        """Parse ENV instruction."""
        if "=" in args:
            key, value = args.split("=", 1)
            self.build_args[key.strip()] = value.strip()

    def _parse_workdir(self, args: str) -> None:
        """Parse WORKDIR instruction."""
        if not args.strip():
            raise DockerfileParseError(0, "WORKDIR requires a path")

    def _parse_expose(self, args: str) -> None:
        """Parse EXPOSE instruction."""
        if not args.strip():
            raise DockerfileParseError(0, "EXPOSE requires a port")

    def _parse_cmd(self, args: str) -> None:
        """Parse CMD instruction."""
        if not args.strip():
            raise DockerfileParseError(0, "CMD requires arguments")

    def _parse_entrypoint(self, args: str) -> None:
        """Parse ENTRYPOINT instruction."""
        if not args.strip():
            raise DockerfileParseError(0, "ENTRYPOINT requires arguments")

    def _parse_copy(self, args: str) -> None:
        """Parse COPY instruction."""
        if len(args.split()) < 2:
            raise DockerfileParseError(0, "COPY requires source and destination")

    def _parse_label(self, args: str) -> None:
        """Parse LABEL instruction."""
        if not args.strip():
            raise DockerfileParseError(0, "LABEL requires key=value pairs")

    def _parse_arg(self, args: str) -> None:
        """Parse ARG instruction."""
        if not args.strip():
            raise DockerfileParseError(0, "ARG requires argument name")

    @staticmethod
    def _split_args(args_str: str) -> list[str]:
        """Split instruction arguments, respecting quoted strings."""
        args = []
        current = ""
        in_quotes = False

        for char in args_str:
            if char in ('"', "'"):
                in_quotes = not in_quotes
            elif char == " " and not in_quotes:
                if current:
                    args.append(current)
                    current = ""
            else:
                current += char

        if current:
            args.append(current)

        return args


class ImageStore:
    """Manages Docker image storage and operations."""

    def __init__(self, storage_root: str = "/var/lib/containers/images") -> None:
        """Initialize image store.

        Args:
            storage_root: Root directory for image storage.
        """
        self.storage_root = storage_root
        self._images: dict[str, Image] = {}
        self._layer_cache: dict[str, Layer] = {}
        self._tag_index: dict[str, set[str]] = {}

    def build_from_dockerfile(
        self,
        dockerfile_content: str,
        name: str,
        tag: str = "latest",
        build_context: dict[str, bytes] | None = None,
        build_args: dict[str, str] | None = None,
    ) -> Image:
        """Build image from Dockerfile.

        Args:
            dockerfile_content: Dockerfile content.
            name: Image name.
            tag: Image tag.
            build_context: Build context files.
            build_args: Build-time arguments.

        Returns:
            Built image.

        Raises:
            DockerfileParseError: If Dockerfile is invalid.
        """
        parser = DockerfileParser()
        instructions = parser.parse(dockerfile_content)

        layers: list[Layer] = []
        env_vars: dict[str, str] = {}
        labels: dict[str, str] = {}
        exposed_ports: list[int] = []
        cmd: list[str] = []
        entrypoint: list[str] = []
        working_dir = "/app"

        # Process instructions to build layers
        for instruction in instructions:
            if instruction.name == "FROM":
                pass  # Base image already handled
            elif instruction.name == "RUN":
                layer_data = f"RUN {' '.join(instruction.args)}".encode()
                layer = Layer(
                    digest=Layer.compute_digest(layer_data),
                    size=len(layer_data),
                    data=layer_data,
                )
                layers.append(layer)
            elif instruction.name == "ENV":
                parts = instruction.args
                if len(parts) >= 2:
                    env_vars[parts[0]] = parts[1]
            elif instruction.name == "EXPOSE":
                try:
                    port = int(instruction.args[0])
                    exposed_ports.append(port)
                except (ValueError, IndexError):
                    pass
            elif instruction.name == "CMD":
                cmd = instruction.args
            elif instruction.name == "ENTRYPOINT":
                entrypoint = instruction.args
            elif instruction.name == "WORKDIR":
                working_dir = instruction.args[0] if instruction.args else "/app"
            elif instruction.name == "LABEL":
                for arg in instruction.args:
                    if "=" in arg:
                        key, value = arg.split("=", 1)
                        labels[key] = value

        image = Image(
            name=name,
            tag=tag,
            layers=layers,
            env=env_vars,
            labels=labels,
            exposed_ports=exposed_ports,
            cmd=cmd,
            entrypoint=entrypoint,
            working_dir=working_dir,
        )

        self._images[image.digest] = image
        self._register_tag(name, tag, image.digest)

        return image

    def create_image(
        self,
        name: str,
        tag: str = "latest",
        env: dict[str, str] | None = None,
        labels: dict[str, str] | None = None,
        cmd: list[str] | None = None,
        entrypoint: list[str] | None = None,
        exposed_ports: list[int] | None = None,
        working_dir: str = "/app",
    ) -> Image:
        """Create an image without Dockerfile.

        Args:
            name: Image name.
            tag: Image tag.
            env: Environment variables.
            labels: Image labels.
            cmd: Default command.
            entrypoint: Entrypoint.
            exposed_ports: Exposed ports.
            working_dir: Working directory.

        Returns:
            Created image.
        """
        # Create a single layer with metadata
        layer_data = f"{name}:{tag}".encode()
        layer = Layer(
            digest=Layer.compute_digest(layer_data),
            size=len(layer_data),
            data=layer_data,
        )

        image = Image(
            name=name,
            tag=tag,
            layers=[layer],
            env=env or {},
            labels=labels or {},
            cmd=cmd or [],
            entrypoint=entrypoint or [],
            exposed_ports=exposed_ports or [],
            working_dir=working_dir,
        )

        self._images[image.digest] = image
        self._register_tag(name, tag, image.digest)

        return image

    def get_image(self, name: str, tag: str = "latest") -> Image:
        """Get image by name and tag.

        Args:
            name: Image name.
            tag: Image tag.

        Returns:
            Image.

        Raises:
            ImageNotFound: If image not found.
        """
        key = f"{name}:{tag}"
        if key in self._tag_index:
            digest = list(self._tag_index[key])[0]
            return self._images[digest]

        raise ImageNotFound(key)

    def list_images(self, name_filter: str | None = None) -> list[Image]:
        """List all images.

        Args:
            name_filter: Filter by image name.

        Returns:
            List of images.
        """
        images = list(self._images.values())

        if name_filter:
            images = [img for img in images if name_filter in img.name]

        return sorted(images, key=lambda img: img.created_at, reverse=True)

    def remove_image(self, name: str, tag: str = "latest", force: bool = False) -> None:
        """Remove an image.

        Args:
            name: Image name.
            tag: Image tag.
            force: Force remove if in use.

        Raises:
            ImageNotFound: If image not found.
        """
        key = f"{name}:{tag}"
        try:
            image = self.get_image(name, tag)
        except ImageNotFound:
            raise ImageNotFound(key)

        if image.digest in self._images:
            del self._images[image.digest]

        if key in self._tag_index:
            self._tag_index[key].discard(image.digest)
            if not self._tag_index[key]:
                del self._tag_index[key]

    def tag_image(self, source_name: str, source_tag: str, target_name: str, target_tag: str) -> None:
        """Create a tag for an existing image.

        Args:
            source_name: Source image name.
            source_tag: Source image tag.
            target_name: Target image name.
            target_tag: Target image tag.

        Raises:
            ImageNotFound: If source image not found.
        """
        image = self.get_image(source_name, source_tag)
        self._register_tag(target_name, target_tag, image.digest)

    def get_image_history(self, name: str, tag: str = "latest") -> list[Layer]:
        """Get image layer history.

        Args:
            name: Image name.
            tag: Image tag.

        Returns:
            List of layers.

        Raises:
            ImageNotFound: If image not found.
        """
        image = self.get_image(name, tag)
        return image.layers

    def _register_tag(self, name: str, tag: str, digest: str) -> None:
        """Register a tag for an image digest.

        Args:
            name: Image name.
            tag: Image tag.
            digest: Image digest.
        """
        key = f"{name}:{tag}"
        if key not in self._tag_index:
            self._tag_index[key] = set()
        self._tag_index[key].add(digest)
