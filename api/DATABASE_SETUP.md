# Database Setup Guide

This guide explains how to set up and use the PostgreSQL database for the Emotion Analysis API.

## Prerequisites

- PostgreSQL installed and running
- Python dependencies installed (`pip install -r requirements.txt`)

## Initial Setup

### 1. Create Database

Connect to PostgreSQL and create a database:

```sql
CREATE DATABASE emotion_analysis;
```

Or using command line:
```bash
createdb emotion_analysis
```

### 2. Configure Environment

Add `DATABASE_URL` to your `api/.env` file:

```env
DATABASE_URL=postgresql://username:password@localhost:5432/emotion_analysis
```

Replace:
- `username` with your PostgreSQL username
- `password` with your PostgreSQL password
- `localhost:5432` with your PostgreSQL host and port (if different)
- `emotion_analysis` with your database name

### 3. Initialize Database Schema

Run the initialization script to create all tables:

```bash
cd api
python db_init.py
```

This will create the following tables:
- `calls` - Main call metadata
- `emotion_segments` - Emotion analysis segments (prosody/burst)
- `emotion_predictions` - Individual emotion scores
- `transcript_segments` - Transcript segments
- `analysis_summaries` - AI-generated summaries

### 4. Migrate Existing Data (Optional)

If you have existing JSON data files, migrate them to the database:

```bash
cd api
python migrate_json_to_db.py
```

This script will:
- Read `retell_results/retell_calls.json`
- Read all individual call JSON files
- Import all data into the database
- Skip calls that already exist
- Provide progress logging

## Database Schema

### Calls Table
Stores main call metadata including:
- Call identifiers (call_id, agent_id, etc.)
- Timestamps and duration
- Analysis status and constraints
- Overall emotion classification
- Transcript availability

### Emotion Segments Table
Stores emotion analysis segments:
- Prosody segments (speech-based emotions)
- Burst segments (vocal burst emotions)
- Time ranges, speakers, categories

### Emotion Predictions Table
Stores individual emotion scores:
- Linked to emotion segments
- Emotion name, score, percentage, category
- Ranked by confidence

### Transcript Segments Table
Stores original transcript:
- Speaker identification
- Time ranges
- Text content
- Confidence scores

### Analysis Summaries Table
Stores AI-generated summaries:
- Summary text
- Summary type (openai/fallback)

## Usage

After setup, the API will automatically use the database for all operations. No code changes needed - the migration is transparent.

## Troubleshooting

### Connection Errors

If you get connection errors:
1. Verify PostgreSQL is running: `pg_isready`
2. Check DATABASE_URL format is correct
3. Verify database exists: `psql -l`
4. Check user permissions

### Migration Issues

If migration fails:
1. Check that database schema is initialized (`python db_init.py`)
2. Verify JSON files are readable
3. Check database connection
4. Review error messages in console

### Performance

For large datasets:
- Ensure indexes are created (done automatically)
- Consider connection pooling (already configured)
- Monitor database size and performance

## Backup

To backup the database:
```bash
pg_dump emotion_analysis > backup.sql
```

To restore:
```bash
psql emotion_analysis < backup.sql
```

