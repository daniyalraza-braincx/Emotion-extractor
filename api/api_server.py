import json
import logging
import os
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple

from fastapi import FastAPI, UploadFile, File, HTTPException, Query, Depends, status, Body
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
from dotenv import load_dotenv

load_dotenv()

from extractor import (
    analyze_audio_files,
    derive_short_call_title,
    download_retell_recording,
    extract_retell_transcript_segments,
    generate_call_purpose_from_summary,
    get_openai_client,
    get_retell_call_details,
    split_stereo_wav_channels,
)


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Authentication configuration
AUTH_USERNAME = os.getenv("AUTH_USERNAME", "admin")
AUTH_PASSWORD = os.getenv("AUTH_PASSWORD", "password")
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-secret-key-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24

security = HTTPBearer()

RETELL_RESULTS_DIR = os.getenv("RETELL_RESULTS_DIR", "retell_results")
RETELL_CALLS_FILENAME = os.getenv(
    "RETELL_CALLS_FILENAME",
    os.path.join(RETELL_RESULTS_DIR, "retell_calls.json"),
)
RETELL_AUDIO_DIR = os.path.join(RETELL_RESULTS_DIR, "audio")

if not os.path.exists(RETELL_RESULTS_DIR):
    os.makedirs(RETELL_RESULTS_DIR, exist_ok=True)

_RETELL_CALLS_LOCK = threading.Lock()
if not os.path.exists(RETELL_AUDIO_DIR):
    os.makedirs(RETELL_AUDIO_DIR, exist_ok=True)

app = FastAPI(title="Hume Emotion Analysis API")

# Enable CORS for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify your frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return encoded_jwt


def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Dict[str, Any]:
    """Verify JWT token and return payload"""
    try:
        token = credentials.credentials
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


@app.post("/auth/login")
async def login(credentials: Dict[str, str] = Body(...)):
    """Authenticate user and return JWT token"""
    username = credentials.get("username")
    password = credentials.get("password")
    
    if not username or not password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username and password are required"
        )
    
    if username == AUTH_USERNAME and password == AUTH_PASSWORD:
        access_token = create_access_token(data={"sub": username})
        return JSONResponse(content={
            "success": True,
            "access_token": access_token,
            "token_type": "bearer"
        })
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password"
        )


@app.get("/auth/verify")
async def verify_auth(token_data: Dict[str, Any] = Depends(verify_token)):
    """Verify if the current token is valid"""
    return JSONResponse(content={
        "success": True,
        "authenticated": True,
        "username": token_data.get("sub")
    })


@app.post("/auth/logout")
async def logout():
    """Logout endpoint (client-side token removal)"""
    return JSONResponse(content={"success": True, "message": "Logged out successfully"})


@app.post("/analyze")
async def analyze_audio(file: UploadFile = File(...), token_data: Dict[str, Any] = Depends(verify_token)):
    """
    Analyze audio file for emotion detection using Hume API.
    
    Returns:
        JSON with a top emotion per time segment for prosody and burst models.
    """
    try:
        # Read uploaded file
        file_content = await file.read()
        filename = file.filename or "uploaded_audio"
        
        file_contents = [(filename, file_content)]

        results = analyze_audio_files(file_contents, include_summary=True)

        if not results:
            raise HTTPException(
                status_code=404,
                detail="No emotion predictions found. The audio may not contain detectable speech.",
            )

        analysis_payload = results[0]
        analysis_payload.setdefault("metadata", {})["analysis_type"] = "custom_upload"

        return JSONResponse(
            content={
                "success": True,
                "filename": filename,
                "results": analysis_payload,
            }
        )
        
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


def _prune_zero_duration_calls(calls: Dict[str, Any]) -> Dict[str, Any]:
    removed_ids = [call_id for call_id, entry in calls.items() if _is_zero_duration_call(entry)]
    if not removed_ids:
        return calls

    for call_id in removed_ids:
        logger.info("Removing zero-duration Retell call %s from metadata store", call_id)
        calls.pop(call_id, None)

    _save_retell_calls(calls)
    return calls


def _load_retell_calls() -> Dict[str, Any]:
    if not os.path.exists(RETELL_CALLS_FILENAME):
        return {}

    try:
        with open(RETELL_CALLS_FILENAME, "r", encoding="utf-8") as file:
            data = json.load(file)
            if isinstance(data, dict):
                calls = data.get("calls")
                if isinstance(calls, dict):
                    return _prune_zero_duration_calls(dict(calls))
    except json.JSONDecodeError:
        logger.error("Failed to decode %s; resetting call metadata store", RETELL_CALLS_FILENAME)

    return {}


