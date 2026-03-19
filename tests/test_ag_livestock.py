"""Tests for livestock management module."""

from datetime import date, timedelta

import pytest

pytestmark = pytest.mark.xfail(
    reason="Domain skeleton pending implementation (tracking: docs/ops/remediation/DOMAIN_STUB_TRACKING.md)",
    strict=False,
)

from thomas.agriculture._types import LivestockAnimal, LivestockType
from thomas.agriculture.livestock import (
    AnimalHealthRecords,
    BodyConditionScore,
    BreedingCalendar,
    FeedRationBalancer,
    HerdTracking,
    ProductionTracking,
    StockingRate,
    WeightGainPrediction,
)


class TestHerdTracking:
    """Test herd tracking functionality."""

    def setup_method(self) -> None:
        """Setup herd tracking."""
        self.herd = HerdTracking()

    def test_add_animal(self) -> None:
        """Test adding animal to herd."""
        animal = LivestockAnimal(
            animal_id="cow001",
            farm_id="farm1",
            livestock_type=LivestockType.CATTLE,
            birth_date=date(2020, 1, 1),
            weight_lbs=1200,
            body_condition_score=5.0,
        )

        self.herd.add_animal(animal)
        assert self.herd.calculate_herd_size() == 1

    def test_get_animal(self) -> None:
        """Test retrieving animal."""
        animal = LivestockAnimal(
            animal_id="cow001",
            farm_id="farm1",
            livestock_type=LivestockType.CATTLE,
            birth_date=date(2020, 1, 1),
            weight_lbs=1200,
            body_condition_score=5.0,
        )

        self.herd.add_animal(animal)
        retrieved = self.herd.get_animal("cow001")

        assert retrieved is not None
        assert retrieved.animal_id == "cow001"

    def test_duplicate_animal_id_raises_error(self) -> None:
        """Test duplicate animal ID raises error."""
        animal1 = LivestockAnimal(
            animal_id="cow001",
            farm_id="farm1",
            livestock_type=LivestockType.CATTLE,
            birth_date=date(2020, 1, 1),
            weight_lbs=1200,
            body_condition_score=5.0,
        )

        animal2 = LivestockAnimal(
            animal_id="cow001",
            farm_id="farm1",
            livestock_type=LivestockType.CATTLE,
            birth_date=date(2020, 6, 1),
            weight_lbs=1100,
            body_condition_score=4.5,
        )

        self.herd.add_animal(animal1)

        with pytest.raises(Exception):
            self.herd.add_animal(animal2)

    def test_get_herd_by_type(self) -> None:
        """Test getting herd by livestock type."""
        cattle = LivestockAnimal(
            animal_id="cow001",
            farm_id="farm1",
            livestock_type=LivestockType.CATTLE,
            birth_date=date(2020, 1, 1),
            weight_lbs=1200,
            body_condition_score=5.0,
        )

        pig = LivestockAnimal(
            animal_id="pig001",
            farm_id="farm1",
            livestock_type=LivestockType.SWINE,
            birth_date=date(2022, 1, 1),
            weight_lbs=300,
            body_condition_score=5.0,
        )

        self.herd.add_animal(cattle)
        self.herd.add_animal(pig)

        cattle_herd = self.herd.get_herd(LivestockType.CATTLE)
        assert len(cattle_herd) == 1
        assert cattle_herd[0].animal_id == "cow001"


class TestFeedRationBalancer:
    """Test feed ration balancing."""

    def setup_method(self) -> None:
        """Setup ration balancer."""
        self.balancer = FeedRationBalancer()

    def test_calculate_ration(self) -> None:
        """Test ration calculation."""
        mix = {
            "corn": 50,
            "soybean_meal": 40,
            "alfalfa_hay": 10,
        }

        ration = self.balancer.calculate_ration(mix)

        # Should have nutrient values
        assert "crude_protein_pct" in ration
        assert "tdn_pct" in ration

    def test_ration_nutrient_values(self) -> None:
        """Test ration has reasonable nutrient values."""
        mix = {
            "corn": 60,
            "soybean_meal": 25,
            "alfalfa_hay": 15,
        }

        ration = self.balancer.calculate_ration(mix)

        # Protein should be between 8% and 20%
        assert 8 < ration["crude_protein_pct"] < 20
        # TDN should be between 50% and 85%
        assert 50 < ration["tdn_pct"] < 85

    def test_check_nutrient_adequacy(self) -> None:
        """Test nutrient adequacy check."""
        mix = {
            "corn": 50,
            "soybean_meal": 40,
            "alfalfa_hay": 10,
        }

        ration = self.balancer.calculate_ration(mix)
        adequacy = self.balancer.check_nutrient_adequacy(ration)

        # Should have adequacy checks for each nutrient
        assert "crude_protein" in adequacy
        assert "tdn" in adequacy


