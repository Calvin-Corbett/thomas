"""Tests for UI system."""

from thomas.marketplace.gaming_platform.ui import (
    Button,
    Label,
    LayoutMode,
    Panel,
    ProgressBar,
    Slider,
    TextInput,
    UIManager,
    UIWidget,
)


class TestUIWidget:
    """Test base UI widget."""

    def test_widget_creation(self) -> None:
        """Test creating widget."""
        widget = UIWidget(name="test_widget")
        assert widget.name == "test_widget"
        assert widget.enabled is True
        assert widget.visible is True

    def test_widget_position(self) -> None:
        """Test widget position."""
        widget = UIWidget()
        widget.position = (100.0, 50.0)
        assert widget.position == (100.0, 50.0)

    def test_widget_size(self) -> None:
        """Test widget size."""
        widget = UIWidget()
        widget.size = (200.0, 100.0)
        assert widget.size == (200.0, 100.0)

    def test_widget_hierarchy(self) -> None:
        """Test parent-child relationships."""
        parent = UIWidget(name="parent")
        child = UIWidget(name="child")

        parent.add_child(child)
        assert child in parent.children
        assert child.parent == parent

    def test_remove_child(self) -> None:
        """Test removing child widget."""
        parent = UIWidget()
        child = UIWidget()

        parent.add_child(child)
        parent.remove_child(child)

        assert child not in parent.children
        assert child.parent is None

    def test_point_in_widget(self) -> None:
        """Test point containment."""
        widget = UIWidget()
        widget.position = (100.0, 100.0)
        widget.size = (50.0, 50.0)

        assert widget.is_point_inside(125.0, 125.0)
        assert not widget.is_point_inside(160.0, 160.0)

    def test_world_position_with_parent(self) -> None:
        """Test world position accounting for parent."""
        parent = UIWidget()
        parent.position = (100.0, 100.0)

        child = UIWidget()
        child.position = (25.0, 25.0)
        parent.add_child(child)

        world_pos = child.get_world_position()
        assert world_pos == (125.0, 125.0)


class TestPanel:
    """Test panel widget."""

    def test_panel_creation(self) -> None:
        """Test creating panel."""
        panel = Panel(name="test_panel")
        assert panel.layout_mode == LayoutMode.VERTICAL

    def test_vertical_layout(self) -> None:
        """Test vertical layout."""
        panel = Panel()
        panel.size = (100.0, 300.0)
        panel.layout_mode = LayoutMode.VERTICAL
        panel.padding = 10.0
        panel.spacing = 5.0

        for i in range(3):
            child = UIWidget()
            child.size = (80.0, 30.0)
            panel.add_child(child)

        panel.do_layout()

        # Children should be stacked vertically
        assert panel.children[0].position[1] == 10.0
        assert panel.children[1].position[1] > panel.children[0].position[1]

    def test_horizontal_layout(self) -> None:
        """Test horizontal layout."""
        panel = Panel()
        panel.size = (300.0, 100.0)
        panel.layout_mode = LayoutMode.HORIZONTAL
        panel.padding = 10.0
        panel.spacing = 5.0

        for i in range(3):
            child = UIWidget()
            child.size = (30.0, 80.0)
            panel.add_child(child)

        panel.do_layout()

        # Children should be arranged horizontally
        assert panel.children[0].position[0] == 10.0


class TestLabel:
    """Test label widget."""

    def test_label_creation(self) -> None:
        """Test creating label."""
        label = Label(name="label", text="Hello World")
        assert label.text == "Hello World"

    def test_label_text_update(self) -> None:
        """Test updating label text."""
        label = Label(text="Initial")
        label.text = "Updated"
        assert label.text == "Updated"

    def test_label_color(self) -> None:
        """Test label color."""
        label = Label()
        label.text_color = (1.0, 0.0, 0.0, 1.0)
        assert label.text_color[0] == 1.0


class TestButton:
    """Test button widget."""

    def test_button_creation(self) -> None:
        """Test creating button."""
        button = Button(name="btn", label="Click Me")
        assert button.label == "Click Me"

    def test_button_click(self) -> None:
        """Test button click detection."""
        clicked = False

        def on_click() -> None:
            nonlocal clicked
            clicked = True

        button = Button()
        button.position = (100.0, 100.0)
        button.size = (50.0, 30.0)
        button.on_click = on_click

        button.on_event("mouse_down", (125.0, 115.0))
        button.on_event("mouse_up", None)

        assert clicked

    def test_button_hover(self) -> None:
        """Test button hover state."""
        button = Button()
        button.position = (0.0, 0.0)
        button.size = (50.0, 30.0)

        button.on_event("mouse_move", (25.0, 15.0))
        assert button.is_hovered

        button.on_event("mouse_move", (100.0, 100.0))
        assert not button.is_hovered


