"""Unit tests for SQLAlchemy models, constraints, and SQLite configuration."""

import os
import tempfile
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError

from app.database import configure_sqlite_engine
from app.models.batch import Batch, BatchResult
from app.models.order import Order, TrackingHistory


def test_sqlite_wal_mode_and_pragmas():
    """Verify that file-backed SQLite databases enable WAL mode and busy timeout."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_db:
        tmp_path = tmp_db.name

    try:
        file_engine = create_engine(
            f"sqlite:///{tmp_path}",
            connect_args={"check_same_thread": False, "timeout": 30.0},
        )
        configure_sqlite_engine(file_engine)

        with file_engine.connect() as conn:
            # Check journal_mode
            res_journal = conn.execute(text("PRAGMA journal_mode;")).scalar()
            assert str(res_journal).lower() == "wal", f"Expected WAL mode, got {res_journal}"

            # Check busy_timeout
            res_timeout = conn.execute(text("PRAGMA busy_timeout;")).scalar()
            assert res_timeout == 30000, f"Expected busy_timeout 30000, got {res_timeout}"

            # Check foreign_keys
            res_fk = conn.execute(text("PRAGMA foreign_keys;")).scalar()
            assert res_fk == 1, f"Expected foreign_keys ON (1), got {res_fk}"

        file_engine.dispose()
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        # WAL mode creates -wal and -shm temporary files
        if os.path.exists(f"{tmp_path}-wal"):
            os.remove(f"{tmp_path}-wal")
        if os.path.exists(f"{tmp_path}-shm"):
            os.remove(f"{tmp_path}-shm")


def test_order_creation_and_defaults(db_session):
    """Verify Order creation with default values and payload storage."""
    order = Order(
        order_id="ORD-TEST-001",
        courier_partner="mock",
        request_payload={"customer": {"name": "Alice"}},
    )
    db_session.add(order)
    db_session.commit()
    db_session.refresh(order)

    assert order.id is not None
    assert order.order_id == "ORD-TEST-001"
    assert order.courier_partner == "mock"
    assert order.status == "CREATED"
    assert order.created_at is not None
    assert order.updated_at is not None
    assert order.request_payload == {"customer": {"name": "Alice"}}
    assert order.response_payload is None


def test_order_id_unique_constraint(db_session):
    """Verify that duplicate order_id violates database UNIQUE constraint."""
    order1 = Order(
        order_id="ORD-DUP-001",
        courier_partner="mock",
    )
    db_session.add(order1)
    db_session.commit()

    order2 = Order(
        order_id="ORD-DUP-001",
        courier_partner="urbanebolt",
    )
    db_session.add(order2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_tracking_history_append_only(db_session):
    """Verify TrackingHistory allows multiple entries per order without overwriting."""
    order = Order(
        order_id="ORD-TRACK-001",
        courier_partner="mock",
        status="CREATED",
    )
    db_session.add(order)
    db_session.commit()

    # Append first event
    evt1 = TrackingHistory(
        order_id=order.order_id,
        status="CREATED",
        raw_payload={"event": "ORDER_CREATED"},
    )
    db_session.add(evt1)
    db_session.commit()

    # Append second event
    evt2 = TrackingHistory(
        order_id=order.order_id,
        status="PICKED_UP",
        raw_payload={"event": "PICKED_UP_AT_HUB"},
    )
    db_session.add(evt2)
    db_session.commit()

    # Append third event
    evt3 = TrackingHistory(
        order_id=order.order_id,
        status="DELIVERED",
        raw_payload={"event": "DELIVERED_TO_CONSIGNEE"},
    )
    db_session.add(evt3)
    db_session.commit()

    # Fetch history
    history = db_session.scalars(
        select(TrackingHistory).where(TrackingHistory.order_id == order.order_id).order_by(TrackingHistory.id)
    ).all()

    assert len(history) == 3
    assert [h.status for h in history] == ["CREATED", "PICKED_UP", "DELIVERED"]
    assert history[0].raw_payload == {"event": "ORDER_CREATED"}
    assert history[2].raw_payload == {"event": "DELIVERED_TO_CONSIGNEE"}


def test_batch_and_batch_results(db_session):
    """Verify Batch and BatchResult entity relationships and status tracking."""
    batch = Batch(
        batch_id="BATCH-001",
        status="PROCESSING",
        total=2,
        successful=0,
        failed=0,
    )
    db_session.add(batch)
    db_session.commit()

    res1 = BatchResult(
        batch_id=batch.batch_id,
        order_id="ORD-001",
        success=True,
    )
    res2 = BatchResult(
        batch_id=batch.batch_id,
        order_id="ORD-002",
        success=False,
        error_code="COURIER_TIMEOUT",
        error_message="Downstream timeout",
    )
    db_session.add_all([res1, res2])

    batch.successful = 1
    batch.failed = 1
    batch.status = "COMPLETED"
    db_session.commit()
    db_session.refresh(batch)

    assert batch.status == "COMPLETED"
    assert batch.successful == 1
    assert batch.failed == 1
    assert len(batch.results) == 2
    assert batch.results[0].order_id == "ORD-001"
    assert batch.results[0].success is True
    assert batch.results[1].order_id == "ORD-002"
    assert batch.results[1].success is False
    assert batch.results[1].error_code == "COURIER_TIMEOUT"


def test_batch_id_unique_constraint(db_session):
    """Verify that duplicate batch_id violates database UNIQUE constraint."""
    batch1 = Batch(batch_id="BATCH-DUP-001", total=1)
    db_session.add(batch1)
    db_session.commit()

    batch2 = Batch(batch_id="BATCH-DUP-001", total=2)
    db_session.add(batch2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_get_db_generator():
    """Verify get_db session dependency lifecycle."""
    from app.database import get_db

    gen = get_db()
    session = next(gen)
    assert session is not None
    # Close generator
    try:
        next(gen)
    except StopIteration:
        pass


def test_init_db():
    """Verify init_db creates all tables on target engine."""
    from app.database import init_db

    mem_engine = create_engine("sqlite:///:memory:")
    init_db(target_engine=mem_engine)
    # Check that orders table was created
    with mem_engine.connect() as conn:
        res = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='orders';")).scalar()
        assert res == "orders"
    mem_engine.dispose()

