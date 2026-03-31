import pytest
from prompts import _classify_question, _is_out_of_scope_response


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
    def test_concise_queries(self, query):
        assert _classify_question(query) == "concise"

    def test_empty_query(self):
        result = _classify_question("")
        assert result in ("casual", "concise")


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
