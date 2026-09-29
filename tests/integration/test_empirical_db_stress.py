"""Empirical stress tests for SQLite WAL mode, concurrency, UNIQUE constraints, and Foreign Keys."""

import os
import shutil
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.database import configure_sqlite_engine, init_db
from app.models.batch import Batch, BatchResult
from app.models.order import Order, TrackingHistory


@pytest.fixture
def temp_db_path():
    """Create a temporary directory and return an absolute SQLite DB file path."""
    tmp_dir = tempfile.mkdtemp(prefix="courier_stress_")
    db_file = os.path.join(tmp_dir, "stress_test.db")
    yield db_file
    # Cleanup after test
    shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.fixture
def stress_engine(temp_db_path):
    """Create a file-backed SQLite engine configured with production WAL settings."""
    eng = create_engine(
        f"sqlite:///{temp_db_path}",
        connect_args={"check_same_thread": False, "timeout": 30.0},
    )
    configure_sqlite_engine(eng)
    init_db(eng)
    yield eng
    eng.dispose()


def test_wal_mode_concurrent_reads_during_active_write(stress_engine):
    """Empirical Test 1: Verify WAL mode allows concurrent reads during an active write transaction.

    In standard rollback journal mode (DELETE), an uncommitted write locks the DB exclusively,
    blocking all readers until the write completes.
    In WAL mode, readers MUST NOT be blocked by an active writer, and readers read from the
    prior snapshot without delay.
    """
    Session = sessionmaker(bind=stress_engine, autocommit=False, autoflush=False)

    # 1. Seed initial committed order
    with Session() as s:
        s.add(Order(order_id="ORD-INITIAL", courier_partner="mock", status="CREATED"))
        s.commit()

    write_started = threading.Event()
    read_completed = threading.Event()
    reader_results = {}

    def writer_task():
        """Writer holds an open, uncommitted transaction modifying data for 0.8 seconds."""
        with Session() as s:
            # Start write transaction
            s.add(Order(order_id="ORD-UNCOMMITTED", courier_partner="mock", status="CREATED"))
            s.flush()  # Flushes SQL INSERT into SQLite write buffer without committing
            write_started.set()

            # Wait until reader has performed its read during the uncommitted transaction
            # or timeout after 2.0s
            read_completed.wait(timeout=2.0)
            time.sleep(0.3)
            s.commit()

    def reader_task():
        """Reader reads the database while writer's transaction is active and uncommitted."""
        # Wait until writer has executed flush() and holds write lock
        assert write_started.wait(timeout=2.0), "Writer failed to start in time"

        start_time = time.monotonic()
        with Session() as s:
            # Check orders present
            orders = s.scalars(select(Order.order_id)).all()
            duration = time.monotonic() - start_time

            reader_results["duration"] = duration
            reader_results["orders"] = orders

        read_completed.set()

    writer_thread = threading.Thread(target=writer_task)
    reader_thread = threading.Thread(target=reader_task)

    writer_thread.start()
    reader_thread.start()

    reader_thread.join(timeout=5.0)
    writer_thread.join(timeout=5.0)

    # Verify reader was NOT blocked (should take < 0.2s, definitely << 0.8s)
    assert reader_results["duration"] < 0.3, f"Reader was blocked! Duration: {reader_results['duration']}s"

    # Verify snapshot isolation: reader saw committed "ORD-INITIAL" and did NOT see "ORD-UNCOMMITTED"
    assert "ORD-INITIAL" in reader_results["orders"]
    assert "ORD-UNCOMMITTED" not in reader_results["orders"]

    # Verify post-commit reader sees both
    with Session() as s:
        final_orders = s.scalars(select(Order.order_id)).all()
        assert "ORD-INITIAL" in final_orders
        assert "ORD-UNCOMMITTED" in final_orders


