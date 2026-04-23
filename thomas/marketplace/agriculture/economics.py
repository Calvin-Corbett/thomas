"""Farm economics module for financial analysis and planning."""

from decimal import Decimal

from thomas.marketplace.agriculture._exceptions import EconomicsError


class EnterpriseBudget:
    """Creates enterprise budgets for crop and livestock operations."""

    def __init__(self) -> None:
        """Initialize enterprise budget calculator."""
        pass

    def calculate_crop_budget(
        self,
        crop_type: str,
        acres: float,
        yield_bu_acre: float,
        price_per_bu: float,
        seed_cost_per_acre: float,
        fertilizer_cost_per_acre: float,
        pesticide_cost_per_acre: float,
        fuel_cost_per_acre: float,
        labor_cost_per_acre: float,
        equipment_cost_per_acre: float,
        land_rent_per_acre: float,
    ) -> dict[str, Decimal]:
        """Calculate crop enterprise budget.

        Args:
            crop_type: Crop name
            acres: Field size
            yield_bu_acre: Expected yield per acre
            price_per_bu: Market price per bushel
            seed_cost_per_acre: Seed expense
            fertilizer_cost_per_acre: Fertilizer expense
            pesticide_cost_per_acre: Pesticide expense
            fuel_cost_per_acre: Fuel/machinery fuel
            labor_cost_per_acre: Labor expense
            equipment_cost_per_acre: Equipment/machinery cost
            land_rent_per_acre: Land rental cost

        Returns:
            Dictionary with budget components and net return
        """
        # Total revenue
        gross_revenue = Decimal(acres * yield_bu_acre * price_per_bu)

        # Variable costs (per acre inputs)
        variable_cost_per_acre = (
            seed_cost_per_acre
            + fertilizer_cost_per_acre
            + pesticide_cost_per_acre
            + fuel_cost_per_acre
            + labor_cost_per_acre
        )
        total_variable_cost = Decimal(acres * variable_cost_per_acre)

        # Fixed costs
        total_fixed_cost = Decimal(acres * (equipment_cost_per_acre + land_rent_per_acre))

        # Net return
        net_return = gross_revenue - total_variable_cost - total_fixed_cost

        return {
            "crop": crop_type,
            "acres": Decimal(acres),
            "gross_revenue": gross_revenue,
            "variable_cost": total_variable_cost,
            "variable_cost_per_bu": total_variable_cost / Decimal(acres * yield_bu_acre)
            if yield_bu_acre > 0
            else Decimal(0),
            "fixed_cost": total_fixed_cost,
            "total_cost": total_variable_cost + total_fixed_cost,
            "net_return": net_return,
            "net_return_per_acre": net_return / Decimal(acres) if acres > 0 else Decimal(0),
        }

    def calculate_livestock_budget(
        self,
        livestock_type: str,
        animal_units: float,
        selling_price_per_lb: float,
        target_weight_gain_lbs: float,
        feed_cost_per_day_per_au: float,
        days_on_feed: int,
        labor_cost_per_au: float,
        facilities_cost_per_au: float,
        health_medicine_cost_per_au: float,
    ) -> dict[str, Decimal]:
        """Calculate livestock enterprise budget.

        Args:
            livestock_type: Type of livestock
            animal_units: Number of animal units
            selling_price_per_lb: Price received per lb
            target_weight_gain_lbs: Expected weight gain
            feed_cost_per_day_per_au: Daily feed expense
            days_on_feed: Feeding period days
            labor_cost_per_au: Labor per animal unit
            facilities_cost_per_au: Facilities cost
            health_medicine_cost_per_au: Health costs

        Returns:
            Dictionary with budget components
        """
        # Revenue
        total_weight_gain = animal_units * target_weight_gain_lbs
        gross_revenue = Decimal(total_weight_gain * selling_price_per_lb)

        # Feed costs
        feed_cost = Decimal(animal_units * feed_cost_per_day_per_au * days_on_feed)

        # Other variable costs
        variable_cost = feed_cost
        fixed_cost = Decimal(animal_units * (labor_cost_per_au + facilities_cost_per_au + health_medicine_cost_per_au))

        # Net return
        net_return = gross_revenue - variable_cost - fixed_cost

        return {
            "livestock": livestock_type,
            "animal_units": Decimal(animal_units),
            "gross_revenue": gross_revenue,
            "feed_cost": feed_cost,
            "feed_cost_per_lb_gain": feed_cost / Decimal(total_weight_gain) if total_weight_gain > 0 else Decimal(0),
            "variable_cost": variable_cost,
            "fixed_cost": fixed_cost,
            "total_cost": variable_cost + fixed_cost,
            "net_return": net_return,
            "net_return_per_au": net_return / Decimal(animal_units) if animal_units > 0 else Decimal(0),
        }


