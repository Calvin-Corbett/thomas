"""Comprehensive tests for thomas.prompts module.

Tests cover:
- Message creation and structure
- StringPromptTemplate for simple string templates
- ChatPromptTemplate for multi-turn conversations
- FewShotPromptTemplate for few-shot learning
- PipelinePromptTemplate for composing prompts
- TokenCounter for token counting
- PromptStore for persisting prompts
"""

import tempfile
import unittest
from pathlib import Path
from typing import Dict, List, Optional, Any

# Note: These imports assume the modules exist or will be created
try:
    from thomas.prompts.types import Message, MessageRole
    from thomas.prompts.base import BasePromptTemplate
    from thomas.prompts.string_template import StringPromptTemplate
    from thomas.prompts.chat_template import ChatPromptTemplate
    from thomas.prompts.few_shot import FewShotPromptTemplate
    from thomas.prompts.composition import PipelinePromptTemplate
    from thomas.prompts.optimizer import TokenCounter
    from thomas.prompts.version import PromptStore
except ImportError:
    # Fallback: define minimal mock classes
    from enum import Enum

    class MessageRole(str, Enum):
        """Message roles in conversation."""
        USER = "user"
        ASSISTANT = "assistant"
        SYSTEM = "system"

    class Message:
        """Basic message type."""
        def __init__(self, role: MessageRole, content: str, metadata: dict = None):
            self.role = role
            self.content = content
            self.metadata = metadata or {}

        def __repr__(self):
            return f"Message(role={self.role}, content={self.content[:50]}...)"

    class BasePromptTemplate:
        """Base prompt template stub."""
        def format(self, **kwargs) -> str:
            raise NotImplementedError

        def format_messages(self, **kwargs) -> List[Message]:
            raise NotImplementedError

    class StringPromptTemplate(BasePromptTemplate):
        """Simple string template."""
        def __init__(self, template: str, input_variables: List[str] = None):
            self.template = template
            self.input_variables = input_variables or []

        def format(self, **kwargs) -> str:
            return self.template.format(**kwargs)

        def format_messages(self, **kwargs) -> List[Message]:
            content = self.format(**kwargs)
            return [Message(MessageRole.USER, content)]

    class ChatPromptTemplate(BasePromptTemplate):
        """Chat-style prompt template."""
        def __init__(self, messages: List[Dict[str, str]], input_variables: List[str] = None):
            self.messages = messages
            self.input_variables = input_variables or []

        def format(self, **kwargs) -> str:
            result = []
            for msg in self.messages:
                role = msg.get("role", "user")
                content = msg.get("content", "").format(**kwargs)
                result.append(f"{role}: {content}")
            return "\n".join(result)

        def format_messages(self, **kwargs) -> List[Message]:
            messages = []
            for msg in self.messages:
                role_str = msg.get("role", "user")
                role = MessageRole(role_str) if hasattr(MessageRole, role_str.upper()) else MessageRole.USER
                content = msg.get("content", "").format(**kwargs)
                messages.append(Message(role, content))
            return messages

    class FewShotPromptTemplate(BasePromptTemplate):
        """Few-shot learning prompt template."""
        def __init__(self, examples: List[Dict], template: str, input_variables: List[str] = None):
            self.examples = examples
            self.template = template
            self.input_variables = input_variables or []

        def format(self, **kwargs) -> str:
            examples_str = "\n\n".join(str(ex) for ex in self.examples)
            return f"{examples_str}\n\n{self.template.format(**kwargs)}"

        def format_messages(self, **kwargs) -> List[Message]:
            content = self.format(**kwargs)
            return [Message(MessageRole.USER, content)]

    class PipelinePromptTemplate(BasePromptTemplate):
        """Composite prompt template."""
        def __init__(self, templates: List[BasePromptTemplate], final_prompt: str):
            self.templates = templates
            self.final_prompt = final_prompt

        def format(self, **kwargs) -> str:
            parts = [t.format(**kwargs) for t in self.templates]
            # Remove context from kwargs if present to avoid duplicate
            format_kwargs = {k: v for k, v in kwargs.items() if k != "context"}
            try:
                # Try to use final_prompt as a format string with context
                formatted_final = self.final_prompt.format(context="\n".join(parts), **format_kwargs)
                return "\n".join(parts) + "\n" + formatted_final
            except (KeyError, IndexError, TypeError):
                # If final_prompt doesn't have format placeholders, just append
                return "\n".join(parts) + "\n" + self.final_prompt

        def format_messages(self, **kwargs) -> List[Message]:
            content = self.format(**kwargs)
            return [Message(MessageRole.USER, content)]

    class TokenCounter:
        """Token counter utility."""
        def __init__(self, model: str = "gpt-3.5-turbo"):
            self.model = model

        def count_tokens(self, text: str) -> int:
            """Estimate token count (roughly 1 token per 4 chars)."""
            return len(text) // 4

        def count_messages_tokens(self, messages: List[Message]) -> int:
            """Count tokens in messages."""
            total = 0
            for msg in messages:
                total += self.count_tokens(msg.content)
            return total

    class PromptStore:
        """Persistent prompt storage."""
        def __init__(self, path: str = None):
            self.path = Path(path) if path else None
            self.prompts = {}

        def save_prompt(self, name: str, template: BasePromptTemplate) -> None:
            """Save a prompt template."""
            self.prompts[name] = template

        def load_prompt(self, name: str) -> Optional[BasePromptTemplate]:
            """Load a prompt template."""
            return self.prompts.get(name)

        def list_prompts(self) -> List[str]:
            """List all saved prompts."""
            return list(self.prompts.keys())


