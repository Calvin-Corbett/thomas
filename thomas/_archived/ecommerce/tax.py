"""Tax calculation and management."""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from ._types import TaxRule


class TaxCalculator:
    """Calculate tax based on jurisdiction and product category."""

    def __init__(self) -> None:
        """Initialize tax calculator."""
        self.tax_rules: dict[str, TaxRule] = {}
        self.product_tax_categories: dict[str, str] = {}
        self.tax_exempt_regions: list[str] = []

    def add_tax_rule(self, rule: TaxRule) -> None:
        """Add tax rule for jurisdiction.

        Args:
            rule: Tax rule
        """
        self.tax_rules[rule.id] = rule

    def set_product_tax_category(self, product_id: str, category: str) -> None:
        """Set product tax category.

        Args:
            product_id: Product ID
            category: Tax category (standard, reduced, exempt)
        """
        self.product_tax_categories[product_id] = category

    def get_product_tax_category(self, product_id: str) -> str:
        """Get product tax category.

        Args:
            product_id: Product ID

        Returns:
            Tax category
        """
        return self.product_tax_categories.get(product_id, "standard")

    def mark_tax_exempt_region(self, region: str) -> None:
        """Mark region as tax-exempt.

        Args:
            region: Region code (state, country)
        """
        if region not in self.tax_exempt_regions:
            self.tax_exempt_regions.append(region)

    def is_tax_exempt_region(self, country: str, state: str | None = None) -> bool:
        """Check if region is tax-exempt.

        Args:
            country: Country code
            state: Optional state code

        Returns:
            True if region is tax-exempt
        """
        # Check state first
        if state:
            region = f"{country}-{state}"
            if region in self.tax_exempt_regions:
                return True

        # Check country
        return country in self.tax_exempt_regions

    def lookup_tax_rate(
        self,
        country: str,
        state: str | None = None,
        tax_category: str = "standard",
    ) -> Decimal:
        """Look up applicable tax rate.

        Args:
            country: Country code
            state: Optional state/province code
            tax_category: Tax category

        Returns:
            Tax rate (0-1, e.g., 0.08 for 8%)
        """
        # Check for specific state rule
        if state:
            for rule in self.tax_rules.values():
                if rule.country == country and rule.state == state and rule.tax_category == tax_category:
                    return rule.rate

        # Check for country rule
        for rule in self.tax_rules.values():
            if rule.country == country and rule.state is None and rule.tax_category == tax_category:
                return rule.rate

        return Decimal("0")

    def calculate_tax_inclusive(
        self,
        price_with_tax: Decimal,
        country: str,
        state: str | None = None,
        tax_category: str = "standard",
    ) -> tuple[Decimal, Decimal]:
        """Calculate tax amount from tax-inclusive price.

        Args:
            price_with_tax: Price including tax
            country: Country code
            state: Optional state code
            tax_category: Product tax category

        Returns:
            Tuple of (base_price, tax_amount)
        """
        tax_rate = self.lookup_tax_rate(country, state, tax_category)
        if tax_rate == 0:
            return (price_with_tax, Decimal("0"))

        # price_with_tax = base_price * (1 + tax_rate)
        # base_price = price_with_tax / (1 + tax_rate)
        base_price = price_with_tax / (1 + tax_rate)
        tax_amount = price_with_tax - base_price

        return (self._round_tax(base_price), self._round_tax(tax_amount))

    def calculate_tax_exclusive(
        self,
        base_price: Decimal,
        country: str,
        state: str | None = None,
        tax_category: str = "standard",
    ) -> Decimal:
        """Calculate tax amount from base price.

        Args:
            base_price: Price before tax
            country: Country code
            state: Optional state code
            tax_category: Product tax category

        Returns:
            Tax amount
        """
        if self.is_tax_exempt_region(country, state):
            return Decimal("0")

        tax_rate = self.lookup_tax_rate(country, state, tax_category)
        return self._round_tax(base_price * tax_rate)

    def calculate_order_tax(
        self,
        items: list[dict[str, Any]],
        country: str,
        state: str | None = None,
    ) -> Decimal:
        """Calculate total tax for order.

        Args:
            items: List of {product_id, unit_price, quantity, tax_category}
            country: Destination country
            state: Destination state

        Returns:
            Total tax for order
        """
        if self.is_tax_exempt_region(country, state):
            return Decimal("0")

        total_tax = Decimal("0")
        for item in items:
            product_id = item.get("product_id")
            tax_category = self.get_product_tax_category(product_id) if product_id else "standard"
            if "tax_category" in item:
                tax_category = item["tax_category"]

            item_total = item["unit_price"] * item["quantity"]
            item_tax = self.calculate_tax_exclusive(item_total, country, state, tax_category)
            total_tax += item_tax

        return self._round_tax(total_tax)

    def _round_tax(self, amount: Decimal) -> Decimal:
        """Round tax amount to 2 decimals.

        Args:
            amount: Tax amount

        Returns:
            Rounded amount
        """
        return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def calculate_vat(
        self,
        base_price: Decimal,
        country: str,
        vat_rate: Decimal | None = None,
    ) -> Decimal:
        """Calculate VAT (Value Added Tax).

        Args:
            base_price: Price before VAT
            country: Country code
            vat_rate: Optional override VAT rate

        Returns:
            VAT amount
        """
        if vat_rate is None:
            vat_rate = self.lookup_tax_rate(country, tax_category="vat")

        return self._round_tax(base_price * vat_rate)

    def apply_tax_exemption(
        self,
        tax_amount: Decimal,
        exemption_percentage: Decimal = Decimal("100"),
    ) -> Decimal:
        """Apply tax exemption certificate.

        Args:
            tax_amount: Original tax amount
            exemption_percentage: Exemption percentage (0-100)

        Returns:
            Tax amount after exemption
        """
        exemption_factor = exemption_percentage / Decimal("100")
        return self._round_tax(tax_amount * (1 - exemption_factor))

    def get_tax_summary(
        self,
        items: list[dict[str, Any]],
        country: str,
        state: str | None = None,
    ) -> dict[str, Any]:
        """Get detailed tax summary for order.

        Args:
            items: List of order items
            country: Destination country
            state: Destination state

        Returns:
            Tax summary dictionary
        """
        subtotal = Decimal("0")
        tax_by_category: dict[str, Decimal] = {}

        for item in items:
            item_total = item["unit_price"] * item["quantity"]
            subtotal += item_total

            tax_category = item.get("tax_category", "standard")
            if "product_id" in item:
                product_id = item["product_id"]
                tax_category = self.get_product_tax_category(product_id)

            if tax_category not in tax_by_category:
                tax_by_category[tax_category] = Decimal("0")

            item_tax = self.calculate_tax_exclusive(item_total, country, state, tax_category)
            tax_by_category[tax_category] += item_tax

        total_tax = sum(tax_by_category.values())

        return {
            "subtotal": subtotal,
            "tax_by_category": {k: self._round_tax(v) for k, v in tax_by_category.items()},
            "total_tax": self._round_tax(total_tax),
            "total_with_tax": subtotal + total_tax,
            "country": country,
            "state": state,
            "is_exempt_region": self.is_tax_exempt_region(country, state),
        }

    def get_tax_reporting_summary(self) -> dict[str, Any]:
        """Get tax reporting summary across all rules.

        Returns:
            Summary of tax configuration
        """
        by_country: dict[str, list[dict[str, Any]]] = {}

        for rule in self.tax_rules.values():
            if rule.country not in by_country:
                by_country[rule.country] = []

            by_country[rule.country].append(
                {
                    "state": rule.state,
                    "rate": float(rule.rate),
                    "category": rule.tax_category,
                }
            )

        return {
            "rules_by_country": by_country,
            "exempt_regions": self.tax_exempt_regions,
            "product_categories": list(set(self.product_tax_categories.values())),
        }
