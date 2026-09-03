"""
Dédoublonnage.
Compare chaque entrée collectée au hash déjà présent en base pour éviter
de retraiter/republier deux fois la même information.
"""
from typing import List, Dict

from sqlalchemy.orm import Session

from app.database import Article


def filter_new_entries(session: Session, entries: List[Dict]) -> List[Dict]:
    """Retourne uniquement les entrées dont le content_hash n'existe pas déjà en base."""
    if not entries:
        return []

    existing_hashes = {
        h[0] for h in session.query(Article.content_hash).filter(
            Article.content_hash.in_([e["content_hash"] for e in entries])
        ).all()
    }

    new_entries = [e for e in entries if e["content_hash"] not in existing_hashes]
    return new_entries
