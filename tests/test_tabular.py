import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from tabular import (
    ImportError_,
    TableError,
    classify,
    convert,
    import_rows,
    profile_columns,
    read_text,
    sanitize_table_name,
)
from tabular.importer import create_sql, quote_ident
from tabular.cli import main
from tabular.report import render_json, render_text
from tabular.reader import detect_delimiter, split_header


class InferTests(unittest.TestCase):
    def test_integer_column(self):
        self.assertEqual(classify(["1", "-42", "+7"]), "INTEGER")

    def test_real_column(self):
        self.assertEqual(classify(["1.5", "-2e3", ".5", "5."]), "REAL")

    def test_int_and_float_mix_is_real(self):
        self.assertEqual(classify(["1", "2.5", "3"]), "REAL")

    def test_text_column(self):
        self.assertEqual(classify(["a1", "2"]), "TEXT")

    def test_empty_column_is_text(self):
        self.assertEqual(classify([]), "TEXT")

    def test_leading_zeros_stay_text(self):
        self.assertEqual(classify(["007", "8"]), "TEXT")
        self.assertEqual(classify(["+007"]), "TEXT")

    def test_zero_alone_is_int(self):
        self.assertEqual(classify(["0", "1"]), "INTEGER")

    def test_int_overflow_stays_text(self):
        self.assertEqual(classify([str(2**63), "1"]), "TEXT")
        self.assertEqual(classify([str(-(2**63))]), "INTEGER")

    def test_nan_inf_stay_text(self):
        self.assertEqual(classify(["nan"]), "TEXT")
        self.assertEqual(classify(["inf"]), "TEXT")
        self.assertEqual(classify(["-inf", "1.0"]), "TEXT")

    def test_surrounding_whitespace_stripped_for_numbers(self):
        self.assertEqual(classify([" 1 ", "2"]), "INTEGER")
        self.assertEqual(convert(" 2.5 ", "REAL"), 2.5)

    def test_convert(self):
        self.assertEqual(convert("42", "INTEGER"), 42)
        self.assertEqual(convert("4.25", "REAL"), 4.25)
        self.assertEqual(convert("abc", "TEXT"), "abc")
        self.assertIsNone(convert("", "INTEGER"))


class ReaderTests(unittest.TestCase):
    def test_delimiter_by_extension(self):
        self.assertEqual(detect_delimiter("a\tb", "x.tsv", None), "\t")
        self.assertEqual(detect_delimiter("a,b", "x.csv", None), ",")

    def test_delimiter_override(self):
        self.assertEqual(detect_delimiter("a;b", "x.csv", ";"), ";")
        with self.assertRaises(TableError):
            detect_delimiter("a;b", "x.csv", ";;")

    def test_delimiter_sniff(self):
        self.assertEqual(detect_delimiter("a;b;c\n1;2;3\n", "x.dat", None), ";")

    def test_header_and_rows(self):
        header, rows = read_text("id,name\n1,ada\n2,lin\n", "x.csv", ",", True)
        self.assertEqual(header, ["id", "name"])
        self.assertEqual(rows, [["1", "ada"], ["2", "lin"]])

    def test_no_header_generates_names(self):
        header, rows = read_text("1,ada\n", "x.csv", ",", False)
        self.assertEqual(header, ["col1", "col2"])
        self.assertEqual(rows, [["1", "ada"]])

    def test_duplicate_and_empty_header_names(self):
        header, rows = split_header([["id", "id", ""], ["1", "2", "3"]], True)
        self.assertEqual(header, ["id", "id_2", "col3"])
        self.assertEqual(rows, [["1", "2", "3"]])

    def test_quoted_fields(self):
        text = 'name,note\n"Smith, John","said ""hi"""\n'
        header, rows = read_text(text, "x.csv", ",", True)
        self.assertEqual(header, ["name", "note"])
        self.assertEqual(rows, [["Smith, John", 'said "hi"']])

    def test_quoted_newline_kept(self):
        text = 'name,note\nada,"line1\nline2"\n'
        header, rows = read_text(text, "x.csv", ",", True)
        self.assertEqual(rows, [["ada", "line1\nline2"]])

    def test_empty_input_rejected(self):
        with self.assertRaises(TableError):
            read_text("", "x.csv", ",", True)
        with self.assertRaises(TableError):
            read_text("\n\n", "x.csv", ",", True)


class ImporterTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.header = ["id", "name", "score"]
        self.rows = [
            ["1", "ada", "9.5"],
            ["2", "lin", ""],
            ["3", "bob", "7"],
        ]
        self.profiles = profile_columns(self.header, self.rows)

    def test_inferred_schema(self):
        self.assertEqual([p.type for p in self.profiles], ["INTEGER", "TEXT", "REAL"])
        self.assertEqual(create_sql("t", self.profiles, None),
                         'CREATE TABLE "t" ("id" INTEGER, "name" TEXT, "score" REAL)')

    def test_roundtrip_types(self):
        import_rows(self.conn, "t", self.profiles, self.rows)
        got = self.conn.execute('SELECT * FROM "t" ORDER BY "id"').fetchall()
        self.assertEqual(got, [(1, "ada", 9.5), (2, "lin", None), (3, "bob", 7.0)])

    def test_empty_policy_null_default(self):
        import_rows(self.conn, "t", self.profiles, self.rows)
        n = self.conn.execute('SELECT COUNT(*) FROM "t" WHERE "score" IS NULL').fetchone()[0]
        self.assertEqual(n, 1)

    def test_empty_policy_text(self):
        import_rows(self.conn, "t", self.profiles, self.rows, empty_policy="text")
        got = self.conn.execute('SELECT "score" FROM "t" WHERE "id"=2').fetchone()
        self.assertEqual(got, ("",))

    def test_empty_policy_zero(self):
        import_rows(self.conn, "t", self.profiles, self.rows, empty_policy="zero")
        got = self.conn.execute('SELECT "score" FROM "t" WHERE "id"=2').fetchone()
        self.assertEqual(got, (0.0,))

    def test_primary_key_and_duplicate(self):
        import_rows(self.conn, "t", self.profiles, self.rows, pk="id")
        with self.assertRaises(ImportError_):
            import_rows(
                self.conn,
                "t",
                self.profiles,
                [["1", "dupe", "1.0"]],
                pk="id",
                if_exists="append",
            )

    def test_pk_column_missing(self):
        with self.assertRaises(ImportError_):
            import_rows(self.conn, "t", self.profiles, self.rows, pk="nope")

    def test_if_exists_fail(self):
        import_rows(self.conn, "t", self.profiles, self.rows)
        with self.assertRaises(ImportError_):
            import_rows(self.conn, "t", self.profiles, self.rows)

    def test_if_exists_replace(self):
        import_rows(self.conn, "t", self.profiles, self.rows)
        import_rows(self.conn, "t", self.profiles, self.rows, if_exists="replace")
        n = self.conn.execute('SELECT COUNT(*) FROM "t"').fetchone()[0]
        self.assertEqual(n, 3)

    def test_if_exists_append_and_mismatch(self):
        import_rows(self.conn, "t", self.profiles, self.rows)
        import_rows(
            self.conn,
            "t",
            self.profiles,
            [["4", "zed", "1.0"]],
            if_exists="append",
        )
        n = self.conn.execute('SELECT COUNT(*) FROM "t"').fetchone()[0]
        self.assertEqual(n, 4)
        other = profile_columns(["a", "b"], [["1", "2"]])
        with self.assertRaises(ImportError_):
            import_rows(self.conn, "t", other, [["1", "2"]], if_exists="append")

    def test_ragged_row_padded_with_empty(self):
        import_rows(self.conn, "t", self.profiles, [["9", "short"]])
        got = self.conn.execute('SELECT * FROM "t"').fetchall()
        self.assertEqual(got, [(9, "short", None)])

    def test_identifier_quoting(self):
        self.assertEqual(quote_ident('we"ird'), '"we""ird"')
        header = ['we"ird']
        profiles = profile_columns(header, [["x"]])
        import_rows(self.conn, "t", profiles, [["x"]])
        got = self.conn.execute('SELECT "we""ird" FROM "t"').fetchall()
        self.assertEqual(got, [("x",)])

    def test_bad_policy_rejected(self):
        with self.assertRaises(ImportError_):
            import_rows(self.conn, "t", self.profiles, self.rows, empty_policy="drop")


