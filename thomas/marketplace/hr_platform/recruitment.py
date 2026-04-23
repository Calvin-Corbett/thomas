"""Recruitment system with ATS, resume parsing, and pipeline analytics."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from thomas.marketplace.hr_platform._exceptions import RecruitmentError
from thomas.marketplace.hr_platform._types import Candidate, Interview, Position


class JobPosting:
    """Job posting for recruitment."""

    def __init__(
        self,
        id: str,
        position_id: str,
        title: str,
        description: str,
        published_date: date,
        closing_date: date,
        required_keywords: list[str],
        min_experience_years: int = 0,
    ) -> None:
        """Initialize job posting.

        Args:
            id: Posting ID
            position_id: Associated position ID
            title: Job title
            description: Job description
            published_date: When posting was published
            closing_date: Application deadline
            required_keywords: Required skills/keywords
            min_experience_years: Minimum experience required
        """
        self.id = id
        self.position_id = position_id
        self.title = title
        self.description = description
        self.published_date = published_date
        self.closing_date = closing_date
        self.required_keywords = required_keywords
        self.min_experience_years = min_experience_years
        self.is_open = True

    def is_accepting_applications(self) -> bool:
        """Check if posting is still accepting applications."""
        return self.is_open and date.today() <= self.closing_date


class RecruitmentPipeline:
    """Defines stages and flow of recruitment process."""

    def __init__(self, stages: list[str]) -> None:
        """Initialize pipeline with stages.

        Args:
            stages: List of pipeline stage names in order
        """
        self.stages = stages
        self.stage_map = {stage: idx for idx, stage in enumerate(stages)}

    def get_next_stage(self, current_stage: str) -> str | None:
        """Get next pipeline stage.

        Args:
            current_stage: Current stage name

        Returns:
            Next stage name or None if at end
        """
        if current_stage not in self.stage_map:
            return None
        current_idx = self.stage_map[current_stage]
        if current_idx < len(self.stages) - 1:
            return self.stages[current_idx + 1]
        return None

    def get_previous_stage(self, current_stage: str) -> str | None:
        """Get previous pipeline stage.

        Args:
            current_stage: Current stage name

        Returns:
            Previous stage name or None if at beginning
        """
        if current_stage not in self.stage_map:
            return None
        current_idx = self.stage_map[current_stage]
        if current_idx > 0:
            return self.stages[current_idx - 1]
        return None


class ResumeParser:
    """Simulates resume parsing and keyword extraction."""

    @staticmethod
    def extract_keywords(resume_text: str) -> list[str]:
        """Extract technical keywords from resume.

        Args:
            resume_text: Resume text content

        Returns:
            List of extracted keywords
        """
        # Common technical keywords
        keywords = {
            "python",
            "java",
            "javascript",
            "c++",
            "golang",
            "rust",
            "sql",
            "nosql",
            "mongodb",
            "postgres",
            "mysql",
            "aws",
            "azure",
            "gcp",
            "kubernetes",
            "docker",
            "react",
            "vue",
            "angular",
            "node",
            "django",
            "machine learning",
            "ai",
            "data science",
            "analytics",
            "agile",
            "scrum",
            "devops",
            "ci/cd",
            "git",
            "rest",
            "graphql",
            "api",
            "microservices",
            "project management",
            "leadership",
            "communication",
        }

        text_lower = resume_text.lower()
        found_keywords = [kw for kw in keywords if kw in text_lower]
        return found_keywords


class RecruitmentManager:
    """Manages recruitment process from posting to hire."""

    def __init__(self) -> None:
        """Initialize recruitment manager."""
        self.postings: dict[str, JobPosting] = {}
        self.candidates: dict[str, Candidate] = {}
        self.interviews: dict[str, Interview] = {}
        self.offers: dict[str, dict] = {}  # candidate_id -> offer details
        self.pipeline = RecruitmentPipeline(
            [
                "applied",
                "screened",
                "interviewed",
                "offered",
                "hired",
                "rejected",
            ]
        )

    def create_posting(
        self,
        position: Position,
        title: str,
        description: str,
        required_keywords: list[str],
        closing_date: date,
    ) -> JobPosting:
        """Create a new job posting.

        Args:
            position: Position object
            title: Job title
            description: Job description
            required_keywords: Required skills
            closing_date: Application deadline

        Returns:
            The created JobPosting
        """
        posting_id = str(uuid.uuid4())
        posting = JobPosting(
            posting_id,
            position.id,
            title,
            description,
            date.today(),
            closing_date,
            required_keywords,
        )
        self.postings[posting_id] = posting
        return posting

    def close_posting(self, posting_id: str) -> JobPosting:
        """Close a job posting.

        Args:
            posting_id: ID of posting to close

        Returns:
            Updated JobPosting

        Raises:
            RecruitmentError: If posting not found
        """
        if posting_id not in self.postings:
            raise RecruitmentError(f"Posting {posting_id} not found")

        posting = self.postings[posting_id]
        posting.is_open = False
        return posting

    def add_candidate(
        self,
        position_id: str,
        first_name: str,
        last_name: str,
        email: str,
        phone: str,
        source: str = "job_board",
        resume_text: str | None = None,
    ) -> Candidate:
        """Add a candidate application.

        Args:
            position_id: Position applied for
            first_name: Candidate first name
            last_name: Candidate last name
            email: Candidate email
            phone: Candidate phone
            source: Application source
            resume_text: Resume content for parsing

        Returns:
            The created Candidate
        """
        candidate = Candidate(
            id=str(uuid.uuid4()),
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone=phone,
            position_id=position_id,
            source=source,
        )

        if resume_text:
            candidate.resume_keywords = ResumeParser.extract_keywords(resume_text)

        self.candidates[candidate.id] = candidate
        return candidate

    def move_candidate(self, candidate_id: str, new_status: str) -> Candidate:
        """Move candidate to next pipeline stage.

        Args:
            candidate_id: ID of candidate
            new_status: New status/stage

        Returns:
            Updated Candidate

        Raises:
            RecruitmentError: If candidate not found
        """
        if candidate_id not in self.candidates:
            raise RecruitmentError(f"Candidate {candidate_id} not found")

        candidate = self.candidates[candidate_id]
        if new_status not in self.pipeline.stage_map:
            raise RecruitmentError(f"Invalid status: {new_status}")

        candidate.status = new_status
        candidate.current_stage = self.pipeline.stage_map[new_status]
        return candidate

    def schedule_interview(
        self,
        candidate_id: str,
        position_id: str,
        interviewer_id: str,
        interview_date: datetime,
        interview_type: str = "phone",
    ) -> Interview:
        """Schedule an interview with a candidate.

        Args:
            candidate_id: ID of candidate
            position_id: ID of position
            interviewer_id: ID of interviewer
            interview_date: Date and time of interview
            interview_type: Type of interview (phone, video, in_person)

        Returns:
            The created Interview

        Raises:
            RecruitmentError: If candidate not found
        """
        if candidate_id not in self.candidates:
            raise RecruitmentError(f"Candidate {candidate_id} not found")

        interview = Interview(
            id=str(uuid.uuid4()),
            candidate_id=candidate_id,
            position_id=position_id,
            interviewer_id=interviewer_id,
            interview_date=interview_date,
            interview_type=interview_type,
            duration_minutes=0,
            rating=Decimal("0"),
            feedback="",
        )

        self.interviews[interview.id] = interview
        return interview

    def record_interview_results(
        self,
        interview_id: str,
        rating: Decimal,
        feedback: str,
        scorecard: dict[str, int],
        recommended: bool,
        duration_minutes: int = 30,
    ) -> Interview:
        """Record interview results and feedback.

        Args:
            interview_id: ID of interview
            rating: Interview rating (1-5)
            feedback: Interview feedback
            scorecard: Scores for evaluation criteria
            recommended: Whether to move forward
            duration_minutes: Interview duration

        Returns:
            Updated Interview

        Raises:
            RecruitmentError: If interview not found
        """
        if interview_id not in self.interviews:
            raise RecruitmentError(f"Interview {interview_id} not found")

        interview = self.interviews[interview_id]
        interview.rating = rating
        interview.feedback = feedback
        interview.scorecard = scorecard
        interview.recommended = recommended
        interview.duration_minutes = duration_minutes

        if recommended:
            self.move_candidate(interview.candidate_id, "offered")

        return interview

    def extend_offer(
        self,
        candidate_id: str,
        position_id: str,
        salary: Decimal,
        start_date: date,
        benefits_summary: str = "",
    ) -> dict:
        """Extend a job offer to candidate.

        Args:
            candidate_id: ID of candidate
            position_id: ID of position
            salary: Annual salary
            start_date: Employment start date
            benefits_summary: Summary of benefits

        Returns:
            Offer details dictionary

        Raises:
            RecruitmentError: If candidate not found
        """
        if candidate_id not in self.candidates:
            raise RecruitmentError(f"Candidate {candidate_id} not found")

        candidate = self.candidates[candidate_id]
        offer = {
            "id": str(uuid.uuid4()),
            "candidate_id": candidate_id,
            "position_id": position_id,
            "salary": salary,
            "start_date": start_date,
            "benefits": benefits_summary,
            "extended_date": date.today(),
            "status": "pending",
        }

        self.offers[candidate_id] = offer
        candidate.offer_extended_date = date.today()

        return offer

    def accept_offer(self, candidate_id: str) -> Candidate:
        """Accept an offer (mark as hired).

        Args:
            candidate_id: ID of candidate

        Returns:
            Updated Candidate with hire_date set

        Raises:
            RecruitmentError: If candidate not found or no offer
        """
        if candidate_id not in self.candidates:
            raise RecruitmentError(f"Candidate {candidate_id} not found")

        if candidate_id not in self.offers:
            raise RecruitmentError(f"No offer for candidate {candidate_id}")

        candidate = self.candidates[candidate_id]
        offer = self.offers[candidate_id]

        candidate.status = "hired"
        candidate.hire_date = offer["start_date"]

        return candidate

    def reject_candidate(self, candidate_id: str, rejection_reason: str = "") -> Candidate:
        """Reject a candidate.

        Args:
            candidate_id: ID of candidate
            rejection_reason: Reason for rejection

        Returns:
            Updated Candidate

        Raises:
            RecruitmentError: If candidate not found
        """
        if candidate_id not in self.candidates:
            raise RecruitmentError(f"Candidate {candidate_id} not found")

        candidate = self.candidates[candidate_id]
        candidate.status = "rejected"
        candidate.rejection_reason = rejection_reason

        if candidate_id in self.offers:
            del self.offers[candidate_id]

        return candidate

    def get_candidates_by_position(self, position_id: str) -> list[Candidate]:
        """Get all candidates for a position.

        Args:
            position_id: ID of position

        Returns:
            List of candidates
        """
        return [c for c in self.candidates.values() if c.position_id == position_id]

    def get_candidates_by_status(self, status: str) -> list[Candidate]:
        """Get candidates by current status.

        Args:
            status: Status to filter by

        Returns:
            List of candidates
        """
        return [c for c in self.candidates.values() if c.status == status]

    def calculate_time_to_fill(self, position_id: str) -> int | None:
        """Calculate average days to fill a position.

        Args:
            position_id: ID of position

        Returns:
            Average days from first application to hire, or None if not filled
        """
        position_candidates = self.get_candidates_by_position(position_id)
        hired = [c for c in position_candidates if c.status == "hired"]

        if not hired:
            return None

        times = []
        for candidate in hired:
            if candidate.hire_date and candidate.created_at.date():
                days = (candidate.hire_date - candidate.created_at.date()).days
                times.append(days)

        return round(sum(times) / len(times)) if times else None

    def get_source_effectiveness(self) -> dict[str, dict[str, any]]:
        """Analyze effectiveness of candidate sources.

        Returns:
            Dictionary with metrics per source
        """
        sources: dict[str, dict[str, any]] = {}

        for candidate in self.candidates.values():
            if candidate.source not in sources:
                sources[candidate.source] = {
                    "total": 0,
                    "hired": 0,
                    "conversion_rate": Decimal("0"),
                }

            sources[candidate.source]["total"] += 1
            if candidate.status == "hired":
                sources[candidate.source]["hired"] += 1

        for source in sources:
            total = sources[source]["total"]
            hired = sources[source]["hired"]
            if total > 0:
                sources[source]["conversion_rate"] = (
                    Decimal(str(hired)) / Decimal(str(total)) * Decimal("100")
                ).quantize(Decimal("0.01"))

        return sources

    def get_pipeline_analytics(self, position_id: str) -> dict[str, int]:
        """Get candidate counts by pipeline stage for a position.

        Args:
            position_id: ID of position

        Returns:
            Dictionary of stage -> candidate count
        """
        analytics: dict[str, int] = {stage: 0 for stage in self.pipeline.stages}

        for candidate in self.get_candidates_by_position(position_id):
            if candidate.status in analytics:
                analytics[candidate.status] += 1

        return analytics

    def get_interview_statistics(self) -> dict[str, any]:
        """Get overall interview statistics.

        Returns:
            Dictionary with interview metrics
        """
        if not self.interviews:
            return {
                "total_interviews": 0,
                "average_rating": Decimal("0"),
                "recommended_count": 0,
            }

        recommended = sum(1 for i in self.interviews.values() if i.recommended)
        avg_rating = sum(i.rating for i in self.interviews.values()) / len(self.interviews)

        return {
            "total_interviews": len(self.interviews),
            "average_rating": avg_rating.quantize(Decimal("0.01")),
            "recommended_count": recommended,
            "recommendation_rate": (
                Decimal(str(recommended)) / Decimal(str(len(self.interviews))) * Decimal("100")
            ).quantize(Decimal("0.01")),
        }
