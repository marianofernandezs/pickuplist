from __future__ import annotations

from datetime import datetime

from celery import Task

from app.celery_app import celery_app
from app.db.session import SessionLocal
from app.models.entities import BatchTask, ProcessingBatch, SourceFile
from app.services.extractor import parse_pdf


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

        if batch is None or task_row is None or source_file is None:
            return {"status": "skipped"}

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
            raise

        task_row.completed_at = datetime.utcnow()
        db.add(task_row)
        db.add(source_file)

        _refresh_batch_status(batch)
        db.add(batch)
        db.commit()
        return {"status": "completed"}
    finally:
        db.close()
