# Standard library imports
import io
import os

# Third-party imports for HTTP requests, UI framework, and image processing
import requests
import streamlit as st
from PIL import Image
from streamlit_card import card

# --- Custom Styling ---
# Load and apply custom CSS from style.css file to enhance the UI appearance
with open("style.css") as f:
    st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

# --- Page Configuration ---
# Configure Streamlit page settings: title, icon, and layout
# 'centered' layout keeps content in the center of the screen
st.set_page_config(
    page_title="MyVastu — Floor Plan Analyzer",
    page_icon="🏠",
    layout="centered",
)

# --- API Configuration ---
# Set the base URL for the FastAPI backend service
# In production (Render), use the deployed service URL from environment variable
# Falls back to localhost for local development
API_BASE_URL = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000/api/v1")

# --- Compass Direction Configuration ---
# List of compass directions for floor plan orientation
COMPASS_OPTIONS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]

# Dictionary mapping compass abbreviations to full labels for user-friendly display
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


# --- Score Bar Visualization Function ---
def render_score_bar(score: float, max_score: float) -> None:
    """
    Renders a visual progress bar showing the Vastu score as a percentage.
    
    Args:
        score (float): The actual score achieved
        max_score (float): The maximum possible score
    
    Color coding:
        - Green (#2ecc71): 80%+ (excellent)
        - Amber (#f39c12): 50-79% (moderate)
        - Red (#e74c3c): Below 50% (needs improvement)
    """
    # Calculate percentage of score relative to max score
    pct = score / max_score if max_score > 0 else 0
    
    # Determine color based on percentage thresholds
    if pct >= 0.8:
        color = "#2ecc71"  # green for excellent
    elif pct >= 0.5:
        color = "#f39c12"  # amber for moderate
    else:
        color = "#e74c3c"  # red for needs attention

    # Render HTML progress bar with inline CSS styling
    st.markdown(
        f"""
        <div style="background:#e0e0e0;border-radius:6px;height:10px;margin-bottom:4px;">
          <div style="background:{color};width:{pct*100:.0f}%;height:10px;border-radius:6px;"></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# --- Header ---
# Display the main title and description of the application
st.title("MyVastu")
st.subheader("Vastu Shastra compliance for your home")
st.markdown("Upload your floor plan, mark north, and get an instant Vastu score with room-by-room feedback.")
st.divider()

# --- Upload Section ---
# Create a two-column layout: left for image upload, right for north direction selection
col1, col2 = st.columns([2, 1])

# Left column: File uploader and image preview
with col1:
    uploaded_file = st.file_uploader(
        "Upload your floor plan",
        type=["jpg", "jpeg", "png"],
        help="JPG or PNG image, max 5MB",
    )
    # If user uploads a file, display it with PIL (Python Imaging Library)
    if uploaded_file:
        image = Image.open(io.BytesIO(uploaded_file.read()))
        uploaded_file.seek(0)  # reset file pointer after PIL read so we can send it again

        st.image(image, caption="Your floor plan", use_container_width=True)

# Right column: Compass direction selector and guidance text
with col2:
    # Dropdown to select which direction is North on the floor plan
    north_direction = st.selectbox(
        "Which direction is North?",
        options=COMPASS_OPTIONS,
        format_func=lambda x: COMPASS_LABELS[x],
        help="Select the compass direction that is North in your floor plan",
    )
    st.markdown("")
    # Display helpful tips for finding North
    st.markdown(
        """
        **How to find North:**
        - Check a compass app on your phone
        - Look for North markers on the floor plan itself
        - Ask your broker — they usually know
        """
    )

st.divider()

# --- Analyze Button ---
# Create a primary button to submit the floor plan for analysis
# Button is disabled until a file is uploaded
analyze_clicked = st.button(
    "Analyze My Floor Plan",
    type="primary",
    disabled=uploaded_file is None,
    use_container_width=True,
)

# Display a caption when no file is uploaded to guide the user
if uploaded_file is None:
    st.caption("Upload a floor plan above to enable analysis.")

# --- Analysis Logic ---
# This block executes when the user clicks the Analyze button and a file is uploaded
if analyze_clicked and uploaded_file is not None:
    # Show a spinner while waiting for the backend to process the image
    with st.spinner("Analyzing your floor plan... this takes about 15–30 seconds."):
        try:
            # Send the floor plan image and north direction to the FastAPI backend
            response = requests.post(
                f"{API_BASE_URL}/analyze",
                files={"floor_plan": (uploaded_file.name, uploaded_file, uploaded_file.type)},
                data={"north_direction": north_direction},
                timeout=90,
            )
            # Raise an exception for HTTP error status codes
            response.raise_for_status()
            # Parse the response as JSON to get the analysis result
            result = response.json()

        # Handle connection errors (backend not running)
        except requests.exceptions.ConnectionError:
            st.error("Cannot connect to the analysis server. Make sure the FastAPI backend is running on port 8000.")
            st.stop()
        # Handle timeout errors (request took too long)
        except requests.exceptions.Timeout:
            st.error("The analysis timed out. Please try again.")
            st.stop()
        # Handle HTTP errors (4xx or 5xx responses)
        except requests.exceptions.HTTPError as e:
            # Try to extract error details from the response JSON
            error_detail = ""
            try:
                error_detail = e.response.json().get("detail", "")
            except Exception:
                pass
            st.error(f"Analysis failed: {error_detail or str(e)}")
            st.stop()
        # Handle any other unexpected errors
        except Exception as e:
            st.error(f"Something went wrong: {e}")
            st.stop()

    # --- Results ---
    # Display results heading and the analysis report
    st.divider()
    st.header("Your Vastu Report")

    # Extract the overall Vastu score from the analysis result
    overall = result["overall_score"]

    # Display the overall score with color-coded metric and interpretation
    score_col, label_col = st.columns([1, 2])
    with score_col:
        # Determine score grade and color based on overall score value
        if overall >= 75:
            score_color = "#2ecc71"  # green
            grade = "Good"
        elif overall >= 50:
            score_color = "#f39c12"  # amber
            grade = "Average"
        else:
            score_color = "#e74c3c"  # red
            grade = "Needs Attention"

        # Display overall score as a metric with pass/fail icon
        st.metric(
            label="Overall Score",
            value=f"{overall:.0f} / 100",
            delta=None,
            help=grade,
            icon="✅" if overall >= 50 else "❌",
        )

    with label_col:
        # Display the marked north direction and summary of the analysis
        st.markdown(f"**North marked as:** {result['north_direction']}")
        st.markdown(f"**Summary:**")
        st.markdown(result["summary"])

    st.divider()

    # --- Per-Rule Breakdown ---
    # Display expandable sections for each Vastu rule with detailed feedback
    st.subheader("Room-by-Room Breakdown")

    # Iterate through each rule result and display details in expandable containers
    for rule in result["rule_results"]:
        # Create expandable section for each rule showing rule name and score
        with st.expander(f"{rule['rule_name']} — {rule['score']:.0f} / {rule['max_score']:.0f} pts", expanded=True):
            # Display visual score bar showing compliance level
            render_score_bar(rule["score"], rule["max_score"])
            # Show what the analysis found for this rule
            st.markdown(f"**What we found:** {rule['observation']}")
            # Display suggestions for improvement if available, otherwise show success message
            if rule["suggestion"]:
                st.info(f"**Suggestion:** {rule['suggestion']}")
            else:
                st.success("This aspect is ideal — no changes needed.")
