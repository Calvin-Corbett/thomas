"""Tests for soil module."""

from datetime import date

import pytest

from thomas.agriculture._types import Soil, SoilTexture
from thomas.agriculture.soil import (
    CationExchangeCapacity,
    OrganicMatterDecomposition,
    SoilHealthScore,
    SoilPHManagement,
    SoilTextureClassifier,
    SoilWaterProperties,
)


class TestSoilTextureClassifier:
    """Test soil texture classification."""

    def test_classify_loam(self) -> None:
        """Test loam classification."""
        texture = SoilTextureClassifier.classify_texture(
            sand_pct=40.0,
            silt_pct=40.0,
            clay_pct=20.0,
        )
        assert texture == SoilTexture.LOAM

    def test_classify_sandy_loam(self) -> None:
        """Test sandy loam classification."""
        texture = SoilTextureClassifier.classify_texture(
            sand_pct=65.0,
            silt_pct=20.0,
            clay_pct=15.0,
        )
        assert texture == SoilTexture.SANDY_LOAM

    def test_classify_clay(self) -> None:
        """Test clay classification."""
        texture = SoilTextureClassifier.classify_texture(
            sand_pct=10.0,
            silt_pct=20.0,
            clay_pct=70.0,
        )
        assert texture == SoilTexture.CLAY

    def test_invalid_percentages(self) -> None:
        """Test invalid texture percentages."""
        with pytest.raises(Exception):
            SoilTextureClassifier.classify_texture(
                sand_pct=50.0,
                silt_pct=30.0,
                clay_pct=10.0,
            )


class TestSoilWaterProperties:
    """Test soil water properties."""

    def test_field_capacity_loam(self) -> None:
        """Test field capacity for loam."""
        fc = SoilWaterProperties.field_capacity_in_per_ft(SoilTexture.LOAM)
        assert 1.4 < fc < 1.6

    def test_wilting_point_loam(self) -> None:
        """Test wilting point for loam."""
        wp = SoilWaterProperties.wilting_point_in_per_ft(SoilTexture.LOAM)
        assert 0.5 < wp < 0.8

    def test_available_water_capacity(self) -> None:
        """Test available water capacity calculation."""
        awc = SoilWaterProperties.available_water_capacity(
            SoilTexture.SILT_LOAM,
            soil_depth_in=12.0,
        )
        # Should be positive and reasonable
        assert 0.5 < awc < 2.0

    def test_sandy_vs_clay_water_holding(self) -> None:
        """Test water holding differences."""
        sand_fc = SoilWaterProperties.field_capacity_in_per_ft(SoilTexture.SAND)
        clay_fc = SoilWaterProperties.field_capacity_in_per_ft(SoilTexture.CLAY)

        # Clay should hold more water than sand
        assert clay_fc > sand_fc


class TestCationExchangeCapacity:
    """Test CEC interpretation."""

    def test_interpret_cec_sand_low(self) -> None:
        """Test low CEC for sand."""
        interpretation = CationExchangeCapacity.interpret_cec(2.0, SoilTexture.SAND)
        assert interpretation == "Low"

    def test_interpret_cec_loam_medium(self) -> None:
        """Test medium CEC for loam."""
        interpretation = CationExchangeCapacity.interpret_cec(12.0, SoilTexture.LOAM)
        assert interpretation == "Medium"

    def test_interpret_cec_clay_high(self) -> None:
        """Test high CEC for clay."""
        interpretation = CationExchangeCapacity.interpret_cec(25.0, SoilTexture.CLAY)
        assert interpretation == "High"


class TestSoilPHManagement:
    """Test soil pH management."""

    def test_interpret_ph_acidic(self) -> None:
        """Test acidic pH interpretation."""
        result = SoilPHManagement.interpret_ph(5.5)
        assert result == "Acidic"

    def test_interpret_ph_neutral(self) -> None:
        """Test neutral pH interpretation."""
        result = SoilPHManagement.interpret_ph(7.0)
        assert "Neutral" in result or "Slightly" in result

    def test_interpret_ph_alkaline(self) -> None:
        """Test alkaline pH interpretation."""
        result = SoilPHManagement.interpret_ph(8.5)
        assert "Alkaline" in result

    def test_lime_requirement_calculation(self) -> None:
        """Test lime requirement calculation."""
        lime_needed = SoilPHManagement.calculate_lime_requirement(
            current_ph=5.5,
            target_ph=6.5,
            cec_meq_per_100g=12.0,
            texture=SoilTexture.LOAM,
        )

        # Should be positive and reasonable
        assert 0 < lime_needed < 10

    def test_no_lime_needed(self) -> None:
        """Test no lime needed when pH is adequate."""
        lime_needed = SoilPHManagement.calculate_lime_requirement(
            current_ph=7.0,
            target_ph=6.5,
            cec_meq_per_100g=12.0,
            texture=SoilTexture.LOAM,
        )

        assert lime_needed == 0.0

    def test_lime_requirement_sand_vs_clay(self) -> None:
        """Test lime requirement varies by texture."""
        lime_sand = SoilPHManagement.calculate_lime_requirement(
            current_ph=5.5,
            target_ph=6.5,
            cec_meq_per_100g=2.0,
            texture=SoilTexture.SAND,
        )

        lime_clay = SoilPHManagement.calculate_lime_requirement(
            current_ph=5.5,
            target_ph=6.5,
            cec_meq_per_100g=20.0,
            texture=SoilTexture.CLAY,
        )

        # Clay needs more lime than sand
        assert lime_clay > lime_sand