def _calculate_duration_ms(call_data: Dict[str, Any]) -> Optional[int]:
    duration_ms = call_data.get("duration_ms")
    if isinstance(duration_ms, (int, float)):
        return int(duration_ms)

    start_ts = call_data.get("start_timestamp")
    end_ts = call_data.get("end_timestamp")
    if isinstance(start_ts, (int, float)) and isinstance(end_ts, (int, float)):
        calculated = int(end_ts - start_ts)
        if calculated >= 0:
            return calculated
    return None


def _is_zero_duration_call(call_data: Dict[str, Any]) -> bool:
    duration_ms = _calculate_duration_ms(call_data) or 0
    return duration_ms <= 0


def _save_retell_calls(calls: Dict[str, Any]) -> None:
    with open(RETELL_CALLS_FILENAME, "w", encoding="utf-8") as file:
        json.dump({"calls": calls}, file, indent=2)


def _normalize_retell_payload(payload: Dict[str, Any]) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """
    Normalize Retell webhook payload to handle multiple formats:
    1. Direct Retell format with call wrapper: { "event": "call_analyzed", "call": {...} }
    2. Direct Retell format without wrapper: { "event": "call_analyzed", "call_id": "...", ... }
    3. n8n format: { "body": { "event": "call_analyzed", ...call data... } }
    
    Returns: (event, call_data) tuple
    """
    event = None
    call_data = None
    
    # Check for n8n format (body wrapper)
    if "body" in payload and isinstance(payload["body"], dict):
        body = payload["body"]
        event = body.get("event")
        # In n8n format, call data is directly in body - make a copy to avoid mutating original
        call_data = dict(body)
    else:
        # Direct Retell format
        event = payload.get("event")
        call_data_raw = payload.get("call")
        
        if isinstance(call_data_raw, dict):
            # Format 1: { "event": "call_analyzed", "call": {...} }
            call_data = dict(call_data_raw)
        elif "call_id" in payload or "recording_multi_channel_url" in payload:
            # Format 2: { "event": "call_analyzed", "call_id": "...", ... } - call data at top level
            call_data = dict(payload)
            # Remove event from call_data since it's not part of call metadata
            call_data.pop("event", None)
        else:
            # Fallback: use call_data_raw as-is (might be None)
            call_data = call_data_raw
    
    # Normalize call_data structure
    if isinstance(call_data, dict):
        # If in_voicemail is at top level, ensure it's in call_analysis
        if "in_voicemail" in call_data:
            if "call_analysis" not in call_data:
                call_data["call_analysis"] = {}
            if "in_voicemail" not in call_data["call_analysis"]:
                call_data["call_analysis"]["in_voicemail"] = call_data["in_voicemail"]
        
        # If call_summary is at top level, ensure it's in call_analysis (if call_analysis exists)
        if "call_summary" in call_data:
            if "call_analysis" not in call_data:
                call_data["call_analysis"] = {}
            # Only set if not already present in call_analysis
            if "call_summary" not in call_data["call_analysis"]:
                call_data["call_analysis"]["call_summary"] = call_data["call_summary"]
    
    return event, call_data


