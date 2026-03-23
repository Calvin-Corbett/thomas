"""Real estate reporting and document generation."""

from datetime import date
from decimal import Decimal

from thomas.marketplace.real_estate._types import (
    Comparable,
    Lease,
    Listing,
    MarketStats,
    Property,
    Transaction,
)


class CMAReportGenerator:
    """Comparative Market Analysis report generation."""

    @staticmethod
    def generate_cma_report(
        subject_property: Property,
        comparables: list[Comparable],
        cma_value: Decimal,
        report_date: date = None,
    ) -> str:
        """Generate a CMA report.

        Args:
            subject_property: Property being valued
            comparables: List of comparable properties
            cma_value: Estimated value from CMA
            report_date: Report date (default today)

        Returns:
            Formatted CMA report text
        """
        if report_date is None:
            report_date = date.today()

        report = f"""
COMPARATIVE MARKET ANALYSIS REPORT
{'=' * 50}

Report Date: {report_date.strftime('%B %d, %Y')}
Subject Property: {subject_property.address}
Property Type: {subject_property.property_type.value}
Bedrooms: {subject_property.bedrooms}
Bathrooms: {subject_property.bathrooms}
Square Footage: {subject_property.sqft:,} sq ft
Year Built: {subject_property.year_built}

COMPARABLE PROPERTIES ANALYZED
{'-' * 50}

"""
        for i, comp in enumerate(comparables, 1):
            report += f"""
Comparable #{i}
Address: {comp.address}
Sale Price: ${comp.sale_price:,.0f}
Sale Date: {comp.sale_date.strftime('%B %d, %Y')}
Square Footage: {comp.sqft:,} sq ft
Bedrooms: {comp.bedrooms}
Bathrooms: {comp.bathrooms}
Days on Market: {comp.days_on_market or 'N/A'}
Price per Sq Ft: ${comp.sale_price / comp.sqft:,.2f}

"""

        avg_price_per_sqft = sum(c.sale_price / c.sqft for c in comparables) / len(comparables)

        report += f"""
VALUATION SUMMARY
{'-' * 50}

Number of Comparables: {len(comparables)}
Average Price per Sq Ft: ${avg_price_per_sqft:,.2f}
Subject Property Sq Ft: {subject_property.sqft:,}
Estimated Value: ${cma_value:,.0f}

MARKET CONDITIONS
Market appears {'strong' if len(comparables) >= 3 else 'limited'} with sufficient comparable data.

Report prepared on {report_date.strftime('%B %d, %Y')}
"""
        return report


class PropertyDetailSheet:
    """Property detail sheet generation."""

    @staticmethod
    def generate_detail_sheet(prop: Property, listing: Listing | None = None) -> str:
        """Generate property detail sheet.

        Args:
            prop: Property instance
            listing: Optional listing instance

        Returns:
            Formatted property detail sheet
        """
        sheet = f"""
PROPERTY DETAIL SHEET
{'=' * 60}

PROPERTY IDENTIFICATION
{'-' * 60}
Property Address: {prop.address}
County: {prop.address.county or 'N/A'}
Property Type: {prop.property_type.value}
Zoning: {prop.zoning_type.value}
Year Built: {prop.year_built} (Age: {prop.age_years()} years)

PHYSICAL CHARACTERISTICS
{'-' * 60}
Bedrooms: {prop.bedrooms}
Bathrooms: {prop.bathrooms}
Total Square Footage: {prop.sqft:,} sq ft
Lot Size: {prop.lot_sqft:,} sq ft
Building Square Feet: {prop.sqft:,}

FINANCIAL INFORMATION
{'-' * 60}
Assessed Value: ${prop.assessed_value:,.0f}
Annual Property Tax: ${prop.annual_tax:,.2f}
HOA Fee (if applicable): ${prop.hoa_fee:,.2f}
"""

        if prop.last_sale_price:
            sheet += f"Last Sale Price: ${prop.last_sale_price:,.0f}\n"
            sheet += f"Last Sale Date: {prop.last_sale_date}\n"

        sheet += f"""
FEATURES
{'-' * 60}
"""
        if prop.features:
            for feature in prop.features:
                sheet += f"• {feature}\n"
        else:
            sheet += "No special features listed\n"

        if listing:
            sheet += f"""
LISTING INFORMATION
{'-' * 60}
List Price: ${listing.list_price:,.0f}
Current Price: ${listing.current_price or listing.list_price:,.0f}
Days on Market: {listing.days_on_market()}
Status: {listing.status}
Listing Views: {listing.views_count}
Inquiries: {listing.inquiries_count}
"""

        sheet += f"\nReport Generated: {date.today().strftime('%B %d, %Y')}\n"
        return sheet


