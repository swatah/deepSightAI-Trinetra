import streamlit as st
import time
import tempfile
import os
import requests
from minio import Minio
from minio.error import S3Error

# checks if sd is installed
try:
    from scenedetect import VideoManager, SceneManager
    from scenedetect.detectors import ContentDetector
    SCENEDETECT_AVAILABLE = True
except ImportError:
    SCENEDETECT_AVAILABLE = False

# --- CONFIGURATION FOR SHARED ARCHITECTURE ---
# IMPORTANT: Replace with the actual IP address of your Server Laptop
SERVER_IP = "<YOUR_SERVER_LAPTOP_IP>" 
# ---

MINIO_URL = f"{SERVER_IP}:9000"
API_URL = f"http://{SERVER_IP}:8080"
QUERY_API_URL = f"http://{SERVER_IP}:8081"
STATIC_SERVER_URL = f"http://{SERVER_IP}:8082"

MINIO_ACCESS_KEY = "minioadmin"
MINIO_SECRET_KEY = "minioadmin"
VIDEO_BUCKET = "videos"


st.set_page_config(
    page_title="Video Search Engine",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for Swatah theme
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@400;600;700&display=swap');
    .stApp {
        background: #f7fafd url('https://www.swatah.ai/assets/images/bg-hex.svg') repeat top left;
        font-family: 'Montserrat', sans-serif;
    }
    .main-content {
        background: #fff;
        border-radius: 22px;
        box-shadow: 0 6px 32px rgba(26,60,75,0.08);
        padding: 2.5rem 2.5rem 2.5rem 2.5rem;
        margin: 0 auto 2.5rem auto;
        max-width: 950px;
    }
    .swatah-logo {
        display: flex;
        justify-content: center;
        align-items: center;
        margin: 32px 0 18px 0;
    }
    .swatah-logo img {
        height: 80px;
    }
    .stButton>button {
        background: #1976D2;
        color: white;
        font-weight: 600;
        border-radius: 8px;
        box-shadow: 0 2px 8px rgba(25,118,210,0.10);
        transition: background 0.2s;
        font-family: 'Montserrat', sans-serif;
    }
    .stButton>button:hover {
        background: #1251a3;
    }
    .stTextInput>div>div>input, .stFileUploader>div>div>input {
        background: #f7fafd;
        border-radius: 6px;
        border: 1px solid #bdbdbd;
        padding: 0.5rem;
        font-family: 'Montserrat', sans-serif;
    }
    .sidebar .sidebar-content {
        background: #e9f0f7 !important;
        border-radius: 22px;
        box-shadow: 0 6px 32px rgba(26,60,75,0.10);
        padding: 1.5rem 1rem 1rem 1rem;
        margin: 1rem 0.5rem;
    }
    .frame-card {
        background: #f7fafd;
        border-radius: 12px;
        box-shadow: 0 2px 12px rgba(25,118,210,0.08);
        margin-bottom: 18px;
        padding: 0.5rem 0.5rem 0.7rem 0.5rem;
        transition: box-shadow 0.2s, transform 0.2s;
        min-height: 180px;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
    }
    .frame-card:hover {
        box-shadow: 0 6px 24px rgba(25,118,210,0.18);
        transform: translateY(-4px) scale(1.03);
    }
    .frame-label {
        color: #1a3c4b;
        font-weight: 600;
        font-size: 1rem;
        margin-top: 0.5rem;
        text-align: center;
        font-family: 'Montserrat', sans-serif;
    }
    </style>
""", unsafe_allow_html=True)

# Centered logo at the top
st.markdown("""
    <div class='swatah-logo'>
        <img src='https://www.swatah.ai/assets/images/logo.svg' alt='Swatah Logo'/>
    </div>
""", unsafe_allow_html=True)

# Main content card
st.markdown("<div class='main-content'>", unsafe_allow_html=True)

# Sidebar CSS and taking input (restore minimal helpful text, keep theme)
st.sidebar.markdown("""
    <style>
    .sidebar .sidebar-content {
        background: #e9f0f7 !important;
        border-radius: 22px;
        box-shadow: 0 6px 32px rgba(26,60,75,0.10);
        padding: 1.5rem 1rem 1rem 1rem;
        margin: 1rem 0.5rem;
    }
    </style>
    <div style='margin-bottom:18px;margin-top:8px;'>
        <span style='font-size:1.15rem;font-weight:700;color:#1a3c4b;font-family:Montserrat,sans-serif;'>Search Options</span>
    </div>
""", unsafe_allow_html=True)
query_type = st.sidebar.radio("Query Type", ["Text", "Image"], label_visibility="visible")

query_text = ""
if query_type == "Text":
    query_text = st.sidebar.text_input("Enter your search text", label_visibility="visible", placeholder="Type your query...")
elif query_type == "Image":
    st.sidebar.file_uploader("Upload an image", type=["png", "jpg", "jpeg"], label_visibility="visible")

st.sidebar.markdown("""
    <div style='margin:18px 0 10px 0;'>
        <span style='font-size:1.15rem;font-weight:700;color:#1a3c4b;font-family:Montserrat,sans-serif;'>Video Input</span>
    </div>
""", unsafe_allow_html=True)
video_file = st.sidebar.file_uploader("Upload a video (MP4)", type=["mp4"], label_visibility="visible")
rtsp_url = st.sidebar.text_input("Or enter RTSP URL", label_visibility="visible", placeholder="rtsp://...")

if st.sidebar.button("Run Search", use_container_width=True):
    if video_file:
        try:
            with st.spinner("Uploading video..."):
                minio_client = Minio(MINIO_URL, access_key=MINIO_ACCESS_KEY, secret_key=MINIO_SECRET_KEY, secure=False)
                if not minio_client.bucket_exists(VIDEO_BUCKET):
                    minio_client.make_bucket(VIDEO_BUCKET)
                video_file.seek(0)
                minio_client.put_object(VIDEO_BUCKET, video_file.name, video_file, length=video_file.getbuffer().nbytes, content_type='video/mp4')
            st.success(f"Video '{video_file.name}' uploaded.")
            with st.spinner("Notifying server to process video..."):
                response = requests.post(f"{API_URL}/process_video", json={"video_uri": video_file.name})
                if response.status_code == 200:
                    st.success("Server has started processing the video!")
                else:
                    st.error(f"Error notifying server: {response.text}")
        except Exception as e:
            st.error(f"An error occurred during upload: {e}")

    if query_text:
        with st.spinner("Searching for relevant frames..."):
            try:
                response = requests.post(f"{QUERY_API_URL}/search/text", json={"query": query_text})
                if response.status_code == 200:
                    st.session_state.search_results = response.json()
                    st.success("Search complete!")
                else:
                    st.error(f"Error during search: {response.text}")
            except Exception as e:
                st.error(f"Failed to connect to Query API: {e}")


# Display video if uploaded or RTSP URL provided (preview is for video files only)
if video_file is not None:
    st.video(video_file)
elif rtsp_url:
    st.markdown("<div style='text-align:center; color:white; font-size:18px; margin-bottom:16px;'>RTSP streaming preview is not supported in Streamlit. Please use a video file for preview.</div>", unsafe_allow_html=True)

#text
st.markdown("""
    <h2 style='color: #1a3c4b; font-weight: 700; margin-bottom: 0.2rem; letter-spacing:0.5px; font-family:Montserrat,sans-serif;'>Relevant Video Frames</h2>
    <hr style='border: none; border-top: 2px solid #1976D2; margin: 0 0 10px 0;'>
    <p style='font-size: 1.08rem; color: #3a5a6a; margin-bottom: 18px; font-family:Montserrat,sans-serif;'>Browse the most relevant frames retrieved from your video using advanced text or image-based search.</p>
""", unsafe_allow_html=True)

#frame cards
if 'search_results' in st.session_state and st.session_state.search_results:
    cols = st.columns(3)
    for i, result in enumerate(st.session_state.search_results):
        with cols[i % 3]:
            relative_frame_path = os.path.relpath(result['frame_path'], '/app/extracted_frames')
            frame_url = f"{STATIC_SERVER_URL}/{relative_frame_path}"
            st.image(frame_url, caption=f"Video: {result['video_id']}", use_column_width=True)
else:
    cols = st.columns(3)
    for i in range(6):
        with cols[i % 3]:
            st.markdown(f"""
                <div class='frame-card'>
                    <div style='width:100%;height:144px;background:linear-gradient(135deg,#e0e0e0 60%,#bdbdbd 100%);border-radius:8px;'></div>
                    <div class='frame-label'>Frame {i+1} (00:{i*5:02d})</div>
                </div>
            """, unsafe_allow_html=True)

#Scene Detection (only for uploaded video)
if video_file is not None:
    if not SCENEDETECT_AVAILABLE:
        st.error("PySceneDetect is not installed. Please install it with 'pip install scenedetect' to enable scene detection.")
    else:
        try:
            st.markdown("<hr style='margin:32px 0 16px 0;'>", unsafe_allow_html=True)
            st.subheader("Scene Detection Results")
            # Save uploaded video to a temp file
            with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as tmp_vid:
                tmp_vid.write(video_file.read())
                tmp_vid_path = tmp_vid.name
            # Run scene detection
            video_manager = VideoManager([tmp_vid_path])
            scene_manager = SceneManager()
            scene_manager.add_detector(ContentDetector(threshold=30.0))
            video_manager.set_downscale_factor()
            video_manager.start()
            scene_manager.detect_scenes(frame_source=video_manager)
            scene_list = scene_manager.get_scene_list()
            video_manager.release()
            # Clean up tmp file
            os.remove(tmp_vid_path)
            if scene_list:
                st.success(f"Detected {len(scene_list)} scenes.")
                for idx, (start, end) in enumerate(scene_list):
                    st.write(f"Scene {idx+1}: {start.get_timecode()} - {end.get_timecode()}")
            else:
                st.info("No distinct scenes detected. Try a different video or adjust detection settings.")
        except Exception as e:
            st.error(f"Scene detection failed: {e}")

st.markdown("</div>", unsafe_allow_html=True)
