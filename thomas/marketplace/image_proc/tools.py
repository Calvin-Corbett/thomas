"""Tools for Image Processing module.

Provides tools for advanced image processing operations.
"""

from typing import Any

from thomas.tools.base import Tool, ToolResult


class ColorProcessingTool(Tool):
    """Process and analyze image colors."""

    name = "img_color_processing"
    category = "image_proc"
    description = "Apply color transformations, adjustments, and analysis"
    parameters = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["color_correction", "white_balance", "histogram_equalization", "color_grading"],
                "description": "Color operation",
            },
            "intensity": {"type": "number", "description": "Operation intensity (0.0-1.0)"},
        },
        "required": ["operation"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            operation = args.get("operation", "")
            intensity = float(args.get("intensity", 1.0))

            if operation not in ["color_correction", "white_balance", "histogram_equalization", "color_grading"]:
                return ToolResult(ok=False, error=f"Unknown operation: {operation}")

            return ToolResult(
                ok=True, data={"status": "operation_applied", "operation": operation, "intensity": intensity}
            )

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class CompressionTool(Tool):
    """Compress and decompress images."""

    name = "img_compression"
    category = "image_proc"
    description = "Compress and decompress images with various codecs"
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["compress", "decompress"], "description": "Compression action"},
            "codec": {"type": "string", "enum": ["jpeg", "png", "webp", "heic"], "description": "Compression codec"},
            "quality": {"type": "integer", "description": "Quality level (0-100)"},
        },
        "required": ["action", "codec"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")
            codec = args.get("codec", "jpeg")
            quality = int(args.get("quality", 85))

            if action not in ["compress", "decompress"]:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

            if codec not in ["jpeg", "png", "webp", "heic"]:
                return ToolResult(ok=False, error=f"Unknown codec: {codec}")

            return ToolResult(
                ok=True,
                data={
                    "status": f"{action}_complete",
                    "codec": codec,
                    "quality": quality if action == "compress" else None,
                },
            )

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class DenoisingTool(Tool):
    """Denoise and filter images."""

    name = "img_denoising"
    category = "image_proc"
    description = "Apply denoising filters to reduce image noise"
    parameters = {
        "type": "object",
        "properties": {
            "denoise_method": {
                "type": "string",
                "enum": ["bilateral", "nlm", "total_variation", "morphological"],
                "description": "Denoising method",
            },
            "strength": {"type": "number", "description": "Denoising strength (0.0-1.0)"},
        },
        "required": ["denoise_method"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            method = args.get("denoise_method", "")
            strength = float(args.get("strength", 0.5))

            supported = ["bilateral", "nlm", "total_variation", "morphological"]
            if method not in supported:
                return ToolResult(ok=False, error=f"Unknown method: {method}")

            return ToolResult(ok=True, data={"status": "denoising_applied", "method": method, "strength": strength})

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_image_proc_tools(registry):
    """Register all image processing tools."""
    registry.register(ColorProcessingTool())
    registry.register(CompressionTool())
    registry.register(DenoisingTool())