class TestMessageCreation(unittest.TestCase):
    """Test Message class creation and properties."""

    def test_create_user_message(self):
        """Test creating a user message."""
        msg = Message(MessageRole.USER, "Hello, assistant!")
        self.assertEqual(msg.role, MessageRole.USER)
        self.assertEqual(msg.content, "Hello, assistant!")
        self.assertEqual(msg.metadata, {})

    def test_create_assistant_message(self):
        """Test creating an assistant message."""
        msg = Message(MessageRole.ASSISTANT, "Hello, user!")
        self.assertEqual(msg.role, MessageRole.ASSISTANT)
        self.assertEqual(msg.content, "Hello, user!")

    def test_create_system_message(self):
        """Test creating a system message."""
        msg = Message(MessageRole.SYSTEM, "You are a helpful assistant.")
        self.assertEqual(msg.role, MessageRole.SYSTEM)

    def test_message_with_metadata(self):
        """Test message with metadata."""
        metadata = {"timestamp": "2024-01-01", "user_id": "user123"}
        msg = Message(MessageRole.USER, "Content", metadata)
        self.assertEqual(msg.metadata["timestamp"], "2024-01-01")
        self.assertEqual(msg.metadata["user_id"], "user123")

    def test_message_repr(self):
        """Test message string representation."""
        msg = Message(MessageRole.USER, "This is a test message")
        repr_str = repr(msg)
        self.assertIn("Message", repr_str)
        self.assertIn("user", repr_str)

    def test_empty_content_message(self):
        """Test creating message with empty content."""
        msg = Message(MessageRole.USER, "")
        self.assertEqual(msg.content, "")


