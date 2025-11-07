import json
import logging
import os
import threading
from datetime import datetime
from typing import Dict, Any, Optional

from fastapi import FastAPI, UploadFile, File, HTTPException
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
RETELL_CALLS_FILENAME = os.getenv(
    "RETELL_CALLS_FILENAME",
    os.path.join(RETELL_RESULTS_DIR, "retell_calls.json"),
)

if not os.path.exists(RETELL_RESULTS_DIR):
    os.makedirs(RETELL_RESULTS_DIR, exist_ok=True)

_RETELL_CALLS_LOCK = threading.Lock()

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


def _current_timestamp_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _load_retell_calls() -> Dict[str, Any]:
    if not os.path.exists(RETELL_CALLS_FILENAME):
        return {}

    try:
        with open(RETELL_CALLS_FILENAME, "r", encoding="utf-8") as file:
            data = json.load(file)
            if isinstance(data, dict):
                calls = data.get("calls")
                if isinstance(calls, dict):
                    return calls
    except json.JSONDecodeError:
        logger.error("Failed to decode %s; resetting call metadata store", RETELL_CALLS_FILENAME)

    return {}


def _save_retell_calls(calls: Dict[str, Any]) -> None:
    with open(RETELL_CALLS_FILENAME, "w", encoding="utf-8") as file:
        json.dump({"calls": calls}, file, indent=2)


def _upsert_retell_call_metadata(call_data: Dict[str, Any], status: Optional[str] = None) -> Dict[str, Any]:
    call_id = call_data.get("call_id")
    if not call_id:
        raise ValueError("call_data must include call_id")

    with _RETELL_CALLS_LOCK:
        calls = _load_retell_calls()
        existing = calls.get(call_id, {})

        merged: Dict[str, Any] = {
            **existing,
            "call_id": call_id,
            "agent_id": call_data.get("agent_id"),
            "agent_name": call_data.get("agent_name"),
            "user_phone_number": call_data.get("user_phone_number"),
            "start_timestamp": call_data.get("start_timestamp"),
            "end_timestamp": call_data.get("end_timestamp"),
            "recording_multi_channel_url": call_data.get("recording_multi_channel_url"),
            "analysis_status": status or existing.get("analysis_status", "pending"),
            "analysis_available": existing.get("analysis_available", False),
            "analysis_filename": existing.get("analysis_filename"),
        }

        if call_data.get("transcript_object") is not None:
            merged["transcript_available"] = True

        merged["last_updated"] = _current_timestamp_iso()
        calls[call_id] = merged
        _save_retell_calls(calls)

    return merged


