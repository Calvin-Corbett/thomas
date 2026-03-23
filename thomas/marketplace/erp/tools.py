"""Tools for ERP system - exposes accounting, inventory, purchasing, and sales management."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from thomas.tools.base import Tool, ToolResult


class ERPCreateAccountTool(Tool):
    """Create a new general ledger account."""

    name = "erp.create_account"
    category = "erp"
    description = "Create a new general ledger account with account type, number, and name"
    parameters = {
        "type": "object",
        "properties": {
            "account_number": {"type": "string", "description": "Account number"},
            "account_name": {"type": "string", "description": "Account name"},
            "account_type": {
                "type": "string",
                "enum": ["asset", "liability", "equity", "revenue", "expense", "other"],
                "description": "Account type",
            },
            "currency": {"type": "string", "description": "Currency code (e.g., USD)"},
            "parent_id": {"type": "string", "description": "Parent account ID (optional)"},
        },
        "required": ["account_number", "account_name", "account_type", "currency"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        from thomas.marketplace.erp._types import AccountType, Currency
        from thomas.marketplace.erp.general_ledger import GeneralLedger

        gl = GeneralLedger()
        try:
            account = gl.create_account(
                account_number=args["account_number"],
                account_name=args["account_name"],
                account_type=AccountType[args["account_type"].upper()],
                currency=Currency[args["currency"].upper()],
                parent_id=args.get("parent_id"),
            )
            return ToolResult(
                ok=True,
                data={
                    "id": account.id,
                    "number": account.account_number,
                    "name": account.account_name,
                    "type": account.account_type.name,
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class ERPGetTrialBalanceTool(Tool):
    """Get the trial balance for a specific date."""

    name = "erp.get_trial_balance"
    category = "erp"
    description = "Retrieve the trial balance showing all account balances as of a specific date"
    parameters = {
        "type": "object",
        "properties": {
            "as_of_date": {"type": "string", "description": "Balance date (YYYY-MM-DD, optional)"},
        },
        "required": [],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        from thomas.marketplace.erp.general_ledger import GeneralLedger

        gl = GeneralLedger()
        try:
            as_of = None
            if args.get("as_of_date"):
                as_of = datetime.fromisoformat(args["as_of_date"]).date()
            balances = gl.trial_balance(as_of)
            return ToolResult(
                ok=True, data={"date": str(as_of or date.today()), "balances": {k: str(v) for k, v in balances.items()}}
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class ERPGetAccountBalanceTool(Tool):
    """Get the balance of a specific account."""

    name = "erp.get_account_balance"
    category = "erp"
    description = "Retrieve the balance of a specific general ledger account"
    parameters = {
        "type": "object",
        "properties": {
            "account_id": {"type": "string", "description": "Account ID"},
            "as_of_date": {"type": "string", "description": "Balance date (YYYY-MM-DD, optional)"},
        },
        "required": ["account_id"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        from thomas.marketplace.erp.general_ledger import GeneralLedger

        gl = GeneralLedger()
        try:
            as_of = None
            if args.get("as_of_date"):
                as_of = datetime.fromisoformat(args["as_of_date"]).date()
            balance = gl.get_account_balance(args["account_id"], as_of)
            return ToolResult(
                ok=True,
                data={
                    "account_id": args["account_id"],
                    "balance": str(balance),
                    "as_of_date": str(as_of or date.today()),
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class ERPCreateInventoryItemTool(Tool):
    """Create a new inventory item."""

    name = "erp.create_inventory_item"
    category = "erp"
    description = "Create a new inventory item with SKU, description, and quantity"
    parameters = {
        "type": "object",
        "properties": {
            "sku": {"type": "string", "description": "Stock keeping unit"},
            "description": {"type": "string", "description": "Item description"},
            "unit_of_measure": {"type": "string", "description": "Unit of measure (e.g., EA, KG)"},
            "quantity_on_hand": {"type": "number", "description": "Current quantity in stock"},
            "unit_cost": {"type": "number", "description": "Cost per unit"},
        },
        "required": ["sku", "description", "unit_of_measure", "quantity_on_hand", "unit_cost"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        from thomas.marketplace.erp._types import UnitOfMeasure
        from thomas.marketplace.erp.inventory import InventoryManager

        inv = InventoryManager()
        try:
            item = inv.create_item(
                sku=args["sku"],
                description=args["description"],
                unit_of_measure=UnitOfMeasure[args["unit_of_measure"].upper()],
                quantity_on_hand=Decimal(str(args["quantity_on_hand"])),
                unit_cost=Decimal(str(args["unit_cost"])),
            )
            return ToolResult(
                ok=True,
                data={
                    "id": item.id,
                    "sku": item.sku,
                    "description": item.description,
                    "quantity": str(item.quantity_on_hand),
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class ERPGetInventoryTool(Tool):
    """Get inventory item details."""

    name = "erp.get_inventory"
    category = "erp"
    description = "Retrieve details of an inventory item including quantity and cost"
    parameters = {
        "type": "object",
        "properties": {
            "item_id": {"type": "string", "description": "Inventory item ID"},
        },
        "required": ["item_id"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        from thomas.marketplace.erp.inventory import InventoryManager

        inv = InventoryManager()
        try:
            item = inv.get_item(args["item_id"])
            return ToolResult(
                ok=True,
                data={
                    "id": item.id,
                    "sku": item.sku,
                    "description": item.description,
                    "quantity": str(item.quantity_on_hand),
                    "unit_cost": str(item.unit_cost),
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class ERPCreatePurchaseOrderTool(Tool):
    """Create a new purchase order."""

    name = "erp.create_purchase_order"
    category = "erp"
    description = "Create a new purchase order with vendor, items, and delivery date"
    parameters = {
        "type": "object",
        "properties": {
            "vendor_id": {"type": "string", "description": "Vendor ID"},
            "order_date": {"type": "string", "description": "Order date (YYYY-MM-DD)"},
            "expected_delivery": {"type": "string", "description": "Expected delivery date (YYYY-MM-DD)"},
            "line_items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "item_id": {"type": "string"},
                        "quantity": {"type": "number"},
                        "unit_price": {"type": "number"},
                    },
                },
                "description": "List of line items",
            },
        },
        "required": ["vendor_id", "order_date", "expected_delivery", "line_items"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        from thomas.marketplace.erp.purchasing import PurchasingManager

        pm = PurchasingManager()
        try:
            order_date = datetime.fromisoformat(args["order_date"]).date()
            delivery_date = datetime.fromisoformat(args["expected_delivery"]).date()
            line_items = [
                {
                    "item_id": item["item_id"],
                    "quantity": Decimal(str(item["quantity"])),
                    "unit_price": Decimal(str(item["unit_price"])),
                }
                for item in args["line_items"]
            ]
            po = pm.create_purchase_order(
                vendor_id=args["vendor_id"],
                order_date=order_date,
                expected_delivery=delivery_date,
                line_items=line_items,
            )
            return ToolResult(
                ok=True,
                data={
                    "id": po.id,
                    "vendor_id": po.vendor_id,
                    "order_date": str(po.order_date),
                    "status": po.status.name if hasattr(po.status, "name") else str(po.status),
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class ERPCreateSalesOrderTool(Tool):
    """Create a new sales order."""

    name = "erp.create_sales_order"
    category = "erp"
    description = "Create a new sales order with customer, items, and delivery date"
    parameters = {
        "type": "object",
        "properties": {
            "customer_id": {"type": "string", "description": "Customer ID"},
            "order_date": {"type": "string", "description": "Order date (YYYY-MM-DD)"},
            "expected_delivery": {"type": "string", "description": "Expected delivery date (YYYY-MM-DD)"},
            "line_items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "item_id": {"type": "string"},
                        "quantity": {"type": "number"},
                        "unit_price": {"type": "number"},
                    },
                },
                "description": "List of line items",
            },
        },
        "required": ["customer_id", "order_date", "expected_delivery", "line_items"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        from thomas.marketplace.erp.sales import SalesManager

        sm = SalesManager()
        try:
            order_date = datetime.fromisoformat(args["order_date"]).date()
            delivery_date = datetime.fromisoformat(args["expected_delivery"]).date()
            line_items = [
                {
                    "item_id": item["item_id"],
                    "quantity": Decimal(str(item["quantity"])),
                    "unit_price": Decimal(str(item["unit_price"])),
                }
                for item in args["line_items"]
            ]
            so = sm.create_sales_order(
                customer_id=args["customer_id"],
                order_date=order_date,
                expected_delivery=delivery_date,
                line_items=line_items,
            )
            return ToolResult(
                ok=True,
                data={
                    "id": so.id,
                    "customer_id": so.customer_id,
                    "order_date": str(so.order_date),
                    "status": so.status.name if hasattr(so.status, "name") else str(so.status),
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_erp_tools(registry, sandbox=None):
    """Register all ERP tools."""
    registry.register(ERPCreateAccountTool())
    registry.register(ERPGetTrialBalanceTool())
    registry.register(ERPGetAccountBalanceTool())
    registry.register(ERPCreateInventoryItemTool())
    registry.register(ERPGetInventoryTool())
    registry.register(ERPCreatePurchaseOrderTool())
    registry.register(ERPCreateSalesOrderTool())
