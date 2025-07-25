import uuid
import threading
from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from services.video_analysis_service import analyze_video, parse_analysis_report, VideoAnalysisError
import shutil
import tempfile
from uuid import UUID
import re
from typing import Optional

router = APIRouter()

class AnalyzeRequest(BaseModel):
    video_link: str = None
    employee_id: str = None
    call_date: str = None
    call_duration: str = None

class JobStatus(str):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    ERROR = "error"

jobs = {}
jobs_lock = threading.Lock()

def remove_json_block_from_summary(summary_text):
    # Remove the last JSON block from the summary
    return re.sub(r'```json[\s\S]*?```', '', summary_text).strip()

def video_analysis_job(job_id, video_link, session_id=None):
    with jobs_lock:
        jobs[job_id]["status"] = JobStatus.PROCESSING
    try:
        report_text = analyze_video(video_link, job_id, session_id=session_id)
        # Remove the JSON block from the summary for the response
        clean_summary = remove_json_block_from_summary(report_text)
        result = parse_analysis_report(clean_summary)
        with jobs_lock:
            jobs[job_id]["status"] = JobStatus.DONE
            jobs[job_id]["result"] = result
    except Exception as e:
        with jobs_lock:
            jobs[job_id]["status"] = JobStatus.ERROR
            jobs[job_id]["error"] = str(e)

@router.post("/analyze")
async def analyze(
    background_tasks: BackgroundTasks,
    session_id: UUID = Form(...),
    file: Optional[UploadFile] = File(None),
    video_link: Optional[str] = Form(None)
):
    job_id = str(session_id)
    with jobs_lock:
        jobs[job_id] = {"status": JobStatus.PENDING, "result": None, "error": None}
    import shutil, tempfile
    if file:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp:
            shutil.copyfileobj(file.file, tmp)
            temp_path = tmp.name
        video_input = temp_path
    elif video_link:
        video_input = video_link
    else:
        raise HTTPException(status_code=400, detail="No video file or link provided.")
    background_tasks.add_task(video_analysis_job, job_id, video_input, session_id)
    return {"job_id": job_id, "status": JobStatus.PENDING}

@router.get("/result/{job_id}")
async def get_result(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job ID not found.")
        if job["status"] == JobStatus.ERROR:
            return {"status": JobStatus.ERROR, "error": job["error"]}
        if job["status"] != JobStatus.DONE:
            return {"status": job["status"]}
        return {"status": JobStatus.DONE, "result": job["result"]} 