def _evaluate_call_constraints(call_data: Dict[str, Any]) -> Dict[str, Any]:
    """Determine if a call should be excluded from analysis."""
    call_analysis = call_data.get("call_analysis") or {}
    transcript_text = call_data.get("transcript") or ""
    disconnection_reason = (
        call_data.get("disconnection_reason")
        or call_data.get("end_reason")
        or ""
    )

    duration_ms = _calculate_duration_ms(call_data)

    too_short = duration_ms is not None and duration_ms < 15_000

    call_summary = ""
    if isinstance(call_analysis, dict):
        call_summary = call_analysis.get("call_summary") or ""

    transcript_lower = transcript_text.lower() if isinstance(transcript_text, str) else ""
    summary_lower = call_summary.lower() if isinstance(call_summary, str) else ""
    disconnection_lower = disconnection_reason.lower()

    transcript_mentions_voicemail = "voicemail" in transcript_lower
    summary_mentions_voicemail = "voicemail" in summary_lower
    disconnection_mentions_voicemail = "voicemail" in disconnection_lower

    transcript_mentions_leave_message = "leave a message" in transcript_lower or "leave me a message" in transcript_lower
    summary_mentions_leave_message = "leave a message" in summary_lower or "leave me a message" in summary_lower

    # Check both call_analysis.in_voicemail and top-level in_voicemail
    in_voicemail_flag = bool(
        call_analysis.get("in_voicemail") or call_data.get("in_voicemail")
    )

    voicemail_detected = any([
        in_voicemail_flag,
        summary_mentions_voicemail,
        transcript_mentions_voicemail,
        disconnection_mentions_voicemail,
        transcript_mentions_leave_message,
        summary_mentions_leave_message,
    ])

    analysis_allowed = True
    block_reason = None
    if voicemail_detected:
        analysis_allowed = False
        block_reason = "Call reached voicemail; cannot analyze emotions."
    elif too_short:
        analysis_allowed = False
        block_reason = "Call too short, insufficient audio for analysis."

    constraints_detail = {
        "voicemail_detected": voicemail_detected,
        "voicemail_flags": {
            "in_voicemail": in_voicemail_flag,
            "summary_mentions_voicemail": summary_mentions_voicemail,
            "transcript_mentions_voicemail": transcript_mentions_voicemail,
            "disconnection_reason": disconnection_reason or None,
            "summary_mentions_leave_message": summary_mentions_leave_message,
            "transcript_mentions_leave_message": transcript_mentions_leave_message,
        },
        "too_short": too_short,
        "duration_ms": duration_ms,
    }

    return {
        "analysis_allowed": analysis_allowed,
        "analysis_block_reason": block_reason,
        "constraints": constraints_detail,
    }


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
            "duration_ms": call_data.get("duration_ms") or existing.get("duration_ms"),
        }

        duration_ms = _calculate_duration_ms(merged)
        if duration_ms is not None:
            merged["duration_ms"] = duration_ms

        if duration_ms is not None and duration_ms <= 0:
            logger.info("Skipping Retell call %s due to zero duration", call_id)
            zero_duration_response = {
                **merged,
                "duration_ms": 0,
                "analysis_allowed": False,
                "analysis_block_reason": "Call contains no audio (duration 0s).",
                "analysis_status": "blocked",
                "analysis_available": False,
                "analysis_filename": None,
                "error_message": None,
            }
            if call_id in calls:
                calls.pop(call_id)
                _save_retell_calls(calls)
            return zero_duration_response

        call_summary_text: Optional[str] = None
        call_analysis = call_data.get("call_analysis")
        if isinstance(call_analysis, dict):
            summary_candidate = call_analysis.get("call_summary") or call_analysis.get("summary")
            if isinstance(summary_candidate, str) and summary_candidate.strip():
                call_summary_text = summary_candidate.strip()
        if not call_summary_text:
            for key in ("summary", "call_summary"):
                summary_candidate = call_data.get(key)
                if isinstance(summary_candidate, str) and summary_candidate.strip():
                    call_summary_text = summary_candidate.strip()
                    break

        llm_client = None

        if call_summary_text:
            merged["call_summary"] = call_summary_text
            if not merged.get("call_purpose"):
                llm_client = llm_client or get_openai_client()
                purpose = generate_call_purpose_from_summary(call_summary_text, openai_client=llm_client)
                if purpose:
                    merged["call_purpose"] = purpose

        if not merged.get("call_title"):
            call_title = derive_short_call_title(
                call_data,
                fallback_summary=call_summary_text,
            )
            if call_title:
                merged["call_title"] = call_title

        constraints = _evaluate_call_constraints(call_data)
        merged["analysis_allowed"] = constraints["analysis_allowed"]
        merged["analysis_block_reason"] = constraints["analysis_block_reason"]
        merged["analysis_constraints"] = constraints["constraints"]
        if not constraints["analysis_allowed"]:
            merged["analysis_status"] = "blocked"
            merged["error_message"] = None
        else:
            merged["error_message"] = existing.get("error_message")

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

        if entry.get("analysis_allowed") is False:
            entry.setdefault("analysis_status", "blocked")
            entry["error_message"] = None

        calls[call_id] = entry
        _save_retell_calls(calls)

        return entry


def _get_retell_call_entry(call_id: str) -> Optional[Dict[str, Any]]:
    with _RETELL_CALLS_LOCK:
        calls = _load_retell_calls()
        entry = calls.get(call_id)
    return entry


