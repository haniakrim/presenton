"""Skywork-backed Smart mode: server-side call to Skywork's hosted PPT API.

The finished .pptx is always kept as a download. It's also run through
`skywork_smart_bridge` to try to open it as a real, editable Smart-mode
presentation — same editor Standard/Smart use. Any slide (or the whole deck)
that can't be made to satisfy Smart mode's own validator falls back
gracefully; the download always succeeds either way.

See /Users/haniakrim/.claude/plans/greedy-imagining-swing.md for the original
download-only design this extends.
"""
import logging
import os
import uuid
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.v1.auth.context import (
    get_current_owner_id,
    reset_current_owner_id,
    set_current_owner_id,
)
from enums.async_task_status import AsyncTaskStatus
from models.sql.async_task import AsyncTaskModel
from models.sql.presentation import PresentationModel, PresentationVersion
from models.sql.slide import SlideModel
from services.database import async_session_maker, get_async_session
from services.documents_loader import DocumentsLoader
from services.skywork_client import SkyworkError, download_pptx, generate_pptx, phase_message
from services.skywork_smart_bridge import build_smart_slides
from services.temp_file_service import TEMP_FILE_SERVICE
from utils.asset_directory_utils import get_exports_directory
from utils.get_env import get_app_data_directory_env, get_skywork_api_key_env

logger = logging.getLogger(__name__)

SKYWORK_ROUTER = APIRouter(prefix="/skywork", tags=["Skywork"])

SKYWORK_ASYNC_TASK_TYPE = "skywork.ppt.generate"


class SkyworkOutlineSlide(BaseModel):
    content: str = ""


class SkyworkGenerateRequest(BaseModel):
    content: str = ""
    language: str = "English"
    n_slides: Optional[int] = None
    file_paths: Optional[list[str]] = None
    outline_slides: Optional[list[SkyworkOutlineSlide]] = None


async def _build_reference_text(
    file_paths: Optional[list[str]], language: str
) -> str:
    if not file_paths:
        return ""
    documents_loader = DocumentsLoader(
        file_paths=file_paths, presentation_language=language
    )
    await documents_loader.load_documents(TEMP_FILE_SERVICE.create_temp_dir())
    parts = [document for document in documents_loader.documents if document]
    return "\n\n".join(parts)[:200_000]


def _outline_reference_text(outline_slides: Optional[list[SkyworkOutlineSlide]]) -> str:
    """Format an approved/edited outline as reference text for Skywork.

    Skywork has no "generate from this exact outline" mode - it always
    decides its own final structure - so this is guidance, not a contract.
    """
    if not outline_slides:
        return ""
    numbered = [
        f"Slide {index + 1}: {slide.content.strip()}"
        for index, slide in enumerate(outline_slides)
        if slide.content.strip()
    ]
    if not numbered:
        return ""
    return (
        "Follow this approved outline as closely as possible, one slide per "
        "entry, in this order:\n\n" + "\n\n".join(numbered)
    )


@SKYWORK_ROUTER.post("/generate", response_model=AsyncTaskModel)
async def start_skywork_generation(
    request: SkyworkGenerateRequest,
    background_tasks: BackgroundTasks,
    sql_session: AsyncSession = Depends(get_async_session),
):
    if not get_skywork_api_key_env():
        raise HTTPException(status_code=404, detail="Skywork is not configured")

    document_reference = await _build_reference_text(request.file_paths, request.language)
    outline_reference = _outline_reference_text(request.outline_slides)
    reference = "\n\n".join(part for part in (document_reference, outline_reference) if part)
    if not request.content.strip() and not reference:
        raise HTTPException(
            status_code=400, detail="A prompt or document is required"
        )

    query = request.content.strip()
    n_slides = request.n_slides or (
        len(request.outline_slides) if request.outline_slides else None
    )
    if n_slides:
        query = f"{query}\n\nPlease produce about {n_slides} slides."

    task = AsyncTaskModel(
        type=SKYWORK_ASYNC_TASK_TYPE,
        status=AsyncTaskStatus.PENDING,
        message="Queued for Skywork generation",
        data={"phase": "queued", "progress": 0, "title": query[:120]},
    )
    sql_session.add(task)
    await sql_session.commit()
    await sql_session.refresh(task)

    background_tasks.add_task(
        _run_skywork_task,
        task.id,
        query,
        request.language,
        reference,
        get_current_owner_id(),
    )
    return task


