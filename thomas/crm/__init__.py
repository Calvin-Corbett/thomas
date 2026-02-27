"""
Thomas CRM Module

A comprehensive Customer Relationship Management system with contact management,
deal tracking, sales pipeline management, lead scoring, and automation capabilities.
"""

from thomas.crm._exceptions import (
    CompanyNotFoundError,
    ContactNotFoundError,
    CRMException,
    DealNotFoundError,
    DuplicateContactError,
    InvalidStageError,
    PipelineNotFoundError,
)
from thomas.crm._types import (
    Activity,
    ActivityType,
    Company,
    Contact,
    Deal,
    DealForecast,
    LeadScore,
    Pipeline,
    Stage,
)
from thomas.crm.activities import ActivityManager
from thomas.crm.automation import WorkflowEngine
from thomas.crm.companies import CompanyManager
from thomas.crm.contacts import ContactManager
from thomas.crm.deals import DealManager
from thomas.crm.integration import IntegrationManager
from thomas.crm.pipeline import PipelineManager
from thomas.crm.reporting import ReportingEngine
from thomas.crm.scoring import ScoringEngine

__version__ = "1.0.0"
__all__ = [
    # Types
    "Contact",
    "Company",
    "Deal",
    "Activity",
    "Pipeline",
    "Stage",
    "LeadScore",
    "DealForecast",
    "ActivityType",
    # Exceptions
    "CRMException",
    "ContactNotFoundError",
    "CompanyNotFoundError",
    "DealNotFoundError",
    "PipelineNotFoundError",
    "InvalidStageError",
    "DuplicateContactError",
    # Managers
    "ContactManager",
    "CompanyManager",
    "PipelineManager",
    "DealManager",
    "ActivityManager",
    "ScoringEngine",
    "ReportingEngine",
    "WorkflowEngine",
    "IntegrationManager",
]
