import pytest
from syllabus_linker import _detect_board_key


class TestBoardDetection:
    @pytest.mark.parametrize("input_name,expected", [
        ("AHSEC", "ahsec"),
        ("Higher Secondary", "ahsec"),
        ("HS Board", "ahsec"),
        ("HS 1st Year", "ahsec"),
        ("HS 2nd Year", "ahsec"),
        ("Class XI students", "ahsec"),
        ("Class XII Board", "ahsec"),
        ("Class 11", "ahsec"),
        ("Class 12", "ahsec"),
        ("AHSEC HS 2nd Year Physics", "ahsec"),
    ])
    def test_ahsec_detection(self, input_name, expected):
        assert _detect_board_key(input_name) == expected

    @pytest.mark.parametrize("input_name,expected", [
        ("SEBA Board", "seba"),
        ("Secondary Education", "seba"),
        ("HSLC", "seba"),
        ("Class IX students", "seba"),
        ("Class X Board", "seba"),
        ("Class 9", "seba"),
        ("Class 10", "seba"),
        ("SEBA Class 10 Mathematics", "seba"),
    ])
    def test_seba_detection(self, input_name, expected):
        assert _detect_board_key(input_name) == expected

    @pytest.mark.parametrize("input_name,expected", [
        ("Darrang College (Autonomous)", "degree"),
        ("Gauhati University", "degree"),
        ("TDC Semester 1", "degree"),
        ("B.Sc Honours", "degree"),
        ("Cotton University", "degree"),
        ("FYUGP NEP", "degree"),
        ("Dibrugarh University Degree", "degree"),
        ("Tezpur University", "degree"),
        ("B.A Major Semester 3", "degree"),
        ("BCA 4th Semester", "degree"),
    ])
    def test_degree_detection(self, input_name, expected):
        assert _detect_board_key(input_name) == expected

    @pytest.mark.parametrize("input_name", [
        "Random text",
        "Hello world",
        "",
        "Something completely unrelated",
    ])
    def test_unknown_fallback(self, input_name):
        assert _detect_board_key(input_name) == "unknown"

    def test_none_input(self):
        assert _detect_board_key(None) == "unknown"

    def test_class_x_does_not_match_xi(self):
        assert _detect_board_key("Class X Board") == "seba"
        assert _detect_board_key("Class XI Board") == "ahsec"
        assert _detect_board_key("Class XII Board") == "ahsec"

    def test_case_insensitive(self):
        assert _detect_board_key("ahsec") == "ahsec"
        assert _detect_board_key("AHSEC") == "ahsec"
        assert _detect_board_key("Ahsec") == "ahsec"