class TestOrganicMatterDecomposition:
    """Test organic matter decomposition."""

    def test_annual_decomposition(self) -> None:
        """Test annual OM decomposition calculation."""
        loss = OrganicMatterDecomposition.estimate_annual_decomposition(
            organic_matter_pct=3.0,
            soil_depth_in=6.0,
        )

        # Should be positive
        assert loss > 0

    def test_residue_carbon_credit_corn_stover(self) -> None:
        """Test carbon credit from corn stover."""
        credit = OrganicMatterDecomposition.residue_carbon_credit(
            residue_type="corn_stover",
            residue_amount_tons_acre=3.0,
        )

        # Should be positive and reasonable
        assert 1000 < credit < 4000

    def test_residue_credit_zero_residue(self) -> None:
        """Test zero residue gives zero credit."""
        credit = OrganicMatterDecomposition.residue_carbon_credit(
            residue_type="corn_stover",
            residue_amount_tons_acre=0.0,
        )

        assert credit == 0.0


class TestSoilHealthScore:
    """Test soil health scoring."""

    def test_calculate_health_score_good_soil(self) -> None:
        """Test health score for good soil."""
        soil = Soil(
            soil_id="test1",
            field_id="field1",
            sand_pct=40.0,
            silt_pct=40.0,
            clay_pct=20.0,
            texture=SoilTexture.LOAM,
            ph=6.5,
            organic_matter_pct=4.0,
            test_date=date(2024, 1, 1),
            nitrate_n_ppm=25.0,
            phosphorus_lbs_acre=35.0,
            potassium_lbs_acre=180.0,
            calcium_lbs_acre=2000.0,
            magnesium_lbs_acre=300.0,
            sulfur_lbs_acre=15.0,
            cec_meq_per_100g=12.0,
        )

        score = SoilHealthScore.calculate_health_score(soil, recent_yield_bu_acre=150)
        assert 60 < score <= 100

    def test_calculate_health_score_poor_soil(self) -> None:
        """Test health score for poor soil."""
        soil = Soil(
            soil_id="test2",
            field_id="field2",
            sand_pct=85.0,
            silt_pct=10.0,
            clay_pct=5.0,
            texture=SoilTexture.SAND,
            ph=4.5,
            organic_matter_pct=1.0,
            test_date=date(2024, 1, 1),
            nitrate_n_ppm=5.0,
            phosphorus_lbs_acre=5.0,
            potassium_lbs_acre=50.0,
            calcium_lbs_acre=500.0,
            magnesium_lbs_acre=50.0,
            sulfur_lbs_acre=5.0,
            cec_meq_per_100g=1.0,
        )

        score = SoilHealthScore.calculate_health_score(soil, recent_yield_bu_acre=80)
        assert 0 <= score < 60

    def test_health_score_range(self) -> None:
        """Test health score is in valid range."""
        soil = Soil(
            soil_id="test3",
            field_id="field3",
            sand_pct=40.0,
            silt_pct=40.0,
            clay_pct=20.0,
            texture=SoilTexture.LOAM,
            ph=6.5,
            organic_matter_pct=3.0,
            test_date=date(2024, 1, 1),
            nitrate_n_ppm=20.0,
            phosphorus_lbs_acre=25.0,
            potassium_lbs_acre=150.0,
            calcium_lbs_acre=1500.0,
            magnesium_lbs_acre=250.0,
            sulfur_lbs_acre=10.0,
            cec_meq_per_100g=10.0,
        )

        score = SoilHealthScore.calculate_health_score(soil, recent_yield_bu_acre=120)
        assert 0 <= score <= 100
