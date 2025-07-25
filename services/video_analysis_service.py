import os
import time
import requests
import gdown
import google.generativeai as genai
from prompts.vkyc_prompt import VKYC_AGENT_ANALYSIS_PROMPT
from utils.video_utils import is_url, is_gdrive_link
from utils.s3_utils import upload_file_to_s3
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Float, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import datetime
from dotenv import load_dotenv
import json
import re
from dateutil import parser
load_dotenv()

DATABASE_URL = os.getenv('DATABASE_URL')
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class QualityCheckVideo(Base):
    __tablename__ = 'quality_check_videos'
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(64))  # Added session_id field
    video_filename = Column(String)
    video_path = Column(String)
    employee_id = Column(String)
    call_date = Column(String)
    call_duration = Column(String)
    analysis_status = Column(String)
    quality_score = Column(Float)
    sop_compliance = Column(String)
    language_issues = Column(String)
    body_language_score = Column(Float)
    id_card_visible = Column(String)
    issues_found = Column(String)
    analysis_details = Column(Text)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    result = Column(Text) # New column for storing parsed analysis results

class VideoSummary(Base):
    __tablename__ = 'video_summaries'
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, index=True)
    video_path = Column(String)
    ai_summary = Column(Text)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

# Ensure table exists
Base.metadata.create_all(bind=engine)

class VideoAnalysisError(Exception):
    pass

def download_video(video_input, temp_video_path):
    if is_gdrive_link(video_input):
        file_id = video_input.split('/d/')[1].split('/')[0]
        gdown.download(f'https://drive.google.com/uc?id={file_id}', temp_video_path, quiet=False)
    elif is_url(video_input):
        response = requests.get(video_input, stream=True, timeout=60)
        response.raise_for_status()
        with open(temp_video_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
    else:
        if not os.path.exists(video_input):
            raise FileNotFoundError("Local file not found.")
        # Copy to temp path for uniform cleanup
        with open(video_input, "rb") as src, open(temp_video_path, "wb") as dst:
            dst.write(src.read())

    # If the video is a local file (not a URL or GDrive), upload to S3 and return the S3 URL
    if not is_url(video_input) and not is_gdrive_link(video_input):
        bucket = os.getenv('S3_BUCKET_NAME')
        s3_url = upload_file_to_s3(temp_video_path, bucket)
        return s3_url
    return temp_video_path

def extract_json_from_summary(summary_text):
    matches = re.findall(r'({[\s\S]*?})', summary_text)
    if not matches:
        return None
    try:
        return json.loads(matches[-1])
    except Exception:
        return None

def to_bool(val):
    if isinstance(val, bool):
        return val
    if isinstance(val, int):
        return bool(val)
    if not val:
        return False
    val = str(val).strip().lower()
    # Accept 1, true, yes, pass, compliant, present, visible, etc. as True
    true_vals = ["1", "true", "yes", "pass", "passed", "compliant", "present", "visible", "ok", "done"]
    return any(tv in val for tv in true_vals)

def safe_parse_datetime(val):
    try:
        if not val or 'XX' in str(val):
            raise ValueError
        return parser.parse(val)
    except Exception:
        return datetime.datetime.utcnow()

def analyze_video(video_input, job_id, prompt=VKYC_AGENT_ANALYSIS_PROMPT, timeout=300, session_id=None):
    temp_video_path = f"temp_{job_id}.mp4"
    myfile = None
    session = SessionLocal()
    try:
        video_source = download_video(video_input, temp_video_path)
        video_filename = os.path.basename(temp_video_path)
        video_path = video_source if video_source.startswith('http') else temp_video_path
        # If video_source is an S3 URL, download it locally for analysis
        if video_source.startswith('http'):
            response = requests.get(video_source, stream=True, timeout=60)
            response.raise_for_status()
            with open(temp_video_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
        myfile = genai.upload_file(temp_video_path)
        start_time = time.time()
        while myfile.state != 2:
            if time.time() - start_time > timeout:
                raise TimeoutError("Video processing timeout after 300 seconds")
            time.sleep(3)
            myfile = genai.get_file(myfile.name)
        model = genai.GenerativeModel("gemini-2.5-flash")
        response = model.generate_content([myfile, prompt])
        ai_summary = response.text
        # Determine the correct video_path for DB
        if is_url(video_input) or is_gdrive_link(video_input):
            db_video_path = video_input
        else:
            db_video_path = video_path
        # Extract structured fields from summary
        fields = extract_json_from_summary(ai_summary)
        result_obj = None
        try:
            result_obj = parse_analysis_report(remove_json_block_from_summary(ai_summary))
        except Exception:
            result_obj = None
        if fields:
            sop = to_bool(fields.get('sop_compliance', 0))
            lang = to_bool(fields.get('language_issues', 0))
            body = to_bool(fields.get('body_language_score', 0))
            id_visible = to_bool(fields.get('id_card_visible', 0))
            # If all are False (0 or null), set analysis_status to 'Passed'
            if not (sop or lang or body or id_visible):
                analysis_status = 'Passed'
            else:
                analysis_status = fields.get('analysis_status', '')
            db_record = QualityCheckVideo(
                session_id=str(session_id),  # Insert session_id
                video_filename=fields.get('video_filename', video_filename),
                video_path=db_video_path,
                employee_id=fields.get('employee_id', ''),
                call_date=fields.get('call_date', ''),
                call_duration=fields.get('call_duration', ''),
                analysis_status=analysis_status,
                quality_score=fields.get('quality_score', 0),
                sop_compliance=sop,
                language_issues=lang,
                body_language_score=body,
                id_card_visible=id_visible,
                issues_found=fields.get('issues_found', ''),
                analysis_details=fields.get('analysis_details', ai_summary),
                created_at=safe_parse_datetime(fields.get('created_at')),
                updated_at=safe_parse_datetime(fields.get('updated_at')),
                result=json.dumps(result_obj) if result_obj else None
            )
            session.add(db_record)
            session.commit()
        #Insert into new summary table only after summary is generated
        summary_record = VideoSummary(
            session_id=str(session_id),
            video_path=video_path,
            ai_summary=ai_summary
        )
        session.add(summary_record)
        session.commit()
        return ai_summary
    except Exception as e:
        raise VideoAnalysisError(str(e))
    finally:
        session.close()
        if myfile:
            try:
                genai.delete_file(myfile.name)
            except Exception:
                pass
        if os.path.exists(temp_video_path):
            os.remove(temp_video_path)

def parse_analysis_report(report_text):
    lines = report_text.splitlines()
    summary = ""
    mistakes = ""
    mistakes_lines = []
    mistakes_found = False
    for i, line in enumerate(lines):
        if "mistake" in line.lower() or "deviation" in line.lower():
            mistakes_found = True
        if mistakes_found and (line.strip() == "" or "summary" in line.lower()):
            break
        if mistakes_found:
            mistakes_lines.append(line)
    for i, line in enumerate(lines):
        if "summary" in line.lower():
            summary = "\n".join(lines[i:])
            break
    mistakes = "\n".join(mistakes_lines) if mistakes_lines else "Not explicitly listed."
    return {
        "summary": summary.strip(),
        "mistakes": mistakes.strip(),
        "full_report": report_text.strip()
    }

def remove_json_block_from_summary(summary_text):
    # This function is not defined in the original file, but is called in analyze_video.
    # Assuming it's meant to remove the JSON block from the summary text.
    # A simple regex to remove the last JSON block found.
    json_pattern = re.compile(r'({[\s\S]*?})')
    match = json_pattern.search(summary_text)
    if match:
        return summary_text[:match.start()] + summary_text[match.end():]
    return summary_text 