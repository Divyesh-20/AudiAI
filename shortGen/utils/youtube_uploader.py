from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2 import service_account
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
import datetime
import pickle
import os
import logging
import pandas as pd
from google.oauth2.credentials import Credentials
import config.config as config

# Configure logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Define YouTube API scopes


def authenticate_youtube(client_id, client_secret, redirect_uri):
    """
    Authenticate using OAuth direct credentials and return YouTube API client.
    """
    try:
        # Define token file
        token_pickle = 'youtube_token.pickle'
        creds = None
        
        # Check if token already exists
        if os.path.exists(token_pickle):
            with open(token_pickle, 'rb') as token:
                creds = pickle.load(token)
        
        # Refresh token if expired or get new token
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                # Create flow using client config
                client_config = {
                    "installed": {
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "redirect_uris": [redirect_uri],
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token"
                    }
                }

                flow = InstalledAppFlow.from_client_config(
                    client_config, config.YOUTUBE_SCOPES
                )
                flow.redirect_uri = redirect_uri
                creds = flow.run_local_server(port=3005)  # Make sure this matches

            # Save new token for future use
            with open(token_pickle, 'wb') as token:
                pickle.dump(creds, token)

        # Build the YouTube API client
        youtube = build('youtube', 'v3', credentials=creds)
        logger.info("YouTube API authenticated successfully")
        return youtube

    except Exception as e:
        logger.error(f"YouTube authentication failed: {str(e)}")
        raise

def upload_video(youtube, video_path, title, description, category_id='22', tags=None):
    """
    Upload video to YouTube.
    
    Parameters:
    - youtube: Authenticated YouTube API client
    - video_path: Path to the video file to upload
    - title: Title of the YouTube video
    - description: Description of the YouTube video
    - category_id: YouTube category ID (default: '22' for People & Blogs)
    - privacy_status: Privacy status of the video (public, private, unlisted)
    - tags: List of tags for the video
    
    Returns:
    - video_id: YouTube video ID
    - upload_status: Status of the upload
    """
    
    privacy_status = 'unlisted'
    try:
        # Check if video file exists
        if not os.path.exists(video_path):
            logger.error(f"Video file not found: {video_path}")
            raise FileNotFoundError(f"Video file not found: {video_path}")
        
        # Set default tags if not provided
        if tags is None:
            tags = ['AI', 'Highlights', 'Video Processing']

        # Create request body
        request_body = {
            'snippet': {
                'title': title,
                'description': description,
                'tags': tags,
                'categoryId': category_id
            },
            'status': {
                'privacyStatus': privacy_status,
                'selfDeclaredMadeForKids': False
            }
        }

        # Create a media file for upload
        media_file = MediaFileUpload(
            video_path, 
            chunksize=1024*1024,  # Use 1MB chunks
            resumable=True, 
            mimetype='video/mp4'
        )

        logger.info(f"Starting YouTube upload for {os.path.basename(video_path)}")
        
        # Upload video to YouTube
        request = youtube.videos().insert(
            part='snippet,status',
            body=request_body,
            media_body=media_file
        )
        
        # Execute request with progress reporting
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                logger.info(f"Uploaded {int(status.progress() * 100)}%")
        
        # Extract video ID and upload status
        video_id = response.get('id')
        upload_status = response.get('status', {}).get('uploadStatus')
        
        logger.info(f"Upload complete for video ID: {video_id}, Status: {upload_status}")
        
        # Return video ID and status
        return video_id, upload_status
        
    except Exception as e:
        logger.error(f"YouTube upload failed: {str(e)}")
        raise


def get_authenticated_service():
    """
    Create an authenticated YouTube API service.
    Returns YouTube API client with proper authentication.
    """
    creds = None
    token_file = 'token.json'
    
    # Check if token file exists
    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, config.YOUTUBE_SCOPES)
    
    # If credentials don't exist or are invalid, get new ones
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'client_secret.json', config.YOUTUBE_SCOPES)
            creds = flow.run_local_server(port=0)
        
        # Save the credentials for future use
        with open(token_file, 'w') as token:
            token.write(creds.to_json())
    
    # Build the YouTube API client
    youtube = build('youtube', 'v3', credentials=creds)
    youtube_analytics = build('youtubeAnalytics', 'v2', credentials=creds)
    
    return youtube, youtube_analytics

