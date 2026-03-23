"""
Coreference resolution module.

Implements mention detection, mention-pair model with features, clustering,
pronoun resolution using Hobbs' algorithm, and sieve-based approach.
"""

from thomas.marketplace.nlu._types import Document, POSTag, Sentence, Span, Token


class CoreferenceResolver:
    """
    Coreference resolution using multiple approaches.

    Detects mentions, links pronouns and named entities using mention-pair models,
    clustering, and sieve-based heuristics.
    """

    def __init__(self, use_hobbs: bool = True) -> None:
        """
        Initialize coreference resolver.

        Args:
            use_hobbs: Whether to use Hobbs' algorithm for pronoun resolution
        """
        self.use_hobbs = use_hobbs
        self.pronouns = {
            "he",
            "she",
            "it",
            "they",
            "them",
            "their",
            "his",
            "her",
            "its",
            "we",
            "us",
            "our",
            "you",
            "your",
            "i",
            "me",
            "my",
        }
        self.plural_pronouns = {"they", "them", "their", "we", "us", "our", "you", "your"}
        self.singular_pronouns = {"he", "she", "it", "i", "me", "my", "his", "her", "its"}
        self.male_pronouns = {"he", "him", "his"}
        self.female_pronouns = {"she", "her", "hers"}

    def resolve(self, document: Document) -> list[list[Span]]:
        """
        Resolve coreferences in a document.

        Args:
            document: Document to process

        Returns:
            List of coreference clusters (each cluster is list of spans)
        """
        # Extract mentions
        mentions = self._extract_mentions(document)

        # Link mentions using sieve approach
        clusters = self._sieve_resolution(mentions, document)

        return clusters

    def resolve_pronouns(self, sentence: Sentence) -> list[tuple[int, int]]:
        """
        Resolve pronouns to antecedents within a sentence.

        Args:
            sentence: Sentence to process

        Returns:
            List of (pronoun_idx, antecedent_idx) pairs
        """
        if not sentence.tokens or not sentence.parse_tree:
            return []

        links = []

        for i, token in enumerate(sentence.tokens):
            if token.text.lower() in self.pronouns:
                # Find antecedent
                antecedent_idx = self._find_antecedent(i, sentence)

                if antecedent_idx is not None and antecedent_idx != i:
                    links.append((i, antecedent_idx))

        return links

    def _extract_mentions(self, document: Document) -> list[tuple[Span, str, int]]:
        """
        Extract mentions from document.

        Returns list of (span, mention_text, sentence_idx) tuples.

        Args:
            document: Document to process

        Returns:
            List of mentions
        """
        mentions = []

        for sent_idx, sentence in enumerate(document.sentences):
            if not sentence.tokens:
                continue

            # Extract named entities as mentions
            for entity in sentence.entities:
                mentions.append((entity.span, entity.text, sent_idx))

            # Extract noun phrases as mentions
            nps = self._extract_noun_phrases(sentence)
            for np_span, np_text in nps:
                # Avoid duplicates with entities
                overlaps_entity = any(np_span.overlaps(entity.span) for entity in sentence.entities)
                if not overlaps_entity:
                    mentions.append((np_span, np_text, sent_idx))

            # Extract pronouns as mentions
            for i, token in enumerate(sentence.tokens):
                if token.text.lower() in self.pronouns:
                    mentions.append((token.span, token.text, sent_idx))

        return mentions

    def _extract_noun_phrases(self, sentence: Sentence) -> list[tuple[Span, str]]:
        """
        Extract noun phrases from sentence using parse tree.

        Args:
            sentence: Sentence to process

        Returns:
            List of (span, text) tuples
        """
        nps = []

        if not sentence.tokens:
            return nps

        # Simple heuristic: DT* NN+ (determiner(s) + nouns)
        i = 0
        while i < len(sentence.tokens):
            token = sentence.tokens[i]

            # Look for starting noun or determiner
            if token.pos and (token.pos.value.startswith("N") or token.pos == POSTag.DT):
                start = i

                # Skip determiners
                if token.pos == POSTag.DT:
                    i += 1
                    if i >= len(sentence.tokens):
                        break
                    token = sentence.tokens[i]

                # Collect nouns and adjectives
                while i < len(sentence.tokens):
                    t = sentence.tokens[i]
                    if t.pos and (t.pos.value.startswith("N") or t.pos.value.startswith("JJ")):
                        i += 1
                    else:
                        break

                # Create noun phrase
                end = i
                if end > start:
                    span = Span(sentence.tokens[start].span.start, sentence.tokens[end - 1].span.end)
                    text = sentence.text[span.start : span.end]
                    nps.append((span, text))
            else:
                i += 1

        return nps

    def _sieve_resolution(self, mentions: list[tuple[Span, str, int]], document: Document) -> list[list[Span]]:
        """
        Apply sieve-based coreference resolution.

        Uses cascade of sieves from most to least precise.

        Args:
            mentions: Extracted mentions
            document: Document context

        Returns:
            Coreference clusters
        """
        # Initialize: each mention is its own cluster
        clusters: dict[int, list[int]] = {i: [i] for i in range(len(mentions))}
        active_clusters: dict[int, int] = {i: i for i in range(len(mentions))}

        # Apply sieves in order
        # Sieve 1: Exact string match
        clusters, active_clusters = self._sieve_exact_match(mentions, clusters, active_clusters)

        # Sieve 2: Head match
        clusters, active_clusters = self._sieve_head_match(mentions, clusters, active_clusters)

        # Sieve 3: Compatible modifiers
        clusters, active_clusters = self._sieve_compatible_modifiers(mentions, clusters, active_clusters)

        # Sieve 4: Pronouns
        clusters, active_clusters = self._sieve_pronouns(mentions, clusters, active_clusters, document)

        # Convert to output format
        result_clusters = []
        seen_clusters = set()

        for cluster_id, mention_indices in clusters.items():
            if cluster_id not in seen_clusters:
                cluster_spans = [mentions[idx][0] for idx in mention_indices]
                result_clusters.append(cluster_spans)
                seen_clusters.add(cluster_id)

        return result_clusters

    def _sieve_exact_match(
        self, mentions: list[tuple[Span, str, int]], clusters: dict[int, list[int]], active_clusters: dict[int, int]
    ) -> tuple[dict[int, list[int]], dict[int, int]]:
        """Sieve 1: Exact string match."""
        text_to_cluster: dict[str, int] = {}

        for i, (span, text, sent_idx) in enumerate(mentions):
            text_lower = text.lower()

            if text_lower in text_to_cluster:
                # Merge clusters
                old_cluster = text_to_cluster[text_lower]
                new_cluster = active_clusters[i]

                if old_cluster != new_cluster:
                    # Merge
                    clusters[old_cluster].extend(clusters[new_cluster])
                    del clusters[new_cluster]

                    # Update mapping
                    for idx in clusters[old_cluster]:
                        active_clusters[idx] = old_cluster

                    active_clusters[i] = old_cluster
            else:
                text_to_cluster[text_lower] = active_clusters[i]

        return clusters, active_clusters

    def _sieve_head_match(
        self, mentions: list[tuple[Span, str, int]], clusters: dict[int, list[int]], active_clusters: dict[int, int]
    ) -> tuple[dict[int, list[int]], dict[int, int]]:
        """Sieve 2: Head noun match."""
        for i, (span_i, text_i, sent_i) in enumerate(mentions):
            head_i = self._get_head_noun(text_i)

            for j, (span_j, text_j, sent_j) in enumerate(mentions):
                if i >= j or sent_i > sent_j:
                    continue

                head_j = self._get_head_noun(text_j)

                if head_i and head_j and head_i.lower() == head_j.lower():
                    # Merge clusters
                    cluster_i = active_clusters[i]
                    cluster_j = active_clusters[j]

                    if cluster_i != cluster_j:
                        clusters[cluster_i].extend(clusters[cluster_j])
                        del clusters[cluster_j]

                        for idx in clusters[cluster_i]:
                            active_clusters[idx] = cluster_i

        return clusters, active_clusters

    def _sieve_compatible_modifiers(
        self, mentions: list[tuple[Span, str, int]], clusters: dict[int, list[int]], active_clusters: dict[int, int]
    ) -> tuple[dict[int, list[int]], dict[int, int]]:
        """Sieve 3: Compatible modifiers."""
        # Check if mentions have compatible modifiers/attributes
        for i in range(len(mentions)):
            for j in range(i + 1, len(mentions)):
                if self._compatible_attributes(mentions[i][1], mentions[j][1]):
                    cluster_i = active_clusters[i]
                    cluster_j = active_clusters[j]

                    if cluster_i != cluster_j:
                        clusters[cluster_i].extend(clusters[cluster_j])
                        del clusters[cluster_j]

                        for idx in clusters[cluster_i]:
                            active_clusters[idx] = cluster_i

        return clusters, active_clusters

    def _sieve_pronouns(
        self,
        mentions: list[tuple[Span, str, int]],
        clusters: dict[int, list[int]],
        active_clusters: dict[int, int],
        document: Document,
    ) -> tuple[dict[int, list[int]], dict[int, int]]:
        """Sieve 4: Pronoun resolution."""
        for i, (span, text, sent_idx) in enumerate(mentions):
            if text.lower() not in self.pronouns:
                continue

            # Find antecedent
            best_antecedent = None
            best_score = -float("inf")

            for j, (span_j, text_j, sent_j) in enumerate(mentions):
                if i == j or sent_j > sent_idx:
                    continue

                # Score antecedent
                score = self._score_antecedent(text, text_j, sent_idx, sent_j)

                if score > best_score:
                    best_score = score
                    best_antecedent = j

            if best_antecedent is not None and best_score > 0:
                cluster_i = active_clusters[i]
                cluster_j = active_clusters[best_antecedent]

                if cluster_i != cluster_j:
                    clusters[cluster_i].extend(clusters[cluster_j])
                    del clusters[cluster_j]

                    for idx in clusters[cluster_i]:
                        active_clusters[idx] = cluster_i

        return clusters, active_clusters

    def _find_antecedent(self, pronoun_idx: int, sentence: Sentence) -> int | None:
        """
        Find antecedent for a pronoun using Hobbs' algorithm.

        Args:
            pronoun_idx: Index of pronoun in sentence
            sentence: Sentence context

        Returns:
            Index of antecedent or None
        """
        if not self.use_hobbs or not sentence.parse_tree:
            return self._simple_antecedent_search(pronoun_idx, sentence)

        pronoun = sentence.tokens[pronoun_idx].text.lower()

        # Search in reverse order (closest first)
        for i in range(pronoun_idx - 1, -1, -1):
            token = sentence.tokens[i]

            if token.text.lower() in self.pronouns:
                continue

            # Check gender/number agreement
            if self._compatible_pronoun_antecedent(pronoun, token):
                return i

        return None

    def _simple_antecedent_search(self, pronoun_idx: int, sentence: Sentence) -> int | None:
        """Simple antecedent search: closest matching noun."""
        pronoun = sentence.tokens[pronoun_idx].text.lower()

        for i in range(pronoun_idx - 1, -1, -1):
            token = sentence.tokens[i]

            if token.pos and token.pos.value.startswith("N"):
                if self._compatible_pronoun_antecedent(pronoun, token):
                    return i

        return None

    def _compatible_pronoun_antecedent(self, pronoun: str, token: Token) -> bool:
        """Check gender/number compatibility."""
        if pronoun in {"he", "him", "his"} or pronoun in {"she", "her", "hers"} or pronoun in {"it", "its"}:
            return token.pos in {POSTag.NN, POSTag.NNP}

        elif pronoun in {"they", "them", "their"}:
            return token.pos in {POSTag.NNS, POSTag.NNPS}

        return True

    def _get_head_noun(self, text: str) -> str | None:
        """Extract head noun from text."""
        words = text.split()
        if words:
            return words[-1]  # Last word is typically head
        return None

    def _compatible_attributes(self, text1: str, text2: str) -> bool:
        """Check if two mentions have compatible attributes."""
        # Very simplified: check if one is substring of other
        return text1 in text2 or text2 in text1

    def _score_antecedent(self, pronoun: str, candidate: str, sent_i: int, sent_j: int) -> float:
        """Score how likely candidate is antecedent of pronoun."""
        score = 0.0

        # Recency (closer in distance = higher score)
        distance = sent_i - sent_j
        score += 1.0 / (1 + distance)

        # Prefer non-pronouns as antecedents
        if candidate.lower() not in self.pronouns:
            score += 1.0

        return score