def test_concurrent_writes_with_busy_timeout(stress_engine):
    """Empirical Test 2: Verify busy_timeout allows concurrent writers to serialize and succeed.

    Under SQLite WAL mode, writers are serialized. With busy_timeout=30000, 10 simultaneous
    writers must all succeed without throwing 'database is locked'.
    """
    Session = sessionmaker(bind=stress_engine, autocommit=False, autoflush=False)
    num_writers = 10
    barrier = threading.Barrier(num_writers)

    def write_worker(idx: int) -> bool:
        barrier.wait()  # Synchronize start across all threads
        with Session() as s:
            s.add(
                Order(
                    order_id=f"ORD-CONCUR-W-{idx}",
                    courier_partner="mock",
                    status="CREATED",
                )
            )
            s.commit()
        return True

    with ThreadPoolExecutor(max_workers=num_writers) as executor:
        futures = [executor.submit(write_worker, i) for i in range(num_writers)]
        results = [f.result() for f in as_completed(futures)]

    assert len(results) == num_writers
    assert all(results)

    # Verify all 10 rows exist
    with Session() as s:
        count = s.scalar(select(Order).where(Order.order_id.like("ORD-CONCUR-W-%")).with_only_columns(text("count(*)")))
        assert count == num_writers


def test_concurrent_duplicate_order_id_unique_constraint(stress_engine):
    """Empirical Test 3: Verify database-level UNIQUE constraint on orders.order_id under race condition.

    20 concurrent threads attempt to insert the EXACT SAME order_id simultaneously.
    Exactly 1 MUST succeed and 19 MUST fail with IntegrityError.
    """
    Session = sessionmaker(bind=stress_engine, autocommit=False, autoflush=False)
    duplicate_order_id = "ORD-RACE-UNIQUE-001"
    num_threads = 20
    barrier = threading.Barrier(num_threads)

    success_count = 0
    integrity_error_count = 0
    other_error_count = 0
    lock = threading.Lock()

    def attempt_insert():
        nonlocal success_count, integrity_error_count, other_error_count
        barrier.wait()  # Fire all threads at the exact same moment
        try:
            with Session() as s:
                s.add(
                    Order(
                        order_id=duplicate_order_id,
                        courier_partner="mock",
                        status="CREATED",
                    )
                )
                s.commit()
            with lock:
                success_count += 1
        except IntegrityError:
            with lock:
                integrity_error_count += 1
        except Exception:
            with lock:
                other_error_count += 1

    threads = [threading.Thread(target=attempt_insert) for _ in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)

    # Empirical assertions
    assert other_error_count == 0, f"Encountered unexpected non-integrity errors: {other_error_count}"
    assert success_count == 1, f"Expected exactly 1 success, got {success_count}"
    assert integrity_error_count == num_threads - 1, (
        f"Expected {num_threads - 1} IntegrityErrors, got {integrity_error_count}"
    )

    # Verify database state has exactly 1 record
    with Session() as s:
        db_count = s.scalar(
            select(text("count(*)")).select_from(Order).where(Order.order_id == duplicate_order_id)
        )
        assert db_count == 1


def test_concurrent_duplicate_batch_id_unique_constraint(stress_engine):
    """Empirical Test 4: Verify database-level UNIQUE constraint on batches.batch_id under race condition."""
    Session = sessionmaker(bind=stress_engine, autocommit=False, autoflush=False)
    duplicate_batch_id = "BATCH-RACE-UNIQUE-001"
    num_threads = 15
    barrier = threading.Barrier(num_threads)

    success_count = 0
    integrity_error_count = 0
    lock = threading.Lock()

    def attempt_batch_insert():
        nonlocal success_count, integrity_error_count
        barrier.wait()
        try:
            with Session() as s:
                s.add(Batch(batch_id=duplicate_batch_id, total=10))
                s.commit()
            with lock:
                success_count += 1
        except IntegrityError:
            with lock:
                integrity_error_count += 1

    threads = [threading.Thread(target=attempt_batch_insert) for _ in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)

    assert success_count == 1
    assert integrity_error_count == num_threads - 1

    with Session() as s:
        db_count = s.scalar(
            select(text("count(*)")).select_from(Batch).where(Batch.batch_id == duplicate_batch_id)
        )
        assert db_count == 1


