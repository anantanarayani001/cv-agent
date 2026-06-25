"""
CV Standardization Agent — Streamlit Web App
Upload a CV → AI parses it → fills gaps with Q&A → outputs PDF + Word
"""

import streamlit as st
import google.generativeai as genai
import json
import re
import os
import sys
import tempfile
from pathlib import Path
import io

# ── Page config ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="CV Standardization Agent",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Inject CSS ───────────────────────────────────────────────────────────────
st.markdown("""
<style>
  .section-bar {
    background:#111; color:#fff; padding:6px 14px;
    font-weight:700; letter-spacing:2px; margin:14px 0 6px;
    font-size:13px;
  }
  .spike-bar {
    background:#111; color:#fff; padding:8px; text-align:center;
    font-weight:700; margin:8px 0 12px; font-size:13px; letter-spacing:1px;
  }
  .missing-field { border:2px solid #ff4b4b !important; }
  .info-box {
    background:#f0f4ff; border-left:4px solid #4a6cf7;
    padding:10px 14px; margin:8px 0; border-radius:4px;
  }
  h1 { font-size:2rem !important; }
</style>
""", unsafe_allow_html=True)

# ── Constants ────────────────────────────────────────────────────────────────

PARSE_PROMPT = """You are a CV parsing expert. Extract ALL information from this CV text and return it as valid JSON.

Apply these formatting rules while extracting:
- Numbers ≥100,000 → mn/bn (150000 → 0.15 mn, 1200000 → 1.2 mn)
- Numbers 1,000–99,999 → add commas (3000 → 3,000)
- Currency symbols → INR/USD/GBP/EUR (₹ → INR, $ → USD)
- Percentile: use %ile (not % or percentile)
- Use capital Top for ranks: Top 5 %ile, Top 3 ranks
- Work experience dates: Jun'21-Aug'22 format
- Other section years: just the ending year e.g. 2021
- Degree abbreviations: B.Sc.(H), B.Tech., B.Com.(H), MBA, M.Tech., CA, etc.
- School format: "School Name, City (BOARD)" e.g. "DPS, Ranchi (CBSE)"
- All bullets must start with action verbs
- Remove Pvt Ltd / Private Limited from company names
- Single quotes only, no double quotes in content

Return ONLY this JSON schema (no explanation):
{
  "name": "FirstName LastName",
  "gender": "",
  "dob": "YYYY-MM-DD",
  "degree_line": "e.g. B.Tech CSE | 2018-22",
  "spike_points": [],
  "academic_profile": [
    {"degree": "", "institution": "", "score": "", "year": ""}
  ],
  "work_experience": [
    {"company": "", "role": "", "duration": "", "responsibilities": [], "initiatives": [], "achievements": []}
  ],
  "academic_achievements": {
    "academic": [{"text": "", "year": ""}],
    "competitions": [{"text": "", "year": ""}],
    "scholarships": [{"text": "", "year": ""}]
  },
  "positions_of_responsibility": [
    {"organization": "", "role": "", "year": "", "bullets": []}
  ],
  "cip": {
    "certifications": [{"organization": "", "title": "", "duration": "", "bullets": []}],
    "internships": [{"organization": "", "title": "", "duration": "", "bullets": []}],
    "projects": [{"organization": "", "title": "", "duration": "", "bullets": []}]
  },
  "eca": {
    "Sports / Adventure Sports": [{"text": "", "year": ""}],
    "Others": [{"text": "Hobbies: ...", "year": ""}]
  },
  "linkedin": "",
  "email": "",
  "phone": ""
}

ECA category names (use exactly): Debate/ Public Speaking | Sports / Adventure Sports | Management | Cultural | Art & Design | Quizzing | Social Service | Technical | Literature | Others

CV TEXT:
{cv_text}"""

IMPROVE_PROMPT = """You are a CV writing expert. Given this CV bullet point, improve it to:
1. Start with a strong action verb (from: Developed, Led, Built, Drove, Achieved, Launched, Managed, Designed, Reduced, Increased, etc.)
2. Include metrics/numbers wherever possible
3. Keep it concise — single line
4. Apply formatting: numbers ≥100,000 → mn/bn, use INR/USD not symbols

Original bullet: {bullet}
Context: {context}

Return ONLY the improved single-line bullet. No explanation."""

# ── Helpers ──────────────────────────────────────────────────────────────────

