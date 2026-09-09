"""Durable project CRUD endpoints for the local research workspace."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from app.api.dependencies import get_project_service
from app.projects import ProjectRecord, ProjectService
from app.schemas import ApiErrorResponse, CreateProjectRequest, RenameProjectRequest

router = APIRouter(prefix="/projects", tags=["Projects"])

_ERROR_RESPONSES = {
    404: {"model": ApiErrorResponse, "description": "Project not found."},
    422: {"model": ApiErrorResponse, "description": "Invalid project request."},
    500: {"model": ApiErrorResponse, "description": "Project persistence failure."},
}


@router.post(
    "",
    response_model=ProjectRecord,
    status_code=status.HTTP_201_CREATED,
    responses=_ERROR_RESPONSES,
)
def create_project(
    request: CreateProjectRequest,
    service: Annotated[ProjectService, Depends(get_project_service)],
) -> ProjectRecord:
    return service.create(request.title)


@router.get("", response_model=tuple[ProjectRecord, ...], responses=_ERROR_RESPONSES)
def list_projects(
    service: Annotated[ProjectService, Depends(get_project_service)],
) -> tuple[ProjectRecord, ...]:
    return service.list()


@router.get("/{project_id}", response_model=ProjectRecord, responses=_ERROR_RESPONSES)
def get_project(
    project_id: UUID,
    service: Annotated[ProjectService, Depends(get_project_service)],
) -> ProjectRecord:
    return service.get(project_id)


@router.patch(
    "/{project_id}", response_model=ProjectRecord, responses=_ERROR_RESPONSES
)
def rename_project(
    project_id: UUID,
    request: RenameProjectRequest,
    service: Annotated[ProjectService, Depends(get_project_service)],
) -> ProjectRecord:
    return service.rename(project_id, request.title)


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_ERROR_RESPONSES,
)
def delete_project(
    project_id: UUID,
    service: Annotated[ProjectService, Depends(get_project_service)],
) -> Response:
    service.delete(project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
