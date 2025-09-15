import os
import requests
from utility.utils import log_response, LOG_TYPE_PEXEL

PEXELS_API_KEY = os.environ.get('PEXELS_KEY')
if not PEXELS_API_KEY:
    raise EnvironmentError("PEXELS_KEY not found in environment variables!")

# --- Video Functions ---
def search_videos(query_string, orientation_landscape=True):
    url = "https://api.pexels.com/videos/search"
    headers = {
        "Authorization": PEXELS_API_KEY,
        "User-Agent": "Mozilla/5.0"
    }
    params = {
        "query": query_string,
        "orientation": "landscape" if orientation_landscape else "portrait",
        "per_page": 15
    }

    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        log_response(LOG_TYPE_PEXEL, query_string, data)
        return data.get('videos', [])
    except Exception as e:
        print(f"Error fetching videos for '{query_string}': {e}")
        return []

def get_best_video(query_string, orientation_landscape=True, used_vids=[]):
    videos = search_videos(query_string, orientation_landscape)
    for video in sorted(videos, key=lambda x: abs(15 - int(x.get('duration', 0)))):
        for vf in video.get('video_files', []):
            if orientation_landscape and vf.get('width') == 1920 and vf.get('height') == 1080:
                link_base = vf['link'].split('.hd')[0]
                if link_base not in used_vids:
                    return vf['link']
            elif not orientation_landscape and vf.get('width') == 1080 and vf.get('height') == 1920:
                link_base = vf['link'].split('.hd')[0]
                if link_base not in used_vids:
                    return vf['link']
    print(f"NO VIDEO found for query: {query_string}")
    return "https://www.pexels.com/video-placeholder.mp4"  # fallback video

def generate_video_url(timed_video_searches, video_server="pexel"):
    timed_video_urls = []
    if video_server == "pexel":
        used_links = []
        for (t1, t2), search_terms in timed_video_searches:
            url = None
            for query in search_terms:
                url = get_best_video(query, orientation_landscape=True, used_vids=used_links)
                if url:
                    used_links.append(url.split('.hd')[0])
                    break
            timed_video_urls.append([[t1, t2], url])
    return timed_video_urls

# --- Image Functions ---
def search_images(query_string, orientation_landscape=True):
    url = "https://api.pexels.com/v1/search"
    headers = {"Authorization": PEXELS_API_KEY, "User-Agent": "Mozilla/5.0"}
    params = {"query": query_string, "orientation": "landscape" if orientation_landscape else "portrait", "per_page": 15}

    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        log_response(LOG_TYPE_PEXEL, query_string, data)
        return data.get("photos", [])
    except Exception as e:
        print(f"Error fetching images for '{query_string}': {e}")
        return []

def get_best_image(query_string, orientation_landscape=True, used_imgs=[]):
    photos = search_images(query_string, orientation_landscape)
    for photo in photos:
        url = photo.get("src", {}).get("original")
        if url and url.split("?")[0] not in used_imgs:
            return url
    print(f"NO IMAGE found for query: {query_string}")
    return "https://www.pexels.com/image-placeholder.jpg"  # fallback image

def generate_image_url(timed_image_searches, image_server="pexel"):
    timed_image_urls = []
    if image_server == "pexel":
        used_links = []
        for (t1, t2), search_terms in timed_image_searches:
            url = None
            for query in search_terms:
                url = get_best_image(query, orientation_landscape=True, used_imgs=used_links)
                if url:
                    used_links.append(url.split("?")[0])
                    break
            timed_image_urls.append([[t1, t2], url])
    return timed_image_urls
