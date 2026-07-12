from __future__ import annotations

import re


def parse_makefile_db_sql_files(makefile_text: str) -> list[str]:
    match = re.search(r"^override DB_SQL_FILES := (.+)$", makefile_text, re.M)
    assert match is not None
    return match.group(1).split()