class TestSlider:
    """Test slider widget."""

    def test_slider_creation(self) -> None:
        """Test creating slider."""
        slider = Slider()
        assert slider.min_value == 0.0
        assert slider.max_value == 100.0
        assert 0.0 <= slider.value <= 100.0

    def test_slider_drag(self) -> None:
        """Test dragging slider."""
        value_changed = False

        def on_change(v: float) -> None:
            nonlocal value_changed
            value_changed = True

        slider = Slider()
        slider.position = (0.0, 0.0)
        slider.size = (200.0, 20.0)
        slider.min_value = 0.0
        slider.max_value = 100.0
        slider.on_value_changed = on_change

        slider.on_event("mouse_down", (100.0, 10.0))
        assert value_changed

    def test_slider_value_range(self) -> None:
        """Test slider value clamping."""
        slider = Slider()
        slider.position = (0.0, 0.0)
        slider.size = (100.0, 20.0)
        slider.min_value = 0.0
        slider.max_value = 100.0

        slider.on_event("mouse_down", (50.0, 10.0))
        assert 0.0 <= slider.value <= 100.0


class TestProgressBar:
    """Test progress bar widget."""

    def test_progress_bar_creation(self) -> None:
        """Test creating progress bar."""
        bar = ProgressBar()
        assert 0.0 <= bar.progress <= 1.0

    def test_progress_bar_values(self) -> None:
        """Test progress bar values."""
        bar = ProgressBar()
        bar.progress = 0.0
        assert bar.progress == 0.0

        bar.progress = 0.5
        assert bar.progress == 0.5

        bar.progress = 1.0
        assert bar.progress == 1.0


class TestTextInput:
    """Test text input widget."""

    def test_text_input_creation(self) -> None:
        """Test creating text input."""
        input_widget = TextInput()
        assert input_widget.text == ""

    def test_text_input_focus(self) -> None:
        """Test text input focus."""
        input_widget = TextInput()
        input_widget.position = (0.0, 0.0)
        input_widget.size = (200.0, 30.0)

        input_widget.on_event("mouse_down", (100.0, 15.0))
        assert input_widget.is_focused

    def test_text_input_character(self) -> None:
        """Test typing characters."""
        text_changed = False

        def on_change(text: str) -> None:
            nonlocal text_changed
            text_changed = True

        input_widget = TextInput()
        input_widget.is_focused = True
        input_widget.on_text_changed = on_change

        input_widget.on_event("key_char", "H")
        assert "H" in input_widget.text
        assert text_changed

    def test_text_input_backspace(self) -> None:
        """Test backspace in text input."""
        input_widget = TextInput()
        input_widget.is_focused = True
        input_widget.text = "Hello"
        input_widget.cursor_position = 5

        input_widget.on_event("key_backspace", None)
        assert len(input_widget.text) < 5

    def test_text_input_submit(self) -> None:
        """Test text submission."""
        submitted = False
        submitted_text = ""

        def on_submit(text: str) -> None:
            nonlocal submitted, submitted_text
            submitted = True
            submitted_text = text

        input_widget = TextInput()
        input_widget.is_focused = True
        input_widget.text = "Test"
        input_widget.on_submit = on_submit

        input_widget.on_event("key_enter", None)
        assert submitted
        assert submitted_text == "Test"


class TestUIManager:
    """Test UI manager."""

    def test_manager_creation(self) -> None:
        """Test creating UI manager."""
        manager = UIManager()
        assert manager.root is not None
        assert manager.focused_widget is None

    def test_register_widget(self) -> None:
        """Test registering widget."""
        manager = UIManager()
        widget = UIWidget(name="test")

        manager.register_widget(widget)
        assert manager.get_widget("test") == widget

    def test_get_widget(self) -> None:
        """Test retrieving registered widget."""
        manager = UIManager()
        widget = UIWidget(name="button")
        manager.register_widget(widget)

        retrieved = manager.get_widget("button")
        assert retrieved == widget

    def test_set_focus(self) -> None:
        """Test focus management."""
        manager = UIManager()
        widget = UIWidget()

        manager.set_focus(widget)
        assert manager.focused_widget == widget

    def test_mouse_event_handling(self) -> None:
        """Test mouse event propagation."""
        manager = UIManager()

        # Add button to root
        button = Button()
        button.position = (0.0, 0.0)
        button.size = (50.0, 30.0)
        manager.root.add_child(button)

        # Send mouse event
        manager.handle_mouse_event("down", 25.0, 15.0)
        assert manager.focused_widget is not None

    def test_create_theme(self) -> None:
        """Test theme creation."""
        manager = UIManager()
        manager.create_theme("dark")
        assert "dark" in manager.themes

    def test_theme_values(self) -> None:
        """Test setting and getting theme values."""
        manager = UIManager()
        manager.create_theme("light")
        manager.set_theme_value("light", "bg_color", (1.0, 1.0, 1.0, 1.0))

        color = manager.get_theme_value("light", "bg_color")
        assert color == (1.0, 1.0, 1.0, 1.0)

    def test_ui_update(self) -> None:
        """Test UI update."""
        manager = UIManager()
        manager.update(0.016)

        # Should complete without error

    def test_ui_render(self) -> None:
        """Test UI rendering."""
        manager = UIManager()
        manager.render()

        # Should complete without error