class BreakEvenAnalysis:
    """Analyzes break-even points for pricing and yield."""

    @staticmethod
    def break_even_yield(
        total_cost_per_acre: float,
        price_per_bu: float,
    ) -> float:
        """Calculate break-even yield.

        Args:
            total_cost_per_acre: Total cost per acre
            price_per_bu: Market price per bushel

        Returns:
            Break-even yield in bu/acre
        """
        if price_per_bu <= 0:
            raise EconomicsError("Price must be positive")
        return total_cost_per_acre / price_per_bu

    @staticmethod
    def break_even_price(
        total_cost_per_acre: float,
        yield_bu_acre: float,
    ) -> float:
        """Calculate break-even price.

        Args:
            total_cost_per_acre: Total cost per acre
            yield_bu_acre: Expected yield per acre

        Returns:
            Break-even price per bushel
        """
        if yield_bu_acre <= 0:
            raise EconomicsError("Yield must be positive")
        return total_cost_per_acre / yield_bu_acre

    @staticmethod
    def sensitivity_analysis(
        base_price: float,
        base_yield: float,
        total_cost: float,
        price_range_pct: float = 20.0,
        yield_range_pct: float = 20.0,
    ) -> dict[str, list[float]]:
        """Perform sensitivity analysis on price and yield.

        Args:
            base_price: Base price per bu
            base_yield: Base yield per acre
            total_cost: Total cost per acre
            price_range_pct: Price variation percentage
            yield_range_pct: Yield variation percentage

        Returns:
            Dictionary with net income at various price/yield combinations
        """
        if base_price <= 0 or base_yield <= 0:
            raise EconomicsError("Price and yield must be positive")

        results = {}

        # Create price and yield scenarios
        price_scenarios = [
            base_price * (1 - price_range_pct / 100),
            base_price * 0.9,
            base_price,
            base_price * 1.1,
            base_price * (1 + price_range_pct / 100),
        ]

        yield_scenarios = [
            base_yield * (1 - yield_range_pct / 100),
            base_yield * 0.9,
            base_yield,
            base_yield * 1.1,
            base_yield * (1 + yield_range_pct / 100),
        ]

        for price in price_scenarios:
            for yield_val in yield_scenarios:
                revenue = price * yield_val
                net_income = revenue - total_cost
                key = f"Price ${price:.2f}, Yield {yield_val:.0f} bu"
                results[key] = net_income

        return results