def get_authenticated_channel_id(youtube):
    """
    Get the authenticated user's YouTube channelId.
    """
    try:
        # Request the authenticated user's channel details
        request = youtube.channels().list(
            part='snippet,contentDetails',
            mine=True  # This ensures we're fetching the authenticated user's channel
        )
        
        # Execute the request
        response = request.execute()
        
        # Extract channelId from the response
        if 'items' in response and len(response['items']) > 0:
            channel_id = response['items'][0]['id']
            return channel_id
        else:
            raise Exception("No channel found for the authenticated user.")
    
    except Exception as e:
        logger.error(f"Failed to fetch channel ID: {str(e)}")
        raise

def get_all_video_ids(youtube):
    """
    Fetch all video IDs from the authenticated channel.
    
    Parameters:
    - youtube: Authenticated YouTube API client
    
    Returns:
    - video_ids: List of video IDs for the channel
    """
    try:
        video_ids = []
        
        channel_id = get_authenticated_channel_id(youtube)
        
        # Fetch the list of videos from the channel
        request = youtube.channels().list(
            part='contentDetails',
            id=channel_id
        )
        response = request.execute()
        
        # Extract playlist ID of uploaded videos
        playlist_id = response['items'][0]['contentDetails']['relatedPlaylists']['uploads']
        
        # Fetch the video IDs from the playlist
        next_page_token = None
        while True:
            request = youtube.playlistItems().list(
                part='snippet',
                playlistId=playlist_id,
                maxResults=50,
                pageToken=next_page_token
            )
            response = request.execute()
            
            # Collect video IDs
            for item in response['items']:
                video_ids.append({
                    'id': item['snippet']['resourceId']['videoId'],
                    'title': item['snippet']['title'],
                    'published_at': item['snippet']['publishedAt']
                })
            
            # Check if there are more pages
            next_page_token = response.get('nextPageToken')
            if not next_page_token:
                break
        
        # Log the video IDs
        logger.info(f"Fetched {len(video_ids)} video IDs from channel {channel_id}")
        
        return video_ids
    
    except Exception as e:
        logger.error(f"Failed to fetch video IDs: {str(e)}")
        raise

def get_video_analytics(youtube_analytics, channel_id, video_id, start_date, end_date):
    """
    Fetch analytics data for a specific video.
    
    Parameters:
    - youtube_analytics: Authenticated YouTube Analytics API client
    - channel_id: YouTube channel ID
    - video_id: YouTube video ID
    - start_date: Start date for analytics (format: 'YYYY-MM-DD')
    - end_date: End date for analytics (format: 'YYYY-MM-DD')
    
    Returns:
    - analytics_data: Analytics data for the video
    """
    try:
        # Request analytics data for the video
        request = youtube_analytics.reports().query(
            ids=f'channel=={channel_id}',
            startDate=start_date,
            endDate=end_date,
            metrics='views,estimatedMinutesWatched,averageViewDuration,likes,comments,subscribersGained',
            dimensions='day',
            filters=f'video=={video_id}'
        )
        
        response = request.execute()
        
        # Log the analytics data
        logger.info(f"Retrieved analytics for Video ID {video_id}")
        
        # Return the analytics data
        return response

    except Exception as e:
        logger.error(f"Failed to fetch video analytics: {str(e)}")
        return {"error": str(e)}

def get_channel_analytics(youtube_analytics, channel_id, start_date, end_date):
    """
    Fetch overall channel analytics.
    
    Parameters:
    - youtube_analytics: Authenticated YouTube Analytics API client
    - channel_id: YouTube channel ID
    - start_date: Start date for analytics (format: 'YYYY-MM-DD')
    - end_date: End date for analytics (format: 'YYYY-MM-DD')
    
    Returns:
    - channel_analytics: Analytics data for the channel
    """
    try:
        # Request analytics data for the channel
        request = youtube_analytics.reports().query(
            ids=f'channel=={channel_id}',
            startDate=start_date,
            endDate=end_date,
            metrics='views,estimatedMinutesWatched,averageViewDuration,likes,dislikes,comments,subscribersGained,subscribersLost',
            dimensions='day'
        )
        
        response = request.execute()
        
        # Log the analytics data
        logger.info(f"Retrieved channel analytics for {channel_id}")
        
        # Return the analytics data
        return response

    except Exception as e:
        logger.error(f"Failed to fetch channel analytics: {str(e)}")
        return {"error": str(e)}

