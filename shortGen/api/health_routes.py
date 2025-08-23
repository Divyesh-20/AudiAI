# health_route.py
from flask import Blueprint, request, jsonify
import os
import shutil
import time
import config
from jobs.job_manager import jobs

health_bp = Blueprint("health", __name__)


@health_bp.route('/cleanup', methods=['POST'])
def cleanup_old_jobs():
    """Clean up old jobs to free up disk space"""
    try:
        hours = int(request.json.get('hours', 24))
        cutoff_time = time.time() - (hours * 3600)

        deleted_jobs = []
        for job_id, job in list(jobs.items()):
            if job.get('created_at', 0) < cutoff_time:
                if 'file_path' in job and os.path.exists(job['file_path']):
                    os.remove(job['file_path'])
                job_folder = os.path.join(config.RESULTS_FOLDER, job_id)
                if os.path.exists(job_folder):
                    shutil.rmtree(job_folder)
                del jobs[job_id]
                deleted_jobs.append(job_id)

        return jsonify({
            'message': f'Cleaned up {len(deleted_jobs)} old jobs',
            'deleted_jobs': deleted_jobs
        }), 200
    except Exception as e:
        return jsonify({'error': f'Cleanup failed: {str(e)}'}), 500


@health_bp.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        'status': 'ok',
        'active_jobs': len(jobs),
        'version': '1.0.0'
    }), 200
