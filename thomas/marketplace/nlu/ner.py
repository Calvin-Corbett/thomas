"""
Named Entity Recognition (NER) module.

Implements BIO tagging-based NER with feature extraction, gazetteer matching,
regex-based extraction for common entities, entity linking, and nested entity handling.
"""

import re
from re import Pattern

from thomas.marketplace.nlu._types import Entity, NERTag, Sentence, Span, Token


class GazetteerMatcher:
    """
    Matches entities against preloaded gazetteer lists.

    Stores and efficiently matches named entities against comprehensive
    lists of names, locations, and organizations.
    """

    def __init__(self) -> None:
        """Initialize gazetteer matcher."""
        self.names: set[str] = set()
        self.locations: set[str] = set()
        self.organizations: set[str] = set()
        self.loaded = False

    def load_default_gazetteers(self) -> None:
        """Load default gazetteers."""
        # Common first/last names
        self.names.update(
            {
                "john",
                "mary",
                "david",
                "jane",
                "robert",
                "sarah",
                "michael",
                "emma",
                "smith",
                "johnson",
                "williams",
                "brown",
                "jones",
                "garcia",
                "miller",
                "davis",
                "rodriguez",
                "martinez",
                "hernandez",
                "lopez",
                "james",
                "george",
                "thomas",
                "charles",
                "alice",
                "bob",
                "charlie",
            }
        )

        # Common locations
        self.locations.update(
            {
                "new york",
                "london",
                "paris",
                "tokyo",
                "beijing",
                "shanghai",
                "moscow",
                "mumbai",
                "delhi",
                "bangkok",
                "dubai",
                "singapore",
                "usa",
                "uk",
                "france",
                "germany",
                "spain",
                "italy",
                "canada",
                "australia",
                "japan",
                "china",
                "india",
                "brazil",
                "mexico",
                "new york city",
                "los angeles",
                "chicago",
                "houston",
                "phoenix",
                "california",
                "texas",
                "florida",
                "washington",
                "manhattan",
                "brooklyn",
                "queens",
                "bronx",
                "staten island",
            }
        )

        # Common organizations
        self.organizations.update(
            {
                "apple",
                "google",
                "microsoft",
                "amazon",
                "facebook",
                "netflix",
                "tesla",
                "ibm",
                "intel",
                "oracle",
                "adobe",
                "salesforce",
                "twitter",
                "linkedin",
                "snapchat",
                "uber",
                "lyft",
                "airbnb",
                "wall street journal",
                "bbc",
                "cnn",
                "nyt",
                "washington post",
                "new york times",
                "the new york times",
                "united nations",
                "world health organization",
                "nato",
                "eu",
                "oecd",
            }
        )

        self.loaded = True

    def match(self, text: str, text_lower: str) -> tuple[NERTag, str] | None:
        """
        Match text against gazetteers.

        Args:
            text: Original text
            text_lower: Lowercased text

        Returns:
            (tag, canonical_form) if match found, None otherwise
        """
        if text_lower in self.names:
            return (NERTag.B_PER, text)
        elif text_lower in self.locations:
            return (NERTag.B_LOC, text)
        elif text_lower in self.organizations:
            return (NERTag.B_ORG, text)

        return None


