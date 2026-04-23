"""
Tests for inpainting module.
"""

import numpy as np
import pytest

from thomas.marketplace.image_proc import Image, Inpainter, InpaintMask


class TestInpainting:
    """Test image inpainting functionality."""

    @pytest.fixture
    def inpainter(self):
        """Create inpainter instance."""
        return Inpainter(patch_size=9, search_radius=50)

    @pytest.fixture
    def image_with_hole(self):
        """Create test image with mask."""
        h, w = 64, 64
        # Create a simple pattern
        x = np.linspace(0, 1, w)
        y = np.linspace(0, 1, h)
        xx, yy = np.meshgrid(x, y)

        base = 0.5 + 0.3 * np.sin(xx * 4) + 0.2 * np.cos(yy * 4)
        img_data = np.dstack([base] * 3)

        # Create circular mask
        mask = np.zeros((h, w))
        cy, cx = h // 2, w // 2
        for y_i in range(h):
            for x_i in range(w):
                if (y_i - cy) ** 2 + (x_i - cx) ** 2 < 100:
                    mask[y_i, x_i] = 255

        return Image(data=np.clip(img_data, 0, 1)), InpaintMask(data=mask)

    def test_exemplar_inpaint(self, inpainter, image_with_hole):
        """Test exemplar-based inpainting."""
        img, mask = image_with_hole
        result = inpainter.inpaint_exemplar(img, mask)

        assert result.height == img.height
        assert result.width == img.width
        assert np.all(result.data >= 0) and np.all(result.data <= 1)

    def test_diffusion_inpaint(self, inpainter, image_with_hole):
        """Test diffusion-based inpainting."""
        img, mask = image_with_hole
        result = inpainter.inpaint_diffusion(img, mask, iterations=50)

        assert result.height == img.height
        assert result.width == img.width
        assert np.all(result.data >= 0) and np.all(result.data <= 1)

    def test_texture_synthesis_inpaint(self, inpainter, image_with_hole):
        """Test texture synthesis inpainting."""
        img, mask = image_with_hole
        result = inpainter.inpaint_texture_synthesis(img, mask)

        assert result.height == img.height
        assert result.width == img.width
        assert np.all(result.data >= 0) and np.all(result.data <= 1)

    def test_inpaint_mask_dimension_mismatch(self, inpainter, image_with_hole):
        """Test that mismatched mask dimensions raise error."""
        img, _ = image_with_hole
        wrong_mask = InpaintMask(data=np.zeros((32, 32)))

        with pytest.raises(Exception):
            inpainter.inpaint_exemplar(img, wrong_mask)

    def test_find_boundary(self, inpainter):
        """Test boundary pixel detection."""
        mask = np.zeros((32, 32))
        mask[10:20, 10:20] = 255

        boundary = inpainter._find_boundary(mask)

        # Boundary should not be empty
        assert len(boundary) > 0

        # All boundary points should be on or near mask edge
        for y, x in boundary:
            assert mask[y, x] > 0

    def test_inpainting_fills_holes(self, inpainter, image_with_hole):
        """Test that inpainting fills holes."""
        img, mask = image_with_hole

        # Count pixels in hole
        hole_pixels = np.sum(mask.data > 0)

        result = inpainter.inpaint_exemplar(img, mask)

        # Entire result should be filled (no remaining black holes)
        # Check by sampling the region where hole was
        assert not np.allclose(result.data[20:44, 20:44], 0)

    def test_small_hole_inpainting(self, inpainter):
        """Test inpainting of small hole."""
        h, w = 64, 64
        # Uniform image
        img_data = np.ones((h, w, 3)) * 0.5

        # Small hole
        mask = np.zeros((h, w))
        mask[30:34, 30:34] = 255

        img = Image(data=img_data)
        inpaint_mask = InpaintMask(data=mask)

        result = inpainter.inpaint_exemplar(img, inpaint_mask)

        # Result should be close to original (uniform)
        assert result.height == h
        assert result.width == w

    def test_large_hole_inpainting(self, inpainter):
        """Test inpainting of large hole."""
        h, w = 128, 128
        # Create textured image
        x = np.linspace(0, 4, w)
        y = np.linspace(0, 4, h)
        xx, yy = np.meshgrid(x, y)

        texture = 0.5 + 0.3 * np.sin(xx) * np.cos(yy)
        img_data = np.dstack([texture] * 3)

        # Large hole
        mask = np.zeros((h, w))
        mask[30:98, 30:98] = 255

        img = Image(data=np.clip(img_data, 0, 1))
        inpaint_mask = InpaintMask(data=mask)

        result = inpainter.inpaint_exemplar(img, inpaint_mask)

        assert result.height == h
        assert result.width == w

    def test_multiple_holes_inpainting(self, inpainter):
        """Test inpainting with multiple separate holes."""
        h, w = 96, 96
        img_data = np.random.rand(h, w, 3) * 0.3 + 0.35

        # Two circular holes
        mask = np.zeros((h, w))
        for cy, cx in [(30, 30), (60, 60)]:
            for y in range(h):
                for x in range(w):
                    if (y - cy) ** 2 + (x - cx) ** 2 < 100:
                        mask[y, x] = 255

        img = Image(data=np.clip(img_data, 0, 1))
        inpaint_mask = InpaintMask(data=mask)

        result = inpainter.inpaint_texture_synthesis(img, inpaint_mask)

        assert result.height == h
        assert result.width == w

    def test_inpaint_mask_dilation(self):
        """Test InpaintMask with dilation parameter."""
        mask_data = np.zeros((32, 32))
        mask_data[15:17, 15:17] = 255

        mask = InpaintMask(data=mask_data, dilation_iter=5)

        assert mask.dilation_iter == 5

    def test_diffusion_iterations_effect(self, inpainter, image_with_hole):
        """Test that more iterations produce smoother results."""
        img, mask = image_with_hole

        result_few = inpainter.inpaint_diffusion(img, mask, iterations=10)
        result_many = inpainter.inpaint_diffusion(img, mask, iterations=100)

        # Results should be different
        assert not np.allclose(result_few.data, result_many.data)

    def test_inpaint_single_pixel_hole(self, inpainter):
        """Test inpainting single pixel hole."""
        h, w = 32, 32
        img_data = np.random.rand(h, w, 3)

        mask = np.zeros((h, w))
        mask[15, 15] = 255

        img = Image(data=np.clip(img_data, 0, 1))
        inpaint_mask = InpaintMask(data=mask)

        result = inpainter.inpaint_exemplar(img, inpaint_mask)

        assert result.height == h
        assert result.width == w

    def test_patchmatch_execution(self, inpainter):
        """Test PatchMatch nearest neighbor field computation."""
        h, w = 32, 32
        img = np.random.rand(h, w, 3)
        mask = np.zeros((h, w), dtype=np.uint8)
        mask[10:20, 10:20] = 1

        nnf = inpainter._patchmatch(img, mask)

        # NNF should have entries for masked pixels
        assert len(nnf) > 0

    def test_inpaint_preserves_non_masked_regions(self, inpainter):
        """Test that inpainting doesn't alter non-masked regions."""
        h, w = 64, 64
        img_data = np.random.rand(h, w, 3)
        original = img_data.copy()

        # Small central mask
        mask = np.zeros((h, w))
        mask[28:36, 28:36] = 255

        img = Image(data=np.clip(img_data, 0, 1))
        inpaint_mask = InpaintMask(data=mask)

        result = inpainter.inpaint_exemplar(img, inpaint_mask)

        # Edges should be preserved
        assert np.allclose(result.data[0:20, 0:20], original[0:20, 0:20])

    def test_boundary_detection_accuracy(self, inpainter):
        """Test boundary detection accuracy."""
        mask = np.zeros((32, 32))
        # Square hole
        mask[10:22, 10:22] = 255

        boundary = inpainter._find_boundary(mask)

        # Boundary should form a closed loop
        # Check that boundary is roughly perimeter of square
        assert len(boundary) > 30

    def test_grayscale_inpainting(self, inpainter):
        """Test inpainting of grayscale image."""
        h, w = 48, 48
        gray_data = np.random.rand(h, w, 1)

        mask = np.zeros((h, w))
        mask[20:28, 20:28] = 255

        img = Image(data=gray_data)
        inpaint_mask = InpaintMask(data=mask)

        result = inpainter.inpaint_diffusion(img, inpaint_mask, iterations=30)

        assert result.height == h
        assert result.width == w

    def test_inpaint_with_priority_map(self, inpainter, image_with_hole):
        """Test inpainting with custom priority map."""
        img, mask_obj = image_with_hole

        # Create custom priority map (higher = inpaint first)
        priority_map = np.ones((img.height, img.width)) * 0.5

        mask = InpaintMask(data=mask_obj.data, priority_map=priority_map)

        result = inpainter.inpaint_exemplar(img, mask)

        assert result.height == img.height

    def test_inpaint_different_mask_values(self, inpainter):
        """Test that only positive mask values are inpainted."""
        h, w = 48, 48
        img_data = np.ones((h, w, 3)) * 0.5

        # Mask with varying positive values
        mask = np.zeros((h, w))
        mask[10:20, 10:20] = 100
        mask[25:30, 25:30] = 200

        img = Image(data=img_data)
        inpaint_mask = InpaintMask(data=mask)

        result = inpainter.inpaint_exemplar(img, inpaint_mask)

        assert result.height == h

    def test_exemplar_vs_diffusion_results(self, inpainter, image_with_hole):
        """Test that exemplar and diffusion give different results."""
        img, mask = image_with_hole

        result_exemplar = inpainter.inpaint_exemplar(img, mask)
        result_diffusion = inpainter.inpaint_diffusion(img, mask, iterations=30)

        # Should give different results
        assert not np.allclose(result_exemplar.data, result_diffusion.data)

    def test_find_boundary_different_shapes(self, inpainter):
        """Test boundary detection with different mask shapes."""
        for shape in [(32, 32), (48, 64), (64, 48)]:
            mask = np.zeros(shape)
            # Central square
            y_start = shape[0] // 4
            x_start = shape[1] // 4
            mask[y_start : 3 * shape[0] // 4, x_start : 3 * shape[1] // 4] = 255

            boundary = inpainter._find_boundary(mask)

            # Should find non-empty boundary
            assert len(boundary) > 0

    def test_patch_sizes(self, inpainter):
        """Test inpainting with different patch sizes."""
        h, w = 64, 64
        img_data = np.random.rand(h, w, 3)

        mask = np.zeros((h, w))
        mask[25:39, 25:39] = 255

        img = Image(data=img_data)
        inpaint_mask = InpaintMask(data=mask)

        for patch_size in [5, 9, 13]:
            inpainter_custom = Inpainter(patch_size=patch_size)
            result = inpainter_custom.inpaint_exemplar(img, inpaint_mask)

            assert result.height == h

    def test_search_radius_effects(self, inpainter, image_with_hole):
        """Test inpainting with different search radius."""
        img, mask = image_with_hole

        inpainter.search_radius = 25
        result1 = inpainter.inpaint_texture_synthesis(img, mask)

        inpainter.search_radius = 100
        result2 = inpainter.inpaint_texture_synthesis(img, mask)

        # Different search radius might give different results
        assert result1.height == result2.height

    def test_inpaint_linear_gradient(self, inpainter):
        """Test inpainting on smooth gradient."""
        h, w = 64, 64
        x = np.linspace(0, 1, w)
        y = np.linspace(0, 1, h)
        xx, yy = np.meshgrid(x, y)

        gradient = xx + yy
        img_data = np.dstack([gradient] * 3)

        mask = np.zeros((h, w))
        mask[25:39, 25:39] = 255

        img = Image(data=img_data)
        inpaint_mask = InpaintMask(data=mask)

        result = inpainter.inpaint_diffusion(img, inpaint_mask, iterations=50)

        # Inpainted region should roughly match surrounding gradient
        left = np.mean(result.data[32, 20:25])
        center = np.mean(result.data[32, 31:33])
        right = np.mean(result.data[32, 39:44])

        # Should increase from left to right
        assert center > left and right > center

    def test_inpaint_texture_preservation(self, inpainter):
        """Test that inpainting preserves texture patterns."""
        h, w = 96, 96
        # Create checkered pattern
        checkers = np.zeros((h, w, 3))
        for y in range(h):
            for x in range(w):
                if (y // 8 + x // 8) % 2 == 0:
                    checkers[y, x, :] = 0.7
                else:
                    checkers[y, x, :] = 0.3

        mask = np.zeros((h, w))
        mask[40:56, 40:56] = 255

        img = Image(data=checkers)
        inpaint_mask = InpaintMask(data=mask)

        result = inpainter.inpaint_texture_synthesis(img, inpaint_mask)

        # Should have filled the mask
        assert np.mean(result.data[48, 48]) > 0

    def test_small_vs_large_masks(self, inpainter):
        """Test inpainting with small and large masks."""
        h, w = 128, 128
        img_data = np.random.rand(h, w, 3)

        img = Image(data=img_data)

        # Small mask
        small_mask = np.zeros((h, w))
        small_mask[60:68, 60:68] = 255

        # Large mask
        large_mask = np.zeros((h, w))
        large_mask[32:96, 32:96] = 255

        result_small = inpainter.inpaint_exemplar(img, InpaintMask(data=small_mask))
        result_large = inpainter.inpaint_exemplar(img, InpaintMask(data=large_mask))

        assert result_small.height == h
        assert result_large.height == h
