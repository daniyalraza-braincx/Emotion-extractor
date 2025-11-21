import io
import os
import json
import time
import wave
import logging
try:
    import audioop  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - fallback for Python>=3.13
    from audioop_lts import audioop  # type: ignore
import re
from typing import List, Dict, Any, Tuple, Optional, TYPE_CHECKING

import requests
from dotenv import load_dotenv
from hume import HumeClient
from hume.expression_measurement.batch.types import InferenceBaseRequest, Models
from hume import expression_measurement as _hume_expression_measurement

try:
    from hume.expression_measurement.batch.batch_client import BatchClientWithUtils  # pyright: ignore[reportMissingImports]
except ImportError:
    BatchClientWithUtils = None

if BatchClientWithUtils is not None:
    # Ensure the global used by HumeClient.batch is defined
    _hume_expression_measurement.client.BatchClientWithUtils = BatchClientWithUtils
from emotion_categories import EMOTION_CATEGORIES, DEFAULT_EMOTION_CATEGORY

if TYPE_CHECKING:
    from openai import OpenAI
else:
    try:
        from openai import OpenAI
    except ImportError:
        OpenAI = None  # type: ignore

load_dotenv()

HUME_API_KEY = os.getenv("HUME_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
RETELL_API_KEY = os.getenv("RETELL_API_KEY")

RETELL_API_BASE_URL = os.getenv(
    "RETELL_API_BASE_URL",
    "https://api.retellai.com"
)


def get_hume_client() -> HumeClient:
    """Initialize and return Hume client"""
    if not HUME_API_KEY:
        raise ValueError("HUME_API_KEY environment variable is not set")
    return HumeClient(api_key=HUME_API_KEY)


def get_openai_client() -> Optional[OpenAI]:
    """Initialize and return OpenAI client if API key is available"""
    if OpenAI is None:
        return None
    
    if not OPENAI_API_KEY:
        return None
    return OpenAI(api_key=OPENAI_API_KEY)


def optimize_audio_for_hume(audio_bytes: bytes, target_sample_rate: int = 16000) -> bytes:
    """
    Optimize audio for Hume API processing by downmixing to mono and resampling to target rate.
    
    This function:
    - Converts stereo to mono (combines channels)
    - Resamples to 16kHz if higher (standard for speech emotion recognition)
    - Preserves audio quality for emotion detection
    
    Args:
        audio_bytes: Raw audio bytes (WAV format)
        target_sample_rate: Target sample rate in Hz (default: 16000)
    
    Returns:
        Optimized audio bytes as WAV
    """
    try:
        with wave.open(io.BytesIO(audio_bytes), 'rb') as w:
            params = w.getparams()
            audio_data = w.readframes(params.nframes)
        
        # Downmix stereo to mono if needed
        if params.nchannels == 2:
            audio_data = audioop.tomono(audio_data, params.sampwidth, 1.0, 1.0)
            nchannels = 1
        else:
            nchannels = params.nchannels
        
        # Resample to target rate if higher
        if params.framerate > target_sample_rate:
            audio_data, _ = audioop.ratecv(
                audio_data,
                params.sampwidth,
                nchannels,
                params.framerate,
                target_sample_rate,
                None
            )
            framerate = target_sample_rate
        else:
            framerate = params.framerate
        
        # Write optimized WAV
        out = io.BytesIO()
        with wave.open(out, 'wb') as w_out:
            w_out.setnchannels(nchannels)
            w_out.setsampwidth(params.sampwidth)
            w_out.setframerate(framerate)
            w_out.writeframes(audio_data)
        
        optimized = out.getvalue()
        size_reduction = (1 - len(optimized) / len(audio_bytes)) * 100
        logging.info(
            f"Audio optimized: {len(audio_bytes)/1024:.1f}KB → {len(optimized)/1024:.1f}KB "
            f"({size_reduction:.1f}% reduction), {params.framerate}Hz→{framerate}Hz, "
            f"{params.nchannels}ch→{nchannels}ch"
        )
        return optimized
        
    except Exception as e:
        logging.warning(f"Failed to optimize audio, using original: {e}")
        return audio_bytes


def prepare_audio_files(file_contents: List[Tuple[str, bytes]], optimize: bool = True) -> List[Tuple[str, bytes, str]]:
    """
    Prepare audio files for submission to Hume API.
    
    Args:
        file_contents: List of tuples (filename, file_bytes)
        optimize: Whether to optimize audio (downmix to mono, resample to 16kHz)
    
    Returns:
        List of tuples (filename, file_bytes, content_type)
    """
    file_objects = []
    for filename, file_content in file_contents:
        # Optimize audio if requested and it's a WAV file
        if optimize and filename.lower().endswith('.wav'):
            try:
                file_content = optimize_audio_for_hume(file_content)
                # Update filename to indicate optimization
                if not filename.endswith('_opt.wav'):
                    base_name = os.path.splitext(filename)[0]
                    filename = f"{base_name}_opt.wav"
            except Exception as e:
                logging.warning(f"Failed to optimize {filename}, using original: {e}")
        
        # Determine content type from extension
        ext = os.path.splitext(filename)[1].lower()
        content_type_map = {
            '.wav': 'audio/wav',
            '.mp3': 'audio/mpeg',
            '.m4a': 'audio/mp4',
            '.flac': 'audio/flac'
        }
        content_type = content_type_map.get(ext, 'audio/wav')
        file_objects.append((filename, file_content, content_type))
    
    return file_objects


def categorize_emotion(emotion_name: Optional[str]) -> str:
    if not emotion_name:
        return DEFAULT_EMOTION_CATEGORY
    return EMOTION_CATEGORIES.get(emotion_name.lower(), DEFAULT_EMOTION_CATEGORY)


def submit_hume_job(file_objects: List[Tuple[str, bytes, str]], client: Optional[HumeClient] = None, use_priority: bool = True) -> str:
    """
    Submit audio files to Hume API for emotion analysis with priority support.
    
    Uses raw HTTP request to bypass SDK limitation and enable priority="high" parameter,
    which provides 20-50% speed boost during peak hours.
    
    Args:
        file_objects: List of tuples (filename, file_bytes, content_type)
        client: Optional HumeClient instance (creates new one if not provided)
        use_priority: Whether to use priority="high" (default: True)
    
    Returns:
        Job ID string
    """
    if client is None:
        client = get_hume_client()
    
    if not HUME_API_KEY:
        raise ValueError("HUME_API_KEY environment variable is not set")
    
    models_config = Models(prosody={}, burst={})
    inference_request = InferenceBaseRequest(models=models_config)
    
    # Try raw HTTP with priority first (if enabled), fallback to SDK
    if use_priority:
        try:
            import httpx
            
            url = "https://api.hume.ai/v0/batch/jobs"
            headers = {
                "X-Hume-Api-Key": HUME_API_KEY,
                "Accept": "application/json",
            }
            
            # Serialize inference request to JSON
            request_dict = inference_request.model_dump() if hasattr(inference_request, 'model_dump') else inference_request
            json_payload = json.dumps(request_dict)
            
            # Build multipart form data exactly as Hume expects
            # Critical: field name must be exactly "file" (singular, repeated for multiple files)
            # Hume SDK uses "file" (singular) - use list of tuples to allow multiple files with same key
            files_list = []
            for filename, file_bytes, content_type in file_objects:
                # Use "file" (singular) as field name - same as Hume SDK
                files_list.append(("file", (filename, file_bytes, content_type)))
            
            # JSON payload goes in data dict with exact field name "json"
            data = {"json": json_payload}
            
            # Priority goes in query params
            params = {"priority": "high"}
            
            # Use httpx.post directly (no need for Client context for single request)
            # files_list allows multiple files with same "file" field name
            response = httpx.post(
                url,
                headers=headers,
                data=data,         # JSON payload with field name "json"
                files=files_list,  # Audio files with field name "file" (singular, repeated)
                params=params,     # Priority parameter
                timeout=60.0,
            )
            response.raise_for_status()
            job_data = response.json()
            
            # Extract job_id from response
            job_id = job_data.get("job_id") or job_data.get("id")
            if job_id:
                logging.info(f"Submitted Hume job {job_id} with priority=high")
                return str(job_id).strip()
            else:
                logging.warning(f"Priority submission succeeded but job_id not found in response: {job_data}, falling back to SDK")
                # Fall through to SDK fallback
                    
        except ImportError:
            logging.warning("httpx not available, using SDK without priority")
            # Fall through to SDK fallback
        except Exception as e:
            error_msg = str(e)
            if hasattr(e, 'response'):
                try:
                    error_msg += f" | Response: {getattr(e.response, 'text', str(e.response))}"
                except:
                    pass
            logging.warning(f"Priority submission failed ({error_msg}), falling back to SDK")
            # Fall through to SDK fallback
    
    # Fallback to SDK method (original implementation)
    try:
        job_id = client.expression_measurement.batch.start_inference_job_from_local_file(
            file=file_objects if file_objects else [],
            json=inference_request
        )
    except Exception as e:
        error_msg = str(e)
        # Try to extract more details from the error
        if hasattr(e, 'response'):
            error_msg += f" | Response: {e.response}"
        raise RuntimeError(f"Failed to submit job to Hume API: {error_msg}")
    
    # Extract job_id from SDK response
    if isinstance(job_id, str):
        return job_id.strip()
    elif hasattr(job_id, 'id'):
        return str(job_id.id).strip()
    elif hasattr(job_id, 'job_id'):
        return str(job_id.job_id).strip()
    elif isinstance(job_id, dict):
        result = job_id.get('id') or job_id.get('job_id')
        if result:
            return str(result).strip()
    
    # Last resort: try to extract UUID from string representation
    job_str = str(job_id)
    uuid_pattern = r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'
    uuid_match = re.search(uuid_pattern, job_str)
    if uuid_match:
        return uuid_match.group(0)
    
    raise ValueError(f"Could not extract valid job_id from response: {type(job_id)} - {job_id}")


def wait_for_job_completion(job_id: str, client: Optional[HumeClient] = None, max_wait_time: int = 600, poll_interval: int = 5) -> Dict[str, Any]:
    """
    Wait for Hume job to complete.
    
    Args:
        job_id: Job ID from submit_hume_job
        client: Optional HumeClient instance
        max_wait_time: Maximum time to wait in seconds
        poll_interval: Seconds between status checks
    
    Returns:
        Job details dictionary
    
    Raises:
        TimeoutError: If job doesn't complete within max_wait_time
        RuntimeError: If job fails
    """
    if client is None:
        client = get_hume_client()
    
    start_time = time.time()
    
    while time.time() - start_time < max_wait_time:
        job_details = client.expression_measurement.batch.get_job_details(job_id)
        status = job_details.state.value if hasattr(job_details.state, 'value') else str(job_details.state)
        
        if "COMPLETED" in status.upper():
            if hasattr(job_details, 'model_dump'):
                return job_details.model_dump()
            return {"status": status}
        elif "FAILED" in status.upper():
            error = getattr(job_details, 'error', 'Unknown error')
            raise RuntimeError(f"Job failed: {error}")
        
        time.sleep(poll_interval)
    
    raise TimeoutError(f"Job did not complete within {max_wait_time} seconds")


def get_predictions(job_id: str, client: Optional[HumeClient] = None) -> List[Dict[str, Any]]:
    """
    Retrieve predictions from completed Hume job.
    
    Args:
        job_id: Job ID from submit_hume_job
        client: Optional HumeClient instance
    
    Returns:
        List of prediction dictionaries
    """
    if client is None:
        client = get_hume_client()
    
    predictions_response = client.expression_measurement.batch.get_job_predictions(job_id)
    
    # Convert to dictionary format
    if hasattr(predictions_response, 'model_dump'):
        predictions_data = predictions_response.model_dump()
    elif hasattr(predictions_response, 'dict'):
        predictions_data = predictions_response.dict()
    elif isinstance(predictions_response, list):
        predictions_data = []
        for item in predictions_response:
            if hasattr(item, 'model_dump'):
                predictions_data.append(item.model_dump())
            elif hasattr(item, 'dict'):
                predictions_data.append(item.dict())
            else:
                predictions_data.append(item)
    else:
        predictions_data = predictions_response
    
    return predictions_data if isinstance(predictions_data, list) else [predictions_data]


def extract_top_emotions(predictions_data: List[Dict[str, Any]], top_n: int = 1) -> List[Dict[str, Any]]:
    """
    Extract top N emotions from predictions data.
    
    Args:
        predictions_data: List of prediction dictionaries from get_predictions
        top_n: Number of top emotions to return per segment (default: 1)
    
    Args:
        file_contents: List of tuples (filename, file_bytes)
        client: Optional HumeClient instance
        include_summary: Whether to populate a generated LLM summary
        retell_call_id: Optional Retell call identifier to auto-fetch transcript metadata
        retell_transcript: Optional pre-fetched Retell transcript segments

    Returns:
        List of file results with top emotions and optional speaker enrichment
    """
    results = []
    
    for item in predictions_data:
        if not isinstance(item, dict) or "results" not in item:
            continue
        
        preds = item.get("results", {}).get("predictions", [])
        if not preds:
            continue
        
        file_result = {
            "filename": item.get("source", {}).get("filename", "unknown"),
            "prosody": [],
            "burst": [],
            "metadata": {},
        }
        category_counts = {"positive": 0, "neutral": 0, "negative": 0}
        
        # Process each prediction
        for pred in preds:
            if not isinstance(pred, dict) or "models" not in pred:
                continue
            
            models = pred["models"]
            
            # Extract prosody emotions
            if "prosody" in models and models["prosody"] is not None:
                prosody_data = models["prosody"]
                grouped_preds = prosody_data.get("grouped_predictions", [])
                # Track seen segments to avoid duplicates (same time range)
                # Note: Hume uses overlapping windows, so same time ranges appear multiple times
                seen_time_ranges = set()
                
                for group in grouped_preds:
                    for pred_item in group.get("predictions", []):
                        time_info = pred_item.get("time", {})
                        time_start = time_info.get("begin", 0) if isinstance(time_info, dict) else 0
                        time_end = time_info.get("end", 0) if isinstance(time_info, dict) else 0
                        text = pred_item.get("text", "") or None  # Keep null if empty, will be filled by transcript matching
                        
                        # Round times to avoid floating point precision issues
                        rounded_start = round(time_start, 2)
                        rounded_end = round(time_end, 2)
                        
                        # Deduplicate based on time range only (text will be added later by transcript matching)
                        # Hume uses sliding windows (0-4s, 1-5s, etc.), so we deduplicate exact time matches
                        time_range_key = (rounded_start, rounded_end)
                        
                        # Skip exact duplicate time ranges (but allow overlapping windows to merge later)
                        if time_range_key in seen_time_ranges:
                            continue
                        seen_time_ranges.add(time_range_key)
                        
                        emotions = pred_item.get("emotions", [])
                        
                        if emotions:
                            top_emotions = sorted(
                                emotions,
                                key=lambda x: x.get("score", 0),
                                reverse=True
                            )[:top_n]

                            enriched_top_emotions = []
                            for emo in top_emotions:
                                name = emo.get("name", "Unknown")
                                category = categorize_emotion(name)
                                enriched_top_emotions.append({
                                    "name": name,
                                    "score": round(emo.get("score", 0), 4),
                                    "percentage": round(emo.get("score", 0) * 100, 1),
                                    "category": category,
                                })

                            primary_category = enriched_top_emotions[0]["category"] if enriched_top_emotions else DEFAULT_EMOTION_CATEGORY
                            category_counts[primary_category] += 1
                            
                            # Store text if available, otherwise null (will be filled by transcript enrichment)
                            file_result["prosody"].append({
                                "time_start": rounded_start,
                                "time_end": rounded_end,
                                "text": text.strip() if text else None,
                                "primary_category": primary_category,
                                "top_emotions": enriched_top_emotions,
                                "source": "prosody",
                            })
            
            # Extract burst emotions
            if "burst" in models and models["burst"] is not None:
                burst_data = models["burst"]
                grouped_preds = burst_data.get("grouped_predictions", [])
                for group in grouped_preds:
                    for pred_item in group.get("predictions", []):
                        time_info = pred_item.get("time", {})
                        time_start = time_info.get("begin", 0) if isinstance(time_info, dict) else 0
                        time_end = time_info.get("end", 0) if isinstance(time_info, dict) else 0
                        emotions = pred_item.get("emotions", [])
                        
                        if emotions:
                            top_emotions = sorted(
                                emotions,
                                key=lambda x: x.get("score", 0),
                                reverse=True
                            )[:top_n]

                            enriched_top_emotions = []
                            for emo in top_emotions:
                                name = emo.get("name", "Unknown")
                                category = categorize_emotion(name)
                                enriched_top_emotions.append({
                                    "name": name,
                                    "score": round(emo.get("score", 0), 4),
                                    "percentage": round(emo.get("score", 0) * 100, 1),
                                    "category": category,
                                })

                            primary_category = enriched_top_emotions[0]["category"] if enriched_top_emotions else DEFAULT_EMOTION_CATEGORY
                            category_counts[primary_category] += 1
                            
                            file_result["burst"].append({
                                "time_start": round(time_start, 2),
                                "time_end": round(time_end, 2),
                                "primary_category": primary_category,
                                "top_emotions": enriched_top_emotions,
                                "source": "burst",
                            })

        file_result["metadata"]["category_counts"] = category_counts
        
        results.append(file_result)
    
    return results


def get_retell_call_details(call_id: str) -> Dict[str, Any]:
    """Fetch call details (including transcript and recording URLs) from Retell."""
    if not RETELL_API_KEY:
        raise ValueError("RETELL_API_KEY environment variable is not set")

    url = f"{RETELL_API_BASE_URL.rstrip('/')}/v2/get-call/{call_id}"
    headers = {
        "Authorization": f"Bearer {RETELL_API_KEY}",
        "Accept": "application/json"
    }

    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
    except requests.HTTPError as http_err:
        raise RuntimeError(
            f"Failed to retrieve Retell call details: {http_err.response.status_code} {http_err.response.text}"
        ) from http_err
    except requests.RequestException as req_err:
        raise RuntimeError(f"Failed to retrieve Retell call details: {req_err}") from req_err

    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("Unexpected response format from Retell API")
    return data


def extract_retell_transcript_segments(call_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return transcript segments from Retell call payload."""
    transcript = call_data.get("transcript_object")
    if not isinstance(transcript, list):
        return []

    cleaned_segments: List[Dict[str, Any]] = []
    for segment in transcript:
        if not isinstance(segment, dict):
            continue

        speaker = segment.get("speaker") or segment.get("role")
        if speaker is None:
            continue

        speaker_lower = str(speaker).lower()
        if speaker_lower in {"user", "customer"}:
            normalized_speaker = "Customer"
        elif speaker_lower in {"agent", "assistant"}:
            normalized_speaker = "Agent"
        else:
            normalized_speaker = speaker.title()

        start = segment.get("start")
        end = segment.get("end")

        words = segment.get("words")
        if (start is None or end is None) and isinstance(words, list) and words:
            first_word = words[0]
            last_word = words[-1]
            start = first_word.get("start")
            end = last_word.get("end")

        if start is None or end is None:
            continue

        cleaned_segment = {
            "speaker": normalized_speaker,
            "start": float(start),
            "end": float(end),
            "text": segment.get("content") or segment.get("text") or ""
        }

        confidence = segment.get("confidence")
        if confidence is not None:
            cleaned_segment["confidence"] = confidence

        cleaned_segments.append(cleaned_segment)

    return cleaned_segments


def download_retell_recording(
    recording_url: str,
    filename: Optional[str] = None,
    timeout: int = 120
) -> Tuple[str, bytes]:
    """Download the multi-channel recording from Retell."""
    if not recording_url:
        raise ValueError("Recording URL is required to download audio")

    try:
        response = requests.get(recording_url, timeout=timeout)
        response.raise_for_status()
    except requests.HTTPError as http_err:
        raise RuntimeError(
            f"Failed to download Retell recording: {http_err.response.status_code} {http_err.response.text}"
        ) from http_err
    except requests.RequestException as req_err:
        raise RuntimeError(f"Failed to download Retell recording: {req_err}") from req_err

    resolved_filename = filename
    if not resolved_filename:
        # Try to infer filename from headers or URL
        content_disposition = response.headers.get("content-disposition")
        if content_disposition:
            match = re.search(r'filename="?([^";]+)"?', content_disposition)
            if match:
                resolved_filename = match.group(1)
        if not resolved_filename:
            resolved_filename = os.path.basename(recording_url.split("?")[0]) or "retell_call.wav"

    return resolved_filename, response.content

def _find_best_transcript_match(
    start: float,
    end: float,
    transcript_segments: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """Find the transcript segment with the largest overlap for the given time window."""
    best_segment: Optional[Dict[str, Any]] = None
    best_overlap = 0.0

    for segment in transcript_segments:
        seg_start = segment.get("start", 0.0)
        seg_end = segment.get("end", 0.0)
        # Calculate overlap between [start, end] and [seg_start, seg_end]
        overlap = max(0.0, min(end, seg_end) - max(start, seg_start))
        if overlap > best_overlap:
            best_overlap = overlap
            best_segment = segment

    return best_segment


def enrich_results_with_transcript(
    results: List[Dict[str, Any]],
    transcript_segments: Optional[List[Dict[str, Any]]] = None
) -> List[Dict[str, Any]]:
    """Attach speaker and transcript details to Hume segments when available."""
    if not transcript_segments:
        return results

    for result in results:
        # Process prosody segments: match to transcripts, then deduplicate by transcript segment
        prosody_segments = result.get("prosody", [])
        
        # First pass: match each Hume segment to a transcript segment
        for prosody_segment in prosody_segments:
            start = prosody_segment.get("time_start", 0.0)
            end = prosody_segment.get("time_end", 0.0)
            matched_segment = _find_best_transcript_match(start, end, transcript_segments)
            if matched_segment:
                prosody_segment["speaker"] = matched_segment.get("speaker")
                transcript_text = matched_segment.get("text")
                if transcript_text:
                    prosody_segment["transcript_text"] = transcript_text
                    prosody_segment["text"] = transcript_text
                    # Update time range to match transcript segment (aligns timeline)
                    transcript_start = matched_segment.get("start", start)
                    transcript_end = matched_segment.get("end", end)
                    prosody_segment["time_start"] = round(transcript_start, 2)
                    prosody_segment["time_end"] = round(transcript_end, 2)
                    # Store transcript segment index for grouping
                    prosody_segment["_transcript_index"] = transcript_segments.index(matched_segment)
        
        # Second pass: only keep segments that matched to a transcript segment
        # and group them by transcript segment index to deduplicate overlapping windows
        transcript_groups = {}  # transcript_index -> list of segments
        
        for prosody_segment in prosody_segments:
            # Only include segments that matched to a transcript segment (have text and transcript_index)
            transcript_index = prosody_segment.get("_transcript_index")
            segment_text = prosody_segment.get("text") or prosody_segment.get("transcript_text")
            
            if transcript_index is None or not segment_text or not segment_text.strip():
                continue  # Skip segments without transcript match or text
            
            # Group by transcript index (handles repeated phrases correctly)
            if transcript_index not in transcript_groups:
                transcript_groups[transcript_index] = []
            transcript_groups[transcript_index].append(prosody_segment)
        
        # Third pass: for each transcript segment, pick the best Hume segment
        # and ensure it uses the transcript's exact time range
        enriched_prosody = []
        for transcript_index, segments in sorted(transcript_groups.items()):
            if not segments or transcript_index >= len(transcript_segments):
                continue
            
            # Get the transcript segment for this index
            matched_transcript = transcript_segments[transcript_index]
            transcript_start = matched_transcript.get("start")
            transcript_end = matched_transcript.get("end")
            
            if transcript_start is None or transcript_end is None:
                continue  # Skip if transcript segment has no valid times
            
            # Pick the segment with the highest emotion score
            best_segment = max(segments, key=lambda s: (
                s.get("top_emotions", [{}])[0].get("score", 0) if s.get("top_emotions") else 0
            ))
            
            # Force time range to match transcript segment exactly (ensures graph alignment)
            best_segment["time_start"] = round(transcript_start, 2)
            best_segment["time_end"] = round(transcript_end, 2)
            
            # Ensure all required fields are present
            best_segment["speaker"] = matched_transcript.get("speaker") or best_segment.get("speaker")
            best_segment["transcript_text"] = matched_transcript.get("text") or best_segment.get("transcript_text")
            best_segment["text"] = best_segment["transcript_text"]
            
            # Clean up internal tracking field
            best_segment.pop("_transcript_index", None)
            enriched_prosody.append(best_segment)
        
        # Sort by time_start to maintain chronological order
        enriched_prosody.sort(key=lambda s: s.get("time_start", 0))
        
        # Replace prosody list with deduplicated version
        result["prosody"] = enriched_prosody
        
        # Process burst segments
        for burst_segment in result.get("burst", []):
            start = burst_segment.get("time_start", 0.0)
            end = burst_segment.get("time_end", 0.0)
            matched_segment = _find_best_transcript_match(start, end, transcript_segments)
            if matched_segment:
                burst_segment["speaker"] = matched_segment.get("speaker")
                transcript_text = matched_segment.get("text")
                if transcript_text:
                    burst_segment["transcript_text"] = transcript_text

        metadata = result.setdefault("metadata", {})
        metadata["retell_transcript_available"] = True
        metadata["retell_transcript_segments"] = transcript_segments

    return results


def summarize_predictions(results: List[Dict[str, Any]], openai_client: Optional[OpenAI] = None) -> Optional[str]:
    """
    Summarize emotion predictions using OpenAI LLM.
    
    Args:
        results: List of file results with top emotions
        openai_client: Optional OpenAI client instance
    
    Returns:
        Summary string or None if OpenAI is not available
    """
    if openai_client is None:
        openai_client = get_openai_client()
    
    if openai_client is None:
        return None
    
    try:
        # Format the predictions data for the prompt with time-based information
        summary_data = []
        for result in results:
            filename = result.get("filename", "unknown")
            prosody_segments = result.get("prosody", [])
            burst_segments = result.get("burst", [])
            metadata = result.get("metadata", {}) or {}
            transcript_segments = metadata.get("retell_transcript_segments", [])
            customer_profile = metadata.get("customer") or {}
            agent_profile = metadata.get("agent") or {}
            call_context = {
                "call_id": metadata.get("retell_call_id"),
                "start_timestamp": metadata.get("start_timestamp"),
                "end_timestamp": metadata.get("end_timestamp"),
                "duration_ms": metadata.get("duration_ms"),
                "lead_status": customer_profile.get("lead_status"),
                "program": customer_profile.get("program") or metadata.get("program"),
            }
            
            # Create time-ordered list of emotional segments
            all_segments = []
            emotion_highlights = []
            speaker_last_emotion: Dict[str, Optional[str]] = {}
            speaker_emotion_counts: Dict[str, Dict[str, int]] = {}
            
            for segment in prosody_segments:
                time_start = segment.get("time_start", 0)
                time_end = segment.get("time_end", 0)
                text = (segment.get("text") or segment.get("transcript_text") or "").strip()
                top_emotions = segment.get("top_emotions", [])
                speaker = segment.get("speaker") or "Unknown"
                if top_emotions:
                    primary_emotion = top_emotions[0].get("name")
                    primary_category = top_emotions[0].get("category", DEFAULT_EMOTION_CATEGORY)
                    if primary_emotion and text:
                        last_emotion = speaker_last_emotion.get(speaker)
                        if primary_emotion != last_emotion:
                            emotion_highlights.append({
                                "speaker": speaker,
                                "time_start": time_start,
                                "time_end": time_end,
                                "text": text,
                                "primary_emotion": primary_emotion,
                                "score": top_emotions[0].get("score"),
                                "category": primary_category,
                            })
                            speaker_last_emotion[speaker] = primary_emotion
                        speaker_emotion_counts.setdefault(speaker, {})
                        speaker_emotion_counts[speaker][primary_emotion] = \
                            speaker_emotion_counts[speaker].get(primary_emotion, 0) + 1

                    all_segments.append({
                        "time_start": time_start,
                        "time_end": time_end,
                        "time_range": f"{time_start:.1f}s-{time_end:.1f}s",
                        "text": text,
                        "speaker": speaker,
                        "top_emotions": [
                            {
                                "name": e.get("name"),
                                "score": e.get("score"),
                                "percentage": e.get("percentage"),
                                "category": e.get("category", DEFAULT_EMOTION_CATEGORY),
                            }
                            for e in top_emotions
                        ]
                    })
            

            
            # Sort by time
            all_segments.sort(key=lambda x: x["time_start"])
            
            file_summary = {
                "filename": filename,
                "segments": all_segments,
                "transcript": [
                    {
                        "time_start": seg.get("start"),
                        "time_end": seg.get("end"),
                        "speaker": seg.get("speaker"),
                        "text": seg.get("text")
                    }
                    for seg in transcript_segments
                ],
                "emotion_highlights": emotion_highlights,
                "speaker_primary_emotions": {
                    speaker: sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
                    for speaker, counts in speaker_emotion_counts.items()
                },
                "context": {
                    "customer": customer_profile,
                    "agent": agent_profile,
                    "call": call_context,
                },
                "category_counts": metadata.get("category_counts"),
            }
            summary_data.append(file_summary)
        
        # Create prompt for OpenAI
        prompt = f"""Analyze the following time-stamped emotion detection results from an audio file and provide a BRIEF, CONCISE summary.

Emotion Data (time-ordered segments with speakers):
{json.dumps(summary_data, indent=2)}

Use these data sections: "segments" (all emotional segments), "transcript" (complete diarized transcript), "emotion_highlights" (meaningful emotion shifts), and "speaker_primary_emotions" (dominant emotions for each speaker). Emotion highlights are ordered by time, but prioritize the customer's experience when summarizing.
You also have a "context" block with customer and agent profile details (names, programs, lead status). Prefer these names over any misheard words in transcripts.
Category counts show how many segments fell into positive, neutral, and negative groupings.

Provide a SHORT summary (1-2 sentences maximum) that:
1. States the practical outcome/result of the recording.
2. Describes the key narrative (why the call happened, major decisions or next steps).
3. Emphasizes the CUSTOMER’S emotional journey first: mention their dominant emotion or any shift (with timestamps) and tie it to the exact quote or action that triggered it.
4. Then mention the Agent’s emotion only if it clearly influences the outcome or marks a shift; avoid repeating the same emotion multiple times.
5. Always acknowledge when the customer commits to a next step (even reluctantly) if the dialogue supports it; never assume refusal without an explicit statement.
6. Keep the tone analytical and concise—no filler phrases.

Example formats:
• "Agent contacts Alexita about the Sterile Processing program and stays calm at 1.2s while explaining the requirements; Alexita shifts from neutrality to disinterest at 18.6s when she asks for a callback. Conversation ends with the Agent agreeing to reconnect later."
• "Customer greets the Agent calmly at 2.9s. Agent becomes determined at 5.4s while pitching the Arcadia interview, then shifts to excitement at 48.3s after the customer confirms Florida residency. Call closes with both aligned on scheduling a follow-up."

Keep it under 100 words."""

        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are an expert contact-center analyst. Produce concise (under 100 words) summaries that report the call outcome, describe the narrative context, and highlight key emotion shifts—always emphasize the customer's emotional journey first, then the agent's only when it impacts the result. Note any customer commitments even when their emotion is muted or negative, and avoid repeating the same emotion unless it changes."},
                {"role": "user", "content": prompt}
            ],
            temperature=0,
            max_tokens=150
        )
        
        summary = response.choices[0].message.content.strip()
        return summary
    
    except Exception as e:
        # If OpenAI fails, return None (non-blocking)
        print(f"Warning: Could not generate summary: {e}")
        return None


def _normalize_sentiment_category(value: Optional[str]) -> str:
    if not value:
        return DEFAULT_EMOTION_CATEGORY
    normalized = str(value).strip().lower()
    if normalized in {"positive", "neutral", "negative"}:
        return normalized
    return DEFAULT_EMOTION_CATEGORY


def determine_overall_call_emotion(
    results: List[Dict[str, Any]],
    summary: Optional[str] = None,
    openai_client: Optional[OpenAI] = None,
) -> Optional[Dict[str, Any]]:
    if not results:
        return None

    timeline_segments: List[Dict[str, Any]] = []
    aggregated_counts = {"positive": 0, "neutral": 0, "negative": 0}

    for result in results:
        prosody_segments = result.get("prosody", []) or []
        metadata = result.get("metadata", {}) or {}
        for segment in prosody_segments:
            time_start = segment.get("time_start")
            time_end = segment.get("time_end", time_start)
            if time_start is None or time_end is None:
                continue
            try:
                start_val = float(time_start)
                end_val = float(time_end)
            except (TypeError, ValueError):
                continue

            speaker = segment.get("speaker") or metadata.get("speaker") or "Unknown"
            top_emotions = segment.get("top_emotions") or []
            primary_category = segment.get("primary_category")
            if not primary_category and top_emotions:
                primary_category = top_emotions[0].get("category")
            normalized_category = _normalize_sentiment_category(primary_category)
            aggregated_counts[normalized_category] += 1

            timeline_segments.append({
                "start": round(start_val, 2),
                "end": round(end_val, 2),
                "speaker": speaker,
                "category": normalized_category,
                "emotion": (top_emotions[0].get("name") if top_emotions else None),
                "text": (segment.get("text") or segment.get("transcript_text") or "").strip(),
            })

    if not timeline_segments:
        return None

    timeline_segments.sort(key=lambda item: item.get("start", 0.0))
    tail_segments = timeline_segments[-12:]
    final_customer_segment = next(
        (segment for segment in reversed(timeline_segments)
         if str(segment.get("speaker", "")).lower() in {"customer", "user", "caller"}),
        timeline_segments[-1],
    )
    final_customer_info = {
        "start": final_customer_segment.get("start"),
        "end": final_customer_segment.get("end"),
        "category": final_customer_segment.get("category"),
        "emotion": final_customer_segment.get("emotion"),
        "text": final_customer_segment.get("text"),
    }

    if openai_client is None:
        openai_client = get_openai_client()

    if openai_client is not None:
        classification_payload = {
            "summary": summary,
            "tail_segments": tail_segments,
            "category_counts": aggregated_counts,
            "final_customer": final_customer_info,
        }
        prompt = (
            "You are an expert QA reviewer for contact-center calls. Analyse the data and decide the call's final sentiment/outcome.\n"
            "Rules:\n"
            "- Look at the customer's willingness to proceed with the AGENT'S ask (e.g. scheduling, link, callback). Emotions alone are not enough.\n"
            "- If the customer accepts or agrees (even reluctantly, e.g. \"fine\", \"okay\", \"send it\"), treat that as a commitment: call_outcome=success and overall_emotion=positive.\n"
            "- If the customer explicitly refuses (e.g. \"no\", \"not interested\", \"don't\") or prosody shows strong negativity matching a refusal, call_outcome=unsuccessful and overall_emotion=negative.\n"
            "- If the agent cannot proceed because requirements are not met or the customer is disqualified (e.g. missing documents, ineligible), treat the call as unsuccessful with overall_emotion=negative unless the customer clearly pivots to an alternative success.\n"
            "- If the customer is busy, asks for a callback, or defers without a definite acceptance (e.g. \"call me later\", \"text me when\" with no confirmation), call_outcome=pending and overall_emotion=neutral unless their tone is unmistakably negative.\n"
            "- If the call ends without any acceptance or agreement throughout the conversation, mark it as call_outcome=pending and overall_emotion=neutral.\n"
            "- Saying \"no\" to additional questions after agreeing does NOT cancel a prior acceptance.\n"
            "- When the behaviour is ambiguous, prefer pending/neutral and document the uncertainty.\n"
            "Return STRICT JSON with keys overall_emotion (positive|neutral|negative), call_outcome (success|unsuccessful|pending), confidence (0-1), reasoning (<=2 sentences referencing the final customer behaviour).\n\n"
            f"Data:\n{json.dumps(classification_payload, ensure_ascii=False, indent=2)}"
        )

        try:
            response = openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are an expert contact-center analyst who produces outcome-focused labels."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=220,
            )
            content = response.choices[0].message.content.strip()
            parsed: Optional[Dict[str, Any]] = None
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                match = re.search(r"\{.*\}", content, re.DOTALL)
                if match:
                    try:
                        parsed = json.loads(match.group(0))
                    except json.JSONDecodeError:
                        parsed = None

            if parsed:
                label_value = _normalize_sentiment_category(parsed.get("overall_emotion"))
                call_outcome_value = str(parsed.get("call_outcome") or "").strip().lower()
                if call_outcome_value not in {"success", "pending", "unsuccessful"}:
                    call_outcome_value = {
                        "positive": "success",
                        "negative": "unsuccessful",
                    }.get(label_value, "pending")

                confidence_raw = parsed.get("confidence")
                try:
                    confidence_value = float(confidence_raw)
                except (TypeError, ValueError):
                    confidence_value = None
                reasoning_text = parsed.get("reasoning")
                if isinstance(reasoning_text, list):
                    reasoning_text = " ".join(str(part) for part in reasoning_text)
                if label_value in {"positive", "neutral", "negative"}:
                    overall_result = {
                        "label": label_value,
                        "call_outcome": call_outcome_value,
                        "confidence": confidence_value if confidence_value is not None else 0.75,
                        "reasoning": str(reasoning_text).strip() if reasoning_text else "",
                        "source": "openai",
                    }
                    logging.getLogger(__name__).info(
                        "Overall call emotion classified by OpenAI (label=%s, outcome=%s)",
                        overall_result.get("label"),
                        overall_result.get("call_outcome"),
                    )
                    return overall_result
        except Exception as exc:  # pylint: disable=broad-except
            print(f"Warning: Overall emotion classification via OpenAI failed: {exc}")

    fallback_label = _normalize_sentiment_category(final_customer_info.get("category"))
    final_text = (final_customer_info.get("text") or "").lower()
    deferral_keywords = (
        "call back", "later", "another time", "not a good time", "busy",
        "can't talk", "cannot talk", "next time", "maybe later"
    )
    if any(keyword in final_text for keyword in deferral_keywords):
        fallback_outcome = "pending"
        fallback_label = "neutral" if fallback_label != "negative" else "negative"
    else:
        outcome_map = {
            "positive": "success",
            "neutral": "pending",
            "negative": "unsuccessful",
        }
        fallback_outcome = outcome_map.get(fallback_label, "pending")
    fallback_reason = "Fallback classification from final customer segment"
    if final_customer_info.get("text"):
        fallback_reason += f": '{final_customer_info['text']}'"

    fallback_result = {
        "label": fallback_label,
        "call_outcome": fallback_outcome,
        "confidence": 0.6 if fallback_label == "positive" else 0.5,
        "reasoning": fallback_reason,
        "source": "fallback",
    }
    logging.getLogger(__name__).info(
        "Overall call emotion determined via fallback (label=%s, outcome=%s)",
        fallback_result.get("label"),
        fallback_result.get("call_outcome"),
    )
    return fallback_result


def analyze_audio_files(
    file_contents: List[Tuple[str, bytes]],
    client: Optional[HumeClient] = None,
    include_summary: bool = True,
    retell_call_id: Optional[str] = None,
    retell_transcript: Optional[List[Dict[str, Any]]] = None,
    retell_metadata: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """
    Complete workflow: submit job, wait for completion, and extract top emotions.
    
    Args:
        file_contents: List of tuples (filename, file_bytes)
        client: Optional HumeClient instance
    
    Returns:
        List of file results with top emotions
    """
    if client is None:
        client = get_hume_client()

    transcript_segments: Optional[List[Dict[str, Any]]] = retell_transcript
    combined_retell_metadata: Dict[str, Any] = dict(retell_metadata or {})

    if transcript_segments is None and retell_call_id:
        try:
            call_data = get_retell_call_details(retell_call_id)
            transcript_segments = extract_retell_transcript_segments(call_data)
            recording_url = call_data.get("recording_multi_channel_url")
            combined_retell_metadata.setdefault("retell_call_id", retell_call_id)
            if recording_url:
                combined_retell_metadata.setdefault("recording_multi_channel_url", recording_url)
            dynamic_variables = call_data.get("retell_llm_dynamic_variables") or {}
            combined_retell_metadata.setdefault("agent", {})
            combined_retell_metadata["agent"].setdefault("id", call_data.get("agent_id"))
            combined_retell_metadata["agent"].setdefault("name", call_data.get("agent_name"))
            combined_retell_metadata["agent"].setdefault("version", call_data.get("agent_version"))
            combined_retell_metadata.setdefault("customer", {})
            if dynamic_variables:
                combined_retell_metadata["customer"].setdefault("first_name", dynamic_variables.get("first_name"))
                combined_retell_metadata["customer"].setdefault("program", dynamic_variables.get("program"))
                combined_retell_metadata["customer"].setdefault("lead_status", dynamic_variables.get("lead_status"))
                combined_retell_metadata["customer"].setdefault("university", dynamic_variables.get("university"))
            combined_retell_metadata.setdefault("retell_llm_dynamic_variables", dynamic_variables)
        except Exception as exc:
            print(f"Warning: Could not fetch Retell call data for {retell_call_id}: {exc}")
    
    # Prepare files
    file_objects = prepare_audio_files(file_contents)
    
    # Submit job
    job_id = submit_hume_job(file_objects, client)
    
    # Wait for completion
    wait_for_job_completion(job_id, client)
    
    # Get predictions
    predictions_data = get_predictions(job_id, client)
    
    # Extract top emotions
    results = extract_top_emotions(predictions_data)

    # Attach transcript and metadata when available
    if transcript_segments:
        results = enrich_results_with_transcript(results, transcript_segments)

    if combined_retell_metadata:
        for result in results:
            result.setdefault("metadata", {}).update(combined_retell_metadata)
    
    # Generate summary using OpenAI if available
    summary: Optional[str] = None
    if include_summary:
        summary = summarize_predictions(results)
        if summary:
            # Add summary to each result
            for result in results:
                result["summary"] = summary
    
    overall_emotion = determine_overall_call_emotion(results, summary)
    if overall_emotion:
        for result in results:
            result.setdefault("metadata", {})["overall_call_emotion"] = overall_emotion
    
    return results

def _normalize_title_text(value: str, max_words: int = 3) -> str:
    if not value:
        return ""
    cleaned = re.sub(r"[^\w\s'-]", " ", str(value))
    tokens = re.findall(r"[A-Za-z0-9']+", cleaned)
    if not tokens:
        return ""
    trimmed = tokens[:max_words]
    normalized_tokens = []
    for token in trimmed:
        if token.isupper():
            normalized_tokens.append(token)
        else:
            normalized_tokens.append(token.capitalize())
    return " ".join(normalized_tokens)


def _heuristic_title_from_summary(summary_text: str) -> Optional[str]:
    lowered = summary_text.lower()

    if "not interested" in lowered or "declined" in lowered or "declines" in lowered or "refused" in lowered:
        return "Not Interested"

    if "voicemail" in lowered:
        if "left a message" in lowered or "leave a message" in lowered:
            return "Left Message"
        return "Voicemail"

    if "callback" in lowered or "call back" in lowered or "follow up" in lowered or "follow-up" in lowered:
        return "Callback Requested"

    if (
        "unreachable" in lowered
        or "no answer" in lowered
        or "did not answer" in lowered
        or "didn't answer" in lowered
        or "unable to reach" in lowered
        or "could not reach" in lowered
        or "never answered" in lowered
    ):
        return "Unreachable"

    if "reschedule" in lowered or "rescheduled" in lowered:
        return "Reschedule"

    if "scheduled" in lowered or "booked" in lowered or "appointment" in lowered or "meeting set" in lowered:
        return "Scheduled"

    if "payment" in lowered and (
        "processed" in lowered
        or "completed" in lowered
        or "taken" in lowered
        or "made" in lowered
    ):
        return "Payment Taken"

    if "transfer" in lowered or "transferred" in lowered or "warm transfer" in lowered:
        return "Transferred"

    if "qualified" in lowered or "approved" in lowered:
        return "Qualified"

    if (
        "interested" in lowered
        or "wants to proceed" in lowered
        or "wants to continue" in lowered
        or "keen to proceed" in lowered
        or "eager to continue" in lowered
    ) and "not interested" not in lowered:
        return "Interested"

    return None


def generate_call_title_from_summary(summary: str, openai_client: Optional[OpenAI] = None) -> Optional[str]:
    summary_text = (summary or "").strip()
    if not summary_text:
        return None

    heuristic_title = _heuristic_title_from_summary(summary_text)
    if heuristic_title:
        return heuristic_title

    if openai_client is None:
        openai_client = get_openai_client()

    if openai_client is not None:
        try:
            response = openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You create concise contact-center call titles. "
                            "Respond with a single title of at most three words in Title Case, "
                            "without punctuation or extra commentary."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"Call summary:\n{summary_text}\n\nProvide a 1-3 word title:",
                    },
                ],
                temperature=0.2,
                max_tokens=16,
            )
            candidate = response.choices[0].message.content.strip()
            normalized = _normalize_title_text(candidate)
            if normalized:
                return normalized
        except Exception as exc:  # pylint: disable=broad-except
            print(f"Warning: Could not generate call title via OpenAI: {exc}")

    tokens = re.findall(r"[A-Za-z0-9']+", summary_text)
    if tokens:
        return _normalize_title_text(" ".join(tokens[:2]))
    return None


def generate_call_purpose_from_summary(summary: str, openai_client: Optional[OpenAI] = None) -> Optional[str]:
    summary_text = (summary or "").strip()
    if not summary_text:
        return None

    if openai_client is None:
        openai_client = get_openai_client()

    if openai_client is None:
        return None

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You classify the primary purpose of contact-center calls. "
                        "Respond with a single label that is exactly one or two words, Title Case, "
                        "describing the customer's main intent or the call outcome (e.g., 'Appointment Booking', 'Insurance Inquiry'). "
                        "Do not add punctuation or commentary."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Call summary:\n"
                        f"{summary_text}\n\n"
                        "Provide the purpose (one or two words):"
                    ),
                },
            ],
            temperature=0.1,
            max_tokens=16,
        )
        candidate = response.choices[0].message.content.strip()
        normalized = _normalize_title_text(candidate, max_words=2)
        return normalized or None
    except Exception as exc:  # pylint: disable=broad-except
        print(f"Warning: Could not generate call purpose via OpenAI: {exc}")
        return None


def derive_short_call_title(
    call_payload: Dict[str, Any],
    fallback_summary: Optional[str] = None,
    openai_client: Optional[OpenAI] = None,
) -> Optional[str]:
    if not isinstance(call_payload, dict):
        return None

    summary_candidates: List[str] = []
    call_analysis = call_payload.get("call_analysis")
    if isinstance(call_analysis, dict):
        for key in ("call_title", "call_summary_title", "summary_title", "call_summary_heading"):
            candidate = call_analysis.get(key)
            normalized = _normalize_title_text(candidate)
            if normalized:
                return normalized

        for key in ("call_summary", "summary", "call_overview", "customer_summary"):
            candidate = call_analysis.get(key)
            if isinstance(candidate, str) and candidate.strip():
                summary_candidates.append(candidate.strip())

    for key in ("call_summary", "summary"):
        candidate = call_payload.get(key)
        if isinstance(candidate, str) and candidate.strip():
            summary_candidates.append(candidate.strip())

    if isinstance(fallback_summary, str) and fallback_summary.strip():
        summary_candidates.append(fallback_summary.strip())

    seen = set()
    for summary_text in summary_candidates:
        if not summary_text or summary_text in seen:
            continue
        seen.add(summary_text)
        title = generate_call_title_from_summary(summary_text, openai_client=openai_client)
        if title:
            return title

    return None
