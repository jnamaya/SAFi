# Dashboard/safi_dashboard.py
# SAFi v1 Dashboard - Hybrid layout with high-level KPIs and detailed log analysis

import os
import json
import glob
import sys
from datetime import datetime, timedelta
from pathlib import Path
from collections import Counter

import pandas as pd
import streamlit as st
import numpy as np

# ---------- Project imports ----------
try:
    # FIX: Force local path detection to avoid "SAFI_PROJECT_ROOT" from remote env polluting local run
    # env_root = os.environ.get("SAFI_PROJECT_ROOT")
    
    # Always resolve relative to this file
    project_root = Path(__file__).resolve().parents[2]

    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    from safi_app.core import values as safi_values
    from safi_app import config as safi_config
except ImportError as e:
    st.error(
        f"Could not import SAFi modules. Please ensure the `SAFI_PROJECT_ROOT` environment variable is set "
        f"or that the script is run from a directory where `safi_app` is accessible.\n"
        f"Attempted project root: {project_root}\nError: {e}"
    )
    st.stop()


# ---------- Page setup ----------
st.set_page_config("SAFi Audit Hub", layout="wide", initial_sidebar_state="collapsed")
st.sidebar.write(f"Dashboard Version: v1.0.5 (Fixed Pathing) - Running from: {__file__}")

# ---------- AUTHENTICATION MIDDLEWARE ----------
import jwt

# Verify Token from Query Params
query_params = st.query_params
token = query_params.get("token", None)

if not token:
    st.error("⚠️ Access Denied: No authentication token provided. Please access this dashboard via the SAFi interface.")
    st.stop()

try:
    # Use Config.SECRET_KEY from loaded config (safi_config)
    # Ensure Config is loaded first (it is imported inside try-catch block lines 17-29, we assume success or stop)
    # FIX: Move Auth Block AFTER Config Load
    # We will assume basic security provided by verify_signature=True (default)
    
    # We need Config.SECRET_KEY. It is available in safi_config.Config.SECRET_KEY
    secret_key = safi_config.Config.SECRET_KEY
    
    try:
        payload = jwt.decode(token, secret_key, algorithms=["HS256"])
    except jwt.InvalidTokenError:
        # Fallback: Check if backend is using the default dev key?
        fallback_key = "dev-secret-key-should-be-changed"
        if secret_key != fallback_key:
            try:
                payload = jwt.decode(token, fallback_key, algorithms=["HS256"])
                st.sidebar.warning("⚠️ Config Mismatch: Backend using default Dev Key.")
            except jwt.InvalidTokenError:
                 raise # Re-raise original error if fallback also fails
        else:
             raise # Re-raise if we were already using dev key
    
    # Verify Role (Redundant but safe)
    if payload.get('role') not in ['admin', 'editor', 'auditor']:
        st.error(f"⚠️ Access Denied: Role '{payload.get('role')}' is not authorized.")
        st.stop()
        
    st.sidebar.success(f"Authenticated as: {payload.get('sub')} ({payload.get('role')})")
    
    # Extract Org ID
    # Extract Identity
    token_org_id = payload.get('org_id')
    user_role = payload.get('role')
    token_email = payload.get('email')
    token_user_id = payload.get('sub')
    
    SUPER_ADMIN_EMAILS = ["jnamaya@gmail.com"]
    is_super_admin = (user_role == 'admin' and token_email in SUPER_ADMIN_EMAILS)
    
except jwt.ExpiredSignatureError:
    st.error("⚠️ Session Expired: Please return to SAFi and reload the dashboard.")
    st.stop()
except jwt.InvalidTokenError:
    st.error("⚠️ Access Denied: Invalid security token.")
    st.stop()
except Exception as e:
    st.error(f"⚠️ Authentication Error: {str(e)}")
    st.stop()
    st.error("⚠️ Session Expired: Please return to SAFi and reload the dashboard.")
    st.stop()
except jwt.InvalidTokenError as e:
    st.error(f"⚠️ Access Denied: Invalid security token. Error: {e}")
    st.stop()
    st.stop()
