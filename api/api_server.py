from typing import List
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from extractor import analyze_audio_files

app = FastAPI(title="Hume Emotion Analysis API")

# Enable CORS for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify your frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/analyze")
async def analyze_audio(file: UploadFile = File(...)):
    """
    Analyze audio file for emotion detection using Hume API.
    
    Returns:
        JSON with top 3 emotions per time segment for prosody and burst models.
    """
    try:
        # Read uploaded file
        file_content = await file.read()
        filename = file.filename or "uploaded_audio"
        
        # Prepare file contents (list of tuples: (filename, bytes))
        file_contents = [(filename, file_content)]
        
        # Analyze using the reusable function from extractor.py
        results = analyze_audio_files(file_contents, include_summary=True)
        
        if not results:
            raise HTTPException(
                status_code=404, 
                detail="No emotion predictions found. The audio may not contain detectable speech."
            )
        
        # Return first result (since we only process one file)
        result = results[0]
        
        return JSONResponse(content={
            "success": True,
            "filename": filename,
            "results": result
        })
        
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


@app.get("/")
async def root():
    """Health check endpoint"""
    return {"message": "Hume Emotion Analysis API is running", "status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
