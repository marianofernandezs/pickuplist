from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.entities import BatchTask, ProcessingBatch, ProductCandidate, SourceFile, User
from app.schemas.auth import ForgotPasswordOut, ForgotPasswordRequest, LoginRequest, ResetPasswordRequest, TokenOut, UserOut
from app.schemas.queue import BatchAcceptedOut, BatchStatusOut, BatchTaskOut
from app.schemas.vige import ProductOut, SourceFileOut
from app.security import create_access_token, get_current_user, get_password_hash
from app.services.auth_service import (
    authenticate_user,
    consume_password_reset_token,
    create_password_reset_token,
    is_email_allowed,
    normalize_email,
    validate_password_strength,
)
from app.services.consolidator import consolidate_products
from app.services.pdf_exporter import export_vige_pdf
from app.workers.tasks import process_source_file

router = APIRouter()

TERMINAL_BATCH_STATUSES = {"completed", "failed", "completed_with_errors"}


def _refresh_batch_status(batch: ProcessingBatch) -> None:
    if batch.processed_files + batch.failed_files < batch.total_files:
        batch.status = "processing"
        return

    if batch.failed_files == 0:
        batch.status = "completed"
    elif batch.processed_files == 0:
        batch.status = "failed"
    else:
        batch.status = "completed_with_errors"


def _mark_task_as_failed(
    db: Session,
    *,
    batch: ProcessingBatch,
    source_file: SourceFile,
    task_row: BatchTask,
    message: str,
) -> None:
    source_file.status = "failed"
    task_row.status = "failed"
    task_row.error_message = message[:2000]
    task_row.completed_at = datetime.utcnow()
    batch.failed_files += 1
    _refresh_batch_status(batch)
    db.add(source_file)
    db.add(task_row)
    db.add(batch)
    db.commit()


@router.post("/auth/login", response_model=TokenOut)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    result = authenticate_user(db, payload.email, payload.password)
    if not result.ok or result.user is None:
        raise HTTPException(status_code=401, detail="Email o contraseña inválidos.")

    token = create_access_token(result.user.email)
    return TokenOut(access_token=token, token_type="bearer", user=result.user)


