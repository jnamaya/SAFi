import streamlit as st
import json, io, os
import pandas as pd
from datetime import datetime, date, timedelta
from collections import Counter, defaultdict
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors

# -------------------------------
# Config
# -------------------------------
st.set_page_config("SAFi v1 Dashboard", layout="wide")

DEFAULT_LOG = os.getenv("SAFI_LOG_PATH", "saf-spirit-log.jsonl")

st.sidebar.header("Settings")
log_path = st.sidebar.text_input("Log path (.jsonl or .json)", value=DEFAULT_LOG)
value_set = st.sidebar.multiselect(
    "Value set (display order)", ["Truth", "Justice", "Autonomy", "Minimizing Harm"],
    default=["Truth", "Justice", "Autonomy", "Minimizing Harm"],
)

# -------------------------------
# I/O helpers
# -------------------------------
def load_lines(path: str):
    if not os.path.exists(path):
        st.error(f"File not found: {path}")
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            txt = f.read().strip()
            if not txt:
                return []
            # Heuristic: JSONL has many lines of JSON objects
            if "\n" in txt:
                return [json.loads(line) for line in txt.splitlines() if line.strip()]
            # Single JSON (array or object)
            obj = json.loads(txt)
            if isinstance(obj, list):
                return obj
            return [obj]
    except Exception as e:
        st.error(f"Failed to parse log file: {e}")
        return []

raw_logs = load_lines(log_path)

# -------------------------------
# Schema normalization
#   Supports:
#   - v1 flat fields (userPrompt, intellectDraft, willDecision, conscienceLedger, spiritScore, drift, spiritNote, finalOutput, timestamp)
#   - legacy nested fields (prompt, intellect.response, will.decision, conscience.evaluations, spirit.score, output, timestamp)
# -------------------------------
def norm_ts(ts):
    if not ts: return None
    ts = ts.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        try:
            # Some logs may be plain datetime strings
            return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        except Exception:
            return None

def normalize_entry(e):
    # If v1 flat keys exist, map them
    if "userPrompt" in e or "intellectDraft" in e or "willDecision" in e:
        will_dec = e.get("willDecision") or ""
        will_dec_norm = "Approved" if will_dec.lower() == "approve" else ("Blocked" if will_dec.lower() == "violation" else will_dec)

        # Conscience ledger may be list of dicts with {value, score, confidence, reason}
        ledger = e.get("conscienceLedger", []) or e.get("conscience_ledger", [])

        return {
            "timestamp": e.get("timestamp"),
            "prompt": e.get("userPrompt", ""),
            "intellect": {
                "response": e.get("intellectDraft", ""),
                "reflection": e.get("intellectReflection", ""),
            },
            "will": {
                "decision": will_dec_norm,
                "reflection": e.get("willReason", ""),
            },
            "conscience": {
                "evaluations": ledger
            },
            "spirit": {
                "score": e.get("spiritScore"),
                "drift": e.get("drift"),
                "reflection": e.get("spiritNote", ""),
            },
            "output": e.get("finalOutput", ""),
            "versions": {
                "protocol": e.get("protocolVersion"),
                "policy": e.get("policyVersion"),
                "log_schema": e.get("logSchemaVersion"),
                "will": e.get("willVersion"),
                "conscience": e.get("conscienceVersion"),
                "spirit": e.get("spiritVersion"),
            },
        }

    # Legacy nested structure fallback
    return {
        "timestamp": e.get("timestamp"),
        "prompt": e.get("prompt", ""),
        "intellect": {
            "response": e.get("intellect", {}).get("response", ""),
            "reflection": e.get("intellect", {}).get("reflection", ""),
        },
        "will": {
            "decision": e.get("will", {}).get("decision", "Unknown"),
            "reflection": e.get("will", {}).get("reflection", ""),
        },
        "conscience": {
            "evaluations": e.get("conscience", {}).get("evaluations", []),
        },
        "spirit": {
            "score": e.get("spirit", {}).get("score"),
            "drift": e.get("spirit", {}).get("drift"),
            "reflection": e.get("spirit", {}).get("reflection", ""),
        },
        "output": e.get("output", ""),
        "versions": {},
    }

logs = [normalize_entry(e) for e in raw_logs][::-1]  # newest first

if st.button("Refresh"):
    raw_logs[:] = load_lines(log_path)
    logs[:] = [normalize_entry(e) for e in raw_logs][::-1]

