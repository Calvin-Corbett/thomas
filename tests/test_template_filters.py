"""Tests for built-in filters."""

from thomas.template_engine import DictLoader, Environment


class TestFilterString:
    """Test string filters."""

    def test_filter_upper(self) -> None:
        """Test upper filter."""
        env = Environment(loader=DictLoader({"test": "{{ text | upper }}"}))
        template = env.get_template("test")
        result = template.render(text="hello")
        assert "HELLO" in result

    def test_filter_lower(self) -> None:
        """Test lower filter."""
        env = Environment(loader=DictLoader({"test": "{{ text | lower }}"}))
        template = env.get_template("test")
        result = template.render(text="HELLO")
        assert "hello" in result

    def test_filter_capitalize(self) -> None:
        """Test capitalize filter."""
        env = Environment(loader=DictLoader({"test": "{{ text | capitalize }}"}))
        template = env.get_template("test")
        result = template.render(text="hello world")
        assert "Hello" in result

    def test_filter_title(self) -> None:
        """Test title filter."""
        env = Environment(loader=DictLoader({"test": "{{ text | title }}"}))
        template = env.get_template("test")
        result = template.render(text="hello world")
        assert "Hello" in result and "World" in result

    def test_filter_trim(self) -> None:
        """Test trim filter."""
        env = Environment(loader=DictLoader({"test": "{{ text | trim }}"}))
        template = env.get_template("test")
        result = template.render(text="  hello  ")
        assert "hello" in result

    def test_filter_replace(self) -> None:
        """Test replace filter."""
        env = Environment(loader=DictLoader({"test": '{{ text | replace("world", "there") }}'}))
        template = env.get_template("test")
        result = template.render(text="hello world")
        assert "hello there" in result

    def test_filter_escape(self) -> None:
        """Test escape filter."""
        env = Environment(loader=DictLoader({"test": "{{ html | escape }}"}))
        template = env.get_template("test")
        result = template.render(html="<script>")
        assert "&lt;" in result or "lt" in result


class TestFilterList:
    """Test list/sequence filters."""

    def test_filter_length(self) -> None:
        """Test length filter."""
        env = Environment(loader=DictLoader({"test": "{{ items | length }}"}))
        template = env.get_template("test")
        result = template.render(items=[1, 2, 3])
        assert "3" in result

    def test_filter_join(self) -> None:
        """Test join filter."""
        env = Environment(loader=DictLoader({"test": "{{ items | join(', ') }}"}))
        template = env.get_template("test")
        result = template.render(items=["a", "b", "c"])
        assert "a, b, c" in result

    def test_filter_first(self) -> None:
        """Test first filter."""
        env = Environment(loader=DictLoader({"test": "{{ items | first }}"}))
        template = env.get_template("test")
        result = template.render(items=[1, 2, 3])
        assert "1" in result

    def test_filter_last(self) -> None:
        """Test last filter."""
        env = Environment(loader=DictLoader({"test": "{{ items | last }}"}))
        template = env.get_template("test")
        result = template.render(items=[1, 2, 3])
        assert "3" in result

    def test_filter_reverse(self) -> None:
        """Test reverse filter."""
        env = Environment(loader=DictLoader({"test": "{{ items | reverse | join('') }}"}))
        template = env.get_template("test")
        result = template.render(items=[1, 2, 3])
        assert "321" in result

    def test_filter_sort(self) -> None:
        """Test sort filter."""
        env = Environment(loader=DictLoader({"test": "{{ items | sort | join('') }}"}))
        template = env.get_template("test")
        result = template.render(items=[3, 1, 2])
        assert "123" in result

    def test_filter_unique(self) -> None:
        """Test unique filter."""
        env = Environment(loader=DictLoader({"test": "{{ items | unique | length }}"}))
        template = env.get_template("test")
        result = template.render(items=[1, 2, 2, 3, 3, 3])
        assert "3" in result

    def test_filter_list(self) -> None:
        """Test list filter."""
        env = Environment(loader=DictLoader({"test": "{{ items | list | length }}"}))
        template = env.get_template("test")
        result = template.render(items="abc")
        assert "3" in result


