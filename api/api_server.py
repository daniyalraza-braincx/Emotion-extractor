import json
import logging
import os
from typing import Dict, Any

from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from extractor import (
    analyze_audio_files,
    download_retell_recording,
    extract_retell_transcript_segments,
    get_retell_call_details,
)


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

RETELL_RESULTS_DIR = os.getenv("RETELL_RESULTS_DIR", "retell_results")

if not os.path.exists(RETELL_RESULTS_DIR):
    os.makedirs(RETELL_RESULTS_DIR, exist_ok=True)

app = FastAPI(title="Hume Emotion Analysis API")

# Enable CORS for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify your frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/analyze")
async def analyze_audio(file: UploadFile = File(...)):
    """
    Analyze audio file for emotion detection using Hume API.
    
    Returns:
        JSON with a top emotion per time segment for prosody and burst models.
    """
    try:
        # Read uploaded file
        file_content = await file.read()
        filename = file.filename or "uploaded_audio"
        
        # Prepare file contents (list of tuples: (filename, bytes))
        file_contents = [(filename, file_content)]
        
        # Analyze using the reusable function from extractor.py
        results = analyze_audio_files(file_contents, include_summary=True)
        
        if not results:
            raise HTTPException(
                status_code=404, 
                detail="No emotion predictions found. The audio may not contain detectable speech."
            )
        
        # Return first result (since we only process one file)
        result = results[0]
        
        return JSONResponse(content={
            "success": True,
            "filename": filename,
            "results": result
        })
        
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_detail = str(e)
        # Include more detailed error info in development
        if hasattr(e, '__traceback__'):
            tb_str = traceback.format_exception(type(e), e, e.__traceback__)
            error_detail += f"\n\nTraceback:\n{''.join(tb_str)}"
        raise HTTPException(status_code=500, detail=f"Error processing audio: {error_detail}")


def _persist_retell_results(call_id: str, payload: Dict[str, Any]) -> None:
    """Persist processed Retell results locally for inspection."""
    output_path = os.path.join(RETELL_RESULTS_DIR, f"{call_id}.json")
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        logger.info("Saved Retell analysis to %s", output_path)
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("Failed to save Retell results for %s: %s", call_id, exc)


def _process_retell_call(call_payload: Dict[str, Any]) -> None:
    call_id = call_payload.get("call_id")
    if not call_id:
        logger.warning("Received Retell payload without call_id; skipping")
        return

    try:
        call_data = call_payload
        if not call_data.get("recording_multi_channel_url"):
            call_data = get_retell_call_details(call_id)

        recording_url = call_data.get("recording_multi_channel_url")
        if not recording_url:
            logger.error("No recording URL available for call %s", call_id)
            return

        filename_hint = f"{call_id}.wav"
        audio_filename, audio_bytes = download_retell_recording(recording_url, filename_hint)
        file_contents = [(audio_filename, audio_bytes)]

        transcript_segments = extract_retell_transcript_segments(call_data)

        analysis_results = analyze_audio_files(
            file_contents,
            include_summary=True,
            retell_call_id=call_id,
            retell_transcript=transcript_segments
        )

        payload_to_store = {
            "call_id": call_id,
            "retell_metadata": {
                "agent_id": call_data.get("agent_id"),
                "start_timestamp": call_data.get("start_timestamp"),
                "end_timestamp": call_data.get("end_timestamp"),
                "recording_multi_channel_url": recording_url,
            },
            "analysis": analysis_results
        }

        _persist_retell_results(call_id, payload_to_store)

    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("Error processing Retell call %s: %s", call_id, exc)


@app.post("/retell/webhook")
async def retell_webhook(payload: Dict[str, Any], background_tasks: BackgroundTasks):
    """Endpoint to receive Retell call events and trigger analysis."""
    event = payload.get("event")
    call_data = payload.get("call")

    if event != "call_analyzed" or not isinstance(call_data, dict):
        logger.info("Ignoring Retell event %s", event)
        return JSONResponse(content={"success": True, "ignored": True})

    call_id = call_data.get("call_id")
    if not call_id:
        raise HTTPException(status_code=400, detail="Missing call_id in Retell payload")

    logger.info("Received call_analyzed webhook for call %s", call_id)
    background_tasks.add_task(_process_retell_call, call_data)

    return JSONResponse(content={"success": True, "message": "Processing started", "call_id": call_id})


@app.get("/")
async def root():
    """Health check endpoint"""
    return {"message": "Hume Emotion Analysis API is running", "status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
