"""Tools for CRM system - exposes contact, deal, pipeline, and activity management."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from thomas.tools.base import Tool, ToolResult


class CRMCreateContactTool(Tool):
    """Create a new contact in the CRM."""

    name = "crm.create_contact"
    category = "crm"
    description = "Create a new contact with contact information including name, email, phone, company, and optional custom fields"
    parameters = {
        "type": "object",
        "properties": {
            "first_name": {"type": "string", "description": "Contact's first name"},
            "last_name": {"type": "string", "description": "Contact's last name"},
            "email": {"type": "string", "description": "Contact email address"},
            "phone": {"type": "string", "description": "Contact phone number (optional)"},
            "company": {"type": "string", "description": "Company name (optional)"},
            "title": {"type": "string", "description": "Job title (optional)"},
            "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags for categorizing contacts"},
        },
        "required": ["first_name", "last_name", "email"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        from thomas.crm.contacts import ContactManager

        manager = ContactManager()
        try:
            contact = manager.create_contact(
                first_name=args["first_name"],
                last_name=args["last_name"],
                email=args["email"],
                phone=args.get("phone"),
                company=args.get("company"),
                title=args.get("title"),
                tags=args.get("tags", []),
            )
            return ToolResult(
                ok=True,
                data={
                    "id": contact.id,
                    "first_name": contact.first_name,
                    "last_name": contact.last_name,
                    "email": contact.email,
                    "company": contact.company,
                    "title": contact.title,
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class CRMListContactsTool(Tool):
    """List all contacts in the CRM."""

    name = "crm.list_contacts"
    category = "crm"
    description = "Retrieve a list of all contacts in the CRM system"
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        from thomas.crm.contacts import ContactManager

        manager = ContactManager()
        try:
            contacts = manager.list_contacts()
            return ToolResult(
                ok=True,
                data=[
                    {
                        "id": c.id,
                        "name": f"{c.first_name} {c.last_name}",
                        "email": c.email,
                        "company": c.company,
                        "title": c.title,
                    }
                    for c in contacts
                ],
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class CRMSearchContactsTool(Tool):
    """Search for contacts by name, email, or company."""

    name = "crm.search_contacts"
    category = "crm"
    description = "Search for contacts using name, email, or company name"
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query (name, email, or company)"},
            "search_type": {"type": "string", "enum": ["name", "email", "company"], "description": "Type of search"},
        },
        "required": ["query", "search_type"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        from thomas.crm.contacts import ContactManager

        manager = ContactManager()
        try:
            results = manager.search_contacts(query=args["query"], search_type=args["search_type"])
            return ToolResult(
                ok=True,
                data=[
                    {
                        "id": c.id,
                        "name": f"{c.first_name} {c.last_name}",
                        "email": c.email,
                        "company": c.company,
                    }
                    for c in results
                ],
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class CRMCreateDealTool(Tool):
    """Create a new deal in the sales pipeline."""

    name = "crm.create_deal"
    category = "crm"
    description = "Create a new deal in the sales pipeline with deal name, value, probability, and expected close date"
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Deal name"},
            "company_id": {"type": "string", "description": "Associated company ID"},
            "contact_id": {"type": "string", "description": "Primary contact ID"},
            "stage_id": {"type": "string", "description": "Pipeline stage ID"},
            "value": {"type": "number", "description": "Deal value in currency"},
            "probability": {"type": "integer", "minimum": 0, "maximum": 100, "description": "Win probability (0-100)"},
            "expected_close": {"type": "string", "description": "Expected close date (YYYY-MM-DD)"},
            "owner": {"type": "string", "description": "Sales rep or deal owner"},
        },
        "required": ["name", "company_id", "contact_id", "stage_id", "value", "probability", "expected_close", "owner"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        from thomas.crm.deals import DealManager

        manager = DealManager()
        try:
            expected_close = datetime.fromisoformat(args["expected_close"])
            deal = manager.create_deal(
                name=args["name"],
                company_id=args["company_id"],
                contact_id=args["contact_id"],
                stage_id=args["stage_id"],
                value=Decimal(str(args["value"])),
                probability=args["probability"],
                expected_close=expected_close,
                owner=args["owner"],
            )
            return ToolResult(
                ok=True,
                data={
                    "id": deal.id,
                    "name": deal.name,
                    "value": str(deal.value),
                    "probability": deal.probability,
                    "stage_id": deal.stage_id,
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class CRMListDealsTool(Tool):
    """List all deals in the pipeline."""

    name = "crm.list_deals"
    category = "crm"
    description = "Retrieve all deals in the sales pipeline"
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        from thomas.crm.deals import DealManager

        manager = DealManager()
        try:
            deals = manager.list_deals()
            return ToolResult(
                ok=True,
                data=[
                    {
                        "id": d.id,
                        "name": d.name,
                        "value": str(d.value),
                        "probability": d.probability,
                        "stage_id": d.stage_id,
                        "owner": d.owner,
                    }
                    for d in deals
                ],
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class CRMSearchDealsTool(Tool):
    """Search for deals by name, owner, or company."""

    name = "crm.search_deals"
    category = "crm"
    description = "Search for deals using name, owner, or company"
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "search_type": {"type": "string", "enum": ["name", "owner", "company_id"], "description": "Type of search"},
        },
        "required": ["query", "search_type"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        from thomas.crm.deals import DealManager

        manager = DealManager()
        try:
            results = manager.search_deals(query=args["query"], search_type=args["search_type"])
            return ToolResult(
                ok=True,
                data=[
                    {
                        "id": d.id,
                        "name": d.name,
                        "value": str(d.value),
                        "owner": d.owner,
                    }
                    for d in results
                ],
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class CRMCalculateDealScoreTool(Tool):
    """Calculate a deal's score based on various factors."""

    name = "crm.calculate_deal_score"
    category = "crm"
    description = "Calculate a deal's score based on probability, value, and other factors"
    parameters = {
        "type": "object",
        "properties": {
            "deal_id": {"type": "string", "description": "Deal ID"},
            "value_weight": {"type": "number", "description": "Weight for deal value (0-1)"},
            "prob_weight": {"type": "number", "description": "Weight for probability (0-1)"},
            "age_weight": {"type": "number", "description": "Weight for deal age (0-1)"},
        },
        "required": ["deal_id"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        from thomas.crm.deals import DealManager

        manager = DealManager()
        try:
            score = manager.calculate_deal_score(
                deal_id=args["deal_id"],
                value_weight=args.get("value_weight", 0.4),
                prob_weight=args.get("prob_weight", 0.4),
                age_weight=args.get("age_weight", 0.2),
            )
            return ToolResult(ok=True, data={"deal_id": args["deal_id"], "score": score})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class CRMGetActivityHistoryTool(Tool):
    """Get activity history for a contact."""

    name = "crm.get_activity_history"
    category = "crm"
    description = "Retrieve activity history for a contact including calls, emails, meetings"
    parameters = {
        "type": "object",
        "properties": {
            "contact_id": {"type": "string", "description": "Contact ID"},
        },
        "required": ["contact_id"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        from thomas.crm.contacts import ContactManager

        manager = ContactManager()
        try:
            history = manager.get_activity_history(args["contact_id"])
            return ToolResult(ok=True, data=history)
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_crm_tools(registry, sandbox=None):
    """Register all CRM tools."""
    registry.register(CRMCreateContactTool())
    registry.register(CRMListContactsTool())
    registry.register(CRMSearchContactsTool())
    registry.register(CRMCreateDealTool())
    registry.register(CRMListDealsTool())
    registry.register(CRMSearchDealsTool())
    registry.register(CRMCalculateDealScoreTool())
    registry.register(CRMGetActivityHistoryTool())
