from __future__ import annotations

import fnmatch
from dataclasses import dataclass


@dataclass(frozen=True)
class FileOverrideRule:
    path: str
    wrong: str
    right: str
    note: str = ""

    def matches(self, relative_path: str) -> bool:
        return fnmatch.fnmatch(relative_path, self.path)


@dataclass(frozen=True)
class CorrectionContext:
    dict_topic: str
    source_relative_path: str
    source_under_saju_raw: bool
    term_stopwords: frozenset[str]
