"""Skywork-backed Smart mode: server-side call to Skywork's hosted PPT API.

The finished .pptx is delivered as a download. Download-only by design;
the Smart-editor bridge tried this session was reverted after repeated
generation issues (broken image paths, schema/validation failures).
"""
import logging
import os
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
from services.database import async_session_maker, get_async_session
from services.documents_loader import DocumentsLoader
from services.skywork_client import SkyworkError, download_pptx, generate_pptx, phase_message
from services.temp_file_service import TEMP_FILE_SERVICE
from utils.asset_directory_utils import get_exports_directory
from utils.get_env import get_app_data_directory_env, get_skywork_api_key_env

logger = logging.getLogger(__name__)

SKYWORK_ROUTER = APIRouter(prefix="/skywork", tags=["Skywork"])

SKYWORK_ASYNC_TASK_TYPE = "skywork.ppt.generate"


class SkyworkGenerateRequest(BaseModel):
    content: str = ""
    language: str = "English"
    n_slides: Optional[int] = None
    file_paths: Optional[list[str]] = None


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


@SKYWORK_ROUTER.post("/generate", response_model=AsyncTaskModel)
async def start_skywork_generation(
    request: SkyworkGenerateRequest,
    background_tasks: BackgroundTasks,
    sql_session: AsyncSession = Depends(get_async_session),
):
    if not get_skywork_api_key_env():
        raise HTTPException(status_code=404, detail="Skywork is not configured")

    reference = await _build_reference_text(request.file_paths, request.language)
    if not request.content.strip() and not reference:
        raise HTTPException(
            status_code=400, detail="A prompt or document is required"
        )

    query = request.content.strip()
    if request.n_slides:
        query = f"{query}\n\nPlease produce about {request.n_slides} slides."

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
