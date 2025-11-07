import io
import os
import json
import time
import wave
import audioop
import re
from typing import List, Dict, Any, Tuple, Optional, TYPE_CHECKING

import requests
from dotenv import load_dotenv
from hume import HumeClient
from hume.expression_measurement.batch.types import InferenceBaseRequest, Models

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


def prepare_audio_files(file_contents: List[Tuple[str, bytes]]) -> List[Tuple[str, bytes, str]]:
    """
    Prepare audio files for submission to Hume API.
    
    Args:
        file_contents: List of tuples (filename, file_bytes)
    
    Returns:
        List of tuples (filename, file_bytes, content_type)
    """
    file_objects = []
    for filename, file_content in file_contents:
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


def submit_hume_job(file_objects: List[Tuple[str, bytes, str]], client: Optional[HumeClient] = None) -> str:
    """
    Submit audio files to Hume API for emotion analysis.
    
    Args:
        file_objects: List of tuples (filename, file_bytes, content_type)
        client: Optional HumeClient instance (creates new one if not provided)
    
    Returns:
        Job ID string
    """
    if client is None:
        client = get_hume_client()
    
    models_config = Models(prosody={}, burst={})
    inference_request = InferenceBaseRequest(models=models_config)
    
    try:
        # Submit job - pass file_objects directly as in the working code
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
    
    # In the working code, job_id is returned directly as a string
    # But let's handle both cases just in case
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