class TestBodyConditionScore:
    """Test body condition scoring."""

    def test_assess_emaciated(self) -> None:
        """Test assessment of emaciated condition."""
        result = BodyConditionScore.assess_condition(1.5)
        assert "Emaciated" in result

    def test_assess_ideal(self) -> None:
        """Test assessment of ideal condition."""
        result = BodyConditionScore.assess_condition(5.0)
        assert "Ideal" in result

    def test_assess_obese(self) -> None:
        """Test assessment of obese condition."""
        result = BodyConditionScore.assess_condition(9.0)
        assert "Obese" in result

    def test_recommend_adjustment_none_needed(self) -> None:
        """Test no adjustment when at target."""
        adjustment = BodyConditionScore.recommend_adjustment(
            current_bcs=5.0,
            target_bcs=5.0,
        )

        assert adjustment is None

    def test_recommend_adjustment_increase(self) -> None:
        """Test recommendation to increase condition."""
        adjustment = BodyConditionScore.recommend_adjustment(
            current_bcs=3.5,
            target_bcs=5.0,
        )

        assert adjustment is not None
        assert "increase" in adjustment.lower()

    def test_recommend_adjustment_decrease(self) -> None:
        """Test recommendation to decrease condition."""
        adjustment = BodyConditionScore.recommend_adjustment(
            current_bcs=7.0,
            target_bcs=5.0,
        )

        assert adjustment is not None
        assert "reduce" in adjustment.lower()


class TestBreedingCalendar:
    """Test breeding calendar."""

    def setup_method(self) -> None:
        """Setup breeding calendar."""
        self.calendar = BreedingCalendar()

    def test_calculate_due_date_cattle(self) -> None:
        """Test due date calculation for cattle."""
        breeding_date = date(2024, 1, 1)
        due_date = self.calendar.calculate_due_date(
            breeding_date=breeding_date,
            livestock_type=LivestockType.CATTLE,
        )

        # Cattle gestation is 283 days
        expected = breeding_date + timedelta(days=283)
        assert due_date == expected

    def test_calculate_due_date_swine(self) -> None:
        """Test due date calculation for swine."""
        breeding_date = date(2024, 1, 1)
        due_date = self.calendar.calculate_due_date(
            breeding_date=breeding_date,
            livestock_type=LivestockType.SWINE,
        )

        # Swine gestation is 114 days
        expected = breeding_date + timedelta(days=114)
        assert due_date == expected

    def test_calculate_breeding_date(self) -> None:
        """Test calculating breeding date from target birth."""
        target_birth = date(2024, 6, 1)
        breeding_date = self.calendar.calculate_breeding_date(
            target_birth_date=target_birth,
            livestock_type=LivestockType.CATTLE,
        )

        # Should be 283 days before birth
        expected = target_birth - timedelta(days=283)
        assert breeding_date == expected


class TestProductionTracking:
    """Test production tracking."""

    def setup_method(self) -> None:
        """Setup production tracking."""
        self.tracker = ProductionTracking()

    def test_record_milk_production(self) -> None:
        """Test recording milk production."""
        self.tracker.record_milk_production("cow001", 50.0)
        self.tracker.record_milk_production("cow001", 52.0)
        self.tracker.record_milk_production("cow001", 48.0)

        avg = self.tracker.calculate_average_production("cow001")

        # (50 + 52 + 48) / 3 = 50
        assert abs(avg - 50.0) < 0.1

    def test_calculate_lactation_total(self) -> None:
        """Test lactation production calculation."""
        self.tracker.record_milk_production("cow001", 50.0)
        self.tracker.record_milk_production("cow001", 50.0)

        lactation_total = self.tracker.calculate_lactation_total(
            "cow001",
            days_in_lactation=305,
        )

        # 50 * 305 = 15,250
        assert abs(lactation_total - 15250.0) < 10


