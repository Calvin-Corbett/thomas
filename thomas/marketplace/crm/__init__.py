"""
Thomas CRM Module

A comprehensive Customer Relationship Management system with contact management,
deal tracking, sales pipeline management, lead scoring, and automation capabilities.
"""

from thomas.marketplace.crm._exceptions import (
    CompanyNotFoundError,
    ContactNotFoundError,
    CRMException,
    DealNotFoundError,
    DuplicateContactError,
    InvalidStageError,
    PipelineNotFoundError,
)
from thomas.marketplace.crm._types import (
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
from thomas.marketplace.crm.activities import ActivityManager
from thomas.marketplace.crm.automation import WorkflowEngine
from thomas.marketplace.crm.companies import CompanyManager
from thomas.marketplace.crm.contacts import ContactManager
from thomas.marketplace.crm.deals import DealManager
from thomas.marketplace.crm.integration import IntegrationManager
from thomas.marketplace.crm.pipeline import PipelineManager
from thomas.marketplace.crm.reporting import ReportingEngine
from thomas.marketplace.crm.scoring import ScoringEngine

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
