import uuid
import threading
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel
from ai_backend.services.video_analysis_service import analyze_video, parse_analysis_report, VideoAnalysisError

router = APIRouter()

class AnalyzeRequest(BaseModel):
    video_link: str

class JobStatus(str):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    ERROR = "error"

jobs = {}
jobs_lock = threading.Lock()

def video_analysis_job(job_id, video_link):
    with jobs_lock:
        jobs[job_id]["status"] = JobStatus.PROCESSING
    try:
        report_text = analyze_video(video_link, job_id)
        result = parse_analysis_report(report_text)
        with jobs_lock:
            jobs[job_id]["status"] = JobStatus.DONE
            jobs[job_id]["result"] = result
    except Exception as e:
        with jobs_lock:
            jobs[job_id]["status"] = JobStatus.ERROR
            jobs[job_id]["error"] = str(e)

@router.post("/analyze")
async def analyze(request: AnalyzeRequest, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())
    with jobs_lock:
        jobs[job_id] = {"status": JobStatus.PENDING, "result": None, "error": None}
    background_tasks.add_task(video_analysis_job, job_id, request.video_link)
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