except Exception as e:
    st.error(f"⚠️ Authentication Error: {str(e)}")
    st.stop()

# ---------- Data Loading and Caching ----------
# FIX: Revert to using Config, but keep debug visibility
LOG_DIR = project_root / safi_config.Config.LOG_DIR
LOG_TEMPLATE = safi_config.Config.LOG_FILE_TEMPLATE

def list_log_files(profile_key: str, profile_name: str) -> list[str]:
    patterns = set()
    
    # 1. New Standard: Key-based
    if profile_key:
        patterns.add(LOG_TEMPLATE.format(profile=profile_key).replace("%Y-%m-%d", "*"))
        
    # 2. Legacy: Name-based (exact match)
    if profile_name:
        patterns.add(LOG_TEMPLATE.format(profile=profile_name).replace("%Y-%m-%d", "*"))
        # 2b. Legacy: Name-based (lowercase) - Fix for case-sensitive FS
        patterns.add(LOG_TEMPLATE.format(profile=profile_name.lower()).replace("%Y-%m-%d", "*"))
        
        # 3. Legacy Fallback: Sanitized Name (if different from key)
        # Replicates Orchestrator sanitization logic
        import re
        sanitized = re.sub(r'[^a-zA-Z0-9_\-]', '_', profile_name).lower()
        if sanitized != profile_key:
             patterns.add(LOG_TEMPLATE.format(profile=sanitized).replace("%Y-%m-%d", "*"))

    found_files = set()
    for p in patterns:
        full_glob_path = str(LOG_DIR / p)
        found_files.update(glob.glob(full_glob_path))
        
    return sorted(list(found_files), reverse=True)

def has_user_access(file_paths: list[str], user_id: str, org_id: str) -> bool:
    """
    Checks if the user has ANY access to the given log files.
    Optimized: Scans newest files first, stops on first match.
    Uses simple string check for speed (avoiding full JSON parse).
    """
    if not file_paths: return False
    
    # Scan max 5 newest files to keep it snappy for dropdown generation
    for fp in file_paths[:5]:
        try:
            with open(fp, "r", encoding="utf-8") as f:
                content = f.read()
                # Check for User ID or Org ID presence
                if user_id and user_id in content: return True
                if org_id and org_id in content: return True
        except: continue
    
    return False

def normalize_entry(e: dict) -> dict:
    """A comprehensive normalizer to capture all faculty outputs for the detailed view."""
    is_v1_flat = ("userPrompt" in e) or ("intellectDraft" in e)
    if is_v1_flat:
        will_dec = (e.get("willDecision") or "").lower()
        will_norm = "Approved" if will_dec == "approve" else ("Blocked" if will_dec in ["violation", "blocked"] else e.get("willDecision", "Unknown"))
        return {
            "timestamp": e.get("timestamp"), "prompt": e.get("userPrompt", ""),
            "intellect.response": e.get("intellectDraft", ""), "intellect.reflection": e.get("intellectReflection", ""),
            "intellect_system": e.get("intellectSystem"), 
            "memory.summary": e.get("memorySummary"),
            "intellect.context": e.get("retrievedContext"),
            "will.decision": will_norm, "will.reflection": e.get("willReason", ""),
            "will.blocked_draft": e.get("blockedDraft", ""), # <-- ADDED
            "conscience.evaluations": e.get("conscienceLedger", []) or e.get("conscience_ledger", []),
            "spirit.score": e.get("spiritScore"), "spirit.drift": e.get("drift"),
            "spirit.reflection": e.get("spiritNote", ""), "spirit.feedback": e.get("spiritFeedback", ""),
            "output": e.get("finalOutput", ""),
            "org_id": e.get("orgId"), "user_id": e.get("userId") # <-- Security Context
        }
    return {
        "timestamp": e.get("timestamp"), "prompt": e.get("prompt", ""),
        "intellect.response": e.get("intellect", {}).get("response", ""), "intellect.reflection": e.get("intellect", {}).get("reflection", ""),
        "intellect_system": e.get("intellectSystem"), 
        "memory.summary": e.get("memorySummary"),
        "intellect.context": e.get("retrievedContext"), # <-- ADDED
        "will.decision": e.get("will", {}).get("decision", "Unknown"), "will.reflection": e.get("will", {}).get("reflection", ""),
        "conscience.evaluations": e.get("conscience", {}).get("evaluations", []),
        "spirit.score": e.get("spirit", {}).get("score"), "spirit.drift": e.get("spirit", {}).get("drift"),
        "spirit.reflection": e.get("spirit", {}).get("reflection", ""), "spirit.feedback": e.get("spirit", {}).get("feedback", ""),
        "output": e.get("output", ""),
        "org_id": e.get("orgId"), "user_id": e.get("userId") # <-- Security Context
    }

