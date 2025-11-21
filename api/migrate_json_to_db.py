"""
Migration script to import existing JSON data into PostgreSQL database.
Reads retell_calls.json and individual call JSON files, then imports all data.
"""

import json
import os
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from database import (
    SessionLocal, Call, EmotionSegment, EmotionPrediction, 
    TranscriptSegment, AnalysisSummary
)

RETELL_RESULTS_DIR = os.getenv("RETELL_RESULTS_DIR", "retell_results")
RETELL_CALLS_FILENAME = os.path.join(RETELL_RESULTS_DIR, "retell_calls.json")


def load_json_file(filepath: str) -> Optional[Dict[str, Any]]:
    """Load JSON file and return parsed data."""
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading {filepath}: {e}")
        return None


def migrate_call_metadata(db: Session, call_data: Dict[str, Any]) -> Optional[Call]:
    """Migrate call metadata to database."""
    call_id = call_data.get("call_id")
    if not call_id:
        return None
    
    # Check if call already exists
    existing_call = db.query(Call).filter(Call.call_id == call_id).first()
    if existing_call:
        print(f"  Call {call_id} already exists, skipping...")
        return existing_call
    
    # Create new call record
    call = Call(
        call_id=call_id,
        agent_id=call_data.get("agent_id"),
        agent_name=call_data.get("agent_name"),
        user_phone_number=call_data.get("user_phone_number"),
        start_timestamp=call_data.get("start_timestamp"),
        end_timestamp=call_data.get("end_timestamp"),
        duration_ms=call_data.get("duration_ms"),
        recording_multi_channel_url=call_data.get("recording_multi_channel_url"),
        analysis_status=call_data.get("analysis_status", "pending"),
        analysis_available=call_data.get("analysis_available", False),
        analysis_allowed=call_data.get("analysis_allowed", True),
        analysis_block_reason=call_data.get("analysis_block_reason"),
        error_message=call_data.get("error_message"),
        call_purpose=call_data.get("call_purpose"),
        call_summary=call_data.get("call_summary"),
        call_title=call_data.get("call_title"),
        overall_emotion_label=call_data.get("overall_emotion_label"),
        overall_emotion_json=call_data.get("overall_emotion"),
        transcript_available=call_data.get("transcript_available", False),
        transcript_object=call_data.get("transcript_object"),
        analysis_constraints=call_data.get("analysis_constraints"),
    )
    
    # Parse last_updated if it's a string
    last_updated = call_data.get("last_updated")
    if isinstance(last_updated, str):
        try:
            # Remove 'Z' suffix and parse
            last_updated = last_updated.rstrip("Z")
            call.last_updated = datetime.fromisoformat(last_updated)
        except:
            pass
    
    db.add(call)
    return call


def migrate_analysis_results(db: Session, call_id: str, analysis_data: List[Dict[str, Any]]):
    """Migrate analysis results (emotion segments, predictions, summaries) to database."""
    for result in analysis_data:
        if not isinstance(result, dict):
            continue
        
        # Migrate prosody segments
        prosody_segments = result.get("prosody", [])
        for segment_data in prosody_segments:
            migrate_emotion_segment(db, call_id, segment_data, "prosody")
        
        # Migrate burst segments
        burst_segments = result.get("burst", [])
        for segment_data in burst_segments:
            migrate_emotion_segment(db, call_id, segment_data, "burst")
        
        # Migrate transcript segments from metadata
        metadata = result.get("metadata", {})
        transcript_segments = metadata.get("retell_transcript_segments", [])
        for transcript_data in transcript_segments:
            migrate_transcript_segment(db, call_id, transcript_data)
        
        # Migrate summary
        summary_text = result.get("summary")
        if summary_text:
            migrate_analysis_summary(db, call_id, summary_text, "openai")


def migrate_emotion_segment(db: Session, call_id: str, segment_data: Dict[str, Any], segment_type: str):
    """Migrate a single emotion segment."""
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
    
    # Migrate emotion predictions
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


