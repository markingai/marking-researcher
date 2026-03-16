"""Datasets router."""

from fastapi import APIRouter, Depends, Query

from ..dependencies import get_current_user
from ..models import DatasetsResponse, DatasetInfo, QuestionInfo
from ..services.dataset_service import (
    get_dataset_info, get_questions, check_pdf_availability, get_custom_subjects,
)

router = APIRouter(prefix="/api/datasets", tags=["datasets"])


@router.get("", response_model=DatasetsResponse)
async def list_datasets(
    input_mode: str = Query("csv"),
    _user: dict = Depends(get_current_user),
):
    maths_info = get_dataset_info("maths", input_mode=input_mode)
    english_info = get_dataset_info("english", input_mode=input_mode)
    pdf_available, pdf_count = check_pdf_availability()

    dataset_list = [
        DatasetInfo(
            subject=maths_info["subject"],
            source=maths_info["source"],
            total_rows=maths_info["total_rows"],
            questions=[QuestionInfo(**q) for q in maths_info["questions"]],
        ),
        DatasetInfo(
            subject=english_info["subject"],
            source=english_info["source"],
            total_rows=english_info["total_rows"],
            questions=[QuestionInfo(**q) for q in english_info["questions"]],
        ),
    ]

    # Add custom subjects
    for subj in get_custom_subjects():
        info = get_dataset_info(subj["slug"])
        dataset_list.append(
            DatasetInfo(
                subject=info["subject"],
                source=info["source"],
                total_rows=info["total_rows"],
                questions=[QuestionInfo(**q) for q in info["questions"]],
            )
        )

    return DatasetsResponse(
        datasets=dataset_list,
        pdf_available=pdf_available,
        pdf_submissions=pdf_count,
    )


@router.get("/{subject}/questions")
async def get_subject_questions(
    subject: str,
    input_mode: str = Query("csv"),
    _user: dict = Depends(get_current_user),
):
    questions = get_questions(subject, input_mode=input_mode)
    return {"questions": [QuestionInfo(**q) for q in questions]}
