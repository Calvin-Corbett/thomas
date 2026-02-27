"""Project Management Module.

A comprehensive project management and planning platform with support for
traditional waterfall, agile/scrum, and hybrid methodologies.
"""

from thomas.project_mgmt._types import (
    Budget,
    Bug,
    Dependency,
    DependencyType,
    Epic,
    GanttBar,
    Milestone,
    Priority,
    Project,
    ProjectStatus,
    Resource,
    ResourceStatus,
    RiskCategory,
    RiskItem,
    RiskStatus,
    Sprint,
    SprintStatus,
    Stakeholder,
    StatusReport,
    Story,
    Task,
    TaskStatus,
    TimeEntry,
    WorkBreakdownItem,
)
from thomas.project_mgmt.agile import AgileManager
from thomas.project_mgmt.budget import BudgetManager
from thomas.project_mgmt.collaboration import CollaborationManager
from thomas.project_mgmt.projects import ProjectManager
from thomas.project_mgmt.reporting import ReportingManager
from thomas.project_mgmt.resources import ResourceManager
from thomas.project_mgmt.risks import RiskManager
from thomas.project_mgmt.scheduling import ScheduleManager
from thomas.project_mgmt.tasks import TaskManager

__all__ = [
    "Project",
    "Task",
    "Milestone",
    "Sprint",
    "Epic",
    "Story",
    "Bug",
    "Resource",
    "TimeEntry",
    "Dependency",
    "GanttBar",
    "RiskItem",
    "Stakeholder",
    "Budget",
    "StatusReport",
    "WorkBreakdownItem",
    "ProjectStatus",
    "TaskStatus",
    "SprintStatus",
    "Priority",
    "DependencyType",
    "ResourceStatus",
    "RiskStatus",
    "RiskCategory",
    "ProjectManager",
    "TaskManager",
    "ScheduleManager",
    "AgileManager",
    "ResourceManager",
    "BudgetManager",
    "RiskManager",
    "ReportingManager",
    "CollaborationManager",
]