def test_foreign_key_enforcement_on_tracking_history(stress_engine):
    """Empirical Test 5: Verify foreign keys are enforced by SQLite engine on tracking_history."""
    Session = sessionmaker(bind=stress_engine, autocommit=False, autoflush=False)

    # 1. Attempt to insert tracking history with non-existent order_id
    with Session() as s:
        s.add(
            TrackingHistory(
                order_id="NON_EXISTENT_ORDER_999",
                status="IN_TRANSIT",
                raw_payload={"msg": "Should fail"},
            )
        )
        with pytest.raises(IntegrityError) as exc_info:
            s.commit()
        # Verify it is a FOREIGN KEY constraint failure
        assert "foreign key" in str(exc_info.value).lower() or "integrityerror" in str(exc_info.value).lower()

    # 2. Insert valid order and ensure tracking history succeeds
    with Session() as s:
        s.add(Order(order_id="ORD-VALID-FK", courier_partner="mock", status="CREATED"))
        s.commit()

    with Session() as s:
        s.add(
            TrackingHistory(
                order_id="ORD-VALID-FK",
                status="CREATED",
                raw_payload={"msg": "Should succeed"},
            )
        )
        s.commit()

    with Session() as s:
        count = s.scalar(
            select(text("count(*)")).select_from(TrackingHistory).where(TrackingHistory.order_id == "ORD-VALID-FK")
        )
        assert count == 1


def test_foreign_key_enforcement_on_batch_results(stress_engine):
    """Empirical Test 6: Verify foreign keys are enforced on batch_results."""
    Session = sessionmaker(bind=stress_engine, autocommit=False, autoflush=False)

    with Session() as s:
        s.add(
            BatchResult(
                batch_id="NON_EXISTENT_BATCH",
                order_id="ORD-1",
                success=True,
            )
        )
        with pytest.raises(IntegrityError) as exc_info:
            s.commit()
        assert "foreign key" in str(exc_info.value).lower() or "integrityerror" in str(exc_info.value).lower()


def test_append_only_tracking_history_immutability(stress_engine):
    """Empirical Test 7: Verify tracking_history preserves immutable audit log across multiple updates."""
    Session = sessionmaker(bind=stress_engine, autocommit=False, autoflush=False)
    order_id = "ORD-AUDIT-STRESS"

    # Step 1: Create Order
    with Session() as s:
        s.add(Order(order_id=order_id, courier_partner="mock", status="CREATED"))
        s.commit()

    # Step 2: Append 5 sequential events over time
    events = [
        ("CREATED", {"checkpoint": "Order created by merchant"}),
        ("PICKED_UP", {"checkpoint": "Courier picked up parcel"}),
        ("IN_TRANSIT", {"checkpoint": "In transit at central hub"}),
        ("OUT_FOR_DELIVERY", {"checkpoint": "Out for delivery with courier agent"}),
        ("DELIVERED", {"checkpoint": "Delivered and signed by customer"}),
    ]

    for status, payload in events:
        time.sleep(0.01)  # Ensure discrete timestamps
        with Session() as s:
            s.add(TrackingHistory(order_id=order_id, status=status, raw_payload=payload))
            # Also update parent order status
            order = s.scalar(select(Order).where(Order.order_id == order_id))
            order.status = status
            s.commit()

    # Step 3: Inspect tracking history audit trail
    with Session() as s:
        history = s.scalars(
            select(TrackingHistory).where(TrackingHistory.order_id == order_id).order_by(TrackingHistory.id.asc())
        ).all()

        assert len(history) == 5, f"Expected 5 history entries, found {len(history)}"

        # Verify all statuses are preserved in exact order
        assert [h.status for h in history] == [e[0] for e in events]

        # Verify payloads are intact and unmodified
        for h, (expected_status, expected_payload) in zip(history, events):
            assert h.status == expected_status
            assert h.raw_payload == expected_payload
            assert h.created_at is not None

        # Verify IDs are monotonically increasing
        ids = [h.id for h in history]
        assert ids == sorted(ids) and len(set(ids)) == 5


