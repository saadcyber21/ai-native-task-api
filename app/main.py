import hashlib
import json
from datetime import UTC
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import Base, engine, get_db
from app.models import IdempotencyRecord, Task, utc_now
from app.schemas import BreakdownOut, TaskCreate, TaskFromText, TaskOut
from app.services import breakdown_task, generate_task

Base.metadata.create_all(bind=engine)
app = FastAPI(title=\"AI-Native Task API\", version=\"0.1.0\", description=\"Natural-language task capture with recurrence, idempotency, and optional LLM structured outputs.\")


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    details = [{\"type\": item.get(\"type\"), \"loc\": item.get(\"loc\"), \"msg\": item.get(\"msg\")} for item in exc.errors()]
    return JSONResponse(status_code=422, content={\"error\": {\"code\": \"validation_error\", \"message\": \"Request validation failed\", \"details\": jsonable_encoder(details)}})


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={\"error\": {\"code\": \"internal_error\", \"message\": \"An unexpected error occurred\", \"details\": []}})


def _task_out(task: Task) -> dict:
    return TaskOut.model_validate(task).model_dump(mode=\"json\")


def _hash(data: dict) -> str:
    raw = json.dumps(data, sort_keys=True, separators=(\",\", \":\"), default=str).encode()
    return hashlib.sha256(raw).hexdigest()


def _idempotent(db: Session, key: str | None, scope: str, request_hash: str) -> dict | None:
    if not key:
        return None
    if len(key) > 255:
        raise HTTPException(status_code=422, detail={\"code\": \"invalid_idempotency_key\", \"message\": \"Idempotency-Key must be at most 255 characters\"})
    record = db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.key == key, IdempotencyRecord.scope == scope))
    if record is None:
        return None
    if record.request_hash != request_hash:
        raise HTTPException(status_code=409, detail={\"code\": \"idempotency_conflict\", \"message\": \"This key was already used with a different request\"})
    return record.response


def _save_idempotency(db: Session, key: str | None, scope: str, request_hash: str, response: dict) -> None:
    if key:
        db.add(IdempotencyRecord(key=key, scope=scope, request_hash=request_hash, response=response))


def _create_task(db: Session, data: TaskCreate, parent_id: str | None = None) -> Task:
    due_at = data.due_at
    if due_at and due_at.tzinfo is None:
        due_at = due_at.replace(tzinfo=UTC)
    elif due_at:
        due_at = due_at.astimezone(UTC)
    return Task(id=str(uuid4()), title=data.title, description=data.description, due_at=due_at, recurrence=data.recurrence.model_dump() if data.recurrence else None, parent_id=parent_id, created_at=utc_now())


@app.get(\"/health\", tags=[\"system\"])
def health():
    return {\"status\": \"ok\"}


@app.post(\"/v1/tasks\", response_model=TaskOut, status_code=status.HTTP_201_CREATED, tags=[\"tasks\"])
def create_task(payload: TaskCreate, idempotency_key: str | None = Header(default=None, alias=\"Idempotency-Key\"), db: Session = Depends(get_db)):
    body = payload.model_dump(mode=\"json\")
    request_hash = _hash(body)
    existing = _idempotent(db, idempotency_key, \"create\", request_hash)
    if existing is not None:
        return existing
    task = _create_task(db, payload)
    db.add(task)
    response = _task_out(task)
    _save_idempotency(db, idempotency_key, \"create\", request_hash, response)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = _idempotent(db, idempotency_key, \"create\", request_hash)
        if existing is not None:
            return existing
        raise
    return response


@app.post(\"/v1/tasks/from-text\", response_model=TaskOut, status_code=status.HTTP_201_CREATED, tags=[\"tasks\"])
def create_from_text(payload: TaskFromText, idempotency_key: str | None = Header(default=None, alias=\"Idempotency-Key\"), db: Session = Depends(get_db)):
    request_hash = _hash(payload.model_dump(mode=\"json\"))
    existing = _idempotent(db, idempotency_key, \"from-text\", request_hash)
    if existing is not None:
        return existing
    try:
        task_data = generate_task(payload.text)
    except Exception as exc:
        raise HTTPException(status_code=502, detail={\"code\": \"generation_failed\", \"message\": \"Task generation failed\"}) from exc
    task = _create_task(db, task_data)
    db.add(task)
    response = _task_out(task)
    _save_idempotency(db, idempotency_key, \"from-text\", request_hash, response)
    db.commit()
    return response


@app.post(\"/v1/tasks/breakdown\", response_model=BreakdownOut, status_code=status.HTTP_201_CREATED, tags=[\"tasks\"])
def breakdown(payload: TaskFromText, idempotency_key: str | None = Header(default=None, alias=\"Idempotency-Key\"), db: Session = Depends(get_db)):
    request_hash = _hash(payload.model_dump(mode=\"json\"))
    existing = _idempotent(db, idempotency_key, \"breakdown\", request_hash)
    if existing is not None:
        return existing
    try:
        titles = breakdown_task(payload.text)
    except Exception as exc:
        raise HTTPException(status_code=502, detail={\"code\": \"generation_failed\", \"message\": \"Subtask generation failed\"}) from exc
    parent = Task(id=str(uuid4()), title=payload.text.strip()[:200], created_at=utc_now())
    subtasks = [Task(id=str(uuid4()), title=title, parent_id=parent.id, created_at=utc_now()) for title in titles]
    db.add(parent)
    db.add_all(subtasks)
    response = {\"parent\": _task_out(parent), \"subtasks\": [_task_out(task) for task in subtasks]}
    _save_idempotency(db, idempotency_key, \"breakdown\", request_hash, response)
    db.commit()
    return response


@app.get(\"/v1/tasks\", response_model=list[TaskOut], tags=[\"tasks\"])
def list_tasks(limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0), db: Session = Depends(get_db)):
    return list(db.scalars(select(Task).where(Task.parent_id.is_(None)).order_by(Task.created_at.desc()).offset(offset).limit(limit)))


@app.get(\"/v1/tasks/{task_id}\", response_model=TaskOut, tags=[\"tasks\"])
def get_task(task_id: str, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail={\"code\": \"task_not_found\", \"message\": \"Task not found\"})
    return task


@app.delete(\"/v1/tasks/{task_id}\", status_code=status.HTTP_204_NO_CONTENT, tags=[\"tasks\"])
def delete_task(task_id: str, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail={\"code\": \"task_not_found\", \"message\": \"Task not found\"})
    db.delete(task)
    db.commit()
