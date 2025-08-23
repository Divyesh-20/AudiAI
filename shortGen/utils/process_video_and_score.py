# app.py - Flask API for Video Highlight Generation
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import os
import uuid
import threading
import time
import shutil
import logging
from werkzeug.utils import secure_filename

# Import video processing functions
import moviepy.editor as mp
import whisper
import subprocess
import pandas as pd

# Import new modules
from utils.scene_intensity import analyze_scene_intensity
from utils.sentiment_analysis import analyze_sentiment
# Configuration

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
import config.config as config

# Create necessary directories
os.makedirs(config.UPLOAD_FOLDER, exist_ok=True)
os.makedirs(config.RESULTS_FOLDER, exist_ok=True)
os.makedirs('temp', exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in config.ALLOWED_EXTENSIONS

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
def process_video(video_path, jobs, job_id, num_highlights=3, highlight_duration=(20, 30)):
    """Process a video file to generate highlights"""

# another
    try:
        job_folder = os.path.join(config.RESULTS_FOLDER, job_id)
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
