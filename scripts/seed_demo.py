#!/usr/bin/env python3
"""Seed the database + FAISS indexes for the demo.

What it does
  1. creates all tables (SQLite dev DB or the PostgreSQL from docker-compose);
  2. bootstraps the admin account (from env) and demo users;
  3. ingests data/documents/* (PDF, DOCX, TXT, MD, CSV, JSON, LOG, XLSX)
     -> parse -> metadata -> chunks -> embeddings -> FAISS;
  4. ingests data/incidents/* (JSON + CSV) into the historical incident store
     used by Similar Incident Discovery;
  5. reindexes the vector stores and prints a summary.

Usage (run from backend/, a virtualenv is optional - any Python >=3.11 with
backend/requirements.txt installed works):
    python ../scripts/seed_demo.py            # incremental
    python ../scripts/seed_demo.py --fresh    # wipe DB + indexes first
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.core.config import get_settings  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fresh", action="store_true", help="delete DB + vector store files before seeding")
    parser.add_argument("--users-only", action="store_true", help="only ensure accounts exist")
    args = parser.parse_args()

    s = get_settings()

    if args.fresh:
        db_path = s.sqlite_path
        if db_path and db_path.exists():
            db_path.unlink()
            print(f"removed {db_path}")
        if s.vectorstore_dir.exists():
            shutil.rmtree(s.vectorstore_dir)
            print(f"removed {s.vectorstore_dir}")

    from app.core.database import Base, db_session, engine
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=engine)

    from app.core.security import ROLE_ADMIN, ROLE_USER, hash_password
    from app.models.user import User
    from app.services import auth_service, document_service, rag_service
    from sqlalchemy import select

    with db_session() as db:
        auth_service.ensure_roles(db)
        auth_service.bootstrap_admin(db)
        auth_service.ensure_demo_user(db)

        demo = [
            ("Priya Sharma", "priya@aira.test", ROLE_USER),
            ("Arjun Mehta", "arjun@aira.test", ROLE_USER),
            ("Riya Patel", "riya@aira.test", ROLE_ADMIN),
        ]
        pw = "Engineer@123"
        for name, email, role in demo:
            if db.scalar(select(User).where(User.email == email)) is None:
                db.add(User(name=name, email=email, password_hash=hash_password(pw), role=role))
                print(f"created {role:5s} user {email} (password {pw!r})")
        db.commit()

        if args.users_only:
            return

        report = document_service.ingest_directory(db, s.documents_dir)
        print(f"documents: stored={report.stored} skipped={len(report.skipped)} errors={len(report.errors)}")
        for e in report.errors[:10]:
            print("  !", e)

        # structured incident history (JSON + CSV) into the similar-incident store
        hist_report = document_service.ingest_directory(db, s.incidents_data_dir, only_incidents=True)
        print(f"incident history: files={hist_report.stored} incidents={hist_report.incidents} errors={len(hist_report.errors)}")

        stats = rag_service.sync_stores(db)
        print("vector stores:", stats)
        for name, store in (("documents", rag_service.get_runtime().document_store), ("incidents", rag_service.get_runtime().incident_store)):
            print(f"  {name}: {len(store.records)} vectors via {store.backend} ({store.embeddings.status()})")

        from sqlalchemy import func
        from app.models.conversation import Incident
        from app.models.document import Document

        print("DB: documents =", db.scalar(select(func.count(Document.id))),
              "| incidents =", db.scalar(select(func.count(Incident.id))))


if __name__ == "__main__":
    main()
