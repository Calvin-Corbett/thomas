"""Tests for carbon module."""

import math

import pytest

from thomas.climate import carbon
from thomas.climate._exceptions import ClimateDataError, InvalidParameterError


class TestCarbonBudget:
    """Test carbon budget calculations."""

    def test_carbon_budget_baseline(self) -> None:
        """Test carbon budget calculation."""
        budget = carbon.carbon_budget(2.0, 37.0, 0.45)
        assert budget["total_emissions"] == 37.0
        assert budget["ocean_sink"] > 0
        assert budget["land_sink"] > 0

    def test_carbon_budget_zero_emissions(self) -> None:
        """Test carbon budget with zero emissions."""
        budget = carbon.carbon_budget(0.0, 0.0, 0.45)
        assert budget["total_emissions"] == 0.0


class TestEmissionFactors:
    """Test emission factor calculations."""

    def test_coal_emission(self) -> None:
        """Test coal emissions."""
        emissions = carbon.emission_factor_calculation("coal", 1000.0)  # 1 ton coal
        assert emissions > 2000.0

    def test_oil_emission(self) -> None:
        """Test oil emissions."""
        emissions = carbon.emission_factor_calculation("oil", 100.0)  # 100 liters
        assert emissions > 300.0

    def test_natural_gas_emission(self) -> None:
        """Test natural gas emissions."""
        emissions = carbon.emission_factor_calculation("natural_gas", 50.0)  # 50 m³
        assert emissions > 90.0

    def test_unknown_fuel_type(self) -> None:
        """Test unknown fuel type."""
        with pytest.raises(InvalidParameterError):
            carbon.emission_factor_calculation("unknown_fuel", 100.0)


class TestCarbonFootprint:
    """Test carbon footprint calculations."""

    def test_personal_carbon_footprint(self) -> None:
        """Test personal carbon footprint."""
        footprint = carbon.carbon_footprint_personal(5000.0, 50.0, 10000.0, 8.0, 5000.0)
        assert footprint > 0

    def test_organizational_footprint(self) -> None:
        """Test organizational carbon footprint."""
        footprint = carbon.carbon_footprint_organizational(1000, 0.5, 0.3, 1.0)
        assert footprint["total"] > 0
        assert footprint["per_employee_kg"] > 0

    def test_organizational_zero_employees(self) -> None:
        """Test organizational footprint with zero employees."""
        footprint = carbon.carbon_footprint_organizational(0, 0.5, 0.3, 0.0)
        assert footprint["per_employee_kg"] == 0


class TestKeelingCurve:
    """Test Keeling curve fitting."""

    def test_keeling_curve_fit(self) -> None:
        """Test Keeling curve fitting."""
        years = [2000 + i for i in range(20)]
        co2 = [370 + i * 2.0 + (5 * math.sin(i * 0.5)) for i in range(20)]
        slope, amplitude, fitted = carbon.keeling_curve_fitting(years, co2)
        assert slope > 1.5
        assert amplitude > 0
        assert len(fitted) == len(co2)

    def test_keeling_insufficient_data(self) -> None:
        """Test Keeling curve with insufficient data."""
        with pytest.raises(ClimateDataError):
            carbon.keeling_curve_fitting([2000], [370])


class TestRadiativeForcing:
    """Test radiative forcing calculations."""

    def test_forcing_co2_doubled(self) -> None:
        """Test forcing for doubled CO2."""
        forcing = carbon.radiative_forcing_co2(560.0, 280.0)
        assert 3.5 < forcing < 4.0

    def test_forcing_co2_baseline(self) -> None:
        """Test forcing at baseline."""
        forcing = carbon.radiative_forcing_co2(280.0, 280.0)
        assert abs(forcing) < 0.01

    def test_forcing_invalid_co2(self) -> None:
        """Test forcing with invalid CO2."""
        with pytest.raises(InvalidParameterError):
            carbon.radiative_forcing_co2(-100.0, 280.0)

    def test_total_ghg_forcing(self) -> None:
        """Test total GHG forcing calculation."""
        forcing = carbon.radiative_forcing_ghg(415.0, 1900.0, 335.0)
        assert forcing["total"] > 0
        assert forcing["co2"] > 0
        assert forcing["ch4"] > 0
        assert forcing["n2o"] > 0


class TestCarbonOffset:
    """Test carbon offset verification."""

    def test_offset_gold_standard(self) -> None:
        """Test offset with gold standard."""
        result = carbon.carbon_offset_verification(100.0, 1000.0, "gold")
        assert result["verified_offset"] == 95.0
        assert result["credibility_factor"] == 0.95

    def test_offset_vcs_standard(self) -> None:
        """Test offset with VCS standard."""
        result = carbon.carbon_offset_verification(100.0, 1000.0, "vcs")
        assert result["verified_offset"] == 90.0

    def test_offset_default_standard(self) -> None:
        """Test offset with default standard."""
        result = carbon.carbon_offset_verification(100.0, 1000.0, "default")
        assert result["verified_offset"] == 80.0

    def test_offset_invalid_standard(self) -> None:
        """Test offset with invalid standard."""
        with pytest.raises(InvalidParameterError):
            carbon.carbon_offset_verification(100.0, 1000.0, "invalid")


class TestEmissionReduction:
    """Test emission reduction scenarios."""

    def test_emission_reduction_pathway(self) -> None:
        """Test emission reduction pathway."""
        pathway = carbon.emission_reduction_scenario(50.0, 2050, 2.0, 1.2)
        assert len(pathway) == 31  # 2020-2050
        assert pathway[0][1] == 50.0  # Start at baseline
        assert pathway[-1][1] < 50.0  # End at lower level

    def test_emission_reduction_zero_rate(self) -> None:
        """Test with zero reduction rate."""
        pathway = carbon.emission_reduction_scenario(50.0, 2050, 0.0)
        assert pathway[0][1] == pathway[-1][1]  # No change


class TestRCPProjection:
    """Test RCP scenario projections."""

    def test_rcp_2_6_projection(self) -> None:
        """Test RCP 2.6 CO2 projection."""
        years = list(range(2020, 2101, 10))
        co2 = carbon.rcp_scenario_co2_projection("2.6", years)
        assert len(co2) == len(years)
        assert co2[0] > 400  # Start at ~410 ppm
        assert co2[-1] < 430  # End below 430 ppm

    def test_rcp_4_5_projection(self) -> None:
        """Test RCP 4.5 CO2 projection."""
        years = list(range(2020, 2101, 10))
        co2 = carbon.rcp_scenario_co2_projection("4.5", years)
        assert co2[-1] > 500

    def test_rcp_8_5_projection(self) -> None:
        """Test RCP 8.5 CO2 projection."""
        years = list(range(2020, 2101, 10))
        co2 = carbon.rcp_scenario_co2_projection("8.5", years)
        assert co2[-1] > 800

    def test_rcp_invalid_scenario(self) -> None:
        """Test invalid RCP scenario."""
        with pytest.raises(InvalidParameterError):
            carbon.rcp_scenario_co2_projection("7.5", [2050])

    def test_rcp_projection_past_and_future(self) -> None:
        """Test RCP projection including past years."""
        years = [2010, 2020, 2050, 2100]
        co2 = carbon.rcp_scenario_co2_projection("4.5", years)
        assert len(co2) == 4
        assert all(c > 0 for c in co2)