@router.get("/auth/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.post("/auth/forgot-password", response_model=ForgotPasswordOut)
def forgot_password(payload: ForgotPasswordRequest, db: Session = Depends(get_db)):
    email = normalize_email(str(payload.email))
    user = db.query(User).filter(User.email == email).first()
    message = "Si el usuario existe, enviaremos instrucciones para recuperar la contraseña."

    if user is None or not user.is_active or not is_email_allowed(email):
        return ForgotPasswordOut(message=message)

    reset_token = create_password_reset_token(db, user)
    if settings.auth_debug_return_reset_token:
        base_url = settings.frontend_base_url.rstrip("/")
        reset_link = f"{base_url}/reset-password?token={reset_token}"
        return ForgotPasswordOut(message=message, reset_token=reset_token, reset_link=reset_link)
    return ForgotPasswordOut(message=message)


@router.post("/auth/reset-password")
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    try:
        validate_password_strength(payload.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    user = consume_password_reset_token(db, payload.token)
    if user is None:
        raise HTTPException(status_code=400, detail="Token inválido o expirado.")

    user.hashed_password = get_password_hash(payload.new_password)
    db.add(user)
    db.commit()
    return {"ok": True}


def _validate_pdf_batch(files: list[UploadFile]) -> None:
    if len(files) == 0:
        raise HTTPException(status_code=400, detail="Debes subir al menos un PDF.")
    if len(files) > settings.max_pdfs_per_batch:
        raise HTTPException(
            status_code=400,
            detail=f"Máximo permitido por lote: {settings.max_pdfs_per_batch} PDFs.",
        )

    for upload in files:
        filename = upload.filename or ""
        if not filename:
            raise HTTPException(status_code=400, detail="Se detectó un archivo sin nombre.")
        if not filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail=f"Archivo no PDF: {filename}")


def _save_uploaded_file(upload: UploadFile, target: Path) -> None:
    source: BinaryIO = upload.file
    with target.open("wb") as destination:
        while True:
            chunk = source.read(settings.upload_chunk_size_bytes)
            if not chunk:
                break
            destination.write(chunk)


@router.post("/upload", response_model=BatchAcceptedOut)
def upload_pdfs(
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    _validate_pdf_batch(files)

    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)

    batch = ProcessingBatch(
        id=str(uuid4()),
        status="queued",
        total_files=len(files),
        processed_files=0,
        failed_files=0,
        created_by_email=current_user.email,
    )
    db.add(batch)
    db.commit()

    for f in files:
        filename = f.filename or "archivo_sin_nombre.pdf"
        unique_name = f"{uuid4()}_{filename}"
        target = upload_dir / unique_name

        entity = SourceFile(
            filename=filename,
            stored_path=str(target),
            status="queued",
            page_count=0,
            requires_ocr=False,
        )
        try:
            db.add(entity)
            db.commit()
        except Exception:
            db.rollback()
            batch.failed_files += 1
            _refresh_batch_status(batch)
            db.add(batch)
            db.commit()
            f.file.close()
            continue

        task_id = str(uuid4())
        task_row = BatchTask(
            batch_id=batch.id,
            source_file_id=entity.id,
            task_id=task_id,
            status="queued",
            error_message=None,
        )
        try:
            db.add(task_row)
            db.commit()
        except Exception:
            db.rollback()
            entity.status = "failed"
            batch.failed_files += 1
            _refresh_batch_status(batch)
            db.add(entity)
            db.add(batch)
            db.commit()
            f.file.close()
            continue

        try:
            _save_uploaded_file(f, target)
        except Exception as exc:
            if target.exists():
                target.unlink()
            _mark_task_as_failed(
                db,
                batch=batch,
                source_file=entity,
                task_row=task_row,
                message=f"No se pudo guardar el PDF {filename}: {exc}",
            )
            continue
        finally:
            f.file.close()

        try:
            process_source_file.apply_async(
                args=[batch.id, entity.id],
                task_id=task_id,
                retry=True,
                retry_policy={
                    "max_retries": 5,
                    "interval_start": 0,
                    "interval_step": 0.5,
                    "interval_max": 3,
                },
            )
        except Exception as exc:
            if target.exists():
                target.unlink()
            _mark_task_as_failed(
                db,
                batch=batch,
                source_file=entity,
                task_row=task_row,
                message=f"No se pudo encolar la tarea para {filename}: {exc}",
            )
            continue

    return BatchAcceptedOut(batch_id=batch.id, status=batch.status, total_files=batch.total_files)


@router.get("/batches/{batch_id}", response_model=BatchStatusOut)
def get_batch_status(
    batch_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = current_user
    batch = db.query(ProcessingBatch).filter(ProcessingBatch.id == batch_id).first()
    if batch is None:
        raise HTTPException(status_code=404, detail="Lote no encontrado.")

    tasks = (
        db.query(BatchTask)
        .filter(BatchTask.batch_id == batch.id)
        .order_by(BatchTask.id.asc())
        .all()
    )

    # Reconciliación defensiva: evita lotes pegados si hubo desalineación de contadores.
    processed_count = sum(1 for task in tasks if task.status == "completed")
    failed_count = sum(1 for task in tasks if task.status == "failed")
    if batch.processed_files != processed_count or batch.failed_files != failed_count:
        batch.processed_files = processed_count
        batch.failed_files = failed_count
        _refresh_batch_status(batch)
        db.add(batch)
        db.commit()
        db.refresh(batch)

    # Si todas las tareas están terminales, fuerza estado terminal del lote.
    if tasks and all(task.status in {"completed", "failed"} for task in tasks):
        if batch.status not in TERMINAL_BATCH_STATUSES:
            _refresh_batch_status(batch)
            db.add(batch)
            db.commit()
            db.refresh(batch)

    return BatchStatusOut(
        batch_id=batch.id,
        status=batch.status,
        total_files=batch.total_files,
        processed_files=batch.processed_files,
        failed_files=batch.failed_files,
        created_by_email=batch.created_by_email,
        created_at=batch.created_at.isoformat(),
        started_at=batch.started_at.isoformat() if batch.started_at else None,
        completed_at=batch.completed_at.isoformat() if batch.completed_at else None,
        tasks=[
            BatchTaskOut(
                source_file_id=task.source_file_id,
                task_id=task.task_id,
                status=task.status,
                error_message=task.error_message,
            )
            for task in tasks
        ],
    )


@router.get("/products", response_model=list[ProductOut])
def list_products(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _ = current_user
    consolidated = consolidate_products(db)
    result: list[ProductOut] = []
    for idx, item in enumerate(consolidated, start=1):
        result.append(
            ProductOut(
                id=idx,
                source_file_id=0,
                page_number=0,
                sku=None,
                description_exact=item.description_exact,
                quantity=item.quantity,
                unit=item.unit,
                presentation=item.presentation,
                observations=None,
            )
        )
    return result


@router.get("/sources", response_model=list[SourceFileOut])
def list_sources(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _ = current_user
    return db.query(SourceFile).order_by(SourceFile.created_at.desc()).all()


@router.get("/export")
def export_pdf(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _ = current_user
    output_dir = Path(settings.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    path = output_dir / "Lista VIGE.pdf"
    export_vige_pdf(db, path, title="Lista VIGE")
    return FileResponse(path=str(path), media_type="application/pdf", filename="Lista VIGE.pdf")


@router.get("/export/bodega")
def export_pickeo_bodega_pdf(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _ = current_user
    output_dir = Path(settings.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    path = output_dir / "Lista Pickeo Bodega.pdf"
    export_vige_pdf(
        db,
        path,
        title="Lista Pickeo Bodega",
        allowed_presentations=("caja",),
    )
    return FileResponse(path=str(path), media_type="application/pdf", filename="Lista Pickeo Bodega.pdf")


@router.get("/export/local")
def export_pickeo_local_pdf(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _ = current_user
    output_dir = Path(settings.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    path = output_dir / "Lista Pickeo Local.pdf"
    export_vige_pdf(
        db,
        path,
        title="Lista Pickeo Local",
        allowed_presentations=("unitario", "pack"),
    )
    return FileResponse(path=str(path), media_type="application/pdf", filename="Lista Pickeo Local.pdf")


@router.post("/reset")
def reset_iteration(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _ = current_user
    source_files = db.query(SourceFile).all()

    for source in source_files:
        file_path = Path(source.stored_path)
        if file_path.exists():
            file_path.unlink()

    output_pdf = Path(settings.output_dir) / "Lista VIGE.pdf"
    if output_pdf.exists():
        output_pdf.unlink()
    output_pdf_bodega = Path(settings.output_dir) / "Lista Pickeo Bodega.pdf"
    if output_pdf_bodega.exists():
        output_pdf_bodega.unlink()
    output_pdf_local = Path(settings.output_dir) / "Lista Pickeo Local.pdf"
    if output_pdf_local.exists():
        output_pdf_local.unlink()

    db.query(ProductCandidate).delete()
    db.execute(text("DELETE FROM extracted_lines"))
    db.query(BatchTask).delete()
    db.query(ProcessingBatch).delete()
    db.query(SourceFile).delete()
    db.commit()

    return {"ok": True}