class CropInsuranceAnalysis:
    """Analyzes crop insurance options and coverage."""

    def __init__(self) -> None:
        """Initialize insurance analysis."""
        pass

    def calculate_aph_yield(
        self,
        historical_yields: list[float],
        exclude_lowest: bool = True,
    ) -> float:
        """Calculate Actual Production History (APH) yield.

        Crop insurance uses 4-10 year history, often excluding lowest year.

        Args:
            historical_yields: List of historical yield values
            exclude_lowest: Whether to exclude lowest yield

        Returns:
            APH yield
        """
        if not historical_yields:
            raise EconomicsError("No yield data provided")

        yields = sorted(historical_yields)

        if exclude_lowest and len(yields) > 1:
            yields = yields[1:]

        aph = sum(yields) / len(yields) if yields else 0
        return round(aph, 1)

    @staticmethod
    def calculate_insurance_premium(
        aph_yield: float,
        coverage_level_pct: float,
        base_rate_pct: float = 0.04,
    ) -> float:
        """Calculate insurance premium.

        Args:
            aph_yield: Actual Production History yield
            coverage_level_pct: Coverage level (0-100)
            base_rate_pct: Base insurance rate

        Returns:
            Annual premium per acre
        """
        if not (0 < coverage_level_pct <= 100):
            raise EconomicsError("Coverage must be 0-100%")

        return aph_yield * coverage_level_pct / 100 * base_rate_pct

    @staticmethod
    def calculate_indemnity(
        aph_yield: float,
        coverage_level_pct: float,
        actual_yield: float,
        price_per_bu: float,
    ) -> float:
        """Calculate insurance indemnity payment.

        Args:
            aph_yield: Actual Production History yield
            coverage_level_pct: Coverage level (0-100)
            actual_yield: Actual yield achieved
            price_per_bu: Guaranteed price

        Returns:
            Indemnity payment per acre
        """
        covered_yield = aph_yield * coverage_level_pct / 100
        loss = max(0, covered_yield - actual_yield)
        return loss * price_per_bu


class MarketPriceTracking:
    """Tracks and analyzes commodity prices."""

    def __init__(self) -> None:
        """Initialize price tracking."""
        self.price_history: dict[str, list[tuple[str, float]]] = {}

    def record_price(
        self,
        commodity: str,
        date_str: str,
        price_per_bu: float,
    ) -> None:
        """Record a price observation.

        Args:
            commodity: Commodity name
            date_str: Date as string
            price_per_bu: Price per bushel
        """
        if commodity not in self.price_history:
            self.price_history[commodity] = []
        self.price_history[commodity].append((date_str, price_per_bu))

    def calculate_average_price(
        self,
        commodity: str,
    ) -> float:
        """Calculate average historical price.

        Args:
            commodity: Commodity name

        Returns:
            Average price per bushel
        """
        prices = self.price_history.get(commodity, [])
        if not prices:
            return 0.0
        values = [p[1] for p in prices]
        return sum(values) / len(values)

    def calculate_price_volatility(
        self,
        commodity: str,
    ) -> float:
        """Calculate price volatility (standard deviation).

        Args:
            commodity: Commodity name

        Returns:
            Standard deviation of prices
        """
        prices = self.price_history.get(commodity, [])
        if len(prices) < 2:
            return 0.0

        values = [p[1] for p in prices]
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        return variance**0.5


class FuturesHedging:
    """Simulates futures hedging strategies."""

    @staticmethod
    def hedge_price(
        bushels_produced: float,
        futures_contract_price: float,
        basis_points: float = -20,
    ) -> dict[str, float]:
        """Calculate hedged price using futures.

        Basis = Spot Price - Futures Price

        Args:
            bushels_produced: Bushels to hedge
            futures_contract_price: Futures price locked in
            basis_points: Expected basis in cents per bu

        Returns:
            Dictionary with hedge economics
        """
        basis_decimal = basis_points / 100.0  # Convert cents to dollars

        # Locked-in price = futures price + basis
        locked_in_price = futures_contract_price + basis_decimal

        revenue_hedged = bushels_produced * locked_in_price

        return {
            "bushels": bushels_produced,
            "futures_price": futures_contract_price,
            "basis": basis_decimal,
            "locked_in_price": round(locked_in_price, 2),
            "hedged_revenue": round(revenue_hedged, 2),
        }


class LandValuation:
    """Calculates fair land values based on productivity."""

    @staticmethod
    def calculate_capitalized_land_value(
        annual_net_return_per_acre: float,
        capitalization_rate: float = 0.04,
    ) -> float:
        """Calculate land value using income capitalization.

        Land Value = Annual Net Income / Capitalization Rate

        Args:
            annual_net_return_per_acre: Average annual net return per acre
            capitalization_rate: Interest/discount rate

        Returns:
            Land value per acre
        """
        if capitalization_rate <= 0:
            raise EconomicsError("Capitalization rate must be positive")

        land_value = annual_net_return_per_acre / capitalization_rate
        return round(land_value, 0)

    @staticmethod
    def calculate_fair_land_rent(
        annual_net_return_per_acre: float,
        land_value_per_acre: float,
        target_return_pct: float = 5.0,
    ) -> float:
        """Calculate fair land rent.

        Fair rent should return landowner a fair return on land value.

        Args:
            annual_net_return_per_acre: Average production returns per acre
            land_value_per_acre: Market value of land
            target_return_pct: Target return on land value

        Returns:
            Fair rent per acre
        """
        # Rent is often 40-50% of net return
        basic_rent = annual_net_return_per_acre * 0.45

        # Adjust for land value return
        land_value_return = land_value_per_acre * (target_return_pct / 100.0)

        fair_rent = (basic_rent + land_value_return) / 2
        return round(fair_rent, 0)


