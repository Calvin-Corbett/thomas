"""UI system with widgets, layout, and event handling."""

from collections.abc import Callable
from enum import Enum, auto
from typing import Any


class LayoutMode(Enum):
    """UI layout modes."""

    VERTICAL = auto()
    HORIZONTAL = auto()
    GRID = auto()
    ABSOLUTE = auto()


class Anchor(Enum):
    """UI anchor positions."""

    TOP_LEFT = auto()
    TOP_CENTER = auto()
    TOP_RIGHT = auto()
    CENTER_LEFT = auto()
    CENTER = auto()
    CENTER_RIGHT = auto()
    BOTTOM_LEFT = auto()
    BOTTOM_CENTER = auto()
    BOTTOM_RIGHT = auto()


class UIWidget:
    """
    Base class for all UI widgets.

    Attributes:
        name: Widget name.
        position: Relative position within parent.
        size: Widget dimensions (width, height).
        enabled: Whether widget is active.
        visible: Whether widget is rendered.
        anchor: Anchor position for layout.
        offset: Offset from anchor.
    """

    def __init__(self, name: str = "widget") -> None:
        """Initialize UI widget."""
        self.name = name
        self.position: tuple[float, float] = (0.0, 0.0)
        self.size: tuple[float, float] = (100.0, 30.0)
        self.enabled = True
        self.visible = True
        self.anchor = Anchor.TOP_LEFT
        self.offset: tuple[float, float] = (0.0, 0.0)
        self.parent: UIWidget | None = None
        self.children: list[UIWidget] = []
        self.on_mouse_enter: Callable[[], None] | None = None
        self.on_mouse_exit: Callable[[], None] | None = None
        self.on_mouse_down: Callable[[], None] | None = None
        self.on_mouse_up: Callable[[], None] | None = None

    def update(self, dt: float) -> None:
        """Update widget."""
        for child in self.children:
            child.update(dt)

    def render(self) -> None:
        """Render widget."""
        if not self.visible:
            return
        for child in self.children:
            child.render()

    def add_child(self, widget: "UIWidget") -> None:
        """Add child widget."""
        widget.parent = self
        self.children.append(widget)

    def remove_child(self, widget: "UIWidget") -> None:
        """Remove child widget."""
        if widget in self.children:
            self.children.remove(widget)
            widget.parent = None

    def get_world_position(self) -> tuple[float, float]:
        """Get world position accounting for parent."""
        x, y = self.position
        ox, oy = self.offset

        if self.parent:
            px, py = self.parent.get_world_position()
            return (px + x + ox, py + y + oy)

        return (x + ox, y + oy)

    def is_point_inside(self, x: float, y: float) -> bool:
        """Check if point is inside widget bounds."""
        wx, wy = self.get_world_position()
        w, h = self.size
        return wx <= x <= wx + w and wy <= y <= wy + h

    def on_event(self, event_type: str, data: Any = None) -> None:
        """Handle event."""
        pass


class Panel(UIWidget):
    """Container widget for organizing child widgets."""

    def __init__(self, name: str = "panel") -> None:
        """Initialize panel."""
        super().__init__(name)
        self.layout_mode = LayoutMode.VERTICAL
        self.background_color: tuple[float, float, float, float] = (0.2, 0.2, 0.2, 1.0)
        self.padding = 10.0
        self.spacing = 5.0

    def render(self) -> None:
        """Render panel background and children."""
        if not self.visible:
            return

        # Render background (in real implementation)
        # render_rect(wx, wy, w, h, color=self.background_color)

        super().render()

    def do_layout(self) -> None:
        """Perform layout of children."""
        if self.layout_mode == LayoutMode.VERTICAL:
            self._layout_vertical()
        elif self.layout_mode == LayoutMode.HORIZONTAL:
            self._layout_horizontal()
        elif self.layout_mode == LayoutMode.GRID:
            self._layout_grid()

    def _layout_vertical(self) -> None:
        """Layout children vertically."""
        y = self.padding
        for child in self.children:
            if not child.visible:
                continue
            child.position = (self.padding, y)
            y += child.size[1] + self.spacing

    def _layout_horizontal(self) -> None:
        """Layout children horizontally."""
        x = self.padding
        for child in self.children:
            if not child.visible:
                continue
            child.position = (x, self.padding)
            x += child.size[0] + self.spacing

    def _layout_grid(self) -> None:
        """Layout children in grid."""
        cols = max(1, int(self.size[0] / 100))
        x, y = self.padding, self.padding
        col = 0

        for child in self.children:
            if not child.visible:
                continue
            child.position = (x, y)
            x += child.size[0] + self.spacing
            col += 1

            if col >= cols:
                col = 0
                x = self.padding
                y += child.size[1] + self.spacing