class MarketSnapshotReport:
    """Market snapshot report generation."""

    @staticmethod
    def generate_market_snapshot(market_stats: MarketStats, previous_stats: MarketStats | None = None) -> str:
        """Generate market snapshot report.

        Args:
            market_stats: Current market statistics
            previous_stats: Previous period statistics for comparison

        Returns:
            Formatted market snapshot
        """
        report = f"""
MARKET SNAPSHOT REPORT
{'=' * 60}

Market: {market_stats.area_name}
Report Date: {market_stats.statistic_date.strftime('%B %d, %Y')}

PRICE METRICS
{'-' * 60}
Median Price: ${market_stats.median_price:,.0f}
Average Price: ${market_stats.average_price:,.0f}
Price per Sq Ft: ${market_stats.price_per_sqft:,.2f}
Median Property Size: {market_stats.median_sqft:,} sq ft
"""

        if previous_stats:
            price_change = market_stats.median_price - previous_stats.median_price
            price_pct = price_change / previous_stats.median_price * 100 if previous_stats.median_price != 0 else 0
            report += f"Price Change: ${price_change:+,.0f} ({price_pct:+.1f}%)\n"

        report += f"""
INVENTORY & ACTIVITY
{'-' * 60}
Active Listings: {market_stats.active_listings}
Pending Listings: {market_stats.pending_listings}
Sold (Recent Period): {market_stats.sold_listings_count}
Months of Supply: {market_stats.inventory_months:.1f}
Median Days on Market: {market_stats.median_dom}
"""

        if previous_stats:
            activity_change = market_stats.sold_listings_count - previous_stats.sold_listings_count
            report += f"Sales Change: {activity_change:+d} properties\n"

        report += f"""
MARKET ANALYSIS
{'-' * 60}
Appreciation Rate (YoY): {market_stats.appreciation_rate * 100:.1f}%
Absorption Rate: {market_stats.inventory_months:.1f} months

"""
        if market_stats.inventory_months > 6:
            market_type = "BUYER'S MARKET"
        elif market_stats.inventory_months < 2:
            market_type = "SELLER'S MARKET"
        else:
            market_type = "BALANCED MARKET"

        report += f"Market Type: {market_type}\n\n"
        report += f"Report Generated: {date.today().strftime('%B %d, %Y')}\n"
        return report


class InvestmentAnalysisReport:
    """Investment analysis report generation."""

    @staticmethod
    def generate_investment_report(
        prop: Property,
        purchase_price: Decimal,
        annual_income: Decimal,
        annual_expenses: Decimal,
        mortgage_amount: Decimal = None,
        annual_mortgage_payment: Decimal = None,
    ) -> str:
        """Generate investment analysis report.

        Args:
            prop: Property instance
            purchase_price: Purchase price
            annual_income: Annual rental income
            annual_expenses: Annual operating expenses
            mortgage_amount: Loan amount (optional)
            annual_mortgage_payment: Annual mortgage payment (optional)

        Returns:
            Formatted investment report
        """
        noi = annual_income - annual_expenses
        cap_rate = noi / purchase_price if purchase_price != 0 else Decimal("0")

        report = f"""
INVESTMENT ANALYSIS REPORT
{'=' * 60}

PROPERTY INFORMATION
{'-' * 60}
Address: {prop.address}
Property Type: {prop.property_type.value}
Purchase Price: ${purchase_price:,.0f}

INCOME & EXPENSES
{'-' * 60}
Gross Annual Income: ${annual_income:,.2f}
Operating Expenses: ${annual_expenses:,.2f}
Net Operating Income (NOI): ${noi:,.2f}
NOI Margin: {(noi / annual_income * 100 if annual_income != 0 else 0):.1f}%

RETURN ANALYSIS
{'-' * 60}
Capitalization Rate: {cap_rate * 100:.2f}%
Price per Sq Ft: ${purchase_price / prop.sqft:,.2f}
Price per Bedroom: ${purchase_price / prop.bedrooms:,.2f}
Gross Rent Multiplier: {purchase_price / annual_income:.2f}x

"""

        if mortgage_amount and annual_mortgage_payment:
            cash_flow = noi - annual_mortgage_payment
            dscr = noi / annual_mortgage_payment if annual_mortgage_payment != 0 else 0
            cash_invested = purchase_price - mortgage_amount
            cocr = cash_flow / cash_invested * 100 if cash_invested != 0 else 0

            report += f"""FINANCING ANALYSIS
{'-' * 60}
Loan Amount: ${mortgage_amount:,.0f}
Down Payment: ${cash_invested:,.0f}
LTV: {(mortgage_amount / purchase_price * 100 if purchase_price != 0 else 0):.1f}%
Annual Debt Service: ${annual_mortgage_payment:,.2f}
DSCR: {dscr:.2f}x

CASH FLOW ANALYSIS
{'-' * 60}
Annual Cash Flow: ${cash_flow:,.2f}
Cash-on-Cash Return: {cocr:.2f}%

"""

        report += f"Report Generated: {date.today().strftime('%B %d, %Y')}\n"
        return report