def convert_analytics_to_dataframe(analytics_data):
    """
    Convert YouTube Analytics API response to a pandas DataFrame.
    """
    if not analytics_data or 'rows' not in analytics_data or not analytics_data['rows']:
        return pd.DataFrame()
    
    # Create DataFrame from rows
    df = pd.DataFrame(analytics_data['rows'], columns=analytics_data['columnHeaders'])
    
    # Fix column names
    df.columns = [header['name'] for header in analytics_data['columnHeaders']]
    
    return df

def analyze_video_performance(df):
    """
    Analyze video performance and return insights.
    """
    if df.empty:
        return "No data available for analysis."
    
    insights = []
    
    # Total views
    total_views = df['views'].sum()
    insights.append(f"Total views: {total_views}")
    
    # Average views per day
    avg_views = df['views'].mean()
    insights.append(f"Average views per day: {avg_views:.2f}")
    
    # Most viewed day
    if 'day' in df.columns:
        most_viewed_day = df.loc[df['views'].idxmax()]
        insights.append(f"Most viewed day: {most_viewed_day['day']} with {most_viewed_day['views']} views")
    
    # Engagement rate (likes + comments / views)
    if 'likes' in df.columns and 'comments' in df.columns:
        engagement = (df['likes'].sum() + df['comments'].sum()) / total_views * 100
        insights.append(f"Engagement rate: {engagement:.2f}%")
    
    # Subscribers gained
    if 'subscribersGained' in df.columns:
        subscribers_gained = df['subscribersGained'].sum()
        insights.append(f"Subscribers gained: {subscribers_gained}")
    
    return "\n".join(insights)

