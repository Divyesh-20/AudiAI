UPLOAD_FOLDER = 'uploads'
RESULTS_FOLDER = 'results'
ALLOWED_EXTENSIONS = {'mp4', 'mov', 'avi', 'mkv', 'webm'}
MAX_CONTENT_LENGTH = 500 * 1024 * 1024  # 500MB max upload size
CLIENT_ID = "258906969713-gc1i9mcn8at6uhaj58lf9s49maf6p5r1.apps.googleusercontent.com"
CLIENT_SECRET = "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"
REDIRECT_URI = "http://localhost:5000/oauth2callback"
YOUTUBE_SCOPES = ['https://www.googleapis.com/auth/youtube.upload', 'https://www.googleapis.com/auth/yt-analytics.readonly']