def wait_for_job_completion(job_id: str, client: Optional[HumeClient] = None, max_wait_time: int = 300, poll_interval: int = 2) -> Dict[str, Any]:
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
            "burst": []
        }
        
        # Process each prediction
        for pred in preds:
            if not isinstance(pred, dict) or "models" not in pred:
                continue
            
            models = pred["models"]
            
            # Extract prosody emotions
            if "prosody" in models and models["prosody"] is not None:
                prosody_data = models["prosody"]
                grouped_preds = prosody_data.get("grouped_predictions", [])
                for group in grouped_preds:
                    for pred_item in group.get("predictions", []):
                        time_info = pred_item.get("time", {})
                        time_start = time_info.get("begin", 0) if isinstance(time_info, dict) else 0
                        time_end = time_info.get("end", 0) if isinstance(time_info, dict) else 0
                        text = pred_item.get("text", "")
                        emotions = pred_item.get("emotions", [])
                        
                        if emotions:
                            top_emotions = sorted(
                                emotions,
                                key=lambda x: x.get("score", 0),
                                reverse=True
                            )[:top_n]
                            
                            file_result["prosody"].append({
                                "time_start": round(time_start, 2),
                                "time_end": round(time_end, 2),
                                "text": text,
                                "top_emotions": [
                                    {
                                        "name": emo.get("name", "Unknown"),
                                        "score": round(emo.get("score", 0), 4),
                                        "percentage": round(emo.get("score", 0) * 100, 1)
                                    }
                                    for emo in top_emotions
                                ]
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
                            
                            file_result["burst"].append({
                                "time_start": round(time_start, 2),
                                "time_end": round(time_end, 2),
                                "top_emotions": [
                                    {
                                        "name": emo.get("name", "Unknown"),
                                        "score": round(emo.get("score", 0), 4),
                                        "percentage": round(emo.get("score", 0) * 100, 1)
                                    }
                                    for emo in top_emotions
                                ]
                            })
        
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


def split_stereo_wav_channels(audio_bytes: bytes) -> Tuple[bytes, bytes]:
    """Split stereo WAV bytes into left (channel 0) and right (channel 1)."""
    audio_buffer = io.BytesIO(audio_bytes)

    with wave.open(audio_buffer, "rb") as wav_in:
        params = wav_in.getparams()
        nchannels, sampwidth, framerate, nframes = params[:4]

        if nchannels != 2:
            raise ValueError("Expected stereo recording (2 channels) from Retell")

        frames = wav_in.readframes(nframes)

    left_frames = audioop.tomono(frames, sampwidth, 1, 0)
    right_frames = audioop.tomono(frames, sampwidth, 0, 1)

    def _build_wav(channel_frames: bytes) -> bytes:
        output_buffer = io.BytesIO()
        with wave.open(output_buffer, "wb") as wav_out:
            wav_out.setnchannels(1)
            wav_out.setsampwidth(sampwidth)
            wav_out.setframerate(framerate)
            wav_out.writeframes(channel_frames)
        return output_buffer.getvalue()

    return _build_wav(left_frames), _build_wav(right_frames)


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
        for prosody_segment in result.get("prosody", []):
            start = prosody_segment.get("time_start", 0.0)
            end = prosody_segment.get("time_end", 0.0)
            matched_segment = _find_best_transcript_match(start, end, transcript_segments)
            if matched_segment:
                prosody_segment["speaker"] = matched_segment.get("speaker")
                transcript_text = matched_segment.get("text")
                if transcript_text:
                    prosody_segment["transcript_text"] = transcript_text
                    prosody_segment["text"] = transcript_text
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
            transcript_segments = result.get("metadata", {}).get("retell_transcript_segments", [])
            
            # Create time-ordered list of emotional segments
            all_segments = []
            emotion_highlights = []
            speaker_last_emotion: Dict[str, Optional[str]] = {}
            speaker_emotion_counts: Dict[str, Dict[str, int]] = {}
            
            for segment in prosody_segments:
                time_start = segment.get("time_start", 0)
                time_end = segment.get("time_end", 0)
                text = segment.get("text", "")
                top_emotions = segment.get("top_emotions", [])
                speaker = segment.get("speaker") or "Unknown"
                if top_emotions:
                    primary_emotion = top_emotions[0].get("name")
                    if primary_emotion:
                        last_emotion = speaker_last_emotion.get(speaker)
                        if primary_emotion != last_emotion:
                            emotion_highlights.append({
                                "speaker": speaker,
                                "time_start": time_start,
                                "time_end": time_end,
                                "text": text,
                                "primary_emotion": primary_emotion,
                                "score": top_emotions[0].get("score"),
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
                        "top_emotions": [{"name": e.get("name"), "score": e.get("score"), "percentage": e.get("percentage")} for e in top_emotions]
                    })
            
            for segment in burst_segments:
                time_start = segment.get("time_start", 0)
                time_end = segment.get("time_end", 0)
                top_emotions = segment.get("top_emotions", [])
                speaker = segment.get("speaker") or "Unknown"
                if top_emotions:
                    primary_emotion = top_emotions[0].get("name")
                    if primary_emotion:
                        last_emotion = speaker_last_emotion.get(speaker)
                        if primary_emotion != last_emotion:
                            emotion_highlights.append({
                                "speaker": speaker,
                                "time_start": time_start,
                                "time_end": time_end,
                                "text": segment.get("transcript_text", ""),
                                "primary_emotion": primary_emotion,
                                "score": top_emotions[0].get("score"),
                                "type": "vocal_burst",
                            })
                            speaker_last_emotion[speaker] = primary_emotion
                        speaker_emotion_counts.setdefault(speaker, {})
                        speaker_emotion_counts[speaker][primary_emotion] = \
                            speaker_emotion_counts[speaker].get(primary_emotion, 0) + 1

                    all_segments.append({
                        "time_start": time_start,
                        "time_end": time_end,
                        "time_range": f"{time_start:.1f}s-{time_end:.1f}s",
                        "type": "vocal_burst",
                        "speaker": speaker,
                        "top_emotions": [{"name": e.get("name"), "score": e.get("score"), "percentage": e.get("percentage")} for e in top_emotions]
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
                }
            }
            summary_data.append(file_summary)
        
        # Create prompt for OpenAI
        prompt = f"""Analyze the following time-stamped emotion detection results from an audio file and provide a BRIEF, CONCISE summary.

Emotion Data (time-ordered segments with speakers):
{json.dumps(summary_data, indent=2)}

Use these data sections: "segments" (all emotional segments), "transcript" (complete diarized transcript), "emotion_highlights" (meaningful emotion shifts), and "speaker_primary_emotions" (dominant emotions for each speaker). Emotion highlights are ordered by time, but prioritize the customer's experience when summarizing.

Provide a SHORT summary (1-2 sentences maximum) that:
1. States the practical outcome/result of the recording.
2. Describes the key narrative (why the call happened, major decisions or next steps).
3. Emphasizes the CUSTOMER’S emotional journey first: mention their dominant emotion or any shift (with timestamps) and tie it to the exact quote or action that triggered it.
4. Then mention the Agent’s emotion only if it clearly influences the outcome or marks a shift; avoid repeating the same emotion multiple times.
5. Keep the tone analytical and concise—no filler phrases.

Example formats:
• "Agent contacts Alexita about the Sterile Processing program and stays calm at 1.2s while explaining the requirements; Alexita shifts from neutrality to disinterest at 18.6s when she asks for a callback. Conversation ends with the Agent agreeing to reconnect later."
• "Customer greets the Agent calmly at 2.9s. Agent becomes determined at 5.4s while pitching the Arcadia interview, then shifts to excitement at 48.3s after the customer confirms Florida residency. Call closes with both aligned on scheduling a follow-up."

Keep it under 100 words."""

        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are an expert contact-center analyst. Produce concise (under 100 words) summaries that report the call outcome, describe the narrative context, and highlight key emotion shifts—always emphasize the customer's emotional journey first, then the agent's only when it impacts the result. Avoid repeating the same emotion unless it changes."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.5,
            max_tokens=150
        )
        
        summary = response.choices[0].message.content.strip()
        return summary
    
    except Exception as e:
        # If OpenAI fails, return None (non-blocking)
        print(f"Warning: Could not generate summary: {e}")
        return None


def analyze_audio_files(
    file_contents: List[Tuple[str, bytes]],
    client: Optional[HumeClient] = None,
    include_summary: bool = True,
    retell_call_id: Optional[str] = None,
    retell_transcript: Optional[List[Dict[str, Any]]] = None
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
    retell_metadata: Dict[str, Any] = {}

    if transcript_segments is None and retell_call_id:
        try:
            call_data = get_retell_call_details(retell_call_id)
            transcript_segments = extract_retell_transcript_segments(call_data)
            recording_url = call_data.get("recording_multi_channel_url")
            retell_metadata = {
                "retell_call_id": retell_call_id,
                "retell_recording_multi_channel_url": recording_url
            }
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

    if retell_metadata:
        for result in results:
            result.setdefault("metadata", {}).update(retell_metadata)
    
    # Generate summary using OpenAI if available
    if include_summary:
        summary = summarize_predictions(results)
        if summary:
            # Add summary to each result
            for result in results:
                result["summary"] = summary
    
    return results


