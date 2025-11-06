import os
import json
import time
from hume import HumeClient
from hume.expression_measurement.batch.types import InferenceBaseRequest, Models


HUME_API_KEY = "Isaq8XuI02sABht8LC0J8DVkRieiA7Gc8J1JFbObpO1zid6m"

def test_hume_expression_measurement():
    # Initialize the Hume client
    client = HumeClient(api_key=HUME_API_KEY)
    
    # Get audio files in the current directory
    audio_files = [f for f in os.listdir(".") if f.lower().endswith((".wav", ".mp3", ".m4a", ".flac"))]
    
    if not audio_files:
        print("No audio files found in current directory.")
        return
    
    print(f"Processing {len(audio_files)} files: {audio_files}")
    
    # Configure models for speech prosody and vocal bursts
    models_config = Models(prosody={}, burst={})
    inference_request = InferenceBaseRequest(models=models_config)
    
    print("\nSubmitting batch job...")
    try:
        # Open files as file objects (some APIs prefer this over filenames)
        file_objects = []
        for filename in audio_files:
            try:
                with open(filename, 'rb') as f:
                    # Read the file content and pass as bytes
                    file_content = f.read()
                    # Pass as tuple (filename, content, content_type) for better recognition
                    file_objects.append((filename, file_content, 'audio/wav'))
            except Exception as e:
                print(f"Warning: Could not read {filename}: {e}")
                # Fallback to just filename
                file_objects.append(filename)
        
        # Submit job with local files
        job_id = client.expression_measurement.batch.start_inference_job_from_local_file(
            file=file_objects if file_objects else audio_files,
            json=inference_request
        )
        
        print(f"Job ID: {job_id}")
        print("Waiting for completion...")
        
        # Poll for job status
        job_details = None
        while True:
            job_details = client.expression_measurement.batch.get_job_details(job_id)
            status = job_details.state.value if hasattr(job_details.state, 'value') else str(job_details.state)
            
            if "COMPLETED" in status.upper() or "completed" in status.lower():
                print(f"Job completed!")
                break
            elif "FAILED" in status.upper() or "failed" in status.lower():
                print(f"Job failed with status: {status}")
                if hasattr(job_details, 'error'):
                    print(f"Error: {job_details.error}")
                # Print full job details for debugging
                if hasattr(job_details, 'model_dump'):
                    print(f"Job details: {job_details.model_dump()}")
                return
            print(f"  Status: {status}... waiting...")
            time.sleep(5)  # Wait 5 seconds before checking again
        
        # Debug: Print job details to see what was processed
        if job_details:
            print(f"\nJob details retrieved.")
            if hasattr(job_details, 'model_dump'):
                job_dict = job_details.model_dump()
                print(f"Job state: {job_dict.get('state', 'unknown')}")
                if 'files_processed' in job_dict:
                    print(f"Files processed: {job_dict['files_processed']}")
                if 'files_total' in job_dict:
                    print(f"Files total: {job_dict['files_total']}")
        
        # Get predictions
        print("\nRetrieving predictions...")
        try:
            predictions_response = client.expression_measurement.batch.get_job_predictions(job_id)
        except Exception as e:
            print(f"Error retrieving predictions: {e}")
            print("Trying to get job details for more information...")
            if job_details and hasattr(job_details, 'model_dump'):
                print(f"Full job details: {json.dumps(job_details.model_dump(), indent=2, default=str)}")
            raise
        
        # Convert predictions response to dictionary format
        if hasattr(predictions_response, 'model_dump'):
            predictions_data = predictions_response.model_dump()
        elif hasattr(predictions_response, 'dict'):
            predictions_data = predictions_response.dict()
        elif isinstance(predictions_response, list):
            # If it's a list, try to convert each item
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
        
        # Save predictions to file
        with open("predictions.json", "w") as f:
            json.dump(predictions_data, f, indent=2, default=str)
        
        print("Predictions saved to predictions.json")
        
        print("\n" + "="*70)
        print("HUME EMOTION RESULTS")
        print("="*70)
        
        # Parse predictions response structure
        # Format: [{source: {...}, results: {predictions: [...]}}]
        results_list = []
        if isinstance(predictions_data, list):
            # Process each file result
            for item in predictions_data:
                if isinstance(item, dict) and "results" in item:
                    result_obj = item["results"]
                    if isinstance(result_obj, dict) and "predictions" in result_obj:
                        predictions_array = result_obj["predictions"]
                        if predictions_array:
                            results_list.append(predictions_array)
                        else:
                            results_list.append({})
                    else:
                        results_list.append(result_obj if isinstance(result_obj, dict) else {})
                else:
                    results_list.append(item if isinstance(item, dict) else {})
        elif isinstance(predictions_data, dict):
            if "results" in predictions_data and "predictions" in predictions_data["results"]:
                preds = predictions_data["results"]["predictions"]
                results_list = preds if isinstance(preds, list) else [preds]
            else:
                results_list = [predictions_data]
        
        # Flatten results if needed
        flattened_results = []
        for result in results_list:
            if isinstance(result, list):
                for pred in result:
                    if isinstance(pred, dict):
                        flattened_results.append(pred)
            else:
                flattened_results.append(result)
        results_list = flattened_results
        
        # Check for errors first
        if isinstance(predictions_data, list):
            for item in predictions_data:
                if isinstance(item, dict):
                    errors = item.get("results", {}).get("errors", [])
                    if errors:
                        print(f"\nWARNING: Errors found in processing:")
                        for error in errors:
                            print(f"  - {error}")
                    # Check if there's an error at the top level
                    if item.get("error"):
                        print(f"\nWARNING: Error in job: {item.get('error')}")
        
        # Check if we actually have any non-empty predictions
        has_predictions = False
        if isinstance(predictions_data, list):
            for item_idx, item in enumerate(predictions_data):
                if isinstance(item, dict) and "results" in item:
                    preds = item.get("results", {}).get("predictions", [])
                    if preds:
                        # Check if any prediction has models with data
                        for pred_idx, pred in enumerate(preds):
                            if isinstance(pred, dict) and "models" in pred:
                                models = pred["models"]
                                prosody = models.get("prosody")
                                burst = models.get("burst")
                                # Check if prosody or burst exist and are not None/empty
                                if (prosody is not None and prosody != {}) or (burst is not None and burst != {}):
                                    has_predictions = True
                                    break
                        if has_predictions:
                            break
        
        if not has_predictions:
            print("\nWARNING: No predictions found in response.")
            print("This could mean:")
            print("  1. The audio files contain no detectable speech")
            print("  2. The files are too short or corrupted")
            print("  3. The audio format is not supported")
            print("  4. The models need different configuration")
            
            # Show file info
            if isinstance(predictions_data, list):
                for i, item in enumerate(predictions_data):
                    filename = audio_files[i] if i < len(audio_files) else f"File {i+1}"
                    source = item.get("source", {})
                    print(f"\n  {filename}:")
                    print(f"    - Content type: {source.get('content_type', 'unknown')}")
                    print(f"    - MD5: {source.get('md_5_sum', 'unknown')}")
                    if "results" in item:
                        results_obj = item["results"]
                        pred_count = len(results_obj.get("predictions", []))
                        print(f"    - Predictions returned: {pred_count}")
                        if results_obj.get("errors"):
                            print(f"    - Errors: {results_obj['errors']}")
            return
    
        # Process predictions and match them to files
        # Structure: [{source: {...}, results: {predictions: [{models: {prosody: {...}, burst: {...}}}]}}]
        file_results = []
        if isinstance(predictions_data, list):
            for item in predictions_data:
                if isinstance(item, dict) and "results" in item:
                    preds = item.get("results", {}).get("predictions", [])
                    # Combine all predictions for this file
                    combined = {}
                    for pred in preds:
                        if isinstance(pred, dict) and "models" in pred:
                            models = pred["models"]
                            # Extract prosody and burst from models
                            for key in ["prosody", "burst"]:
                                if key in models and models[key] is not None:
                                    if key not in combined:
                                        combined[key] = models[key]
                                    else:
                                        # Merge predictions from grouped_predictions
                                        if isinstance(combined[key], dict) and "grouped_predictions" in combined[key]:
                                            existing_groups = combined[key]["grouped_predictions"]
                                            new_groups = models[key].get("grouped_predictions", [])
                                            combined[key]["grouped_predictions"] = existing_groups + new_groups
                    file_results.append(combined if combined else {})
                else:
                    file_results.append({})
        
        # Process each file result
        # Use file_results if available, otherwise use results_list
        processed_results = file_results if file_results else results_list
        
        for i, result in enumerate(processed_results):
            filename = audio_files[i] if i < len(audio_files) else f"File {i+1}"
            print(f"\n{filename}")
            print("─" * 50)
            
            # Check if result is a string (from string conversion) and try to parse
            if isinstance(result, str):
                print(f"  WARNING: Result is a string: {result[:100]}...")
                continue
            
            # Process prosody and burst results
            # Structure: {prosody: {grouped_predictions: [{predictions: [{time: {...}, emotions: [...]}]}]}}
            has_data = False
            if isinstance(result, dict):
                # Process prosody results (speech emotions)
                if "prosody" in result:
                    prosody_data = result["prosody"]
                    has_data = True
                    if isinstance(prosody_data, dict):
                        grouped_preds = prosody_data.get("grouped_predictions", [])
                        if grouped_preds:
                            print("\nSpeech Prosody Emotions:")
                            for group in grouped_preds:
                                preds = group.get("predictions", [])
                                for pred in preds:
                                    time_info = pred.get("time", {})
                                    time_start = time_info.get("begin", 0) if isinstance(time_info, dict) else 0
                                    time_end = time_info.get("end", 0) if isinstance(time_info, dict) else 0
                                    text = pred.get("text", "")
                                    emotions = pred.get("emotions", [])
                                    if emotions:
                                        # Get top 3 emotions
                                        emotions_sorted = sorted(emotions, key=lambda x: x.get("score", 0), reverse=True)[:3]
                                        if text:
                                            print(f"\n[{time_start:.1f}s - {time_end:.1f}s] \"{text}\"")
                                        else:
                                            print(f"\n[{time_start:.1f}s - {time_end:.1f}s]")
                                        for idx, emo in enumerate(emotions_sorted, 1):
                                            score = emo.get("score", 0)
                                            # Score is a probability (0.0 to 1.0) - higher means more prominent
                                            bar = "█" * int(score * 30)
                                            print(f"   {idx}. {emo.get('name', 'Unknown'):<20}: {score:.3f} ({score*100:.1f}%) {bar}")
                
                # Process burst results (vocal bursts)
                if "burst" in result:
                    burst_data = result["burst"]
                    has_data = True
                    if isinstance(burst_data, dict):
                        grouped_preds = burst_data.get("grouped_predictions", [])
                        if grouped_preds:
                            print("\nVocal Bursts:")
                            for group in grouped_preds:
                                preds = group.get("predictions", [])
                                for pred in preds:
                                    time_info = pred.get("time", {})
                                    time_start = time_info.get("begin", 0) if isinstance(time_info, dict) else 0
                                    time_end = time_info.get("end", 0) if isinstance(time_info, dict) else 0
                                    emotions = pred.get("emotions", [])
                                    if emotions:
                                        # Get top 3 emotions
                                        emotions_sorted = sorted(emotions, key=lambda x: x.get("score", 0), reverse=True)[:3]
                                        print(f"\n[{time_start:.1f}s - {time_end:.1f}s]")
                                        for idx, emo in enumerate(emotions_sorted, 1):
                                            score = emo.get("score", 0)
                                            # Score is a probability (0.0 to 1.0) - higher means more prominent
                                            bar = "█" * int(score * 30)
                                            print(f"   {idx}. {emo.get('name', 'Unknown'):<20}: {score:.3f} ({score*100:.1f}%) {bar}")
                
                # If no data found at all
                if not has_data:
                    print(f"  (No emotion data detected)")
                    print(f"  This may indicate:")
                    print(f"    - Audio file contains no speech")
                    print(f"    - File is too short or corrupted")
                    print(f"    - Audio format issue")
        
        print("\nProcessing complete!")
        
    except Exception as e:
        print(f"Error processing job: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_hume_expression_measurement()
