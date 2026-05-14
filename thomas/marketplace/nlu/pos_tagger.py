"""
Part-of-Speech (POS) tagging module using Hidden Markov Model.

Implements HMM-based POS tagging with Viterbi decoding, unknown word handling
using suffix-based rules, and beam search decoding with accuracy evaluation.
"""

import math
from collections import Counter, defaultdict

from thomas.marketplace.nlu._exceptions import ClassificationError
from thomas.marketplace.nlu._types import POSTag, Sentence, Token


class POSTagger:
    """
    Hidden Markov Model-based POS tagger using Viterbi algorithm.

    Learns emission and transition probabilities from tagged corpus and
    applies Viterbi decoding with sophisticated unknown word handling.
    """

    def __init__(self, beam_size: int = 5) -> None:
        """
        Initialize POS tagger.

        Args:
            beam_size: Beam size for beam search decoding
        """
        self.beam_size = beam_size
        self.emission_probs: dict[POSTag, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        self.transition_probs: dict[POSTag, dict[POSTag, float]] = defaultdict(lambda: defaultdict(float))
        self.tag_counts: dict[POSTag, int] = Counter()
        self.word_tag_counts: dict[str, dict[POSTag, int]] = defaultdict(lambda: defaultdict(int))
        self.tag_vocabulary: set[POSTag] = set()
        self.word_vocabulary: set[str] = set()
        self.is_trained = False

        # Unknown word handling rules
        self.suffix_rules = {
            "ly": POSTag.RB,
            "tion": POSTag.NN,
            "ing": POSTag.VBG,
            "ness": POSTag.NN,
            "ment": POSTag.NN,
            "able": POSTag.JJ,
            "ible": POSTag.JJ,
            "ful": POSTag.JJ,
            "less": POSTag.JJ,
            "ed": POSTag.VBD,
            "er": POSTag.NN,
            "est": POSTag.JJS,
            "ous": POSTag.JJ,
            "ive": POSTag.JJ,
        }

    def train(self, tagged_sentences: list[list[tuple[str, str]]]) -> None:
        """
        Train HMM tagger on tagged corpus.

        Args:
            tagged_sentences: List of sentences with (word, tag) tuples
        """
        # Count emissions and transitions
        prev_tag = None

        for sentence in tagged_sentences:
            for word, tag_str in sentence:
                try:
                    tag = POSTag(tag_str)
                except ValueError:
                    # Skip unknown tags
                    continue

                # Record word-tag counts
                word_lower = word.lower()
                self.word_tag_counts[word_lower][tag] += 1
                self.word_vocabulary.add(word_lower)

                # Record tag counts
                self.tag_counts[tag] += 1
                self.tag_vocabulary.add(tag)

                # Record transitions
                if prev_tag is not None:
                    self.transition_probs[prev_tag][tag] += 1

                prev_tag = tag

            prev_tag = None

        # Compute probabilities with Laplace smoothing
        self._compute_probabilities()
        self.is_trained = True

    def _compute_probabilities(self) -> None:
        """Compute emission and transition probabilities with smoothing."""
        # Emission probabilities
        sum(self.tag_counts.values())

        for word, tag_counts in self.word_tag_counts.items():
            for tag, count in tag_counts.items():
                # Add-1 smoothing
                self.emission_probs[tag][word] = (count + 1) / (self.tag_counts[tag] + len(self.word_vocabulary) + 1)

        # Transition probabilities
        for prev_tag in self.tag_vocabulary:
            total = sum(self.transition_probs[prev_tag].values())
            for tag in self.tag_vocabulary:
                count = self.transition_probs[prev_tag].get(tag, 0)
                # Add-1 smoothing
                self.transition_probs[prev_tag][tag] = (count + 1) / (total + len(self.tag_vocabulary) + 1)

    def tag(self, tokens: list[Token]) -> list[Token]:
        """
        Tag a list of tokens.

        Args:
            tokens: List of tokens to tag

        Returns:
            List of tokens with POS tags assigned
        """
        if not self.is_trained:
            raise ClassificationError("Tagger not trained. Call train() first.")

        if not tokens:
            return []

        # Use Viterbi decoding
        tags = self._viterbi(tokens)

        # Assign tags to tokens
        for token, tag in zip(tokens, tags):
            token.pos = tag

        return tokens

    def tag_sentence(self, sentence: Sentence) -> Sentence:
        """
        Tag all tokens in a sentence.

        Args:
            sentence: Sentence to tag

        Returns:
            Sentence with tagged tokens
        """
        self.tag(sentence.tokens)
        return sentence

    def _viterbi(self, tokens: list[Token]) -> list[POSTag]:
        """
        Viterbi algorithm for sequence tagging.

        Args:
            tokens: Tokens to tag

        Returns:
            List of most likely tags
        """
        n = len(tokens)
        words = [t.text.lower() for t in tokens]

        # Initialize DP tables
        viterbi_table: dict[int, dict[POSTag, float]] = defaultdict(lambda: defaultdict(float))
        backpointer: dict[int, dict[POSTag, POSTag]] = defaultdict(lambda: defaultdict(lambda: None))

        # Base case: first word
        for tag in self.tag_vocabulary:
            emission = self._get_emission_prob(tag, words[0])
            viterbi_table[0][tag] = math.log(emission)

        # Fill DP table
        for i in range(1, n):
            for tag in self.tag_vocabulary:
                emission = self._get_emission_prob(tag, words[i])

                best_prev_tag = None
                best_prob = float("-inf")

                for prev_tag in self.tag_vocabulary:
                    transition = self.transition_probs.get(prev_tag, {}).get(tag, 1e-10)
                    prob = viterbi_table[i - 1][prev_tag] + math.log(transition) + math.log(emission)

                    if prob > best_prob:
                        best_prob = prob
                        best_prev_tag = prev_tag

                viterbi_table[i][tag] = best_prob
                backpointer[i][tag] = best_prev_tag

        # Backtrack to find best path
        best_last_tag = max(viterbi_table[n - 1], key=viterbi_table[n - 1].get)
        path = [best_last_tag]

        for i in range(n - 1, 0, -1):
            best_last_tag = backpointer[i][best_last_tag]
            path.append(best_last_tag)

        return list(reversed(path))

    def _get_emission_prob(self, tag: POSTag, word: str) -> float:
        """
        Get emission probability for word-tag pair, handling unknown words.

        Args:
            tag: POS tag
            word: Word (lowercased)

        Returns:
            Emission probability
        """
        if word in self.word_vocabulary:
            return self.emission_probs[tag].get(word, 1e-10)

        # Unknown word handling with suffix rules
        for suffix, default_tag in self.suffix_rules.items():
            if word.endswith(suffix):
                if tag == default_tag:
                    return 0.1  # Higher probability for matching suffix rule
                else:
                    return 0.01  # Lower probability for non-matching

        # Default for completely unknown words
        if tag in {POSTag.NN, POSTag.NNS, POSTag.NNP, POSTag.NNPS}:
            return 0.05  # Nouns are common for unknowns
        return 1e-10

    def beam_search(self, tokens: list[Token], beam_size: int | None = None) -> list[POSTag]:
        """
        Beam search decoding for sequence tagging.

        Args:
            tokens: Tokens to tag
            beam_size: Beam size (uses default if None)

        Returns:
            List of tags
        """
        if beam_size is None:
            beam_size = self.beam_size

        n = len(tokens)
        words = [t.text.lower() for t in tokens]

        # Initialize beams: list of (prob, path)
        beams: list[list[tuple[float, list[POSTag]]]] = [[] for _ in range(n)]

        # First word
        for tag in self.tag_vocabulary:
            emission = self._get_emission_prob(tag, words[0])
            beams[0].append((math.log(emission), [tag]))

        beams[0].sort(key=lambda x: x[0], reverse=True)
        beams[0] = beams[0][:beam_size]

        # Fill beams
        for i in range(1, n):
            candidates = []

            for prev_prob, prev_path in beams[i - 1]:
                prev_tag = prev_path[-1]

                for tag in self.tag_vocabulary:
                    emission = self._get_emission_prob(tag, words[i])
                    transition = self.transition_probs.get(prev_tag, {}).get(tag, 1e-10)
                    prob = prev_prob + math.log(transition) + math.log(emission)
                    path = prev_path + [tag]
                    candidates.append((prob, path))

            candidates.sort(key=lambda x: x[0], reverse=True)
            beams[i] = candidates[:beam_size]

        # Return best path
        best_prob, best_path = beams[n - 1][0]
        return best_path

    def evaluate(self, test_sentences: list[list[tuple[str, str]]]) -> dict[str, float]:
        """
        Evaluate tagger on test data.

        Args:
            test_sentences: List of tagged sentences

        Returns:
            Dictionary with accuracy metrics
        """
        total = 0
        correct = 0
        correct_by_tag: dict[str, int] = defaultdict(int)
        total_by_tag: dict[str, int] = defaultdict(int)

        for sentence in test_sentences:
            words = [w for w, _ in sentence]
            gold_tags = [POSTag(t) for _, t in sentence]

            # Tag
            tokens = [Token(text=w, span=None) for w in words]  # type: ignore
            predicted_tags = self._viterbi(tokens)

            # Compare
            for gold, pred in zip(gold_tags, predicted_tags):
                total += 1
                if gold == pred:
                    correct += 1
                    correct_by_tag[gold.value] += 1

                total_by_tag[gold.value] += 1

        # Calculate metrics
        accuracy = correct / total if total > 0 else 0.0
        per_tag_accuracy = {}

        for tag in total_by_tag:
            per_tag_accuracy[tag] = correct_by_tag[tag] / total_by_tag[tag] if total_by_tag[tag] > 0 else 0.0

        return {"overall_accuracy": accuracy, "per_tag_accuracy": per_tag_accuracy, "correct": correct, "total": total}