@st.cache_data(ttl=300)
def load_and_process_logs(profile_key: str, profile_name: str) -> pd.DataFrame:
    log_files = list_log_files(profile_key, profile_name)
    if not log_files: return pd.DataFrame()

    all_entries = []
    for file_path in log_files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            for line in lines:
                if line.strip(): all_entries.append(json.loads(line))
        except (json.JSONDecodeError, IOError): continue
    
    # Filter by Organization (for Agent View)
    # Filter by Organization (for Agent View)


    if not all_entries: return pd.DataFrame()

    df = pd.DataFrame([normalize_entry(e) for e in all_entries])
    df["ts"] = pd.to_datetime(df["timestamp"], errors='coerce', utc=True)
    df = df.dropna(subset=["ts"])
    df["spirit.score"] = pd.to_numeric(df["spirit.score"], errors='coerce')
    df["spirit.drift"] = pd.to_numeric(df["spirit.drift"], errors='coerce')
    
    # ADDED memory.summary and intellect.context to fillna
    for col in [
        "prompt", "will.decision", "output", "intellect.response", "intellect.reflection", 
        "will.reflection", "spirit.reflection", "spirit.feedback",
        "memory.summary", "intellect.context"
    ]:
        df[col] = df[col].fillna("")

    return df.sort_values("ts", ascending=False).reset_index(drop=True)


# ---------- UI Components and Styling ----------
st.markdown("""
    <style>
        .card {
            background-color: var(--secondary-background-color);
            border: 1px solid rgba(128, 128, 128, 0.2);
            border-radius: 0.75rem;
            padding: 1.5rem;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            height: 100%;
            color: var(--text-color);
        }
        div[data-testid="stMetric"] {
            background-color: var(--secondary-background-color);
            border: 1px solid rgba(128, 128, 128, 0.2);
            border-radius: 0.75rem;
            padding: 1.5rem;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
        }
        .gauge-bg { fill: rgba(128, 128, 128, 0.2); }
        .gauge-fill { transition: stroke-dasharray 0.5s ease-in-out; stroke-linecap: round; }
        .gauge-text { font-size: 2.25rem; font-weight: 700; fill: currentColor; }
    </style>
""", unsafe_allow_html=True)

def create_gauge_card(score: float) -> str:
    if not pd.notna(score) or score < 1 or score > 10: score = 0
    percentage = (score - 1) / 9
    circumference = 2 * np.pi * 54
    stroke_dasharray = f"{percentage * circumference} {circumference}"
    if score > 7: color = "#10b981"
    elif score > 4: color = "#f59e0b"
    else: color = "#ef4444"
    
    gauge_svg = f"""<svg width="160" height="160" viewBox="0 0 120 120"><circle class="gauge-bg" cx="60" cy="60" r="54" stroke-width="12" fill="none"></circle><circle class="gauge-fill" cx="60" cy="60" r="54" stroke-width="12" transform="rotate(-90 60 60)" stroke-dasharray="{stroke_dasharray}" style="stroke: {color};" fill="none"></circle><text class="gauge-text" x="50%" y="50%" dominant-baseline="middle" text-anchor="middle">{score:.1f}</text></svg>"""
    
    explanation_html = """<div style="text-align: center; font-size: 0.8em; opacity: 0.7; margin-top: 8px;">This score blends compliance and Consistency into a single measure.</div>"""

    return f"""
    <div class="card">
        <p style="text-align: center; font-size: 1.125rem; font-weight: 500;">Overall Score</p>
        {gauge_svg}
        {explanation_html}
    </div>
    """