def _update_retell_call_entry(call_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    with _RETELL_CALLS_LOCK:
        calls = _load_retell_calls()
        entry = calls.get(call_id)
        if entry is None:
            raise KeyError(f"Call {call_id} not found")

        entry.update(updates)
        entry["last_updated"] = _current_timestamp_iso()

        if "analysis_filename" in updates:
            entry["analysis_available"] = bool(updates.get("analysis_filename"))

        calls[call_id] = entry
        _save_retell_calls(calls)

        return entry


def _get_retell_call_entry(call_id: str) -> Optional[Dict[str, Any]]:
    with _RETELL_CALLS_LOCK:
        calls = _load_retell_calls()
        entry = calls.get(call_id)
    return entry


def _persist_retell_results(call_id: str, payload: Dict[str, Any]) -> str:
    """Persist processed Retell results locally for inspection."""
    output_path = os.path.join(RETELL_RESULTS_DIR, f"{call_id}.json")
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        logger.info("Saved Retell analysis to %s", output_path)
        return output_path
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("Failed to save Retell results for %s: %s", call_id, exc)
        raise


def _process_retell_call(call_payload: Dict[str, Any]) -> Dict[str, Any]:
    call_id = call_payload.get("call_id")
    if not call_id:
        logger.warning("Received Retell payload without call_id; skipping")
        raise ValueError("Missing call_id in Retell payload")

    try:
        call_data = call_payload
        if not call_data.get("recording_multi_channel_url"):
            call_data = get_retell_call_details(call_id)

        recording_url = call_data.get("recording_multi_channel_url")
        if not recording_url:
            logger.error("No recording URL available for call %s", call_id)
            raise RuntimeError("No recording URL available for this call")

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

        saved_path = _persist_retell_results(call_id, payload_to_store)
        try:
            _update_retell_call_entry(
                call_id,
                {
                    "analysis_status": "completed",
                    "analysis_filename": os.path.basename(saved_path),
                    "recording_multi_channel_url": recording_url,
                },
            )
        except KeyError:
            logger.warning("Retell call %s not found in metadata store while finalizing analysis", call_id)

        return payload_to_store

    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("Error processing Retell call %s: %s", call_id, exc)
        try:
            _update_retell_call_entry(
                call_id,
                {
                    "analysis_status": "error",
                    "error_message": str(exc),
                },
            )
        except KeyError:
            logger.warning("Retell call %s not found in metadata store while recording error", call_id)
        raise


@app.post("/retell/webhook")
async def retell_webhook(payload: Dict[str, Any]):
    """Endpoint to receive Retell call events and register them for analysis."""
    event = payload.get("event")
    call_data = payload.get("call")

    if event != "call_analyzed" or not isinstance(call_data, dict):
        logger.info("Ignoring Retell event %s", event)
        return JSONResponse(content={"success": True, "ignored": True})

    call_id = call_data.get("call_id")
    if not call_id:
        raise HTTPException(status_code=400, detail="Missing call_id in Retell payload")

    logger.info("Received call_analyzed webhook for call %s", call_id)
    try:
        metadata = _upsert_retell_call_metadata(call_data, status="pending")
    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("Failed to record Retell call metadata for %s: %s", call_id, exc)
        raise HTTPException(status_code=500, detail="Failed to record call metadata") from exc

    return JSONResponse(
        content={
            "success": True,
            "message": "Call registered",
            "call_id": call_id,
            "call_metadata": metadata,
        }
    )


@app.get("/retell/calls")
async def list_retell_calls():
    """Return available Retell calls registered via webhook."""
    calls = _load_retell_calls()
    sorted_calls = sorted(
        calls.values(),
        key=lambda entry: entry.get("start_timestamp") or 0,
        reverse=True,
    )
    return JSONResponse(content={"success": True, "calls": sorted_calls})


def _ensure_call_registered(call_id: str) -> Dict[str, Any]:
    call_entry = _get_retell_call_entry(call_id)
    if not call_entry:
        raise HTTPException(status_code=404, detail=f"Call {call_id} not found")
    return call_entry


def _prepare_retell_call_payload(call_entry: Dict[str, Any]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "call_id": call_entry["call_id"],
        "recording_multi_channel_url": call_entry.get("recording_multi_channel_url"),
    }
    return payload


@app.post("/retell/calls/{call_id}/analyze")
async def analyze_retell_call(call_id: str):
    """Trigger Hume analysis for a previously-registered Retell call."""
    call_entry = _ensure_call_registered(call_id)
    _update_retell_call_entry(call_id, {"analysis_status": "processing", "error_message": None})

    try:
        call_payload = _prepare_retell_call_payload(call_entry)
        analysis_payload = _process_retell_call(call_payload)
    except HTTPException:
        raise
    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("Failed to analyze Retell call %s: %s", call_id, exc)
        raise HTTPException(status_code=500, detail=f"Failed to analyze call: {exc}") from exc

    analysis_results = analysis_payload.get("analysis") or []
    first_result: Optional[Dict[str, Any]] = analysis_results[0] if analysis_results else None

    response_content: Dict[str, Any] = {
        "success": True,
        "call_id": call_id,
        "results": first_result,
        "retell_metadata": analysis_payload.get("retell_metadata"),
    }

    recording_url = analysis_payload.get("retell_metadata", {}).get("recording_multi_channel_url")
    if recording_url:
        response_content["recording_url"] = recording_url

    return JSONResponse(content=response_content)


@app.get("/retell/calls/{call_id}/analysis")
async def get_retell_call_analysis(call_id: str):
    """Return stored analysis for a Retell call if it has been processed."""
    call_entry = _ensure_call_registered(call_id)
    analysis_filename = call_entry.get("analysis_filename")
    if not analysis_filename:
        raise HTTPException(status_code=404, detail="Analysis not available for this call")

    analysis_path = os.path.join(RETELL_RESULTS_DIR, analysis_filename)
    if not os.path.exists(analysis_path):
        raise HTTPException(status_code=404, detail="Stored analysis file not found")

    with open(analysis_path, "r", encoding="utf-8") as file:
        payload = json.load(file)

    analysis_results = payload.get("analysis") or []
    first_result: Optional[Dict[str, Any]] = analysis_results[0] if analysis_results else None

    return JSONResponse(
        content={
            "success": True,
            "call_id": call_id,
            "results": first_result,
            "retell_metadata": payload.get("retell_metadata"),
            "recording_url": payload.get("retell_metadata", {}).get("recording_multi_channel_url"),
        }
    )


@app.get("/")
async def root():
    """Health check endpoint"""
    return {"message": "Hume Emotion Analysis API is running", "status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
