"""Tests for BotRenderMiddleware page-type dispatch (cache key derivation)."""
import pytest

from routes.cms_sarvam_health import derive_bot_cache_key


class TestStaticPages:
    @pytest.mark.parametrize("path,expected", [
        ("/", "_homepage_"),
        ("", "_homepage_"),
        ("/library", "_homepage_"),
        ("/pricing", "_pricing_"),
        ("/terms", "_terms_"),
        ("/privacy", "_privacy_"),
        ("/about", "_about_"),
        ("/chat", "_chat_"),
        ("/curriculum", "_curriculum_"),
        ("/exam-routine", "_exam_routine_"),
        # Task #499: every audited route must derive a distinct cache
        # key so the bot-render output carries its own canonical.
        ("/home", "_home_"),
        ("/technology", "_technology_"),
        ("/login", "_authshell_/login"),
        ("/signup", "_authshell_/signup"),
        ("/profile", "_authshell_/profile"),
        ("/admin/login", "_authshell_/admin-login"),
    ])
    def test_static(self, path, expected):
        assert derive_bot_cache_key(path) == expected

    def test_strips_trailing_slash(self):
        assert derive_bot_cache_key("/pricing/") == "_pricing_"
        assert derive_bot_cache_key("/curriculum///") == "_curriculum_"
        # Task #499: trailing-slash variants must still hit the same
        # auth-shell cache key — otherwise /login/ would skip bot-render
        # and lose its byte-zero canonical.
        assert derive_bot_cache_key("/login/") == "_authshell_/login"
        assert derive_bot_cache_key("/admin/login/") == "_authshell_/admin-login"


class TestBoardLevel:
    @pytest.mark.parametrize("board", ["ahsec", "seba", "degree", "cbse", "nep"])
    def test_board_landing(self, board):
        assert derive_bot_cache_key(f"/{board}") == f"_board_/{board}"

    def test_unknown_board_returns_none(self):
        assert derive_bot_cache_key("/randomthing") is None
        assert derive_bot_cache_key("/icse") is None


class TestBoardClass:
    @pytest.mark.parametrize("board,cls", [
        ("ahsec", "class-12"),
        ("seba", "class-10"),
        ("degree", "sem-1"),
    ])
    def test_board_class(self, board, cls):
        assert derive_bot_cache_key(f"/{board}/{cls}") == f"_board_class_/{board}/{cls}"

    def test_unknown_board_class(self):
        assert derive_bot_cache_key("/foo/bar") is None


class TestSubjectAndTopic:
    def test_subject_three_segments(self):
        assert (
            derive_bot_cache_key("/ahsec/class-12/physics")
            == "_subj_/ahsec/class-12/physics"
        )

    def test_topic_four_segments_defaults_to_notes(self):
        assert (
            derive_bot_cache_key("/ahsec/class-12/physics/mechanics")
            == "ahsec/class-12/physics/mechanics/notes"
        )

    @pytest.mark.parametrize("ptype", [
        "notes", "mcqs", "important-questions", "examples", "definition",
    ])
    def test_typed_topic(self, ptype):
        path = f"/ahsec/class-12/physics/mechanics/{ptype}"
        assert (
            derive_bot_cache_key(path)
            == f"ahsec/class-12/physics/mechanics/{ptype}"
        )

    @pytest.mark.parametrize("bad", ["banana", "faq", "summary"])
    def test_invalid_page_type_returns_none(self, bad):
        assert (
            derive_bot_cache_key(f"/ahsec/class-12/physics/mechanics/{bad}")
            is None
        )


class TestLearnPyqSubject:
    def test_learn_route(self):
        assert derive_bot_cache_key("/learn/photosynthesis") == "_learn_/photosynthesis"

    def test_pyq_route(self):
        assert derive_bot_cache_key("/pyq/2024-physics") == "_pyq_/2024-physics"

    def test_subject_id_route(self):
        assert (
            derive_bot_cache_key("/subject/abc123")
            == "_subject_id_/abc123"
        )


class TestExcludedPaths:
    def test_paths_with_file_extension_skipped(self):
        assert derive_bot_cache_key("/file.css") is None
        assert derive_bot_cache_key("/image.png") is None
        assert derive_bot_cache_key("/data.json") is None

    def test_paths_too_long_return_none(self):
        assert derive_bot_cache_key("/a/b/c/d/e/f") is None
