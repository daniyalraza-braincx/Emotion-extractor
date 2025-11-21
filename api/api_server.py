
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple

from fastapi import FastAPI, UploadFile, File, HTTPException, Query, Depends, status, Body, BackgroundTasks
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
from dotenv import load_dotenv
from sqlalchemy.orm import Session
from sqlalchemy import and_

load_dotenv()

from extractor import (
    analyze_audio_files,
    derive_short_call_title,
    download_retell_recording,
    extract_retell_transcript_segments,
    generate_call_purpose_from_summary,
    get_openai_client,
    get_retell_call_details,
)
from database import (
    get_db, Call, EmotionSegment, EmotionPrediction, 
    TranscriptSegment, AnalysisSummary, SessionLocal
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


def _get_all_calls_dict(db: Session) -> Dict[str, Any]:
    """Get all calls from database as dictionary format."""
    calls = db.query(Call).all()
    return {call.call_id: call.to_dict() for call in calls}


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
    """
    Check if a call has zero or negative duration.
    Returns False if duration is None (unknown) - only removes calls with explicitly zero/negative duration.
    """
    duration_ms = _calculate_duration_ms(call_data)
    # Only consider it zero-duration if we have an explicit value that is <= 0
    # Don't remove calls with None duration (unknown duration) as they might be valid
    if duration_ms is None:
        return False
    return duration_ms <= 0


# _save_retell_calls removed - using database directly


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


def _strip_words_from_transcript(transcript_object: Any) -> Any:
    """Remove words array from transcript segments to reduce storage size.
    
    Keeps only essential fields: speaker, start, end, content/text, confidence.
    """
    if not isinstance(transcript_object, list):
        return transcript_object
    
    cleaned_transcript = []
    for segment in transcript_object:
        if not isinstance(segment, dict):
            cleaned_transcript.append(segment)
            continue
        
        # Create a copy without words array
        cleaned_segment = {k: v for k, v in segment.items() if k != "words"}
        cleaned_transcript.append(cleaned_segment)
    
    return cleaned_transcript


def _upsert_retell_call_metadata(db: Session, call_data: Dict[str, Any], status: Optional[str] = None) -> Dict[str, Any]:
    call_id = call_data.get("call_id")
    if not call_id:
        raise ValueError("call_data must include call_id")

    # Get existing call or create new
    existing_call = db.query(Call).filter(Call.call_id == call_id).first()
    
    duration_ms = call_data.get("duration_ms")
    if duration_ms is None:
        duration_ms = _calculate_duration_ms(call_data)
    
    if duration_ms is not None and duration_ms <= 0:
        logger.info("Skipping Retell call %s due to zero duration", call_id)
        if existing_call:
            db.delete(existing_call)
            db.commit()
        return {
            "call_id": call_id,
            "duration_ms": 0,
            "analysis_allowed": False,
            "analysis_block_reason": "Call contains no audio (duration 0s).",
            "analysis_status": "blocked",
            "analysis_available": False,
            "error_message": None,
        }

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

    if existing_call:
        # Update existing call
        call = existing_call
        call.agent_id = call_data.get("agent_id") or call.agent_id
        call.agent_name = call_data.get("agent_name") or call.agent_name
        call.user_phone_number = call_data.get("user_phone_number") or call.user_phone_number
        call.start_timestamp = call_data.get("start_timestamp") or call.start_timestamp
        call.end_timestamp = call_data.get("end_timestamp") or call.end_timestamp
        call.recording_multi_channel_url = call_data.get("recording_multi_channel_url") or call.recording_multi_channel_url
        call.analysis_status = status or call.analysis_status
        call.duration_ms = duration_ms or call.duration_ms
    else:
        # Create new call
        call = Call(
            call_id=call_id,
            agent_id=call_data.get("agent_id"),
            agent_name=call_data.get("agent_name"),
            user_phone_number=call_data.get("user_phone_number"),
            start_timestamp=call_data.get("start_timestamp"),
            end_timestamp=call_data.get("end_timestamp"),
            recording_multi_channel_url=call_data.get("recording_multi_channel_url"),
            analysis_status=status or "pending",
            duration_ms=duration_ms,
        )
        db.add(call)

    if call_summary_text:
        call.call_summary = call_summary_text
        if not call.call_purpose:
            llm_client = get_openai_client()
            purpose = generate_call_purpose_from_summary(call_summary_text, openai_client=llm_client)
            if purpose:
                call.call_purpose = purpose

    if not call.call_title:
        call_title = derive_short_call_title(call_data, fallback_summary=call_summary_text)
        if call_title:
            call.call_title = call_title

    constraints = _evaluate_call_constraints(call_data)
    call.analysis_allowed = constraints["analysis_allowed"]
    call.analysis_block_reason = constraints["analysis_block_reason"]
    call.analysis_constraints = constraints["constraints"]
    if not constraints["analysis_allowed"]:
        call.analysis_status = "blocked"
        call.error_message = None

    # Store transcript_object if available
    transcript_object = call_data.get("transcript_object")
    if transcript_object is not None:
        call.transcript_available = True
        call.transcript_object = _strip_words_from_transcript(transcript_object)
    elif existing_call and existing_call.transcript_object is not None:
        call.transcript_object = _strip_words_from_transcript(existing_call.transcript_object)
        call.transcript_available = True

    db.commit()
    db.refresh(call)
    return call.to_dict()


def _update_retell_call_entry(db: Session, call_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    call = db.query(Call).filter(Call.call_id == call_id).first()
    if call is None:
        raise KeyError(f"Call {call_id} not found")

    # Update fields
    for key, value in updates.items():
        if hasattr(call, key):
            if value is not None or key in ["analysis_status", "error_message", "analysis_allowed", "analysis_block_reason"]:
                setattr(call, key, value)

    # analysis_available is set directly in updates, no need for filename check

    if call.analysis_allowed is False:
        call.analysis_status = "blocked"
        call.error_message = None

    db.commit()
    db.refresh(call)
    return call.to_dict()


def _get_retell_call_entry(db: Session, call_id: str) -> Optional[Dict[str, Any]]:
    call = db.query(Call).filter(Call.call_id == call_id).first()
    return call.to_dict() if call else None


def _refresh_call_metadata(db: Session, call_id: str) -> Dict[str, Any]:
    call = db.query(Call).filter(Call.call_id == call_id).first()
    if call is None:
        raise KeyError(f"Call {call_id} not found")

    detailed_data = get_retell_call_details(call_id)
    constraint_info = _evaluate_call_constraints(detailed_data)

    call.agent_id = detailed_data.get("agent_id") or call.agent_id
    call.agent_name = detailed_data.get("agent_name") or call.agent_name
    call.user_phone_number = detailed_data.get("user_phone_number") or call.user_phone_number
    call.start_timestamp = detailed_data.get("start_timestamp") or call.start_timestamp
    call.end_timestamp = detailed_data.get("end_timestamp") or call.end_timestamp
    call.duration_ms = detailed_data.get("duration_ms") or call.duration_ms
    call.recording_multi_channel_url = detailed_data.get("recording_multi_channel_url") or call.recording_multi_channel_url
    call.analysis_allowed = constraint_info["analysis_allowed"]
    call.analysis_block_reason = constraint_info["analysis_block_reason"]
    call.analysis_constraints = constraint_info["constraints"]

    if not constraint_info["analysis_allowed"]:
        call.analysis_status = "blocked"
        call.error_message = None
    else:
        if call.analysis_status == "blocked":
            call.analysis_status = "pending"
        call.analysis_block_reason = None

    fallback_summary = None
    call_analysis = detailed_data.get("call_analysis")
    if isinstance(call_analysis, dict):
        fallback_summary = call_analysis.get("call_summary") or call_analysis.get("summary")

    if not fallback_summary:
        fallback_summary = detailed_data.get("call_summary") or detailed_data.get("summary")

    if fallback_summary:
        purpose = generate_call_purpose_from_summary(fallback_summary)
        if purpose:
            call.call_purpose = purpose

    db.commit()
    db.refresh(call)
    return call.to_dict()


def _persist_retell_results(db: Session, call_id: str, analysis_results: List[Dict[str, Any]], retell_metadata: Dict[str, Any]) -> None:
    """Persist processed Retell results to database."""
    try:
        # Delete existing analysis data for this call
        db.query(EmotionSegment).filter(EmotionSegment.call_id == call_id).delete()
        db.query(TranscriptSegment).filter(TranscriptSegment.call_id == call_id).delete()
        db.query(AnalysisSummary).filter(AnalysisSummary.call_id == call_id).delete()
        
        # Process each analysis result
        for result in analysis_results:
            if not isinstance(result, dict):
                continue
            
            # Migrate prosody segments
            prosody_segments = result.get("prosody", [])
            for segment_data in prosody_segments:
                _save_emotion_segment(db, call_id, segment_data, "prosody")
            
            # Migrate burst segments
            burst_segments = result.get("burst", [])
            for segment_data in burst_segments:
                _save_emotion_segment(db, call_id, segment_data, "burst")
            
            # Migrate transcript segments from metadata
            metadata = result.get("metadata", {})
            transcript_segments = metadata.get("retell_transcript_segments", [])
            for transcript_data in transcript_segments:
                _save_transcript_segment(db, call_id, transcript_data)
            
            # Migrate summary
            summary_text = result.get("summary")
            if summary_text:
                _save_analysis_summary(db, call_id, summary_text, "openai")
        
        db.commit()
        logger.info("Saved Retell analysis to database for call %s", call_id)
    except Exception as exc:  # pylint: disable=broad-except
        db.rollback()
        logger.error("Failed to save Retell results for %s: %s", call_id, exc)
        raise


def _save_emotion_segment(db: Session, call_id: str, segment_data: Dict[str, Any], segment_type: str):
    """Save a single emotion segment to database."""
    time_start = segment_data.get("time_start", 0.0)
    time_end = segment_data.get("time_end", 0.0)
    
    segment = EmotionSegment(
        call_id=call_id,
        segment_type=segment_type,
        time_start=float(time_start) if time_start is not None else 0.0,
        time_end=float(time_end) if time_end is not None else 0.0,
        speaker=segment_data.get("speaker"),
        text=segment_data.get("text"),
        transcript_text=segment_data.get("transcript_text"),
        primary_category=segment_data.get("primary_category"),
        source=segment_data.get("source", segment_type),
    )
    
    db.add(segment)
    db.flush()  # Flush to get segment.id
    
    # Save emotion predictions
    top_emotions = segment_data.get("top_emotions", [])
    for rank, emotion_data in enumerate(top_emotions, start=1):
        if not isinstance(emotion_data, dict):
            continue
        
        prediction = EmotionPrediction(
            segment_id=segment.id,
            emotion_name=emotion_data.get("name", "Unknown"),
            score=float(emotion_data.get("score", 0.0)),
            percentage=float(emotion_data.get("percentage", 0.0)),
            category=emotion_data.get("category", "neutral"),
            rank=rank,
        )
        db.add(prediction)


def _save_transcript_segment(db: Session, call_id: str, transcript_data: Dict[str, Any]):
    """Save a single transcript segment to database."""
    start_time = transcript_data.get("start", 0.0)
    end_time = transcript_data.get("end", 0.0)
    speaker = transcript_data.get("speaker")
    text = transcript_data.get("text", "")
    
    segment = TranscriptSegment(
        call_id=call_id,
        speaker=speaker or "Unknown",
        start_time=float(start_time) if start_time is not None else 0.0,
        end_time=float(end_time) if end_time is not None else 0.0,
        text=text,
        confidence=transcript_data.get("confidence"),
    )
    db.add(segment)


def _save_analysis_summary(db: Session, call_id: str, summary_text: str, summary_type: str):
    """Save analysis summary to database."""
    summary = AnalysisSummary(
        call_id=call_id,
        summary_text=summary_text,
        summary_type=summary_type,
    )
    db.add(summary)


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


def _load_overall_emotion_for_call(db: Session, call_id: str) -> Optional[Dict[str, Any]]:
    """Load overall emotion from call's overall_emotion_json field."""
    call = db.query(Call).filter(Call.call_id == call_id).first()
    if not call or not call.overall_emotion_json:
        return None
    return call.overall_emotion_json


def _process_retell_call(db: Session, call_payload: Dict[str, Any]) -> Dict[str, Any]:
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
            # Only update with non-null values from call_data, preserving existing metadata
            merged_data.update({k: v for k, v in call_data.items() if v is not None})
            call_data = merged_data
        else:
            # If we can't fetch from Retell API, preserve existing metadata from call_payload
            # Don't overwrite existing values with nulls
            for key in ["start_timestamp", "end_timestamp", "duration_ms", "agent_id", "agent_name", "user_phone_number"]:
                if call_data.get(key) is None and call_payload.get(key) is not None:
                    call_data[key] = call_payload[key]

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
        
        # Get existing entry to preserve metadata
        existing_entry = _get_retell_call_entry(db, call_id)
        
        # Helper to preserve existing values if new value is None
        def preserve_or_update(key: str):
            new_val = call_data.get(key)
            if new_val is not None:
                return new_val
            if existing_entry and existing_entry.get(key) is not None:
                return existing_entry.get(key)
            return call_payload.get(key)  # Fallback to original payload
        
        metadata_updates = {
            "analysis_allowed": constraint_info["analysis_allowed"],
            "analysis_block_reason": constraint_info["analysis_block_reason"],
            "analysis_constraints": constraint_info["constraints"],
            # Only update timestamps/duration if we have valid values, otherwise preserve existing
            "start_timestamp": preserve_or_update("start_timestamp"),
            "end_timestamp": preserve_or_update("end_timestamp"),
            "duration_ms": preserve_or_update("duration_ms"),
            "agent_id": preserve_or_update("agent_id"),
            "agent_name": preserve_or_update("agent_name"),
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
            _update_retell_call_entry(db, call_id, metadata_updates)
        except KeyError:
            # Call not in metadata store - create it now, preserving metadata from call_payload
            logger.warning("Retell call %s not found in metadata store when updating constraints, creating entry", call_id)
            minimal_call_data = {
                "call_id": call_id,
                "recording_multi_channel_url": call_data.get("recording_multi_channel_url") or call_payload.get("recording_multi_channel_url"),
                "start_timestamp": call_data.get("start_timestamp") or call_payload.get("start_timestamp"),
                "end_timestamp": call_data.get("end_timestamp") or call_payload.get("end_timestamp"),
                "duration_ms": call_data.get("duration_ms") or call_payload.get("duration_ms"),
                "agent_id": call_data.get("agent_id") or call_payload.get("agent_id"),
                "agent_name": call_data.get("agent_name") or call_payload.get("agent_name"),
                "user_phone_number": call_data.get("user_phone_number") or call_payload.get("user_phone_number"),
            }
            _upsert_retell_call_metadata(db, minimal_call_data, status="processing")
            _update_retell_call_entry(db, call_id, metadata_updates)

        if not constraint_info["analysis_allowed"]:
            raise HTTPException(
                status_code=400,
                detail=constraint_info["analysis_block_reason"] or "Call cannot be analyzed.",
            )

        recording_url = call_data.get("recording_multi_channel_url")

        filename_hint = f"{call_id}.wav"
        audio_filename, audio_bytes = download_retell_recording(recording_url, filename_hint)

        # Submit combined audio to Hume - speaker labels will come from transcript matching
        file_contents = [(audio_filename, audio_bytes)]
        logger.info("Using combined audio for call %s (speaker labels from transcript)", call_id)

        # Extract transcript segments - but fetch fresh from API if stored one is incomplete
        # (stored transcript_object may have words stripped, which breaks extraction if segments lack start/end)
        transcript_segments = extract_retell_transcript_segments(call_data)
        if not transcript_segments:
            # Fallback: fetch fresh from Retell API to ensure we have complete transcript with words
            try:
                fresh_call_data = get_retell_call_details(call_id)
                transcript_segments = extract_retell_transcript_segments(fresh_call_data)
                logger.info("Fetched fresh transcript from Retell API for call %s", call_id)
            except Exception as exc:
                logger.warning("Could not fetch fresh transcript from Retell API for call %s: %s", call_id, exc)

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

        overall_emotion = _extract_overall_emotion_from_results(analysis_results)

        analysis_summary: Optional[str] = None
        for result in analysis_results:
            if isinstance(result, dict):
                summary_candidate = result.get("summary")
                if isinstance(summary_candidate, str) and summary_candidate.strip():
                    analysis_summary = summary_candidate.strip()
                    break

        # Save analysis results to database
        _persist_retell_results(db, call_id, analysis_results, retell_metadata)
        
        try:
            final_updates: Dict[str, Any] = {
                "analysis_status": "completed",
                "analysis_available": True,
                "recording_multi_channel_url": recording_url,
            }

            if overall_emotion:
                final_updates["overall_emotion_json"] = overall_emotion
                final_updates["overall_emotion_label"] = overall_emotion.get("label")

            existing_entry = _get_retell_call_entry(db, call_id)

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

            # Preserve existing metadata in final_updates if not already set
            if existing_entry:
                if "start_timestamp" not in final_updates and existing_entry.get("start_timestamp"):
                    final_updates["start_timestamp"] = existing_entry.get("start_timestamp")
                if "end_timestamp" not in final_updates and existing_entry.get("end_timestamp"):
                    final_updates["end_timestamp"] = existing_entry.get("end_timestamp")
                if "duration_ms" not in final_updates and existing_entry.get("duration_ms"):
                    final_updates["duration_ms"] = existing_entry.get("duration_ms")
                if "agent_id" not in final_updates and existing_entry.get("agent_id"):
                    final_updates["agent_id"] = existing_entry.get("agent_id")
                if "agent_name" not in final_updates and existing_entry.get("agent_name"):
                    final_updates["agent_name"] = existing_entry.get("agent_name")
                if "user_phone_number" not in final_updates and existing_entry.get("user_phone_number"):
                    final_updates["user_phone_number"] = existing_entry.get("user_phone_number")
            
            _update_retell_call_entry(db, call_id, final_updates)
        except Exception as update_exc:  # pylint: disable=broad-except
            logger.error("Failed to update metadata store for call %s after analysis: %s", call_id, update_exc)

        # Return payload in same format as before for compatibility
        return {
            "call_id": call_id,
            "retell_metadata": retell_metadata,
            "analysis": analysis_results
        }

    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("Error processing Retell call %s: %s", call_id, exc)
        # Create a new session for error handling
        error_db = SessionLocal()
        try:
            try:
                _update_retell_call_entry(
                    error_db,
                    call_id,
                    {
                        "analysis_status": "error",
                        "error_message": str(exc),
                    },
                )
            except KeyError:
                # Call not in metadata store - create it with error status
                logger.warning("Retell call %s not found in metadata store while recording error, creating entry", call_id)
                minimal_call_data = {
                    "call_id": call_id,
                    "recording_multi_channel_url": call_payload.get("recording_multi_channel_url"),
                }
                _upsert_retell_call_metadata(error_db, minimal_call_data, status="error")
                _update_retell_call_entry(error_db, call_id, {
                    "error_message": str(exc),
                })
        except Exception as update_exc:  # pylint: disable=broad-except
            logger.error("Failed to update metadata store for call %s: %s", call_id, update_exc)
        finally:
            error_db.close()
        raise


@app.post("/retell/webhook")
async def retell_webhook(payload: Dict[str, Any], db: Session = Depends(get_db)):
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
        logger.info("Ignoring Retell event %s (call_data type: %s)", event, type(call_data).__name__)
        if event == "call_analyzed" and not isinstance(call_data, dict):
            logger.warning("call_analyzed event received but call_data is not a dict. Payload keys: %s", list(payload.keys())[:10])
        return JSONResponse(content={"success": True, "ignored": True})

    call_id = call_data.get("call_id")
    if not call_id:
        raise HTTPException(status_code=400, detail="Missing call_id in Retell payload")

    logger.info("Received call_analyzed webhook for call %s", call_id)
    try:
        metadata = _upsert_retell_call_metadata(db, call_data, status="pending")
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
async def list_retell_calls(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    per_page: int = Query(15, ge=1, le=100, description="Number of items per page"),
    token_data: Dict[str, Any] = Depends(verify_token),
    db: Session = Depends(get_db)
):
    """
    Return available Retell calls registered via webhook.
    
    Supports pagination via query parameters:
    - page: Page number (default: 1, minimum: 1)
    - per_page: Items per page (default: 15, minimum: 1, maximum: 100)
    """
    # Query calls, excluding zero-duration calls
    query = db.query(Call).filter(
        (Call.duration_ms.is_(None)) | (Call.duration_ms > 0)
    )
    
    total_count = query.count()
    total_pages = max(1, (total_count + per_page - 1) // per_page)
    
    # Apply pagination and sorting
    calls = query.order_by(
        Call.start_timestamp.desc().nullslast()
    ).offset((page - 1) * per_page).limit(per_page).all()
    
    enriched_calls = []
    for call in calls:
        call_entry = call.to_dict()
        if call.analysis_status == "completed":
            overall_emotion = call_entry.get("overall_emotion")
            if not isinstance(overall_emotion, dict):
                overall_emotion = _load_overall_emotion_for_call(db, call.call_id)
                if overall_emotion:
                    call_entry["overall_emotion"] = overall_emotion
                    call_entry["overall_emotion_label"] = overall_emotion.get("label")
                    try:
                        _update_retell_call_entry(
                            db,
                            call.call_id,
                            {
                                "overall_emotion_json": overall_emotion,
                                "overall_emotion_label": overall_emotion.get("label"),
                            },
                        )
                    except KeyError:
                        logger.warning("Call %s missing when caching overall emotion", call.call_id)
            else:
                label = call_entry.get("overall_emotion_label")
                if not label:
                    call_entry["overall_emotion_label"] = overall_emotion.get("label")
        enriched_calls.append(call_entry)

    return JSONResponse(content={
        "success": True,
        "calls": enriched_calls,
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total_count,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1,
        }
    })


@app.post("/retell/calls/refresh")
async def refresh_retell_calls(
    call_id: Optional[str] = None, 
    token_data: Dict[str, Any] = Depends(verify_token),
    db: Session = Depends(get_db)
):
    """
    Re-evaluate stored call metadata (voicemail detection, duration, etc.).
    If call_id is provided, refresh only that call; otherwise refresh all.
    """
    refreshed = []
    errors: Dict[str, str] = {}

    if call_id:
        target_ids = [call_id]
    else:
        # Get all call IDs from database
        calls = db.query(Call).all()
        target_ids = [call.call_id for call in calls]

    for cid in target_ids:
        try:
            entry = _refresh_call_metadata(db, cid)
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


def _ensure_call_registered(db: Session, call_id: str) -> Dict[str, Any]:
    call_entry = _get_retell_call_entry(db, call_id)
    if not call_entry:
        raise HTTPException(status_code=404, detail=f"Call {call_id} not found")
    return call_entry


def _prepare_retell_call_payload(call_entry: Dict[str, Any]) -> Dict[str, Any]:
    """Prepare call payload for analysis, preserving all existing metadata."""
    payload: Dict[str, Any] = {
        "call_id": call_entry["call_id"],
        "recording_multi_channel_url": call_entry.get("recording_multi_channel_url"),
        # Preserve existing metadata to avoid overwriting with nulls
        "start_timestamp": call_entry.get("start_timestamp"),
        "end_timestamp": call_entry.get("end_timestamp"),
        "duration_ms": call_entry.get("duration_ms"),
        "agent_id": call_entry.get("agent_id"),
        "agent_name": call_entry.get("agent_name"),
        "user_phone_number": call_entry.get("user_phone_number"),
    }
    # Include transcript_object if available (from n8n or stored metadata)
    # NOTE: Do NOT strip words here - extract_retell_transcript_segments needs words
    # as fallback if segments don't have start/end timestamps
    transcript_object = call_entry.get("transcript_object")
    if transcript_object is not None:
        payload["transcript_object"] = transcript_object
    return payload


def _process_retell_call_background(call_id: str, call_payload: Dict[str, Any]) -> None:
    """Background task to process Retell call analysis without blocking the HTTP request."""
    db = SessionLocal()
    try:
        logger.info("Starting background analysis for call %s", call_id)
        analysis_payload = _process_retell_call(db, call_payload)
        logger.info("Completed background analysis for call %s", call_id)
    except HTTPException as exc:
        logger.error("HTTP error in background analysis for call %s: %s", call_id, exc.detail)
        try:
            _update_retell_call_entry(db, call_id, {
                "analysis_status": "error",
                "error_message": exc.detail
            })
        except KeyError:
            # Call not in metadata store - create it with error status
            logger.warning("Retell call %s not found in metadata store while recording HTTP error, creating entry", call_id)
            minimal_call_data = {
                "call_id": call_id,
                "recording_multi_channel_url": call_payload.get("recording_multi_channel_url"),
            }
            _upsert_retell_call_metadata(db, minimal_call_data, status="error")
            _update_retell_call_entry(db, call_id, {
                "error_message": exc.detail
            })
    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("Failed to analyze Retell call %s in background: %s", call_id, exc)
        try:
            _update_retell_call_entry(db, call_id, {
                "analysis_status": "error",
                "error_message": str(exc)
            })
        except KeyError:
            # Call not in metadata store - create it with error status
            logger.warning("Retell call %s not found in metadata store while recording error, creating entry", call_id)
            minimal_call_data = {
                "call_id": call_id,
                "recording_multi_channel_url": call_payload.get("recording_multi_channel_url"),
            }
            _upsert_retell_call_metadata(db, minimal_call_data, status="error")
            _update_retell_call_entry(db, call_id, {
                "error_message": str(exc)
            })
    finally:
        db.close()


@app.post("/retell/calls/{call_id}/analyze")
async def analyze_retell_call(
    call_id: str, 
    force: bool = Query(False), 
    background_tasks: BackgroundTasks = BackgroundTasks(),
    token_data: Dict[str, Any] = Depends(verify_token),
    db: Session = Depends(get_db)
):
    """
    Trigger Hume analysis for a previously-registered Retell call.
    
    Returns immediately and processes in the background to avoid gateway timeouts.
    Use GET /retell/calls/{call_id}/analysis to check status and retrieve results.
    """
    call_entry = _ensure_call_registered(db, call_id)
    if call_entry.get("analysis_allowed") is False:
        reason = call_entry.get("analysis_block_reason") or "Call cannot be analyzed."
        raise HTTPException(
            status_code=400,
            detail=reason,
        )

    # If analysis already exists and not forcing, return it immediately
    if not force:
        try:
            return await get_retell_call_analysis(call_id, db=db)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise

    # Check if already processing
    current_status = call_entry.get("analysis_status")
    if current_status == "processing":
        return JSONResponse(content={
            "success": True,
            "message": "Analysis already in progress",
            "call_id": call_id,
            "status": "processing"
        })

    if force:
        logger.info("Force re-running analysis for Retell call %s", call_id)

    # Mark as processing and start background task
    _update_retell_call_entry(db, call_id, {"analysis_status": "processing", "error_message": None})
    
    call_payload = _prepare_retell_call_payload(call_entry)
    background_tasks.add_task(_process_retell_call_background, call_id, call_payload)

    # Return immediately - processing happens in background
    return JSONResponse(content={
        "success": True,
        "message": "Analysis started in background",
        "call_id": call_id,
        "status": "processing",
        "note": "Use GET /retell/calls/{call_id}/analysis to check status and retrieve results when complete"
    })


def _reconstruct_analysis_from_db(db: Session, call_id: str) -> Optional[Dict[str, Any]]:
    """Reconstruct analysis results from database in the format expected by frontend."""
    call = db.query(Call).filter(Call.call_id == call_id).first()
    if not call or not call.analysis_available:
        return None
    
    # Get emotion segments with predictions eagerly loaded
    prosody_segments = db.query(EmotionSegment).filter(
        EmotionSegment.call_id == call_id,
        EmotionSegment.segment_type == "prosody"
    ).order_by(EmotionSegment.time_start).all()
    
    burst_segments = db.query(EmotionSegment).filter(
        EmotionSegment.call_id == call_id,
        EmotionSegment.segment_type == "burst"
    ).order_by(EmotionSegment.time_start).all()
    
    # Load predictions for all segments
    segment_ids = [seg.id for seg in prosody_segments + burst_segments]
    if segment_ids:
        predictions = db.query(EmotionPrediction).filter(
            EmotionPrediction.segment_id.in_(segment_ids)
        ).all()
        # Group predictions by segment_id
        predictions_by_segment = {}
        for pred in predictions:
            if pred.segment_id not in predictions_by_segment:
                predictions_by_segment[pred.segment_id] = []
            predictions_by_segment[pred.segment_id].append(pred)
        
        # Attach predictions to segments
        for seg in prosody_segments + burst_segments:
            seg._predictions_cache = sorted(
                predictions_by_segment.get(seg.id, []),
                key=lambda x: x.rank
            )
    
    # Get transcript segments
    transcript_segments = db.query(TranscriptSegment).filter(
        TranscriptSegment.call_id == call_id
    ).order_by(TranscriptSegment.start_time).all()
    
    # Get summary
    summary_obj = db.query(AnalysisSummary).filter(
        AnalysisSummary.call_id == call_id
    ).order_by(AnalysisSummary.created_at.desc()).first()
    
    # Build metadata
    metadata: Dict[str, Any] = {
        "retell_call_id": call_id,
        "recording_multi_channel_url": call.recording_multi_channel_url,
        "start_timestamp": call.start_timestamp,
        "end_timestamp": call.end_timestamp,
        "duration_ms": call.duration_ms,
        "agent": {
            "id": call.agent_id,
            "name": call.agent_name,
        },
        "retell_transcript_available": call.transcript_available,
        "retell_transcript_segments": [seg.to_dict() for seg in transcript_segments],
    }
    
    if call.analysis_constraints:
        metadata["analysis_constraints"] = call.analysis_constraints
    
    # Count categories
    category_counts = {"positive": 0, "neutral": 0, "negative": 0}
    for seg in prosody_segments:
        if seg.primary_category:
            category_counts[seg.primary_category] = category_counts.get(seg.primary_category, 0) + 1
    metadata["category_counts"] = category_counts
    
    if call.overall_emotion_json:
        metadata["overall_call_emotion"] = call.overall_emotion_json
    
    # Build result - manually construct segment dicts with predictions
    def segment_to_dict(seg):
        seg_dict = {
            "time_start": float(seg.time_start) if seg.time_start else 0.0,
            "time_end": float(seg.time_end) if seg.time_end else 0.0,
            "primary_category": seg.primary_category,
            "source": seg.source,
        }
        if seg.speaker:
            seg_dict["speaker"] = seg.speaker
        if seg.text:
            seg_dict["text"] = seg.text
        if seg.transcript_text:
            seg_dict["transcript_text"] = seg.transcript_text
        
        # Add predictions if available
        preds = getattr(seg, '_predictions_cache', [])
        if preds:
            seg_dict["top_emotions"] = [
                {
                    "name": pred.emotion_name,
                    "score": float(pred.score) if pred.score else 0.0,
                    "percentage": float(pred.percentage) if pred.percentage else 0.0,
                    "category": pred.category,
                }
                for pred in preds
            ]
        return seg_dict
    
    result = {
        "filename": f"{call_id}_combined",
        "prosody": [segment_to_dict(seg) for seg in prosody_segments],
        "burst": [segment_to_dict(seg) for seg in burst_segments],
        "metadata": metadata,
    }
    
    if summary_obj:
        result["summary"] = summary_obj.summary_text
    
    return result


@app.get("/retell/calls/{call_id}/analysis")
async def get_retell_call_analysis(
    call_id: str, 
    token_data: Dict[str, Any] = Depends(verify_token),
    db: Session = Depends(get_db)
):
    """
    Return stored analysis for a Retell call if it has been processed.
    
    Returns status information if analysis is still processing or has errors.
    """
    call_entry = _ensure_call_registered(db, call_id)
    
    # Check if still processing
    analysis_status = call_entry.get("analysis_status")
    if analysis_status == "processing":
        return JSONResponse(content={
            "success": True,
            "call_id": call_id,
            "status": "processing",
            "message": "Analysis is still in progress. Please check again in a few moments."
        })
    
    # Check if there was an error
    if analysis_status == "error":
        error_message = call_entry.get("error_message", "Unknown error occurred")
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "call_id": call_id,
                "status": "error",
                "error_message": error_message
            }
        )
    
    # Reconstruct analysis from database
    result = _reconstruct_analysis_from_db(db, call_id)
    if not result:
        raise HTTPException(status_code=404, detail="Analysis not available for this call")
    
    # Build retell_metadata from call
    call = db.query(Call).filter(Call.call_id == call_id).first()
    retell_metadata = {
        "retell_call_id": call_id,
        "recording_multi_channel_url": call.recording_multi_channel_url,
        "start_timestamp": call.start_timestamp,
        "end_timestamp": call.end_timestamp,
        "duration_ms": call.duration_ms,
    }

    return JSONResponse(
        content={
            "success": True,
            "call_id": call_id,
            "results": result,
            "retell_metadata": retell_metadata,
            "recording_url": call.recording_multi_channel_url,
        }
    )


@app.get("/")
async def root():
    """Health check endpoint"""
    return {"message": "Hume Emotion Analysis API is running", "status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

