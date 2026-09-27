"""Tests for the idempotent schema migration runner (DB-independent)."""

from arthaai.db.migrate import schema_statements, split_statements


class TestSplitStatements:
    def test_two_simple_statements(self):
        assert split_statements("SELECT 1; SELECT 2;") == ["SELECT 1", "SELECT 2"]

    def test_trailing_statement_without_semicolon(self):
        assert split_statements("SELECT 1; SELECT 2") == ["SELECT 1", "SELECT 2"]

    def test_semicolon_inside_single_quoted_string(self):
        assert split_statements("INSERT INTO t VALUES ('a;b');") == [
            "INSERT INTO t VALUES ('a;b')"
        ]

    def test_doubled_quote_is_not_a_terminator(self):
        assert split_statements("SELECT 'it''s; fine';") == ["SELECT 'it''s; fine'"]

    def test_line_comment_is_stripped_and_does_not_split(self):
        stmts = split_statements("SELECT 1 -- a; comment\n; SELECT 2;")
        assert stmts == ["SELECT 1", "SELECT 2"]

    def test_block_comment_is_stripped_and_does_not_split(self):
        stmts = split_statements("SELECT 1 /* a; comment */; SELECT 2;")
        assert stmts == ["SELECT 1", "SELECT 2"]

    def test_dollar_quoted_body_keeps_semicolons(self):
        sql = "CREATE FUNCTION f() RETURNS int AS $$ BEGIN; RETURN 1; END; $$ LANGUAGE plpgsql;"
        stmts = split_statements(sql)
        assert len(stmts) == 1
        assert "BEGIN; RETURN 1; END;" in stmts[0]

    def test_empty_input(self):
        assert split_statements("") == []
        assert split_statements("   \n  ") == []

    def test_comment_only_input(self):
        assert split_statements("-- just a comment\n") == []


class TestSchemaStatements:
    def test_schema_contains_promotion_and_provider_migrations(self):
        joined = "\n".join(schema_statements())
        assert "signal_promotion" in joined
        assert "preferred_provider" in joined
        assert "ADD COLUMN IF NOT EXISTS" in joined

    def test_every_statement_is_non_empty(self):
        assert all(s.strip() for s in schema_statements())