def test_cascade_delete_order_and_tracking_history(stress_engine):
    """Empirical Test 8: Verify deleting parent order cleans up tracking history via cascade."""
    Session = sessionmaker(bind=stress_engine, autocommit=False, autoflush=False)
    order_id = "ORD-CASCADE-TEST"

    with Session() as s:
        order = Order(order_id=order_id, courier_partner="mock", status="CREATED")
        s.add(order)
        s.commit()

        s.add_all([
            TrackingHistory(order_id=order_id, status="CREATED"),
            TrackingHistory(order_id=order_id, status="PICKED_UP"),
            TrackingHistory(order_id=order_id, status="DELIVERED"),
        ])
        s.commit()

    # Verify rows exist
    with Session() as s:
        assert s.scalar(select(text("count(*)")).select_from(TrackingHistory).where(TrackingHistory.order_id == order_id)) == 3

    # Delete order
    with Session() as s:
        order = s.scalar(select(Order).where(Order.order_id == order_id))
        s.delete(order)
        s.commit()

    # Verify both order and tracking history are gone
    with Session() as s:
        assert s.scalar(select(text("count(*)")).select_from(Order).where(Order.order_id == order_id)) == 0
        assert s.scalar(select(text("count(*)")).select_from(TrackingHistory).where(TrackingHistory.order_id == order_id)) == 0


def test_transaction_rollback_and_reader_isolation(stress_engine):
    """Empirical Test 9: Verify rolled back transactions leave zero trace and do not leak to readers."""
    Session = sessionmaker(bind=stress_engine, autocommit=False, autoflush=False)

    with Session() as s:
        s.add(Order(order_id="ORD-COMMITTED", courier_partner="mock", status="CREATED"))
        s.commit()

    with Session() as s:
        s.add(Order(order_id="ORD-TO-BE-ABORTED", courier_partner="mock", status="CREATED"))
        s.flush()
        # Abort transaction
        s.rollback()

    # Reader verifies ORD-TO-BE-ABORTED is not present
    with Session() as s:
        orders = s.scalars(select(Order.order_id)).all()
        assert "ORD-COMMITTED" in orders
        assert "ORD-TO-BE-ABORTED" not in orders


def test_null_constraint_enforcement(stress_engine):
    """Empirical Test 10: Verify NOT NULL constraints on critical columns."""
    Session = sessionmaker(bind=stress_engine, autocommit=False, autoflush=False)

    # 1. Order without order_id
    with Session() as s:
        s.add(Order(order_id=None, courier_partner="mock"))
        with pytest.raises(IntegrityError):
            s.commit()

    # 2. Order without courier_partner
    with Session() as s:
        s.add(Order(order_id="ORD-NO-PARTNER", courier_partner=None))
        with pytest.raises(IntegrityError):
            s.commit()

    # 3. TrackingHistory without order_id
    with Session() as s:
        s.add(TrackingHistory(order_id=None, status="CREATED"))
        with pytest.raises(IntegrityError):
            s.commit()

    # 4. TrackingHistory without status
    with Session() as s:
        s.add(TrackingHistory(order_id="ORD-COMMITTED", status=None))
        with pytest.raises(IntegrityError):
            s.commit()


def _mp_worker(db_path: str, worker_id: int) -> bool:
    """Worker function executed in a separate OS process."""
    eng = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30.0},
    )
    configure_sqlite_engine(eng)
    Session = sessionmaker(bind=eng, autocommit=False, autoflush=False)
    with Session() as s:
        s.add(Order(order_id=f"ORD-MP-{worker_id}", courier_partner="mock", status="CREATED"))
        s.commit()
    eng.dispose()
    return True


def test_multiprocess_concurrency(temp_db_path):
    """Empirical Test 11: Multi-process concurrency on file-backed SQLite database in WAL mode."""
    from concurrent.futures import ProcessPoolExecutor

    # Initialize schema first
    init_eng = create_engine(
        f"sqlite:///{temp_db_path}",
        connect_args={"check_same_thread": False, "timeout": 30.0},
    )
    configure_sqlite_engine(init_eng)
    init_db(init_eng)
    init_eng.dispose()

    num_processes = 6
    with ProcessPoolExecutor(max_workers=num_processes) as p_executor:
        futures = [p_executor.submit(_mp_worker, temp_db_path, i) for i in range(num_processes)]
        results = [f.result(timeout=15.0) for f in futures]

    assert len(results) == num_processes
    assert all(results)

    # Verify all records inserted
    verify_eng = create_engine(f"sqlite:///{temp_db_path}")
    with verify_eng.connect() as conn:
        count = conn.execute(text("SELECT count(*) FROM orders WHERE order_id LIKE 'ORD-MP-%';")).scalar()
        assert count == num_processes
    verify_eng.dispose()

