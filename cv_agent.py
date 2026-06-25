#!/usr/bin/env python3
"""
cv_agent.py — CV Standardization Agent
---
This script is the orchestrator. It:
1. Accepts a raw CV file path (PDF/DOCX) or a pre-filled JSON data file
2. Parses raw text from the CV
3. Structures the data into the standard schema
4. Identifies gaps and prints questions to ask the person
5. Calls cv_generator.py to produce the final PDF

Usage:
  python cv_agent.py --parse <cv_file>       → Extract & print raw text
  python cv_agent.py --check <data.json>     → Validate & list missing fields
  python cv_agent.py --generate <data.json> <output.pdf>  → Generate PDF

The Claude agent in this project handles the interactive conversation.
This script is the technical backbone.
"""

import sys, os, json, re
from cv_parser import extract

# ── Schema definition ────────────────────────────────────────────────────────

EMPTY_SCHEMA = {
    "name":          "",      # "FirstName LastName" — exactly 2 parts
    "gender":        "",      # "Male" / "Female" / "Non-binary" / etc.
    "dob":           "",      # "YYYY-MM-DD"
    "degree_line":   "",      # Optional tagline under name, e.g. "B.Tech CSE | 2019-23"
    "spike_points":  [],      # Exactly 4 strings, max 3 words each, Pascal Case

    "academic_profile": [
        # {
        #   "degree":      "B.Sc.(H)",          ← Standardized abbreviation
        #   "institution": "Ramjas College, University of Delhi",
        #   "score":       "8.49/10.00",        ← 2 decimal places
        #   "year":        "2020-23"             ← YYYY-YY format
        # }
    ],

    "work_experience": [
        # {
        #   "company":         "Urban Company",
        #   "role":            "Intern - Strategy, Business Dev",
        #   "duration":        "Jan'23-Apr'23",   ← MMM'YY format
        #   "responsibilities": [],
        #   "initiatives":     [],
        #   "achievements":    []
        # }
    ],

    "academic_achievements": {
        "academic":     [],   # [{"text": "...", "year": "2020"}, ...]
        "competitions": [],
        "scholarships": []
    },

    "positions_of_responsibility": [
        # {
        #   "organization": "Ramjas College",
        #   "role":         "Vice President, Ramjas Zoological Society",
        #   "year":         "2022",
        #   "bullets":      ["Hosted 8+ webinars for 300+ attendees ..."]
        # }
    ],

    "cip": {
        "certifications": [],
        # {
        #   "organization": "Coursera",
        #   "title":        "Certification - Machine Learning, Stanford University",
        #   "duration":     "",
        #   "bullets":      []
        # }
        "internships": [],
        # {
        #   "organization": "Google",
        #   "title":        "Intern - Product Management, Growth",
        #   "duration":     "May'23-Jul'23",
        #   "bullets":      []
        # }
        "projects": []
        # {
        #   "organization": "IIT Delhi",
        #   "title":        "Project - Supply Chain Optimization, Operations",
        #   "duration":     "",
        #   "bullets":      []
        # }
    },

    "eca": {
        # Keys must be one of these categories (or a custom justified one):
        # "Debate/ Public Speaking" | "Sports / Adventure Sports" | "Management"
        # "Cultural" | "Art & Design" | "Quizzing" | "Social Service"
        # "Technical" | "Literature" | "Others"
        #
        # Each value: [{"text": "...", "year": "2021"}, ...]
        # "Others" MUST include Hobbies as the last item:
        #   {"text": "Hobbies: Reading, Volleyball, Anime", "year": ""}
    },

    "linkedin": "",   # Full URL: https://linkedin.com/in/handle
    "email":    "",
    "phone":    ""    # "+91 XXXXXXXXXX"
}


# ── Validation & gap detection ───────────────────────────────────────────────