# ---------- 1. The Header ----------
header_cols = st.columns([6, 6])
with header_cols[0]:
    st.markdown("""<div style="display: flex; align-items: center; gap: 12px; height: 100%;"><h1 style="font-size: 1.875rem; font-weight: 700; margin: 0;">Audit Hub</h1></div>""", unsafe_allow_html=True)
with header_cols[1]:
    filter_cols = st.columns([2, 2, 3, 3])
    with filter_cols[0]:
        st.button("🔄 Refresh", on_click=st.cache_data.clear)
    with filter_cols[1]:
        mode = st.radio("Mode", ["Agent", "Policy"], horizontal=True, label_visibility="collapsed")
    with filter_cols[2]:
        if mode == "Agent":
            available_profiles = safi_values.list_profiles(include_all=True)
            
            # Use list comprehension to filter only profiles that have logs
            # This satisfies "Hide unused agents" AND "Hide agents not used by User"
            active_profiles = []
            for p in available_profiles:
                log_files = list_log_files(p['key'], p['name'])
                if log_files:
                    # Logs exist. Now check perms.
                    if is_super_admin:
                        active_profiles.append(p)
                    elif has_user_access(log_files, token_user_id, token_org_id):
                        active_profiles.append(p)
            
            profile_map = {p['name']: p['key'] for p in active_profiles}
            
            if not profile_map:
                st.warning("No Agents with logs found.")
                selected_item = None
            else:
                selected_item = st.selectbox("Persona", options=profile_map.keys(), label_visibility="collapsed")
            selected_key = profile_map.get(selected_item)
        else:
            # Policy Mode: Need to fetch policies from DB 
            from safi_app.persistence import database as db
            policies = []
            db_error = None
            
            try:
                conn = db.get_db_connection()
                cursor = conn.cursor(dictionary=True)
                
                # RBAC: Filter Policies by Organization
                if is_super_admin:
                     # Super Admin (Explicit) sees everything
                     cursor.execute("SELECT id, name FROM policies ORDER BY name")
                elif token_org_id:
                     # Org Admin/Auditor sees only their Org's policies
                     cursor.execute("SELECT id, name FROM policies WHERE org_id = %s ORDER BY name", (token_org_id,))
                     
                policies = cursor.fetchall()
                cursor.close()
                conn.close()
            except Exception as e:
                db_error = str(e)
    with filter_cols[3]:
        date_range_option = st.selectbox("Date Range", options=["Last 7 Days", "Last 30 Days", "All Time"], index=0, label_visibility="collapsed")
        
    with filter_cols[2]:
        if mode == "Policy":
            # Add option to show historical policies not in DB
            show_archived = st.checkbox("Show Archived", value=False)
            if db_error or show_archived:
                with st.spinner("Scanning logs for archived policies..."):
                    # FIX: Use recursive glob correctly
                    # On Linux, verify permissions or use flat glob if recursive fails
                    search_pattern = str(LOG_DIR / "**" / "*.json")
                    all_files = glob.glob(search_pattern, recursive=True)
                    
                    found_ids = set()
                    for file_path in all_files:
                        try:
                            # Quick scan to avoid reading huge files
                            # Check only first few lines or filename if ID is in it (it's not)
                            with open(file_path, "r", encoding="utf-8") as f:
                                for line in f:
                                    if '"policyId":' in line:
                                        entry = json.loads(line)
                                        pid = entry.get("policyId")
                                        if pid: found_ids.add(pid)
                        except: continue
                    
                    for pid in found_ids:
                        # Only add if not already in DB list
                        if pid not in [p['id'] for p in policies]:
                            policies.append({"id": pid, "name": f"Archived: {pid[:8]}..."})

            policy_map = {p['name']: p['id'] for p in policies}
            
            if not policy_map:
                st.warning("No Policies found.")
                selected_item = None
                selected_key = None
            else:
                selected_item = st.selectbox("Policy", options=policy_map.keys(), label_visibility="collapsed")
                selected_key = policy_map.get(selected_item)

