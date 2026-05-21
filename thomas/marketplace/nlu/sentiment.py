"""
Sentiment analysis module with multiple approaches.

Implements lexicon-based sentiment analysis with valence shifting, negation handling,
degree modifiers, contrastive conjunctions, aspect-based sentiment, emotion detection,
and subjectivity classification.
"""

from collections import defaultdict

from thomas.marketplace.nlu._types import NERTag, Sentence, SentimentResult, Token


class SentimentAnalyzer:
    """
    Lexicon-based sentiment analysis with advanced linguistic features.

    Analyzes sentiment using sentiment lexicons with support for negation,
    intensifiers, degree modifiers, and aspect-based analysis.
    """

    def __init__(self) -> None:
        """Initialize sentiment analyzer."""
        self.positive_words = self._load_positive_lexicon()
        self.negative_words = self._load_negative_lexicon()
        self.intensifiers = {"very", "extremely", "incredibly", "absolutely", "definitely", "really", "so"}
        self.diminishers = {"somewhat", "quite", "rather", "fairly", "kind of", "sort of", "a bit"}
        self.negations = {"no", "not", "never", "neither", "nobody", "nothing", "n't"}
        self.contrast_conj = {"but", "however", "yet", "although", "though", "while"}
        self.emotions = self._load_emotion_lexicon()

    def _load_positive_lexicon(self) -> dict[str, float]:
        """Load positive words with valence scores."""
        return {
            "good": 0.7,
            "great": 0.8,
            "excellent": 0.9,
            "amazing": 0.9,
            "wonderful": 0.9,
            "awesome": 0.85,
            "fantastic": 0.85,
            "love": 0.9,
            "beautiful": 0.85,
            "perfect": 0.9,
            "happy": 0.8,
            "joy": 0.8,
            "glad": 0.75,
            "brilliant": 0.9,
            "best": 0.95,
            "better": 0.7,
            "nice": 0.65,
            "fine": 0.6,
            "lovely": 0.8,
            "superb": 0.9,
            "outstanding": 0.9,
            "exceptional": 0.85,
            "impressive": 0.8,
            "splendid": 0.85,
            "marvellous": 0.85,
            "perfect": 0.95,
            "positive": 0.7,
            "win": 0.75,
            "success": 0.8,
            "hope": 0.65,
            "proud": 0.8,
            "thank": 0.7,
            "thanks": 0.7,
            "delighted": 0.9,
            "charming": 0.8,
            "delightful": 0.85,
            "enjoyable": 0.8,
            "favorable": 0.7,
            "fortunate": 0.75,
            "handsome": 0.75,
            "helpful": 0.7,
            "honest": 0.65,
        }

    def _load_negative_lexicon(self) -> dict[str, float]:
        """Load negative words with valence scores."""
        return {
            "bad": -0.7,
            "terrible": -0.9,
            "awful": -0.9,
            "horrible": -0.9,
            "ugly": -0.8,
            "hate": -0.9,
            "angry": -0.8,
            "sad": -0.8,
            "poor": -0.7,
            "worst": -0.95,
            "worse": -0.7,
            "disgusting": -0.9,
            "offensive": -0.8,
            "stupid": -0.8,
            "dumb": -0.8,
            "crazy": -0.6,
            "fail": -0.8,
            "failure": -0.8,
            "disaster": -0.9,
            "broken": -0.7,
            "mess": -0.7,
            "problem": -0.6,
            "issue": -0.5,
            "worry": -0.6,
            "concerned": -0.5,
            "disappointed": -0.8,
            "disappointing": -0.8,
            "frustrating": -0.8,
            "frustration": -0.8,
            "annoying": -0.7,
            "annoyed": -0.7,
            "upset": -0.7,
            "weak": -0.6,
            "useless": -0.8,
            "worthless": -0.9,
            "shameful": -0.8,
            "ashamed": -0.75,
            "toxic": -0.85,
            "harm": -0.75,
            "harmful": -0.75,
            "danger": -0.8,
            "dangerous": -0.8,
            "fear": -0.75,
        }

    def _load_emotion_lexicon(self) -> dict[str, str]:
        """Load emotion words and their emotions (Plutchik's 8 emotions)."""
        return {
            # Joy
            "happy": "joy",
            "joy": "joy",
            "glad": "joy",
            "delighted": "joy",
            "cheerful": "joy",
            "content": "joy",
            "pleased": "joy",
            # Trust
            "trust": "trust",
            "confident": "trust",
            "secure": "trust",
            "faith": "trust",
            # Fear
            "afraid": "fear",
            "scared": "fear",
            "terrified": "fear",
            "anxious": "fear",
            "worry": "fear",
            "concerned": "fear",
            "nervous": "fear",
            # Surprise
            "surprised": "surprise",
            "shocked": "surprise",
            "amazed": "surprise",
            # Sadness
            "sad": "sadness",
            "unhappy": "sadness",
            "depressed": "sadness",
            "gloomy": "sadness",
            "miserable": "sadness",
            "melancholy": "sadness",
            # Disgust
            "disgusted": "disgust",
            "disgusting": "disgust",
            "repulsive": "disgust",
            # Anger
            "angry": "anger",
            "furious": "anger",
            "enraged": "anger",
            "mad": "anger",
            "annoyed": "anger",
            "irritated": "anger",
            "cross": "anger",
            # Anticipation
            "excited": "anticipation",
            "hopeful": "anticipation",
            "eager": "anticipation",
        }

    def analyze(self, sentence: Sentence) -> SentimentResult:
        """
        Analyze sentiment of a sentence.

        Args:
            sentence: Sentence to analyze

        Returns:
            Sentiment analysis result
        """
        tokens = sentence.tokens
        text = sentence.text.lower()

        if not tokens:
            return SentimentResult(polarity=0.0, confidence=0.0, subjectivity=0.0)

        # Analyze at different levels
        sentence_polarity = self._compute_sentence_polarity(tokens, text)
        aspect_sentiments = self._extract_aspect_sentiments(tokens, sentence)
        emotions = self._detect_emotions(tokens, text)
        subjectivity = self._compute_subjectivity(tokens, text)

        # Extract phrases
        positive_phrases = self._extract_sentiment_phrases(tokens, text, "positive")
        negative_phrases = self._extract_sentiment_phrases(tokens, text, "negative")

        # Compute confidence
        confidence = min(1.0, abs(sentence_polarity) + 0.3) if sentence_polarity != 0.0 else 0.5

        return SentimentResult(
            polarity=sentence_polarity,
            confidence=confidence,
            subjectivity=subjectivity,
            emotions=emotions,
            aspect_sentiments=aspect_sentiments,
            positive_phrases=positive_phrases,
            negative_phrases=negative_phrases,
        )

    def _compute_sentence_polarity(self, tokens: list[Token], text: str) -> float:
        """
        Compute overall sentence polarity.

        Args:
            tokens: Sentence tokens
            text: Sentence text

        Returns:
            Polarity score [-1, 1]
        """
        if not tokens:
            return 0.0

        polarity_scores = []

        for i, token in enumerate(tokens):
            word = token.text.lower()

            if word in self.positive_words:
                score = self.positive_words[word]
            elif word in self.negative_words:
                score = self.negative_words[word]
            else:
                continue

            # Apply negation
            if i > 0 and tokens[i - 1].text.lower() in self.negations:
                score = -score

            # Apply intensifiers/diminishers
            if i > 0:
                prev_word = tokens[i - 1].text.lower()
                if prev_word in self.intensifiers:
                    score = score * 1.5
                elif prev_word in self.diminishers:
                    score = score * 0.5

            polarity_scores.append(score)

        # Handle contrast conjunctions
        contrast_positions = [i for i, t in enumerate(tokens) if t.text.lower() in self.contrast_conj]

        if contrast_positions:
            # After contrast, sentiment is usually flipped/emphasized
            pos = contrast_positions[-1]
            before_contrast = polarity_scores[:pos]
            after_contrast = polarity_scores[pos + 1 :]

            before_polarity = sum(before_contrast) / len(before_contrast) if before_contrast else 0
            after_polarity = sum(after_contrast) / len(after_contrast) if after_contrast else 0

            # After contrast is more important
            final_polarity = 0.3 * before_polarity + 0.7 * after_polarity
        else:
            final_polarity = sum(polarity_scores) / len(polarity_scores) if polarity_scores else 0

        return max(-1.0, min(1.0, final_polarity))

    def _extract_aspect_sentiments(self, tokens: list[Token], sentence: Sentence) -> dict[str, float]:
        """
        Extract aspect-based sentiments.

        Args:
            tokens: Sentence tokens
            sentence: Sentence with entities

        Returns:
            Dictionary of aspect -> polarity
        """
        aspect_sentiments: dict[str, float] = {}

        for entity in sentence.entities:
            if entity.label in (NERTag.B_LOC, NERTag.B_ORG, NERTag.B_MISC):
                # Find sentiment words near entity
                entity_sentiment = 0.0
                count = 0

                for i, token in enumerate(tokens):
                    if token.span.overlaps(entity.span):
                        # Check nearby tokens for sentiment
                        window = 3
                        for j in range(max(0, i - window), min(len(tokens), i + window + 1)):
                            word = tokens[j].text.lower()
                            if word in self.positive_words:
                                entity_sentiment += self.positive_words[word]
                                count += 1
                            elif word in self.negative_words:
                                entity_sentiment += self.negative_words[word]
                                count += 1

                if count > 0:
                    aspect_sentiments[entity.canonical_form or entity.text] = entity_sentiment / count

        return aspect_sentiments

    def _detect_emotions(self, tokens: list[Token], text: str) -> dict[str, float]:
        """
        Detect emotions in text.

        Args:
            tokens: Sentence tokens
            text: Sentence text

        Returns:
            Dictionary of emotion -> intensity
        """
        emotion_counts: dict[str, int] = defaultdict(int)

        for token in tokens:
            word = token.text.lower()
            if word in self.emotions:
                emotion = self.emotions[word]
                emotion_counts[emotion] += 1

        # Convert to intensities
        emotions: dict[str, float] = {}
        total = sum(emotion_counts.values())

        if total > 0:
            for emotion, count in emotion_counts.items():
                emotions[emotion] = count / total

        return emotions

    def _compute_subjectivity(self, tokens: list[Token], text: str) -> float:
        """
        Compute subjectivity score.

        Args:
            tokens: Sentence tokens
            text: Sentence text

        Returns:
            Subjectivity [0, 1]
        """
        subjectivity_indicators = {
            "i",
            "we",
            "believe",
            "think",
            "feel",
            "opinion",
            "seem",
            "appear",
            "perhaps",
            "maybe",
            "probably",
            "likely",
            "doubt",
        }

        count = sum(1 for t in tokens if t.text.lower() in subjectivity_indicators)
        return min(1.0, count / max(1, len(tokens)))

    def _extract_sentiment_phrases(self, tokens: list[Token], text: str, sentiment_type: str) -> list[str]:
        """
        Extract sentiment-bearing phrases.

        Args:
            tokens: Sentence tokens
            text: Sentence text
            sentiment_type: 'positive' or 'negative'

        Returns:
            List of sentiment phrases
        """
        phrases = []
        lexicon = self.positive_words if sentiment_type == "positive" else self.negative_words

        for i, token in enumerate(tokens):
            if token.text.lower() in lexicon:
                # Extract phrase around sentiment word
                start = max(0, i - 2)
                end = min(len(tokens), i + 3)
                phrase_tokens = [t.text for t in tokens[start:end]]
                phrase = " ".join(phrase_tokens)
                phrases.append(phrase)

        return phrases
