"""
Database models and session management for PostgreSQL using SQLAlchemy ORM.
"""

import json
from datetime import datetime
from typing import Optional, Dict, Any, List
from sqlalchemy import (
    create_engine, Column, String, Integer, BigInteger, Boolean, Text, 
    DateTime, ForeignKey, Numeric, Index, JSON as SQLJSON
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship, Session
from sqlalchemy.dialects.postgresql import JSONB
from dotenv import load_dotenv
import os

load_dotenv()

Base = declarative_base()

# Database connection
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is not set")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Session:
    """Dependency for FastAPI to get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class Call(Base):
    """Main call metadata table."""
    __tablename__ = "calls"

    call_id = Column(String(255), primary_key=True, index=True)
    agent_id = Column(String(255), nullable=True, index=True)
    agent_name = Column(String(255), nullable=True)
    user_phone_number = Column(String(50), nullable=True)
    
    start_timestamp = Column(BigInteger, nullable=True, index=True)
    end_timestamp = Column(BigInteger, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    
    recording_multi_channel_url = Column(Text, nullable=True)
    
    analysis_status = Column(String(50), nullable=False, default="pending", index=True)
    analysis_available = Column(Boolean, default=False)
    analysis_allowed = Column(Boolean, default=True)
    analysis_block_reason = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    
    call_purpose = Column(String(255), nullable=True)
    call_summary = Column(Text, nullable=True)
    call_title = Column(String(255), nullable=True)
    
    overall_emotion_label = Column(String(50), nullable=True, index=True)
    overall_emotion_json = Column(JSONB, nullable=True)
    
    transcript_available = Column(Boolean, default=False)
    transcript_object = Column(JSONB, nullable=True)
    
    analysis_constraints = Column(JSONB, nullable=True)
    
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    emotion_segments = relationship("EmotionSegment", back_populates="call", cascade="all, delete-orphan", lazy="dynamic")
    transcript_segments = relationship("TranscriptSegment", back_populates="call", cascade="all, delete-orphan", lazy="dynamic")
    analysis_summaries = relationship("AnalysisSummary", back_populates="call", cascade="all, delete-orphan", lazy="dynamic")

    def to_dict(self) -> Dict[str, Any]:
        """Convert Call model to dictionary format compatible with existing code."""
        result = {
            "call_id": self.call_id,
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "user_phone_number": self.user_phone_number,
            "start_timestamp": self.start_timestamp,
            "end_timestamp": self.end_timestamp,
            "duration_ms": self.duration_ms,
            "recording_multi_channel_url": self.recording_multi_channel_url,
            "analysis_status": self.analysis_status,
            "analysis_available": self.analysis_available,
            "analysis_allowed": self.analysis_allowed,
            "analysis_block_reason": self.analysis_block_reason,
            "error_message": self.error_message,
            "call_purpose": self.call_purpose,
            "call_summary": self.call_summary,
            "call_title": self.call_title,
            "overall_emotion_label": self.overall_emotion_label,
            "transcript_available": self.transcript_available,
        }
        
        # Convert JSONB fields
        if self.overall_emotion_json:
            result["overall_emotion"] = self.overall_emotion_json
        if self.transcript_object:
            result["transcript_object"] = self.transcript_object
        if self.analysis_constraints:
            result["analysis_constraints"] = self.analysis_constraints
        
        # Format last_updated as ISO string
        if self.last_updated:
            result["last_updated"] = self.last_updated.replace(microsecond=0).isoformat() + "Z"
        
        return result


class EmotionSegment(Base):
    """Emotion segments (prosody and burst) table."""
    __tablename__ = "emotion_segments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    call_id = Column(String(255), ForeignKey("calls.call_id", ondelete="CASCADE"), nullable=False, index=True)
    segment_type = Column(String(20), nullable=False)  # 'prosody' or 'burst'
    time_start = Column(Numeric(10, 2), nullable=False)
    time_end = Column(Numeric(10, 2), nullable=False)
    speaker = Column(String(50), nullable=True, index=True)
    text = Column(Text, nullable=True)
    transcript_text = Column(Text, nullable=True)
    primary_category = Column(String(50), nullable=True, index=True)
    source = Column(String(20), nullable=False)  # 'prosody' or 'burst'
    
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    call = relationship("Call", back_populates="emotion_segments")
    predictions = relationship("EmotionPrediction", back_populates="segment", cascade="all, delete-orphan")

    def to_dict(self) -> Dict[str, Any]:
        """Convert EmotionSegment to dictionary format."""
        result = {
            "time_start": float(self.time_start) if self.time_start else 0.0,
            "time_end": float(self.time_end) if self.time_end else 0.0,
            "primary_category": self.primary_category,
            "source": self.source,
        }
        
        if self.speaker:
            result["speaker"] = self.speaker
        if self.text:
            result["text"] = self.text
        if self.transcript_text:
            result["transcript_text"] = self.transcript_text
        
        # Include predictions - access via relationship query
        predictions_list = list(self.predictions)
        if predictions_list:
            result["top_emotions"] = [
                {
                    "name": pred.emotion_name,
                    "score": float(pred.score) if pred.score else 0.0,
                    "percentage": float(pred.percentage) if pred.percentage else 0.0,
                    "category": pred.category,
                }
                for pred in sorted(predictions_list, key=lambda x: x.rank)
            ]
        
        return result


class EmotionPrediction(Base):
    """Individual emotion predictions per segment."""
    __tablename__ = "emotion_predictions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    segment_id = Column(Integer, ForeignKey("emotion_segments.id", ondelete="CASCADE"), nullable=False, index=True)
    emotion_name = Column(String(100), nullable=False, index=True)
    score = Column(Numeric(5, 4), nullable=False)
    percentage = Column(Numeric(5, 1), nullable=False)
    category = Column(String(50), nullable=False, index=True)
    rank = Column(Integer, nullable=False)  # 1 = top emotion, 2 = second, etc.
    
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    segment = relationship("EmotionSegment", back_populates="predictions")


class TranscriptSegment(Base):
    """Original transcript segments table."""
    __tablename__ = "transcript_segments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    call_id = Column(String(255), ForeignKey("calls.call_id", ondelete="CASCADE"), nullable=False, index=True)
    speaker = Column(String(50), nullable=False, index=True)
    start_time = Column(Numeric(10, 2), nullable=False)
    end_time = Column(Numeric(10, 2), nullable=False)
    text = Column(Text, nullable=False)
    confidence = Column(Numeric(5, 4), nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    call = relationship("Call", back_populates="transcript_segments")

    def to_dict(self) -> Dict[str, Any]:
        """Convert TranscriptSegment to dictionary format."""
        result = {
            "speaker": self.speaker,
            "start": float(self.start_time) if self.start_time else 0.0,
            "end": float(self.end_time) if self.end_time else 0.0,
            "text": self.text,
        }
        if self.confidence is not None:
            result["confidence"] = float(self.confidence)
        return result


class AnalysisSummary(Base):
    """AI-generated analysis summaries table."""
    __tablename__ = "analysis_summaries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    call_id = Column(String(255), ForeignKey("calls.call_id", ondelete="CASCADE"), nullable=False, index=True)
    summary_text = Column(Text, nullable=False)
    summary_type = Column(String(50), default="openai")  # 'openai', 'fallback'
    
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    call = relationship("Call", back_populates="analysis_summaries")


# Create indexes for performance
Index("idx_calls_start_timestamp", Call.start_timestamp.desc())
Index("idx_calls_analysis_status", Call.analysis_status)
Index("idx_emotion_segments_call_time", EmotionSegment.call_id, EmotionSegment.time_start)
Index("idx_transcript_segments_call_time", TranscriptSegment.call_id, TranscriptSegment.start_time)