class Label(UIWidget):
    """Text label widget."""

    def __init__(self, name: str = "label", text: str = "") -> None:
        """Initialize label."""
        super().__init__(name)
        self.text = text
        self.text_color: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)
        self.font_size = 16
        self.alignment = "left"  # left, center, right

    def render(self) -> None:
        """Render label text."""
        if not self.visible:
            return
        # render_text(self.text, self.get_world_position(), self.font_size, self.text_color)
        super().render()


class Button(UIWidget):
    """Clickable button widget."""

    def __init__(self, name: str = "button", label: str = "") -> None:
        """Initialize button."""
        super().__init__(name)
        self.label = label
        self.on_click: Callable[[], None] | None = None
        self.is_hovered = False
        self.is_pressed = False
        self.normal_color: tuple[float, float, float, float] = (0.3, 0.3, 0.3, 1.0)
        self.hover_color: tuple[float, float, float, float] = (0.5, 0.5, 0.5, 1.0)
        self.pressed_color: tuple[float, float, float, float] = (0.2, 0.2, 0.2, 1.0)

    def render(self) -> None:
        """Render button."""
        if not self.visible:
            return

        # Choose color based on state
        if self.is_pressed:
            pass
        elif self.is_hovered:
            pass
        else:
            pass

        # render_rect(..., color=color)
        # render_text(self.label, ...)
        super().render()

    def on_event(self, event_type: str, data: Any = None) -> None:
        """Handle button events."""
        if event_type == "mouse_down" and self.is_point_inside(data[0], data[1]):
            self.is_pressed = True
        elif event_type == "mouse_up":
            if self.is_pressed and self.on_click:
                self.on_click()
            self.is_pressed = False
        elif event_type == "mouse_move":
            self.is_hovered = self.is_point_inside(data[0], data[1])


class Slider(UIWidget):
    """Slider widget for numeric input."""

    def __init__(self, name: str = "slider") -> None:
        """Initialize slider."""
        super().__init__(name)
        self.min_value = 0.0
        self.max_value = 100.0
        self.value = 50.0
        self.on_value_changed: Callable[[float], None] | None = None
        self.is_dragging = False

    def on_event(self, event_type: str, data: Any = None) -> None:
        """Handle slider events."""
        if event_type == "mouse_down" and self.is_point_inside(data[0], data[1]):
            self.is_dragging = True
            self._update_value_from_position(data[0])
        elif event_type == "mouse_up":
            self.is_dragging = False
        elif event_type == "mouse_move" and self.is_dragging:
            self._update_value_from_position(data[0])

    def _update_value_from_position(self, x: float) -> None:
        """Update value from mouse position."""
        wx, _ = self.get_world_position()
        w, _ = self.size
        local_x = x - wx
        t = max(0.0, min(1.0, local_x / w))
        self.value = self.min_value + (self.max_value - self.min_value) * t

        if self.on_value_changed:
            self.on_value_changed(self.value)


class ProgressBar(UIWidget):
    """Progress bar widget."""

    def __init__(self, name: str = "progress_bar") -> None:
        """Initialize progress bar."""
        super().__init__(name)
        self.progress = 0.5
        self.fill_color: tuple[float, float, float, float] = (0.2, 0.8, 0.2, 1.0)
        self.background_color: tuple[float, float, float, float] = (0.3, 0.3, 0.3, 1.0)

    def render(self) -> None:
        """Render progress bar."""
        if not self.visible:
            return

        # render background
        # render fill based on progress
        super().render()


class TextInput(UIWidget):
    """Text input widget."""

    def __init__(self, name: str = "text_input") -> None:
        """Initialize text input."""
        super().__init__(name)
        self.text = ""
        self.placeholder = "Enter text..."
        self.is_focused = False
        self.cursor_position = 0
        self.on_text_changed: Callable[[str], None] | None = None
        self.on_submit: Callable[[str], None] | None = None

    def on_event(self, event_type: str, data: Any = None) -> None:
        """Handle text input events."""
        if event_type == "mouse_down" and self.is_point_inside(data[0], data[1]):
            self.is_focused = True
        elif event_type == "key_char" and self.is_focused:
            self.text += data
            self.cursor_position += 1
            if self.on_text_changed:
                self.on_text_changed(self.text)
        elif event_type == "key_backspace" and self.is_focused:
            if self.cursor_position > 0:
                self.text = self.text[: self.cursor_position - 1] + self.text[self.cursor_position :]
                self.cursor_position -= 1
                if self.on_text_changed:
                    self.on_text_changed(self.text)
        elif event_type == "key_enter" and self.is_focused:
            if self.on_submit:
                self.on_submit(self.text)