# -------------------------------
# Summary builders
# -------------------------------
def build_summary(entries):
    approved = blocked = 0
    spirit_scores = []
    activity = []
    omitted_values = Counter()

    for idx, e in enumerate(entries):
        dt = norm_ts(e.get("timestamp")) or datetime.utcnow()
        decision = (e.get("will", {}).get("decision") or "").lower()
        score = e.get("spirit", {}).get("score")

        if decision.startswith("approve"):
            approved += 1
        elif decision.startswith("block") or decision == "violation":
            blocked += 1

        if score is not None:
            try:
                spirit_scores.append(float(score))
            except Exception:
                pass

        # Count “omits/violates” by interpreting scores:
        # >0 = Affirmed, 0 = Omitted, <0 = Violated
        for v in e.get("conscience", {}).get("evaluations", []):
            vs = v.get("score")
            if vs is None: continue
            try:
                s = float(vs)
            except Exception:
                continue
            if s < 0:
                omitted_values.update([v.get("value", "Unknown")])
            elif s == 0:
                omitted_values.update([v.get("value", "Unknown")])

        short_prompt = (e.get("prompt", "") or "").strip()
        if len(short_prompt) > 90:
            short_prompt = short_prompt[:90] + "..."
        activity.append({
            "Index": idx,
            "Timestamp": dt.strftime("%b %d, %Y %H:%M"),
            "Decision": (e.get("will", {}).get("decision") or "Unknown"),
            "Spirit Score": round(score, 2) if isinstance(score, (int, float)) else score,
            "Prompt": short_prompt
        })

    avg = round(sum(spirit_scores)/len(spirit_scores), 2) if spirit_scores else 0.0
    ratio = f"{round(100*approved/max(approved+blocked,1))}%"
    top_omit = omitted_values.most_common(1)
    top_text = f"{top_omit[0][0]} ({top_omit[0][1]})" if top_omit else "N/A"

    return avg, ratio, top_text, pd.DataFrame(activity)

def build_value_drift(entries):
    # Aggregate per day per value using sign(score)
    bucket = defaultdict(lambda: defaultdict(lambda: {"Affirmed":0, "Omitted":0, "Violated":0}))
    today = date.today()
    start = today - timedelta(days=365)

    for e in entries:
        ts = norm_ts(e.get("timestamp"))
        if not ts: continue
        d = ts.date()
        if d < start: continue

        for v in e.get("conscience", {}).get("evaluations", []):
            name = v.get("value", "Unknown")
            vs = v.get("score")
            if vs is None: continue
            try:
                s = float(vs)
            except Exception:
                continue
            key = "Affirmed" if s > 0 else ("Omitted" if s == 0 else "Violated")
            bucket[name][d][key] += 1

    rows = []
    for name, days in bucket.items():
        for d, counts in days.items():
            for kind, count in counts.items():
                rows.append({"Date": d, "Value": name, "Type": kind, "Count": count})
    return pd.DataFrame(rows)

# -------------------------------
# PDF report
# -------------------------------
def make_pdf(entry):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter)
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph("<b>SAFi v1 Report</b>", styles["h1"]))
    story.append(Spacer(1, 12))

    story.append(Paragraph("<b>Prompt</b>", styles["h2"]))
    story.append(Paragraph(entry.get("prompt",""), styles["Normal"]))
    story.append(Spacer(1, 8))

    story.append(Paragraph("<b>Intellect</b>", styles["h2"]))
    story.append(Paragraph("<b>Draft</b>", styles["h3"]))
    story.append(Paragraph(entry.get("intellect",{}).get("response",""), styles["Normal"]))
    story.append(Paragraph("<b>Reflection</b>", styles["h3"]))
    story.append(Paragraph(entry.get("intellect",{}).get("reflection",""), styles["Normal"]))
    story.append(Spacer(1, 8))

    story.append(Paragraph("<b>Will</b>", styles["h2"]))
    story.append(Paragraph("<b>Decision</b>", styles["h3"]))
    story.append(Paragraph(entry.get("will",{}).get("decision",""), styles["Normal"]))
    story.append(Paragraph("<b>Reason</b>", styles["h3"]))
    story.append(Paragraph(entry.get("will",{}).get("reflection",""), styles["Normal"]))
    story.append(Spacer(1, 8))

    story.append(Paragraph("<b>Conscience</b>", styles["h2"]))
    evals = entry.get("conscience",{}).get("evaluations",[])
    if evals:
        cols = list(evals[0].keys())
        data = [cols] + [[str(r.get(c,"")) for c in cols] for r in evals]
        t = Table(data)
        t.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,0),colors.grey),
            ('TEXTCOLOR',(0,0),(-1,0),colors.whitesmoke),
            ('GRID',(0,0),(-1,-1),0.5,colors.black),
            ('ALIGN',(0,0),(-1,-1),'CENTER')
        ]))
        story.append(t)
    else:
        story.append(Paragraph("No conscience data.", styles["Normal"]))
    story.append(Spacer(1, 8))

    story.append(Paragraph("<b>Spirit</b>", styles["h2"]))
    story.append(Paragraph(f"Score: {entry.get('spirit',{}).get('score','')}", styles["Normal"]))
    story.append(Paragraph(f"Drift: {entry.get('spirit',{}).get('drift','')}", styles["Normal"]))
    story.append(Paragraph("<b>Note</b>", styles["h3"]))
    story.append(Paragraph(entry.get("spirit",{}).get("reflection",""), styles["Normal"]))
    story.append(Spacer(1, 8))

    out = entry.get("output")
    if out:
        story.append(Paragraph("<b>Final User Output</b>", styles["h2"]))
        story.append(Paragraph(out, styles["Normal"]))

    doc.build(story)
    pdf = buf.getvalue()
    buf.close()
    return pdf