def interactive_analytics():
    """
    Interactive function to explore your YouTube analytics.
    """
    # Authenticate and build the service
    youtube, youtube_analytics = get_authenticated_service()
    
    # Get the authenticated channel ID
    channel_id = get_authenticated_channel_id(youtube)
    print(f"Authenticated as channel ID: {channel_id}")
    
    # Get default date range (last 30 days)
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - datetime.timedelta(days=30)).strftime('%Y-%m-%d')
    
    while True:
        print("\n--- YouTube Analytics Explorer ---")
        print("1. View Channel Overview")
        print("2. Analyze Specific Video")
        print("3. Compare Videos")
        print("4. Change Date Range")
        print("5. Exit")
        
        choice = input("\nEnter your choice (1-5): ")
        
        if choice == '1':
            # Get channel analytics
            print(f"\nFetching channel analytics from {start_date} to {end_date}...")
            analytics = get_channel_analytics(youtube_analytics, channel_id, start_date, end_date)
            
            # Convert to DataFrame and display
            df = convert_analytics_to_dataframe(analytics)
            if not df.empty:
                print("\nChannel Performance Summary:")
                print(f"Total Views: {df['views'].sum()}")
                print(f"Watch Time (minutes): {df['estimatedMinutesWatched'].sum()}")
                print(f"Likes: {df['likes'].sum() if 'likes' in df.columns else 'N/A'}")
                print(f"Comments: {df['comments'].sum() if 'comments' in df.columns else 'N/A'}")
                print(f"Subscribers Gained: {df['subscribersGained'].sum() if 'subscribersGained' in df.columns else 'N/A'}")
                
                save_option = input("\nWould you like to save this data to CSV? (y/n): ")
                if save_option.lower() == 'y':
                    filename = f"channel_analytics_{start_date}_to_{end_date}.csv"
                    df.to_csv(filename, index=False)
                    print(f"Data saved to {filename}")
            else:
                print("No data available for this time period.")
        
        elif choice == '2':
            # Get all videos
            videos = get_all_video_ids(youtube)
            
            if not videos:
                print("No videos found in this channel.")
                continue
            
            # Display video list
            print("\nYour Videos:")
            for i, video in enumerate(videos):
                print(f"{i+1}. {video['title']}")
            
            # Select a video
            video_choice = input("\nEnter video number to analyze (or 0 to go back): ")
            if video_choice == '0':
                continue
            
            try:
                video_index = int(video_choice) - 1
                if 0 <= video_index < len(videos):
                    selected_video = videos[video_index]
                    print(f"\nAnalyzing: {selected_video['title']}")
                    
                    # Get video analytics
                    analytics = get_video_analytics(
                        youtube_analytics, 
                        channel_id, 
                        selected_video['id'], 
                        start_date, 
                        end_date
                    )
                    
                    # Convert to DataFrame and analyze
                    df = convert_analytics_to_dataframe(analytics)
                    if not df.empty:
                        print("\nVideo Performance Insights:")
                        print(analyze_video_performance(df))
                        
                        save_option = input("\nWould you like to save this data to CSV? (y/n): ")
                        if save_option.lower() == 'y':
                            filename = f"video_analytics_{selected_video['id']}_{start_date}_to_{end_date}.csv"
                            df.to_csv(filename, index=False)
                            print(f"Data saved to {filename}")
                    else:
                        print("No data available for this video in the selected time period.")
                else:
                    print("Invalid selection.")
            except ValueError:
                print("Please enter a valid number.")
        
        elif choice == '3':
            # Get all videos
            videos = get_all_video_ids(youtube)
            
            if not videos:
                print("No videos found in this channel.")
                continue
            
            # Display video list
            print("\nYour Videos:")
            for i, video in enumerate(videos):
                print(f"{i+1}. {video['title']}")
            
            # Select videos to compare
            compare_choices = input("\nEnter video numbers to compare (comma-separated, max 5): ")
            try:
                choices = [int(c.strip()) - 1 for c in compare_choices.split(',')]
                if any(choice < 0 or choice >= len(videos) for choice in choices):
                    print("One or more invalid selections.")
                    continue
                
                if len(choices) > 5:
                    print("Please select a maximum of 5 videos to compare.")
                    continue
                
                # Collect data for each video
                comparison_data = {}
                for video_index in choices:
                    selected_video = videos[video_index]
                    analytics = get_video_analytics(
                        youtube_analytics, 
                        channel_id, 
                        selected_video['id'], 
                        start_date, 
                        end_date
                    )
                    
                    df = convert_analytics_to_dataframe(analytics)
                    if not df.empty:
                        comparison_data[selected_video['title']] = {
                            'views': df['views'].sum(),
                            'watch_time': df['estimatedMinutesWatched'].sum() if 'estimatedMinutesWatched' in df.columns else 0,
                            'likes': df['likes'].sum() if 'likes' in df.columns else 0,
                            'comments': df['comments'].sum() if 'comments' in df.columns else 0,
                            'subscribers_gained': df['subscribersGained'].sum() if 'subscribersGained' in df.columns else 0
                        }
                
                # Display comparison
                if comparison_data:
                    print("\nVideo Comparison:")
                    comparison_df = pd.DataFrame(comparison_data).T
                    print(comparison_df)
                    
                    save_option = input("\nWould you like to save this comparison to CSV? (y/n): ")
                    if save_option.lower() == 'y':
                        filename = f"video_comparison_{start_date}_to_{end_date}.csv"
                        comparison_df.to_csv(filename)
                        print(f"Comparison saved to {filename}")
                else:
                    print("No data available for comparison in the selected time period.")
            
            except ValueError:
                print("Please enter valid numbers separated by commas.")
        
        elif choice == '4':
            # Change date range
            print("\nCurrent date range: {} to {}".format(start_date, end_date))
            print("Enter new date range (format: YYYY-MM-DD):")
            
            new_start = input("Start date: ")
            new_end = input("End date: ")
            
            # Validate dates
            try:
                datetime.strptime(new_start, '%Y-%m-%d')
                datetime.strptime(new_end, '%Y-%m-%d')
                start_date = new_start
                end_date = new_end
                print(f"Date range updated: {start_date} to {end_date}")
            except ValueError:
                print("Invalid date format. Please use YYYY-MM-DD.")
        
        elif choice == '5':
            print("Exiting YouTube Analytics Explorer. Goodbye!")
            break
        
        else:
            print("Invalid choice. Please enter a number between 1 and 5.")
