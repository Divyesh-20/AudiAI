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

# Import new modules
from utils.scene_intensity import analyze_scene_intensity
from utils.sentiment_analysis import analyze_sentiment
from utils.youtube_uploader import authenticate_youtube, upload_video

from utils.youtube_uploader import get_authenticated_service, get_channel_analytics, get_video_analytics, convert_analytics_to_dataframe, analyze_video_performance, get_all_video_ids , get_authenticated_channel_id



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

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def merge_scores(sentiment_scores, intensity_scores, weight_sentiment=0.4, weight_intensity=0.6, num_highlights=3):
    """
    Merge sentiment analysis scores and visual intensity scores to find the best highlights.
    
    Parameters:
    - sentiment_scores: List of dicts with {'start_time', 'end_time', 'score'} from sentiment analysis
    - intensity_scores: List of dicts with {'start_time', 'end_time', 'score'} from scene intensity
    - weight_sentiment: Weight to give sentiment scores in the final scoring (0-1)
    - weight_intensity: Weight to give intensity scores in the final scoring (0-1)
    - num_highlights: Number of highlights to return
    
    Returns:
    - List of dicts with {'start_time', 'end_time', 'score'} representing the top highlights
    """
    # Normalize scores within each category
    def normalize_scores(scores_list):
        if not scores_list:
            return []
            
        max_score = max(item['score'] for item in scores_list)
        min_score = min(item['score'] for item in scores_list)
        score_range = max_score - min_score if max_score > min_score else 1
        
        normalized = []
        for item in scores_list:
            normalized_item = item.copy()
            normalized_item['score'] = (item['score'] - min_score) / score_range
            normalized.append(normalized_item)
        return normalized
    
    norm_sentiment = normalize_scores(sentiment_scores)
    norm_intensity = normalize_scores(intensity_scores)
    
    # Create segments dictionary to track all potential highlight segments
    all_segments = {}
    
    # Add sentiment segments
    for item in norm_sentiment:
        key = (item['start_time'], item['end_time'])
        if key not in all_segments:
            all_segments[key] = {
                'start_time': item['start_time'],
                'end_time': item['end_time'],
                'sentiment_score': item['score'],
                'intensity_score': 0
            }
        else:
            all_segments[key]['sentiment_score'] = item['score']
    
    # Add intensity segments
    for item in norm_intensity:
        key = (item['start_time'], item['end_time'])
        if key not in all_segments:
            all_segments[key] = {
                'start_time': item['start_time'],
                'end_time': item['end_time'],
                'sentiment_score': 0,
                'intensity_score': item['score']
            }
        else:
            all_segments[key]['intensity_score'] = item['score']
    
    # Calculate combined scores
    merged_results = []
    for segment in all_segments.values():
        combined_score = (segment['sentiment_score'] * weight_sentiment + 
                         segment['intensity_score'] * weight_intensity)
        
        merged_results.append({
            'start_time': segment['start_time'],
            'end_time': segment['end_time'],
            'score': combined_score
        })
    
    # Sort by score and return top highlights
    merged_results.sort(key=lambda x: x['score'], reverse=True)
    return merged_results[:num_highlights]

# Video processing function
def process_video(video_path, job_id, num_highlights=3, highlight_duration=(20, 30)):
    """Process a video file to generate highlights"""
    # Path to your service account JSON key
    API_KEY_FILE = 'Recusion\shortGen\cred.json'

# Authenticate YouTube API once when the app starts
    try:
        youtube_client = authenticate_youtube(API_KEY_FILE)
    except Exception as e:
        logger.error(f"Failed to authenticate with YouTube API: {str(e)}")
        youtube_client = None

