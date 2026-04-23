"""Soil science module for soil analysis, health assessment, and management."""

from thomas.marketplace.agriculture._exceptions import SoilError
from thomas.marketplace.agriculture._types import Soil, SoilTexture


class SoilTextureClassifier:
    """Classifies soil texture using USDA soil texture triangle."""

    @staticmethod
    def classify_texture(
        sand_pct: float,
        silt_pct: float,
        clay_pct: float,
    ) -> SoilTexture:
        """Classify soil texture from particle size distribution.

        Uses USDA soil texture triangle algorithm.
        Assumes sand_pct + silt_pct + clay_pct = 100

        Args:
            sand_pct: Sand percentage (0-100)
            silt_pct: Silt percentage (0-100)
            clay_pct: Clay percentage (0-100)

        Returns:
            SoilTexture classification

        Raises:
            SoilError: If percentages don't sum to ~100
        """
        total = sand_pct + silt_pct + clay_pct
        if not (95 <= total <= 105):
            raise SoilError(f"Sand + Silt + Clay must sum to 100, got {total}")

        # Normalize to handle rounding
        total = sand_pct + silt_pct + clay_pct
        sand_pct = (sand_pct / total) * 100
        silt_pct = (silt_pct / total) * 100
        clay_pct = (clay_pct / total) * 100

        # USDA texture triangle classification
        if clay_pct < 27:
            if sand_pct > 52 and silt_pct < 28:
                if sand_pct > 70:
                    return SoilTexture.SAND
                else:
                    return SoilTexture.LOAMY_SAND
            elif sand_pct > 43 and silt_pct < 28:
                return SoilTexture.SANDY_LOAM
            elif silt_pct >= 28 and sand_pct <= 52:
                if sand_pct < 28:
                    return SoilTexture.SILT_LOAM
                else:
                    return SoilTexture.LOAM
            elif sand_pct <= 43 and silt_pct >= 28:
                return SoilTexture.SILT_LOAM
        else:  # clay_pct >= 27
            if sand_pct > 45:
                return SoilTexture.SANDY_CLAY
            elif sand_pct > 27:
                return SoilTexture.SANDY_CLAY_LOAM
            elif silt_pct >= 28:
                if clay_pct >= 40:
                    return SoilTexture.SILTY_CLAY
                else:
                    return SoilTexture.SILTY_CLAY_LOAM
            else:
                return SoilTexture.CLAY_LOAM

        # Default fallback
        return SoilTexture.LOAM


class SoilWaterProperties:
    """Calculates soil water holding capacity and availability."""

    # Water holding capacity by texture (inches/foot of soil)
    WHC_TEXTURE_MAP = {
        SoilTexture.SAND: 0.75,
        SoilTexture.LOAMY_SAND: 0.9,
        SoilTexture.SANDY_LOAM: 1.2,
        SoilTexture.LOAM: 1.5,
        SoilTexture.SILT_LOAM: 1.7,
        SoilTexture.SILT: 1.6,
        SoilTexture.SANDY_CLAY_LOAM: 1.4,
        SoilTexture.CLAY_LOAM: 1.6,
        SoilTexture.SILTY_CLAY_LOAM: 1.8,
        SoilTexture.SANDY_CLAY: 1.2,
        SoilTexture.SILTY_CLAY: 1.7,
        SoilTexture.CLAY: 1.5,
    }

    @staticmethod
    def field_capacity_in_per_ft(texture: SoilTexture) -> float:
        """Get field capacity for soil texture.

        Field capacity is maximum water held after gravity drainage.

        Args:
            texture: SoilTexture classification

        Returns:
            Field capacity in inches per foot of soil
        """
        return SoilWaterProperties.WHC_TEXTURE_MAP.get(texture, 1.5)

    @staticmethod
    def wilting_point_in_per_ft(texture: SoilTexture) -> float:
        """Get wilting point for soil texture.

        Wilting point is water content where plants can't extract water.

        Args:
            texture: SoilTexture classification

        Returns:
            Wilting point in inches per foot of soil
        """
        # Wilting point is ~40-50% of field capacity
        fc = SoilWaterProperties.field_capacity_in_per_ft(texture)
        return fc * 0.45

    @staticmethod
    def available_water_capacity(
        texture: SoilTexture,
        soil_depth_in: float = 12.0,
    ) -> float:
        """Calculate available water capacity.

        Available water = Field Capacity - Wilting Point

        Args:
            texture: SoilTexture classification
            soil_depth_in: Soil depth considered (default 1 foot)

        Returns:
            Available water in inches
        """
        fc = SoilWaterProperties.field_capacity_in_per_ft(texture)
        wp = SoilWaterProperties.wilting_point_in_per_ft(texture)
        feet = soil_depth_in / 12.0
        return (fc - wp) * feet