def migrate_transcript_segment(db: Session, call_id: str, transcript_data: Dict[str, Any]):
    """Migrate a single transcript segment."""
    # Check if already exists (avoid duplicates)
    start_time = transcript_data.get("start", 0.0)
    end_time = transcript_data.get("end", 0.0)
    speaker = transcript_data.get("speaker")
    text = transcript_data.get("text", "")
    
    existing = db.query(TranscriptSegment).filter(
        TranscriptSegment.call_id == call_id,
        TranscriptSegment.start_time == start_time,
        TranscriptSegment.speaker == speaker
    ).first()
    
    if existing:
        return  # Skip duplicate
    
    segment = TranscriptSegment(
        call_id=call_id,
        speaker=speaker or "Unknown",
        start_time=float(start_time) if start_time is not None else 0.0,
        end_time=float(end_time) if end_time is not None else 0.0,
        text=text,
        confidence=transcript_data.get("confidence"),
    )
    db.add(segment)


def migrate_analysis_summary(db: Session, call_id: str, summary_text: str, summary_type: str):
    """Migrate analysis summary."""
    # Check if already exists
    existing = db.query(AnalysisSummary).filter(
        AnalysisSummary.call_id == call_id,
        AnalysisSummary.summary_type == summary_type
    ).first()
    
    if existing:
        return  # Skip duplicate
    
    summary = AnalysisSummary(
        call_id=call_id,
        summary_text=summary_text,
        summary_type=summary_type,
    )
    db.add(summary)


def migrate_all_data():
    """Main migration function."""
    db = SessionLocal()
    
    try:
        print("Starting data migration...")
        print(f"Loading calls from {RETELL_CALLS_FILENAME}")
        
        # Load main calls file
        calls_data = load_json_file(RETELL_CALLS_FILENAME)
        if not calls_data:
            print(f"Error: Could not load {RETELL_CALLS_FILENAME}")
            return
        
        calls_dict = calls_data.get("calls", {})
        total_calls = len(calls_dict)
        print(f"Found {total_calls} calls to migrate")
        
        migrated_count = 0
        skipped_count = 0
        error_count = 0
        
        # Migrate each call
        for idx, (call_id, call_data) in enumerate(calls_dict.items(), 1):
            try:
                print(f"\n[{idx}/{total_calls}] Migrating call {call_id}...")
                
                # Skip zero-duration calls
                duration_ms = call_data.get("duration_ms")
                if duration_ms is not None and duration_ms <= 0:
                    print(f"  Skipping zero-duration call")
                    skipped_count += 1
                    continue
                
                # Migrate call metadata
                call = migrate_call_metadata(db, call_data)
                if not call:
                    print(f"  Error: Could not migrate call metadata")
                    error_count += 1
                    continue
                
                # Migrate analysis results if available
                analysis_filename = call_data.get("analysis_filename")
                if analysis_filename:
                    analysis_path = os.path.join(RETELL_RESULTS_DIR, analysis_filename)
                    analysis_data = load_json_file(analysis_path)
                    
                    if analysis_data:
                        analysis_results = analysis_data.get("analysis", [])
                        if analysis_results:
                            print(f"  Migrating analysis results...")
                            migrate_analysis_results(db, call_id, analysis_results)
                            print(f"  Analysis results migrated")
                
                # Commit this call
                db.commit()
                migrated_count += 1
                print(f"  ✓ Call migrated successfully")
                
            except IntegrityError as e:
                db.rollback()
                print(f"  Error: Integrity error - {e}")
                error_count += 1
            except Exception as e:
                db.rollback()
                print(f"  Error migrating call {call_id}: {e}")
                error_count += 1
        
        print(f"\n{'='*60}")
        print(f"Migration complete!")
        print(f"  Migrated: {migrated_count}")
        print(f"  Skipped: {skipped_count}")
        print(f"  Errors: {error_count}")
        print(f"  Total: {total_calls}")
        
    except Exception as e:
        db.rollback()
        print(f"Fatal error during migration: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    migrate_all_data()