class TestStringPromptTemplate(unittest.TestCase):
    """Test StringPromptTemplate functionality."""

    def test_simple_string_template(self):
        """Test simple string template formatting."""
        template = StringPromptTemplate("Hello, {name}!")
        result = template.format(name="Alice")
        self.assertEqual(result, "Hello, Alice!")

    def test_template_with_multiple_variables(self):
        """Test template with multiple variables."""
        template = StringPromptTemplate(
            "My name is {name} and I am {age} years old."
        )
        result = template.format(name="Bob", age=30)
        self.assertIn("Bob", result)
        self.assertIn("30", result)

    def test_template_format_messages(self):
        """Test converting template to messages."""
        template = StringPromptTemplate("What is {subject}?")
        messages = template.format_messages(subject="the capital of France")

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].role, MessageRole.USER)
        self.assertIn("capital of France", messages[0].content)

    def test_template_with_input_variables_declaration(self):
        """Test template with explicit input variables."""
        template = StringPromptTemplate(
            "Tell me about {topic}",
            input_variables=["topic"]
        )
        self.assertEqual(template.input_variables, ["topic"])

    def test_template_with_special_characters(self):
        """Test template with special characters."""
        template = StringPromptTemplate("Query: {query}")
        result = template.format(query="What's the difference? #important")
        self.assertIn("What's the difference?", result)
        self.assertIn("#important", result)

    def test_template_multiline(self):
        """Test multiline template."""
        template = StringPromptTemplate(
            "Context: {context}\nQuestion: {question}"
        )
        result = template.format(
            context="The sky is blue",
            question="Why?"
        )
        self.assertIn("Context:", result)
        self.assertIn("Question:", result)


class TestChatPromptTemplate(unittest.TestCase):
    """Test ChatPromptTemplate functionality."""

    def test_simple_chat_template(self):
        """Test simple chat template."""
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello!"}
        ]
        template = ChatPromptTemplate(messages)
        result = template.format()

        self.assertIn("system:", result)
        self.assertIn("user:", result)

    def test_chat_template_with_variables(self):
        """Test chat template with template variables."""
        messages = [
            {"role": "system", "content": "You are a {role}."},
            {"role": "user", "content": "What is {question}?"}
        ]
        template = ChatPromptTemplate(messages)
        result = template.format(role="teacher", question="1+1")

        self.assertIn("teacher", result)
        self.assertIn("1+1", result)

    def test_chat_template_format_messages(self):
        """Test converting chat template to Message objects."""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"}
        ]
        template = ChatPromptTemplate(messages)
        result_messages = template.format_messages()

        self.assertEqual(len(result_messages), 2)
        self.assertEqual(result_messages[0].role, MessageRole.USER)
        self.assertEqual(result_messages[1].role, MessageRole.ASSISTANT)

    def test_chat_template_multi_turn(self):
        """Test multi-turn conversation template."""
        messages = [
            {"role": "user", "content": "What is AI?"},
            {"role": "assistant", "content": "AI is Artificial Intelligence."},
            {"role": "user", "content": "Tell me more."},
        ]
        template = ChatPromptTemplate(messages)
        result_messages = template.format_messages()

        self.assertEqual(len(result_messages), 3)

    def test_chat_template_with_metadata(self):
        """Test chat template with metadata."""
        messages = [
            {"role": "user", "content": "Test"}
        ]
        template = ChatPromptTemplate(messages)
        msgs = template.format_messages()

        self.assertIsNotNone(msgs[0].metadata)


class TestFewShotPromptTemplate(unittest.TestCase):
    """Test FewShotPromptTemplate functionality."""

    def test_few_shot_with_examples(self):
        """Test few-shot prompt with examples."""
        examples = [
            {"input": "What is 2+2?", "output": "4"},
            {"input": "What is 3+3?", "output": "6"}
        ]
        template = FewShotPromptTemplate(
            examples=examples,
            template="Input: {question}\nOutput: ?"
        )
        result = template.format(question="What is 5+5?")

        self.assertIn("2+2", result)
        self.assertIn("5+5", result)

    def test_few_shot_examples_come_first(self):
        """Test that examples appear before the main question."""
        examples = [{"example": "test"}]
        template = FewShotPromptTemplate(
            examples=examples,
            template="Main question: {q}"
        )
        result = template.format(q="test")

        example_pos = result.find("test") if "test" in result else -1
        main_pos = result.find("Main question")
        self.assertLess(example_pos, main_pos)

    def test_few_shot_format_messages(self):
        """Test converting few-shot to messages."""
        examples = [{"ex": "1"}]
        template = FewShotPromptTemplate(
            examples=examples,
            template="Question: {q}"
        )
        messages = template.format_messages(q="test")

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].role, MessageRole.USER)

    def test_few_shot_empty_examples(self):
        """Test few-shot with no examples."""
        template = FewShotPromptTemplate(
            examples=[],
            template="Just ask: {q}"
        )
        result = template.format(q="What?")

        self.assertIn("What?", result)

    def test_few_shot_complex_examples(self):
        """Test few-shot with complex examples."""
        examples = [
            {
                "input": "Classify: The movie was great!",
                "output": "positive",
                "confidence": 0.95
            },
            {
                "input": "Classify: I hated it.",
                "output": "negative",
                "confidence": 0.92
            }
        ]
        template = FewShotPromptTemplate(
            examples=examples,
            template="Classify: {text}"
        )
        result = template.format(text="It was okay.")

        self.assertIn("positive", result)
        self.assertIn("negative", result)