async def _run_skywork_task(
    task_id: str,
    query: str,
    language: str,
    reference: str,
    owner_id,
) -> None:
    owner_token = set_current_owner_id(owner_id)
    try:
        async with async_session_maker() as sql_session:
            task = await sql_session.get(AsyncTaskModel, task_id)
            if not task:
                logger.warning("[skywork.generate] task missing task_id=%s", task_id)
                return

            api_key = get_skywork_api_key_env()

            async def on_progress(event_type: str, data: dict[str, Any]) -> None:
                phase = data.get("phase") or event_type
                task.message = phase_message(phase, data)
                task.data = {
                    **(task.data or {}),
                    "phase": phase,
                    "progress": data.get("progress", (task.data or {}).get("progress", 0)),
                    "message": task.message,
                }
                task.updated_at = datetime.now()
                sql_session.add(task)
                await sql_session.commit()

            try:
                download_url = await generate_pptx(
                    api_key=api_key,
                    query=query,
                    language=language,
                    reference=reference,
                    on_progress=on_progress,
                )

                filename = f"skywork-{task_id}.pptx"
                dest_path = os.path.join(get_exports_directory(), filename)
                await download_pptx(download_url, dest_path)

                app_data_directory = get_app_data_directory_env() or "/tmp/presenton"
                served_path = "/app_data/" + os.path.relpath(
                    dest_path, app_data_directory
                ).replace(os.sep, "/")

                task.message = "Preparing editable slides..."
                task.data = {
                    **(task.data or {}),
                    "phase": "smart_bridge",
                    "progress": 96,
                    "message": task.message,
                }
                task.updated_at = datetime.now()
                sql_session.add(task)
                await sql_session.commit()

                presentation_id: Optional[str] = None
                try:
                    smart_slides = await build_smart_slides(dest_path)
                except Exception:
                    logger.exception(
                        "[skywork.generate] smart bridge failed task_id=%s; "
                        "keeping the download-only result",
                        task_id,
                    )
                    smart_slides = []

                if smart_slides:
                    presentation = PresentationModel(
                        id=uuid.uuid4(),
                        version=PresentationVersion.V2_STANDARD,
                        content=query,
                        n_slides=len(smart_slides),
                        language=language,
                        title=query[:120] or "Skywork Presentation",
                        generation_mode="smart",
                        source="skywork",
                        fonts={"Inter": "/vendor/fonts/sans_serif/inter/Inter[opsz,wght].ttf"},
                    )
                    sql_session.add(presentation)
                    for index, slide in enumerate(smart_slides):
                        sql_session.add(
                            SlideModel(
                                presentation=presentation.id,
                                layout_group="smart-html",
                                layout="smart-html",
                                index=index,
                                content={"title": slide["title"]},
                                html_content=slide["html"],
                                speaker_note=slide.get("speaker_note", ""),
                            )
                        )
                    await sql_session.commit()
                    presentation_id = str(presentation.id)

                task.status = AsyncTaskStatus.COMPLETED
                task.message = "Export complete."
                task.data = {
                    "phase": "done",
                    "progress": 100,
                    "message": "Export complete.",
                    "title": query[:120],
                    "filename": filename,
                    "path": served_path,
                    "download_url": download_url,
                    "presentation_id": presentation_id,
                    "editable": presentation_id is not None,
                }
                task.updated_at = datetime.now()
                sql_session.add(task)
                await sql_session.commit()
            except SkyworkError as exc:
                task.status = AsyncTaskStatus.ERROR
                task.message = str(exc)
                task.error = {"status_code": 502, "detail": str(exc)}
                task.updated_at = datetime.now()
                sql_session.add(task)
                await sql_session.commit()
            except Exception as exc:  # noqa: BLE001 - background task, no client to raise to
                logger.exception("[skywork.generate] unexpected failure task_id=%s", task_id)
                task.status = AsyncTaskStatus.ERROR
                task.message = "Skywork generation failed unexpectedly."
                task.error = {"status_code": 500, "detail": str(exc)}
                task.updated_at = datetime.now()
                sql_session.add(task)
                await sql_session.commit()
    finally:
        reset_current_owner_id(owner_token)