class TestStockingRate:
    """Test stocking rate calculations."""

    def test_calculate_animal_units(self) -> None:
        """Test animal unit calculation."""
        au = StockingRate.calculate_animal_units(
            number_of_animals=100,
            avg_weight_lbs=1000,
        )

        # 100 animals Ã— 1000 lbs / 1000 = 100 AU
        assert abs(au - 100.0) < 0.1

    def test_calculate_max_stocking_rate(self) -> None:
        """Test maximum stocking rate calculation."""
        max_au = StockingRate.calculate_max_stocking_rate(
            forage_production_tons_acre=3.0,
            forage_utilization_pct=50.0,
            annual_forage_requirement_lbs_au=6000.0,
        )

        # (3 tons Ã— 2000 lbs/ton Ã— 50%) / 6000 = 0.5 AU/acre
        assert 0.4 < max_au < 0.6

    def test_stocking_rate_validation(self) -> None:
        """Test stocking rate is positive and reasonable."""
        max_au = StockingRate.calculate_max_stocking_rate(
            forage_production_tons_acre=2.5,
            forage_utilization_pct=60.0,
        )

        assert max_au > 0


class TestAnimalHealthRecords:
    """Test animal health record management."""

    def setup_method(self) -> None:
        """Setup health records."""
        self.records = AnimalHealthRecords()

    def test_record_treatment(self) -> None:
        """Test recording medical treatment."""
        treatment_date = date(2024, 1, 1)

        self.records.record_treatment(
            animal_id="cow001",
            treatment_date=treatment_date,
            treatment_type="antibiotic",
            medication="penicillin",
            withdrawal_days=5,
        )

        records = self.records.health_records["cow001"]
        assert len(records) == 1
        assert records[0]["medication"] == "penicillin"

    def test_can_sell_product_within_withdrawal(self) -> None:
        """Test cannot sell product during withdrawal period."""
        self.records.record_treatment(
            animal_id="cow001",
            treatment_date=date(2024, 1, 1),
            treatment_type="antibiotic",
            medication="penicillin",
            withdrawal_days=5,
        )

        can_sell = self.records.can_sell_product("cow001", date(2024, 1, 3))
        assert not can_sell

    def test_can_sell_product_after_withdrawal(self) -> None:
        """Test can sell product after withdrawal period."""
        self.records.record_treatment(
            animal_id="cow001",
            treatment_date=date(2024, 1, 1),
            treatment_type="antibiotic",
            medication="penicillin",
            withdrawal_days=5,
        )

        can_sell = self.records.can_sell_product("cow001", date(2024, 1, 10))
        assert can_sell


class TestWeightGainPrediction:
    """Test weight gain prediction."""

    def test_predict_daily_gain(self) -> None:
        """Test daily gain prediction."""
        prediction = WeightGainPrediction.predict_daily_gain(
            current_weight_lbs=800,
            target_weight_lbs=1200,
            days_to_target=200,
            feed_conversion_ratio=5.0,
        )

        # (1200 - 800) / 200 = 2 lbs/day
        assert abs(prediction["daily_gain_lbs"] - 2.0) < 0.1

        # 2 lbs Ã— 5 FCR = 10 lbs feed/day
        assert abs(prediction["daily_feed_required_lbs"] - 10.0) < 0.1

    def test_total_feed_required(self) -> None:
        """Test total feed requirement calculation."""
        prediction = WeightGainPrediction.predict_daily_gain(
            current_weight_lbs=800,
            target_weight_lbs=1200,
            days_to_target=200,
        )

        # Daily feed Ã— days
        total_feed = prediction["daily_feed_required_lbs"] * 200
        assert abs(total_feed - prediction["total_feed_required_lbs"]) < 1
