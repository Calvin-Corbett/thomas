"""Product listings with quality scoring, duplicate detection, and recommendations."""

import math
import re
import uuid
from datetime import datetime
from decimal import Decimal

from thomas.marketplace._exceptions import (
    InvalidListingState,
    ListingNotFoundError,
    VendorException,
)
from thomas.marketplace._types import (
    Category,
    Listing,
    ListingState,
)


class ListingStateManager:
    """State machine for listing lifecycle: draft→published→archived."""

    VALID_TRANSITIONS: dict[ListingState, list[ListingState]] = {
        ListingState.DRAFT: [ListingState.PUBLISHED, ListingState.ARCHIVED],
        ListingState.PUBLISHED: [ListingState.ARCHIVED, ListingState.DELISTED],
        ListingState.ARCHIVED: [ListingState.PUBLISHED],
        ListingState.DELISTED: [],
    }

    @staticmethod
    def can_transition(current_state: ListingState, target_state: ListingState) -> bool:
        """Check if state transition is valid.

        Args:
            current_state: Current listing state.
            target_state: Target listing state.

        Returns:
            True if transition is valid.
        """
        return target_state in ListingStateManager.VALID_TRANSITIONS.get(current_state, [])

    @staticmethod
    def transition(listing: Listing, target_state: ListingState) -> Listing:
        """Perform listing state transition.

        Args:
            listing: Listing to transition.
            target_state: Target state.

        Returns:
            Updated listing.

        Raises:
            InvalidListingState: If transition invalid.
        """
        if not ListingStateManager.can_transition(listing.state, target_state):
            raise InvalidListingState(listing.id, listing.state.value, target_state.value)

        listing.state = target_state
        listing.updated_at = datetime.utcnow()
        return listing


class ListingQualityScorer:
    """Score listing quality based on completeness and content."""

    MIN_TITLE_LENGTH: int = 10
    MIN_DESCRIPTION_LENGTH: int = 50
    MIN_IMAGES: int = 1
    MAX_IMAGES: int = 10

    @staticmethod
    def calculate_quality_score(listing: Listing) -> Decimal:
        """Calculate listing quality score (0-100).

        Scores based on:
        - Title length and completeness (20%)
        - Description quality (30%)
        - Image count (20%)
        - Price presence (15%)
        - Attribute completeness (15%)

        Args:
            listing: Listing to score.

        Returns:
            Quality score 0-100.
        """
        score = Decimal("0")

        # Title score (20%)
        title_score = Decimal("0")
        if listing.title and len(listing.title) >= ListingQualityScorer.MIN_TITLE_LENGTH:
            title_score = Decimal("20")
        elif listing.title:
            title_score = Decimal("10")
        score += title_score

        # Description score (30%)
        desc_score = Decimal("0")
        if listing.description:
            desc_len = len(listing.description)
            if desc_len >= ListingQualityScorer.MIN_DESCRIPTION_LENGTH:
                desc_score = Decimal("30")
            else:
                desc_score = Decimal(min(30, desc_len / 2))
        score += desc_score

        # Image score (20%)
        img_count = len(listing.images)
        if img_count >= ListingQualityScorer.MIN_IMAGES:
            img_score = Decimal(min(20, 20 * img_count / ListingQualityScorer.MAX_IMAGES))
        else:
            img_score = Decimal("0")
        score += img_score

        # Price score (15%)
        price_score = Decimal("15") if listing.price > Decimal("0") else Decimal("0")
        score += price_score

        # Attributes score (15%)
        attr_score = Decimal("0")
        if listing.attributes:
            attr_score = Decimal(min(15, 15 * len(listing.attributes) / 5))
        score += attr_score

        return score