def get_api_key() -> str:
    """Get API key from Streamlit secrets or session state."""
    if "GEMINI_API_KEY" in st.secrets:
        return st.secrets["GEMINI_API_KEY"]
    return st.session_state.get("api_key", "")


def extract_text(uploaded_file) -> str:
    """Extract text from uploaded PDF or DOCX."""
    suffix = Path(uploaded_file.name).suffix.lower()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
        f.write(uploaded_file.read())
        tmp_path = f.name

    try:
        if suffix == ".pdf":
            import pdfplumber
            with pdfplumber.open(tmp_path) as pdf:
                return "\n".join(p.extract_text() or "" for p in pdf.pages)
        elif suffix in (".docx", ".doc"):
            from docx import Document
            doc = Document(tmp_path)
            lines = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
            for table in doc.tables:
                for row in table.rows:
                    cells = [c.text.strip() for c in row.cells if c.text.strip()]
                    if cells:
                        lines.append(" | ".join(cells))
            return "\n".join(lines)
        elif suffix in (".txt", ".md"):
            return uploaded_file.read().decode("utf-8", errors="ignore")
        else:
            return ""
    finally:
        os.unlink(tmp_path)


def parse_cv_with_gemini(raw_text: str, api_key: str) -> dict:
    """Send raw CV text to Gemini and get structured JSON back."""
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-1.5-flash')
    prompt = PARSE_PROMPT.replace("{cv_text}", raw_text[:12000])

    response = model.generate_content(prompt)
    content = response.text

    # Extract JSON block
    match = re.search(r"\{[\s\S]*\}", content)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return {}


def find_missing_fields(data: dict) -> list[tuple[str, str]]:
    """Return list of (field_key, question) for missing required fields."""
    gaps = []
    if not data.get("name") or len(data["name"].split()) > 2:
        gaps.append(("name", "Full name (FirstName LastName — max 2 parts):"))
    if not data.get("gender"):
        gaps.append(("gender", "Gender (Female / Male / Non-binary / Prefer not to say):"))
    if not data.get("dob"):
        gaps.append(("dob", "Date of birth (YYYY-MM-DD, e.g. 2001-09-18):"))

    spikes = data.get("spike_points", [])
    if len(spikes) < 4:
        for i in range(len(spikes), 4):
            gaps.append((f"spike_{i}", f"Spike Point {i+1} (1–3 words, Pascal Case, e.g. 'National Rank 2'):"))

    if not data.get("academic_profile"):
        gaps.append(("ap_note", "⚠ No academic qualifications found — please add them below."))

    eca = data.get("eca", {})
    others = eca.get("Others", [])
    has_hobbies = any("hobbies" in str(p).lower() for p in others)
    if not has_hobbies:
        gaps.append(("hobbies", "Hobbies (required as last line, e.g. 'Playing Volleyball, Reading, Chess'):"))

    if not data.get("linkedin") and not data.get("email"):
        gaps.append(("linkedin", "LinkedIn profile URL (https://linkedin.com/in/yourhandle):"))
        gaps.append(("email", "Email address:"))

    return gaps


def generate_pdf(data: dict) -> bytes:
    """Generate standardized CV as PDF bytes."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as f:
        tmp_path = f.name

    # Import here to avoid circular issues
    sys.path.insert(0, os.path.dirname(__file__))
    from cv_generator import CV

    cv = CV(data, tmp_path)
    cv.generate()

    with open(tmp_path, "rb") as f:
        pdf_bytes = f.read()
    os.unlink(tmp_path)
    return pdf_bytes


def generate_docx(data: dict) -> bytes:
    """Generate standardized CV as Word .docx bytes."""
    sys.path.insert(0, os.path.dirname(__file__))
    from cv_docx_generator import generate_cv_docx
    return generate_cv_docx(data)


# ── Session state init ───────────────────────────────────────────────────────

def init_state():
    defaults = {
        "stage": "upload",   # upload → review → download
        "raw_text": "",
        "cv_data": {},
        "api_key": "",
        "filename": "",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ── SIDEBAR ──────────────────────────────────────────────────────────────────

def sidebar():
    with st.sidebar:
        st.title("⚙️ Settings")

        # API key (only show if not in secrets)
        if "GEMINI_API_KEY" not in st.secrets:
            st.markdown("**Google Gemini API Key**")
            key = st.text_input(
                "Enter your Google AI Studio key",
                type="password",
                value=st.session_state.api_key,
                placeholder="AIza...",
                help="Get a free key at aistudio.google.com",
            )
            st.session_state.api_key = key
            if not key:
                st.warning("🔑 API key required to process CVs")
                st.markdown("[Get a free API key →](https://aistudio.google.com/)")
        else:
            st.success("✅ API key configured")

        st.divider()
        st.markdown("**How it works**")
        st.markdown("""