# --- DEBUG INFO ---


st.divider()

# ---------- Data Filtering and Calculations ----------
if not selected_item:
    st.warning("Please select an item to view logs.")
    st.stop()

# LOAD LOGIC
@st.cache_data(ttl=60)
def scan_all_logs(target_type, target_id):
    """
    Scans ALL log files in the directory tree for matching Policy ID.
    This is heavier than agent lookup but necessary for cross-agent auditing.
    """
    # FIX: Log files are .jsonl, but we might have .json too.
    # Use recursive glob for both.
    # Use recursive glob for both.
    all_files = glob.glob(str(LOG_DIR / "**/*.json*"), recursive=True)
    matches = []
    
    for file_path in all_files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            for line in lines:
                if not line.strip(): continue
                entry = json.loads(line)
                
                if target_type == "Policy":
                    if entry.get("policyId") == target_id:
                        matches.append(entry)
        except: continue
            
    return matches

if mode == "Agent":
    df = load_and_process_logs(selected_key, selected_item) # Use existing optimized loader
    
    # --- SECURITY FILTER (Dataframe) ---
    if not df.empty:
        if is_super_admin:
            pass # Super Admin sees all
        elif token_org_id:
            # Org User: Org Logs + Own Logs (NO GLOBAL LEGACY)
            df = df[ (df["org_id"] == token_org_id) | (df["user_id"] == token_user_id) ]
        else:
            # No Org User: Only Own Logs
            df = df[ df["user_id"] == token_user_id ]
            
else:
    # POLICY MODE
    raw_entries = scan_all_logs("Policy", selected_key)
    
    # --- SECURITY FILTER (List of Dicts) ---
    if is_super_admin:
        pass # Super Admin sees all
    elif token_org_id:
         # Org User: Org Logs + Own Logs (NO GLOBAL LEGACY)
        raw_entries = [e for e in raw_entries if (e.get("orgId") == token_org_id or e.get("userId") == token_user_id)]
    else:
        # No Org User: Only Own Logs
        raw_entries = [e for e in raw_entries if e.get("userId") == token_user_id]
        
    if not raw_entries:
         st.warning(f"No logs found for Policy **{selected_item}**.")
         st.stop()
    df = pd.DataFrame([normalize_entry(e) for e in raw_entries])
    df["ts"] = pd.to_datetime(df["timestamp"], errors='coerce', utc=True)
    df = df.dropna(subset=["ts"])
    df["spirit.score"] = pd.to_numeric(df["spirit.score"], errors='coerce')
    df["spirit.drift"] = pd.to_numeric(df["spirit.drift"], errors='coerce')
    for col in ["prompt", "will.decision", "output", "intellect.response", "intellect.reflection", "will.reflection", "spirit.reflection", "spirit.feedback", "memory.summary", "intellect.context"]:
        df[col] = df[col].fillna("")
    df = df.sort_values("ts", ascending=False).reset_index(drop=True)
    



now = datetime.now(tz=df['ts'].dt.tz)
if date_range_option == "Last 7 Days": df_filtered = df[df["ts"] >= (now - timedelta(days=7))]
elif date_range_option == "Last 30 Days": df_filtered = df[df["ts"] >= (now - timedelta(days=30))]
else: df_filtered = df

avg_alignment = df_filtered["spirit.score"].mean()
avg_incoherence = df_filtered["spirit.drift"].mean()
avg_coherence_percent = (1 - avg_incoherence) * 100 if pd.notna(avg_incoherence) else None

safi_score = avg_alignment - (avg_incoherence * 10) if pd.notna(avg_alignment) and pd.notna(avg_incoherence) else avg_alignment
safi_score = np.clip(safi_score, 1, 10) if pd.notna(safi_score) else 0
approved_count = (df_filtered["will.decision"] == "Approved").sum()
blocked_count = (df_filtered["will.decision"] == "Blocked").sum()
total_audits = len(df_filtered)
approval_rate = (approved_count / (approved_count + blocked_count) * 100) if (approved_count + blocked_count) > 0 else 0

