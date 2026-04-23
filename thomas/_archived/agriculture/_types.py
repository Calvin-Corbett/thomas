"""Core data types for agricultural management system.

Defines all primary data structures for farms, fields, crops, soil, weather,
irrigation, nutrients, pests, harvests, equipment, sensors, and livestock.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum


class CropFamily(Enum):
    """Plant family classification for crop rotation."""

    SOLANACEAE = "Solanaceae"  # Tomato, pepper, potato
    BRASSICACEAE = "Brassicaceae"  # Cabbage, broccoli, canola
    FABACEAE = "Fabaceae"  # Legume, pea, bean
    POACEAE = "Poaceae"  # Grain, wheat, corn
    APIACEAE = "Apiaceae"  # Carrot, celery, parsnip
    CUCURBITACEAE = "Cucurbitaceae"  # Squash, melon, cucumber
    ASTERACEAE = "Asteraceae"  # Sunflower, lettuce
    CHENOPODIACEAE = "Chenopodiaceae"  # Beet, spinach, chard


class GrowthStage(Enum):
    """Crop growth stage based on BBCH scale."""

    DORMANCY = "Dormancy"
    GERMINATION = "Germination"
    VEGETATIVE = "Vegetative"
    FLOWERING = "Flowering"
    GRAIN_FILL = "Grain Fill"
    MATURITY = "Maturity"
    HARVEST = "Harvest"


class SoilTexture(Enum):
    """USDA soil texture classification."""

    SAND = "Sand"
    LOAMY_SAND = "Loamy Sand"
    SANDY_LOAM = "Sandy Loam"
    LOAM = "Loam"
    SILT_LOAM = "Silt Loam"
    SILT = "Silt"
    SANDY_CLAY_LOAM = "Sandy Clay Loam"
    CLAY_LOAM = "Clay Loam"
    SILTY_CLAY_LOAM = "Silty Clay Loam"
    SANDY_CLAY = "Sandy Clay"
    SILTY_CLAY = "Silty Clay"
    CLAY = "Clay"


class IrrigationType(Enum):
    """Irrigation system type."""

    FLOOD = "Flood"
    FURROW = "Furrow"
    SPRINKLER = "Sprinkler"
    CENTER_PIVOT = "Center Pivot"
    DRIP = "Drip"
    MICRO = "Micro"


class FertilizerType(Enum):
    """Fertilizer classification."""

    SYNTHETIC = "Synthetic"
    ORGANIC = "Organic"
    MANURE = "Manure"
    BLENDED = "Blended"
    LIQUID = "Liquid"
    GRANULAR = "Granular"


class PestType(Enum):
    """Agricultural pest classification."""

    INSECT = "Insect"
    DISEASE = "Disease"
    WEED = "Weed"
    NEMATODE = "Nematode"
    VERTEBRATE = "Vertebrate"


class TreatmentMethod(Enum):
    """Pest treatment application method."""

    SPRAY = "Spray"
    SOIL_APPLICATION = "Soil Application"
    SEED_TREATMENT = "Seed Treatment"
    MECHANICAL = "Mechanical"
    BIOLOGICAL = "Biological"
    CULTURAL = "Cultural"


class LivestockType(Enum):
    """Livestock species classification."""

    CATTLE = "Cattle"
    SWINE = "Swine"
    POULTRY = "Poultry"
    SHEEP = "Sheep"
    GOAT = "Goat"
    HORSE = "Horse"


@dataclass
class Farm:
    """Represents a farm operation with location and basic information.

    Attributes:
        farm_id: Unique farm identifier
        name: Farm name
        location: (latitude, longitude) in decimal degrees
        total_acres: Total farm size in acres
        operator_name: Farm operator name
        established_date: Farm establishment date
        irrigation_available: Whether irrigation infrastructure exists
    """

    farm_id: str
    name: str
    location: tuple[float, float]
    total_acres: float
    operator_name: str
    established_date: date
    irrigation_available: bool = False
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class CropVariety:
    """A specific crop variety with growing requirements.

    Attributes:
        variety_id: Unique identifier
        name: Variety name (e.g., "Pioneer P1197AM")
        crop_type: Crop type (e.g., "Corn")
        family: Plant family for rotation
        days_to_maturity: Days from emergence to maturity
        gdd_required: Growing degree days needed
        temp_min: Minimum germination temperature (Celsius)
        temp_opt: Optimal growing temperature (Celsius)
        temp_max: Maximum tolerable temperature (Celsius)
        water_requirement_in: Water need in inches per season
        nitrogen_lbs_per_acre: Recommended N application rate
        phosphorus_lbs_per_acre: Recommended P2O5 application
        potassium_lbs_per_acre: Recommended K2O application
    """

    variety_id: str
    name: str
    crop_type: str
    family: CropFamily
    days_to_maturity: int
    gdd_required: float
    temp_min: float
    temp_opt: float
    temp_max: float
    water_requirement_in: float
    nitrogen_lbs_per_acre: float
    phosphorus_lbs_per_acre: float
    potassium_lbs_per_acre: float


@dataclass
class Crop:
    """A crop planting on a field.

    Attributes:
        crop_id: Unique identifier
        field_id: Associated field
        variety: CropVariety planted
        planting_date: Date seeds/transplants placed
        emergence_date: Date seedlings emerged
        growth_stage: Current growth stage
        gdd_accumulated: Growing degree days accumulated
        yield_goal_bu_per_acre: Target yield for enterprise budget
    """

    crop_id: str
    field_id: str
    variety: CropVariety
    planting_date: date
    emergence_date: date | None = None
    growth_stage: GrowthStage = GrowthStage.DORMANCY
    gdd_accumulated: float = 0.0
    yield_goal_bu_per_acre: float = 0.0


@dataclass
class Soil:
    """Soil properties for a field.

    Attributes:
        soil_id: Unique identifier
        field_id: Associated field
        sand_pct: Sand percentage (0-100)
        silt_pct: Silt percentage (0-100)
        clay_pct: Clay percentage (0-100)
        texture: USDA soil texture class
        ph: Soil pH (0-14)
        organic_matter_pct: Organic matter percentage
        test_date: Date of soil test
        nitrate_n_ppm: Nitrate-N concentration
        phosphorus_lbs_acre: Phosphorus (Olsen method)
        potassium_lbs_acre: Potassium (K)
        calcium_lbs_acre: Calcium (Ca)
        magnesium_lbs_acre: Magnesium (Mg)
        sulfur_lbs_acre: Sulfur (S)
        cec_meq_per_100g: Cation Exchange Capacity
    """

    soil_id: str
    field_id: str
    sand_pct: float
    silt_pct: float
    clay_pct: float
    texture: SoilTexture
    ph: float
    organic_matter_pct: float
    test_date: date
    nitrate_n_ppm: float
    phosphorus_lbs_acre: float
    potassium_lbs_acre: float
    calcium_lbs_acre: float
    magnesium_lbs_acre: float
    sulfur_lbs_acre: float
    cec_meq_per_100g: float


@dataclass
class Field:
    """A field within a farm.

    Attributes:
        field_id: Unique identifier
        farm_id: Parent farm
        name: Field name
        acres: Field size in acres
        elevation_ft: Average elevation
        slope_pct: Average slope percentage
        last_crop: Previous crop grown
        days_since_harvest: Days since last harvest
    """

    field_id: str
    farm_id: str
    name: str
    acres: float
    elevation_ft: float
    slope_pct: float
    last_crop: str | None = None
    days_since_harvest: int = 0


@dataclass
class Weather:
    """Daily weather observation or forecast.

    Attributes:
        weather_id: Unique identifier
        location: (latitude, longitude)
        date: Date of observation
        temp_max_f: Maximum temperature
        temp_min_f: Minimum temperature
        temp_avg_f: Average temperature
        precipitation_in: Rainfall amount
        wind_speed_mph: Average wind speed
        relative_humidity_pct: Relative humidity
        solar_radiation_ly: Solar radiation
        is_forecast: True if forecast, False if observed
    """

    weather_id: str
    location: tuple[float, float]
    date: date
    temp_max_f: float
    temp_min_f: float
    temp_avg_f: float
    precipitation_in: float
    wind_speed_mph: float
    relative_humidity_pct: float
    solar_radiation_ly: float
    is_forecast: bool = False


@dataclass
class Irrigation:
    """Irrigation event record.

    Attributes:
        irrigation_id: Unique identifier
        field_id: Field irrigated
        irrigation_type: Irrigation method
        application_depth_in: Water applied in inches
        application_date: Date of application
        efficiency_pct: Application efficiency (0-100)
        pump_size_gpm: Pump capacity
        duration_hours: Application duration
    """

    irrigation_id: str
    field_id: str
    irrigation_type: IrrigationType
    application_depth_in: float
    application_date: date
    efficiency_pct: float
    pump_size_gpm: float
    duration_hours: float


@dataclass
class Fertilizer:
    """Fertilizer application record.

    Attributes:
        fertilizer_id: Unique identifier
        field_id: Field receiving fertilizer
        product_name: Fertilizer product name
        fertilizer_type: Product classification
        nitrogen_pct: N percentage
        phosphorus_pct: P2O5 percentage
        potassium_pct: K2O percentage
        application_rate_lbs_acre: Pounds per acre applied
        application_date: Date applied
        method: Application method
    """

    fertilizer_id: str
    field_id: str
    product_name: str
    fertilizer_type: FertilizerType
    nitrogen_pct: float
    phosphorus_pct: float
    potassium_pct: float
    application_rate_lbs_acre: float
    application_date: date
    method: str


@dataclass
class Pesticide:
    """Pesticide application record.

    Attributes:
        pesticide_id: Unique identifier
        field_id: Field treated
        product_name: Pesticide product name
        pest_type: Type of pest targeted
        target_pest: Specific pest name
        application_rate: Rate of application (units/acre)
        application_date: Date applied
        treatment_method: Application method
    """

    pesticide_id: str
    field_id: str
    product_name: str
    pest_type: PestType
    target_pest: str
    application_rate: float
    application_date: date
    treatment_method: TreatmentMethod


@dataclass
class Harvest:
    """Harvest event record.

    Attributes:
        harvest_id: Unique identifier
        field_id: Field harvested
        crop_id: Crop harvested
        harvest_date: Date of harvest
        yield_bu_per_acre: Yield achieved
        total_yield_bu: Total bushels harvested
        moisture_pct: Grain moisture at harvest
        test_weight_lbs_bu: Test weight of grain
    """

    harvest_id: str
    field_id: str
    crop_id: str
    harvest_date: date
    yield_bu_per_acre: float
    total_yield_bu: float
    moisture_pct: float
    test_weight_lbs_bu: float


@dataclass
class Equipment:
    """Farm equipment record.

    Attributes:
        equipment_id: Unique identifier
        farm_id: Farm that owns equipment
        name: Equipment name/model
        equipment_type: Type of equipment
        purchase_date: Date purchased
        purchase_price: Original purchase price
        hours_operated: Total operating hours
        fuel_consumption_gph: Gallons per hour fuel use
    """

    equipment_id: str
    farm_id: str
    name: str
    equipment_type: str
    purchase_date: date
    purchase_price: Decimal
    hours_operated: float
    fuel_consumption_gph: float


@dataclass
class SensorReading:
    """Data from soil or plant sensor.

    Attributes:
        reading_id: Unique identifier
        field_id: Field being monitored
        sensor_type: Type of sensor (soil moisture, pH, etc.)
        measurement_value: Measured value
        measurement_unit: Unit of measurement
        reading_datetime: Timestamp of reading
        sensor_depth_in: Depth of measurement if soil
    """

    reading_id: str
    field_id: str
    sensor_type: str
    measurement_value: float
    measurement_unit: str
    reading_datetime: datetime
    sensor_depth_in: float | None = None


@dataclass
class SatelliteImage:
    """Satellite imagery record for a field.

    Attributes:
        image_id: Unique identifier
        field_id: Field imaged
        image_date: Date of image capture
        ndvi_min: Minimum NDVI value in field
        ndvi_max: Maximum NDVI value in field
        ndvi_mean: Mean NDVI value
        ndvi_std: Standard deviation of NDVI
        cloud_cover_pct: Percentage cloud cover
        data_source: Source (Sentinel, Landsat, etc.)
    """

    image_id: str
    field_id: str
    image_date: date
    ndvi_min: float
    ndvi_max: float
    ndvi_mean: float
    ndvi_std: float
    cloud_cover_pct: float
    data_source: str


@dataclass
class YieldPrediction:
    """Predicted crop yield for a field.

    Attributes:
        prediction_id: Unique identifier
        field_id: Field being predicted
        crop_id: Crop being predicted
        prediction_date: Date prediction made
        predicted_yield_bu_acre: Predicted yield
        confidence_pct: Confidence level (0-100)
        model_used: Model name used for prediction
    """

    prediction_id: str
    field_id: str
    crop_id: str
    prediction_date: date
    predicted_yield_bu_acre: float
    confidence_pct: float
    model_used: str


@dataclass
class MarketPrice:
    """Market price observation for a commodity.

    Attributes:
        price_id: Unique identifier
        commodity: Commodity name (e.g., "Corn", "Soybeans")
        price_date: Date of price
        price_per_bu: Price per bushel
        futures_month: Futures contract month if applicable
        data_source: Source of price data
    """

    price_id: str
    commodity: str
    price_date: date
    price_per_bu: float
    futures_month: str | None = None
    data_source: str = "USDA"


@dataclass
class LivestockAnimal:
    """Individual livestock animal record.

    Attributes:
        animal_id: Unique identifier (tag/ID)
        farm_id: Farm that owns animal
        livestock_type: Type of livestock
        birth_date: Birth date
        weight_lbs: Current weight
        body_condition_score: BCS (1-9 scale)
        dam_id: Mother's animal ID
        sire_id: Father's animal ID
        last_breeding_date: Last breeding event date
    """

    animal_id: str
    farm_id: str
    livestock_type: LivestockType
    birth_date: date
    weight_lbs: float
    body_condition_score: float
    dam_id: str | None = None
    sire_id: str | None = None
    last_breeding_date: date | None = None
