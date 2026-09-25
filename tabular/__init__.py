"""tabular — CSV/TSV to SQLite importer with type inference."""

from .infer import ColumnProfile, classify, convert, profile_columns
from .reader import TableError, read_text
from .importer import ImportError_, import_rows, sanitize_table_name

__version__ = "1.0.0"

__all__ = [
    "ColumnProfile",
    "ImportError_",
    "TableError",
    "classify",
    "convert",
    "import_rows",
    "profile_columns",
    "read_text",
    "sanitize_table_name",
    "__version__",
]
