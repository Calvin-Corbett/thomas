"""Compliance and regulatory tracking module for legal practice operations."""

import difflib
import logging
from datetime import date, datetime, timedelta
from enum import Enum
from uuid import uuid4

logger = logging.getLogger(__name__)


class ComplianceStatus(Enum):
    """Enumeration of compliance statuses."""

    DRAFT = "draft"
    REVIEW = "review"
    APPROVED = "approved"
    PUBLISHED = "published"
    RETIRED = "retired"


class ComplianceObligation:
    """Represents a compliance obligation with due dates."""

    def __init__(
        self,
        obligation_id: str,
        title: str,
        description: str,
        due_date: date,
        responsible_party: str,
        regulation: str,
        status: str = "pending",
    ) -> None:
        """Initialize a compliance obligation."""
        self.obligation_id = obligation_id
        self.title = title
        self.description = description
        self.due_date = due_date
        self.responsible_party = responsible_party
        self.regulation = regulation
        self.status = status
        self.created_at = datetime.now()
        self.completed_at: datetime | None = None
        self.notes: str = ""


class CompliancePolicy:
    """Represents a compliance policy with lifecycle."""

    def __init__(
        self,
        policy_id: str,
        title: str,
        content: str,
        status: ComplianceStatus = ComplianceStatus.DRAFT,
    ) -> None:
        """Initialize a compliance policy."""
        self.policy_id = policy_id
        self.title = title
        self.content = content
        self.status = status
        self.version = 1
        self.created_at = datetime.now()
        self.published_at: datetime | None = None
        self.retired_at: datetime | None = None
        self.effective_date = date.today()


class ComplianceRisk:
    """Represents a compliance risk with probability and impact scoring."""

    def __init__(
        self,
        risk_id: str,
        title: str,
        description: str,
        probability: int,  # 1-5
        impact: int,  # 1-5
        area: str,
    ) -> None:
        """Initialize a compliance risk."""
        self.risk_id = risk_id
        self.title = title
        self.description = description
        self.probability = probability
        self.impact = impact
        self.area = area
        self.risk_score = probability * impact
        self.created_at = datetime.now()
        self.mitigation_plan: str = ""
        self.status = "open"