1. 📤 Upload your CV (PDF or Word)
2. 🤖 AI extracts all details
3. ✏️ Fill in any missing info
4. 📥 Download your standardized CV
        """)

        st.divider()
        st.markdown("**Output format**")
        st.markdown("✅ PDF\n✅ Word (.docx)")

        if st.session_state.stage != "upload":
            st.divider()
            if st.button("🔄 Start Over", use_container_width=True):
                for k in ["stage", "raw_text", "cv_data", "filename"]:
                    st.session_state[k] = "" if isinstance(st.session_state[k], str) else {} if isinstance(st.session_state[k], dict) else "upload"
                st.session_state.stage = "upload"
                st.rerun()


# ── STAGE 1: UPLOAD ──────────────────────────────────────────────────────────

def stage_upload():
    st.title("📄 CV Standardization Agent")
    st.markdown("Upload your CV and get a clean, standardized version — correctly formatted, properly structured, ready to submit.")

    col1, col2 = st.columns([2, 1])
    with col1:
        uploaded = st.file_uploader(
            "Upload your CV",
            type=["pdf", "docx", "doc", "txt"],
            help="Accepted: PDF, Word (.docx), or plain text",
        )

        if uploaded:
            st.session_state.filename = uploaded.name
            api_key = get_api_key()

            if not api_key:
                st.error("Please enter your Google Gemini API key in the sidebar first.")
                return

            if st.button("🚀 Process CV", type="primary", use_container_width=True):
                with st.spinner("Extracting text from your CV..."):
                    raw = extract_text(uploaded)

                if not raw.strip():
                    st.error("Could not extract text from this file. Please try a PDF or DOCX.")
                    return

                st.session_state.raw_text = raw

                with st.spinner("AI is reading and structuring your CV..."):
                    try:
                        parsed = parse_cv_with_gemini(raw, api_key)
                    except Exception as e:
                        if "API_KEY" in str(e) or "invalid" in str(e).lower():
                            st.error("❌ Invalid API key. Please check your key in the sidebar.")
                        else:
                            st.error(f"❌ Error: {e}")
                        return

                if not parsed:
                    st.error("Could not parse the CV. Please ensure it has readable text.")
                    return

                st.session_state.cv_data = parsed
                st.session_state.stage = "review"
                st.rerun()

    with col2:
        st.markdown("""
