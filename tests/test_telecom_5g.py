"""
Tests for 5G features module.
"""

import pytest

from thomas.marketplace.telecom.five_g import (
    BeamManager,
    EdgeComputeOptimizer,
    MassiveMIMO,
    MMWavePropagation,
    NetworkSlicingManager,
)


class TestNetworkSlicingManager:
    """Test network slicing."""

    def test_create_slice(self) -> None:
        """Test creating network slice."""
        manager = NetworkSlicingManager()
        slice_obj = manager.create_slice(
            name="eMBB Slice",
            slice_type="eMBB",
            latency_sla_ms=50.0,
            throughput_sla_gbps=1.0,
            reliability_sla_percent=99.9,
        )
        assert slice_obj.name == "eMBB Slice"
        assert slice_obj.slice_type == "eMBB"

    def test_allocate_resources_to_slice(self) -> None:
        """Test allocating resources to slice."""
        manager = NetworkSlicingManager(total_spectrum_mhz=2000.0)
        slice_obj = manager.create_slice("Test Slice", "URLLC", 10.0, 0.1, 99.99)

        success = manager.allocate_resources_to_slice(
            slice_obj.id,
            spectrum_mhz=200.0,
            compute_percent=25.0,
        )
        assert success is True

    def test_allocate_more_than_available(self) -> None:
        """Test allocating more resources than available."""
        manager = NetworkSlicingManager(total_spectrum_mhz=200.0)
        slice_obj = manager.create_slice("Test Slice", "mMTC", 100.0, 0.01, 90.0)

        success = manager.allocate_resources_to_slice(
            slice_obj.id,
            spectrum_mhz=300.0,
            compute_percent=50.0,
        )
        assert success is False

    def test_assign_subscriber_to_slice(self) -> None:
        """Test assigning subscriber to slice."""
        manager = NetworkSlicingManager()
        slice_obj = manager.create_slice("Test Slice", "eMBB", 50.0, 1.0, 99.9)

        success = manager.assign_subscriber_to_slice("1234567890", slice_obj.id)
        assert success is True
        assert "1234567890" in slice_obj.subscribers

    def test_get_slice_utilization(self) -> None:
        """Test slice utilization calculation."""
        manager = NetworkSlicingManager()
        slice_obj = manager.create_slice("Test Slice", "eMBB", 50.0, 1.0, 99.9)

        manager.allocate_resources_to_slice(
            slice_obj.id,
            spectrum_mhz=100.0,
            compute_percent=50.0,
        )

        utilization = manager.get_slice_utilization(slice_obj.id)
        assert utilization > 0


class TestMassiveMIMO:
    """Test massive MIMO."""

    def test_estimate_channel_capacity(self) -> None:
        """Test channel capacity estimation."""
        mimo = MassiveMIMO(num_antennas=64, frequency_mhz=3500.0)
        capacity = mimo.estimate_channel_capacity(
            snr_db=10.0,
            num_users=4,
            bandwidth_mhz=100.0,
        )
        assert capacity > 0

    def test_mimo_capacity_vs_siso(self) -> None:
        """Test MIMO provides more capacity than SISO."""
        bandwidth_mhz = 100.0
        snr_db = 10.0

        mimo = MassiveMIMO(num_antennas=64)
        mimo_capacity = mimo.estimate_channel_capacity(snr_db, num_users=1, bandwidth_mhz=bandwidth_mhz)

        mimo_single = MassiveMIMO(num_antennas=1)
        siso_capacity = mimo_single.estimate_channel_capacity(snr_db, num_users=1, bandwidth_mhz=bandwidth_mhz)

        assert mimo_capacity > siso_capacity

    def test_channel_estimation_overhead(self) -> None:
        """Test channel estimation overhead."""
        mimo = MassiveMIMO(num_antennas=64)
        overhead = mimo.calculate_channel_estimation_overhead(pilot_sequence_length=128)
        assert 0 <= overhead <= 50.0

    def test_precoding_gain(self) -> None:
        """Test precoding gain calculation."""
        mimo = MassiveMIMO(num_antennas=64)
        gain = mimo.calculate_precoding_gain(num_users=4, user_snr_db=10.0)
        assert isinstance(gain, float)


class TestBeamManager:
    """Test beam management."""

    def test_calculate_beam_gain(self) -> None:
        """Test beam gain at different angles."""
        beam_mgr = BeamManager(num_beams=64, beam_width_degrees=5.6)

        gain_center = beam_mgr.calculate_beam_gain(angle_from_boresight=0.0)
        gain_edge = beam_mgr.calculate_beam_gain(angle_from_boresight=2.8)
        gain_far = beam_mgr.calculate_beam_gain(angle_from_boresight=10.0)

        assert gain_center > gain_edge
        assert gain_edge > gain_far

    def test_perform_beam_sweeping(self) -> None:
        """Test beam sweeping."""
        beam_mgr = BeamManager(num_beams=64)
        signal_strengths = {i: -80.0 - i * 0.5 for i in range(64)}
        signal_strengths[32] = -70.0  # Peak at beam 32

        best_beam = beam_mgr.perform_beam_sweeping(signal_strengths)
        assert best_beam == 32

    def test_beam_tracking_overhead(self) -> None:
        """Test beam tracking overhead."""
        beam_mgr = BeamManager()
        overhead = beam_mgr.estimate_beam_tracking_overhead(velocity_kmh=50.0)
        assert 0 <= overhead <= 20.0

    def test_narrow_beam_search(self) -> None:
        """Test narrow beam search."""
        beam_mgr = BeamManager(num_beams=64)
        signal_strengths = {i: -90.0 - (i - 32) ** 2 / 50 for i in range(64)}

        candidates = beam_mgr.narrow_beam_search(signal_strengths, num_best_beams=4)
        assert len(candidates) > 0
        assert all(0 <= b < 64 for b in candidates)


