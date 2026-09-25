# tabular

**CSV/TSV → SQLite importer in pure Python — conservative type inference, empty-value policies, schema report. Zero dependencies.**

[![CI](https://github.com/efealtiparmakoglu/tabular/actions/workflows/ci.yml/badge.svg)](https://github.com/efealtiparmakoglu/tabular/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org)

```
$ tabular schema employees.csv
table employees: 5 columns, 4 rows
column      type     nulls  distinct  min  max
----------------------------------------------
id          INTEGER      0         4    1    4
name        TEXT         0         4    -    -
department  TEXT         0         2    -    -
salary      REAL         1         3  78000  92000
hired       TEXT         0         4    -    -

$ tabular import employees.csv --db company.db --pk id
imported 4 rows into employees (company.db)
```

Reads the file once, infers each column's SQLite type from the data, creates
the table and loads the rows inside one transaction.

## Why tabular

- **Conservative inference.** INTEGER / REAL / TEXT only — and values that
  would change on conversion keep the column TEXT: `007` stays `007` (zip
  codes, phone numbers), integers beyond 64-bit stay text, `nan`/`inf`
  never sneak into REAL columns.
- **Empty-value policies.** `--empty null` (default), `--empty text` or
  `--empty zero` decide what blank cells become, per policy not per whim.
- **Schema report.** Per-column type, null count, distinct count and numeric
  min/max — as text or `--json` — before you commit to the import.
- **Table lifecycle.** `--if-exists fail|replace|append`; append validates
  column compatibility first. `--pk` gives you a real primary key, so
  duplicate imports fail loudly instead of silently doubling rows.
- **Real-world files.** TSV by extension, delimiter sniffing for the rest,
  BOM stripping, quoted fields with embedded commas/newlines, ragged rows,
  duplicate or missing header names.
- **Zero dependencies.** Standard library only — `csv`, `sqlite3`, `argparse`.

## Usage

```sh
tabular import data.csv --db app.db                    # table name from file
tabular import data.tsv --db app.db --table metrics    # TSV by extension
tabular import raw.csv --db app.db --pk id --empty zero
tabular import new.csv --db app.db --if-exists append  # column-checked append
tabular schema data.csv --json                         # report only
cat data.csv | tabular import - --db app.db            # stdin
```

Exit codes: 0 ok, 1 runtime error (missing file, duplicate key, column
mismatch), 2 usage error.

## Development

```sh
python3 -m unittest discover -s tests
```

45 tests cover the classifier (leading zeros, 64-bit overflow, nan/inf,
whitespace), the reader (sniffing, quoting, header dedup), the importer
(round-trip types, empty policies, PK duplicates, if-exists modes,
identifier quoting), the reports, and CLI exit codes end-to-end.

## License

MIT — see [LICENSE](LICENSE).
