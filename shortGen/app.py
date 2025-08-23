# app.py - Flask API for Video Highlight Generation
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import os
import uuid
import threading
import time
import shutil
import logging
import datetime
from werkzeug.utils import secure_filename

# Import video processing functions
import moviepy.editor as mp
import whisper
import subprocess
import pandas as pd

from utils.youtube_uploader import authenticate_youtube, upload_video

from utils.youtube_uploader import get_authenticated_service, get_channel_analytics, get_video_analytics, convert_analytics_to_dataframe, analyze_video_performance, get_all_video_ids , get_authenticated_channel_id

from utils.process_video_and_score import allowed_file , process_video

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Configuration
UPLOAD_FOLDER = 'uploads'
RESULTS_FOLDER = 'results'
ALLOWED_EXTENSIONS = {'mp4', 'mov', 'avi', 'mkv', 'webm'}
MAX_CONTENT_LENGTH = 500 * 1024 * 1024  # 500MB max upload size

# Create necessary directories
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(RESULTS_FOLDER, exist_ok=True)
os.makedirs('temp', exist_ok=True)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

# Dictionary to store job status
jobs = {}


# API Routes

@app.route('/api/uploadToYoutube', methods=['POST'])
def upload_to_youtube():
    """
    Endpoint to upload a video to YouTube.
    
    Expected JSON payload:
    {
        "video_id": "job_id_of_processed_video",
        "highlight_index": 0,  # (optional) Index of the highlight to upload, default is 0
        "title": "Custom title",  # (optional)
        "description": "Custom description",  # (optional)
        "privacy": "unlisted"  # (optional) "public", "private", or "unlisted"
    }
    """
    try:
        # Validate request data
        if not request.is_json:
            return jsonify({'error': 'Request must be JSON'}), 400
            
        data = request.json
        
        # Check required fields
        if 'video_id' not in data:
            return jsonify({'error': 'Missing required field: video_id'}), 400
            
        job_id = data['video_id']

        # Print for debugging
        print("Received job_id:", job_id)
        print("Received job_id:", jobs)

        
        # Check if job exists
        if not isinstance(job_id, str):
            return jsonify({'error': 'job_id must be a string'}), 400

        if job_id not in jobs:
            return jsonify({'error': 'Job not found'}), 404
            
        job = jobs[job_id]
        
        # Check if job is complete
        if job.get('status') != 'complete':
            return jsonify({'error': 'Video processing is not complete yet'}), 400
        
        # Get highlight index (default to 0)
        highlight_index = int(data.get('highlight_index', 0))
        
        # Validate highlight index
        if not job.get('metadata') or highlight_index >= len(job.get('metadata', [])):
            return jsonify({'error': 'Invalid highlight index'}), 400
            
        highlight_metadata = job['metadata'][highlight_index]
        highlight_path = os.path.join(RESULTS_FOLDER, job_id, highlight_metadata['filename'])
        
        # Check if file exists
        if not os.path.exists(highlight_path):
            return jsonify({'error': 'Highlight file not found'}), 404
        
        # Path to YouTube credentials
        API_KEY_FILE = 'cred.json'
        CLIENT_ID = "258906969713-gc1i9mcn8at6uhaj58lf9s49maf6p5r1.apps.googleusercontent.com"
        CLIENT_SECRET = "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"
        REDIRECT_URI = "http://localhost:5000/oauth2callback"
        # Authenticate YouTube API
        try:
            youtube_client = authenticate_youtube(CLIENT_ID, CLIENT_SECRET, REDIRECT_URI)
        except Exception as e:
            logger.error(f"Failed to authenticate with YouTube API: {str(e)}")
            return jsonify({'error': f'YouTube authentication failed: {str(e)}'}), 500
            
        # Prepare upload parameters
        title = data.get('title', f"Highlight {highlight_index + 1} - {job['filename']}")
        description = data.get('description', f"Automatically generated highlight from {job['filename']}")
        privacy_status = data.get('privacy', 'unlisted')
        
        # Valid privacy status values
        valid_privacy = ['public', 'private', 'unlisted']
        if privacy_status not in valid_privacy:
            privacy_status = 'unlisted'  # Default to unlisted if invalid
            
        # Custom tags
        tags = data.get('tags', ['AI Generated', 'Video Highlights', 'Automatic Editing'])
        
        # Upload to YouTube
        try:
            video_id, status = upload_video(
                youtube_client,
                highlight_path,
                title,
                description,

                
            )
            
            # Save YouTube info in metadata
            highlight_metadata["youtube_id"] = video_id
            highlight_metadata["youtube_url"] = f"https://www.youtube.com/watch?v={video_id}"
            
            return jsonify({
                'success': True,
                'video_id': video_id,
                'status': status,
                'youtube_url': f"https://www.youtube.com/watch?v={video_id}"
            }), 200
            
        except Exception as e:
            logger.error(f"YouTube upload failed: {str(e)}")
            return jsonify({'error': f'YouTube upload failed: {str(e)}'}), 500
            
    except Exception as e:
        logger.error(f"Error in upload_to_youtube endpoint: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/upload', methods=['POST'])
def upload_videoo():
    # Check if the post request has the file part
    if 'video' not in request.files:
        return jsonify({'error': 'No video file provided'}), 400
    
    file = request.files['video']
    
    # If the user does not select a file
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    if file and allowed_file(file.filename):
        # Create a new job ID
        job_id = str(uuid.uuid4())
        
        # Secure the filename and save the file
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{job_id}_{filename}")
        file.save(file_path)
        
        # Get processing parameters
        num_highlights = int(request.form.get('num_highlights', 3))
        min_duration = int(request.form.get('min_duration', 20))
        max_duration = int(request.form.get('max_duration', 30))
        
        # Initialize job status
        jobs[job_id] = {
            'id': job_id,
            'filename': filename,
            'file_path': file_path,
            'status': 'queued',
            'progress': 0,
            'created_at': time.time(),
            'num_highlights': num_highlights,
            'highlight_duration': (min_duration, max_duration)
        }
        
        # Start processing in a background thread
        threading.Thread(
            target=process_video,
            args=(file_path, jobs, job_id, num_highlights, (min_duration, max_duration))
        ).start()
        
        return jsonify({
            'job_id': job_id,
            'status': 'queued',
            'message': 'Video upload successful. Processing started.'
        }), 202
    
    return jsonify({'error': 'File type not allowed'}), 400

@app.route('/api/status/<job_id>', methods=['GET'])
def get_job_status(job_id):
    if job_id not in jobs:
        return jsonify({'error': 'Job not found'}), 404
    
    job = jobs[job_id].copy()
    
    # Don't return internal file paths
    if 'file_path' in job:
        del job['file_path']
    if 'result_files' in job:
        del job['result_files']
    
    return jsonify(job), 200

@app.route('/api/results/<job_id>', methods=['GET'])
def get_job_results(job_id):
    if job_id not in jobs:
        return jsonify({'error': 'Job not found'}), 404
    
    job = jobs[job_id]
    
    if job['status'] != 'complete':
        return jsonify({
            'status': job['status'],
            'progress': job['progress'],
            'message': 'Job is not complete yet'
        }), 202
    
    # Return links to download the highlights
    highlight_urls = []
    for i, metadata in enumerate(job.get('metadata', [])):
        highlight_urls.append({
            'id': i + 1,
            'filename': metadata['filename'],
            'url': f"/api/download/{job_id}/{metadata['filename']}",
            'duration': metadata['duration'],
            'start_time': metadata['start_time'],
            'end_time': metadata['end_time']
        })
    
    return jsonify({
        'job_id': job_id,
        'status': 'complete',
        'highlights': highlight_urls,
        # Include download link for transcript if available
        'transcript_url': f"/api/transcript/{job_id}" if os.path.exists(os.path.join(RESULTS_FOLDER, job_id, 'transcript.txt')) else None
    }), 200

@app.route('/api/download/<job_id>/<filename>', methods=['GET'])
def download_file(job_id, filename):
    # Validate job exists
    if job_id not in jobs:
        return jsonify({'error': 'Job not found'}), 404
    
    # Validate job is complete
    job = jobs[job_id]
    if job['status'] != 'complete':
        return jsonify({'error': 'Job is not complete yet'}), 400
    
    # Validate filename
    file_path = os.path.join(RESULTS_FOLDER, job_id, filename)
    print("filepath",file_path)
    if not os.path.exists(file_path):
        return jsonify({'error': 'File not found'}), 404
    
    return send_file(file_path, as_attachment=True)

@app.route('/api/transcript/<job_id>', methods=['GET'])
def get_transcript(job_id):
    # Validate job exists
    if job_id not in jobs:
        return jsonify({'error': 'Job not found'}), 404
    
    # Validate transcript exists
    transcript_path = os.path.join(RESULTS_FOLDER, job_id, 'transcript.txt')
    if not os.path.exists(transcript_path):
        return jsonify({'error': 'Transcript not available'}), 404
    
    return send_file(transcript_path, as_attachment=True)

@app.route('/api/cleanup', methods=['POST'])
def cleanup_old_jobs():
    """Clean up old jobs to free up disk space"""
    try:
        # Get cutoff time (default: 24 hours)
        hours = int(request.json.get('hours', 24))
        cutoff_time = time.time() - (hours * 3600)
        
        deleted_jobs = []
        for job_id, job in list(jobs.items()):
            if job.get('created_at', 0) < cutoff_time:
                # Delete job files
                if 'file_path' in job and os.path.exists(job['file_path']):
                    os.remove(job['file_path'])
                
                # Delete result folder
                job_folder = os.path.join(RESULTS_FOLDER, job_id)
                if os.path.exists(job_folder):
                    shutil.rmtree(job_folder)
                
                # Remove job from memory
                del jobs[job_id]
                deleted_jobs.append(job_id)
        
        return jsonify({
            'message': f'Cleaned up {len(deleted_jobs)} old jobs',
            'deleted_jobs': deleted_jobs
        }), 200
    except Exception as e:
        return jsonify({'error': f'Cleanup failed: {str(e)}'}), 500

# Health check endpoint
@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({
        'status': 'ok',
        'active_jobs': len(jobs),
        'version': '1.0.0'
    }), 200


# Route to get authenticated YouTube API service
@app.route('/api/authenticate', methods=['GET'])
def authenticate():
    try:
        youtube, youtube_analytics = get_authenticated_service()
        return jsonify({"message": "Authenticated successfully!"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Route to get channel analytics
@app.route('/api/channel/analytics', methods=['GET'])
def get_channel_overview():
    try:
        # Get authenticated YouTube service
        youtube, youtube_analytics = get_authenticated_service()

        # Get the authenticated channel ID
        channel_id = get_authenticated_channel_id(youtube)
        print(f"Authenticated as channel ID: {channel_id}")

        # Get the date range (default: last 30 days)
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - datetime.timedelta(days=30)).strftime('%Y-%m-%d')

        # Fetch channel analytics
        analytics = get_channel_analytics(youtube_analytics, channel_id, start_date, end_date)
        
        # Convert to DataFrame and return it
        df = convert_analytics_to_dataframe(analytics)
        if not df.empty:
            return jsonify(df.to_dict(orient='records')), 200
        else:
            return jsonify({"error": "No data available for the selected time period."}), 404

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Route to get video analytics for a specific video
@app.route('/api/video/analytics', methods=['GET'])
def get_video_performance():
    try:
        video_id = request.args.get('video_id')
        if not video_id:
            return jsonify({"error": "video_id parameter is required."}), 400

        # Get authenticated YouTube service
        youtube, youtube_analytics = get_authenticated_service()

        # Get the authenticated channel ID
        channel_id = get_authenticated_channel_id(youtube)

        # Get the date range (default: last 30 days)
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - datetime.timedelta(days=30)).strftime('%Y-%m-%d')

        # Fetch video analytics
        analytics = get_video_analytics(youtube_analytics, channel_id, video_id, start_date, end_date)

        # Convert to DataFrame and analyze
        df = convert_analytics_to_dataframe(analytics)
        if not df.empty:
            performance = analyze_video_performance(df)
            return jsonify({"performance": performance}), 200
        else:
            return jsonify({"error": "No data available for the selected video in the selected time period."}), 404

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Route to get all videos from the authenticated channel
@app.route('/api/videos', methods=['GET'])
def get_all_videos():
    try:
        # Get authenticated YouTube service
        youtube, youtube_analytics = get_authenticated_service()

        # Get all videos from the channel
        videos = get_all_video_ids(youtube)
        return jsonify(videos), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500



if __name__ == '__main__':
    # Install required packages if not already installed
    try:
        import pkg_resources
        required_packages = ['moviepy', 'scenedetect[opencv]', 'whisper', 'spacy', 'flask', 'flask-cors']
        installed = {pkg.key for pkg in pkg_resources.working_set}
        missing = [pkg for pkg in required_packages if pkg.split('[')[0] not in installed]
        
        if missing:
            logger.info(f"Installing missing packages: {missing}")
            import sys
            import subprocess
            subprocess.check_call([sys.executable, '-m', 'pip', 'install'] + missing)
            
            # Special case for whisper
            if 'whisper' in missing:
                subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'git+https://github.com/openai/whisper.git'])
    except Exception as e:
        logger.warning(f"Package check failed: {str(e)}")
    
    # Run the Flask application
    app.run(host='0.0.0.0', port=5000, debug=True)