class TestMMWavePropagation:
    """Test mmWave propagation."""

    def test_path_loss_los(self) -> None:
        """Test line-of-sight path loss."""
        mmwave = MMWavePropagation(frequency_ghz=28.0)
        path_loss = mmwave.calculate_path_loss_los(distance_m=100.0)
        assert path_loss > 0

    def test_path_loss_nlos(self) -> None:
        """Test non-line-of-sight path loss."""
        mmwave = MMWavePropagation(frequency_ghz=28.0)
        los_loss = mmwave.calculate_path_loss_los(distance_m=100.0)
        nlos_loss = mmwave.calculate_path_loss_nlos(distance_m=100.0, num_obstacles=1)
        assert nlos_loss > los_loss

    def test_coverage_range_estimation(self) -> None:
        """Test coverage range estimation."""
        mmwave = MMWavePropagation(frequency_ghz=28.0)
        coverage_range = mmwave.estimate_coverage_range(
            tx_power_dbm=20.0,
            sensitivity_dbm=-70.0,
            antenna_gain_dbi=10.0,
        )
        assert coverage_range > 0
        assert coverage_range < 1000  # mmWave has limited range

    def test_frequency_dependency(self) -> None:
        """Test that higher frequency has more path loss."""
        mmwave_28 = MMWavePropagation(frequency_ghz=28.0)
        mmwave_73 = MMWavePropagation(frequency_ghz=73.0)

        loss_28 = mmwave_28.calculate_path_loss_los(distance_m=100.0)
        loss_73 = mmwave_73.calculate_path_loss_los(distance_m=100.0)

        assert loss_73 > loss_28


class TestEdgeComputeOptimizer:
    """Test edge computing optimization."""

    def test_add_mec_location(self) -> None:
        """Test adding MEC location."""
        optimizer = EdgeComputeOptimizer()
        optimizer.add_mec_location(
            location_id="MEC-1",
            lat=0.0,
            lon=0.0,
            compute_capacity_percent=80.0,
        )
        assert "MEC-1" in optimizer.mec_locations

    def test_calculate_edge_latency(self) -> None:
        """Test edge latency calculation."""
        optimizer = EdgeComputeOptimizer()
        latency = optimizer.calculate_edge_latency(
            distance_km=10.0,
            processing_time_ms=5.0,
        )
        assert latency > 5.0  # Should include propagation

    def test_select_optimal_mec(self) -> None:
        """Test optimal MEC selection."""
        optimizer = EdgeComputeOptimizer()
        optimizer.add_mec_location("MEC-1", 0.0, 0.0, 80.0)
        optimizer.add_mec_location("MEC-2", 10.0, 10.0, 80.0)

        selected = optimizer.select_optimal_mec(
            subscriber_lat=0.5,
            subscriber_lon=0.5,
            latency_requirement_ms=100.0,
        )
        assert selected in ["MEC-1", "MEC-2", None]

    def test_urllc_latency_budget(self) -> None:
        """Test URLLC latency budget breakdown."""
        optimizer = EdgeComputeOptimizer()
        budget = optimizer.estimate_urllc_latency_budget()

        assert "total" in budget
        assert budget["total"] <= 5.0  # URLLC max latency
        assert sum(budget[k] for k in budget if k != "total") <= budget["total"]


class Test5GIntegration:
    """Integration tests for 5G features."""

    def test_network_slicing_with_mimo(self) -> None:
        """Test network slicing with massive MIMO."""
        slicing_mgr = NetworkSlicingManager(total_spectrum_mhz=400.0)
        embb_slice = slicing_mgr.create_slice(
            name="eMBB", slice_type="eMBB", latency_sla_ms=50.0, throughput_sla_gbps=1.0, reliability_sla_percent=99.9
        )

        urllc_slice = slicing_mgr.create_slice(
            name="URLLC",
            slice_type="URLLC",
            latency_sla_ms=1.0,
            throughput_sla_gbps=0.1,
            reliability_sla_percent=99.999,
        )

        slicing_mgr.allocate_resources_to_slice(embb_slice.id, spectrum_mhz=200.0, compute_percent=60.0)
        slicing_mgr.allocate_resources_to_slice(urllc_slice.id, spectrum_mhz=100.0, compute_percent=30.0)

        mimo = MassiveMIMO(num_antennas=64)
        embb_capacity = mimo.estimate_channel_capacity(10.0, 1, 200.0)

        assert embb_capacity > 0

    def test_mmwave_with_beam_management(self) -> None:
        """Test mmWave with beam management."""
        mmwave = MMWavePropagation(frequency_ghz=28.0)
        beam_mgr = BeamManager(num_beams=64)

        coverage = mmwave.estimate_coverage_range(
            tx_power_dbm=20.0,
            sensitivity_dbm=-70.0,
            antenna_gain_dbi=10.0,
        )

        signal_strengths = {i: -70.0 - (i - 32) ** 2 / 100 for i in range(64)}
        best_beam = beam_mgr.perform_beam_sweeping(signal_strengths)

        assert coverage > 0
        assert best_beam is not None


if __name__ == "__main__":
    pytest.main([__file__])
