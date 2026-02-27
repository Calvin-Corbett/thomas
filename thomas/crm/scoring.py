"""
Lead and deal scoring engine for the CRM.
"""

from datetime import datetime
from typing import Any

from thomas.crm._types import Contact, LeadScore


class ScoringEngine:
    """Scoring engine for leads and deals.

    Provides configurable scoring models including demographic scoring,
    behavioral scoring, predictive scoring, and score decay.
    """

    def __init__(self) -> None:
        """Initialize the scoring engine."""
        self._lead_scores: dict[str, LeadScore] = {}
        self._scoring_config: dict[str, Any] = {
            "demographic_weight": 0.3,
            "behavioral_weight": 0.4,
            "predictive_weight": 0.3,
            "score_decay_days": 90,
            "decay_rate": 0.1,  # 10% per decay period
        }

    def configure_scoring(
        self,
        demographic_weight: float = 0.3,
        behavioral_weight: float = 0.4,
        predictive_weight: float = 0.3,
        score_decay_days: int = 90,
        decay_rate: float = 0.1,
    ) -> None:
        """Configure the scoring model.

        Args:
            demographic_weight: Weight for demographic factors (0-1)
            behavioral_weight: Weight for behavioral factors (0-1)
            predictive_weight: Weight for predictive factors (0-1)
            score_decay_days: Days for score decay cycle
            decay_rate: Decay rate per cycle (0-1)
        """
        total_weight = demographic_weight + behavioral_weight + predictive_weight

        if total_weight != 1.0:
            # Normalize weights
            demographic_weight /= total_weight
            behavioral_weight /= total_weight
            predictive_weight /= total_weight

        self._scoring_config = {
            "demographic_weight": demographic_weight,
            "behavioral_weight": behavioral_weight,
            "predictive_weight": predictive_weight,
            "score_decay_days": score_decay_days,
            "decay_rate": decay_rate,
        }

    def score_lead(
        self,
        contact: Contact,
        demographic_data: dict[str, Any] | None = None,
        behavioral_data: dict[str, Any] | None = None,
        historical_conversions: list[dict[str, Any]] | None = None,
    ) -> LeadScore:
        """Score a lead using configurable components.

        Args:
            contact: Contact object to score
            demographic_data: Demographic attributes
            behavioral_data: Behavioral signals
            historical_conversions: Historical conversion data for prediction

        Returns:
            LeadScore object
        """
        demographic_score = self._calculate_demographic_score(contact, demographic_data or {})

        behavioral_score = self._calculate_behavioral_score(contact, behavioral_data or {})

        predictive_score = self._calculate_predictive_score(contact, historical_conversions or [])

        # Calculate weighted total
        weights = self._scoring_config
        total_score = int(
            (demographic_score * weights["demographic_weight"])
            + (behavioral_score * weights["behavioral_weight"])
            + (predictive_score * weights["predictive_weight"])
        )

        # Determine grade
        grade = self._score_to_grade(total_score)

        explanation = self._generate_explanation(
            contact,
            demographic_score,
            behavioral_score,
            predictive_score,
        )

        lead_score = LeadScore(
            contact_id=contact.id,
            total_score=total_score,
            demographic_score=int(demographic_score),
            behavioral_score=int(behavioral_score),
            predictive_score=int(predictive_score),
            grade=grade,
            explanation=explanation,
        )

        self._lead_scores[contact.id] = lead_score
        return lead_score

    def _calculate_demographic_score(
        self,
        contact: Contact,
        demographic_data: dict[str, Any],
    ) -> float:
        """Calculate demographic score component.

        Args:
            contact: Contact object
            demographic_data: Demographic attributes

        Returns:
            Score 0-100
        """
        score = 50.0  # Default mid-range

        # Title scoring
        executive_titles = {"CEO", "CTO", "CFO", "COO", "VP", "SVP", "President"}
        if contact.title:
            title_upper = contact.title.upper()
            if any(exec_title in title_upper for exec_title in executive_titles):
                score += 20
            elif any(word in title_upper for word in {"DIRECTOR", "MANAGER", "LEAD", "SENIOR"}):
                score += 10

        # Company size scoring
        company_size = demographic_data.get("company_size")
        if company_size:
            if isinstance(company_size, int):
                if company_size > 1000:
                    score += 15
                elif company_size > 500:
                    score += 10
                elif company_size > 100:
                    score += 5

        # Industry scoring
        high_value_industries = {"Technology", "Finance", "Healthcare", "Professional Services", "Insurance"}
        industry = demographic_data.get("industry")
        if industry:
            if any(ind.lower() in industry.lower() for ind in high_value_industries):
                score += 10

        # Revenue scoring
        revenue = demographic_data.get("revenue")
        if revenue:
            try:
                if isinstance(revenue, (int, float)):
                    if revenue > 1000000000:  # >$1B
                        score += 15
                    elif revenue > 100000000:  # >$100M
                        score += 10
                    elif revenue > 10000000:  # >$10M
                        score += 5
            except (ValueError, TypeError):
                pass

        return min(score, 100.0)

    def _calculate_behavioral_score(
        self,
        contact: Contact,
        behavioral_data: dict[str, Any],
    ) -> float:
        """Calculate behavioral score component.

        Args:
            contact: Contact object
            behavioral_data: Behavioral signals

        Returns:
            Score 0-100
        """
        score = 0.0

        # Email engagement
        email_opens = behavioral_data.get("email_opens", 0)
        email_clicks = behavioral_data.get("email_clicks", 0)
        if email_opens > 5:
            score += 15
        elif email_opens > 3:
            score += 10
        elif email_opens > 0:
            score += 5

        if email_clicks > 2:
            score += 10
        elif email_clicks > 0:
            score += 5

        # Website engagement
        website_visits = behavioral_data.get("website_visits", 0)
        if website_visits > 10:
            score += 15
        elif website_visits > 5:
            score += 10
        elif website_visits > 0:
            score += 5

        # Form fills
        form_fills = behavioral_data.get("form_fills", 0)
        score += form_fills * 10

        # Content downloads
        downloads = behavioral_data.get("content_downloads", 0)
        score += downloads * 5

        # Page viewing - pricing and demo pages indicate strong interest
        demo_page_views = behavioral_data.get("demo_page_views", 0)
        pricing_page_views = behavioral_data.get("pricing_page_views", 0)
        score += demo_page_views * 20
        score += pricing_page_views * 15

        # Recent activity bonus
        last_activity = behavioral_data.get("last_activity_date")
        if last_activity:
            if isinstance(last_activity, str):
                last_activity = datetime.fromisoformat(last_activity)

            days_since_activity = (datetime.utcnow() - last_activity).days
            if days_since_activity < 7:
                score += 20
            elif days_since_activity < 30:
                score += 10
            elif days_since_activity > 90:
                score -= 10

        return min(score, 100.0)

    def _calculate_predictive_score(
        self,
        contact: Contact,
        historical_conversions: list[dict[str, Any]],
    ) -> float:
        """Calculate predictive score using logistic regression.

        Args:
            contact: Contact object
            historical_conversions: Historical conversion data

        Returns:
            Score 0-100
        """
        if not historical_conversions:
            return 50.0  # Default if no history

        # Simplified logistic regression approach
        conversion_rate = (
            sum(1 for h in historical_conversions if h.get("converted", False)) / len(historical_conversions)
            if historical_conversions
            else 0.5
        )

        # Base probability from historical data
        base_score = conversion_rate * 100

        # Adjust based on similarity to conversion profile
        converted_profiles = [h for h in historical_conversions if h.get("converted", False)]

        if converted_profiles:
            # Check title similarity
            converted_titles = [p.get("title", "").upper() for p in converted_profiles]
            if contact.title and any(
                word in contact.title.upper()
                for profile_title in converted_titles
                for word in profile_title.split()
                if word
            ):
                base_score += 10

        return min(base_score, 100.0)

    def _score_to_grade(self, score: int) -> str:
        """Convert a numeric score to a letter grade.

        Args:
            score: Score 0-100

        Returns:
            Grade A-F
        """
        if score >= 90:
            return "A"
        elif score >= 80:
            return "B"
        elif score >= 70:
            return "C"
        elif score >= 60:
            return "D"
        else:
            return "F"

    def _generate_explanation(
        self,
        contact: Contact,
        demographic_score: float,
        behavioral_score: float,
        predictive_score: float,
    ) -> list[str]:
        """Generate an explanation for the scoring.

        Args:
            contact: Contact object
            demographic_score: Demographic component
            behavioral_score: Behavioral component
            predictive_score: Predictive component

        Returns:
            List of explanation strings
        """
        explanation = []

        if demographic_score > 70:
            explanation.append("Strong demographic fit")
        if behavioral_score > 70:
            explanation.append("High engagement signals")
        if predictive_score > 70:
            explanation.append("Strong historical conversion patterns")

        if contact.title:
            explanation.append(f"Title: {contact.title}")

        if contact.company:
            explanation.append(f"Company: {contact.company}")

        if behavioral_score < 40:
            explanation.append("Limited recent engagement")

        return explanation

    def apply_score_decay(
        self,
        contact_id: str,
        last_activity_date: datetime,
    ) -> LeadScore | None:
        """Apply score decay based on inactivity.

        Score decays over time when there's no engagement.

        Args:
            contact_id: Contact ID
            last_activity_date: Date of last activity

        Returns:
            Updated LeadScore or None if not found
        """
        if contact_id not in self._lead_scores:
            return None

        lead_score = self._lead_scores[contact_id]
        config = self._scoring_config

        # Calculate decay
        days_inactive = (datetime.utcnow() - last_activity_date).days
        decay_periods = days_inactive / config["score_decay_days"]

        # Exponential decay: score * (1 - decay_rate) ^ periods
        decay_factor = (1 - config["decay_rate"]) ** decay_periods
        decayed_score = int(lead_score.total_score * decay_factor)

        lead_score.total_score = decayed_score
        lead_score.grade = self._score_to_grade(decayed_score)
        lead_score.last_updated = datetime.utcnow()

        return lead_score

    def get_lead_score(self, contact_id: str) -> LeadScore | None:
        """Get the current lead score for a contact.

        Args:
            contact_id: Contact ID

        Returns:
            LeadScore object or None if not found
        """
        return self._lead_scores.get(contact_id)

    def get_high_value_leads(
        self,
        min_score: int = 80,
    ) -> list[LeadScore]:
        """Get leads above a certain score threshold.

        Args:
            min_score: Minimum score threshold

        Returns:
            List of high-value LeadScore objects
        """
        return [score for score in self._lead_scores.values() if score.total_score >= min_score]

    def get_at_risk_leads(self) -> list[LeadScore]:
        """Get leads with declining scores due to inactivity.

        Returns:
            List of at-risk LeadScore objects
        """
        return [score for score in self._lead_scores.values() if score.total_score < 40]

    def compare_scores(
        self,
        contact_id1: str,
        contact_id2: str,
    ) -> dict[str, Any] | None:
        """Compare scores between two contacts.

        Args:
            contact_id1: First contact ID
            contact_id2: Second contact ID

        Returns:
            Dictionary with comparison or None if contacts not scored
        """
        score1 = self._lead_scores.get(contact_id1)
        score2 = self._lead_scores.get(contact_id2)

        if not score1 or not score2:
            return None

        return {
            "contact1_id": contact_id1,
            "contact1_score": score1.total_score,
            "contact1_grade": score1.grade,
            "contact2_id": contact_id2,
            "contact2_score": score2.total_score,
            "contact2_grade": score2.grade,
            "score_difference": score1.total_score - score2.total_score,
            "higher_score": (contact_id1 if score1.total_score > score2.total_score else contact_id2),
        }
