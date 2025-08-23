from flask import Blueprint, request, jsonify, send_file
import os
import uuid
import threading
import time
from werkzeug.utils import secure_filename
import logging

from jobs.job_manager import jobs
from utils.process_video_and_score import allowed_file, process_video
import config.config as config

highlight_bp = Blueprint("highlight_bp", __name__)
logger = logging.getLogger(__name__)

# ------------------ ROUTES ------------------

@highlight_bp.route('/upload', methods=['POST'])
def upload_videoo():
    if 'video' not in request.files:
        return jsonify({'error': 'No video file provided'}), 400
    
    file = request.files['video']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    if file and allowed_file(file.filename):
        job_id = str(uuid.uuid4())
        filename = secure_filename(file.filename)
        file_path = os.path.join(config.UPLOAD_FOLDER, f"{job_id}_{filename}")
        file.save(file_path)

        num_highlights = int(request.form.get('num_highlights', 3))
        min_duration = int(request.form.get('min_duration', 20))
        max_duration = int(request.form.get('max_duration', 30))

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


@highlight_bp.route('/status/<job_id>', methods=['GET'])
def get_job_status(job_id):
    if job_id not in jobs:
        return jsonify({'error': 'Job not found'}), 404
    
    job = jobs[job_id].copy()
    job.pop('file_path', None)
    job.pop('result_files', None)
    
    return jsonify(job), 200


@highlight_bp.route('/results/<job_id>', methods=['GET'])
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
        'transcript_url': f"/api/transcript/{job_id}" if os.path.exists(os.path.join(config.RESULTS_FOLDER, job_id, 'transcript.txt')) else None
    }), 200


@highlight_bp.route('/download/<job_id>/<filename>', methods=['GET'])
def download_file(job_id, filename):
    if job_id not in jobs:
        return jsonify({'error': 'Job not found'}), 404
    
    job = jobs[job_id]
    if job['status'] != 'complete':
        return jsonify({'error': 'Job is not complete yet'}), 400
    
    file_path = os.path.join(config.RESULTS_FOLDER, job_id, filename)
    if not os.path.exists(file_path):
        return jsonify({'error': 'File not found'}), 404
    
    return send_file(file_path, as_attachment=True)


@highlight_bp.route('/transcript/<job_id>', methods=['GET'])
def get_transcript(job_id):
    if job_id not in jobs:
        return jsonify({'error': 'Job not found'}), 404
    
    transcript_path = os.path.join(config.RESULTS_FOLDER, job_id, 'transcript.txt')
    if not os.path.exists(transcript_path):
        return jsonify({'error': 'Transcript not available'}), 404
    
    return send_file(transcript_path, as_attachment=True)
