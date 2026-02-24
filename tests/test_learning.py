"""Tests for thomas.learning module."""
import os
import json
import tempfile
import unittest

from thomas.learning.types import Lesson, LessonType, TeachabilityConfig, FeedbackEntry
from thomas.learning.store import LessonStore
from thomas.learning.analyzer import ConversationAnalyzer
from thomas.learning.injector import LessonInjector
from thomas.learning.feedback import FeedbackLoop
from thomas.learning.teacher import TeachableAgent


class TestLessonStore(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.td.name, "lessons.json")
        self.store = LessonStore(self.path)

    def tearDown(self):
        self.td.cleanup()

    def test_add_and_get(self):
        lesson = Lesson(lesson_type=LessonType.FACT, input_pattern="hello", output_pattern="world")
        lid = self.store.add_lesson(lesson)
        got = self.store.get_lesson(lid)
        self.assertIsNotNone(got)
        self.assertEqual(got.output_pattern, "world")

    def test_search(self):
        self.store.add_lesson(Lesson(lesson_type=LessonType.EXAMPLE, input_pattern="python programming language", output_pattern="use python"))
        self.store.add_lesson(Lesson(lesson_type=LessonType.EXAMPLE, input_pattern="cooking recipes food", output_pattern="make food"))
        results = self.store.search("python code", limit=5)
        self.assertGreater(len(results), 0)
        self.assertIn("python", results[0].input_pattern)

    def test_update_confidence(self):
        lesson = Lesson(lesson_type=LessonType.FACT, input_pattern="test", output_pattern="result")
        lid = self.store.add_lesson(lesson)
        self.store.update_confidence(lid, success=True)
        self.store.update_confidence(lid, success=True)
        self.store.update_confidence(lid, success=False)
        got = self.store.get_lesson(lid)
        self.assertAlmostEqual(got.confidence, 2/3, places=2)

    def test_remove(self):
        lesson = Lesson(lesson_type=LessonType.FACT, input_pattern="x", output_pattern="y")
        lid = self.store.add_lesson(lesson)
        self.assertTrue(self.store.remove_lesson(lid))
        self.assertIsNone(self.store.get_lesson(lid))

    def test_get_by_type(self):
        self.store.add_lesson(Lesson(lesson_type=LessonType.FACT, input_pattern="a", output_pattern="b"))
        self.store.add_lesson(Lesson(lesson_type=LessonType.CORRECTION, input_pattern="c", output_pattern="d"))
        facts = self.store.get_by_type(LessonType.FACT)
        self.assertEqual(len(facts), 1)

    def test_stats(self):
        self.store.add_lesson(Lesson(lesson_type=LessonType.FACT, input_pattern="a", output_pattern="b"))
        stats = self.store.stats()
        self.assertEqual(stats["total"], 1)

    def test_persistence(self):
        self.store.add_lesson(Lesson(lesson_type=LessonType.FACT, input_pattern="persist", output_pattern="ok"))
        store2 = LessonStore(self.path)
        self.assertEqual(len(store2.search("persist")), 1)


class TestAnalyzer(unittest.TestCase):
    def setUp(self):
        self.analyzer = ConversationAnalyzer()

    def test_analyze_success(self):
        lesson = self.analyzer.analyze_success("How do I sort?", "Use sorted()", 0.9)
        self.assertIsNotNone(lesson)
        self.assertEqual(lesson.lesson_type, LessonType.EXAMPLE)

    def test_analyze_success_low_score(self):
        lesson = self.analyzer.analyze_success("test", "bad", 0.3)
        self.assertIsNone(lesson)

    def test_analyze_correction(self):
        lesson = self.analyzer.analyze_correction("input", "wrong answer", "right answer")
        self.assertEqual(lesson.lesson_type, LessonType.CORRECTION)
        self.assertEqual(lesson.output_pattern, "right answer")

    def test_analyze_preference(self):
        lesson = self.analyzer.analyze_preference("input", "chosen", "rejected")
        self.assertEqual(lesson.lesson_type, LessonType.PREFERENCE)


class TestInjector(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.store = LessonStore(os.path.join(self.td.name, "l.json"))
        self.injector = LessonInjector()

    def tearDown(self):
        self.td.cleanup()

    def test_inject_with_lessons(self):
        self.store.add_lesson(Lesson(lesson_type=LessonType.EXAMPLE, input_pattern="python sorting", output_pattern="Use sorted()"))
        result = self.injector.inject_into_prompt("You are helpful.", "python sort", self.store)
        self.assertIn("Learned Knowledge", result)

    def test_inject_no_lessons(self):
        result = self.injector.inject_into_prompt("Base prompt", "random query", self.store)
        self.assertEqual(result, "Base prompt")

    def test_rank_lessons(self):
        lessons = [
            Lesson(lesson_type=LessonType.CORRECTION, input_pattern="a", output_pattern="b", confidence=0.9),
            Lesson(lesson_type=LessonType.EXAMPLE, input_pattern="c", output_pattern="d", confidence=0.5),
        ]
        ranked = self.injector.rank_lessons(lessons, "test")
        self.assertEqual(ranked[0].lesson_type, LessonType.CORRECTION)


class TestFeedback(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.fb = FeedbackLoop(os.path.join(self.td.name, "fb.json"))

    def tearDown(self):
        self.td.cleanup()

    def test_record_feedback(self):
        fid = self.fb.record_feedback("interaction1", 0.9, "great job")
        self.assertTrue(len(fid) > 0)

    def test_process_feedback(self):
        self.fb.record_feedback("i1", 0.9, "great work")
        self.fb.record_feedback("i2", 0.2, "terrible output")
        lessons = self.fb.process_feedback()
        self.assertGreater(len(lessons), 0)

    def test_improvement_suggestions(self):
        self.fb.record_feedback("i1", 0.2, "bad")
        suggestions = self.fb.get_improvement_suggestions()
        self.assertGreater(len(suggestions), 0)


class TestTeachableAgent(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()

        class MyAgent(TeachableAgent):
            pass

        self.agent = MyAgent()
        config = TeachabilityConfig(storage_path=os.path.join(self.td.name, "teach.json"))
        self.agent._init_teachability(config)

    def tearDown(self):
        self.td.cleanup()

    def test_learn(self):
        lid = self.agent.learn("How to sort python list", "Use sorted() function", 0.9)
        self.assertIsNotNone(lid)

    def test_recall(self):
        self.agent.learn("python sorting algorithms", "Use sorted()", 0.9)
        lessons = self.agent.recall("sort python", limit=5)
        self.assertGreater(len(lessons), 0)

    def test_teach(self):
        lid = self.agent.teach("The sky is blue", context="color questions")
        self.assertIsNotNone(lid)

    def test_correct(self):
        lid = self.agent.correct("capital of France", "London", "Paris")
        self.assertIsNotNone(lid)

    def test_enhance_prompt(self):
        self.agent.teach("Always be concise", context="writing style", tags=["style"])
        result = self.agent.enhance_prompt("You are helpful.", "writing style tips")
        self.assertIn("Learned Knowledge", result)

    def test_knowledge_summary(self):
        self.agent.teach("fact1")
        summary = self.agent.get_knowledge_summary()
        self.assertIn("Total lessons: 1", summary)


if __name__ == "__main__":
    unittest.main()
