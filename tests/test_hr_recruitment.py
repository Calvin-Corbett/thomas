"""Tests for recruitment system."""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from thomas.hr_platform._exceptions import RecruitmentError
from thomas.hr_platform._types import Position
from thomas.hr_platform.recruitment import (
    RecruitmentManager,
    RecruitmentPipeline,
    ResumeParser,
)


class TestRecruitmentManager:
    """Test recruitment functionality."""

    @pytest.fixture
    def manager(self) -> RecruitmentManager:
        """Create recruitment manager."""
        return RecruitmentManager()

    @pytest.fixture
    def position(self) -> Position:
        """Create test position."""
        return Position(
            id="pos1",
            title="Software Engineer",
            department_id="dept1",
            level="Senior",
            salary_min=Decimal("100000"),
            salary_max=Decimal("150000"),
            salary_mid=Decimal("125000"),
        )

    def test_create_posting(self, manager: RecruitmentManager, position: Position) -> None:
        """Test creating job posting."""
        posting = manager.create_posting(
            position,
            "Senior Software Engineer",
            "We seek an experienced engineer",
            ["Python", "AWS", "Docker"],
            date(2024, 6, 30),
        )

        assert posting.position_id == position.id
        assert posting.title == "Senior Software Engineer"
        assert posting.is_open

    def test_close_posting(self, manager: RecruitmentManager, position: Position) -> None:
        """Test closing job posting."""
        posting = manager.create_posting(
            position,
            "Senior Software Engineer",
            "We seek an experienced engineer",
            ["Python", "AWS"],
            date(2024, 6, 30),
        )

        closed = manager.close_posting(posting.id)

        assert not closed.is_open

    def test_posting_accepting_applications(self, manager: RecruitmentManager, position: Position) -> None:
        """Test checking if posting is accepting applications."""
        posting = manager.create_posting(
            position,
            "Senior Software Engineer",
            "We seek an experienced engineer",
            ["Python"],
            date.today() + timedelta(days=30),
        )

        assert posting.is_accepting_applications()

    def test_add_candidate(self, manager: RecruitmentManager, position: Position) -> None:
        """Test adding candidate."""
        candidate = manager.add_candidate(
            position.id,
            "Jane",
            "Smith",
            "jane@example.com",
            "555-1234",
            "linkedin",
            "Experienced engineer. Skills: Python, Java, AWS.",
        )

        assert candidate.position_id == position.id
        assert candidate.status == "applied"
        assert "python" in [kw.lower() for kw in candidate.resume_keywords]

    def test_candidate_resume_parsing(self) -> None:
        """Test resume keyword extraction."""
        resume = "Expert in Python, JavaScript, React, and Node.js"
        keywords = ResumeParser.extract_keywords(resume)

        assert "python" in keywords
        assert "javascript" in keywords
        assert "react" in keywords
        assert "node" in keywords

    def test_candidate_match_score(self, manager: RecruitmentManager, position: Position) -> None:
        """Test resume match scoring."""
        candidate = manager.add_candidate(
            position.id,
            "John",
            "Doe",
            "john@example.com",
            "555-5678",
            "linkedin",
            "Skills: Python, AWS, Docker, Kubernetes",
        )

        score = candidate.match_score(["Python", "AWS", "Docker"])

        assert score == Decimal("100")

    def test_candidate_partial_match(self, manager: RecruitmentManager, position: Position) -> None:
        """Test partial resume match."""
        candidate = manager.add_candidate(
            position.id,
            "John",
            "Doe",
            "john@example.com",
            "555-5678",
            "linkedin",
            "Skills: Python, Java",
        )

        score = candidate.match_score(["Python", "AWS", "Docker"])

        assert score == Decimal("33.33")

    def test_move_candidate(self, manager: RecruitmentManager, position: Position) -> None:
        """Test moving candidate through pipeline."""
        candidate = manager.add_candidate(
            position.id,
            "Jane",
            "Smith",
            "jane@example.com",
            "555-1234",
        )

        updated = manager.move_candidate(candidate.id, "screened")

        assert updated.status == "screened"

    def test_schedule_interview(self, manager: RecruitmentManager, position: Position) -> None:
        """Test scheduling interview."""
        candidate = manager.add_candidate(
            position.id,
            "Jane",
            "Smith",
            "jane@example.com",
            "555-1234",
        )

        interview_dt = datetime(2024, 6, 15, 14, 0, 0)
        interview = manager.schedule_interview(
            candidate.id,
            position.id,
            "int1",
            interview_dt,
            "phone",
        )

        assert interview.candidate_id == candidate.id
        assert interview.interview_type == "phone"

    def test_record_interview_results(self, manager: RecruitmentManager, position: Position) -> None:
        """Test recording interview results."""
        candidate = manager.add_candidate(
            position.id,
            "Jane",
            "Smith",
            "jane@example.com",
            "555-1234",
        )

        interview_dt = datetime(2024, 6, 15, 14, 0, 0)
        interview = manager.schedule_interview(
            candidate.id,
            position.id,
            "int1",
            interview_dt,
        )

        scorecard = {"technical": 4, "communication": 5, "culture_fit": 4}
        updated = manager.record_interview_results(
            interview.id,
            Decimal("4.5"),
            "Strong candidate",
            scorecard,
            True,
            30,
        )

        assert updated.rating == Decimal("4.5")
        assert updated.recommended

    def test_extend_offer(self, manager: RecruitmentManager, position: Position) -> None:
        """Test extending job offer."""
        candidate = manager.add_candidate(
            position.id,
            "Jane",
            "Smith",
            "jane@example.com",
            "555-1234",
        )

        offer = manager.extend_offer(
            candidate.id,
            position.id,
            Decimal("125000"),
            date(2024, 8, 1),
            "Health, dental, 401k",
        )

        assert offer["candidate_id"] == candidate.id
        assert offer["salary"] == Decimal("125000")
        assert offer["status"] == "pending"

    def test_accept_offer(self, manager: RecruitmentManager, position: Position) -> None:
        """Test accepting job offer."""
        candidate = manager.add_candidate(
            position.id,
            "Jane",
            "Smith",
            "jane@example.com",
            "555-1234",
        )

        manager.extend_offer(
            candidate.id,
            position.id,
            Decimal("125000"),
            date(2024, 8, 1),
        )

        hired = manager.accept_offer(candidate.id)

        assert hired.status == "hired"
        assert hired.hire_date == date(2024, 8, 1)

    def test_reject_candidate(self, manager: RecruitmentManager, position: Position) -> None:
        """Test rejecting candidate."""
        candidate = manager.add_candidate(
            position.id,
            "Jane",
            "Smith",
            "jane@example.com",
            "555-1234",
        )

        rejected = manager.reject_candidate(candidate.id, "Insufficient experience")

        assert rejected.status == "rejected"
        assert rejected.rejection_reason == "Insufficient experience"

    def test_get_candidates_by_position(self, manager: RecruitmentManager, position: Position) -> None:
        """Test getting candidates by position."""
        cand1 = manager.add_candidate(position.id, "Jane", "Smith", "jane@example.com", "555-1")
        cand2 = manager.add_candidate(position.id, "John", "Doe", "john@example.com", "555-2")

        candidates = manager.get_candidates_by_position(position.id)

        assert len(candidates) == 2

    def test_get_candidates_by_status(self, manager: RecruitmentManager, position: Position) -> None:
        """Test filtering candidates by status."""
        cand1 = manager.add_candidate(position.id, "Jane", "Smith", "jane@example.com", "555-1")
        cand2 = manager.add_candidate(position.id, "John", "Doe", "john@example.com", "555-2")

        manager.move_candidate(cand1.id, "interviewed")

        interviewed = manager.get_candidates_by_status("interviewed")

        assert len(interviewed) == 1
        assert interviewed[0].id == cand1.id

    def test_time_to_fill(self, manager: RecruitmentManager, position: Position) -> None:
        """Test calculating time to fill."""
        candidate = manager.add_candidate(
            position.id,
            "Jane",
            "Smith",
            "jane@example.com",
            "555-1234",
        )

        manager.extend_offer(
            candidate.id,
            position.id,
            Decimal("125000"),
            date.today() + timedelta(days=15),
        )

        manager.accept_offer(candidate.id)

        time_to_fill = manager.calculate_time_to_fill(position.id)

        assert time_to_fill is not None
        assert time_to_fill > 0

    def test_source_effectiveness(self, manager: RecruitmentManager, position: Position) -> None:
        """Test analyzing source effectiveness."""
        cand1 = manager.add_candidate(
            position.id,
            "Jane",
            "Smith",
            "jane@example.com",
            "555-1",
            "linkedin",
        )

        manager.extend_offer(cand1.id, position.id, Decimal("125000"), date.today() + timedelta(days=15))
        manager.accept_offer(cand1.id)

        effectiveness = manager.get_source_effectiveness()

        assert "linkedin" in effectiveness
        assert effectiveness["linkedin"]["conversion_rate"] == Decimal("100.00")

    def test_pipeline_analytics(self, manager: RecruitmentManager, position: Position) -> None:
        """Test pipeline stage analytics."""
        manager.add_candidate(position.id, "Jane", "Smith", "jane@example.com", "555-1")
        manager.add_candidate(position.id, "John", "Doe", "john@example.com", "555-2")

        analytics = manager.get_pipeline_analytics(position.id)

        assert analytics["applied"] == 2

    def test_interview_statistics(self, manager: RecruitmentManager, position: Position) -> None:
        """Test interview statistics."""
        candidate = manager.add_candidate(
            position.id,
            "Jane",
            "Smith",
            "jane@example.com",
            "555-1234",
        )

        interview_dt = datetime(2024, 6, 15, 14, 0, 0)
        interview = manager.schedule_interview(
            candidate.id,
            position.id,
            "int1",
            interview_dt,
        )

        manager.record_interview_results(
            interview.id,
            Decimal("4.5"),
            "Great",
            {"technical": 5},
            True,
        )

        stats = manager.get_interview_statistics()

        assert stats["total_interviews"] == 1
        assert stats["recommended_count"] == 1
        assert stats["recommendation_rate"] == Decimal("100.00")

    def test_recruitment_pipeline_stages(self) -> None:
        """Test recruitment pipeline."""
        pipeline = RecruitmentPipeline(["applied", "screened", "interviewed", "offered", "hired", "rejected"])

        next_stage = pipeline.get_next_stage("applied")
        assert next_stage == "screened"

        prev_stage = pipeline.get_previous_stage("screened")
        assert prev_stage == "applied"

    def test_invalid_candidate(self, manager: RecruitmentManager) -> None:
        """Test error handling for invalid candidate."""
        with pytest.raises(RecruitmentError):
            manager.move_candidate("nonexistent", "screened")