def _refresh_call_metadata(call_id: str) -> Dict[str, Any]:
    with _RETELL_CALLS_LOCK:
        calls = _load_retell_calls()
        entry = calls.get(call_id)
        if entry is None:
            raise KeyError(f"Call {call_id} not found")

        detailed_data = get_retell_call_details(call_id)
        constraint_info = _evaluate_call_constraints(detailed_data)

        updated_entry = {
            **entry,
            "call_id": call_id,
            "agent_id": detailed_data.get("agent_id"),
            "agent_name": detailed_data.get("agent_name"),
            "user_phone_number": detailed_data.get("user_phone_number"),
            "start_timestamp": detailed_data.get("start_timestamp"),
            "end_timestamp": detailed_data.get("end_timestamp"),
            "duration_ms": detailed_data.get("duration_ms"),
            "recording_multi_channel_url": detailed_data.get("recording_multi_channel_url"),
            "analysis_allowed": constraint_info["analysis_allowed"],
            "analysis_block_reason": constraint_info["analysis_block_reason"],
            "analysis_constraints": constraint_info["constraints"],
        }

        if not constraint_info["analysis_allowed"]:
            updated_entry["analysis_status"] = "blocked"
            updated_entry["error_message"] = None
        else:
            updated_entry["analysis_status"] = updated_entry.get("analysis_status", "pending")
            updated_entry["analysis_block_reason"] = None

        fallback_summary = None
        call_analysis = detailed_data.get("call_analysis")
        if isinstance(call_analysis, dict):
            fallback_summary = call_analysis.get("call_summary") or call_analysis.get("summary")

        if not fallback_summary:
            fallback_summary = detailed_data.get("call_summary") or detailed_data.get("summary")

        if fallback_summary:
            purpose = generate_call_purpose_from_summary(fallback_summary)
            if purpose:
                updated_entry["call_purpose"] = purpose

        updated_entry["last_updated"] = _current_timestamp_iso()
        calls[call_id] = updated_entry
        _save_retell_calls(calls)

    return updated_entry


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


def _extract_overall_emotion_from_results(
    analysis_results: Optional[List[Dict[str, Any]]],
) -> Optional[Dict[str, Any]]:
    if not analysis_results:
        return None

    for result in analysis_results:
        if not isinstance(result, dict):
            continue
        metadata = result.get("metadata")
        if not isinstance(metadata, dict):
            continue
        overall_emotion = metadata.get("overall_call_emotion")
        if isinstance(overall_emotion, dict) and overall_emotion:
            return overall_emotion

        overall_status = metadata.get("overall_call_status")
        if isinstance(overall_status, dict) and overall_status:
            return overall_status

    return None


