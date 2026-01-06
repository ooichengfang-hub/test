import streamlit as st
import pandas as pd
import os
from datetime import datetime
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS
from streamlit_js_eval import streamlit_js_eval

# --- Helper: Extract GPS from Uploaded Files ---
def get_file_metadata(image_file):
    try:
        image = Image.open(image_file)
        info = image._getexif()
        if not info: return None, None
        
        exif = {TAGS.get(tag, tag): value for tag, value in info.items()}
        timestamp = exif.get("DateTimeOriginal")
        
        gps_info = exif.get("GPSInfo")
        coords = None
        if gps_info:
            def to_deg(v): return float(v[0]) + (float(v[1])/60.0) + (float(v[2])/3600.0)
            lat = to_deg(gps_info[2])
            if gps_info[1] == 'S': lat = -lat
            lon = to_deg(gps_info[4])
            if gps_info[3] == 'W': lon = -lon
            coords = f"{lat},{lon}"
        return timestamp, coords
    except:
        return None, None

# --- UI Setup ---
st.set_page_config(page_title="Site Attendance", page_icon="📸")
st.title("🚧 Site Punch Card")

# Get Live GPS (runs in background for Live Camera mode)
live_loc = streamlit_js_eval(js_expressions="navigator.geolocation.getCurrentPosition(x => {return x.coords}, (err) => {return err})", key="gps")

staff_name = st.selectbox("Staff Name", ["Alice", "Bob", "Charlie"])
mode = st.radio("Choose Method", ["Live Photo", "Upload from Gallery"])

final_img = None
final_gps = "Unknown"
final_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# --- Logic: Live Camera ---
if mode == "Live Photo":
    final_img = st.camera_input("Take Live Photo")
    if live_loc and isinstance(live_loc, dict):
        final_gps = f"{live_loc['latitude']},{live_loc['longitude']}"

# --- Logic: Upload ---
else:
    final_img = st.file_uploader("Upload JPEG with GPS data", type=['jpg', 'jpeg'])
    if final_img:
        meta_time, meta_gps = get_file_metadata(final_img)
        if meta_gps:
            final_gps = meta_gps
            final_time = meta_time if meta_time else final_time
            st.success(f"Verified Metadata Found: {final_gps}")
        else:
            st.warning("⚠️ No GPS found in photo metadata. Make sure 'Location Tags' are on in camera settings.")

# --- Save Button ---
if final_img and st.button("Submit Attendance"):
    # Save Image
    path = f"punched_photos/{staff_name}_{datetime.now().strftime('%H%M%S')}.jpg"
    if not os.path.exists("punched_photos"): os.makedirs("punched_photos")
    
    with open(path, "wb") as f:
        f.write(final_img.getbuffer())
        
    # Log to CSV
    log_data = {"Name": staff_name, "Time": final_time, "GPS": final_gps, "File": path}
    df = pd.DataFrame([log_data])
    df.to_csv("attendance.csv", mode='a', header=not os.path.exists("attendance.csv"), index=False)
    
    st.success("✅ Attendance Recorded!")
    st.markdown(f"[View Location on Maps](https://www.google.com/maps?q={final_gps})")
