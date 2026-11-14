"""The desktop-plugin surface other modules import.

Phase 3.5 put one of these names on the kernel: ``install_plugin_bundle_bytes``
resolves the ``desktop_plugin_installer`` service and calls it, instead of being
a straight re-export of the runtime function. Every caller that already imports
it from here — the marketplace import route among them — therefore installs
through a provider that can be replaced while Thomas runs, with no change at the
call site and none in behaviour while the default provider is the one mounted.

Importing ``install_plugin_bundle_bytes`` from ``desktop_plugins_runtime``
directly still bypasses the seam. That is where the implementation lives and
where the runtime's own recursive dependency installs call it; the facade is the
seam, and this is the difference between the two.
"""

from __future__ import annotations

from typing import Any

from thomas.server.desktop_plugins_manifest import (
    DesktopPluginManifest,
    build_plugin_bundle_bytes,
    compute_plugin_bundle_sha256,
    load_bundled_desktop_plugin_manifest,
    load_desktop_plugin_manifest_from_data,
    maybe_load_desktop_plugin_manifest,
    resolve_bundled_plugin_dir,
)
from thomas.server.desktop_plugins_runtime import (
    build_plugin_install_deep_link,
    create_official_hosted_manifest,
    create_plugin_store_api_key_file,
    get_installed_plugin,
    get_or_create_plugin_store_api_key,
    install_bundled_plugin,
    install_plugin_bundle_file,
    install_plugin_from_store,
    is_plugin_enabled,
    list_installed_plugins,
    parse_plugin_install_deep_link,
    resolve_installed_plugin_asset,
    set_installed_plugin_enabled,
    uninstall_plugin,
)


def install_plugin_bundle_bytes(
    config: Any,
    bundle_bytes: bytes,
    *,
    source: dict[str, Any],
    require_signature: bool = True,
    **kwargs: Any,
) -> dict[str, Any]:
    """Install a desktop plugin bundle through the kernel's installer service.

    Same arguments, same return, same exceptions as the runtime function it
    resolves to. The service is the point: mount a different provider and this
    call site follows it, without being edited or restarted.
    """
    from thomas.server.plugin_systems_kernel import desktop_plugin_installer

    return desktop_plugin_installer().install(
        config,
        bundle_bytes,
        source=source,
        require_signature=require_signature,
        **kwargs,
    )


__all__ = [
    "DesktopPluginManifest",
    "build_plugin_bundle_bytes",
    "build_plugin_install_deep_link",
    "compute_plugin_bundle_sha256",
    "create_official_hosted_manifest",
    "create_plugin_store_api_key_file",
    "get_installed_plugin",
    "get_or_create_plugin_store_api_key",
    "install_bundled_plugin",
    "install_plugin_bundle_bytes",
    "install_plugin_bundle_file",
    "install_plugin_from_store",
    "is_plugin_enabled",
    "list_installed_plugins",
    "load_bundled_desktop_plugin_manifest",
    "load_desktop_plugin_manifest_from_data",
    "maybe_load_desktop_plugin_manifest",
    "parse_plugin_install_deep_link",
    "resolve_bundled_plugin_dir",
    "resolve_installed_plugin_asset",
    "set_installed_plugin_enabled",
    "uninstall_plugin",
]
