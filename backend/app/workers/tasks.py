from __future__ import annotations

from datetime import datetime

from celery import Task

from app.celery_app import celery_app
from app.db.session import SessionLocal
from app.models.entities import BatchTask, ProcessingBatch, SourceFile
from app.services.extractor import parse_pdf

TRANSIENT_ERROR_TOKENS = (
    "timeout",
    "timed out",
    "temporarily unavailable",
    "connection reset",
    "connection refused",
    "server closed the connection",
    "could not connect",
    "lost connection",
    "deadlock",
)


def _is_transient_task_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(token in message for token in TRANSIENT_ERROR_TOKENS)


def _refresh_batch_status(batch: ProcessingBatch) -> None:
    if batch.processed_files + batch.failed_files < batch.total_files:
        batch.status = "processing"
        if batch.started_at is None:
            batch.started_at = datetime.utcnow()
        return

    batch.completed_at = datetime.utcnow()
    if batch.failed_files == 0:
        batch.status = "completed"
    elif batch.processed_files == 0:
        batch.status = "failed"
    else:
        batch.status = "completed_with_errors"


@celery_app.task(bind=True, name="app.workers.tasks.process_source_file")
def process_source_file(self: Task, batch_id: str, source_file_id: int) -> dict[str, str]:
    db = SessionLocal()
    try:
        batch = db.query(ProcessingBatch).filter(ProcessingBatch.id == batch_id).first()
        task_row = db.query(BatchTask).filter(BatchTask.task_id == self.request.id).first()
        source_file = db.query(SourceFile).filter(SourceFile.id == source_file_id).first()

        if batch is None or source_file is None:
            return {"status": "skipped"}
        if task_row is None:
            task_row = BatchTask(
                batch_id=batch.id,
                source_file_id=source_file.id,
                task_id=str(self.request.id),
                status="queued",
                error_message=None,
            )
            db.add(task_row)
            db.commit()

        task_row.status = "processing"
        task_row.started_at = datetime.utcnow()
        source_file.status = "processing"
        if batch.started_at is None:
            batch.started_at = datetime.utcnow()
            batch.status = "processing"
        db.add(task_row)
        db.add(source_file)
        db.add(batch)
        db.commit()

        try:
            parse_pdf(db, source_file)
            task_row.status = "completed"
            source_file.status = "processed"
            batch.processed_files += 1
        except Exception as exc:
            db.rollback()
            source_file = db.query(SourceFile).filter(SourceFile.id == source_file_id).first()
            batch = db.query(ProcessingBatch).filter(ProcessingBatch.id == batch_id).first()
            task_row = db.query(BatchTask).filter(BatchTask.task_id == self.request.id).first()

            current_retry = int(self.request.retries or 0)
            max_retry_attempts = 2
            should_retry = current_retry < max_retry_attempts and _is_transient_task_error(exc)
            if should_retry:
                if source_file is not None:
                    source_file.status = "queued"
                    db.add(source_file)
                if task_row is not None:
                    task_row.status = "retrying"
                    task_row.error_message = f"Reintentando por error transitorio: {str(exc)[:160]}"
                    db.add(task_row)
                if batch is not None:
                    batch.status = "processing"
                    db.add(batch)
                db.commit()
                raise self.retry(exc=exc, countdown=2 ** (current_retry + 1), max_retries=max_retry_attempts)

            if source_file is not None:
                source_file.status = "failed"
                db.add(source_file)
            if task_row is not None:
                task_row.status = "failed"
                task_row.error_message = str(exc)[:2000]
                task_row.completed_at = datetime.utcnow()
                db.add(task_row)
            if batch is not None:
                batch.failed_files += 1
                _refresh_batch_status(batch)
                db.add(batch)
            db.commit()
            return {"status": "failed"}

        task_row.completed_at = datetime.utcnow()
        db.add(task_row)
        db.add(source_file)

        _refresh_batch_status(batch)
        db.add(batch)
        db.commit()
        return {"status": "completed"}
    finally:
        db.close()