class ComplianceManager:
    """Manages compliance obligations, policies, and risk assessment."""

    def __init__(self) -> None:
        """Initialize the compliance manager."""
        self.obligations: dict[str, ComplianceObligation] = {}
        self.policies: dict[str, list[CompliancePolicy]] = {}
        self.risks: dict[str, ComplianceRisk] = {}
        self.audit_trail: list[dict] = []
        self.training_requirements: dict[str, list[dict]] = {}
        self.whistleblower_cases: list[dict] = []

    def create_obligation(
        self,
        title: str,
        description: str,
        due_date: date,
        responsible_party: str,
        regulation: str,
    ) -> ComplianceObligation:
        """Create a new compliance obligation."""
        obligation_id = str(uuid4())
        obligation = ComplianceObligation(
            obligation_id=obligation_id,
            title=title,
            description=description,
            due_date=due_date,
            responsible_party=responsible_party,
            regulation=regulation,
        )

        self.obligations[obligation_id] = obligation
        self._log_audit("create_obligation", obligation_id)
        logger.info(f"Created compliance obligation {obligation_id}: {title}")
        return obligation

    def update_obligation_status(
        self,
        obligation_id: str,
        status: str,
        notes: str = "",
    ) -> ComplianceObligation:
        """Update the status of a compliance obligation."""
        if obligation_id not in self.obligations:
            raise ValueError(f"Obligation {obligation_id} not found")

        obligation = self.obligations[obligation_id]
        old_status = obligation.status
        obligation.status = status
        obligation.notes = notes

        if status == "completed":
            obligation.completed_at = datetime.now()

        self._log_audit(
            "update_obligation",
            obligation_id,
            {"old_status": old_status, "new_status": status},
        )
        logger.info(f"Updated obligation {obligation_id} to {status}")
        return obligation

    def get_overdue_obligations(self) -> list[ComplianceObligation]:
        """Get all overdue compliance obligations."""
        today = date.today()
        return [o for o in self.obligations.values() if o.due_date < today and o.status != "completed"]

    def get_upcoming_obligations(
        self,
        days: int = 30,
    ) -> list[ComplianceObligation]:
        """Get obligations due within next N days."""
        today = date.today()
        threshold = today + timedelta(days=days)

        return [o for o in self.obligations.values() if today <= o.due_date <= threshold and o.status != "completed"]

    def create_policy(
        self,
        title: str,
        content: str,
    ) -> CompliancePolicy:
        """Create a new compliance policy (starts in DRAFT)."""
        policy_id = str(uuid4())
        policy = CompliancePolicy(
            policy_id=policy_id,
            title=title,
            content=content,
        )

        self.policies[policy_id] = [policy]
        self._log_audit("create_policy", policy_id)
        logger.info(f"Created policy {policy_id}: {title}")
        return policy

    def transition_policy(
        self,
        policy_id: str,
        new_status: ComplianceStatus,
    ) -> CompliancePolicy:
        """Transition policy through lifecycle: DRAFT->REVIEW->APPROVED->PUBLISHED->RETIRED."""
        if policy_id not in self.policies:
            raise ValueError(f"Policy {policy_id} not found")

        current_policy = self.policies[policy_id][-1]
        old_status = current_policy.status

        # Create new version
        new_policy = CompliancePolicy(
            policy_id=policy_id,
            title=current_policy.title,
            content=current_policy.content,
            status=new_status,
        )
        new_policy.version = current_policy.version + 1

        if new_status == ComplianceStatus.PUBLISHED:
            new_policy.published_at = datetime.now()
        elif new_status == ComplianceStatus.RETIRED:
            new_policy.retired_at = datetime.now()

        self.policies[policy_id].append(new_policy)
        self._log_audit(
            "transition_policy",
            policy_id,
            {"old_status": old_status.value, "new_status": new_status.value},
        )

        logger.info(f"Transitioned policy {policy_id} to {new_status.value}")
        return new_policy

    def update_policy(
        self,
        policy_id: str,
        content: str,
    ) -> CompliancePolicy:
        """Update policy content (must be in DRAFT or REVIEW status)."""
        if policy_id not in self.policies:
            raise ValueError(f"Policy {policy_id} not found")

        current_policy = self.policies[policy_id][-1]

        # Create new version
        new_policy = CompliancePolicy(
            policy_id=policy_id,
            title=current_policy.title,
            content=content,
            status=current_policy.status,
        )
        new_policy.version = current_policy.version + 1

        self.policies[policy_id].append(new_policy)
        logger.info(f"Updated policy {policy_id} to version {new_policy.version}")
        return new_policy

    def get_policy(
        self,
        policy_id: str,
        version: int | None = None,
    ) -> CompliancePolicy:
        """Get a policy by ID, optionally by version."""
        if policy_id not in self.policies:
            raise ValueError(f"Policy {policy_id} not found")

        versions = self.policies[policy_id]
        if version:
            matching = [p for p in versions if p.version == version]
            if not matching:
                raise ValueError(f"Policy version {version} not found")
            return matching[0]

        return versions[-1]

    def compare_policy_versions(
        self,
        policy_id: str,
        version1: int,
        version2: int,
    ) -> list[str]:
        """Compare two versions of a policy."""
        if policy_id not in self.policies:
            raise ValueError(f"Policy {policy_id} not found")

        versions = self.policies[policy_id]
        p1 = next((p for p in versions if p.version == version1), None)
        p2 = next((p for p in versions if p.version == version2), None)

        if not p1 or not p2:
            raise ValueError("One or both versions not found")

        diff = list(
            difflib.unified_diff(
                p1.content.splitlines(keepends=True),
                p2.content.splitlines(keepends=True),
                fromfile=f"v{version1}",
                tofile=f"v{version2}",
            )
        )

        return diff

    def create_risk(
        self,
        title: str,
        description: str,
        probability: int,
        impact: int,
        area: str,
    ) -> ComplianceRisk:
        """Create a compliance risk assessment."""
        if not 1 <= probability <= 5 or not 1 <= impact <= 5:
            raise ValueError("Probability and impact must be 1-5")

        risk_id = str(uuid4())
        risk = ComplianceRisk(
            risk_id=risk_id,
            title=title,
            description=description,
            probability=probability,
            impact=impact,
            area=area,
        )

        self.risks[risk_id] = risk
        self._log_audit("create_risk", risk_id)
        logger.info(f"Created compliance risk {risk_id}: {title}")
        return risk

    def set_risk_mitigation(
        self,
        risk_id: str,
        mitigation_plan: str,
    ) -> ComplianceRisk:
        """Set mitigation plan for a risk."""
        if risk_id not in self.risks:
            raise ValueError(f"Risk {risk_id} not found")

        risk = self.risks[risk_id]
        risk.mitigation_plan = mitigation_plan
        return risk

    def get_high_risk_items(self, threshold: int = 15) -> list[ComplianceRisk]:
        """Get risks scoring above threshold (probability × impact)."""
        return [r for r in self.risks.values() if r.risk_score >= threshold and r.status == "open"]

    def add_training_requirement(
        self,
        employee_id: str,
        training_type: str,
        due_date: date,
        description: str = "",
    ) -> dict:
        """Add a training requirement for an employee."""
        requirement = {
            "requirement_id": str(uuid4()),
            "training_type": training_type,
            "due_date": due_date,
            "description": description,
            "completed": False,
            "completed_at": None,
            "created_at": datetime.now(),
        }

        if employee_id not in self.training_requirements:
            self.training_requirements[employee_id] = []

        self.training_requirements[employee_id].append(requirement)
        self._log_audit("add_training_requirement", employee_id)
        return requirement

    def complete_training(
        self,
        employee_id: str,
        requirement_id: str,
    ) -> dict:
        """Mark training requirement as completed."""
        if employee_id not in self.training_requirements:
            raise ValueError(f"Employee {employee_id} not found")

        requirements = self.training_requirements[employee_id]
        matching = [r for r in requirements if r["requirement_id"] == requirement_id]

        if not matching:
            raise ValueError(f"Requirement {requirement_id} not found")

        req = matching[0]
        req["completed"] = True
        req["completed_at"] = datetime.now()

        self._log_audit("complete_training", requirement_id)
        return req

    def get_training_status(self, employee_id: str) -> dict:
        """Get training compliance status for an employee."""
        if employee_id not in self.training_requirements:
            return {"total": 0, "completed": 0, "overdue": 0}

        reqs = self.training_requirements[employee_id]
        today = date.today()

        completed = sum(1 for r in reqs if r["completed"])
        overdue = sum(1 for r in reqs if not r["completed"] and r["due_date"] < today)

        return {
            "total": len(reqs),
            "completed": completed,
            "pending": len(reqs) - completed,
            "overdue": overdue,
        }

    def report_whistleblower_case(
        self,
        reporter_id: str,
        description: str,
        category: str,
    ) -> dict:
        """Report a potential whistleblower case."""
        case = {
            "case_id": str(uuid4()),
            "reporter_id": reporter_id,
            "description": description,
            "category": category,
            "reported_at": datetime.now(),
            "status": "open",
            "investigation_notes": "",
        }

        self.whistleblower_cases.append(case)
        self._log_audit("report_whistleblower", case["case_id"])
        logger.info(f"Reported whistleblower case {case['case_id']}")
        return case

    def get_audit_trail(
        self,
        action: str | None = None,
        entity_id: str | None = None,
    ) -> list[dict]:
        """Retrieve audit trail with optional filters."""
        trail = self.audit_trail

        if action:
            trail = [t for t in trail if t["action"] == action]
        if entity_id:
            trail = [t for t in trail if t["entity_id"] == entity_id]

        return sorted(trail, key=lambda t: t["timestamp"], reverse=True)

    def _log_audit(
        self,
        action: str,
        entity_id: str,
        details: dict | None = None,
    ) -> None:
        """Internal: log action to audit trail."""
        entry = {
            "action": action,
            "entity_id": entity_id,
            "timestamp": datetime.now(),
            "details": details or {},
        }
        self.audit_trail.append(entry)