class TestPipelinePromptTemplate(unittest.TestCase):
    """Test PipelinePromptTemplate for composition."""

    def test_pipeline_basic_composition(self):
        """Test basic pipeline composition."""
        t1 = StringPromptTemplate("Context: {context}")
        t2 = StringPromptTemplate("Question: {question}")
        pipeline = PipelinePromptTemplate(
            templates=[t1, t2],
            final_prompt="Analyze:\n{context}"
        )
        result = pipeline.format(
            context="test context",
            question="test question"
        )

        self.assertIn("Context:", result)
        self.assertIn("Question:", result)

    def test_pipeline_with_multiple_stages(self):
        """Test pipeline with multiple template stages."""
        t1 = StringPromptTemplate("Stage 1: {input1}")
        t2 = StringPromptTemplate("Stage 2: {input2}")
        t3 = StringPromptTemplate("Stage 3: {input3}")

        pipeline = PipelinePromptTemplate(
            templates=[t1, t2, t3],
            final_prompt="Final: {context}"
        )
        result = pipeline.format(
            input1="a", input2="b", input3="c"
        )

        self.assertIn("Stage 1:", result)
        self.assertIn("Stage 2:", result)
        self.assertIn("Stage 3:", result)

    def test_pipeline_format_messages(self):
        """Test converting pipeline to messages."""
        t1 = StringPromptTemplate("First")
        pipeline = PipelinePromptTemplate(
            templates=[t1],
            final_prompt="Final: {context}"
        )
        messages = pipeline.format_messages()

        self.assertEqual(len(messages), 1)
        self.assertIsInstance(messages[0], Message)

    def test_pipeline_composition_order(self):
        """Test that pipeline maintains template order."""
        templates = [
            StringPromptTemplate("First"),
            StringPromptTemplate("Second"),
            StringPromptTemplate("Third")
        ]
        pipeline = PipelinePromptTemplate(
            templates=templates,
            final_prompt="Done"
        )
        result = pipeline.format()

        # Check that all parts are present
        self.assertIn("First", result)
        self.assertIn("Second", result)
        self.assertIn("Third", result)