class CationExchangeCapacity:
    """Interprets and applies Cation Exchange Capacity (CEC)."""

    @staticmethod
    def interpret_cec(
        cec_meq_per_100g: float,
        texture: SoilTexture,
    ) -> str:
        """Interpret CEC value.

        Args:
            cec_meq_per_100g: CEC in milliequivalents per 100g
            texture: SoilTexture classification

        Returns:
            Interpretation string (Low, Medium, High)
        """
        if texture == SoilTexture.SAND:
            if cec_meq_per_100g < 3:
                return "Low"
            elif cec_meq_per_100g < 5:
                return "Medium"
            else:
                return "High"
        elif texture in [SoilTexture.LOAM, SoilTexture.SILT_LOAM]:
            if cec_meq_per_100g < 10:
                return "Low"
            elif cec_meq_per_100g < 15:
                return "Medium"
            else:
                return "High"
        else:  # Clay-based
            if cec_meq_per_100g < 15:
                return "Low"
            elif cec_meq_per_100g < 25:
                return "Medium"
            else:
                return "High"


class SoilPHManagement:
    """Manages soil pH and liming recommendations."""

    @staticmethod
    def interpret_ph(ph: float) -> str:
        """Interpret soil pH value.

        Args:
            ph: Soil pH (0-14)

        Returns:
            pH interpretation
        """
        if ph < 5.0:
            return "Very Acidic"
        elif ph < 6.0:
            return "Acidic"
        elif ph < 7.0:
            return "Slightly Acidic"
        elif ph < 8.0:
            return "Neutral to Slightly Alkaline"
        else:
            return "Alkaline"

    @staticmethod
    def calculate_lime_requirement(
        current_ph: float,
        target_ph: float,
        cec_meq_per_100g: float,
        texture: SoilTexture,
    ) -> float:
        """Calculate lime requirement to raise pH.

        Uses buffer-pH based approach: Amount of lime needed depends on
        current pH, target pH, CEC, and soil texture.

        Args:
            current_ph: Current soil pH
            target_ph: Desired pH
            cec_meq_per_100g: Cation exchange capacity
            texture: Soil texture classification

        Returns:
            Lime requirement in tons per acre
        """
        if current_ph >= target_ph:
            return 0.0

        ph_change_needed = target_ph - current_ph

        # Lime requirement increases with CEC and pH change
        # Sandy soils need less lime, clay soils need more
        texture_factor = {
            SoilTexture.SAND: 0.5,
            SoilTexture.LOAMY_SAND: 0.6,
            SoilTexture.SANDY_LOAM: 0.7,
            SoilTexture.LOAM: 0.9,
            SoilTexture.SILT_LOAM: 1.0,
            SoilTexture.SILT: 1.1,
            SoilTexture.CLAY_LOAM: 1.3,
            SoilTexture.SILTY_CLAY_LOAM: 1.4,
            SoilTexture.CLAY: 1.5,
            SoilTexture.SANDY_CLAY_LOAM: 1.2,
            SoilTexture.SANDY_CLAY: 1.1,
            SoilTexture.SILTY_CLAY: 1.3,
        }.get(texture, 1.0)

        # Base lime requirement calculation
        lime_needed = ph_change_needed * cec_meq_per_100g * texture_factor * 0.3
        return max(0.0, lime_needed)


