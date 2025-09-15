import os
import traceback
import asyncio
import shutil
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from moviepy.config import change_settings

# ------------------ Dynamic ImageMagick Detection ------------------
def detect_imagemagick():
    # Check system PATH first
    path = shutil.which("magick")
    if path and os.path.isfile(path):
        change_settings({"IMAGEMAGICK_BINARY": path})
        print(f"✅ ImageMagick detected in PATH: {path}")
        return path

    # Check common installation directories (Windows)
    common_paths = [
        r"C:\Program Files\ImageMagick-7.1.2-Q16-HDRI\magick.exe",
        r"C:\Program Files\ImageMagick-7.1.1-Q16-HDRI\magick.exe",
        r"C:\Program Files\ImageMagick-7.0.10-Q16\magick.exe",
    ]
    for p in common_paths:
        if os.path.isfile(p):
            change_settings({"IMAGEMAGICK_BINARY": p})
            print(f"✅ ImageMagick detected at {p}")
            return p

    raise EnvironmentError(
        "❌ ImageMagick not found! Please install it and add it to PATH."
    )

# Detect at startup
detect_imagemagick()

# ------------------ Utility imports ------------------
from utility.script.script_generator import generate_script
from utility.audio.audio_generator import generate_audio
from utility.captions.timed_captions_generator import generate_timed_captions
from utility.video.background_video_generator import generate_video_url, generate_image_url
from utility.render.render_engine import get_output_media
from utility.video.video_search_query_generator import getVideoSearchQueriesTimed, merge_empty_intervals

# ------------------ Flask setup ------------------
app = Flask(__name__, static_folder="static")
CORS(app)

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200

@app.route("/generate-video", methods=["POST"])
def generate_video_api():
    try:
        data = request.get_json(force=True)
        topic = data.get("topic")
        duration = int(data.get("duration", 60))

        if not topic:
            return jsonify({"error": "Missing 'topic' in request body"}), 400

        SAMPLE_FILE_NAME = "audio_tts.wav"
        VIDEO_SERVER = "pexel"

        # Step 1 - Generate script
        script = generate_script(topic, duration)

        # Step 2 - Generate audio
        asyncio.run(generate_audio(script, SAMPLE_FILE_NAME))

        # Step 3 - Generate captions
        timed_captions = generate_timed_captions(SAMPLE_FILE_NAME)

        # Step 4 - Generate search queries
        search_terms = getVideoSearchQueriesTimed(script, timed_captions)

        # Step 5 - Generate background visuals
        background_video_urls = generate_image_url(search_terms, VIDEO_SERVER) if search_terms else []

        # Merge empty intervals
        background_video_urls = merge_empty_intervals(background_video_urls or [], duration)

        # Step 6 - Final video rendering
        if background_video_urls:
            video_filename = get_output_media(SAMPLE_FILE_NAME, timed_captions, background_video_urls, VIDEO_SERVER)

            # Ensure it's stored in static/
            video_path = os.path.join("static", "rendered_video.mp4")
            # Remove existing file to prevent FileExistsError
            if os.path.exists(video_path):
                os.remove(video_path)

            if not os.path.exists(video_filename):
                raise FileNotFoundError(f"{video_filename} not found")

            os.rename(video_filename, video_path)

            return jsonify({
                "topic": topic,
                "duration": duration,
                "script": script,
                "video_url": "/videos/rendered_video.mp4"
            }), 200
        else:
            return jsonify({"error": "No video background found"}), 500

    except Exception:
        tb = traceback.format_exc()
        app.logger.error("Exception in /generate-video:\n%s", tb)
        return jsonify({"error": "Internal server error"}), 500

@app.route("/videos/<filename>", methods=["GET"])
def serve_video(filename):
    return send_from_directory("static", filename)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    os.makedirs("static", exist_ok=True)
    app.run(host="0.0.0.0", port=port, debug=True)
