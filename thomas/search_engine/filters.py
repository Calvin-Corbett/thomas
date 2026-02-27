"""Post-retrieval filtering for search results."""

import math
from abc import ABC, abstractmethod
from typing import Any


class SearchFilter(ABC):
    """Base class for search result filters."""

    @abstractmethod
    def matches(self, doc: dict[str, Any]) -> bool:
        """Check if document matches filter."""
        pass


class RangeFilter(SearchFilter):
    """Filter by numeric range."""

    def __init__(
        self, field: str, min_value: float | None = None, max_value: float | None = None, inclusive: bool = True
    ) -> None:
        """Initialize range filter."""
        self.field = field
        self.min_value = min_value
        self.max_value = max_value
        self.inclusive = inclusive

    def matches(self, doc: dict[str, Any]) -> bool:
        """Check if document value is in range."""
        if self.field not in doc:
            return False

        try:
            value = float(doc[self.field])
        except (ValueError, TypeError):
            return False

        if self.min_value is not None:
            if self.inclusive:
                if value < self.min_value:
                    return False
            else:
                if value <= self.min_value:
                    return False

        if self.max_value is not None:
            if self.inclusive:
                if value > self.max_value:
                    return False
            else:
                if value >= self.max_value:
                    return False

        return True


class DateRangeFilter(SearchFilter):
    """Filter by date range."""

    def __init__(self, field: str, start_date: str | None = None, end_date: str | None = None) -> None:
        """Initialize date range filter."""
        self.field = field
        self.start_date = start_date
        self.end_date = end_date

    def matches(self, doc: dict[str, Any]) -> bool:
        """Check if document date is in range."""
        if self.field not in doc:
            return False

        date_str = str(doc[self.field])

        if self.start_date and date_str < self.start_date:
            return False

        if self.end_date and date_str > self.end_date:
            return False

        return True


class TermFilter(SearchFilter):
    """Filter by exact term match."""

    def __init__(self, field: str, value: Any) -> None:
        """Initialize term filter."""
        self.field = field
        self.value = value

    def matches(self, doc: dict[str, Any]) -> bool:
        """Check if document matches term."""
        if self.field not in doc:
            return False
        return str(doc[self.field]).lower() == str(self.value).lower()


class TermsFilter(SearchFilter):
    """Filter by multiple term values."""

    def __init__(self, field: str, values: list[Any]) -> None:
        """Initialize terms filter."""
        self.field = field
        self.values = {str(v).lower() for v in values}

    def matches(self, doc: dict[str, Any]) -> bool:
        """Check if document matches any term."""
        if self.field not in doc:
            return False
        return str(doc[self.field]).lower() in self.values


class BooleanFilter(SearchFilter):
    """Filter by boolean field value."""

    def __init__(self, field: str, value: bool) -> None:
        """Initialize boolean filter."""
        self.field = field
        self.value = value

    def matches(self, doc: dict[str, Any]) -> bool:
        """Check if document boolean matches."""
        if self.field not in doc:
            return False

        doc_value = doc[self.field]
        if isinstance(doc_value, bool):
            return doc_value == self.value
        elif isinstance(doc_value, str):
            return doc_value.lower() in ("true", "yes", "1") == self.value
        else:
            return bool(doc_value) == self.value


class GeoDistanceFilter(SearchFilter):
    """Filter by geographic distance using haversine formula."""

    def __init__(self, field: str, latitude: float, longitude: float, distance_km: float) -> None:
        """Initialize geo distance filter."""
        self.field = field
        self.latitude = latitude
        self.longitude = longitude
        self.distance_km = distance_km

    def matches(self, doc: dict[str, Any]) -> bool:
        """Check if document is within distance."""
        if self.field not in doc:
            return False

        doc_value = doc[self.field]
        if isinstance(doc_value, dict) and "lat" in doc_value and "lon" in doc_value:
            doc_lat = float(doc_value["lat"])
            doc_lon = float(doc_value["lon"])
        elif isinstance(doc_value, (list, tuple)) and len(doc_value) >= 2:
            doc_lat, doc_lon = float(doc_value[0]), float(doc_value[1])
        else:
            return False

        distance = self._haversine_distance(self.latitude, self.longitude, doc_lat, doc_lon)
        return distance <= self.distance_km

    @staticmethod
    def _haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate distance between two points in kilometers."""
        R = 6371  # Earth radius in km

        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        delta_lat = math.radians(lat2 - lat1)
        delta_lon = math.radians(lon2 - lon1)

        a = math.sin(delta_lat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2
        c = 2 * math.asin(math.sqrt(a))

        return R * c


class CachedFilter(SearchFilter):
    """Caches filter results for repeated use."""

    def __init__(self, base_filter: SearchFilter) -> None:
        """Initialize cached filter."""
        self.base_filter = base_filter
        self._cache: dict[int, bool] = {}

    def matches(self, doc: dict[str, Any]) -> bool:
        """Check using cache."""
        # Create cache key from doc contents
        cache_key = hash(frozenset(doc.items()))
        if cache_key not in self._cache:
            self._cache[cache_key] = self.base_filter.matches(doc)
        return self._cache[cache_key]

    def clear_cache(self) -> None:
        """Clear the cache."""
        self._cache.clear()


class FilterComposition:
    """Combines multiple filters with AND/OR/NOT logic."""

    def __init__(self) -> None:
        """Initialize composition."""
        self.and_filters: list[SearchFilter] = []
        self.or_filters: list[SearchFilter] = []
        self.not_filters: list[SearchFilter] = []

    def add_and(self, filter_obj: SearchFilter) -> "FilterComposition":
        """Add AND filter."""
        self.and_filters.append(filter_obj)
        return self

    def add_or(self, filter_obj: SearchFilter) -> "FilterComposition":
        """Add OR filter."""
        self.or_filters.append(filter_obj)
        return self

    def add_not(self, filter_obj: SearchFilter) -> "FilterComposition":
        """Add NOT filter."""
        self.not_filters.append(filter_obj)
        return self

    def matches(self, doc: dict[str, Any]) -> bool:
        """Check if document matches composition."""
        # ALL AND filters must match
        for filter_obj in self.and_filters:
            if not filter_obj.matches(doc):
                return False

        # At least ONE OR filter must match (if any)
        if self.or_filters:
            or_match = False
            for filter_obj in self.or_filters:
                if filter_obj.matches(doc):
                    or_match = True
                    break
            if not or_match:
                return False

        # NONE of the NOT filters should match
        for filter_obj in self.not_filters:
            if filter_obj.matches(doc):
                return False

        return True


class FilteredSearch:
    """Applies filters to search results."""

    def __init__(self) -> None:
        """Initialize filtered search."""
        self.filters: list[SearchFilter] = []

    def add_filter(self, filter_obj: SearchFilter) -> None:
        """Add filter."""
        self.filters.append(filter_obj)

    def apply_filters(self, docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Filter document list."""
        result = docs
        for filter_obj in self.filters:
            result = [doc for doc in result if filter_obj.matches(doc)]
        return result

    def filter_count(self, docs: list[dict[str, Any]]) -> dict[str, int]:
        """Count documents matching each filter."""
        counts = {}
        for i, filter_obj in enumerate(self.filters):
            matches = sum(1 for doc in docs if filter_obj.matches(doc))
            counts[f"filter_{i}"] = matches
        return counts
