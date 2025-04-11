from fastapi import FastAPI, HTTPException
import ffmpeg
from fastapi.responses import JSONResponse
import tempfile
import whisper
import requests
from pathlib import Path
import subprocess

from pydantic import BaseModel
import aiohttp
import asyncio
from io import BytesIO
from supabase import create_client, Client
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

app = FastAPI()

# Initialize Whisper model
model = whisper.load_model("base")

class VideoRequest(BaseModel):
    video_url: str

# -- download_video, extract_audio, transcribe_audio (same as above) --
@app.get("/ffmpeg-check")
def ffmpeg_check():
    try:
        result = subprocess.run(["ffmpeg", "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return {"output": result.stdout.decode()}
    except Exception as e:
        return {"error": str(e)}
    

    
@app.post("/transcribe/")
async def transcribe_video(request: VideoRequest):
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        video_path = download_video(request.video_url, temp_path)
        audio_path = extract_audio(video_path, temp_path)
        transcription = transcribe_audio(audio_path)
        return {
            "message": "Transcription completed successfully",
            "audio_url": str(audio_path),
            "transcription": transcription,
        }

# Load Supabase credentials from env
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

@app.post("/compress")
async def compress_video_endpoint(req: VideoRequest):
    if not req.video_url:
        raise HTTPException(status_code=400, detail="No video URL provided")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(req.video_url) as response:
                if response.status != 200:
                    raise HTTPException(status_code=400, detail="Video fetch failed")
                video_bytes = await response.read()

        input_stream = BytesIO(video_bytes)
        output_stream = BytesIO()

        process = (
            ffmpeg
            .input("pipe:0")
            .output("pipe:1", vcodec="libx264", crf=28, format="mp4")
            .run_async(pipe_stdin=True, pipe_stdout=True, pipe_stderr=True)
        )

        out, err = process.communicate(input=input_stream.read())
        if process.returncode != 0:
            print(err.decode())
            raise HTTPException(status_code=500, detail="Compression failed")

        filename = f"compressed/{int(asyncio.get_event_loop().time())}_compressed.mp4"
        res = supabase.storage.from_("videos").upload(filename, out, {"content-type": "video/mp4"})

        if res.get("error"):
            raise HTTPException(status_code=500, detail=f"Upload failed: {res['error']['message']}")

        public_url = supabase.storage.from_("videos").get_public_url(filename).get("publicURL")

        return JSONResponse(
            status_code=200,
            content={
                "message": "Video compressed successfully",
                "compressedVideoUrl": public_url
            }
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
