# How to Deploy the CV Agent (5 minutes)

## Step 1 — Get a Free Groq API Key

1. Go to **https://console.groq.com/**
2. Sign in / sign up (free)
3. Click **API Keys** → **Create API key**
4. Copy the key (starts with `gsk_...`)

Free tier: **14,400 requests/day** at zero cost.

---

## Step 2 — Put the files on GitHub

1. Go to **https://github.com/new** → create a new **public** repository (name it `cv-agent` or anything)
2. Upload these files to the repo:
   - `app.py`
   - `cv_generator.py`
   - `cv_docx_generator.py`
   - `cv_parser.py`
   - `cv_agent.py`
   - `requirements.txt`
3. Click **Commit changes**

---

## Step 3 — Deploy on Render.com (free)

1. Go to **https://render.com/** and sign in with GitHub
2. Click **New** → **Web Service**
3. Connect your GitHub repo
4. Set:
   - **Runtime**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `streamlit run app.py --server.port $PORT --server.address 0.0.0.0`
5. Under **Environment** → add:
   - **Key**: `GROQ_API_KEY`
   - **Value**: your `gsk_...` key
6. Click **Deploy Web Service**

---

## Step 4 — Share

You'll get a URL like:
**`https://cv-agent-xxxx.onrender.com`**

Share this with anyone. They upload a CV, answer a few questions, and download a standardized version — free, no install needed.

---

## Run locally (optional)

```bash
pip install -r requirements.txt
GROQ_API_KEY=gsk_your_key streamlit run app.py
```

Then open http://localhost:8501 in your browser.
