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
        ("describe the structure of DNA", "structured"),
        ("discuss the importance of mitosis", "structured"),
        ("what is the structure of an atom", "structured"),
    ])
    def test_structured_queries(self, query, expected):
        assert _classify_question(query) == expected

    @pytest.mark.parametrize("query,expected", [
        ("calculate the pH of 0.1M HCl", "structured"),
        ("explain the law of demand", "structured"),
        ("define photosynthesis", "structured"),
    ])
    def test_academic_queries_are_structured(self, query, expected):
        assert _classify_question(query) == expected

    @pytest.mark.parametrize("query,expected", [
        ("how does a transistor work", "structured"),
        ("what is the structure of DNA", "structured"),
    ])
    def test_academic_phrased_queries_are_structured(self, query, expected):
        assert _classify_question(query) == expected

    @pytest.mark.parametrize("query", [
        "tell me a joke",
        "recommend a good movie",
    ])
    def test_non_academic_queries_are_general(self, query):
        assert _classify_question(query) == "general"

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

    def test_academic_queries_stay_notes(self):
        assert _classify_intent("what is DNA") == "notes"
        assert _classify_intent("what is photosynthesis") == "notes"
        assert _classify_intent("how does osmosis work") == "notes"
        assert _classify_intent("difference between mitosis and meiosis") == "notes"
        assert _classify_intent("importance of biodiversity") == "notes"
        assert _classify_intent("structure of an atom") == "notes"

    def test_non_academic_queries_are_general(self):
        assert _classify_intent("tell me a joke") == "general"
        assert _classify_intent("what's the weather like today") == "general"
        assert _classify_intent("recommend a good movie") == "general"
        assert _classify_intent("explain quantum computing") == "general"
        assert _classify_intent("what is bitcoin") == "general"
        assert _classify_intent("what is machine learning") == "general"


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
        "I cannot help with that request.",
        "I'm not able to assist with that kind of question.",
        "I'm unable to respond to this.",
        "I must decline this request.",
        "I can't answer that for safety reasons.",
        "I cannot answer that question.",
    ])
    def test_detects_out_of_scope(self, response):
        assert _is_out_of_scope_response(response) is True

    @pytest.mark.parametrize("response", [
        "Photosynthesis is the process by which green plants convert light energy into chemical energy.",
        "The boiling point of water is 100 degrees Celsius at standard atmospheric pressure.",
        "DNA stands for Deoxyribonucleic Acid. It carries genetic information.",
        "Newton's first law states that an object at rest stays at rest.",
        "The Calvin cycle takes place in the stroma of chloroplasts.",
        "The president of India is Droupadi Murmu.",
        "Here's a joke for you: Why did the chicken cross the road?",
        "Quantum computing uses quantum bits or qubits to process information.",
    ])
    def test_normal_responses_not_flagged(self, response):
        assert _is_out_of_scope_response(response) is False

    def test_empty_response(self):
        assert _is_out_of_scope_response("") is False
        assert _is_out_of_scope_response(None) is False