def _load_overall_emotion_for_call(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    analysis_filename = entry.get("analysis_filename")
    if not analysis_filename:
        return None

    analysis_path = os.path.join(RETELL_RESULTS_DIR, analysis_filename)
    if not os.path.exists(analysis_path):
        return None

    try:
        with open(analysis_path, "r", encoding="utf-8") as file:
            payload = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read analysis for %s: %s", entry.get("call_id"), exc)
        return None

    analysis_results = payload.get("analysis")
    if not isinstance(analysis_results, list):
        return None

    return _extract_overall_emotion_from_results(analysis_results)


def _merge_channel_results(
    call_identifier: str,
    channel_results: list,
    transcript_data: Optional[list],
) -> Dict[str, Any]:
    """Combine per-channel analysis outputs into a single multi-speaker result."""
    combined_prosody = []
    combined_burst = []
    combined_metadata: Dict[str, Any] = {}
    summary_value = None
    base_metadata_copied = False

    for result in channel_results:
        filename = (result.get("filename") or "").lower()
        speaker = "Agent"
        if "_user" in filename or "customer" in filename:
            speaker = "Customer"
        elif "_agent" in filename:
            speaker = "Agent"
        else:
            speaker = result.get("prosody", [{}])[0].get("speaker") or speaker

        if summary_value is None and result.get("summary"):
            summary_value = result.get("summary")

        metadata = result.get("metadata") or {}
        combined_metadata.setdefault(speaker.lower(), metadata)

        for segment in result.get("prosody", []):
            segment_copy = {
                **segment,
                "speaker": speaker,
                "top_emotions": [
                    dict(emotion) for emotion in segment.get("top_emotions", [])
                ],
            }
            combined_prosody.append(segment_copy)

        for segment in result.get("burst", []):
            segment_copy = {
                **segment,
                "speaker": speaker,
                "top_emotions": [
                    dict(emotion) for emotion in segment.get("top_emotions", [])
                ],
            }
            combined_burst.append(segment_copy)

        if not base_metadata_copied and metadata:
            combined_metadata.update(metadata)
            base_metadata_copied = True

    combined_prosody.sort(key=lambda seg: seg.get("time_start") or 0)
    combined_burst.sort(key=lambda seg: seg.get("time_start") or 0)

    combined_metadata["retell_transcript_segments"] = transcript_data or []
    combined_metadata["retell_call_id"] = call_identifier
    combined_metadata["retell_transcript_available"] = bool(transcript_data)

    combined_result = {
        "filename": f"{call_identifier}_combined",
        "prosody": combined_prosody,
        "burst": combined_burst,
        "metadata": combined_metadata,
    }

    if summary_value:
        combined_result["summary"] = summary_value

    overall_status = None
    for channel_result in channel_results:
        metadata = channel_result.get("metadata") or {}
        candidate = metadata.get("overall_call_status")
        if candidate:
            overall_status = dict(candidate)
            break

    if overall_status:
        combined_result.setdefault("metadata", {})["overall_call_status"] = overall_status

    return combined_result


def _process_retell_call(call_payload: Dict[str, Any]) -> Dict[str, Any]:
    call_id = call_payload.get("call_id")
    if not call_id:
        logger.warning("Received Retell payload without call_id; skipping")
        raise ValueError("Missing call_id in Retell payload")

    try:
        call_data = dict(call_payload)
        detailed_data: Optional[Dict[str, Any]] = None
        try:
            detailed_data = get_retell_call_details(call_id)
        except Exception as fetch_exc:  # pylint: disable=broad-except
            logger.warning("Could not fetch detailed Retell data for %s: %s", call_id, fetch_exc)

        if detailed_data:
            merged_data = dict(detailed_data)
            merged_data.update({k: v for k, v in call_data.items() if v is not None})
            call_data = merged_data

        call_summary_text: Optional[str] = None
        call_analysis = call_data.get("call_analysis")
        if isinstance(call_analysis, dict):
            summary_candidate = call_analysis.get("call_summary") or call_analysis.get("summary")
            if isinstance(summary_candidate, str) and summary_candidate.strip():
                call_summary_text = summary_candidate.strip()
        if not call_summary_text:
            for key in ("summary", "call_summary"):
                candidate = call_data.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    call_summary_text = candidate.strip()
                    break

        if not call_data.get("recording_multi_channel_url"):
            logger.error("No recording URL available for call %s", call_id)
            raise RuntimeError("No recording URL available for this call")

        constraint_info = _evaluate_call_constraints(call_data)
        metadata_updates = {
            "analysis_allowed": constraint_info["analysis_allowed"],
            "analysis_block_reason": constraint_info["analysis_block_reason"],
            "analysis_constraints": constraint_info["constraints"],
            "start_timestamp": call_data.get("start_timestamp"),
            "end_timestamp": call_data.get("end_timestamp"),
            "duration_ms": call_data.get("duration_ms"),
            "agent_id": call_data.get("agent_id"),
            "agent_name": call_data.get("agent_name"),
        }

        if call_summary_text:
            metadata_updates["call_summary"] = call_summary_text
            purpose = generate_call_purpose_from_summary(call_summary_text)
            if purpose:
                metadata_updates["call_purpose"] = purpose

        call_title = derive_short_call_title(
            call_data,
            fallback_summary=call_summary_text,
        )
        if call_title:
            metadata_updates["call_title"] = call_title

        if not constraint_info["analysis_allowed"]:
            metadata_updates["analysis_status"] = "blocked"
            metadata_updates["error_message"] = None

        try:
            _update_retell_call_entry(call_id, metadata_updates)
        except KeyError:
            logger.warning("Retell call %s not found in metadata store when updating constraints", call_id)

        if not constraint_info["analysis_allowed"]:
            raise HTTPException(
                status_code=400,
                detail=constraint_info["analysis_block_reason"] or "Call cannot be analyzed.",
            )

        recording_url = call_data.get("recording_multi_channel_url")

        filename_hint = f"{call_id}.wav"
        audio_filename, audio_bytes = download_retell_recording(recording_url, filename_hint)

        try:
            user_audio, agent_audio = split_stereo_wav_channels(audio_bytes)
            agent_path = os.path.join(RETELL_AUDIO_DIR, f"{call_id}_agent.wav")
            user_path = os.path.join(RETELL_AUDIO_DIR, f"{call_id}_user.wav")
            with open(agent_path, "wb") as agent_f:
                agent_f.write(agent_audio)
            with open(user_path, "wb") as user_f:
                user_f.write(user_audio)
            logger.info("Saved channel audio for call %s to %s and %s", call_id, agent_path, user_path)
            file_contents = [
                (f"{call_id}_user.wav", user_audio),
                (f"{call_id}_agent.wav", agent_audio),
            ]
        except Exception as channel_err:  # pylint: disable=broad-except
            logger.warning("Could not split channels for call %s: %s", call_id, channel_err)
            file_contents = [(audio_filename, audio_bytes)]

        transcript_segments = extract_retell_transcript_segments(call_data)

        dynamic_variables = call_data.get("retell_llm_dynamic_variables") or {}
        retell_metadata = {
            "retell_call_id": call_id,
            "recording_multi_channel_url": recording_url,
            "start_timestamp": call_data.get("start_timestamp"),
            "end_timestamp": call_data.get("end_timestamp"),
            "duration_ms": call_data.get("duration_ms"),
            "agent": {
                "id": call_data.get("agent_id"),
                "name": call_data.get("agent_name"),
                "version": call_data.get("agent_version"),
            },
            "customer": {
                "first_name": dynamic_variables.get("first_name") or call_data.get("customer_name"),
                "program": dynamic_variables.get("program"),
                "lead_status": dynamic_variables.get("lead_status"),
                "university": dynamic_variables.get("university"),
            },
            "analysis_constraints": constraint_info["constraints"],
        }

        analysis_results = analyze_audio_files(
            file_contents,
            include_summary=True,
            retell_call_id=call_id,
            retell_transcript=transcript_segments,
            retell_metadata=retell_metadata,
        )

        if len(analysis_results) >= 2:
            combined_result = _merge_channel_results(call_id, analysis_results, transcript_segments)
            analysis_results.insert(0, combined_result)

        overall_emotion = _extract_overall_emotion_from_results(analysis_results)

        analysis_summary: Optional[str] = None
        for result in analysis_results:
            if isinstance(result, dict):
                summary_candidate = result.get("summary")
                if isinstance(summary_candidate, str) and summary_candidate.strip():
                    analysis_summary = summary_candidate.strip()
                    break

        payload_to_store = {
            "call_id": call_id,
            "retell_metadata": retell_metadata,
            "analysis": analysis_results
        }

        saved_path = _persist_retell_results(call_id, payload_to_store)
        try:
            final_updates: Dict[str, Any] = {
                "analysis_status": "completed",
                "analysis_filename": os.path.basename(saved_path),
                "recording_multi_channel_url": recording_url,
            }

            if overall_emotion:
                final_updates["overall_emotion"] = overall_emotion
                final_updates["overall_emotion_label"] = overall_emotion.get("label")

            try:
                existing_entry = _get_retell_call_entry(call_id)
            except KeyError:
                existing_entry = None

            openai_client = None
            fallback_summary = analysis_summary or call_summary_text

            if analysis_summary and (not existing_entry or not existing_entry.get("call_summary")):
                final_updates["call_summary"] = analysis_summary

            needs_title = not existing_entry or not existing_entry.get("call_title")
            if needs_title and fallback_summary:
                openai_client = openai_client or get_openai_client()
                derived_title = derive_short_call_title(
                    call_data,
                    fallback_summary=fallback_summary,
                    openai_client=openai_client,
                )
                if derived_title:
                    final_updates["call_title"] = derived_title

            needs_purpose = not existing_entry or not existing_entry.get("call_purpose")
            if needs_purpose and fallback_summary:
                openai_client = openai_client or get_openai_client()
                purpose = generate_call_purpose_from_summary(fallback_summary, openai_client=openai_client)
                if purpose:
                    final_updates["call_purpose"] = purpose

            _update_retell_call_entry(
                call_id,
                final_updates,
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
    """
    Endpoint to receive Retell call events and register them for analysis.
    
    Supports two payload formats:
    1. Direct Retell format: { "event": "call_analyzed", "call": {...} }
    2. n8n format: { "body": { "event": "call_analyzed", ...call data... } }
    """
    event, call_data = _normalize_retell_payload(payload)

    if event != "call_analyzed" or not isinstance(call_data, dict):
        logger.info("Ignoring Retell event %s (call_data type: %s)", event, type(call_data).__name__)
        if event == "call_analyzed" and not isinstance(call_data, dict):
            logger.warning("call_analyzed event received but call_data is not a dict. Payload keys: %s", list(payload.keys())[:10])
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
async def list_retell_calls(token_data: Dict[str, Any] = Depends(verify_token)):
    """Return available Retell calls registered via webhook."""
    calls = _load_retell_calls()
    filtered_calls = [
        entry for entry in calls.values()
        if not _is_zero_duration_call(entry)
    ]
    sorted_calls = sorted(
        filtered_calls,
        key=lambda entry: entry.get("start_timestamp") or 0,
        reverse=True,
    )
    enriched_calls = []
    for entry in sorted_calls:
        call_entry = dict(entry)
        if call_entry.get("analysis_status") == "completed":
            overall_emotion = call_entry.get("overall_emotion")
            if not isinstance(overall_emotion, dict):
                overall_emotion = _load_overall_emotion_for_call(call_entry)
                if overall_emotion:
                    call_entry["overall_emotion"] = overall_emotion
                    call_entry["overall_emotion_label"] = overall_emotion.get("label")
                    call_id = call_entry.get("call_id")
                    if call_id:
                        try:
                            _update_retell_call_entry(
                                call_id,
                                {
                                    "overall_emotion": overall_emotion,
                                    "overall_emotion_label": overall_emotion.get("label"),
                                },
                            )
                        except KeyError:
                            logger.warning("Call %s missing when caching overall emotion", call_id)
            else:
                label = call_entry.get("overall_emotion_label")
                if not label:
                    call_entry["overall_emotion_label"] = overall_emotion.get("label")
        enriched_calls.append(call_entry)

    return JSONResponse(content={"success": True, "calls": enriched_calls})


@app.post("/retell/calls/refresh")
async def refresh_retell_calls(call_id: Optional[str] = None, token_data: Dict[str, Any] = Depends(verify_token)):
    """
    Re-evaluate stored call metadata (voicemail detection, duration, etc.).
    If call_id is provided, refresh only that call; otherwise refresh all.
    """
    refreshed = []
    errors: Dict[str, str] = {}

    with _RETELL_CALLS_LOCK:
        calls = _load_retell_calls()
        target_ids = [call_id] if call_id else list(calls.keys())

    for cid in target_ids:
        try:
            entry = _refresh_call_metadata(cid)
            refreshed.append(entry)
        except Exception as exc:  # pylint: disable=broad-except
            errors[cid] = str(exc)

    return JSONResponse(
        content={
            "success": len(errors) == 0,
            "refreshed_count": len(refreshed),
            "errors": errors,
            "calls": refreshed if call_id else None,
        }
    )


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
async def analyze_retell_call(call_id: str, force: bool = Query(False), token_data: Dict[str, Any] = Depends(verify_token)):
    """Trigger Hume analysis for a previously-registered Retell call."""
    call_entry = _ensure_call_registered(call_id)
    if call_entry.get("analysis_allowed") is False:
        reason = call_entry.get("analysis_block_reason") or "Call cannot be analyzed."
        raise HTTPException(
            status_code=400,
            detail=reason,
        )

    if not force:
        try:
            return await get_retell_call_analysis(call_id)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise

    if force:
        logger.info("Force re-running analysis for Retell call %s", call_id)

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
async def get_retell_call_analysis(call_id: str, token_data: Dict[str, Any] = Depends(verify_token)):
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
    if analysis_results and len(analysis_results) >= 2:
        first_filename = (analysis_results[0].get("filename") or "").lower()
        if "_combined" not in first_filename:
            transcript_segments = None
            for result in analysis_results:
                metadata = result.get("metadata") or {}
                segments = metadata.get("retell_transcript_segments")
                if segments:
                    transcript_segments = segments
                    break
            combined_result = _merge_channel_results(call_id, analysis_results, transcript_segments)
            analysis_results.insert(0, combined_result)
            payload["analysis"] = analysis_results
            _persist_retell_results(call_id, payload)

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
