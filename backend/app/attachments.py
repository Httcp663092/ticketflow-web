"""Authenticated, bounded file storage. Attachments are public within ticket scope."""

import os
import re
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from .db import database
from .models import Attachment, User

MAX_BYTES = 10 * 1024 * 1024
TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".csv": "text/csv",
}


def storage():
    return Path(os.getenv("ATTACHMENT_DIR", "./attachments")).resolve()


def validate_content(suffix, head):
    if suffix == ".png" and not head.startswith(b"\x89PNG\r\n\x1a\n"):
        raise HTTPException(415, "Invalid PNG content")
    if suffix in {".jpg", ".jpeg"} and not head.startswith(b"\xff\xd8\xff"):
        raise HTTPException(415, "Invalid JPEG content")
    if suffix == ".pdf" and not head.startswith(b"%PDF-"):
        raise HTTPException(415, "Invalid PDF content")


def item(a):
    return {
        "id": a.id,
        "filename": a.filename,
        "size": a.size,
        "uploader_id": a.uploader_id,
        "created_at": a.created_at,
    }


def make_router(current, visible, log):
    router = APIRouter(prefix="/api/tickets")

    @router.get("/{ticket_id}/attachments")
    def listing(
        ticket_id: int, db: Session = Depends(database), user: User = Depends(current)
    ):
        visible(ticket_id, db, user)
        return [
            item(a)
            for a in db.scalars(
                select(Attachment)
                .where(Attachment.ticket_id == ticket_id)
                .order_by(Attachment.id)
            )
        ]

    @router.post("/{ticket_id}/attachments", status_code=201)
    async def upload(
        ticket_id: int,
        request: Request,
        filename: str = Query(min_length=1, max_length=200),
        db: Session = Depends(database),
        user: User = Depends(current),
    ):
        ticket = visible(ticket_id, db, user)
        if any(c in filename for c in ("/", "\\")) or re.search(
            r"[\x00-\x1f\x7f]", filename
        ):
            raise HTTPException(422, "Invalid filename")
        suffix = Path(filename).suffix.lower()
        if suffix not in TYPES:
            raise HTTPException(415, "Allowed types: PNG, JPEG, PDF, TXT, CSV")
        if (
            db.scalar(
                select(func.count())
                .select_from(Attachment)
                .where(Attachment.ticket_id == ticket_id)
            )
            >= 20
        ):
            raise HTTPException(413, "At most 20 attachments per ticket")
        root = storage()
        root.mkdir(parents=True, exist_ok=True)
        key = uuid4().hex
        target = root / key
        size = 0
        head = bytearray()
        try:
            with target.open("xb") as output:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise HTTPException(413, "File exceeds 10 MiB")
                    # Keep only a bounded prefix for image/PDF signature checks.
                    if len(head) < 8192:
                        head.extend(chunk[: 8192 - len(head)])
                    output.write(chunk)
            if not size:
                raise HTTPException(422, "Empty file")
            if suffix in {".txt", ".csv"}:
                # Incremental decoding accepts multibyte characters across chunk boundaries.
                import codecs

                decoder = codecs.getincrementaldecoder("utf-8")()
                try:
                    with target.open("rb") as source:
                        while data := source.read(65536):
                            if b"\x00" in data:
                                raise HTTPException(415, "Binary text file rejected")
                            decoder.decode(data)
                        decoder.decode(b"", final=True)
                except UnicodeDecodeError:
                    raise HTTPException(415, "Text files must be UTF-8")
            else:
                validate_content(suffix, bytes(head))
            attachment = Attachment(
                ticket_id=ticket.id,
                uploader_id=user.id,
                filename=filename,
                storage_key=key,
                content_type=TYPES[suffix],
                size=size,
            )
            db.add(attachment)
            log(db, ticket, user, f"Attachment uploaded: {filename}")
            db.commit()
            return item(attachment)
        except BaseException:
            db.rollback()
            target.unlink(missing_ok=True)
            raise

    @router.get("/{ticket_id}/attachments/{attachment_id}")
    def download(
        ticket_id: int,
        attachment_id: int,
        db: Session = Depends(database),
        user: User = Depends(current),
    ):
        visible(ticket_id, db, user)
        attachment = db.get(Attachment, attachment_id)
        if not attachment or attachment.ticket_id != ticket_id:
            raise HTTPException(404, "Attachment not found")
        target = storage() / attachment.storage_key
        if not target.is_file():
            raise HTTPException(404, "Attachment file unavailable")
        return FileResponse(
            target,
            media_type="application/octet-stream",
            filename=attachment.filename,
            headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"},
        )

    return router
