import os
import json
import time
import re
from typing import List, Dict, Any, Tuple, Optional
from dotenv import load_dotenv
from hume import HumeClient
from hume.expression_measurement.batch.types import InferenceBaseRequest, Models
from openai import OpenAI

# Load environment variables
load_dotenv()
HUME_API_KEY = os.getenv("HUME_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

if not HUME_API_KEY:
    raise ValueError("HUME_API_KEY not found in environment variables. Please set it in .env file")


def get_hume_client() -> HumeClient:
    """Initialize and return Hume client"""
    return HumeClient(api_key=HUME_API_KEY)


def get_openai_client() -> Optional[OpenAI]:
    """Initialize and return OpenAI client if API key is available"""
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


def extract_top_emotions(predictions_data: List[Dict[str, Any]], top_n: int = 3) -> List[Dict[str, Any]]:
    """
    Extract top N emotions from predictions data.
    
    Args:
        predictions_data: List of prediction dictionaries from get_predictions
        top_n: Number of top emotions to return per segment (default: 3)
    
    Returns:
        List of file results with top emotions
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
            
            # Create time-ordered list of emotional segments
            all_segments = []
            
            for segment in prosody_segments:
                time_start = segment.get("time_start", 0)
                time_end = segment.get("time_end", 0)
                text = segment.get("text", "")
                top_emotions = segment.get("top_emotions", [])
                if top_emotions:
                    all_segments.append({
                        "time_start": time_start,
                        "time_end": time_end,
                        "time_range": f"{time_start:.1f}s-{time_end:.1f}s",
                        "text": text,
                        "top_emotions": [{"name": e.get("name"), "score": e.get("score"), "percentage": e.get("percentage")} for e in top_emotions]
                    })
            
            for segment in burst_segments:
                time_start = segment.get("time_start", 0)
                time_end = segment.get("time_end", 0)
                top_emotions = segment.get("top_emotions", [])
                if top_emotions:
                    all_segments.append({
                        "time_start": time_start,
                        "time_end": time_end,
                        "time_range": f"{time_start:.1f}s-{time_end:.1f}s",
                        "type": "vocal_burst",
                        "top_emotions": [{"name": e.get("name"), "score": e.get("score"), "percentage": e.get("percentage")} for e in top_emotions]
                    })
            
            # Sort by time
            all_segments.sort(key=lambda x: x["time_start"])
            
            file_summary = {
                "filename": filename,
                "segments": all_segments
            }
            summary_data.append(file_summary)
        
        # Create prompt for OpenAI
        prompt = f"""Analyze the following time-stamped emotion detection results from an audio file and provide a BRIEF, CONCISE summary.

Emotion Data (time-ordered segments):
{json.dumps(summary_data, indent=2)}

Provide a SHORT summary (1-2 sentences maximum) that:
1. States the overall emotional outcome/result of the recording
2. Highlights key emotion changes WITH TIMESTAMPS when emotions shift significantly
3. Be direct and avoid redundancy

Example format: "The recording shows [overall emotion]. At [time], emotion shifts to [new emotion] when [context]. Overall [outcome]."

Keep it under 100 words and focus only on significant emotional changes with timestamps."""

        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are an expert at providing concise, time-aware summaries of emotional data. Be brief and direct."},
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


def analyze_audio_files(file_contents: List[Tuple[str, bytes]], client: Optional[HumeClient] = None, include_summary: bool = True) -> List[Dict[str, Any]]:
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
    
    # Generate summary using OpenAI if available
    if include_summary:
        summary = summarize_predictions(results)
        if summary:
            # Add summary to each result
            for result in results:
                result["summary"] = summary
    
    return results