class NameTests(unittest.TestCase):
    def test_sanitize(self):
        self.assertEqual(sanitize_table_name("my data-2024.csv"), "my_data_2024_csv")
        self.assertEqual(sanitize_table_name("2024report"), "_2024report")
        self.assertEqual(sanitize_table_name("---"), "table")
        self.assertEqual(sanitize_table_name("simple"), "simple")


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.profiles = profile_columns(
            ["id", "name", "score"],
            [["1", "ada", "9.5"], ["2", "lin", ""], ["3", "bob", "7"]],
        )

    def test_text_layout(self):
        text = render_text("t", self.profiles, 3)
        self.assertTrue(text.startswith("table t: 3 columns, 3 rows\n"))
        self.assertIn("column  type     nulls  distinct  min  max", text)
        self.assertIn("id      INTEGER      0         3    1    3", text)
        self.assertIn("name    TEXT         0         3    -    -", text)
        self.assertIn("score   REAL         1         2    7  9.5", text)

    def test_json_layout(self):
        doc = json.loads(render_json("t", self.profiles, 3))
        self.assertEqual(doc["table"], "t")
        self.assertEqual(doc["rows"], 3)
        self.assertEqual(doc["columns"][0], {
            "name": "id", "type": "INTEGER", "nulls": 0, "distinct": 3,
            "min": "1", "max": "3", "samples": ["1", "2", "3"],
        })
        self.assertEqual(doc["columns"][2]["nulls"], 1)
        self.assertEqual(doc["columns"][2]["min"], "7")
        self.assertEqual(doc["columns"][2]["max"], "9.5")


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.csv = self.dir / "people.csv"
        self.csv.write_text(
            "id,name,score\n1,ada,9.5\n2,lin,\n3,bob,7\n", encoding="utf-8"
        )
        self.db = self.dir / "out.sqlite"

    def tearDown(self):
        self.tmp.cleanup()

    def test_import_and_verify(self):
        rc = main(["import", str(self.csv), "--db", str(self.db), "--table", "people"])
        self.assertEqual(rc, 0)
        conn = sqlite3.connect(self.db)
        rows = conn.execute("SELECT * FROM people ORDER BY id").fetchall()
        conn.close()
        self.assertEqual(rows, [(1, "ada", 9.5), (2, "lin", None), (3, "bob", 7.0)])

    def test_import_default_table_name(self):
        rc = main(["import", str(self.csv), "--db", str(self.db)])
        self.assertEqual(rc, 0)
        conn = sqlite3.connect(self.db)
        n = conn.execute("SELECT COUNT(*) FROM people").fetchone()[0]
        conn.close()
        self.assertEqual(n, 3)

    def test_import_if_exists_fail_errors(self):
        main(["import", str(self.csv), "--db", str(self.db)])
        rc = main(["import", str(self.csv), "--db", str(self.db)])
        self.assertEqual(rc, 1)

    def test_import_pk_duplicate(self):
        rc = main([
            "import", str(self.csv), "--db", str(self.db), "--table", "t", "--pk", "id",
        ])
        self.assertEqual(rc, 0)
        dup = self.dir / "dup.csv"
        dup.write_text("id,name,score\n1,x,1\n", encoding="utf-8")
        rc = main([
            "import", str(dup), "--db", str(self.db), "--table", "t",
            "--pk", "id", "--if-exists", "append",
        ])
        self.assertEqual(rc, 1)

    def test_schema_text_and_json(self):
        rc = main(["schema", str(self.csv)])
        self.assertEqual(rc, 0)
        rc = main(["schema", str(self.csv), "--json"])
        self.assertEqual(rc, 0)

    def test_schema_captures_stdout(self):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            main(["schema", str(self.csv), "--json"])
        doc = json.loads(buf.getvalue())
        self.assertEqual(doc["table"], "people")
        self.assertEqual(doc["rows"], 3)

    def test_missing_file_exit_1(self):
        rc = main(["schema", str(self.dir / "nope.csv")])
        self.assertEqual(rc, 1)

    def test_usage_errors_exit_2(self):
        with self.assertRaises(SystemExit) as cm:
            main(["bogus-subcommand"])
        self.assertEqual(cm.exception.code, 2)
        with self.assertRaises(SystemExit) as cm:
            main(["import", str(self.csv)])  # missing --db
        self.assertEqual(cm.exception.code, 2)
        with self.assertRaises(SystemExit) as cm:
            main(["import", str(self.csv), "--db", str(self.db), "--empty", "drop"])
        self.assertEqual(cm.exception.code, 2)

    def test_version_exit_0(self):
        with self.assertRaises(SystemExit) as cm:
            main(["--version"])
        self.assertEqual(cm.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
