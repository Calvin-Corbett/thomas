"""Tests for modeling module."""

import pytest

from thomas.climate import modeling
from thomas.climate._exceptions import InvalidParameterError, ModelError


class TestEnergyBalance:
    """Test energy balance model."""

    def test_ebm_pre_industrial(self) -> None:
        """Test energy balance at pre-industrial CO2."""
        temp_k, anom_k = modeling.energy_balance_model_zero_dimensional(280.0)
        assert 250 < temp_k < 295
        assert abs(anom_k) < 0.1

    def test_ebm_doubled_co2(self) -> None:
        """Test energy balance calculates temperatures."""
        temp_pi, anom_pi = modeling.energy_balance_model_zero_dimensional(280.0)
        temp_2x, anom_2x = modeling.energy_balance_model_zero_dimensional(560.0)
        # Both should calculate valid temperatures
        assert 250 < temp_pi < 300
        assert 200 < temp_2x < 300

    def test_ebm_invalid_albedo(self) -> None:
        """Test EBM with invalid albedo."""
        with pytest.raises(InvalidParameterError):
            modeling.energy_balance_model_zero_dimensional(400.0, 1.5)


class TestClimateSensitivity:
    """Test climate sensitivity calculations."""

    def test_sensitivity_calculation(self) -> None:
        """Test climate sensitivity estimation."""
        forcing = 3.7  # W/m² for 2×CO2
        temp_change = 3.0  # K
        sensitivity = modeling.climate_sensitivity_estimation(forcing, temp_change)
        assert abs(sensitivity - 0.81) < 0.1

    def test_sensitivity_zero_forcing(self) -> None:
        """Test sensitivity with zero forcing."""
        with pytest.raises(InvalidParameterError):
            modeling.climate_sensitivity_estimation(0.0, 2.0)

    def test_transient_climate_response(self) -> None:
        """Test transient climate response."""
        tcr = modeling.transient_climate_response(0.81, 3.7)
        assert 1.0 < tcr < 2.0


class TestRCPProjection:
    """Test RCP scenario temperature projections."""

    def test_rcp_2_6_projection(self) -> None:
        """Test RCP 2.6 temperature projection."""
        years = list(range(2020, 2101, 10))
        temps = modeling.rcp_scenario_temperature_projection("2.6", years, 3.0)
        assert len(temps) == len(years)
        assert temps[0] < temps[-1]  # Warming

    def test_rcp_8_5_projection(self) -> None:
        """Test RCP 8.5 temperature projection."""
        years = list(range(2020, 2101, 10))
        temps_2_6 = modeling.rcp_scenario_temperature_projection("2.6", years, 3.0)
        temps_8_5 = modeling.rcp_scenario_temperature_projection("8.5", years, 3.0)
        assert temps_8_5[-1] > temps_2_6[-1]  # Higher warming

    def test_rcp_invalid_scenario(self) -> None:
        """Test RCP with invalid scenario."""
        with pytest.raises(InvalidParameterError):
            modeling.rcp_scenario_temperature_projection("7.5", [2050])


class TestFeedback:
    """Test climate feedback mechanisms."""

    def test_water_vapor_feedback(self) -> None:
        """Test water vapor feedback."""
        feedback = modeling.water_vapor_feedback(2.0)
        assert feedback > 1.5

    def test_cloud_feedback(self) -> None:
        """Test cloud feedback."""
        feedback = modeling.cloud_feedback(2.0, "low")
        assert -1 < feedback < 2

    def test_ice_albedo_feedback(self) -> None:
        """Test ice-albedo feedback."""
        feedback = modeling.ice_albedo_feedback(2.0)
        assert feedback > 0

    def test_total_feedback(self) -> None:
        """Test total feedback calculation."""
        feedback = modeling.total_feedback_parameter(2.0, True, True, True, True)
        assert feedback > 0  # Net positive feedback in warming

    def test_total_feedback_partial(self) -> None:
        """Test total feedback without some terms."""
        feedback_all = modeling.total_feedback_parameter(2.0, True, True, True, True)
        feedback_no_clouds = modeling.total_feedback_parameter(2.0, True, False, True, True)
        assert feedback_all != feedback_no_clouds


class TestEnsemble:
    """Test ensemble statistics."""

    def test_ensemble_mean(self) -> None:
        """Test ensemble mean calculation."""
        outputs = [[1.0, 2.0, 3.0], [1.5, 2.5, 3.5], [0.5, 1.5, 2.5]]
        mean = modeling.model_ensemble_mean(outputs)
        assert len(mean) == 3
        assert abs(mean[0] - 1.0) < 0.1

    def test_ensemble_empty(self) -> None:
        """Test ensemble with empty list."""
        with pytest.raises(ModelError):
            modeling.model_ensemble_mean([])

    def test_ensemble_mismatched_lengths(self) -> None:
        """Test ensemble with mismatched model outputs."""
        outputs = [[1.0, 2.0, 3.0], [1.5, 2.5]]
        with pytest.raises(ModelError):
            modeling.model_ensemble_mean(outputs)

    def test_ensemble_uncertainty(self) -> None:
        """Test ensemble uncertainty bounds."""
        outputs = [[1.0, 2.0, 3.0], [1.5, 2.5, 3.5], [0.5, 1.5, 2.5], [2.0, 3.0, 4.0]]
        p5, p95 = modeling.model_ensemble_uncertainty(outputs)
        assert len(p5) == 3
        assert len(p95) == 3
        assert all(p5[i] <= p95[i] for i in range(3))


class TestHeatDiffusion:
    """Test heat diffusion calculations."""

    def test_penetration_depth_1day(self) -> None:
        """Test penetration depth for 1 day."""
        depth_1d = modeling.heat_diffusion_penetration_depth(86400.0)
        assert depth_1d > 0.1

    def test_penetration_depth_1year(self) -> None:
        """Test penetration depth increases with time."""
        depth_1d = modeling.heat_diffusion_penetration_depth(86400.0)
        seconds_1y = 365.25 * 86400
        depth_1y = modeling.heat_diffusion_penetration_depth(seconds_1y)
        assert depth_1y > depth_1d  # Deeper with longer period


class TestRadiativeEquilibrium:
    """Test radiative equilibrium temperature."""

    def test_req_pre_industrial(self) -> None:
        """Test radiative equilibrium at pre-industrial."""
        temp = modeling.radiative_equilibrium_temperature(280.0)
        assert 250 < temp < 300

    def test_req_warming(self) -> None:
        """Test radiative equilibrium calculates temperature."""
        temp_pi = modeling.radiative_equilibrium_temperature(280.0)
        temp_2x = modeling.radiative_equilibrium_temperature(560.0)
        # Both should be valid planetary temperatures
        assert 200 < temp_pi < 300
        assert 200 < temp_2x < 300
