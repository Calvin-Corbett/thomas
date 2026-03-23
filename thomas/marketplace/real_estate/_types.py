"""Type definitions for real estate platform."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum


class PropertyType(str, Enum):
    """Property type enumeration."""

    SINGLE_FAMILY = "single_family"
    MULTI_FAMILY = "multi_family"
    COMMERCIAL = "commercial"
    INDUSTRIAL = "industrial"
    LAND = "land"
    MIXED_USE = "mixed_use"


class ZoningType(str, Enum):
    """Zoning type enumeration."""

    RESIDENTIAL = "residential"
    COMMERCIAL = "commercial"
    INDUSTRIAL = "industrial"
    AGRICULTURAL = "agricultural"
    MIXED_USE = "mixed_use"


@dataclass
class Address:
    """Property address information.

    Attributes:
        street: Street address line
        city: City name
        state: State abbreviation
        zip_code: Postal code
        county: County name
        latitude: Geographic latitude
        longitude: Geographic longitude
    """

    street: str
    city: str
    state: str
    zip_code: str
    county: str | None = None
    latitude: float | None = None
    longitude: float | None = None

    def __str__(self) -> str:
        """Return formatted address string."""
        return f"{self.street}, {self.city}, {self.state} {self.zip_code}"

    def has_coordinates(self) -> bool:
        """Check if address has geographic coordinates."""
        return self.latitude is not None and self.longitude is not None


@dataclass
class Agent:
    """Real estate agent information.

    Attributes:
        agent_id: Unique agent identifier
        name: Agent full name
        email: Contact email address
        phone: Contact phone number
        license_number: Real estate license number
        brokerage: Brokerage firm name
        specialties: List of property type specialties
        years_experience: Years in real estate business
    """

    agent_id: str
    name: str
    email: str
    phone: str
    license_number: str
    brokerage: str
    specialties: list[PropertyType] = field(default_factory=list)
    years_experience: int = 0


@dataclass
class Inspection:
    """Property inspection information.

    Attributes:
        inspection_id: Unique inspection identifier
        property_id: Associated property identifier
        inspector_name: Name of inspector
        inspection_date: Date of inspection
        report_url: URL to full inspection report
        major_issues: List of major issues found
        estimated_repairs: Estimated repair costs
        overall_condition: Overall condition assessment (1-10 scale)
    """

    inspection_id: str
    property_id: str
    inspector_name: str
    inspection_date: date
    report_url: str
    major_issues: list[str] = field(default_factory=list)
    estimated_repairs: Decimal = Decimal("0")
    overall_condition: int = 5


@dataclass
class Appraisal:
    """Property appraisal information.

    Attributes:
        appraisal_id: Unique appraisal identifier
        property_id: Associated property identifier
        appraiser_name: Name of appraiser
        appraisal_date: Date of appraisal
        appraised_value: Appraised property value
        report_url: URL to full appraisal report
        approach_values: Dictionary of valuation approaches (CMA, cost, income)
    """

    appraisal_id: str
    property_id: str
    appraiser_name: str
    appraisal_date: date
    appraised_value: Decimal
    report_url: str
    approach_values: dict[str, Decimal] = field(default_factory=dict)


@dataclass
class Comparable:
    """Comparable property for valuation analysis.

    Attributes:
        comparable_id: Unique comparable identifier
        address: Property address
        sale_price: Sale price
        sale_date: Date of sale
        sqft: Square footage
        bedrooms: Number of bedrooms
        bathrooms: Number of bathrooms
        age_years: Property age in years
        condition: Condition rating (1-10)
        sold_date: When property sold (for market timing)
    """

    comparable_id: str
    address: Address
    sale_price: Decimal
    sale_date: date
    sqft: int
    bedrooms: int
    bathrooms: Decimal
    age_years: int
    condition: int
    days_on_market: int | None = None


@dataclass
class Property:
    """Property information and characteristics.

    Attributes:
        property_id: Unique property identifier
        address: Property address
        property_type: Type of property
        zoning_type: Zoning classification
        bedrooms: Number of bedrooms
        bathrooms: Number of bathrooms
        sqft: Total square footage
        lot_sqft: Lot size in square feet
        year_built: Year property was constructed
        last_sale_price: Last recorded sale price
        last_sale_date: Date of last sale
        current_owner: Current property owner name
        assessed_value: Tax assessed value
        annual_tax: Annual property tax amount
        hoa_fee: Monthly HOA fee if applicable
        features: List of property features
        ownership_history: List of previous owners with dates
    """

    property_id: str
    address: Address
    property_type: PropertyType
    zoning_type: ZoningType
    bedrooms: int
    bathrooms: Decimal
    sqft: int
    lot_sqft: int
    year_built: int
    last_sale_price: Decimal | None = None
    last_sale_date: date | None = None
    current_owner: str | None = None
    assessed_value: Decimal = Decimal("0")
    annual_tax: Decimal = Decimal("0")
    hoa_fee: Decimal = Decimal("0")
    features: list[str] = field(default_factory=list)
    ownership_history: list[tuple[str, date, date]] = field(default_factory=list)

    def age_years(self) -> int:
        """Calculate property age in years."""
        return date.today().year - self.year_built


@dataclass
class Listing:
    """MLS-style property listing.

    Attributes:
        listing_id: Unique listing identifier
        property_id: Associated property identifier
        agent_id: Listing agent identifier
        list_date: Date listing became active
        list_price: Initial listing price
        current_price: Current asking price
        status: Listing status
        description: Full listing description
        marketing_keywords: Keywords for marketing
        photo_urls: URLs to listing photos
        open_houses: List of open house dates
        views_count: Number of listing views
        saves_count: Number of times saved
        inquiries_count: Number of inquiries received
        price_reductions: List of price changes with dates
    """

    listing_id: str
    property_id: str
    agent_id: str
    list_date: date
    list_price: Decimal
    status: str  # "active", "pending", "sold", "withdrawn", "expired"
    description: str = ""
    marketing_keywords: list[str] = field(default_factory=list)
    photo_urls: list[str] = field(default_factory=list)
    open_houses: list[date] = field(default_factory=list)
    current_price: Decimal | None = None
    views_count: int = 0
    saves_count: int = 0
    inquiries_count: int = 0
    price_reductions: list[tuple[Decimal, date]] = field(default_factory=list)

    def days_on_market(self) -> int:
        """Calculate days on market."""
        return (date.today() - self.list_date).days

    def price_reduction_total(self) -> Decimal:
        """Calculate total price reduction from original list price."""
        if not self.price_reductions:
            current = self.current_price or self.list_price
            return self.list_price - current
        return self.list_price - self.price_reductions[-1][0]


@dataclass
class Tenant:
    """Rental tenant information.

    Attributes:
        tenant_id: Unique tenant identifier
        name: Full name
        email: Email address
        phone: Phone number
        credit_score: Credit score
        annual_income: Annual income
        rental_history: List of previous rental periods
        background_check: Background check completion status
        screening_score: Calculated screening score
    """

    tenant_id: str
    name: str
    email: str
    phone: str
    credit_score: int
    annual_income: Decimal
    rental_history: list[tuple[str, date, date]] = field(default_factory=list)
    background_check: bool = False
    screening_score: float | None = None


@dataclass
class Lease:
    """Lease agreement information.

    Attributes:
        lease_id: Unique lease identifier
        property_id: Associated property identifier
        tenant_id: Associated tenant identifier
        start_date: Lease start date
        end_date: Lease end date
        monthly_rent: Monthly rent amount
        security_deposit: Security deposit amount
        lease_type: "residential" or "commercial"
        status: Lease status (active, month_to_month, terminated)
        rent_escalation: Annual rent increase percentage
        cam_charges: Common area maintenance charges
        lease_terms: Dictionary of custom lease terms
    """

    lease_id: str
    property_id: str
    tenant_id: str
    start_date: date
    end_date: date
    monthly_rent: Decimal
    security_deposit: Decimal
    lease_type: str  # "residential" or "commercial"
    status: str = "active"  # "active", "month_to_month", "terminated"
    rent_escalation: Decimal = Decimal("0")
    cam_charges: Decimal = Decimal("0")
    lease_terms: dict[str, str] = field(default_factory=dict)

    def is_month_to_month(self) -> bool:
        """Check if lease is month-to-month."""
        return self.status == "month_to_month"

    def days_remaining(self) -> int:
        """Calculate days remaining on lease."""
        remaining = (self.end_date - date.today()).days
        return max(0, remaining)


@dataclass
class Mortgage:
    """Mortgage loan information.

    Attributes:
        mortgage_id: Unique mortgage identifier
        property_id: Associated property identifier
        principal: Original loan amount
        interest_rate: Annual interest rate (as decimal, e.g., 0.065 for 6.5%)
        term_months: Loan term in months
        start_date: Loan start date
        monthly_payment: Calculated monthly payment
        loan_type: "fixed" or "adjustable"
        points: Discount points paid
        closing_costs: Total closing costs
    """

    mortgage_id: str
    property_id: str
    principal: Decimal
    interest_rate: Decimal
    term_months: int
    start_date: date
    monthly_payment: Decimal = Decimal("0")
    loan_type: str = "fixed"
    points: Decimal = Decimal("0")
    closing_costs: Decimal = Decimal("0")


@dataclass
class Offer:
    """Purchase offer information.

    Attributes:
        offer_id: Unique offer identifier
        property_id: Associated property identifier
        buyer_agent_id: Buyer's agent identifier
        listing_agent_id: Listing agent identifier
        offer_price: Offered purchase price
        offer_date: Date offer was submitted
        earnest_money: Earnest money deposit amount
        contingencies: List of contingencies (inspection, financing, appraisal)
        contingency_deadlines: Dictionary of contingency deadlines
        status: Offer status (submitted, countered, accepted, rejected, withdrawn)
        closing_date: Proposed closing date
    """

    offer_id: str
    property_id: str
    buyer_agent_id: str
    listing_agent_id: str
    offer_price: Decimal
    offer_date: date
    earnest_money: Decimal = Decimal("0")
    contingencies: list[str] = field(default_factory=list)
    contingency_deadlines: dict[str, date] = field(default_factory=dict)
    status: str = "submitted"  # submitted, countered, accepted, rejected, withdrawn
    closing_date: date | None = None


@dataclass
class Commission:
    """Real estate commission information.

    Attributes:
        commission_id: Unique commission identifier
        transaction_id: Associated transaction identifier
        listing_agent_id: Listing agent identifier
        selling_agent_id: Selling agent identifier
        listing_broker_id: Listing broker identifier
        selling_broker_id: Selling broker identifier
        total_commission: Total commission amount
        commission_rate: Commission rate as decimal (e.g., 0.06 for 6%)
        listing_agent_split: Listing agent's share percentage
        broker_split: Broker's share percentage
        paid_date: Date commission was paid
    """

    commission_id: str
    transaction_id: str
    listing_agent_id: str
    selling_agent_id: str
    listing_broker_id: str
    selling_broker_id: str
    total_commission: Decimal
    commission_rate: Decimal
    listing_agent_split: Decimal = Decimal("50")
    broker_split: Decimal = Decimal("50")
    paid_date: date | None = None


@dataclass
class Transaction:
    """Real estate transaction information.

    Attributes:
        transaction_id: Unique transaction identifier
        property_id: Associated property identifier
        offer_id: Associated offer identifier
        purchase_price: Final purchase price
        purchase_date: Closing/purchase date
        title_insurance_cost: Title insurance premium
        transfer_tax: Transfer/deed tax
        recording_fees: Recording and filing fees
        closing_costs_total: Total closing costs
        buyer_name: Buyer name
        seller_name: Seller name
        buyer_agent_id: Buyer agent identifier
        seller_agent_id: Seller agent identifier
        mortgage_id: Associated mortgage identifier
        status: Transaction status (pending, closed, cancelled)
    """

    transaction_id: str
    property_id: str
    offer_id: str
    purchase_price: Decimal
    purchase_date: date
    buyer_name: str
    seller_name: str
    buyer_agent_id: str
    seller_agent_id: str
    title_insurance_cost: Decimal = Decimal("0")
    transfer_tax: Decimal = Decimal("0")
    recording_fees: Decimal = Decimal("0")
    closing_costs_total: Decimal = Decimal("0")
    mortgage_id: str | None = None
    status: str = "closed"  # pending, closed, cancelled


@dataclass
class MarketStats:
    """Market statistics for a geographic area.

    Attributes:
        market_id: Unique market identifier
        area_name: Geographic area name
        statistic_date: Date statistics were calculated
        median_price: Median property price
        average_price: Average property price
        median_sqft: Median square footage
        active_listings: Number of active listings
        pending_listings: Number of pending listings
        sold_listings_count: Number of sold properties in period
        median_dom: Median days on market
        inventory_months: Months of inventory (absorption rate)
        price_per_sqft: Average price per square foot
        appreciation_rate: Year-over-year price appreciation
    """

    market_id: str
    area_name: str
    statistic_date: date
    median_price: Decimal
    average_price: Decimal
    median_sqft: int
    active_listings: int
    pending_listings: int
    sold_listings_count: int
    median_dom: int
    inventory_months: Decimal
    price_per_sqft: Decimal
    appreciation_rate: Decimal = Decimal("0")