<div class="info-box">
<b>What gets standardized:</b><br>
• Numbers → 0.5 mn, 3,000<br>
• Currency → INR, USD<br>
• Percentile → %ile<br>
• Dates → Jun'22, 2022-23<br>
• Degrees → B.Sc.(H), B.Tech.<br>
• Schools → Name, City (Board)<br>
• Bullets → action verbs<br>
• No blank gaps on the page
</div>
        """, unsafe_allow_html=True)

    st.divider()
    st.markdown("#### Or start from scratch")
    if st.button("✍️ Build CV from scratch (no upload)", use_container_width=False):
        st.session_state.cv_data = {
            "name": "", "gender": "", "dob": "", "degree_line": "",
            "spike_points": [], "academic_profile": [], "work_experience": [],
            "academic_achievements": {"academic": [], "competitions": [], "scholarships": []},
            "positions_of_responsibility": [], "cip": {"certifications": [], "internships": [], "projects": []},
            "eca": {}, "linkedin": "", "email": "", "phone": ""
        }
        st.session_state.stage = "review"
        st.rerun()


# ── STAGE 2: REVIEW ───────────────────────────────────────────────────────────

def stage_review():
    st.title("✏️ Review & Complete Your CV")
    if st.session_state.filename:
        st.caption(f"Source file: {st.session_state.filename}")

    data = st.session_state.cv_data
    missing = find_missing_fields(data)

    if missing:
        st.warning(f"⚠️ {len(missing)} required field(s) need your input before generating.")

    # ── Basic info ───────────────────────────────────────────────────────────
    with st.expander("👤 Personal Details", expanded=bool(missing)):
        c1, c2, c3 = st.columns(3)
        with c1:
            data["name"] = st.text_input(
                "Full Name *",
                value=data.get("name", ""),
                placeholder="FirstName LastName",
                help="Exactly 2 parts. If no surname, use 'NA'",
            )
        with c2:
            data["gender"] = st.text_input(
                "Gender *",
                value=data.get("gender", ""),
                placeholder="Female / Male / Non-binary",
            )
        with c3:
            data["dob"] = st.text_input(
                "Date of Birth *",
                value=data.get("dob", ""),
                placeholder="YYYY-MM-DD",
            )
        data["degree_line"] = st.text_input(
            "Degree / Info line (shown under name)",
            value=data.get("degree_line", ""),
            placeholder="e.g. B.Tech CSE | 2018-22",
        )

    # ── Spike points ─────────────────────────────────────────────────────────
    with st.expander("⚡ Spike Points (4 required)", expanded=len(data.get("spike_points", [])) < 4):
        st.caption("Exactly 4 highlights, Pascal Case, max 3 words each. Cover: Academics | Work | Positions | ECA")
        spikes = data.get("spike_points", ["", "", "", ""])
        while len(spikes) < 4:
            spikes.append("")
        cols = st.columns(4)
        for i, col in enumerate(cols):
            with col:
                spikes[i] = st.text_input(f"Spike {i+1} *", value=spikes[i], placeholder=["National Rank 2", "Google Intern", "Tech Council Head", "Gold Volleyball"][i])
        data["spike_points"] = [s.strip() for s in spikes if s.strip()]

    # ── Academic profile ─────────────────────────────────────────────────────
    with st.expander("🎓 Academic Profile", expanded=not data.get("academic_profile")):
        st.caption("List from most recent to oldest. Include postgrad (if any), graduation, Class XII, Class X.")
        ap = data.get("academic_profile", [])

        # Show existing
        updated_ap = []
        for i, e in enumerate(ap):
            st.markdown(f"**Entry {i+1}**")
            c1, c2, c3, c4 = st.columns([2, 3, 2, 1.5])
            with c1:
                deg = st.text_input("Degree", value=e.get("degree",""), key=f"ap_deg_{i}", placeholder="B.Tech CSE / Class XII")
            with c2:
                inst = st.text_input("Institution", value=e.get("institution",""), key=f"ap_inst_{i}", placeholder="IIT Bombay or DPS, City (CBSE)")
            with c3:
                score = st.text_input("Score", value=e.get("score",""), key=f"ap_score_{i}", placeholder="9.12/10.00 or 95.40%")
            with c4:
                year = st.text_input("Year", value=e.get("year",""), key=f"ap_year_{i}", placeholder="2018-22")
            updated_ap.append({"degree": deg, "institution": inst, "score": score, "year": year})

        # Add new entry
        if st.button("+ Add qualification", key="add_ap"):
            updated_ap.append({"degree": "", "institution": "", "score": "", "year": ""})
        data["academic_profile"] = [e for e in updated_ap if e["degree"] or e["institution"]]

    # ── Work experience ───────────────────────────────────────────────────────
    with st.expander("💼 Work Experience"):
        st.caption("Include full-time jobs and internships. Reverse chronological order.")
        we = data.get("work_experience", [])
        updated_we = []
        for i, e in enumerate(we):
            st.markdown(f"**{e.get('company', f'Entry {i+1}')}**")
            c1, c2, c3 = st.columns([2, 3, 1.5])
            with c1:
                company = st.text_input("Company", value=e.get("company",""), key=f"we_co_{i}")
            with c2:
                role = st.text_input("Role / Designation", value=e.get("role",""), key=f"we_role_{i}", placeholder="Intern - Strategy, Growth")
            with c3:
                dur = st.text_input("Duration", value=e.get("duration",""), key=f"we_dur_{i}", placeholder="Jun'22-Aug'22")

            resp_text = st.text_area("Responsibilities (one per line)", value="\n".join(e.get("responsibilities",[])), key=f"we_resp_{i}", height=80)
            init_text = st.text_area("Initiatives (one per line)", value="\n".join(e.get("initiatives",[])), key=f"we_init_{i}", height=60)
            ach_text  = st.text_area("Achievements (one per line)", value="\n".join(e.get("achievements",[])), key=f"we_ach_{i}", height=60)

            updated_we.append({
                "company": company, "role": role, "duration": dur,
                "responsibilities": [l.strip() for l in resp_text.splitlines() if l.strip()],
                "initiatives":      [l.strip() for l in init_text.splitlines() if l.strip()],
                "achievements":     [l.strip() for l in ach_text.splitlines() if l.strip()],
            })
            st.divider()

        if st.button("+ Add work experience", key="add_we"):
            updated_we.append({"company":"","role":"","duration":"","responsibilities":[],"initiatives":[],"achievements":[]})
        data["work_experience"] = [e for e in updated_we if e["company"]]

    # ── Academic achievements ─────────────────────────────────────────────────
    with st.expander("🏆 Academic Achievements"):
        aa = data.get("academic_achievements", {"academic":[],"competitions":[],"scholarships":[]})
        for cat in ("academic", "competitions", "scholarships"):
            st.markdown(f"**{cat.title()}** (one per line, with year at end if desired)")
            items = aa.get(cat, [])
            existing = "\n".join(
                f"{p.get('text','')} | {p.get('year','')}" if isinstance(p, dict) else str(p)
                for p in items
            )
            new_text = st.text_area(f"{cat}", value=existing, key=f"aa_{cat}", height=80,
                                    placeholder="Secured Rank 1 in JEE Advanced among 1,50,000 candidates | 2021")
            parsed_items = []
            for line in new_text.splitlines():
                line = line.strip()
                if not line: continue
                if " | " in line:
                    parts = line.rsplit(" | ", 1)
                    parsed_items.append({"text": parts[0].strip(), "year": parts[1].strip()})
                else:
                    parsed_items.append({"text": line, "year": ""})
            aa[cat] = parsed_items
        data["academic_achievements"] = aa

    # ── Positions of responsibility ──────────────────────────────────────────
    with st.expander("👥 Positions of Responsibility"):
        por = data.get("positions_of_responsibility", [])
        updated_por = []
        for i, e in enumerate(por):
            st.markdown(f"**{e.get('organization', f'POR {i+1}')}**")
            c1, c2, c3 = st.columns([2, 3, 1])
            with c1:
                org = st.text_input("Organization", value=e.get("organization",""), key=f"por_org_{i}")
            with c2:
                role = st.text_input("Role", value=e.get("role",""), key=f"por_role_{i}", placeholder="Vice President, Science Society")
            with c3:
                year = st.text_input("Year", value=str(e.get("year","")), key=f"por_year_{i}")
            bullets_text = st.text_area("Bullets (one per line)", value="\n".join(e.get("bullets",[])), key=f"por_b_{i}", height=80)
            updated_por.append({
                "organization": org, "role": role, "year": year,
                "bullets": [l.strip() for l in bullets_text.splitlines() if l.strip()]
            })
            st.divider()
        if st.button("+ Add POR", key="add_por"):
            updated_por.append({"organization":"","role":"","year":"","bullets":[]})
        data["positions_of_responsibility"] = [e for e in updated_por if e["organization"]]

    # ── CIP ──────────────────────────────────────────────────────────────────
    with st.expander("📋 Certifications, Internships & Projects"):
        cip = data.get("cip", {"certifications":[],"internships":[],"projects":[]})
        for cat in ("certifications", "internships", "projects"):
            st.markdown(f"**{cat.title()}**")
            items = cip.get(cat, [])
            updated = []
            for i, e in enumerate(items):
                c1, c2, c3 = st.columns([2, 3, 1.5])
                with c1:
                    org = st.text_input("Org/Platform", value=e.get("organization",""), key=f"cip_{cat}_org_{i}")
                with c2:
                    title = st.text_input("Title", value=e.get("title",""), key=f"cip_{cat}_title_{i}",
                                          placeholder=f"{'Certification' if cat=='certifications' else 'Intern' if cat=='internships' else 'Project'} - Name, Dept")
                with c3:
                    dur = st.text_input("Duration", value=e.get("duration",""), key=f"cip_{cat}_dur_{i}")
                bullets_text = st.text_area("Bullets", value="\n".join(e.get("bullets",[])), key=f"cip_{cat}_b_{i}", height=60)
                updated.append({
                    "organization": org, "title": title, "duration": dur,
                    "bullets": [l.strip() for l in bullets_text.splitlines() if l.strip()]
                })
            if st.button(f"+ Add {cat[:-1]}", key=f"add_cip_{cat}"):
                updated.append({"organization":"","title":"","duration":"","bullets":[]})
            cip[cat] = [e for e in updated if e["organization"] or e["title"]]
            st.divider()
        data["cip"] = cip

    # ── ECA ──────────────────────────────────────────────────────────────────
    with st.expander("🏅 Extra-Curricular Activities"):
        ECA_CATS = [
            "Debate/ Public Speaking", "Sports / Adventure Sports", "Management",
            "Cultural", "Art & Design", "Quizzing", "Social Service",
            "Technical", "Literature", "Others",
        ]
        eca = data.get("eca", {})
        updated_eca = {}

        for cat in ECA_CATS:
            items = eca.get(cat, [])
            existing = "\n".join(
                f"{p.get('text','')} | {p.get('year','')}" if isinstance(p, dict) else str(p)
                for p in items
            )
            val = st.text_area(cat, value=existing, key=f"eca_{cat}", height=60,
                               placeholder=("Hobbies: Reading, Volleyball, Chess" if cat == "Others"
                                            else f"e.g. Secured Gold at Inter-College Meet | 2022"))
            parsed = []
            for line in val.splitlines():
                line = line.strip()
                if not line: continue
                if " | " in line:
                    parts = line.rsplit(" | ", 1)
                    parsed.append({"text": parts[0].strip(), "year": parts[1].strip()})
                else:
                    parsed.append({"text": line, "year": ""})
            if parsed:
                updated_eca[cat] = parsed
        data["eca"] = updated_eca

    # ── Contact ──────────────────────────────────────────────────────────────
    with st.expander("🔗 Contact & Links", expanded=not data.get("linkedin")):
        c1, c2, c3 = st.columns(3)
        with c1:
            data["linkedin"] = st.text_input("LinkedIn URL", value=data.get("linkedin",""),
                                              placeholder="https://linkedin.com/in/yourhandle")
        with c2:
            data["email"] = st.text_input("Email", value=data.get("email",""))
        with c3:
            data["phone"] = st.text_input("Phone", value=data.get("phone",""), placeholder="+91 XXXXXXXXXX")

    # ── Validate & Generate ──────────────────────────────────────────────────
    st.divider()

    missing_now = find_missing_fields(data)
    if missing_now:
        items_str = "\n".join(f"• {q}" for _, q in missing_now)
        st.warning(f"Still missing:\n{items_str}")

    col_a, col_b = st.columns([1, 3])
    with col_a:
        if st.button("✅ Generate My CV", type="primary", use_container_width=True):
            st.session_state.cv_data = data
            st.session_state.stage = "download"
            st.rerun()


# ── STAGE 3: DOWNLOAD ─────────────────────────────────────────────────────────

def stage_download():
    st.title("🎉 Your Standardized CV is Ready!")

    data = st.session_state.cv_data
    name = data.get("name", "CV")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### 📥 Download")

        # PDF
        with st.spinner("Generating PDF..."):
            try:
                pdf_bytes = generate_pdf(data)
                st.download_button(
                    label="⬇️ Download PDF",
                    data=pdf_bytes,
                    file_name=f"{name.replace(' ', '_')}_CV.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                    type="primary",
                )
            except Exception as e:
                st.error(f"PDF error: {e}")

        st.markdown("")

        # Word
        with st.spinner("Generating Word document..."):
            try:
                docx_bytes = generate_docx(data)
                st.download_button(
                    label="⬇️ Download Word (.docx)",
                    data=docx_bytes,
                    file_name=f"{name.replace(' ', '_')}_CV.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    use_container_width=True,
                )
            except Exception as e:
                st.error(f"Word error: {e}")

        st.markdown("")
        if st.button("✏️ Edit CV", use_container_width=True):
            st.session_state.stage = "review"
            st.rerun()

    with col2:
        st.markdown("### 📋 CV Summary")
        spikes = data.get("spike_points", [])
        if spikes:
            st.markdown(f"""<div class="spike-bar">{' &nbsp;|&nbsp; '.join(spikes)}</div>""",
                        unsafe_allow_html=True)

        st.markdown(f"**Name:** {data.get('name','')}")
        ap = data.get("academic_profile", [])
        if ap:
            st.markdown(f"**Qualifications:** {len(ap)} entries")
            for e in ap:
                st.markdown(f"  • {e.get('degree','')} — {e.get('institution','')} — {e.get('score','')} ({e.get('year','')})")

        we = data.get("work_experience", [])
        if we:
            st.markdown(f"**Work/Internships:** {len(we)} entries")

        por = data.get("positions_of_responsibility", [])
        if por:
            st.markdown(f"**PORs:** {len(por)} entries")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    init_state()
    sidebar()

    if st.session_state.stage == "upload":
        stage_upload()
    elif st.session_state.stage == "review":
        stage_review()
    elif st.session_state.stage == "download":
        stage_download()


if __name__ == "__main__":
    main()
