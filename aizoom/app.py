import cv2
import numpy as np
import uuid
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import FileResponse
import shutil
import os

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# Allow all origins for testing; you can restrict this for production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins (or specify domains)
    allow_credentials=True,
    allow_methods=["*"],  # Allow all HTTP methods
    allow_headers=["*"],  # Allow all headers
)


UPLOAD_DIR = "uploads"
OUTPUT_DIR = "processed"

# Ensure directories exist
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

@app.post("/process-video/")
async def process_video(file: UploadFile = File(...)):
    # Save uploaded file
    input_video_path = f"{UPLOAD_DIR}/{uuid.uuid4()}.mp4"
    with open(input_video_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Process the video
    output_video_path = f"{OUTPUT_DIR}/{uuid.uuid4()}_output.mp4"
    process_zoom_tracking(input_video_path, output_video_path)

    # Return the processed video
    return FileResponse(output_video_path, media_type="video/mp4")

def process_zoom_tracking(input_video_path, output_video_path):
    cap = cv2.VideoCapture(input_video_path)

    if not cap.isOpened():
        print("Error: Could not open video.")
        return

    ret, frame = cap.read()
    if not ret:
        print("Error: Couldn't read the video frame.")
        return

    frame_h, frame_w = frame.shape[:2]
    zoomed_h = frame_h
    zoomed_w = int(frame_h * (16 / 9))  # Convert to 16:9 ratio

    # --- Full-screen ROI selection ---
    cv2.namedWindow("Select Object to Track", cv2.WINDOW_NORMAL)
    cv2.setWindowProperty("Select Object to Track", cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

    bbox = cv2.selectROI("Select Object to Track", frame, fromCenter=False, showCrosshair=True)
    cv2.destroyAllWindows()

    tracker = cv2.legacy.TrackerCSRT_create()
    tracker.init(frame, bbox)

    zoom_factor = 1.4
    smooth_x, smooth_y = bbox[0], bbox[1]

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(output_video_path, fourcc, 30.0, (zoomed_w, zoomed_h))

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        success, bbox = tracker.update(frame)

        if success:
            x, y, w, h = [int(v) for v in bbox]
            smooth_x = int(0.8 * smooth_x + 0.2 * x)
            smooth_y = int(0.8 * smooth_y + 0.2 * y)
            obj_center_x = smooth_x + w // 2
            obj_center_y = smooth_y + h // 2
        else:
            obj_center_x = frame_w // 2
            obj_center_y = frame_h // 2
            smooth_x = int(0.9 * smooth_x + 0.1 * obj_center_x)
            smooth_y = int(0.9 * smooth_y + 0.1 * obj_center_y)

        zoom_w_scaled = int(zoomed_w / zoom_factor)
        zoom_h_scaled = int(zoomed_h / zoom_factor)

        x1 = max(0, obj_center_x - zoom_w_scaled // 2)
        y1 = max(0, obj_center_y - zoom_h_scaled // 2)
        x2 = min(frame_w, obj_center_x + zoom_w_scaled // 2)
        y2 = min(frame_h, obj_center_y + zoom_h_scaled // 2)

        cropped = frame[y1:y2, x1:x2]
        zoomed_frame = cv2.resize(cropped, (zoomed_w, zoomed_h), interpolation=cv2.INTER_LINEAR)

        out.write(zoomed_frame)

    cap.release()
    out.release()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
