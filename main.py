from fastapi import FastAPI, HTTPException
import ffmpeg
from fastapi.responses import JSONResponse
import tempfile
import whisper
import requests
from pathlib import Path
from pydantic import BaseModel
import aiohttp
import asyncio
from io import BytesIO
from supabase import create_client, Client

app = FastAPI()

# Initialize Whisper model
model = whisper.load_model("base")  # You can choose from "base", "small", "medium", "large"

# Pydantic model for the request
class VideoRequest(BaseModel):
    video_url: str

# Helper function to download the video from the provided URL
def download_video(video_url: str, temp_dir: Path) -> Path:
    try:
        # Fetch video data from the provided URL
        response = requests.get(video_url)
        response.raise_for_status()  # Ensure we got a successful response

        # Save the video data to a temporary file
        video_filename = video_url.split("/")[-1]
        video_path = temp_dir / video_filename

        with open(video_path, "wb") as f:
            f.write(response.content)
        
        return video_path
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=400, detail=f"Error downloading video: {e}")

# Function to extract audio from the video using FFmpeg
def extract_audio(video_path: Path, temp_dir: Path) -> Path:
    try:
        audio_filename = video_path.stem + ".mp3"  # Convert video filename to .mp3
        audio_file_path = temp_dir / audio_filename

        # Run FFmpeg to extract audio from the video
        ffmpeg.input(str(video_path)).output(str(audio_file_path)).run(overwrite_output=True)

        return audio_file_path
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error extracting audio: {e}")

# Function to transcribe audio using Whisper
def transcribe_audio(audio_file_path: Path) -> str:
    try:
        # Use Whisper to transcribe the audio file
        result = model.transcribe(str(audio_file_path))
        return result['text']  # Return the transcription text
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error with transcription: {e}")

@app.post("/transcribe/")
async def transcribe_video(request: VideoRequest):
    # Create a temporary directory to store the video and audio
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # Step 1: Download the video from the URL
        video_path = download_video(request.video_url, temp_path)

        # Step 2: Extract audio from the video using FFmpeg
        audio_path = extract_audio(video_path, temp_path)

        # Step 3: Transcribe the audio using Whisper
        transcription = transcribe_audio(audio_path)

        # Return the result
        return {
            "message": "Transcription completed successfully",
            "audio_url": str(audio_path),
            "transcription": transcription,
        }

SUPABASE_URL = "https://yvaoyubwynyvqfelhzcd.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inl2YW95dWJ3eW55dnFmZWxoemNkIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDQwNDEyMzIsImV4cCI6MjA1OTYxNzIzMn0.V4-TQm-R5HUyLUBIu4uBKzYXAUpHvE7YALkGhGeQx_M"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Input schema
class VideoRequest(BaseModel):
    videoUrl: str

# Route
@app.post("/compress")
async def compress_video_endpoint(req: VideoRequest):
    if not req.videoUrl:
        raise HTTPException(status_code=400, detail="No video URL provided")

    try:
        # Step 1: Fetch video
        async with aiohttp.ClientSession() as session:
            async with session.get(req.videoUrl) as response:
                if response.status != 200:
                    raise HTTPException(status_code=400, detail="Video fetch failed")
                video_bytes = await response.read()

        # Step 2: Compress using ffmpeg
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

        # Step 3: Upload to Supabase
        filename = f"compressed/{int(asyncio.get_event_loop().time())}_compressed.mp4"
        res = supabase.storage.from_("videos").upload(filename, out, {"content-type": "video/mp4"})

        if res.get("error"):
            raise HTTPException(status_code=500, detail=f"Upload failed: {res['error']['message']}")

        # Step 4: Get public URL
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