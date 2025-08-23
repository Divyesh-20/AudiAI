# app.py - Flask API for Video Highlight Generation
from flask import Flask
from flask_cors import CORS
import os
import logging
import config.config as config

# Import Blueprints
from api.health_routes import health_bp
from api.video_routes import highlight_bp
from api.youtube_routes import youtube_bp
# (uncomment and add as you split more routes into separate files)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Dictionary to store job status (shared across routes)

def create_app():
    """Create and configure the Flask app."""
    app = Flask(__name__)
    CORS(app)  # Enable CORS

    # Register Blueprints
    app.register_blueprint(health_bp, url_prefix="/api")
    app.register_blueprint(youtube_bp, url_prefix="/api")
    app.register_blueprint(highlight_bp, url_prefix="/api")

    # Create necessary directories
    os.makedirs(config.UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(config.RESULTS_FOLDER, exist_ok=True)
    os.makedirs("temp", exist_ok=True)

    app.config["UPLOAD_FOLDER"] = config.UPLOAD_FOLDER
    app.config["MAX_CONTENT_LENGTH"] = config.MAX_CONTENT_LENGTH

    return app


if __name__ == "__main__":
    # Install required packages if not already installed
    try:
        import pkg_resources
        required_packages = [
            "moviepy", "scenedetect[opencv]", "whisper",
            "spacy", "flask", "flask-cors"
        ]
        installed = {pkg.key for pkg in pkg_resources.working_set}
        missing = [pkg for pkg in required_packages if pkg.split("[")[0] not in installed]

        if missing:
            logger.info(f"Installing missing packages: {missing}")
            import sys
            import subprocess
            subprocess.check_call([sys.executable, "-m", "pip", "install"] + missing)

            # Special case for whisper
            if "whisper" in missing:
                subprocess.check_call([
                    sys.executable, "-m", "pip", "install",
                    "git+https://github.com/openai/whisper.git"
                ])
    except Exception as e:
        logger.warning(f"Package check failed: {str(e)}")

    # Run the Flask application
    app = create_app()
    app.run(host="0.0.0.0", port=5000, debug=True)