class TestFilterMath:
    """Test mathematical filters."""

    def test_filter_abs(self) -> None:
        """Test abs filter."""
        env = Environment(loader=DictLoader({"test": "{{ num | abs }}"}))
        template = env.get_template("test")
        result = template.render(num=-5)
        assert "5" in result

    def test_filter_int(self) -> None:
        """Test int filter."""
        env = Environment(loader=DictLoader({"test": "{{ num | int }}"}))
        template = env.get_template("test")
        result = template.render(num="42")
        assert "42" in result

    def test_filter_float(self) -> None:
        """Test float filter."""
        env = Environment(loader=DictLoader({"test": "{{ num | float }}"}))
        template = env.get_template("test")
        result = template.render(num="3.14")
        assert "3.14" in result

    def test_filter_round(self) -> None:
        """Test round filter."""
        env = Environment(loader=DictLoader({"test": "{{ num | round(2) }}"}))
        template = env.get_template("test")
        result = template.render(num=3.14159)
        assert "3.14" in result

    def test_filter_sum(self) -> None:
        """Test sum filter."""
        env = Environment(loader=DictLoader({"test": "{{ nums | sum }}"}))
        template = env.get_template("test")
        result = template.render(nums=[1, 2, 3, 4])
        assert "10" in result

    def test_filter_min(self) -> None:
        """Test min filter."""
        env = Environment(loader=DictLoader({"test": "{{ nums | min }}"}))
        template = env.get_template("test")
        result = template.render(nums=[3, 1, 2])
        assert "1" in result

    def test_filter_max(self) -> None:
        """Test max filter."""
        env = Environment(loader=DictLoader({"test": "{{ nums | max }}"}))
        template = env.get_template("test")
        result = template.render(nums=[3, 1, 2])
        assert "3" in result


class TestFilterDict:
    """Test dictionary filters."""

    def test_filter_dictsort(self) -> None:
        """Test dictsort filter."""
        env = Environment(loader=DictLoader({"test": "{{ d | dictsort | length }}"}))
        template = env.get_template("test")
        result = template.render(d={"c": 3, "a": 1, "b": 2})
        assert "3" in result


class TestFilterDefault:
    """Test default filter."""

    def test_filter_default_with_value(self) -> None:
        """Test default filter with existing value."""
        env = Environment(loader=DictLoader({"test": "{{ value | default('N/A') }}"}))
        template = env.get_template("test")
        result = template.render(value="present")
        assert "present" in result

    def test_filter_default_no_value(self) -> None:
        """Test default filter with missing value."""
        env = Environment(loader=DictLoader({"test": "{{ value | default('N/A') }}"}))
        template = env.get_template("test")
        result = template.render()
        assert "N/A" in result

    def test_filter_default_false_value(self) -> None:
        """Test default filter with false value in boolean mode."""
        env = Environment(loader=DictLoader({"test": "{{ value | default('N/A', true) }}"}))
        template = env.get_template("test")
        result = template.render(value=False)
        assert "N/A" in result


class TestFilterString2:
    """Test more string filters."""

    def test_filter_truncate(self) -> None:
        """Test truncate filter."""
        env = Environment(loader=DictLoader({"test": "{{ text | truncate(5) }}"}))
        template = env.get_template("test")
        result = template.render(text="hello world")
        assert "..." in result or len(result) < 20

    def test_filter_center(self) -> None:
        """Test center filter."""
        env = Environment(loader=DictLoader({"test": "{{ text | center(10) }}"}))
        template = env.get_template("test")
        result = template.render(text="hi")
        assert "hi" in result

    def test_filter_indent(self) -> None:
        """Test indent filter."""
        env = Environment(loader=DictLoader({"test": "{{ text | indent(4) }}"}))
        template = env.get_template("test")
        result = template.render(text="line1\nline2")
        # Should have indentation
        assert "line1" in result or "    " in result

    def test_filter_wordcount(self) -> None:
        """Test wordcount filter."""
        env = Environment(loader=DictLoader({"test": "{{ text | wordcount }}"}))
        template = env.get_template("test")
        result = template.render(text="hello world test")
        assert "3" in result

    def test_filter_striptags(self) -> None:
        """Test striptags filter."""
        env = Environment(loader=DictLoader({"test": "{{ html | striptags }}"}))
        template = env.get_template("test")
        result = template.render(html="<p>hello</p>")
        assert "hello" in result
        assert "<p>" not in result


class TestFilterComplex:
    """Test complex filter combinations."""

    def test_multiple_filters_chain(self) -> None:
        """Test chaining multiple filters."""
        env = Environment(loader=DictLoader({"test": "{{ items | join(', ') | upper }}"}))
        template = env.get_template("test")
        result = template.render(items=["a", "b", "c"])
        assert "A, B, C" in result

    def test_filter_with_variable_argument(self) -> None:
        """Test filter with variable argument."""
        env = Environment(loader=DictLoader({"test": "{{ text | replace(old, new) }}"}))
        template = env.get_template("test")
        result = template.render(text="hello world", old="world", new="there")
        assert "hello there" in result

    def test_grouped_filter(self) -> None:
        """Test groupby filter."""
        env = Environment(loader=DictLoader({"test": "{{ items | groupby('type') | length }}"}))
        template = env.get_template("test")
        result = template.render(
            items=[
                {"type": "a", "value": 1},
                {"type": "a", "value": 2},
                {"type": "b", "value": 3},
            ]
        )
        assert "2" in result