def validate(data: dict) -> list:
    """
    Returns a list of (field, question) tuples for anything missing or unclear.
    Questions are what the agent should ask the person.
    """
    gaps = []

    # ── Name ──────────────────────────────────────────────────────────────
    name = data.get('name', '').strip()
    if not name:
        gaps.append(('name', "What is your full name? (I'll format it as FirstName LastName — exactly two parts. If you have no last name, I'll use 'NA')"))
    elif len(name.split()) > 2:
        gaps.append(('name', f"Your name '{name}' has more than 2 parts. Which two should I use as First and Last name?"))

    # ── Gender & DOB ──────────────────────────────────────────────────────
    if not data.get('gender'):
        gaps.append(('gender', "What is your gender? (e.g. Female / Male / Non-binary / Prefer not to say)"))
    if not data.get('dob'):
        gaps.append(('dob', "What is your date of birth? (Format: YYYY-MM-DD, e.g. 2001-09-18)"))

    # ── Spike points ──────────────────────────────────────────────────────
    spikes = data.get('spike_points', [])
    if len(spikes) < 4:
        gaps.append(('spike_points',
            "I need exactly 4 spike points (short 1–3 word highlights shown as your headline). "
            "These should cover one achievement each from: Academic Achievements, Work/Internships, "
            "Positions of Responsibility, and Extra-Curriculars. "
            "What are your 4 strongest highlights? (e.g. 'National Rank 1', 'Gold Volleyball', 'Airtel Winner')"))
    elif any(len(s.split()) > 3 for s in spikes):
        long = [s for s in spikes if len(s.split()) > 3]
        gaps.append(('spike_points',
            f"These spike points are too long (max 3 words each): {long}. How would you shorten them?"))

    # ── Academic profile ──────────────────────────────────────────────────
    ap = data.get('academic_profile', [])
    if not ap:
        gaps.append(('academic_profile',
            "Please share your academic qualifications. For each one, I need: "
            "Degree (e.g. B.Tech, Class XII, Class X), Institution name & city, "
            "Score (percentage or GPA/10), and the year(s) (e.g. 2019-23 or just 2020)."))
    else:
        for i, e in enumerate(ap):
            if not e.get('degree'):
                gaps.append((f'academic_profile[{i}].degree',
                    f"What degree/qualification is entry #{i+1} in your academic profile? "
                    f"(e.g. B.Tech, B.Sc.(H), Class XII, Class X, MBA)"))
            if not e.get('institution'):
                gaps.append((f'academic_profile[{i}].institution',
                    f"What institution did you attend for '{e.get('degree', f'entry #{i+1}')}'? "
                    f"Include city and board if school (e.g. 'DPS, Ranchi (CBSE)')"))
            if not e.get('score'):
                gaps.append((f'academic_profile[{i}].score',
                    f"What was your score/GPA for '{e.get('degree', f'entry #{i+1}')}'? "
                    f"(Format: 8.49/10.00 for GPA, or 95.40% for percentage — 2 decimal places)"))
            if not e.get('year'):
                gaps.append((f'academic_profile[{i}].year',
                    f"What years did you attend for '{e.get('degree', f'entry #{i+1}')}'? "
                    f"(Format: 2020-23 for multi-year, or just 2020 for single year)"))

    # ── Work experience ───────────────────────────────────────────────────
    for i, exp in enumerate(data.get('work_experience', [])):
        if not exp.get('company'):
            gaps.append((f'work_experience[{i}].company',
                f"What is the company name for work experience #{i+1}? "
                f"(Drop 'Pvt Ltd' / 'Private Limited' suffixes. For conglomerates, include the specific BU — e.g. 'Reliance Jio')"))
        if not exp.get('duration'):
            gaps.append((f'work_experience[{i}].duration',
                f"What were the start and end dates for your role at {exp.get('company', f'company #{i+1}')}? "
                f"(Format: Jun'21-Aug'23)"))
        if not exp.get('responsibilities') and not exp.get('achievements'):
            gaps.append((f'work_experience[{i}].bullets',
                f"What were your responsibilities and key achievements at {exp.get('company', f'company #{i+1}')}? "
                f"Please share as bullet points starting with action verbs. "
                f"Include numbers/metrics wherever possible (e.g. 'Led a team of 12', 'Grew revenue by INR 0.5 mn')"))

    # ── Positions of responsibility ───────────────────────────────────────
    for i, por in enumerate(data.get('positions_of_responsibility', [])):
        if not por.get('role'):
            gaps.append((f'por[{i}].role',
                f"What was your role/title for POR #{i+1} at {por.get('organization', 'the organization')}?"))
        if not por.get('bullets'):
            gaps.append((f'por[{i}].bullets',
                f"What did you do as {por.get('role', f'POR #{i+1}')} at {por.get('organization', 'the organization')}? "
                f"(2–3 bullet points with impact/numbers)"))

    # ── CIP ───────────────────────────────────────────────────────────────
    for cat in ('certifications', 'internships', 'projects'):
        for i, e in enumerate(data.get('cip', {}).get(cat, [])):
            if not e.get('bullets'):
                gaps.append((f'cip.{cat}[{i}].bullets',
                    f"What were the key tasks/outcomes for your {cat[:-1]} at {e.get('organization', f'org #{i+1}')}? "
                    f"Please share as bullet points with action verbs and numbers."))

    # ── ECA ───────────────────────────────────────────────────────────────
    eca = data.get('eca', {})
    if not eca:
        gaps.append(('eca',
            "Do you have any extra-curricular activities to add? "
            "These can include: sports, debate, cultural activities, social service, literature, quizzing, etc. "
            "For each, share a one-line description with the year."))
    else:
        others = eca.get('Others', [])
        has_hobbies = any('hobbies' in p.get('text', '').lower()
                          for p in others if isinstance(p, dict))
        if not has_hobbies:
            gaps.append(('eca.Others.Hobbies',
                "What are your hobbies? This is required as the last line of the CV "
                "(e.g. 'Hobbies: Reading, Volleyball, Watching anime')"))

    # ── Contact ───────────────────────────────────────────────────────────
    if not data.get('linkedin'):
        gaps.append(('linkedin', "What is your LinkedIn profile URL? (e.g. https://linkedin.com/in/yourhandle)"))
    if not data.get('email') and not data.get('phone'):
        gaps.append(('contact',
            "Please share your email address and/or phone number for the CV footer. "
            "(Phone format: +91 XXXXXXXXXX)"))

    return gaps


