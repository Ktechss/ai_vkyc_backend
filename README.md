# ai_backend

A structured FastAPI backend for video KYC analysis using Google Gemini AI.

## Structure

- `main.py` — FastAPI app entrypoint
- `controllers/` — API route handlers (controllers)
- `services/` — Business logic and integration with Google AI
- `prompts/` — Prompt templates for analysis
- `utils/` — Utility functions (e.g., URL detection)

## How to Run

1. Install dependencies:
   ```bash
   pip install fastapi uvicorn gdown google-generativeai python-dotenv requests
   ```
2. Set your `GOOGLE_AI_API_KEY` in a `.env` file.
3. Start the backend:
   ```bash
   uvicorn ai_backend.main:app --reload
   ```
4. Use the API:
   - `POST /analyze` with `{ "video_link": "<url or file path>" }` returns a job ID.
   - `GET /result/{job_id}` returns the analysis result or job status.

## Notes
- Handles Google Drive, direct video URLs, and local files.
- Asynchronous, job-based processing for scalability.
- CORS enabled for frontend integration. 