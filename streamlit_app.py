import io

import requests
import streamlit as st
from PIL import Image

# --- Page config ---
st.set_page_config(
    page_title="MyVastu — Floor Plan Analyzer",
    page_icon="🏠",
    layout="centered",
)

API_BASE_URL = "http://127.0.0.1:8000/api/v1"

COMPASS_OPTIONS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
COMPASS_LABELS = {
    "N": "N — North",
    "NE": "NE — North-East",
    "E": "E — East",
    "SE": "SE — South-East",
    "S": "S — South",
    "SW": "SW — South-West",
    "W": "W — West",
    "NW": "NW — North-West",
}


def render_score_bar(score: float, max_score: float) -> None:
    pct = score / max_score if max_score > 0 else 0
    if pct >= 0.8:
        color = "#2ecc71"  # green
    elif pct >= 0.5:
        color = "#f39c12"  # amber
    else:
        color = "#e74c3c"  # red

    st.markdown(
        f"""
        <div style="background:#e0e0e0;border-radius:6px;height:10px;margin-bottom:4px;">
          <div style="background:{color};width:{pct*100:.0f}%;height:10px;border-radius:6px;"></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# --- Header ---
st.title("MyVastu")
st.subheader("Vastu Shastra compliance for your home")
st.markdown("Upload your floor plan, mark north, and get an instant Vastu score with room-by-room feedback.")
st.divider()

# --- Upload section ---
col1, col2 = st.columns([2, 1])

with col1:
    uploaded_file = st.file_uploader(
        "Upload your floor plan",
        type=["jpg", "jpeg", "png"],
        help="JPG or PNG image, max 5MB",
    )
    if uploaded_file:
        image = Image.open(io.BytesIO(uploaded_file.read()))
        uploaded_file.seek(0)  # reset after PIL read so we can send it again
        st.image(image, caption="Your floor plan", use_container_width=True)

with col2:
    north_direction = st.selectbox(
        "Which direction is North?",
        options=COMPASS_OPTIONS,
        format_func=lambda x: COMPASS_LABELS[x],
        help="Select the compass direction that is North in your floor plan",
    )
    st.markdown("")
    st.markdown(
        """
        **How to find North:**
        - Check a compass app on your phone
        - Look for North markers on the floor plan itself
        - Ask your broker — they usually know
        """
    )

st.divider()

# --- Analyze button ---
analyze_clicked = st.button(
    "Analyze My Floor Plan",
    type="primary",
    disabled=uploaded_file is None,
    use_container_width=True,
)

if uploaded_file is None:
    st.caption("Upload a floor plan above to enable analysis.")

# --- Analysis ---
if analyze_clicked and uploaded_file is not None:
    with st.spinner("Analyzing your floor plan... this takes about 15–30 seconds."):
        try:
            response = requests.post(
                f"{API_BASE_URL}/analyze",
                files={"floor_plan": (uploaded_file.name, uploaded_file, uploaded_file.type)},
                data={"north_direction": north_direction},
                timeout=90,
            )
            response.raise_for_status()
            result = response.json()

        except requests.exceptions.ConnectionError:
            st.error("Cannot connect to the analysis server. Make sure the FastAPI backend is running on port 8000.")
            st.stop()
        except requests.exceptions.Timeout:
            st.error("The analysis timed out. Please try again.")
            st.stop()
        except requests.exceptions.HTTPError as e:
            error_detail = ""
            try:
                error_detail = e.response.json().get("detail", "")
            except Exception:
                pass
            st.error(f"Analysis failed: {error_detail or str(e)}")
            st.stop()
        except Exception as e:
            st.error(f"Something went wrong: {e}")
            st.stop()

    # --- Results ---
    st.divider()
    st.header("Your Vastu Report")

    overall = result["overall_score"]

    # Overall score display
    score_col, label_col = st.columns([1, 2])
    with score_col:
        if overall >= 75:
            score_color = "#2ecc71"
            grade = "Good"
        elif overall >= 50:
            score_color = "#f39c12"
            grade = "Average"
        else:
            score_color = "#e74c3c"
            grade = "Needs Attention"

        st.markdown(
            f"""
            <div style="text-align:center;padding:20px;background:#f8f8f8;border-radius:12px;">
              <div style="font-size:52px;font-weight:bold;color:{score_color};">{overall:.0f}</div>
              <div style="font-size:16px;color:#666;">out of 100</div>
              <div style="font-size:18px;font-weight:600;margin-top:6px;color:{score_color};">{grade}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with label_col:
        st.markdown(f"**North marked as:** {result['north_direction']}")
        st.markdown(f"**Summary:**")
        st.markdown(result["summary"])

    st.divider()

    # Per-rule breakdown
    st.subheader("Room-by-Room Breakdown")

    for rule in result["rule_results"]:
        with st.expander(f"{rule['rule_name']} — {rule['score']:.0f} / {rule['max_score']:.0f} pts", expanded=True):
            render_score_bar(rule["score"], rule["max_score"])
            st.markdown(f"**What we found:** {rule['observation']}")
            if rule["suggestion"]:
                st.info(f"**Suggestion:** {rule['suggestion']}")
            else:
                st.success("This aspect is ideal — no changes needed.")