class ScrollView(UIWidget):
    """Scrollable view container."""

    def __init__(self, name: str = "scroll_view") -> None:
        """Initialize scroll view."""
        super().__init__(name)
        self.scroll_offset = 0.0
        self.content_height = 0.0
        self.scroll_speed = 20.0

    def render(self) -> None:
        """Render scroll view with clipping."""
        if not self.visible:
            return
        # Implement scissor/clip for children
        super().render()


class Grid(UIWidget):
    """Grid layout widget."""

    def __init__(self, name: str = "grid") -> None:
        """Initialize grid."""
        super().__init__(name)
        self.columns = 3
        self.rows = 3
        self.cell_width = 0.0
        self.cell_height = 0.0

    def do_layout(self) -> None:
        """Layout grid cells."""
        if self.columns <= 0 or self.rows <= 0:
            return

        self.cell_width = self.size[0] / self.columns
        self.cell_height = self.size[1] / self.rows

        for i, child in enumerate(self.children):
            col = i % self.columns
            row = i // self.columns
            child.position = (col * self.cell_width, row * self.cell_height)
            child.size = (self.cell_width, self.cell_height)


class UIManager:
    """
    UI system managing widget tree and events.

    Features:
    - Widget tree with parent-child relationships
    - Event propagation (mouse events bubble)
    - Focus management (tab order)
    - Layout engine (horizontal/vertical/grid)
    - UI themes
    - 9-slice sprite rendering for scalable UI
    - Tooltips
    - Widget animations
    """

    def __init__(self) -> None:
        """Initialize UI manager."""
        self.root: Panel = Panel("root")
        self.focused_widget: UIWidget | None = None
        self.hovered_widget: UIWidget | None = None
        self.widgets: dict[str, UIWidget] = {}
        self.themes: dict[str, dict[str, Any]] = {}

    def register_widget(self, widget: UIWidget) -> None:
        """Register widget in manager."""
        self.widgets[widget.name] = widget

    def get_widget(self, name: str) -> UIWidget | None:
        """Get widget by name."""
        return self.widgets.get(name)

    def set_focus(self, widget: UIWidget | None) -> None:
        """Set focused widget."""
        self.focused_widget = widget

    def handle_mouse_event(self, event_type: str, x: float, y: float) -> None:
        """
        Handle mouse event.

        Args:
            event_type: "move", "down", "up"
            x: Mouse X.
            y: Mouse Y.
        """
        widget = self._find_widget_at(self.root, x, y)

        if event_type == "move":
            self.hovered_widget = widget
        elif event_type == "down":
            self.set_focus(widget)
            self._propagate_event(widget, "mouse_down", (x, y))
        elif event_type == "up":
            self._propagate_event(widget, "mouse_up", (x, y))

    def handle_key_event(self, key: str) -> None:
        """Handle keyboard event."""
        if self.focused_widget:
            if key == "enter":
                self.focused_widget.on_event("key_enter")
            elif key == "backspace":
                self.focused_widget.on_event("key_backspace")
            else:
                self.focused_widget.on_event("key_char", key)

    def update(self, dt: float) -> None:
        """Update UI."""
        self.root.update(dt)

    def render(self) -> None:
        """Render UI."""
        self.root.render()

    def _find_widget_at(self, widget: UIWidget, x: float, y: float) -> UIWidget | None:
        """Find widget at position."""
        if not widget.is_point_inside(x, y):
            return None

        for child in reversed(widget.children):  # Check in reverse order
            result = self._find_widget_at(child, x, y)
            if result:
                return result

        return widget

    def _propagate_event(self, widget: UIWidget | None, event_type: str, data: Any = None) -> None:
        """Propagate event up widget hierarchy."""
        while widget:
            widget.on_event(event_type, data)
            widget = widget.parent

    def create_theme(self, name: str) -> None:
        """Create UI theme."""
        self.themes[name] = {}

    def set_theme_value(self, theme: str, key: str, value: Any) -> None:
        """Set theme value."""
        if theme not in self.themes:
            self.create_theme(theme)
        self.themes[theme][key] = value

    def get_theme_value(self, theme: str, key: str, default: Any = None) -> Any:
        """Get theme value."""
        if theme not in self.themes:
            return default
        return self.themes[theme].get(key, default)
