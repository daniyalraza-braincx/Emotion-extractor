# Hume Emotion Analysis API

FastAPI server for analyzing audio files using Hume's Expression Measurement API.

## Setup

1. **Install dependencies:**
   ```bash
   pip install -r api/requirements.txt
   ```

2. **Create a `.env` file** (in either the root directory or the `api` directory):
   ```env
   HUME_API_KEY=your_hume_api_key_here
   OPENAI_API_KEY=your_openai_api_key_here
   ```
   
   Note: 
   - `HUME_API_KEY` is required for emotion analysis
   - `OPENAI_API_KEY` is optional but recommended for AI-powered summaries of the emotion predictions
   - The script will automatically look for `.env` in the current directory and parent directories

## Running the Server

**Option 1: Run from the api directory (Recommended)**

```bash
cd api
python api_server.py
```

**Option 2: Using uvicorn from root directory**

```bash
cd api
uvicorn api_server:app --host 0.0.0.0 --port 8000 --reload
```

The server will start at `http://localhost:8000`

## Testing the API

### 1. Interactive API Documentation

Visit `http://localhost:8000/docs` in your browser for Swagger UI documentation where you can test the API directly.

### 2. Using curl

```bash
curl -X POST "http://localhost:8000/analyze" \
  -H "accept: application/json" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@path/to/your/audio.wav"
```

### 3. Using Python requests

```python
import requests

url = "http://localhost:8000/analyze"
files = {"file": open("path/to/your/audio.wav", "rb")}
response = requests.post(url, files=files)
print(response.json())
```

### 4. Health Check

```bash
curl http://localhost:8000/
```

## API Endpoints

- `POST /analyze` - Analyze an audio file for emotions
  - Accepts: audio file (WAV, MP3, M4A, FLAC)
  - Returns: JSON with top 3 emotions per time segment

- `GET /` - Health check endpoint

## Response Format

```json
{
  "success": true,
  "filename": "audio.wav",
  "results": {
    "filename": "audio.wav",
    "prosody": [
      {
        "time_start": 0.0,
        "time_end": 5.0,
        "text": "Hello world",
        "top_emotions": [
          {
            "name": "Calmness",
            "score": 0.8234,
            "percentage": 82.3
          },
          ...
        ]
      }
    ],
    "burst": [...],
    "summary": "Overall, the audio demonstrates a calm and confident emotional tone. The dominant emotions detected are Calmness (82.3%) and Confidence (15.2%), suggesting the speaker is composed and self-assured throughout the recording. The emotional patterns remain relatively stable with minimal fluctuations, indicating a consistent mood..."
  }
}
```

**Note:** The `summary` field is only included if `OPENAI_API_KEY` is set in your `.env` file. The summary provides an AI-generated analysis of the emotional patterns detected in the audio.

