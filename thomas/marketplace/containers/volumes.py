"""Container volume management."""

import os
from dataclasses import dataclass

from thomas.marketplace.containers._exceptions import InvalidConfiguration, VolumeNotFound
from thomas.marketplace.containers._types import Volume


@dataclass
class VolumeMount:
    """Volume mount information."""

    volume_name: str
    container_path: str
    read_only: bool = False
    container_id: str | None = None


class VolumeManager:
    """Manages container volumes and mounts."""

    def __init__(self, storage_root: str = "/var/lib/containers/volumes") -> None:
        """Initialize volume manager.

        Args:
            storage_root: Root directory for volume storage.
        """
        self.storage_root = storage_root
        self._volumes: dict[str, Volume] = {}
        self._mounts: dict[str, list[VolumeMount]] = {}
        self._bind_mounts: dict[str, str] = {}

    def create_volume(
        self,
        name: str,
        driver: str = "local",
        labels: dict[str, str] | None = None,
    ) -> Volume:
        """Create a named volume.

        Args:
            name: Volume name.
            driver: Storage driver.
            labels: Volume labels.

        Returns:
            Created volume.

        Raises:
            InvalidConfiguration: If volume already exists.
        """
        if name in self._volumes:
            raise InvalidConfiguration(f"Volume already exists: {name}")

        volume = Volume(
            name=name,
            driver=driver,
            labels=labels or {},
            mountpoint=os.path.join(self.storage_root, name),
        )

        self._volumes[name] = volume
        self._mounts[name] = []

        return volume

    def remove_volume(self, name: str, force: bool = False) -> None:
        """Remove a volume.

        Args:
            name: Volume name.
            force: Force remove even if in use.

        Raises:
            VolumeNotFound: If volume not found.
            InvalidConfiguration: If volume is in use and force=False.
        """
        if name not in self._volumes:
            raise VolumeNotFound(name)

        if not force and name in self._mounts and self._mounts[name]:
            raise InvalidConfiguration(f"Volume is in use: {name}")

        del self._volumes[name]
        if name in self._mounts:
            del self._mounts[name]

    def mount_volume(
        self,
        volume_name: str,
        container_id: str,
        container_path: str,
        read_only: bool = False,
    ) -> VolumeMount:
        """Mount a volume to a container.

        Args:
            volume_name: Volume name.
            container_id: Container ID.
            container_path: Path in container.
            read_only: Mount as read-only.

        Returns:
            Mount information.

        Raises:
            VolumeNotFound: If volume not found.
        """
        if volume_name not in self._volumes:
            raise VolumeNotFound(volume_name)

        mount = VolumeMount(
            volume_name=volume_name,
            container_path=container_path,
            read_only=read_only,
            container_id=container_id,
        )

        self._mounts[volume_name].append(mount)

        return mount

    def bind_mount(
        self,
        host_path: str,
        container_id: str,
        container_path: str,
        read_only: bool = False,
    ) -> VolumeMount:
        """Create a bind mount.

        Args:
            host_path: Path on host.
            container_id: Container ID.
            container_path: Path in container.
            read_only: Mount as read-only.

        Returns:
            Mount information.

        Raises:
            InvalidConfiguration: If host path does not exist.
        """
        if not os.path.exists(host_path):
            raise InvalidConfiguration(f"Host path does not exist: {host_path}")

        # Create synthetic volume for bind mount
        bind_id = f"bind_{container_id}_{len(self._bind_mounts)}"
        self._bind_mounts[bind_id] = host_path

        mount = VolumeMount(
            volume_name=bind_id,
            container_path=container_path,
            read_only=read_only,
            container_id=container_id,
        )

        return mount

    def unmount_volume(self, container_id: str, container_path: str) -> None:
        """Unmount a volume from a container.

        Args:
            container_id: Container ID.
            container_path: Path in container.
        """
        for volume_name, mounts in self._mounts.items():
            self._mounts[volume_name] = [
                m for m in mounts if not (m.container_id == container_id and m.container_path == container_path)
            ]

    def list_volumes(self, name_filter: str | None = None, label_filter: dict[str, str] | None = None) -> list[Volume]:
        """List volumes.

        Args:
            name_filter: Filter by volume name.
            label_filter: Filter by labels.

        Returns:
            List of volumes.
        """
        volumes = list(self._volumes.values())

        if name_filter:
            volumes = [v for v in volumes if name_filter in v.name]

        if label_filter:
            for key, value in label_filter.items():
                volumes = [v for v in volumes if v.labels.get(key) == value]

        return sorted(volumes, key=lambda v: v.created_at, reverse=True)

    def get_volume(self, name: str) -> Volume:
        """Get volume by name.

        Args:
            name: Volume name.

        Returns:
            Volume.

        Raises:
            VolumeNotFound: If volume not found.
        """
        if name not in self._volumes:
            raise VolumeNotFound(name)

        return self._volumes[name]

    def inspect_volume(self, name: str) -> dict:
        """Get detailed volume information.

        Args:
            name: Volume name.

        Returns:
            Volume details dictionary.

        Raises:
            VolumeNotFound: If volume not found.
        """
        volume = self.get_volume(name)

        containers = set()
        if name in self._mounts:
            for mount in self._mounts[name]:
                if mount.container_id:
                    containers.add(mount.container_id)

        return {
            "name": volume.name,
            "driver": volume.driver,
            "mountpoint": volume.mountpoint,
            "labels": volume.labels,
            "size_bytes": volume.size_bytes,
            "containers": list(containers),
            "created_at": volume.created_at.isoformat(),
        }

    def cleanup_dangling_volumes(self) -> list[str]:
        """Remove volumes not used by any container.

        Returns:
            List of removed volume names.
        """
        removed = []

        for name in list(self._volumes.keys()):
            if name not in self._mounts or not self._mounts[name]:
                self.remove_volume(name, force=True)
                removed.append(name)

        return removed

    def get_container_volumes(self, container_id: str) -> list[VolumeMount]:
        """Get volumes mounted to a container.

        Args:
            container_id: Container ID.

        Returns:
            List of volume mounts.
        """
        mounts = []

        for volume_name, mount_list in self._mounts.items():
            for mount in mount_list:
                if mount.container_id == container_id:
                    mounts.append(mount)

        for bind_id, host_path in self._bind_mounts.items():
            # This is simplified - in reality we'd track this better
            pass

        return mounts

    def calculate_volume_size(self, name: str) -> int:
        """Calculate volume size on disk.

        Args:
            name: Volume name.

        Returns:
            Size in bytes.

        Raises:
            VolumeNotFound: If volume not found.
        """
        volume = self.get_volume(name)

        try:
            total_size = 0
            for dirpath, dirnames, filenames in os.walk(volume.mountpoint):
                for filename in filenames:
                    filepath = os.path.join(dirpath, filename)
                    if os.path.exists(filepath):
                        total_size += os.path.getsize(filepath)
            return total_size
        except Exception:
            return 0
