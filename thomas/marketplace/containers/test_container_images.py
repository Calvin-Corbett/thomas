"""Tests for container image management."""

import pytest

from thomas.marketplace.containers._exceptions import DockerfileParseError, ImageNotFound
from thomas.marketplace.containers._types import Image, Layer
from thomas.marketplace.containers.images import DockerfileParser, ImageStore


@pytest.fixture
def image_store():
    """Create an image store instance."""
    return ImageStore()


class TestDockerfileParser:
    """Tests for Dockerfile parsing."""

    def test_parse_basic_dockerfile(self):
        """Test parsing basic Dockerfile."""
        dockerfile = """
FROM python:3.9
RUN pip install flask
ENV APP_ENV=production
WORKDIR /app
EXPOSE 8080
CMD ["python", "app.py"]
"""
        parser = DockerfileParser()
        instructions = parser.parse(dockerfile)

        assert len(instructions) > 0
        assert parser.base_image == "python"
        assert parser.base_tag == "3.9"

    def test_parse_dockerfile_with_labels(self):
        """Test parsing Dockerfile with labels."""
        dockerfile = """
FROM ubuntu:20.04
LABEL version="1.0" description="Test image"
"""
        parser = DockerfileParser()
        parser.parse(dockerfile)

        assert parser.base_image == "ubuntu"

    def test_parse_dockerfile_missing_from(self):
        """Test that Dockerfile without FROM fails."""
        dockerfile = "RUN echo hello"

        parser = DockerfileParser()
        with pytest.raises(DockerfileParseError):
            parser.parse(dockerfile)

    def test_parse_dockerfile_with_comments(self):
        """Test parsing Dockerfile with comments."""
        dockerfile = """
# This is a comment
FROM python:3.9
# Another comment
RUN pip install flask
"""
        parser = DockerfileParser()
        instructions = parser.parse(dockerfile)

        assert any(i.name == "RUN" for i in instructions)

    def test_parse_dockerfile_multiline_args(self):
        """Test parsing Dockerfile with arguments."""
        dockerfile = """
FROM python:3.9
RUN pip install \\
    flask \\
    requests
"""
        parser = DockerfileParser()
        instructions = parser.parse(dockerfile)

        assert any(i.name == "RUN" for i in instructions)


class TestImageStore:
    """Tests for image store."""

    def test_create_image(self, image_store):
        """Test creating an image."""
        image = image_store.create_image(
            "myapp",
            tag="1.0",
            env={"DEBUG": "false"},
            cmd=["python", "app.py"],
        )

        assert image.name == "myapp"
        assert image.tag == "1.0"
        assert image.env["DEBUG"] == "false"

    def test_get_image(self, image_store):
        """Test retrieving an image."""
        created = image_store.create_image("myapp", tag="1.0")
        retrieved = image_store.get_image("myapp", tag="1.0")

        assert retrieved.name == created.name
        assert retrieved.tag == created.tag

    def test_get_nonexistent_image(self, image_store):
        """Test that getting nonexistent image fails."""
        with pytest.raises(ImageNotFound):
            image_store.get_image("nonexistent")

    def test_list_images(self, image_store):
        """Test listing images."""
        image_store.create_image("app1")
        image_store.create_image("app2")

        images = image_store.list_images()

        assert len(images) == 2

    def test_list_images_with_filter(self, image_store):
        """Test listing images with name filter."""
        image_store.create_image("python-app")
        image_store.create_image("nodejs-app")

        images = image_store.list_images(name_filter="python")

        assert len(images) == 1
        assert images[0].name == "python-app"

    def test_tag_image(self, image_store):
        """Test tagging an image."""
        image_store.create_image("myapp", tag="1.0")
        image_store.tag_image("myapp", "1.0", "myapp", "latest")

        latest = image_store.get_image("myapp", tag="latest")
        assert latest.name == "myapp"

    def test_remove_image(self, image_store):
        """Test removing an image."""
        image_store.create_image("myapp")
        image_store.remove_image("myapp")

        with pytest.raises(ImageNotFound):
            image_store.get_image("myapp")

    def test_build_from_dockerfile(self, image_store):
        """Test building image from Dockerfile."""
        dockerfile = """
FROM python:3.9
RUN pip install flask
ENV APP_ENV=production
WORKDIR /app
CMD ["python", "app.py"]
"""
        image = image_store.build_from_dockerfile(dockerfile, "myapp", tag="1.0")

        assert image.name == "myapp"
        assert image.tag == "1.0"
        assert len(image.layers) > 0

    def test_image_digest(self, image_store):
        """Test image digest calculation."""
        image1 = image_store.create_image("myapp", tag="1.0")
        image2 = image_store.create_image("myapp", tag="2.0")

        assert image1.digest != image2.digest

    def test_image_size(self):
        """Test image size calculation."""
        layer1 = Layer.compute_digest(b"data1")
        layer2 = Layer.compute_digest(b"data2")

        image = Image(
            name="test",
            layers=[
                Layer(digest=layer1, size=1000),
                Layer(digest=layer2, size=2000),
            ],
        )

        assert image.size_bytes == 3000

    def test_image_layers(self, image_store):
        """Test image layer history."""
        dockerfile = """
FROM ubuntu:20.04
RUN apt-get update
RUN apt-get install -y python3
"""
        image_store.build_from_dockerfile(dockerfile, "myapp")
        layers = image_store.get_image_history("myapp")

        assert len(layers) > 0

    def test_image_full_name(self):
        """Test fully qualified image name."""
        image = Image(name="myapp", tag="1.0")
        assert image.full_name == "myapp:1.0"

    def test_image_with_labels(self, image_store):
        """Test image with labels."""
        labels = {"version": "1.0", "author": "test"}
        image = image_store.create_image("myapp", labels=labels)

        assert image.labels == labels

    def test_image_with_exposed_ports(self, image_store):
        """Test image with exposed ports."""
        image = image_store.create_image(
            "myapp",
            exposed_ports=[8080, 9090],
        )

        assert 8080 in image.exposed_ports
        assert 9090 in image.exposed_ports

    def test_image_with_volumes(self, image_store):
        """Test image with volume definitions."""
        image = image_store.create_image(
            "myapp",
        )
        image.volumes = ["/data", "/config"]

        assert "/data" in image.volumes

    def test_image_with_entrypoint(self, image_store):
        """Test image with entrypoint."""
        image = image_store.create_image(
            "myapp",
            entrypoint=["python", "-u"],
            cmd=["app.py"],
        )

        assert image.entrypoint == ["python", "-u"]
        assert image.cmd == ["app.py"]

    def test_image_with_working_dir(self, image_store):
        """Test image with working directory."""
        image = image_store.create_image(
            "myapp",
            working_dir="/app/src",
        )

        assert image.working_dir == "/app/src"

    def test_image_with_user(self, image_store):
        """Test image with user."""
        image = Image(
            name="myapp",
            user="appuser",
        )

        assert image.user == "appuser"

    def test_default_image_tag(self, image_store):
        """Test default image tag."""
        image = image_store.create_image("myapp")

        assert image.tag == "latest"
