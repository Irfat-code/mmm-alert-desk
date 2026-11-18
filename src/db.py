"""Small database wrapper.

Uses DuckDB when it is installed. Falls back to SQLite (built into Python)
so the project still runs without extra installs. All SQL in sql/ is written
to work in both.
"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "alert_desk"


class Database:
    def __init__(self, path=DEFAULT_DB):
        path = Path(path)
        try:
            import duckdb

            self.engine = "duckdb"
            self.path = path.with_suffix(".duckdb")
            self.con = duckdb.connect(str(self.path))
        except ImportError:
            import sqlite3

            self.engine = "sqlite"
            self.path = path.with_suffix(".sqlite")
            self.con = sqlite3.connect(self.path)

    @staticmethod
    def remove(path=DEFAULT_DB):
        """Delete any existing database file so a rebuild starts clean."""
        for suffix in (".duckdb", ".duckdb.wal", ".sqlite"):
            Path(path).with_suffix(suffix).unlink(missing_ok=True)

    def run_script(self, sql_path):
        sql = Path(sql_path).read_text()
        if self.engine == "sqlite":
            self.con.executescript(sql)
            return
        # Strip comment lines, then run one statement at a time.
        lines = [ln for ln in sql.splitlines() if not ln.strip().startswith("--")]
        for statement in "\n".join(lines).split(";"):
            if statement.strip():
                self.con.execute(statement)

    def query(self, sql):
        if self.engine == "duckdb":
            return self.con.execute(sql).df()
        return pd.read_sql_query(sql, self.con)

    def query_file(self, sql_path):
        return self.query(Path(sql_path).read_text())

    def write(self, table, df):
        """Append a DataFrame to an existing table (columns matched by name)."""
        cols = ", ".join(df.columns)
        if self.engine == "duckdb":
            self.con.register("_incoming", df)
            self.con.execute(f"INSERT INTO {table} ({cols}) SELECT {cols} FROM _incoming")
            self.con.unregister("_incoming")
        else:
            out = df.copy()
            for c in out.columns:
                if pd.api.types.is_datetime64_any_dtype(out[c]):
                    out[c] = out[c].dt.strftime("%Y-%m-%d")
            out.to_sql(table, self.con, if_exists="append", index=False)
            self.con.commit()

    def close(self):
        self.con.close()
