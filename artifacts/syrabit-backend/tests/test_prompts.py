import pytest
from prompts import _classify_question, _classify_intent, _is_out_of_scope_response, classify_intent


class TestClassifyQuestion:
    @pytest.mark.parametrize("query,expected", [
        ("hi", "casual"),
        ("hello", "casual"),
        ("good morning", "casual"),
        ("thanks", "casual"),
        ("motivate me", "casual"),
    ])
    def test_casual_queries(self, query, expected):
        assert _classify_question(query) == expected

    @pytest.mark.parametrize("query,expected", [
        ("define photosynthesis", "structured"),
        ("explain the Calvin cycle", "structured"),
        ("describe the structure of DNA", "structured"),
        ("discuss the importance of mitosis", "structured"),
    ])
    def test_structured_queries(self, query, expected):
        assert _classify_question(query) == expected

    @pytest.mark.parametrize("query", [
        "what is the boiling point of water",
        "how does a transistor work",
        "what is the boiling point of ethanol",
        "calculate the pH of 0.1M HCl",
    ])
    def test_academic_queries_are_structured(self, query):
        assert _classify_question(query) == "structured"

    def test_empty_query(self):
        result = _classify_question("")
        assert result in ("casual", "structured")


class TestClassifyIntent:
    @pytest.mark.parametrize("query,expected", [
        ("MCQ", "notes"),
        ("PYQ", "pyq"),
        ("mcq", "notes"),
        ("pyq", "pyq"),
        ("notes", "notes"),
        ("MCQ on photosynthesis", "notes"),
        ("PYQ 2024", "pyq"),
        ("notes for chapter 1", "notes"),
    ])
    def test_short_form_intents(self, query, expected):
        assert _classify_intent(query) == expected

    @pytest.mark.parametrize("query,expected", [
        ("hi", "casual"),
        ("hello", "casual"),
        ("thanks", "casual"),
        ("good morning", "casual"),
        ("...", "casual"),
        ("help", "casual"),
        ("help me", "casual"),
    ])
    def test_casual_intents(self, query, expected):
        assert _classify_intent(query) == expected

    @pytest.mark.parametrize("query,expected", [
        ("syllabus of business studies", "syllabus"),
        ("previous year question paper 2024", "pyq"),
        ("solve question 3 from 2023 pyq", "pyq"),
        ("important questions for exam", "important_questions"),
        ("important topics", "important_questions"),
        ("questions from chapter 2", "important_questions"),
        ("flashcard for revision", "notes"),
        ("exam pattern of physics", "chapter_meta"),
        ("5 mark questions list", "pyq"),
        ("explain the law of demand", "notes"),
        ("solve x^2 + 5x = 0", "notes"),
    ])
    def test_academic_intents(self, query, expected):
        assert _classify_intent(query) == expected

    @pytest.mark.parametrize("query,expected", [
        ("hi, give me PYQ for 2024", "pyq"),
        ("hello can you explain photosynthesis", "notes"),
        ("hey give me important questions", "important_questions"),
    ])
    def test_mixed_greeting_academic(self, query, expected):
        assert _classify_intent(query) == expected

    def test_empty_returns_notes(self):
        assert _classify_intent("") == "notes"

    def test_general_queries_map_to_notes(self):
        assert _classify_intent("what is DNA") == "notes"


class TestClassifyIntentTuple:
    def test_returns_tuple(self):
        intent, db_cat = classify_intent("notes for chapter 1")
        assert intent == "notes"
        assert db_cat == "notes"

    def test_pyq_returns_question_paper_category(self):
        intent, db_cat = classify_intent("PYQ 2024")
        assert intent == "pyq"
        assert db_cat == "question_paper"

    def test_casual_returns_none_category(self):
        intent, db_cat = classify_intent("hello")
        assert intent == "casual"
        assert db_cat is None

    def test_syllabus_returns_none_category(self):
        intent, db_cat = classify_intent("syllabus of physics")
        assert intent == "syllabus"
        assert db_cat is None

    def test_important_questions_returns_category(self):
        intent, db_cat = classify_intent("important questions for exam")
        assert intent == "important_questions"
        assert db_cat == "important_questions"

    def test_chapter_meta_returns_none_category(self):
        intent, db_cat = classify_intent("exam pattern of physics")
        assert intent == "chapter_meta"
        assert db_cat is None


class TestOutOfScopeDetection:
    @pytest.mark.parametrize("response", [
        "This question is outside the scope of my curriculum expertise.",
        "I'm sorry, but that falls outside my area. I'm designed to help with academic subjects only.",
        "This topic is not part of the curriculum I cover.",
        "I cannot help with this — it's beyond the scope of what I'm trained on.",
        "That's not covered in the curriculum I support.",
        "This is not related to your syllabus topics.",
        "I'm designed to help with your AHSEC/SEBA curriculum.",
        "This is beyond my expertise as an educational assistant.",
        "I specialize in Assam board curriculum only.",
    ])
    def test_detects_out_of_scope(self, response):
        assert _is_out_of_scope_response(response) is True

    @pytest.mark.parametrize("response", [
        "Photosynthesis is the process by which green plants convert light energy into chemical energy.",
        "The boiling point of water is 100 degrees Celsius at standard atmospheric pressure.",
        "DNA stands for Deoxyribonucleic Acid. It carries genetic information.",
        "Newton's first law states that an object at rest stays at rest.",
        "The Calvin cycle takes place in the stroma of chloroplasts.",
    ])
    def test_normal_responses_not_flagged(self, response):
        assert _is_out_of_scope_response(response) is False

    def test_empty_response(self):
        assert _is_out_of_scope_response("") is False
        assert _is_out_of_scope_response(None) is False
