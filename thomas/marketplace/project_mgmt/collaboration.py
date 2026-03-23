"""Collaboration and communication management for projects.

Implements comment threads, activity feeds, document management,
meeting management, decision logs, and change requests.
"""

import uuid
from datetime import datetime


class Comment:
    """Comment on task or project."""

    def __init__(
        self,
        id: str,
        author_id: str,
        content: str,
        parent_id: str | None = None,
    ) -> None:
        """Initialize comment.

        Args:
            id: Comment identifier.
            author_id: Author resource identifier.
            content: Comment text content.
            parent_id: Parent comment ID (for threading).
        """
        self.id = id
        self.author_id = author_id
        self.content = content
        self.parent_id = parent_id
        self.created_at = datetime.now()
        self.mentions: set[str] = set()  # @mentioned resource IDs

    def extract_mentions(self) -> set[str]:
        """Extract @mentions from comment content.

        Returns:
            Set of mentioned resource IDs.
        """
        mentions: set[str] = set()
        words = self.content.split()
        for word in words:
            if word.startswith("@"):
                # Simple extraction: remove @ and punctuation
                mention = word[1:].rstrip(".,!?")
                if mention:
                    mentions.add(mention)
        return mentions


class ActivityLog:
    """Activity log entry."""

    def __init__(
        self,
        id: str,
        resource_id: str,
        action: str,
        entity_id: str,
        entity_type: str,
        details: dict[str, str] | None = None,
    ) -> None:
        """Initialize activity log entry.

        Args:
            id: Activity identifier.
            resource_id: User who performed action.
            action: Action type (created, updated, deleted, etc).
            entity_id: Entity affected.
            entity_type: Entity type (task, project, etc).
            details: Additional details.
        """
        self.id = id
        self.resource_id = resource_id
        self.action = action
        self.entity_id = entity_id
        self.entity_type = entity_type
        self.details = details or {}
        self.created_at = datetime.now()


class MeetingNote:
    """Meeting agenda and minutes."""

    def __init__(
        self,
        id: str,
        title: str,
        project_id: str,
        scheduled_date: datetime,
    ) -> None:
        """Initialize meeting note.

        Args:
            id: Meeting identifier.
            title: Meeting title.
            project_id: Associated project.
            scheduled_date: Scheduled meeting date/time.
        """
        self.id = id
        self.title = title
        self.project_id = project_id
        self.scheduled_date = scheduled_date
        self.agenda_items: list[str] = []
        self.attendees: set[str] = set()
        self.minutes: str = ""
        self.action_items: list[dict[str, str]] = []
        self.decisions: list[str] = []


class Decision:
    """Decision log entry."""

    def __init__(
        self,
        id: str,
        title: str,
        description: str,
        project_id: str,
        made_by: str,
    ) -> None:
        """Initialize decision.

        Args:
            id: Decision identifier.
            title: Decision title.
            description: Decision description and rationale.
            project_id: Associated project.
            made_by: Decision maker resource ID.
        """
        self.id = id
        self.title = title
        self.description = description
        self.project_id = project_id
        self.made_by = made_by
        self.made_date = datetime.now()
        self.rationale: str = ""
        self.alternatives: list[str] = []
        self.impact: str = ""


class ChangeRequest:
    """Change request for scope management."""

    def __init__(
        self,
        id: str,
        title: str,
        description: str,
        project_id: str,
        submitted_by: str,
    ) -> None:
        """Initialize change request.

        Args:
            id: Change request identifier.
            title: Change title.
            description: Change description.
            project_id: Associated project.
            submitted_by: Submitter resource ID.
        """
        self.id = id
        self.title = title
        self.description = description
        self.project_id = project_id
        self.submitted_by = submitted_by
        self.status = "submitted"  # submitted, under_review, approved, rejected, implemented
        self.submitted_date = datetime.now()
        self.reviewed_date: datetime | None = None
        self.reviewed_by: str | None = None
        self.impact_assessment: str = ""
        self.implementation_plan: str = ""