# ── Formatting rules checker ─────────────────────────────────────────────────

def check_formatting(data: dict) -> list:
    """
    Scan all text fields and return warnings about formatting violations.
    """
    warnings = []
    all_texts = []

    def collect_texts(obj, path=''):
        if isinstance(obj, str):
            all_texts.append((path, obj))
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                collect_texts(item, f'{path}[{i}]')
        elif isinstance(obj, dict):
            for k, v in obj.items():
                collect_texts(v, f'{path}.{k}')

    collect_texts(data)

    for path, text in all_texts:
        # Currency symbols
        if any(sym in text for sym in ['₹', '$', '£', '€']):
            warnings.append(f"{path}: Use INR/USD/GBP/EUR instead of currency symbols → '{text[:60]}'")
        # Large numbers without mn/bn
        nums = re.findall(r'\b\d{6,}\b', text.replace(',', ''))
        for n in nums:
            if int(n) >= 100000:
                warnings.append(f"{path}: Number {n} should use mn/bn notation → '{text[:60]}'")
        # Percentile written as %
        if re.search(r'\d+\s*%(?!ile)', text):
            warnings.append(f"{path}: Use '%ile' for percentile → '{text[:60]}'")
        # Double quotes
        if '"' in text:
            warnings.append(f"{path}: Replace double quotes with single quotes → '{text[:60]}'")
        # Lowercase 'top' when used as rank
        if re.search(r'\btop\b', text):
            warnings.append(f"{path}: 'top' should be 'Top' (uppercase T) when used as rank → '{text[:60]}'")

    return warnings


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    mode = sys.argv[1]

    if mode == '--parse' and len(sys.argv) >= 3:
        text = extract(sys.argv[2])
        print(text)

    elif mode == '--check' and len(sys.argv) >= 3:
        with open(sys.argv[2], encoding='utf-8') as f:
            data = json.load(f)
        gaps = validate(data)
        warnings = check_formatting(data)
        if gaps:
            print("=== MISSING / UNCLEAR FIELDS ===")
            for field, question in gaps:
                print(f"\n[{field}]\n  → {question}")
        if warnings:
            print("\n=== FORMATTING WARNINGS ===")
            for w in warnings:
                print(f"  ⚠ {w}")
        if not gaps and not warnings:
            print("✓ Data looks complete and well-formatted.")

    elif mode == '--generate' and len(sys.argv) >= 4:
        from cv_generator import CV
        with open(sys.argv[2], encoding='utf-8') as f:
            data = json.load(f)
        cv = CV(data, sys.argv[3])
        name = cv.generate()
        print(f"✓ Generated: {sys.argv[3]}")

    else:
        print(__doc__)
        sys.exit(1)


if __name__ == '__main__':
    main()