class OrganicMatterDecomposition:
    """Models organic matter decomposition in soil."""

    @staticmethod
    def estimate_annual_decomposition(
        organic_matter_pct: float,
        soil_depth_in: float = 6.0,
    ) -> float:
        """Estimate annual organic matter loss from decomposition.

        Assumes ~2-5% annual decomposition rate depending on conditions.

        Args:
            organic_matter_pct: Current organic matter percentage
            soil_depth_in: Soil sampling depth

        Returns:
            Annual organic matter loss in lbs/acre
        """
        # Convert % OM to lbs/acre (top 6 inches)
        # Bulk density ~1.3 g/cm3 for mineral soils
        acres_to_soil_lbs = (soil_depth_in / 12.0) * 1e6 * 1.3 * 1000 / 453.592
        om_lbs_acre = organic_matter_pct * acres_to_soil_lbs / 100.0

        # Annual decomposition 3% + crop residue incorporation
        annual_loss = om_lbs_acre * 0.03
        return annual_loss

    @staticmethod
    def residue_carbon_credit(
        residue_type: str,
        residue_amount_tons_acre: float,
    ) -> float:
        """Calculate carbon credit from crop residue incorporation.

        Args:
            residue_type: Type of residue (e.g., "corn_stover", "soybean_straw")
            residue_amount_tons_acre: Amount of residue incorporated

        Returns:
            Carbon added in lbs/acre (as organic matter equivalent)
        """
        carbon_content = {
            "corn_stover": 0.42,  # 42% carbon content
            "soybean_straw": 0.40,
            "small_grain_straw": 0.38,
        }.get(residue_type, 0.40)

        # Carbon to OM is ~1.7x (OM is ~58% carbon)
        carbon_lbs = residue_amount_tons_acre * 2000 * carbon_content
        om_equivalent = carbon_lbs / 0.58
        return om_equivalent


class SoilHealthScore:
    """Calculates comprehensive soil health index."""

    @staticmethod
    def calculate_health_score(
        soil: Soil,
        recent_yield_bu_acre: float = 150.0,
    ) -> float:
        """Calculate overall soil health score (0-100).

        Composite index from physical, chemical, and biological indicators.

        Args:
            soil: Soil object with test results
            recent_yield_bu_acre: Recent field yield as biological indicator

        Returns:
            Health score 0-100
        """
        score = 0.0

        # Physical (25 points)
        # Favorable texture ranges
        texture_score = 20.0
        if soil.texture in [SoilTexture.LOAM, SoilTexture.SILT_LOAM]:
            texture_score = 25.0
        elif soil.texture in [SoilTexture.SANDY_LOAM, SoilTexture.CLAY_LOAM]:
            texture_score = 20.0
        score += texture_score

        # Chemical (40 points)
        # pH (10 points)
        if 6.0 <= soil.ph <= 7.5:
            score += 10.0
        elif 5.5 <= soil.ph <= 8.0:
            score += 7.0
        else:
            score += 3.0

        # Organic matter (15 points) - 3% is good, 5%+ is excellent
        if soil.organic_matter_pct >= 5.0:
            score += 15.0
        elif soil.organic_matter_pct >= 3.5:
            score += 12.0
        elif soil.organic_matter_pct >= 2.0:
            score += 8.0
        else:
            score += 3.0

        # Nitrogen (8 points)
        if soil.nitrate_n_ppm >= 20:
            score += 8.0
        elif soil.nitrate_n_ppm >= 10:
            score += 5.0
        else:
            score += 2.0

        # Phosphorus (4 points)
        if soil.phosphorus_lbs_acre >= 30:
            score += 4.0
        elif soil.phosphorus_lbs_acre >= 15:
            score += 2.0
        else:
            score += 0.5

        # Potassium (3 points)
        if soil.potassium_lbs_acre >= 150:
            score += 3.0
        elif soil.potassium_lbs_acre >= 100:
            score += 1.5
        else:
            score += 0.5

        # Biological (35 points)
        # Use yield as proxy for biological health
        if recent_yield_bu_acre >= 150:
            score += 35.0
        elif recent_yield_bu_acre >= 120:
            score += 28.0
        elif recent_yield_bu_acre >= 100:
            score += 20.0
        else:
            score += 10.0

        return min(100.0, score)