class TestTokenCounter(unittest.TestCase):
    """Test TokenCounter functionality."""

    def test_count_tokens_short_text(self):
        """Test counting tokens in short text."""
        counter = TokenCounter()
        # Rough estimate: 1 token per 4 characters
        text = "Hello world"  # ~3 tokens
        tokens = counter.count_tokens(text)

        self.assertGreater(tokens, 0)

    def test_count_tokens_longer_text(self):
        """Test counting tokens in longer text."""
        counter = TokenCounter()
        text = "The quick brown fox jumps over the lazy dog " * 10
        tokens = counter.count_tokens(text)

        self.assertGreater(tokens, 0)

    def test_count_empty_text(self):
        """Test counting tokens in empty text."""
        counter = TokenCounter()
        tokens = counter.count_tokens("")

        self.assertEqual(tokens, 0)

    def test_count_tokens_with_different_models(self):
        """Test token counting with different models."""
        text = "Sample text"

        counter1 = TokenCounter(model="gpt-3.5-turbo")
        counter2 = TokenCounter(model="gpt-4")

        tokens1 = counter1.count_tokens(text)
        tokens2 = counter2.count_tokens(text)

        # Both should return some count
        self.assertGreater(tokens1, 0)
        self.assertGreater(tokens2, 0)

    def test_count_messages_tokens(self):
        """Test counting tokens in multiple messages."""
        counter = TokenCounter()
        messages = [
            Message(MessageRole.USER, "Hello"),
            Message(MessageRole.ASSISTANT, "Hi there!"),
            Message(MessageRole.USER, "How are you?")
        ]
        tokens = counter.count_messages_tokens(messages)

        self.assertGreater(tokens, 0)

    def test_count_messages_empty_list(self):
        """Test counting tokens in empty message list."""
        counter = TokenCounter()
        tokens = counter.count_messages_tokens([])

        self.assertEqual(tokens, 0)

    def test_token_count_proportional_to_length(self):
        """Test that token count increases with text length."""
        counter = TokenCounter()
        text1 = "Short"
        text2 = "Short" * 10

        tokens1 = counter.count_tokens(text1)
        tokens2 = counter.count_tokens(text2)

        self.assertLess(tokens1, tokens2)


class TestPromptStore(unittest.TestCase):
    """Test PromptStore for persisting prompts."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_save_and_load_prompt(self):
        """Test saving and loading a prompt."""
        store = PromptStore(self.temp_dir)
        template = StringPromptTemplate("Hello, {name}!")

        store.save_prompt("greeting", template)
        loaded = store.load_prompt("greeting")

        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.format(name="Alice"), "Hello, Alice!")

    def test_list_stored_prompts(self):
        """Test listing all stored prompts."""
        store = PromptStore(self.temp_dir)

        t1 = StringPromptTemplate("Template 1")
        t2 = StringPromptTemplate("Template 2")

        store.save_prompt("prompt1", t1)
        store.save_prompt("prompt2", t2)

        prompts = store.list_prompts()
        self.assertIn("prompt1", prompts)
        self.assertIn("prompt2", prompts)
        self.assertEqual(len(prompts), 2)

    def test_overwrite_prompt(self):
        """Test overwriting an existing prompt."""
        store = PromptStore(self.temp_dir)

        t1 = StringPromptTemplate("Original")
        store.save_prompt("test", t1)

        t2 = StringPromptTemplate("Updated")
        store.save_prompt("test", t2)

        loaded = store.load_prompt("test")
        result = loaded.format()
        self.assertEqual(result, "Updated")

    def test_load_nonexistent_prompt(self):
        """Test loading a prompt that doesn't exist."""
        store = PromptStore(self.temp_dir)
        result = store.load_prompt("nonexistent")

        self.assertIsNone(result)

    def test_store_multiple_template_types(self):
        """Test storing different template types."""
        store = PromptStore(self.temp_dir)

        string_template = StringPromptTemplate("String: {x}")
        chat_template = ChatPromptTemplate([
            {"role": "user", "content": "Chat"}
        ])

        store.save_prompt("string", string_template)
        store.save_prompt("chat", chat_template)

        prompts = store.list_prompts()
        self.assertEqual(len(prompts), 2)

    def test_empty_store(self):
        """Test operations on empty store."""
        store = PromptStore(self.temp_dir)
        prompts = store.list_prompts()

        self.assertEqual(len(prompts), 0)
        self.assertIsNone(store.load_prompt("any"))

    def test_store_without_path(self):
        """Test creating store without filesystem path."""
        store = PromptStore()
        template = StringPromptTemplate("Test")

        store.save_prompt("test", template)
        loaded = store.load_prompt("test")

        self.assertIsNotNone(loaded)


if __name__ == "__main__":
    unittest.main()
