























from flask import Blueprint, request, jsonify
import os
import logging
import datetime
from jobs.job_manager import jobs
from utils.youtube_uploader import (
    authenticate_youtube, upload_video, get_authenticated_service,
    get_channel_analytics, get_video_analytics, convert_analytics_to_dataframe,
    analyze_video_performance, get_all_video_ids, get_authenticated_channel_id
)
import config.config as config

youtube_bp = Blueprint("youtube_bp", __name__)
logger = logging.getLogger(__name__)

# ---- Routes ----
@youtube_bp.route("/uploadToYoutube", methods=["POST"])
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
        highlight_path = os.path.join(config.RESULTS_FOLDER, job_id, highlight_metadata['filename'])
        
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

@youtube_bp.route("/authenticate", methods=["GET"])
def authenticate():
    try:
        youtube, youtube_analytics = get_authenticated_service()
        return jsonify({"message": "Authenticated successfully!"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@youtube_bp.route("/channel/analytics", methods=["GET"])
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

@youtube_bp.route("/video/analytics", methods=["GET"])
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

@youtube_bp.route("/videos", methods=["GET"])
def get_all_videos():
    try:
        # Get authenticated YouTube service
        youtube, youtube_analytics = get_authenticated_service()

        # Get all videos from the channel
        videos = get_all_video_ids(youtube)
        return jsonify(videos), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