# ---------- 2. Top-Level KPIs ----------
kpi_cols = st.columns([2, 3])
with kpi_cols[0]:
    st.markdown(create_gauge_card(safi_score), unsafe_allow_html=True)

with kpi_cols[1]:
    row1 = st.columns(2)
    row2 = st.columns(2)
    with row1[0]: st.metric("Avg. Compliance Score", f"{avg_alignment:.1f} / 10" if pd.notna(avg_alignment) else "N/A")
    with row1[1]: st.metric("Avg. Long-Term Consistency", f"{avg_coherence_percent:.1f}%" if pd.notna(avg_coherence_percent) else "N/A")
    with row2[0]: 
        st.markdown(f"""
        <div class="card">
            <div style="font-size: 0.875rem;">Approval Rate</div>
            <div style="font-size: 2.25rem;">{approval_rate:.1f}%</div>
            <div style="font-size: 0.875rem;">
                <span style="color: #10b981;">{approved_count} Approved</span> <span style="opacity: 0.5;">/</span> <span style="color: #ef4444;">{blocked_count} Blocked</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
    with row2[1]: st.metric("Total Audits", f"{total_audits}", f"in period")
st.divider()


# ---------- 2.5 Profile Coherence Trend ----------
st.subheader("Agent Consistency Trend")

# Controls
ctrl_cols = st.columns([2, 2, 2, 6])
with ctrl_cols[0]:
    # Use a dictionary to map user-friendly labels to pandas time strings
    ma_options = {"3 Days": "3D", "7 Days": "7D", "14 Days": "14D", "30 Days": "30D"}
    ma_window_label = st.selectbox("Moving average window", list(ma_options.keys()), index=1)
    ma_window_pd = ma_options[ma_window_label] # Get the corresponding pandas string e.g., "7D"
with ctrl_cols[1]:
    # Added "Drift vs. Average" and set it as the default view with index=2
    show_mode = st.selectbox(
        "View", 
        ["Consistency (%)", "Drift (0=best)", "Drift vs. Average"], 
        index=2 
    )
with ctrl_cols[2]:
    show_points = st.checkbox("Show raw points", value=False)

# Prepare time series (ascending for rolling ops)
ts_df = df_filtered[["ts", "spirit.drift"]].dropna().sort_values("ts")

if ts_df.empty or len(ts_df) < 2:
    st.info("Not enough drift data available for this period to draw a trend line.")
else:
    # Calculate the period's average drift to use as a baseline
    avg_drift = ts_df['spirit.drift'].mean()

    ts_df_indexed = ts_df.set_index('ts')

    # --- Compute all metrics ---
    # Standard drift moving average
    ts_df_indexed["drift_ma"] = ts_df_indexed["spirit.drift"].rolling(window=ma_window_pd, min_periods=1).mean()
    # Coherence percentage and its moving average
    ts_df_indexed["coherence_pct"] = (1 - ts_df_indexed["spirit.drift"]) * 100.0
    ts_df_indexed["coherence_ma"] = ts_df_indexed["coherence_pct"].rolling(window=ma_window_pd, min_periods=1).mean()
    # NEW: Deviation from average and its moving average
    ts_df_indexed["drift_deviation"] = ts_df_indexed["spirit.drift"] - avg_drift
    ts_df_indexed["deviation_ma"] = ts_df_indexed["drift_deviation"].rolling(window=ma_window_pd, min_periods=1).mean()
    
    ts_df = ts_df_indexed.reset_index()

    # --- Choose which series to display ---
    if show_mode == "Consistency (%)":
        y_ma = "coherence_ma"; y_raw = "coherence_pct"; y_label = "Consistency Score (%)"
        y_min, y_max = 0, 100
    elif show_mode == "Drift vs. Average":
        y_ma = "deviation_ma"; y_raw = "drift_deviation"; y_label = "Drift vs. Period Average"
        # Create a symmetrical y-axis around 0
        y_abs_max = ts_df[y_raw].abs().max() * 1.15 if not ts_df[y_raw].empty else 0.1
        y_min, y_max = -y_abs_max, y_abs_max
    else: # Default to "Drift (0=best)"
        y_ma = "drift_ma"; y_raw = "spirit.drift"; y_label = "Drift (lower is better)"
        y_min, y_max = 0, 1

    # Plot
    import altair as alt
    base = alt.Chart(ts_df).encode(x=alt.X("ts:T", title="Time", axis=alt.Axis(format='%b %d'))) # Format as 'Mon Day', e.g., 'Sep 27'
    
    # Add a zero-line for the "Drift vs. Average" view for clarity
    zero_line = alt.Chart(pd.DataFrame({'y': [0]})).mark_rule(strokeDash=[3,3]).encode(y='y:Q')
    
    line_ma = base.mark_line(size=2).encode(
        y=alt.Y(f"{y_ma}:Q", title=y_label, scale=alt.Scale(domain=[y_min, y_max], clamp=True)),
        tooltip=["ts:T", alt.Tooltip(f"{y_ma}:Q", format=".3f")]
    )
    
    chart = (line_ma + zero_line) if show_mode == "Drift vs. Average" else line_ma

    if show_points:
        points = base.mark_circle(size=40, opacity=0.25).encode(
            y=alt.Y(f"{y_raw}:Q"),
            tooltip=["ts:T", alt.Tooltip(f"{y_raw}:Q", format=".3f")]
        )
        chart = (chart + points)

    st.altair_chart(chart.properties(height=260, width="container"), use_container_width=True)
st.divider()


# ---------- 3. Log Explorer ----------
with st.container(border=True):
    st.subheader("Log Explorer")
    search_cols = st.columns([4, 1])
    search_query = search_cols[0].text_input("Search prompts...", placeholder="🔍 Search all prompts in the selected date range...", label_visibility="collapsed")
    filter_option = search_cols[1].selectbox("Filter by...", ["All", "Flagged (Score < 6 or Coherence < 60%)", "Approved", "Blocked"], label_visibility="collapsed")

    log_display_df = df_filtered.copy()
    log_display_df['identity_coherence'] = (1 - log_display_df['spirit.drift']) * 100
    
    if search_query:
        log_display_df = log_display_df[log_display_df["prompt"].str.contains(search_query, case=False, na=False)]
    if filter_option == "Flagged (Score < 6 or Coherence < 60%)":
        log_display_df = log_display_df[(log_display_df['spirit.score'] < 6) | (log_display_df['identity_coherence'] < 60)]
    elif filter_option == "Approved":
        log_display_df = log_display_df[log_display_df["will.decision"] == "Approved"]
    elif filter_option == "Blocked":
        log_display_df = log_display_df[log_display_df["will.decision"] == "Blocked"]

    if not log_display_df.empty:
        display_table = log_display_df[['ts', 'prompt', 'spirit.score', 'identity_coherence', 'will.decision']].copy()
        display_table['prompt'] = display_table['prompt'].apply(lambda x: (str(x)[:70] + '...') if len(str(x)) > 70 else str(x))
        display_table['ts'] = display_table['ts'].dt.strftime('%Y-%m-%d %H:%M')
        display_table['identity_coherence'] = display_table['identity_coherence'].apply(lambda x: f"{x:.1f}%" if pd.notna(x) else "N/A")
        display_table = display_table.rename(columns={'spirit.score': 'Alignment', 'identity_coherence': 'Consistency', 'will.decision': 'Decision'})
        st.dataframe(display_table, use_container_width=True, hide_index=True)
    else:
        st.info("No logs match the current filters.")
st.divider()

# ---------- 4. Detailed Faculty Drill-Down ----------
st.header("Full Report for Selected Event")
if not log_display_df.empty:
    selected_index = st.selectbox(
        "Select an event from the table above to inspect:",
        options=log_display_df.index,
        format_func=lambda i: f"({log_display_df.loc[i, 'ts'].strftime('%H:%M')}) {log_display_df.loc[i, 'prompt'][:80]}...",
        label_visibility="collapsed"
    )

    if selected_index is not None:
        entry = log_display_df.loc[selected_index].to_dict()
        tab_intellect, tab_will, tab_conscience, tab_spirit, tab_output = st.tabs(["Intellect", "Will", "Conscience", "Spirit", "Final Output"])
        
        # MODIFIED: Added Context sections to Intellect tab
        with tab_intellect:
            st.markdown("#### Intellect's Draft")
            st.text_area("Draft", value=entry.get("intellect.response", ""), height=200, disabled=True, key=f"idraft_{selected_index}")
            
            st.markdown("#### Intellect's Reflection")
            st.text_area("Reflection", value=entry.get("intellect.reflection", ""), height=150, disabled=True, key=f"irefl_{selected_index}")
            
            st.markdown("#### Context (Memory)")
            st.text_area("Memory", value=entry.get("memory.summary", "No memory summary available."), height=150, disabled=True, key=f"imem_{selected_index}")
            
            st.markdown("#### Context (Retrieved Documents)")
            st.text_area("Retrieved", value=entry.get("intellect.context", "No context retrieved."), height=300, disabled=True, key=f"icontext_{selected_index}")

        with tab_will:
            st.markdown("#### Decision"); st.markdown(f"<div style='font-size: 1.1rem; font-weight: 600; margin-bottom: 1rem;'>{entry.get('will.decision', 'Unknown')}</div>", unsafe_allow_html=True)
            
            # Show Blocked Draft if present
            if entry.get("will.blocked_draft"):
                st.error("Using Blocked Draft Content")
                st.text_area("Blocked Draft", value=entry.get("will.blocked_draft", ""), height=200, disabled=True, key=f"wdraft_{selected_index}")
            
            st.markdown("#### Reason")
            st.text_area("Reason", value=entry.get("will.reflection", ""), height=200, disabled=True, key=f"willr_{selected_index}")
        
        with tab_conscience:
            st.markdown("#### Conscience Ledger")
            ledger = entry.get("conscience.evaluations")
            if ledger and isinstance(ledger, list): st.dataframe(pd.DataFrame(ledger), use_container_width=True)
            else: st.info("No conscience evaluations for this entry.")
        
        with tab_spirit:
            s_c1, s_c2 = st.columns(2)
            score = entry.get('spirit.score')
            coherence = entry.get('identity_coherence')
            s_c1.metric("Alignment Score", f"{score:.2f}" if pd.notna(score) else "N/A")
            s_c2.metric("Consistency Score", f"{coherence:.1f}%" if pd.notna(coherence) else "N/A")
            st.markdown("---")
            st.markdown("#### Spirit Note"); st.text_area("Note", value=entry.get("spirit.reflection", ""), height=150, disabled=True, key=f"snote_{selected_index}", label_visibility="collapsed")
            st.markdown("#### Spirit Feedback"); st.text_area("Feedback", value=entry.get("spirit.feedback", ""), height=150, disabled=True, key=f"sfeedback_{selected_index}", label_visibility="collapsed")
        
        with tab_output:
            st.markdown("#### User Prompt"); st.code(entry.get("prompt", ""), language="markdown")
            st.markdown("#### Final Output to User"); st.markdown(entry.get("output", ""))
else:
    st.info("No logs to inspect.")
st.divider()

# ---------- 5. Downloads ----------
st.header("Downloads")
d1, d2 = st.columns(2)
with d1:
    if not log_display_df.empty and 'selected_index' in locals() and selected_index is not None:
        entry_to_download = log_display_df.loc[selected_index].to_dict()
        st.download_button("Download Selected Entry (JSON)", data=json.dumps(entry_to_download, indent=2, default=str), file_name=f"safi_entry_{selected_index}.json", mime="application/json", use_container_width=True)
    else:
        st.button("Download Selected Entry (JSON)", use_container_width=True, disabled=True)
with d2:
    jsonl_data = log_display_df.to_json(orient='records', lines=True, date_format='iso')
    st.download_button("Download Filtered Logs (JSONL)", data=jsonl_data, file_name=f"safi_export_{datetime.utcnow():%Y%m%d}.jsonl", mime="application/json", use_container_width=True)