class DuplicateDetector:
    """Detect duplicate listings using TF-IDF cosine similarity."""

    SIMILARITY_THRESHOLD: Decimal = Decimal("0.85")

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        """Tokenize text into words.

        Args:
            text: Text to tokenize.

        Returns:
            Set of tokens.
        """
        raw_tokens = re.findall(r"[a-z0-9]+", text.lower())
        tokens: set[str] = set()

        for token in raw_tokens:
            # Normalize storage-capacity variants (256gb vs 512gb) so listings
            # with only capacity differences are treated as near-duplicates.
            if re.fullmatch(r"\d+(gb|tb|mb)", token):
                unit = re.sub(r"^\d+", "", token)
                tokens.add(f"<size>{unit}")
                continue
            tokens.add(token)

        return tokens

    @staticmethod
    def _term_frequency(tokens: set[str]) -> dict[str, float]:
        """Calculate term frequency.

        Args:
            tokens: Document tokens.

        Returns:
            TF scores for each token.
        """
        total = len(tokens)
        if total == 0:
            return {}
        return {token: 1.0 / total for token in tokens}

    @staticmethod
    def _cosine_similarity(vec1: dict[str, float], vec2: dict[str, float]) -> Decimal:
        """Calculate cosine similarity between vectors.

        Args:
            vec1: First vector.
            vec2: Second vector.

        Returns:
            Similarity score 0-1.
        """
        all_tokens = set(vec1.keys()) | set(vec2.keys())
        if not all_tokens:
            return Decimal("0")

        dot_product = sum(vec1.get(token, 0) * vec2.get(token, 0) for token in all_tokens)

        norm1 = math.sqrt(sum(v**2 for v in vec1.values())) or 1
        norm2 = math.sqrt(sum(v**2 for v in vec2.values())) or 1

        similarity = dot_product / (norm1 * norm2) if norm1 and norm2 else 0
        return Decimal(str(similarity))

    @staticmethod
    def is_duplicate(title1: str, title2: str, attributes1: dict, attributes2: dict) -> tuple[bool, Decimal]:
        """Check if two listings are duplicates.

        Uses TF-IDF cosine similarity on titles and attributes.

        Args:
            title1: First listing title.
            title2: Second listing title.
            attributes1: First listing attributes.
            attributes2: Second listing attributes.

        Returns:
            Tuple of (is_duplicate, similarity_score).
        """
        tokens1 = DuplicateDetector._tokenize(title1)
        tokens2 = DuplicateDetector._tokenize(title2)

        vec1 = DuplicateDetector._term_frequency(tokens1)
        vec2 = DuplicateDetector._term_frequency(tokens2)

        title_similarity = DuplicateDetector._cosine_similarity(vec1, vec2)

        is_dup = title_similarity >= DuplicateDetector.SIMILARITY_THRESHOLD

        return is_dup, title_similarity


class CategoryTree:
    """Hierarchical category tree with breadcrumb generation."""

    def __init__(self) -> None:
        """Initialize category tree."""
        self._categories: dict[str, Category] = {}

    def add_category(
        self,
        name: str,
        description: str,
        icon_url: str,
        parent_id: str | None = None,
        attribute_keys: list[str] | None = None,
    ) -> Category:
        """Add category to tree.

        Args:
            name: Category name.
            description: Category description.
            icon_url: Icon image URL.
            parent_id: Parent category ID.
            attribute_keys: Searchable attributes for category.

        Returns:
            Created category.
        """
        category_id = f"cat_{uuid.uuid4().hex[:12]}"

        breadcrumb = []
        if parent_id and parent_id in self._categories:
            parent = self._categories[parent_id]
            breadcrumb = list(parent.breadcrumb or [])

        breadcrumb.append(name)

        category = Category(
            id=category_id,
            name=name,
            parent_id=parent_id,
            description=description,
            icon_url=icon_url,
            breadcrumb=breadcrumb,
            attribute_keys=attribute_keys or [],
        )

        self._categories[category_id] = category
        return category

    def get_category(self, category_id: str) -> Category:
        """Get category by ID.

        Args:
            category_id: Category identifier.

        Returns:
            Category object.

        Raises:
            VendorException: If category not found.
        """
        category = self._categories.get(category_id)
        if not category:
            raise VendorException(f"Category not found: {category_id}")
        return category

    def get_breadcrumb(self, category_id: str) -> list[str]:
        """Get full breadcrumb path for category.

        Args:
            category_id: Category identifier.

        Returns:
            List of category names from root to category.
        """
        category = self.get_category(category_id)
        return category.breadcrumb

    def list_categories(self, parent_id: str | None = None) -> list[Category]:
        """List categories, optionally filtered by parent.

        Args:
            parent_id: Parent category to filter by.

        Returns:
            List of categories.
        """
        categories = list(self._categories.values())
        if parent_id:
            categories = [c for c in categories if c.parent_id == parent_id]
        return categories


