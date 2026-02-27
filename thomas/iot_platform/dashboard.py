"""
IoT dashboard data and widget management.

Provides dashboard definitions, widget management, real-time data
binding, templates, and configuration export.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from thomas.iot_platform._exceptions import IoTException


class DashboardManager:
    """
    Manages IoT dashboards and widgets.

    Provides widget definitions, layouts, real-time binding,
    templates, and configuration export.
    """

    def __init__(self) -> None:
        """Initialize the dashboard manager."""
        self._dashboards: dict[str, dict[str, Any]] = {}
        self._widgets: dict[str, dict[str, Any]] = {}
        self._templates: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    def create_dashboard(
        self,
        name: str,
        description: str,
        width_cols: int = 12,
    ) -> dict[str, Any]:
        """
        Create a new dashboard.

        Args:
            name: Dashboard name.
            description: Dashboard description.
            width_cols: Grid width in columns.

        Returns:
            Dashboard configuration.

        Raises:
            IoTException: If name is empty.
        """
        if not name or len(name.strip()) == 0:
            raise IoTException("Dashboard name cannot be empty")

        with self._lock:
            dashboard_id = str(uuid4())

            dashboard = {
                "dashboard_id": dashboard_id,
                "name": name,
                "description": description,
                "width_cols": width_cols,
                "widgets": [],
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
                "refresh_interval_seconds": 5,
            }

            self._dashboards[dashboard_id] = dashboard
            return dashboard

    def get_dashboard(self, dashboard_id: str) -> dict[str, Any] | None:
        """
        Get dashboard configuration.

        Args:
            dashboard_id: ID of dashboard.

        Returns:
            Dashboard data or None if not found.
        """
        with self._lock:
            return self._dashboards.get(dashboard_id)

    def add_widget(
        self,
        dashboard_id: str,
        widget_type: str,
        title: str,
        config: dict[str, Any],
        row: int = 0,
        col: int = 0,
        width: int = 4,
        height: int = 2,
    ) -> dict[str, Any]:
        """
        Add widget to dashboard.

        Widget types: gauge, chart, map, table, alert_list, kpi.

        Args:
            dashboard_id: Target dashboard ID.
            widget_type: Type of widget.
            title: Widget title.
            config: Widget configuration.
            row: Grid row position.
            col: Grid column position.
            width: Widget width in columns.
            height: Widget height in rows.

        Returns:
            Created widget data.

        Raises:
            IoTException: If dashboard not found or invalid type.
        """
        with self._lock:
            if dashboard_id not in self._dashboards:
                raise IoTException(f"Dashboard {dashboard_id} not found")

            if widget_type not in ("gauge", "chart", "map", "table", "alert_list", "kpi"):
                raise IoTException(f"Invalid widget type: {widget_type}")

            widget_id = str(uuid4())

            widget = {
                "widget_id": widget_id,
                "type": widget_type,
                "title": title,
                "config": config,
                "position": {
                    "row": row,
                    "col": col,
                    "width": width,
                    "height": height,
                },
                "created_at": datetime.utcnow().isoformat(),
                "data_source": None,
                "refresh_interval_seconds": 5,
            }

            self._widgets[widget_id] = widget
            self._dashboards[dashboard_id]["widgets"].append(widget_id)

            return widget

    def update_widget_config(
        self,
        widget_id: str,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Update widget configuration.

        Args:
            widget_id: Widget ID.
            config: New configuration.

        Returns:
            Updated widget data.

        Raises:
            IoTException: If widget not found.
        """
        with self._lock:
            if widget_id not in self._widgets:
                raise IoTException(f"Widget {widget_id} not found")

            widget = self._widgets[widget_id]
            widget["config"].update(config)

            return widget

    def bind_data_source(
        self,
        widget_id: str,
        data_source: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Bind data source to widget for real-time updates.

        Data source format:
        {
            "type": "telemetry|device_status|rule_alerts",
            "device_id": UUID,
            "metric": str,
            "group_id": str,
        }

        Args:
            widget_id: Target widget ID.
            data_source: Data source specification.

        Returns:
            Updated widget data.

        Raises:
            IoTException: If widget not found.
        """
        with self._lock:
            if widget_id not in self._widgets:
                raise IoTException(f"Widget {widget_id} not found")

            widget = self._widgets[widget_id]
            widget["data_source"] = data_source

            return widget

    def create_gauge_widget(
        self,
        dashboard_id: str,
        title: str,
        device_id: UUID,
        metric: str,
        min_value: float = 0,
        max_value: float = 100,
    ) -> dict[str, Any]:
        """
        Create a gauge widget for metric visualization.

        Args:
            dashboard_id: Target dashboard.
            title: Widget title.
            device_id: Source device.
            metric: Metric name.
            min_value: Gauge minimum.
            max_value: Gauge maximum.

        Returns:
            Created gauge widget.
        """
        config = {
            "min_value": min_value,
            "max_value": max_value,
            "threshold_warning": max_value * 0.75,
            "threshold_critical": max_value * 0.9,
            "unit": "",
        }

        widget = self.add_widget(dashboard_id, "gauge", title, config)

        data_source = {
            "type": "telemetry",
            "device_id": str(device_id),
            "metric": metric,
        }

        self.bind_data_source(widget["widget_id"], data_source)

        return widget

    def create_chart_widget(
        self,
        dashboard_id: str,
        title: str,
        device_id: UUID,
        metrics: list[str],
        time_range_minutes: int = 60,
    ) -> dict[str, Any]:
        """
        Create a time-series chart widget.

        Args:
            dashboard_id: Target dashboard.
            title: Widget title.
            device_id: Source device.
            metrics: Metrics to display.
            time_range_minutes: Historical time range.

        Returns:
            Created chart widget.
        """
        config = {
            "chart_type": "line",
            "metrics": metrics,
            "time_range_minutes": time_range_minutes,
            "enable_zoom": True,
            "enable_pan": True,
        }

        widget = self.add_widget(dashboard_id, "chart", title, config)

        data_source = {
            "type": "telemetry",
            "device_id": str(device_id),
            "metrics": metrics,
        }

        self.bind_data_source(widget["widget_id"], data_source)

        return widget

    def create_alert_list_widget(
        self,
        dashboard_id: str,
        title: str,
        severity_filter: list[str] | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """
        Create an alert list widget.

        Args:
            dashboard_id: Target dashboard.
            title: Widget title.
            severity_filter: Optional severity filters.
            limit: Max alerts to display.

        Returns:
            Created alert widget.
        """
        config = {
            "severity_filter": severity_filter or ["warning", "error", "critical"],
            "limit": limit,
            "show_acknowledged": False,
            "sort_by": "timestamp",
        }

        widget = self.add_widget(dashboard_id, "alert_list", title, config, height=4)

        data_source = {
            "type": "rule_alerts",
        }

        self.bind_data_source(widget["widget_id"], data_source)

        return widget

    def create_kpi_widget(
        self,
        dashboard_id: str,
        title: str,
        device_id: UUID,
        metric: str,
        aggregation: str = "avg",
    ) -> dict[str, Any]:
        """
        Create a KPI (key performance indicator) widget.

        Args:
            dashboard_id: Target dashboard.
            title: Widget title.
            device_id: Source device.
            metric: Metric name.
            aggregation: Aggregation function.

        Returns:
            Created KPI widget.
        """
        config = {
            "aggregation": aggregation,
            "time_range_minutes": 60,
            "trend_enabled": True,
        }

        widget = self.add_widget(dashboard_id, "kpi", title, config, width=3)

        data_source = {
            "type": "telemetry",
            "device_id": str(device_id),
            "metric": metric,
        }

        self.bind_data_source(widget["widget_id"], data_source)

        return widget

    def create_map_widget(
        self,
        dashboard_id: str,
        title: str,
        group_id: str,
        zoom_level: int = 12,
    ) -> dict[str, Any]:
        """
        Create a map widget for device locations.

        Args:
            dashboard_id: Target dashboard.
            title: Widget title.
            group_id: Device group to display.
            zoom_level: Map zoom level.

        Returns:
            Created map widget.
        """
        config = {
            "zoom_level": zoom_level,
            "enable_clustering": True,
            "show_labels": True,
        }

        widget = self.add_widget(dashboard_id, "map", title, config, width=6, height=4)

        data_source = {
            "type": "device_locations",
            "group_id": group_id,
        }

        self.bind_data_source(widget["widget_id"], data_source)

        return widget

    def save_as_template(
        self,
        dashboard_id: str,
        template_name: str,
        description: str,
    ) -> dict[str, Any]:
        """
        Save dashboard as a template.

        Args:
            dashboard_id: Dashboard to save.
            template_name: Template name.
            description: Template description.

        Returns:
            Created template data.

        Raises:
            IoTException: If dashboard not found.
        """
        with self._lock:
            if dashboard_id not in self._dashboards:
                raise IoTException(f"Dashboard {dashboard_id} not found")

            dashboard = self._dashboards[dashboard_id]

            template_id = str(uuid4())

            template = {
                "template_id": template_id,
                "name": template_name,
                "description": description,
                "dashboard_config": dict(dashboard),
                "created_at": datetime.utcnow().isoformat(),
            }

            self._templates[template_id] = template

            return template

    def load_from_template(
        self,
        template_id: str,
        new_dashboard_name: str,
    ) -> dict[str, Any]:
        """
        Create dashboard from template.

        Args:
            template_id: Template to load.
            new_dashboard_name: Name for new dashboard.

        Returns:
            Created dashboard data.

        Raises:
            IoTException: If template not found.
        """
        with self._lock:
            if template_id not in self._templates:
                raise IoTException(f"Template {template_id} not found")

            template = self._templates[template_id]
            config = template["dashboard_config"]

            dashboard_id = str(uuid4())

            new_dashboard = {
                **config,
                "dashboard_id": dashboard_id,
                "name": new_dashboard_name,
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
            }

            self._dashboards[dashboard_id] = new_dashboard

            return new_dashboard

    def export_dashboard_config(self, dashboard_id: str) -> str:
        """
        Export dashboard configuration as JSON.

        Args:
            dashboard_id: Dashboard to export.

        Returns:
            JSON string of dashboard config.

        Raises:
            IoTException: If dashboard not found.
        """
        with self._lock:
            if dashboard_id not in self._dashboards:
                raise IoTException(f"Dashboard {dashboard_id} not found")

            dashboard = self._dashboards[dashboard_id]

            # Build export with widget details
            export_data = dict(dashboard)
            export_data["widgets_detail"] = [self._widgets.get(wid, {}) for wid in dashboard["widgets"]]

            return json.dumps(export_data, indent=2, default=str)

    def list_dashboards(self) -> list[dict[str, Any]]:
        """List all dashboards."""
        with self._lock:
            return list(self._dashboards.values())

    def list_templates(self) -> list[dict[str, Any]]:
        """List all dashboard templates."""
        with self._lock:
            return list(self._templates.values())

    def delete_dashboard(self, dashboard_id: str) -> bool:
        """
        Delete a dashboard.

        Args:
            dashboard_id: Dashboard to delete.

        Returns:
            True if deleted successfully.
        """
        with self._lock:
            if dashboard_id in self._dashboards:
                dashboard = self._dashboards[dashboard_id]

                # Clean up widgets
                for widget_id in dashboard["widgets"]:
                    if widget_id in self._widgets:
                        del self._widgets[widget_id]

                del self._dashboards[dashboard_id]
                return True

            return False

    def get_dashboard_count(self) -> int:
        """Get total number of dashboards."""
        with self._lock:
            return len(self._dashboards)

    def get_widget_count(self, dashboard_id: str) -> int:
        """
        Get widget count for a dashboard.

        Args:
            dashboard_id: Dashboard ID.

        Returns:
            Number of widgets.
        """
        with self._lock:
            if dashboard_id not in self._dashboards:
                return 0

            return len(self._dashboards[dashboard_id]["widgets"])
