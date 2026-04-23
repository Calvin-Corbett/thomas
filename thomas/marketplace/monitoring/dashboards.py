"""
Dashboard engine for metric visualization.

Supports dashboard definitions with panels, templating, time ranges,
and multiple panel types.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from thomas.marketplace.monitoring._exceptions import MetricError
from thomas.marketplace.monitoring._types import (
    Annotation,
    Dashboard,
    Panel,
    Query,
    Threshold,
)


@dataclass
class PanelData:
    """Data for a panel."""

    panel_id: str
    timestamps: list[float]
    values: dict[str, list[float]]  # series_key -> values
    threshold_violations: list[tuple[float, str]] = field(default_factory=list)


@dataclass
class DashboardVariable:
    """A dashboard template variable."""

    name: str
    var_type: str  # query, custom, interval
    value: Any
    label: str = ""
    options: list[str] = field(default_factory=list)
    multi: bool = False


class DashboardEngine:
    """Engine for dashboard rendering and management."""

    def __init__(self, query_engine: any) -> None:
        self.query_engine = query_engine
        self._lock = threading.Lock()
        self._dashboards: dict[str, Dashboard] = {}
        self._annotations: list[Annotation] = []
        self._panel_cache: dict[str, PanelData] = {}
        self._cache_ttl_seconds = 60

    def create_dashboard(self, dashboard: Dashboard) -> str:
        """Create a new dashboard."""
        with self._lock:
            if dashboard.id in self._dashboards:
                raise MetricError(f"Dashboard {dashboard.id} already exists")

            dashboard.created_at = datetime.utcnow()
            dashboard.updated_at = datetime.utcnow()
            self._dashboards[dashboard.id] = dashboard
            return dashboard.id

    def update_dashboard(self, dashboard: Dashboard) -> bool:
        """Update an existing dashboard."""
        with self._lock:
            if dashboard.id not in self._dashboards:
                return False

            dashboard.updated_at = datetime.utcnow()
            dashboard.version += 1
            self._dashboards[dashboard.id] = dashboard
            # Invalidate cache
            self._panel_cache.clear()
            return True

    def delete_dashboard(self, dashboard_id: str) -> bool:
        """Delete a dashboard."""
        with self._lock:
            if dashboard_id in self._dashboards:
                del self._dashboards[dashboard_id]
                return True
            return False

    def get_dashboard(self, dashboard_id: str) -> Dashboard | None:
        """Get a dashboard."""
        with self._lock:
            return self._dashboards.get(dashboard_id)

    def list_dashboards(self, tags: list[str] | None = None) -> list[Dashboard]:
        """List all dashboards, optionally filtered by tags."""
        with self._lock:
            dashboards = list(self._dashboards.values())

            if tags:
                dashboards = [d for d in dashboards if any(tag in d.tags for tag in tags)]

            return dashboards

    def add_annotation(self, annotation: Annotation) -> None:
        """Add an annotation to dashboard."""
        with self._lock:
            self._annotations.append(annotation)

    def get_annotations(
        self,
        dashboard_id: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Annotation]:
        """Get annotations."""
        with self._lock:
            annotations = list(self._annotations)

            if dashboard_id:
                annotations = [a for a in annotations if a.dashboard_id == dashboard_id]

            if start:
                annotations = [a for a in annotations if a.timestamp >= start]

            if end:
                annotations = [a for a in annotations if a.timestamp <= end]

            return annotations

    def render_panel(
        self,
        dashboard_id: str,
        panel_id: str,
        start: float | None = None,
        end: float | None = None,
    ) -> PanelData | None:
        """Render a panel with data."""
        dashboard = self.get_dashboard(dashboard_id)
        if not dashboard:
            return None

        panel = None
        for p in dashboard.panels:
            if p.id == panel_id:
                panel = p
                break

        if not panel:
            return None

        # Check cache
        cache_key = f"{dashboard_id}_{panel_id}"
        with self._lock:
            if cache_key in self._panel_cache:
                return self._panel_cache[cache_key]

        # Execute query
        try:
            if start and end:
                result = self.query_engine.range_query(
                    panel.query.expr,
                    start,
                    end,
                    step=panel.interval.total_seconds(),
                )

                # Build panel data
                timestamps = []
                values: dict[str, list[float]] = {}

                for series_key, series_data in result.series.items():
                    values[series_key] = []
                    for ts, val in series_data:
                        if ts not in timestamps:
                            timestamps.append(ts)
                        values[series_key].append(val)

                timestamps.sort()

                panel_data = PanelData(
                    panel_id=panel_id,
                    timestamps=timestamps,
                    values=values,
                )

                # Check threshold violations
                for threshold in panel.thresholds:
                    for series_key, series_values in values.items():
                        for val in series_values:
                            if threshold.severity == "critical" and val > threshold.value:
                                panel_data.threshold_violations.append((val, threshold.severity))

                # Cache result
                with self._lock:
                    self._panel_cache[cache_key] = panel_data

                return panel_data

        except Exception:  # REVIEWED: broad catch
            pass

        return None

    def render_dashboard(
        self,
        dashboard_id: str,
        start: float | None = None,
        end: float | None = None,
    ) -> dict[str, Any] | None:
        """Render entire dashboard with all panel data."""
        dashboard = self.get_dashboard(dashboard_id)
        if not dashboard:
            return None

        if not start or not end:
            # Use default time range
            end = datetime.utcnow().timestamp()
            start = (datetime.utcnow() - timedelta(hours=6)).timestamp()

        panels_data = {}
        for panel in dashboard.panels:
            panel_data = self.render_panel(dashboard_id, panel.id, start, end)
            if panel_data:
                panels_data[panel.id] = {
                    "title": panel.title,
                    "type": panel.panel_type,
                    "timestamps": panel_data.timestamps,
                    "values": panel_data.values,
                    "threshold_violations": panel_data.threshold_violations,
                }

        annotations = self.get_annotations(
            dashboard_id=dashboard_id,
            start=datetime.fromtimestamp(start),
            end=datetime.fromtimestamp(end),
        )

        return {
            "id": dashboard.id,
            "title": dashboard.title,
            "description": dashboard.description,
            "panels": panels_data,
            "annotations": [
                {
                    "timestamp": a.timestamp.timestamp(),
                    "title": a.title,
                    "severity": a.severity,
                }
                for a in annotations
            ],
            "variables": dashboard.variables,
            "refresh_interval": dashboard.refresh_interval.total_seconds(),
            "version": dashboard.version,
        }

    def export_dashboard(self, dashboard_id: str) -> str | None:
        """Export dashboard as JSON."""
        dashboard = self.get_dashboard(dashboard_id)
        if not dashboard:
            return None

        dashboard_dict = {
            "id": dashboard.id,
            "title": dashboard.title,
            "description": dashboard.description,
            "panels": [
                {
                    "id": panel.id,
                    "title": panel.title,
                    "type": panel.panel_type,
                    "query": panel.query.expr,
                    "interval": panel.interval.total_seconds(),
                    "thresholds": [
                        {
                            "value": t.value,
                            "severity": t.severity,
                        }
                        for t in panel.thresholds
                    ],
                    "unit": panel.unit,
                }
                for panel in dashboard.panels
            ],
            "variables": dashboard.variables,
            "time_range": dashboard.time_range,
            "refresh_interval": dashboard.refresh_interval.total_seconds(),
            "tags": dashboard.tags,
        }

        return json.dumps(dashboard_dict, indent=2)

    def import_dashboard(self, json_str: str) -> Dashboard | None:
        """Import dashboard from JSON."""
        try:
            data = json.loads(json_str)

            panels = []
            for panel_data in data.get("panels", []):
                query = Query(expr=panel_data["query"])
                thresholds = [
                    Threshold(
                        value=t["value"],
                        severity=t.get("severity", "warning"),
                    )
                    for t in panel_data.get("thresholds", [])
                ]
                panel = Panel(
                    id=panel_data["id"],
                    title=panel_data["title"],
                    panel_type=panel_data["type"],
                    query=query,
                    interval=timedelta(seconds=panel_data.get("interval", 60)),
                    thresholds=thresholds,
                    unit=panel_data.get("unit", ""),
                )
                panels.append(panel)

            dashboard = Dashboard(
                id=data["id"],
                title=data["title"],
                description=data.get("description", ""),
                panels=panels,
                variables=data.get("variables", {}),
                time_range=tuple(data.get("time_range", ("now-6h", "now"))),
                refresh_interval=timedelta(seconds=data.get("refresh_interval", 30)),
                tags=data.get("tags", []),
            )

            return dashboard

        except Exception:  # REVIEWED: broad catch
            return None

    def clear_cache(self) -> None:
        """Clear panel data cache."""
        with self._lock:
            self._panel_cache.clear()