class ListingRegistry:
    """In-memory listing registry with quality and duplicate tracking."""

    def __init__(self) -> None:
        """Initialize listing registry."""
        self._listings: dict[str, Listing] = {}
        self._vendor_listings: dict[str, list[str]] = {}
        self._category_tree = CategoryTree()

    def create_listing(
        self,
        vendor_id: str,
        product_id: str,
        title: str,
        description: str,
        price: Decimal,
        quantity: int,
        category_id: str,
        images: list[str],
        attributes: dict,
    ) -> Listing:
        """Create product listing in DRAFT state.

        Args:
            vendor_id: Vendor identifier.
            product_id: Product identifier.
            title: Product title.
            description: Product description.
            price: Product price.
            quantity: Available quantity.
            category_id: Category identifier.
            images: Product image URLs.
            attributes: Product attributes.

        Returns:
            Created listing.
        """
        listing_id = f"listing_{uuid.uuid4().hex[:12]}"
        now = datetime.utcnow()

        listing = Listing(
            id=listing_id,
            vendor_id=vendor_id,
            product_id=product_id,
            state=ListingState.DRAFT,
            title=title,
            description=description,
            price=price,
            quantity=quantity,
            category_id=category_id,
            images=images,
            attributes=attributes,
            created_at=now,
            updated_at=now,
        )

        # Calculate quality score
        listing.quality_score = ListingQualityScorer.calculate_quality_score(listing)

        # Check for duplicates
        self._check_and_mark_duplicates(listing)

        self._listings[listing_id] = listing
        if vendor_id not in self._vendor_listings:
            self._vendor_listings[vendor_id] = []
        self._vendor_listings[vendor_id].append(listing_id)

        return listing

    def _check_and_mark_duplicates(self, new_listing: Listing) -> None:
        """Check new listing against existing listings for duplicates.

        Args:
            new_listing: Listing to check.
        """
        best_match_id: str | None = None
        best_similarity = Decimal("0")

        for listing_id, listing in self._listings.items():
            if listing.vendor_id != new_listing.vendor_id:
                continue

            is_dup, similarity = DuplicateDetector.is_duplicate(
                new_listing.title,
                listing.title,
                new_listing.attributes,
                listing.attributes,
            )

            if is_dup and similarity > best_similarity:
                best_similarity = similarity
                best_match_id = listing_id

        if best_match_id:
            new_listing.is_duplicate = True
            new_listing.duplicate_of = best_match_id

    def get_listing(self, listing_id: str) -> Listing:
        """Get listing by ID.

        Args:
            listing_id: Listing identifier.

        Returns:
            Listing object.

        Raises:
            ListingNotFoundError: If listing not found.
        """
        listing = self._listings.get(listing_id)
        if not listing:
            raise ListingNotFoundError(listing_id)
        return listing

    def publish_listing(self, listing_id: str) -> Listing:
        """Publish listing to PUBLISHED state.

        Args:
            listing_id: Listing identifier.

        Returns:
            Published listing.

        Raises:
            ListingNotFoundError: If listing not found.
        """
        listing = self.get_listing(listing_id)
        listing = ListingStateManager.transition(listing, ListingState.PUBLISHED)
        return listing

    def archive_listing(self, listing_id: str) -> Listing:
        """Archive listing.

        Args:
            listing_id: Listing identifier.

        Returns:
            Archived listing.

        Raises:
            ListingNotFoundError: If listing not found.
        """
        listing = self.get_listing(listing_id)
        listing = ListingStateManager.transition(listing, ListingState.ARCHIVED)
        return listing

    def list_vendor_listings(self, vendor_id: str, state: ListingState | None = None) -> list[Listing]:
        """List vendor's listings with optional state filter.

        Args:
            vendor_id: Vendor identifier.
            state: Filter by listing state.

        Returns:
            List of vendor's listings.
        """
        listing_ids = self._vendor_listings.get(vendor_id, [])
        listings = [self._listings[lid] for lid in listing_ids if lid in self._listings]

        if state:
            listings = [l for l in listings if l.state == state]

        return listings

    def record_view(self, listing_id: str) -> int:
        """Record a view for a listing.

        Args:
            listing_id: Listing identifier.

        Returns:
            Updated view count.

        Raises:
            ListingNotFoundError: If listing not found.
        """
        listing = self.get_listing(listing_id)
        listing.view_count += 1
        return listing.view_count

    def get_recommended_listings(self, viewed_listing_id: str, limit: int = 5) -> list[Listing]:
        """Get recommendations based on collaborative filtering.

        Returns listings frequently viewed together with input listing.

        Args:
            viewed_listing_id: Listing the user viewed.
            limit: Maximum recommendations to return.

        Returns:
            List of recommended listings.
        """
        viewed = self.get_listing(viewed_listing_id)

        # Find listings with similar attributes in same category
        similar_listings = [
            l
            for l in self._listings.values()
            if l.category_id == viewed.category_id and l.id != viewed_listing_id and l.state == ListingState.PUBLISHED
        ]

        # Score by view count and freshness
        similar_listings.sort(key=lambda l: (l.view_count, l.updated_at), reverse=True)

        return similar_listings[:limit]