class RentRollReport:
    """Rent roll report generation."""

    @staticmethod
    def generate_rent_roll(leases: list[Lease], property_id: str = None) -> str:
        """Generate rent roll report.

        Args:
            leases: List of leases
            property_id: Optional property filter

        Returns:
            Formatted rent roll report
        """
        if property_id:
            leases = [l for l in leases if l.property_id == property_id]

        active_leases = [l for l in leases if l.status == "active"]

        report = f"""
RENT ROLL REPORT
{'=' * 60}

Report Date: {date.today().strftime('%B %d, %Y')}
Total Leases: {len(leases)}
Active Leases: {len(active_leases)}

LEASE SUMMARY
{'-' * 60}

"""
        total_monthly_rent = Decimal("0")

        for lease in active_leases:
            report += f"""
Lease ID: {lease.lease_id}
Tenant: {lease.tenant_id}
Start Date: {lease.start_date}
End Date: {lease.end_date}
Monthly Rent: ${lease.monthly_rent:,.2f}
CAM Charges: ${lease.cam_charges:,.2f}
Status: {lease.status}

"""
            total_monthly_rent += lease.monthly_rent

        report += f"""
RENT ROLL TOTALS
{'-' * 60}
Total Monthly Rent (Active): ${total_monthly_rent:,.2f}
Total Annual Income: ${total_monthly_rent * 12:,.2f}
Average Rent per Unit: ${(total_monthly_rent / len(active_leases) if active_leases else 0):,.2f}
Occupancy Rate: {(len(active_leases) / len(leases) * 100 if leases else 0):.1f}%

"""
        report += f"Report Generated: {date.today().strftime('%B %d, %Y')}\n"
        return report


class TransactionSummary:
    """Transaction summary report generation."""

    @staticmethod
    def generate_transaction_summary(
        transactions: list[Transaction],
    ) -> str:
        """Generate transaction summary report.

        Args:
            transactions: List of transactions

        Returns:
            Formatted transaction summary
        """
        report = f"""
TRANSACTION SUMMARY REPORT
{'=' * 60}

Report Date: {date.today().strftime('%B %d, %Y')}
Total Transactions: {len(transactions)}

TRANSACTION DETAILS
{'-' * 60}

"""
        total_volume = Decimal("0")
        total_closing_costs = Decimal("0")

        for trans in transactions:
            report += f"""
Transaction ID: {trans.transaction_id}
Property: {trans.property_id}
Purchase Price: ${trans.purchase_price:,.0f}
Closing Date: {trans.purchase_date}
Buyer: {trans.buyer_name}
Seller: {trans.seller_name}
Status: {trans.status}
Closing Costs: ${trans.closing_costs_total:,.2f}

"""
            total_volume += trans.purchase_price
            total_closing_costs += trans.closing_costs_total

        avg_price = total_volume / len(transactions) if transactions else Decimal("0")
        avg_closing_costs = total_closing_costs / len(transactions) if transactions else Decimal("0")

        report += f"""
SUMMARY TOTALS
{'-' * 60}
Total Transaction Volume: ${total_volume:,.0f}
Average Transaction Price: ${avg_price:,.0f}
Total Closing Costs: ${total_closing_costs:,.2f}
Average Closing Costs per Transaction: ${avg_closing_costs:,.2f}
Closing Cost Percentage: {(total_closing_costs / total_volume * 100 if total_volume != 0 else 0):.2f}%

"""
        report += f"Report Generated: {date.today().strftime('%B %d, %Y')}\n"
        return report


class PortfolioPerformanceSummary:
    """Portfolio performance summary generation."""

    @staticmethod
    def generate_portfolio_summary(
        properties: list[Property],
        total_value: Decimal,
        annual_income: Decimal,
        annual_expenses: Decimal,
    ) -> str:
        """Generate portfolio performance summary.

        Args:
            properties: List of properties in portfolio
            total_value: Total portfolio value
            annual_income: Total annual income
            annual_expenses: Total annual expenses

        Returns:
            Formatted portfolio summary
        """
        noi = annual_income - annual_expenses
        overall_cap_rate = noi / total_value if total_value != 0 else Decimal("0")

        report = f"""
PORTFOLIO PERFORMANCE SUMMARY
{'=' * 60}

Report Date: {date.today().strftime('%B %d, %Y')}

PORTFOLIO OVERVIEW
{'-' * 60}
Total Properties: {len(properties)}
Total Portfolio Value: ${total_value:,.0f}
Average Property Value: ${(total_value / len(properties) if properties else 0):,.0f}

INCOME ANALYSIS
{'-' * 60}
Gross Annual Income: ${annual_income:,.2f}
Annual Operating Expenses: ${annual_expenses:,.2f}
Net Operating Income: ${noi:,.2f}
Overall Cap Rate: {overall_cap_rate * 100:.2f}%
Income per Property: ${(annual_income / len(properties) if properties else 0):,.2f}

PROPERTY BREAKDOWN
{'-' * 60}

"""
        for prop in properties:
            allocation = (Decimal(1) / len(properties)) * 100
            report += f"{prop.address}: {allocation:.1f}% of portfolio\n"

        report += f"\nReport Generated: {date.today().strftime('%B %d, %Y')}\n"
        return report