class CollaborationManager:
    """Manages project collaboration and communication.

    Handles comments, activity tracking, meetings, decisions,
    and change requests.
    """

    def __init__(self) -> None:
        """Initialize collaboration manager."""
        self.comments: dict[str, list[Comment]] = {}  # entity_id -> comments
        self.activity_log: dict[str, list[ActivityLog]] = {}  # entity_id -> activities
        self.meetings: dict[str, MeetingNote] = {}
        self.decisions: dict[str, Decision] = {}
        self.change_requests: dict[str, ChangeRequest] = {}
        self.documents: dict[str, dict[str, str]] = {}  # entity_id -> {filename -> path}

    def add_comment(
        self,
        entity_id: str,
        author_id: str,
        content: str,
        parent_comment_id: str | None = None,
    ) -> Comment:
        """Add comment to task/project.

        Args:
            entity_id: Task or project identifier.
            author_id: Comment author resource ID.
            content: Comment text.
            parent_comment_id: Parent comment for threading.

        Returns:
            Created Comment instance.
        """
        comment_id = str(uuid.uuid4())
        comment = Comment(
            id=comment_id,
            author_id=author_id,
            content=content,
            parent_id=parent_comment_id,
        )
        comment.mentions = comment.extract_mentions()

        if entity_id not in self.comments:
            self.comments[entity_id] = []

        self.comments[entity_id].append(comment)
        return comment

    def get_comments(
        self,
        entity_id: str,
    ) -> list[Comment]:
        """Get comments for entity.

        Args:
            entity_id: Task or project identifier.

        Returns:
            List of Comment instances.
        """
        return self.comments.get(entity_id, [])

    def log_activity(
        self,
        resource_id: str,
        action: str,
        entity_id: str,
        entity_type: str,
        details: dict[str, str] | None = None,
    ) -> ActivityLog:
        """Log activity for audit trail.

        Args:
            resource_id: User performing action.
            action: Action type.
            entity_id: Entity affected.
            entity_type: Entity type.
            details: Additional details.

        Returns:
            Created ActivityLog instance.
        """
        activity_id = str(uuid.uuid4())
        activity = ActivityLog(
            id=activity_id,
            resource_id=resource_id,
            action=action,
            entity_id=entity_id,
            entity_type=entity_type,
            details=details,
        )

        if entity_id not in self.activity_log:
            self.activity_log[entity_id] = []

        self.activity_log[entity_id].append(activity)
        return activity

    def get_activity_feed(
        self,
        entity_id: str,
        limit: int = 50,
    ) -> list[ActivityLog]:
        """Get activity feed for entity.

        Args:
            entity_id: Entity identifier.
            limit: Maximum entries to return.

        Returns:
            List of recent ActivityLog entries.
        """
        activities = self.activity_log.get(entity_id, [])
        return sorted(
            activities,
            key=lambda a: a.created_at,
            reverse=True,
        )[:limit]

    def create_meeting(
        self,
        title: str,
        project_id: str,
        scheduled_date: datetime,
    ) -> MeetingNote:
        """Create meeting and agenda.

        Args:
            title: Meeting title.
            project_id: Associated project.
            scheduled_date: Scheduled date/time.

        Returns:
            Created MeetingNote instance.
        """
        meeting_id = str(uuid.uuid4())
        meeting = MeetingNote(
            id=meeting_id,
            title=title,
            project_id=project_id,
            scheduled_date=scheduled_date,
        )
        self.meetings[meeting_id] = meeting
        return meeting

    def get_meeting(self, meeting_id: str) -> MeetingNote | None:
        """Retrieve meeting by ID.

        Args:
            meeting_id: Meeting identifier.

        Returns:
            MeetingNote instance or None.
        """
        return self.meetings.get(meeting_id)

    def add_agenda_item(
        self,
        meeting_id: str,
        item: str,
    ) -> MeetingNote:
        """Add agenda item to meeting.

        Args:
            meeting_id: Meeting identifier.
            item: Agenda item text.

        Returns:
            Updated MeetingNote instance.
        """
        meeting = self.get_meeting(meeting_id)
        if meeting:
            meeting.agenda_items.append(item)
        return meeting

    def record_minutes(
        self,
        meeting_id: str,
        minutes: str,
    ) -> MeetingNote:
        """Record meeting minutes.

        Args:
            meeting_id: Meeting identifier.
            minutes: Meeting minutes text.

        Returns:
            Updated MeetingNote instance.
        """
        meeting = self.get_meeting(meeting_id)
        if meeting:
            meeting.minutes = minutes
        return meeting

    def add_action_item(
        self,
        meeting_id: str,
        description: str,
        owner_id: str,
        due_date: datetime | None = None,
    ) -> MeetingNote:
        """Add action item from meeting.

        Args:
            meeting_id: Meeting identifier.
            description: Action item description.
            owner_id: Responsible resource ID.
            due_date: Due date for action.

        Returns:
            Updated MeetingNote instance.
        """
        meeting = self.get_meeting(meeting_id)
        if meeting:
            meeting.action_items.append(
                {
                    "id": str(uuid.uuid4()),
                    "description": description,
                    "owner": owner_id,
                    "due_date": due_date.isoformat() if due_date else "",
                    "status": "open",
                }
            )
        return meeting

    def record_decision(
        self,
        title: str,
        description: str,
        project_id: str,
        made_by: str,
        rationale: str = "",
        alternatives: list[str] | None = None,
    ) -> Decision:
        """Record project decision.

        Args:
            title: Decision title.
            description: Decision description.
            project_id: Associated project.
            made_by: Decision maker ID.
            rationale: Decision rationale.
            alternatives: Alternative options considered.

        Returns:
            Created Decision instance.
        """
        decision_id = str(uuid.uuid4())
        decision = Decision(
            id=decision_id,
            title=title,
            description=description,
            project_id=project_id,
            made_by=made_by,
        )
        decision.rationale = rationale
        decision.alternatives = alternatives or []
        self.decisions[decision_id] = decision
        return decision

    def get_decisions(
        self,
        project_id: str,
    ) -> list[Decision]:
        """Get decisions for project.

        Args:
            project_id: Project identifier.

        Returns:
            List of Decision instances.
        """
        return [d for d in self.decisions.values() if d.project_id == project_id]

    def submit_change_request(
        self,
        title: str,
        description: str,
        project_id: str,
        submitted_by: str,
    ) -> ChangeRequest:
        """Submit change request.

        Args:
            title: Change title.
            description: Change description.
            project_id: Associated project.
            submitted_by: Submitter ID.

        Returns:
            Created ChangeRequest instance.
        """
        cr_id = str(uuid.uuid4())
        cr = ChangeRequest(
            id=cr_id,
            title=title,
            description=description,
            project_id=project_id,
            submitted_by=submitted_by,
        )
        self.change_requests[cr_id] = cr
        return cr

    def review_change_request(
        self,
        cr_id: str,
        reviewed_by: str,
        impact_assessment: str,
    ) -> ChangeRequest:
        """Review change request.

        Args:
            cr_id: Change request ID.
            reviewed_by: Reviewer ID.
            impact_assessment: Assessment of change impact.

        Returns:
            Updated ChangeRequest instance.
        """
        cr = self.change_requests.get(cr_id)
        if cr:
            cr.reviewed_by = reviewed_by
            cr.reviewed_date = datetime.now()
            cr.impact_assessment = impact_assessment
            cr.status = "under_review"
        return cr

    def approve_change_request(
        self,
        cr_id: str,
        implementation_plan: str,
    ) -> ChangeRequest:
        """Approve change request.

        Args:
            cr_id: Change request ID.
            implementation_plan: Plan for implementation.

        Returns:
            Updated ChangeRequest instance.
        """
        cr = self.change_requests.get(cr_id)
        if cr:
            cr.status = "approved"
            cr.implementation_plan = implementation_plan
        return cr

    def reject_change_request(self, cr_id: str) -> ChangeRequest:
        """Reject change request.

        Args:
            cr_id: Change request ID.

        Returns:
            Updated ChangeRequest instance.
        """
        cr = self.change_requests.get(cr_id)
        if cr:
            cr.status = "rejected"
        return cr

    def implement_change_request(
        self,
        cr_id: str,
    ) -> ChangeRequest:
        """Mark change request as implemented.

        Args:
            cr_id: Change request ID.

        Returns:
            Updated ChangeRequest instance.
        """
        cr = self.change_requests.get(cr_id)
        if cr:
            cr.status = "implemented"
        return cr

    def attach_document(
        self,
        entity_id: str,
        filename: str,
        file_path: str,
    ) -> None:
        """Attach document to task/project.

        Args:
            entity_id: Entity identifier.
            filename: Document filename.
            file_path: Path to document file.
        """
        if entity_id not in self.documents:
            self.documents[entity_id] = {}
        self.documents[entity_id][filename] = file_path

    def get_documents(self, entity_id: str) -> dict[str, str]:
        """Get attached documents.

        Args:
            entity_id: Entity identifier.

        Returns:
            Dictionary mapping filename to file path.
        """
        return self.documents.get(entity_id, {})

    def get_change_requests(
        self,
        project_id: str,
        status: str | None = None,
    ) -> list[ChangeRequest]:
        """Get change requests for project.

        Args:
            project_id: Project identifier.
            status: Filter by status.

        Returns:
            List of ChangeRequest instances.
        """
        crs = [cr for cr in self.change_requests.values() if cr.project_id == project_id]
        if status:
            crs = [cr for cr in crs if cr.status == status]
        return crs
