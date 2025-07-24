import os
import time
import requests
import gdown
import google.generativeai as genai
from ai_backend.prompts.vkyc_prompt import VKYC_AGENT_ANALYSIS_PROMPT
from ai_backend.utils.video_utils import is_url, is_gdrive_link

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

def analyze_video(video_input, job_id, prompt=VKYC_AGENT_ANALYSIS_PROMPT, timeout=300):
    temp_video_path = f"temp_{job_id}.mp4"
    myfile = None
    try:
        download_video(video_input, temp_video_path)
        myfile = genai.upload_file(temp_video_path)
        # Wait for the file to become ACTIVE (state == 2)
        start_time = time.time()
        while myfile.state != 2:
            if time.time() - start_time > timeout:
                raise TimeoutError("Video processing timeout after 300 seconds")
            time.sleep(3)
            myfile = genai.get_file(myfile.name)
        model = genai.GenerativeModel("gemini-2.5-flash")
        response = model.generate_content([myfile, prompt])
        return response.text
    except Exception as e:
        raise VideoAnalysisError(str(e))
    finally:
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