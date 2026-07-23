"""Small data-loading helpers for S1 views and CLI entry points."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from common.schema import Incident, read_csv

REPO_ROOT = Path(__file__).resolve().parents[1]
INCIDENTS_PATH = REPO_ROOT / "data" / "incidents.csv"
KB_DIR = REPO_ROOT / "data" / "kb_articles"


@dataclass(frozen=True)
class KbArticle:
    article_id: str
    title: str
    text: str
    path: Path


def load_incidents(path: Path = INCIDENTS_PATH) -> list[Incident]:
    return read_csv(path)


def load_kb_articles(kb_dir: Path = KB_DIR) -> list[KbArticle]:
    articles: list[KbArticle] = []
    for path in sorted(kb_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        first_line = text.splitlines()[0] if text.splitlines() else path.stem
        title = first_line.lstrip("# ").strip()
        article_id = path.stem.split("_", maxsplit=1)[0]
        articles.append(KbArticle(article_id=article_id, title=title, text=text, path=path))
    return articles