# -------------------------------
# Dashboard
# -------------------------------
st.title("SAFi v1 Dashboard")
st.caption(f"Last updated: {datetime.utcnow().strftime('%b %d, %Y – %H:%M UTC')}")

avg, approval_ratio, top_omit, activity_df = build_summary(logs)

c1, c2, c3, c4 = st.columns(4)
with c1:
    st.markdown("### Avg Spirit Score")
    st.metric(label="1–10", value=avg)
with c2:
    st.markdown("### Approval Ratio")
    st.metric(label="Approved / All", value=approval_ratio)
with c3:
    st.markdown("### Value Set")
    st.write(", ".join(value_set))
with c4:
    st.markdown("### Most Omitted/Violated")
    st.write(top_omit)

st.divider()
st.markdown("### Recent Activity")
st.dataframe(activity_df, use_container_width=True, hide_index=True)

st.sidebar.markdown("---")
st.sidebar.subheader("Value Drift Monitor (last 365 days)")
drift_df = build_value_drift(logs)
if not drift_df.empty:
    for v in value_set:
        vdf = drift_df[drift_df["Value"] == v]
        if vdf.empty:
            continue
        pivot = vdf.pivot_table(index="Date", columns="Type", values="Count", fill_value=0)
        st.sidebar.markdown(f"**{v}**")
        st.sidebar.line_chart(pivot)
else:
    st.sidebar.info("No ledger data in range.")

st.divider()
st.markdown("### View Full Report")
if logs:
    idx = st.number_input("Entry index", min_value=0, max_value=len(logs)-1, step=1, value=0)
    e = logs[idx]

    st.markdown("#### Prompt")
    st.code(e.get("prompt",""), language="markdown")

    cA, cB = st.columns(2)
    with cA:
        st.markdown("#### Intellect Draft")
        st.text_area("Draft", value=e.get("intellect",{}).get("response",""), height=180, key=f"idraft_{idx}")
        st.markdown("#### Will")
        st.text_input("Decision", value=e.get("will",{}).get("decision",""), key=f"willd_{idx}")
        st.text_area("Will Reason", value=e.get("will",{}).get("reflection",""), height=120, key=f"willr_{idx}")
    with cB:
        st.markdown("#### Intellect Reflection")
        st.text_area("Reflection", value=e.get("intellect",{}).get("reflection",""), height=180, key=f"irefl_{idx}")
        st.markdown("#### Spirit")
        st.text_input("Score", value=str(e.get("spirit",{}).get("score","")), key=f"sscore_{idx}")
        st.text_input("Drift", value=str(e.get("spirit",{}).get("drift","")), key=f"sdrift_{idx}")
        st.text_area("Note", value=e.get("spirit",{}).get("reflection",""), height=120, key=f"snote_{idx}")

    st.markdown("#### Conscience Ledger")
    led = e.get("conscience",{}).get("evaluations",[])
    if led:
        st.dataframe(pd.DataFrame(led), use_container_width=True)
    else:
        st.info("No conscience evaluations for this entry.")

    if e.get("output"):
        st.markdown("#### Final User Output")
        st.text_area("Final Output", value=e.get("output",""), height=160, key=f"out_{idx}")

    cD1, cD2 = st.columns(2)
    with cD1:
        pdf_bytes = make_pdf(e)
        st.download_button("Download PDF", data=pdf_bytes, file_name=f"safi_report_{idx}.pdf", mime="application/pdf")
    with cD2:
        st.download_button("Download Raw JSON", data=json.dumps(e, indent=2), file_name=f"safi_raw_{idx}.json", mime="application/json")
else:
    st.warning("No log entries parsed.")