class NERTagger:
    """
    Feature-based Named Entity Recognition using sequence labeling.

    Uses BIO tagging scheme with feature extraction including word shape,
    capitalization, prefix/suffix, and context window features.
    """

    def __init__(self) -> None:
        """Initialize NER tagger."""
        self.gazetteer = GazetteerMatcher()
        self.gazetteer.load_default_gazetteers()

        # Regex patterns for specific entity types
        self.patterns = self._compile_patterns()

        # Feature weights (would be learned in real system)
        self.model_weights: dict[str, float] = {}

    def _compile_patterns(self) -> dict[str, Pattern[str]]:
        """Compile regex patterns for entity extraction."""
        return {
            "date": re.compile(
                r"\b(\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2}|"
                r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2},? \d{4}|"
                r"(?:January|February|March|April|May|June|July|August|September|October|November|December) \d{1,2},? \d{4})\b",
                re.IGNORECASE,
            ),
            "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
            "phone": re.compile(r"\b(?:\+?1[-.\s]?)?\(?[2-9]\d{2}\)?[-.\s]?[2-9]\d{2}[-.\s]?\d{4}\b"),
            "url": re.compile(r"\b(?:https?://|www\.)[^\s]+\b", re.IGNORECASE),
            "money": re.compile(r"\$?\s*\d+(?:,\d{3})*(?:\.\d{2})?(?:\s*(?:USD|EUR|GBP|JPY))?(?![\d%])", re.IGNORECASE),
            "percent": re.compile(r"\d+(?:\.\d+)?%"),
        }

    def tag(self, sentence: Sentence) -> list[Entity]:
        """
        Recognize entities in a sentence.

        Args:
            sentence: Sentence to process

        Returns:
            List of entities found
        """
        entities = []

        # Apply regex patterns
        for ent_type, pattern in self.patterns.items():
            tag = self._entity_type_to_tag(ent_type)
            for match in pattern.finditer(sentence.text):
                span = Span(match.start(), match.end())
                entity_text = sentence.text[match.start() : match.end()]
                entities.append(
                    Entity(text=entity_text, span=span, label=tag, confidence=0.95, canonical_form=entity_text)
                )

        # Apply gazetteer matching with feature-based confidence
        for token in sentence.tokens:
            if token.pos and token.pos.value.startswith("N"):  # Noun
                text_lower = token.text.lower()
                match = self.gazetteer.match(token.text, text_lower)

                if match:
                    tag, canonical = match
                    confidence = self._compute_confidence(token)
                    entities.append(
                        Entity(
                            text=token.text, span=token.span, label=tag, confidence=confidence, canonical_form=canonical
                        )
                    )

        # Apply BIO sequence tagging for contextual entities
        bio_entities = self._bio_tag(sentence)
        entities.extend(bio_entities)

        # Remove duplicates and handle nesting
        entities = self._deduplicate_entities(entities)

        return entities

    def _bio_tag(self, sentence: Sentence) -> list[Entity]:
        """
        Apply BIO sequence tagging based on features.

        Args:
            sentence: Sentence to tag

        Returns:
            List of entities found
        """
        if not sentence.tokens:
            return []

        entities = []
        current_entity = None
        current_entity_tokens = []
        current_tag = None

        for i, token in enumerate(sentence.tokens):
            features = self._extract_features(token, i, sentence)
            predicted_tag = self._predict_tag(features)

            if predicted_tag == NERTag.O:
                # No entity
                if current_entity is not None:
                    # End current entity
                    start_span = current_entity_tokens[0].span
                    end_span = current_entity_tokens[-1].span
                    entity_text = sentence.text[start_span.start : end_span.end]

                    entities.append(
                        Entity(
                            text=entity_text,
                            span=Span(start_span.start, end_span.end),
                            label=current_tag,
                            confidence=0.85,
                        )
                    )
                    current_entity = None
                    current_entity_tokens = []
                    current_tag = None
            else:
                # Entity tag
                if predicted_tag.value.startswith("B-"):
                    # Begin new entity
                    if current_entity is not None:
                        start_span = current_entity_tokens[0].span
                        end_span = current_entity_tokens[-1].span
                        entity_text = sentence.text[start_span.start : end_span.end]

                        entities.append(
                            Entity(
                                text=entity_text,
                                span=Span(start_span.start, end_span.end),
                                label=current_tag,
                                confidence=0.85,
                            )
                        )

                    current_entity = token
                    current_entity_tokens = [token]
                    current_tag = predicted_tag

                elif predicted_tag.value.startswith("I-") and current_entity is not None:
                    # Continue entity
                    if current_tag and current_tag.value.split("-")[1] == predicted_tag.value.split("-")[1]:
                        current_entity_tokens.append(token)

        # Handle last entity
        if current_entity is not None:
            start_span = current_entity_tokens[0].span
            end_span = current_entity_tokens[-1].span
            entity_text = sentence.text[start_span.start : end_span.end]

            entities.append(
                Entity(text=entity_text, span=Span(start_span.start, end_span.end), label=current_tag, confidence=0.85)
            )

        return entities

    def _extract_features(self, token: Token, idx: int, sentence: Sentence) -> dict[str, float]:
        """
        Extract features for a token.

        Args:
            token: Token to extract features for
            idx: Index of token in sentence
            sentence: Sentence context

        Returns:
            Feature dictionary
        """
        features: dict[str, float] = {}

        # Word shape features
        features["is_capitalized"] = float(token.text[0].isupper())
        features["is_all_caps"] = float(token.text.isupper())
        features["is_all_lower"] = float(token.text.islower())
        features["is_numeric"] = float(token.text.isdigit())
        features["contains_digit"] = float(any(c.isdigit() for c in token.text))
        features["contains_hyphen"] = float("-" in token.text)

        # Prefix/suffix features
        for size in [2, 3]:
            if len(token.text) >= size:
                features[f"prefix{size}"] = hash(token.text[:size]) % 100
                features[f"suffix{size}"] = hash(token.text[-size:]) % 100

        # POS features
        if token.pos:
            features["pos_is_noun"] = float(token.pos.value.startswith("N"))
            features["pos_is_verb"] = float(token.pos.value.startswith("V"))
            features["pos_is_adj"] = float(token.pos.value.startswith("J"))
            features["pos_is_prop"] = float(token.pos in (POSTag.NNP, POSTag.NNPS))

        # Context features
        if idx > 0:
            prev_token = sentence.tokens[idx - 1]
            features["prev_is_capitalized"] = float(prev_token.text[0].isupper())

        if idx < len(sentence.tokens) - 1:
            next_token = sentence.tokens[idx + 1]
            features["next_is_capitalized"] = float(next_token.text[0].isupper())

        return features

    def _predict_tag(self, features: dict[str, float]) -> NERTag:
        """
        Predict NER tag based on features.

        Args:
            features: Feature dictionary

        Returns:
            Predicted NER tag
        """
        # Simple heuristic-based prediction
        if features.get("is_numeric", 0) > 0.5:
            return NERTag.B_DATE
        if features.get("contains_digit", 0) > 0.5 and features.get("is_numeric", 0) < 0.5:
            return NERTag.B_MONEY
        if features.get("pos_is_prop", 0) > 0.5 and features.get("is_capitalized", 0) > 0.5:
            return NERTag.B_PER
        if features.get("is_capitalized", 0) > 0.5:
            return NERTag.B_LOC

        return NERTag.O

    def _compute_confidence(self, token: Token) -> float:
        """
        Compute confidence score for entity match.

        Args:
            token: Token being matched

        Returns:
            Confidence score [0, 1]
        """
        confidence = 0.5

        # Increase confidence for proper nouns
        if token.pos in (POSTag.NNP, POSTag.NNPS):
            confidence += 0.3

        # Increase confidence for capitalized words
        if token.text[0].isupper():
            confidence += 0.1

        return min(confidence, 1.0)

    def _deduplicate_entities(self, entities: list[Entity]) -> list[Entity]:
        """
        Remove duplicate/overlapping entities, keeping highest confidence.

        Args:
            entities: List of entities

        Returns:
            Deduplicated entity list
        """
        if not entities:
            return []

        # Sort by confidence descending
        entities.sort(key=lambda e: e.confidence, reverse=True)

        # Remove overlapping
        result = []
        for entity in entities:
            overlaps = any(entity.span.overlaps(existing.span) for existing in result)
            if not overlaps:
                result.append(entity)

        return result

    def _entity_type_to_tag(self, entity_type: str) -> NERTag:
        """Convert entity type to NER tag."""
        mapping = {
            "date": NERTag.B_DATE,
            "email": NERTag.B_EMAIL,
            "phone": NERTag.B_MISC,
            "url": NERTag.B_URL,
            "money": NERTag.B_MONEY,
            "percent": NERTag.B_PERCENT,
        }
        return mapping.get(entity_type, NERTag.B_MISC)


# Import needed for type hints
from thomas.marketplace.nlu._types import POSTag