# another
    try:
        job_folder = os.path.join(RESULTS_FOLDER, job_id)
        os.makedirs(job_folder, exist_ok=True)
        
        # Update job status
        jobs[job_id]['status'] = 'processing'
        jobs[job_id]['progress'] = 10
        
        # Load the video file
        clip = mp.VideoFileClip(video_path)
        total_duration = clip.duration
        logger.info(f"Video loaded. Duration: {total_duration:.2f} seconds")
        
        # Update progress
        jobs[job_id]['progress'] = 20
        
        # Check if audio exists
        has_audio = clip.audio is not None
        
        # Extract audio and transcribe if available
        transcript = None
        sentiment_scores = []
        if has_audio:
            audio_path = os.path.join('temp', f"{job_id}_audio.wav")
            clip.audio.write_audiofile(audio_path)
            
            # Update progress
            jobs[job_id]['progress'] = 40
            
            # Load whisper model and transcribe
            try:
                model = whisper.load_model("base")
                result = model.transcribe(audio_path)
                transcript = result['text']
                logger.info("Transcription completed")
                
                # Save transcript
                with open(os.path.join(job_folder, 'transcript.txt'), 'w') as f:
                    f.write(transcript)

                if transcript:
                    sentiment_scores = analyze_sentiment(transcript)
                    logger.info(f"Sentiment analysis completed. Top sentiment lines: {len(sentiment_scores)}")
            except Exception as e:
                logger.error(f"Transcription error: {str(e)}")

            # Remove temporary audio file
            if os.path.exists(audio_path):
                os.remove(audio_path)
        
        # Update progress
        jobs[job_id]['progress'] = 60
        
        # Run scene detection
        scenes_file = os.path.abspath(os.path.join('temp', f"{job_id}_scenes.csv"))
        scene_output_dir = os.path.abspath(os.path.join('temp', f"{job_id}_scenes"))
        os.makedirs(scene_output_dir, exist_ok=True)
        
        scenes_df = None
        intensity_scores = []
        
        try:
            subprocess.run([
                'scenedetect',
                '--input', video_path,
                '--output', scene_output_dir,
                'detect-content',
                '--threshold', '30',
                'list-scenes',
                '--output', scenes_file
            ], check=True)
            
            logger.info("Scene detection completed")
            
            # Read the CSV file with scene information
            if os.path.exists(scenes_file):
                try:
                    scenes_df = pd.read_csv(scenes_file)
                    logger.info(f"Detected {len(scenes_df)} scenes")
                    
                    # Extract scene times
                    scene_times = []
                    if scenes_df is not None and len(scenes_df) > 0:
                        scene_times = [
                            (scenes_df.iloc[i]['Start Time (seconds)'], scenes_df.iloc[i]['End Time (seconds)'])
                            for i in range(len(scenes_df))
                        ]
                    
                    # Analyze intensity and update results
                    intensity_scores = analyze_scene_intensity(video_path, scene_times)
                    logger.info(f"Scene intensity analysis completed. Top scenes: {len(intensity_scores)}")
                except Exception as e:
                    logger.error(f"Error reading scene CSV: {str(e)}")
        except Exception as e:
            logger.error(f"Scene detection error: {str(e)}")
        
        # Update progress
        jobs[job_id]['progress'] = 70
        
        # Determine highlights
        highlights = []
        
        # Merge sentiment and intensity scores to get top highlights
        if transcript and intensity_scores:
            merged_scores = merge_scores(sentiment_scores, intensity_scores, num_highlights=num_highlights)
            logger.info(f"Merged scores generated. Top {len(merged_scores)} highlights selected.")
            
            # Use merged_scores for highlight generation
            for score in merged_scores:
                start_time = score['start_time']
                end_time = score['end_time']
                
                # Ensure minimum and maximum duration
                current_duration = end_time - start_time
                if current_duration < highlight_duration[0]:
                    # Extend if too short
                    extension = (highlight_duration[0] - current_duration) / 2
                    start_time = max(0, start_time - extension)
                    end_time = min(total_duration, end_time + extension)
                elif current_duration > highlight_duration[1]:
                    # Trim if too long
                    middle = (start_time + end_time) / 2
                    half_duration = highlight_duration[1] / 2
                    start_time = middle - half_duration
                    end_time = middle + half_duration
                
                # Ensure we don't exceed clip duration
                if end_time > total_duration:
                    end_time = total_duration
                
                # Add highlight based on merged scores
                if start_time < end_time:
                    highlights.append((start_time, end_time))
        
        # If we don't have enough highlights from merged scores, fall back to scene detection
        if len(highlights) < num_highlights and scenes_df is not None and len(scenes_df) > 0:
            scenes_needed = num_highlights - len(highlights)
            for i in range(min(scenes_needed, len(scenes_df))):
                start_time = scenes_df.iloc[i]['Start Time (seconds)']
                max_duration = min(highlight_duration[1], scenes_df.iloc[i]['Length (seconds)'])
                end_time = start_time + max_duration
                
                # Ensure we don't exceed clip duration
                if end_time > total_duration:
                    end_time = total_duration
                
                # Ensure minimum duration if possible
                if end_time - start_time < highlight_duration[0] and i < len(scenes_df) - 1:
                    end_time = start_time + highlight_duration[0]
                    if end_time > total_duration:
                        end_time = total_duration
                
                highlights.append((start_time, end_time))
        
        # If we still need more highlights or no scenes were detected
        remaining = num_highlights - len(highlights)
        if remaining > 0:
            segment_length = min(highlight_duration[1], total_duration / (remaining + 1))
            for i in range(remaining):
                start_time = (i + 1) * segment_length
                end_time = start_time + segment_length
                if end_time > total_duration:
                    end_time = total_duration
                if start_time < end_time:  # Make sure we have a valid segment
                    highlights.append((start_time, end_time))
        
        # Update progress
        jobs[job_id]['progress'] = 80
        
        # Create highlight videos
        highlight_paths = []
        metadata = []
        
        for i, (start, end) in enumerate(highlights):
            highlight_name = f"highlight_{i+1}.mp4"
            output_path = os.path.join(job_folder, highlight_name)
            
            logger.info(f"Creating highlight {i+1} from {start:.2f}s to {end:.2f}s")
            
            # Create subclip and write to file
            subclip = clip.subclip(start, end)
            subclip.write_videofile(
                output_path, 
                codec='libx264', 
                audio_codec='aac' if has_audio else None,
                threads=2,
                verbose=False,
                logger=None
            )
            
            highlight_paths.append(output_path)
            metadata.append({
                "filename": highlight_name,
                "start_time": start,
                "end_time": end,
                "duration": end - start
            })
            
            # Increment progress as each highlight is completed
            jobs[job_id]['progress'] = 80 + ((i + 1) * 20 // len(highlights))
        
        # Save metadata
        with open(os.path.join(job_folder, 'metadata.json'), 'w') as f:
            import json
            json.dump({
                "original_video": os.path.basename(video_path),
                "total_duration": total_duration,
                "has_audio": has_audio,
                "highlights": metadata,
                "transcript": transcript
            }, f, indent=2)
        
        # Clean up
        clip.close()

        # Upload highlights to YouTube
        if youtube_client:
            for i, highlight_path in enumerate(highlight_paths):
                try:
                    title = f"Highlight {i+1} - {os.path.basename(video_path)}"
                    description = f"Automatically generated highlight from {os.path.basename(video_path)}"
            
            # Default to unlisted for safety
                    privacy_status = 'unlisted'
            
            # Custom tags for better searchability
                    tags = ['AI Generated', 'Video Highlights', 'Automatic Editing']
            
                    video_id, status = upload_video(
                    youtube_client, 
                    highlight_path, 
                    title, 
                    description,
                    
                 )
            
                    logger.info(f"Uploaded highlight {i+1} to YouTube. Video ID: {video_id}, Status: {status}")
            
            # Add YouTube info to metadata
                    metadata[i]["youtube_id"] = video_id
                    metadata[i]["youtube_url"] = f"https://www.youtube.com/watch?v={video_id}"
            
                except Exception as e:
                    logger.error(f"Error uploading highlight {i+1} to YouTube: {str(e)}")
                    metadata[i]["youtube_error"] = str(e)

        
        # Update job status to complete
        jobs[job_id]['status'] = 'complete'
        jobs[job_id]['progress'] = 100
        jobs[job_id]['result_files'] = highlight_paths
        jobs[job_id]['metadata'] = metadata
        
        logger.info(f"Job {job_id} completed successfully")
        return True
        
    except Exception as e:
        logger.error(f"Error processing video: {str(e)}")
        # Update job status to failed
        jobs[job_id]['status'] = 'failed'
        jobs[job_id]['error'] = str(e)
        return False

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
            args=(file_path, job_id, num_highlights, (min_duration, max_duration))
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