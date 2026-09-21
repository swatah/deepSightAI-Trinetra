"""
Enterprise Search UI for deepSightAI Trinetra (UI-82 to UI-93).

Features:
- UI-82: JWT authentication support with Authorization Bearer header
- UI-83: Environment-driven configuration (no hardcoded server IPs or credentials)
- UI-84: Vehicle Search tab (attribute filters, reference crop, camera/time filters)
- UI-85: Person Search tab (reference crop, camera/time filters)
- UI-87: Image Search tab end-to-end
- UI-88: Render thumbnails using presigned MinIO URLs
- UI-91: Graceful handling of loading, empty, and error states
- UI-92: Dynamic camera dropdown populated from GET /cameras
- UI-93: Direct consumption of API frame_timestamp
"""

import os
import io
import base64
import uuid
import tempfile
from typing import Optional, List, Dict, Any
from datetime import datetime

import streamlit as st
import requests
from minio import Minio

try:
    from scenedetect import VideoManager, SceneManager
    from scenedetect.detectors import ContentDetector
    SCENEDETECT_AVAILABLE = True
except ImportError:
    SCENEDETECT_AVAILABLE = False

# --- CONFIGURATION (UI-83) ---
SERVER_HOST = os.getenv("SERVER_HOST", "localhost")
API_URL = os.getenv("API_URL", f"http://{SERVER_HOST}:8080")
QUERY_API_URL = os.getenv("QUERY_API_URL", f"http://{SERVER_HOST}:8081")
ALERT_API_URL = os.getenv("ALERT_API_URL", QUERY_API_URL)
WATCHLIST_API_URL = os.getenv("WATCHLIST_API_URL", QUERY_API_URL)
MINIO_URL = os.getenv("MINIO_URL", f"{SERVER_HOST}:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
VIDEO_BUCKET = os.getenv("VIDEO_BUCKET", "videos")
FRAME_BUCKET = os.getenv("FRAME_BUCKET", "frames")
DEFAULT_TENANT_ID = os.getenv("TENANT_ID", "default")
DEFAULT_AUTH_TOKEN = os.getenv("AUTH_TOKEN", "")


def check_user_permission(permission: str) -> bool:
    """Check if the current token has the required permission or admin role (UI-89)."""
    token = st.session_state.get("auth_token", DEFAULT_AUTH_TOKEN)
    if not token:
        return True
    try:
        from jose import jwt
        claims = jwt.get_unverified_claims(token)
        roles = claims.get("roles", [])
        if not isinstance(roles, list):
            roles = [roles] if roles else []
        permissions = claims.get("permissions", [])
        if not isinstance(permissions, list):
            permissions = [permissions] if permissions else []
        all_perms = set(roles + permissions)
        return "admin" in all_perms or permission in all_perms
    except Exception:
        return True


# Page Setup
st.set_page_config(
    page_title="deepSightAI Trinetra - Video Search",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@400;600;700&display=swap');
    .stApp {
        background: #f7fafd;
        font-family: 'Montserrat', sans-serif;
    }
    .main-content {
        background: #fff;
        border-radius: 16px;
        box-shadow: 0 4px 24px rgba(26,60,75,0.08);
        padding: 2rem;
        margin: 0 auto 2rem auto;
        max-width: 1200px;
    }
    .frame-card {
        background: #fdfdfd;
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 0.75rem;
        margin-bottom: 1rem;
        box-shadow: 0 2px 8px rgba(0,0,0,0.04);
        transition: transform 0.2s, box-shadow 0.2s;
    }
    .frame-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 16px rgba(0,0,0,0.1);
    }
    .frame-badge {
        display: inline-block;
        padding: 0.2rem 0.5rem;
        font-size: 0.75rem;
        font-weight: 600;
        border-radius: 4px;
        background-color: #e2e8f0;
        color: #1e293b;
        margin-right: 0.25rem;
    }
    </style>
""", unsafe_allow_html=True)


# --- AUTH & HEADERS HELPER (UI-82) ---
def get_auth_headers() -> Dict[str, str]:
    """Retrieve HTTP headers with Bearer token and tenant context (UI-82)."""
    token = st.session_state.get("auth_token", DEFAULT_AUTH_TOKEN)
    tenant_id = st.session_state.get("tenant_id", DEFAULT_TENANT_ID)
    headers = {"X-Tenant-ID": tenant_id}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


# --- CAMERA REGISTRY HELPER (UI-92) ---
def fetch_cameras() -> List[Dict[str, Any]]:
    """Fetch camera list dynamically from SearchService (UI-92)."""
    try:
        headers = get_auth_headers()
        res = requests.get(f"{QUERY_API_URL}/cameras", headers=headers, timeout=5)
        if res.status_code == 200:
            return res.json()
    except Exception:
        pass
    return []


# --- TIMESTAMP FORMATTING (UI-93) ---
def format_timestamp(seconds: Optional[float]) -> str:
    """Format seconds directly to HH:MM:SS (UI-93)."""
    if seconds is None:
        return "N/A"
    total_sec = int(round(seconds))
    hrs = total_sec // 3600
    mins = (total_sec % 3600) // 60
    secs = total_sec % 60
    if hrs > 0:
        return f"{hrs:02d}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"


# --- SIDEBAR CONTROLS (UI-82, UI-83, UI-92) ---
with st.sidebar:
    st.title("deepSightAI Trinetra")
    st.caption("Intelligent Visual Search Platform")

    # Authentication section (UI-82)
    with st.expander("Authentication & Tenant", expanded=False):
        st.session_state.auth_token = st.text_input("JWT Token", value=st.session_state.get("auth_token", DEFAULT_AUTH_TOKEN), type="password")
        st.session_state.tenant_id = st.text_input("Tenant ID", value=st.session_state.get("tenant_id", DEFAULT_TENANT_ID))

    # Video Ingestion section
    with st.expander("Video Ingestion", expanded=False):
        ingest_type = st.radio("Source Type", ["File", "RTSP Feed"])
        ingest_camera_id = st.text_input("Camera ID", value="cam-01")
        if ingest_type == "File":
            uploaded_video = st.file_uploader("Upload MP4", type=["mp4"])
            if st.button("Ingest Video", key="btn_ingest_file") and uploaded_video:
                try:
                    unique_name = f"{uuid.uuid4()}-{uploaded_video.name}"
                    minio_c = Minio(MINIO_URL.replace("http://", "").replace("https://", ""), access_key=MINIO_ACCESS_KEY, secret_key=MINIO_SECRET_KEY, secure=False)
                    if not minio_c.bucket_exists(VIDEO_BUCKET):
                        minio_c.make_bucket(VIDEO_BUCKET)
                    uploaded_video.seek(0)
                    minio_c.put_object(VIDEO_BUCKET, unique_name, uploaded_video, length=uploaded_video.getbuffer().nbytes, content_type="video/mp4")
                    resp = requests.post(f"{API_URL}/process_video", json={"video_uri": unique_name, "camera_id": ingest_camera_id, "tenant_id": st.session_state.tenant_id}, headers=get_auth_headers(), timeout=10)
                    if resp.status_code == 200:
                        st.success("Video dispatched to extractor!")
                    else:
                        st.error(f"Ingest error: {resp.text}")
                except Exception as e:
                    st.error(f"Ingestion failed: {e}")
        else:
            rtsp_stream_url = st.text_input("RTSP URL", placeholder="rtsp://...")
            if st.button("Start Stream Ingest", key="btn_ingest_rtsp") and rtsp_stream_url:
                try:
                    resp = requests.post(f"{API_URL}/process_rtsp_stream", json={"rtsp_url": rtsp_stream_url, "camera_id": ingest_camera_id, "tenant_id": st.session_state.tenant_id}, headers=get_auth_headers(), timeout=10)
                    if resp.status_code == 200:
                        st.success("RTSP stream dispatched!")
                    else:
                        st.error(f"RTSP dispatch error: {resp.text}")
                except Exception as e:
                    st.error(f"Stream dispatch failed: {e}")

    # Camera selector populated from GET /cameras (UI-92)
    cameras = fetch_cameras()
    camera_options = ["All Cameras"] + [f"{c['id']} - {c.get('name', c['id'])}" for c in cameras]
    selected_camera_label = st.selectbox("Filter Camera", camera_options)
    selected_camera_id = None
    if selected_camera_label != "All Cameras":
        selected_camera_id = selected_camera_label.split(" - ")[0]

    # Timestamp filters
    time_start_input = st.number_input("Start Timestamp (seconds)", min_value=0.0, value=0.0, step=1.0)
    time_end_input = st.number_input("End Timestamp (seconds, 0 for any)", min_value=0.0, value=0.0, step=1.0)
    time_start = time_start_input if time_start_input > 0 else None
    time_end = time_end_input if time_end_input > 0 else None
    top_k = st.slider("Top K Results", min_value=1, max_value=100, value=12)


# --- MAIN SEARCH INTERFACE (UI-84, UI-85, UI-87) ---
st.markdown("<div class='main-content'>", unsafe_allow_html=True)
st.title("Visual Search Engine")

tab_text, tab_vehicle, tab_person, tab_image, tab_plate, tab_watchlist, tab_alerts = st.tabs([
    "🔍 Text Search",
    "🚗 Vehicle Search",
    "👤 Person Search",
    "🖼️ Image Search",
    "🔢 Plate Search",
    "📋 Watchlists",
    "🚨 Live Alerts"
])


results: List[Dict[str, Any]] = []

# --- TAB 1: TEXT SEARCH ---
with tab_text:
    st.subheader("Semantic Natural Language Search")
    text_query = st.text_input("Search Description", placeholder="e.g. red sedan, person in yellow jacket, black delivery van")
    if st.button("Search Text", key="btn_search_text", type="primary") and text_query:
        payload = {
            "query": text_query,
            "query_text": text_query,
            "top_k": top_k,
            "tenant_id": st.session_state.tenant_id,
            "camera_ids": [selected_camera_id] if selected_camera_id else None,
            "time_start": time_start,
            "time_end": time_end
        }
        with st.spinner("Searching Milvus vector collection..."):
            try:
                res = requests.post(f"{QUERY_API_URL}/search/text", json=payload, headers=get_auth_headers(), timeout=15)
                if res.status_code == 200:
                    results = res.json()
                    st.session_state.last_results = results
                elif res.status_code == 401:
                    st.error("Authentication required (401). Please supply a valid JWT token in the sidebar.")
                else:
                    st.error(f"Search failed ({res.status_code}): {res.text}")
            except Exception as e:
                st.error(f"Connection error: {e}")

# --- TAB 2: VEHICLE SEARCH (UI-84) ---
with tab_vehicle:
    st.subheader("Vehicle Detection & Attribute Search (UI-84)")
    col1, col2, col3 = st.columns(3)
    with col1:
        v_color = st.selectbox("Vehicle Color", ["Any", "Red", "Blue", "White", "Black", "Silver", "Gray", "Green", "Yellow"])
    with col2:
        v_type = st.selectbox("Vehicle Type", ["Any", "Sedan", "SUV", "Truck", "Van", "Bus", "Hatchback", "Motorcycle"])
    with col3:
        v_plate = st.text_input("License Plate (optional)", placeholder="e.g. MH12AB1234")

    v_crop = st.file_uploader("Reference Vehicle Crop (optional)", type=["jpg", "jpeg", "png"], key="v_crop_uploader")

    if st.button("Search Vehicles", key="btn_search_vehicle", type="primary"):
        ref_b64 = None
        if v_crop:
            ref_b64 = base64.b64encode(v_crop.read()).decode("utf-8")

        payload = {
            "color": v_color.lower() if v_color != "Any" else None,
            "vehicle_type": v_type.lower() if v_type != "Any" else None,
            "plate_number": v_plate if v_plate.strip() else None,
            "reference_image_base64": ref_b64,
            "camera_ids": [selected_camera_id] if selected_camera_id else None,
            "time_start": time_start,
            "time_end": time_end,
            "top_k": top_k,
            "tenant_id": st.session_state.tenant_id
        }
        with st.spinner("Searching vehicle detections..."):
            try:
                res = requests.post(f"{QUERY_API_URL}/search/vehicle", json=payload, headers=get_auth_headers(), timeout=15)
                if res.status_code == 200:
                    results = res.json()
                    st.session_state.last_results = results
                elif res.status_code == 401:
                    st.error("Authentication required (401).")
                else:
                    st.error(f"Search error ({res.status_code}): {res.text}")
            except Exception as e:
                st.error(f"Connection error: {e}")

# --- TAB 3: PERSON SEARCH (UI-85) ---
with tab_person:
    st.subheader("Person & Pedestrian Search (UI-85)")
    p_crop = st.file_uploader("Reference Person Image / Crop", type=["jpg", "jpeg", "png"], key="p_crop_uploader")

    if st.button("Search People", key="btn_search_person", type="primary"):
        ref_b64 = None
        if p_crop:
            ref_b64 = base64.b64encode(p_crop.read()).decode("utf-8")

        payload = {
            "reference_image_base64": ref_b64,
            "camera_ids": [selected_camera_id] if selected_camera_id else None,
            "time_start": time_start,
            "time_end": time_end,
            "top_k": top_k,
            "tenant_id": st.session_state.tenant_id
        }
        with st.spinner("Searching person detections..."):
            try:
                res = requests.post(f"{QUERY_API_URL}/search/person", json=payload, headers=get_auth_headers(), timeout=15)
                if res.status_code == 200:
                    results = res.json()
                    st.session_state.last_results = results
                elif res.status_code == 401:
                    st.error("Authentication required (401).")
                else:
                    st.error(f"Search error ({res.status_code}): {res.text}")
            except Exception as e:
                st.error(f"Connection error: {e}")

# --- TAB 4: IMAGE SEARCH (UI-87) ---
with tab_image:
    st.subheader("Image-Based Visual Search (UI-87)")
    img_target_type = st.radio("Target Search Type", ["Vehicles", "People"])
    img_upload = st.file_uploader("Upload Image to Search", type=["jpg", "jpeg", "png"], key="img_tab_uploader")

    if st.button("Search by Image", key="btn_search_image", type="primary") and img_upload:
        b64_content = base64.b64encode(img_upload.read()).decode("utf-8")
        endpoint = f"{QUERY_API_URL}/search/vehicle" if img_target_type == "Vehicles" else f"{QUERY_API_URL}/search/person"
        payload = {
            "reference_image_base64": b64_content,
            "camera_ids": [selected_camera_id] if selected_camera_id else None,
            "time_start": time_start,
            "time_end": time_end,
            "top_k": top_k,
            "tenant_id": st.session_state.tenant_id
        }
        with st.spinner(f"Matching {img_target_type}..."):
            try:
                res = requests.post(endpoint, json=payload, headers=get_auth_headers(), timeout=15)
                if res.status_code == 200:
                    results = res.json()
                    st.session_state.last_results = results
                elif res.status_code == 401:
                    st.error("Authentication required (401).")
                else:
                    st.error(f"Search error ({res.status_code}): {res.text}")
            except Exception as e:
                st.error(f"Connection error: {e}")

# --- TAB 5: PLATE SEARCH (UI-86) ---
with tab_plate:
    st.subheader("License Plate Recognition (LPR) Search (UI-86)")
    p_col1, p_col2 = st.columns([2, 1])
    with p_col1:
        plate_input = st.text_input(
            "License Plate Number",
            placeholder="e.g. KA01AB1234, MH12DE1432, 7XYZ123",
            key="plate_input_field"
        )
    with p_col2:
        plate_mode = st.radio(
            "Match Mode",
            ["Exact Match", "Fuzzy Search (Trigram)"],
            horizontal=True,
            key="plate_mode_radio"
        )

    plate_sim_threshold = 0.3
    if "Fuzzy" in plate_mode:
        plate_sim_threshold = st.slider(
            "Similarity Threshold",
            min_value=0.1,
            max_value=1.0,
            value=0.3,
            step=0.05,
            key="plate_sim_slider"
        )

    if st.button("Search Plates", key="btn_search_plate", type="primary") and plate_input.strip():
        payload = {
            "plate_number": plate_input.strip(),
            "exact": "Exact" in plate_mode,
            "mode": "exact" if "Exact" in plate_mode else "fuzzy",
            "similarity_threshold": plate_sim_threshold,
            "camera_ids": [selected_camera_id] if selected_camera_id else None,
            "time_start": time_start,
            "time_end": time_end,
            "top_k": top_k,
            "tenant_id": st.session_state.tenant_id
        }
        with st.spinner("Searching license plate records..."):
            try:
                res = requests.post(f"{QUERY_API_URL}/search/plate", json=payload, headers=get_auth_headers(), timeout=15)
                if res.status_code == 200:
                    results = res.json()
                    st.session_state.last_results = results
                elif res.status_code == 401:
                    st.error("Authentication required (401). Please supply a valid JWT token.")
                else:
                    st.error(f"Plate search error ({res.status_code}): {res.text}")
            except Exception as e:
                st.error(f"Connection error: {e}")

# --- TAB 6: WATCHLIST MANAGEMENT (UI-89) ---
with tab_watchlist:
    st.subheader("Watchlist Management (BOLOs)")
    can_write_watchlist = check_user_permission("watchlist:write")

    if can_write_watchlist:
        with st.expander("➕ Add New Watchlist Target", expanded=False):
            with st.form("form_add_watchlist"):
                w_col1, w_col2, w_col3 = st.columns(3)
                with w_col1:
                    w_type = st.selectbox(
                        "Target Type",
                        ["plate", "person_reid", "vehicle_reid"],
                        format_func=lambda x: {"plate": "License Plate", "person_reid": "Person Re-ID", "vehicle_reid": "Vehicle Re-ID"}.get(x, x)
                    )
                with w_col2:
                    w_label = st.text_input("Label / Description / Case ID *", placeholder="e.g. Stolen Blue Sedan, Suspect Case #402")
                with w_col3:
                    w_priority = st.selectbox("Alert Priority", ["medium", "high", "critical", "low"])

                w_plate = None
                w_ref_pk = None
                if w_type == "plate":
                    w_plate = st.text_input("Target License Plate *", placeholder="e.g. MH12AB1234")
                else:
                    w_ref_pk = st.text_input("Reference Object PK", placeholder="e.g. det_cam1_123456_0")

                submit_watchlist = st.form_submit_button("Create Watchlist Entry", type="primary")
                if submit_watchlist:
                    if not w_label:
                        st.error("Label is required.")
                    elif w_type == "plate" and not w_plate:
                        st.error("License plate is required for plate watchlist.")
                    else:
                        payload = {
                            "entry_type": w_type,
                            "label": w_label,
                            "priority": w_priority,
                            "plate_text": w_plate,
                            "reid_reference_pk": w_ref_pk,
                            "active": True
                        }
                        try:
                            res = requests.post(f"{WATCHLIST_API_URL}/watchlist", json=payload, headers=get_auth_headers(), timeout=10)
                            if res.status_code in (200, 201):
                                st.success("Watchlist entry created successfully!")
                            elif res.status_code == 403:
                                st.error("Permission denied (403): Missing 'watchlist:write' permission.")
                            else:
                                st.error(f"Failed to create entry ({res.status_code}): {res.text}")
                        except Exception as e:
                            st.error(f"Connection error: {e}")
    else:
        st.info("ℹ️ Read-only view: 'watchlist:write' permission is required to add or modify watchlist entries.")

    # List active watchlist entries
    st.markdown("### Active Watchlist Entries")
    try:
        w_list_res = requests.get(f"{WATCHLIST_API_URL}/watchlist", headers=get_auth_headers(), timeout=10)
        if w_list_res.status_code == 200:
            w_entries = w_list_res.json()
            if w_entries:
                for entry in w_entries:
                    w_badge_color = "#ef4444" if entry.get("priority") == "critical" else "#f97316" if entry.get("priority") == "high" else "#3b82f6"
                    st.markdown(
                        f"<div class='frame-card'>"
                        f"<strong>#{entry['id']} - {entry['label']}</strong> "
                        f"<span class='frame-badge' style='background:{w_badge_color};color:#fff;'>{entry.get('priority', 'medium').upper()}</span> "
                        f"<span class='frame-badge'>Type: {entry.get('entry_type')}</span> "
                        f"<span class='frame-badge'>Status: {'ACTIVE' if entry.get('active') else 'INACTIVE'}</span>"
                        f"<br/><small>Plate: {entry.get('plate_text_norm') or 'N/A'} | Ref PK: {entry.get('reid_reference_pk') or 'N/A'} | Created: {entry.get('created_at', '')[:19]}</small>"
                        f"</div>",
                        unsafe_allow_html=True
                    )
                    if can_write_watchlist:
                        col_btn1, col_btn2 = st.columns([1, 8])
                        with col_btn1:
                            if st.button("Delete", key=f"del_wl_{entry['id']}"):
                                del_res = requests.delete(f"{WATCHLIST_API_URL}/watchlist/{entry['id']}", headers=get_auth_headers(), timeout=5)
                                if del_res.status_code == 200:
                                    st.success(f"Entry #{entry['id']} deleted")
                                    st.rerun()
            else:
                st.info("No watchlist entries configured for this tenant.")
        elif w_list_res.status_code == 401:
            st.error("Authentication required (401). Please supply a valid JWT token.")
        else:
            st.error(f"Could not load watchlist entries ({w_list_res.status_code}): {w_list_res.text}")
    except Exception as e:
        st.error(f"Error fetching watchlists: {e}")

# --- TAB 7: LIVE ALERTS (UI-90) ---
with tab_alerts:
    st.subheader("🚨 Live Alerts & Monitoring (UI-90)")
    col_a1, col_a2, col_a3 = st.columns([2, 2, 2])
    with col_a1:
        auto_poll = st.checkbox("Auto-poll every 5 seconds", value=False, key="chk_auto_poll")
    with col_a2:
        unack_only = st.checkbox("Unacknowledged only", value=False, key="chk_unack_only")
    with col_a3:
        btn_poll = st.button("🔄 Poll Alerts Now", key="btn_poll_alerts", type="secondary")

    try:
        poll_params = {"limit": 50, "unacknowledged_only": unack_only}
        alerts_res = requests.get(f"{ALERT_API_URL}/alerts/poll", params=poll_params, headers=get_auth_headers(), timeout=10)
        if alerts_res.status_code == 200:
            alerts_data = alerts_res.json()
            if alerts_data:
                st.markdown(f"**Found {len(alerts_data)} alerts**")
                for alert in alerts_data:
                    st.markdown("<div class='frame-card'>", unsafe_allow_html=True)
                    a_cols = st.columns([1, 3])
                    with a_cols[0]:
                        if alert.get("thumbnail_url"):
                            st.image(alert["thumbnail_url"], use_column_width=True)
                        else:
                            st.caption("No crop preview")
                    with a_cols[1]:
                        score = alert.get("match_score", 0.0)
                        matched_ts = alert.get("matched_at", "")[:19]
                        cam = alert.get("camera_id", "cam-default")
                        ack = alert.get("acknowledged", False)
                        ack_by = alert.get("acknowledged_by")
                        ack_at = alert.get("acknowledged_at", "")[:19] if alert.get("acknowledged_at") else ""

                        st.markdown(
                            f"<h4>Alert #{alert['id']} — Camera: {cam}</h4>"
                            f"<p><strong>Match Score:</strong> {score:.2f} | <strong>Time:</strong> {matched_ts} | <strong>Watchlist Entry:</strong> #{alert.get('watchlist_entry_id')}</p>",
                            unsafe_allow_html=True
                        )

                        if ack:
                            st.success(f"✅ Acknowledged by **{ack_by}** at {ack_at}")
                        else:
                            st.warning("⚠️ PENDING OPERATOR REVIEW")
                            if st.button(f"Acknowledge #{alert['id']}", key=f"ack_btn_{alert['id']}", type="primary"):
                                ack_res = requests.patch(f"{ALERT_API_URL}/alerts/{alert['id']}/acknowledge", headers=get_auth_headers(), timeout=5)
                                if ack_res.status_code == 200:
                                    st.success(f"Alert #{alert['id']} acknowledged!")
                                    st.rerun()
                                else:
                                    st.error(f"Acknowledgment failed: {ack_res.text}")

                    st.markdown("</div>", unsafe_allow_html=True)
            else:
                st.info("No alerts found matching the criteria.")
        elif alerts_res.status_code == 401:
            st.error("Authentication required (401). Please supply a valid JWT token.")
        else:
            st.error(f"Error fetching alerts ({alerts_res.status_code}): {alerts_res.text}")
    except Exception as e:
        st.error(f"Alert connection error: {e}")


# --- RESULTS DISPLAY (UI-88, UI-91, UI-93) ---
st.markdown("---")
display_results = results or st.session_state.get("last_results", [])

if display_results:
    st.subheader(f"Results ({len(display_results)} found)")
    grid_cols = st.columns(3)
    for idx, hit in enumerate(display_results):
        with grid_cols[idx % 3]:
            st.markdown("<div class='frame-card'>", unsafe_allow_html=True)
            # Render thumbnail with presigned URL (UI-88)
            thumb_url = hit.get("thumbnail_url")
            if thumb_url:
                st.image(thumb_url, use_column_width=True)
            else:
                st.info("No thumbnail preview available")

            # Direct consumption of frame_timestamp (UI-93)
            formatted_ts = format_timestamp(hit.get("frame_timestamp"))
            score = hit.get("score", 0.0)
            cam = hit.get("camera_id") or "cam-default"

            badges_html = f"<span class='frame-badge'>Score: {score:.2f}</span>"
            badges_html += f"<span class='frame-badge'>Time: {formatted_ts}</span>"
            badges_html += f"<span class='frame-badge'>Cam: {cam}</span>"

            if hit.get("color"):
                badges_html += f"<span class='frame-badge'>{hit['color'].title()}</span>"
            if hit.get("vehicle_type"):
                badges_html += f"<span class='frame-badge'>{hit['vehicle_type'].title()}</span>"
            if hit.get("plate_number"):
                badges_html += f"<span class='frame-badge' style='background-color:#dbeafe;color:#1e40af;'>Plate: {hit['plate_number']}</span>"

            st.markdown(f"<div style='margin-top:0.5rem;'>{badges_html}</div>", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)

elif "last_results" in st.session_state:
    # Handle empty state gracefully (UI-91)
    st.info("No detections or frames found matching the search criteria.")

st.markdown("</div>", unsafe_allow_html=True)