class MachineryCosting:
    """Calculates machinery ownership and operating costs."""

    @staticmethod
    def calculate_annual_machinery_cost(
        purchase_price: float,
        useful_life_years: int,
        salvage_value_pct: float = 10,
        hours_per_year: float = 100,
        fuel_gph: float = 5,
        fuel_price_per_gal: float = 3.00,
    ) -> dict[str, float]:
        """Calculate total annual machinery cost.

        Args:
            purchase_price: Initial purchase price
            useful_life_years: Expected useful life
            salvage_value_pct: Expected salvage value percentage
            hours_per_year: Operating hours per year
            fuel_gph: Fuel consumption gallons per hour
            fuel_price_per_gal: Fuel price

        Returns:
            Dictionary with cost components
        """
        # Depreciation (straight-line)
        salvage_value = purchase_price * (salvage_value_pct / 100.0)
        annual_depreciation = (purchase_price - salvage_value) / useful_life_years

        # Interest (average value method)
        average_value = (purchase_price + salvage_value) / 2
        annual_interest = average_value * 0.05  # 5% interest rate

        # Fuel cost
        annual_fuel = hours_per_year * fuel_gph * fuel_price_per_gal

        # Repair and maintenance (5% of average value per year)
        annual_repairs = average_value * 0.05

        total_cost = annual_depreciation + annual_interest + annual_fuel + annual_repairs

        return {
            "depreciation": round(annual_depreciation, 2),
            "interest": round(annual_interest, 2),
            "fuel": round(annual_fuel, 2),
            "repairs_maintenance": round(annual_repairs, 2),
            "total_annual_cost": round(total_cost, 2),
            "cost_per_hour": round(total_cost / hours_per_year, 2) if hours_per_year > 0 else 0,
        }


class FarmFinancialRatios:
    """Calculates financial ratios for farm analysis."""

    @staticmethod
    def calculate_profit_margin(
        net_return: float,
        gross_revenue: float,
    ) -> float:
        """Calculate profit margin percentage.

        Args:
            net_return: Net return/profit
            gross_revenue: Total revenue

        Returns:
            Profit margin percentage
        """
        if gross_revenue <= 0:
            return 0.0
        return (net_return / gross_revenue) * 100

    @staticmethod
    def calculate_operating_ratio(
        operating_cost: float,
        gross_revenue: float,
    ) -> float:
        """Calculate operating ratio.

        OR < 1.0 is good (costs less than revenue).

        Args:
            operating_cost: Total operating costs
            gross_revenue: Total revenue

        Returns:
            Operating ratio
        """
        if gross_revenue <= 0:
            return float("inf")
        return operating_cost / gross_revenue

    @staticmethod
    def calculate_roa(
        net_return: float,
        total_assets: float,
    ) -> float:
        """Calculate Return on Assets.

        Args:
            net_return: Annual net return
            total_assets: Total farm assets

        Returns:
            ROA percentage
        """
        if total_assets <= 0:
            return 0.0
        return (net_return / total_assets) * 100

    @staticmethod
    def calculate_debt_to_equity(
        total_debt: float,
        total_equity: float,
    ) -> float:
        """Calculate debt-to-equity ratio.

        Args:
            total_debt: Total farm debt
            total_equity: Total farm equity

        Returns:
            Debt-to-equity ratio
        """
        if total_equity <= 0:
            return float("inf")
        return total_debt / total_equity
