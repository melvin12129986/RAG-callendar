# Google Calendar RAG Assistant with BERT Forward Pass & Groq AI Reasoning

A full-stack intelligent calendar web application combining **BERT Transformer forward-pass embeddings**, a **Semantic Hashed Table**, and **Groq AI reasoning**.

---

## 🌟 Key Features

1. **BERT Forward-Pass Embedding Layer (`app/bert_engine.py`)**:
   - Every calendar event is tokenized and passed through a PyTorch BERT Transformer model in a forward pass.
   - Attention-masked mean pooling generates high-dimensional semantic representations.
   - Computes a 64-bit quantized hash fingerprint (SimHash) for table indexing.

2. **Hashed Table & Cosine Similarity Matcher**:
   - Stores calendar events keyed by ID and semantic hash.
   - When a user asks a question, the query undergoes the identical BERT forward pass.
   - Cosine similarity \(\frac{\mathbf{u} \cdot \mathbf{v}}{\|\mathbf{u}\|_2 \|\mathbf{v}\|_2}\) evaluates similarity against all stored calendar records to retrieve top-\(K\) candidates.

3. **Groq AI Reasoning Engine (`app/ai_service.py`)**:
   - Synthesizes user intent, temporal offsets (e.g. "next week", "tomorrow at 3pm"), and retrieved cosine similarity matches using fast Groq models (e.g., `openai/gpt-oss-120b`).
   - Formulates step-by-step reasoning and determines calendar actions:
     - **Create Event**: Parse and schedule new meetings.
     - **Update / Reschedule Event**: Identify the target event via cosine similarity and update start/end times.
     - **Delete / Cancel Event**: Identify target event and cancel schedule.
     - **Calendar QA**: Inquire about upcoming schedules and conflicts.

4. **Google Calendar API Integration (`app/calendar_service.py`)**:
   - Supports Google Calendar OAuth 2.0 (`credentials.json`).
   - Includes automatic realistic in-memory seeded calendar fallback if OAuth credentials are not supplied yet, allowing the app to run immediately out-of-the-box.

5. **Modern Interactive Web UI (`app/static/`)**:
   - Real-time chat interface displaying AI reasoning, cosine similarity scores, and hash fingerprints.
   - Calendar management view with event creation, editing, and deletion.
   - **BERT Hashed Table Inspector**: Inspect internal vector dimensions and semantic hash values.

---

## 🚀 Quickstart

### 1. Requirements & Setup

Make sure Python 3.10+ is installed:
```powershell
pip install -r requirements.txt
```

### 2. Configure Environment (Optional)

Create a `.env` file (or set keys inside the Web UI):
```env
GROQ_API_KEY=your_groq_api_key_here
GROQ_MODEL=openai/gpt-oss-120b
BERT_MODEL_NAME=prajjwal1/bert-tiny
```

### 3. Connect Google Calendar (Optional)
To use real Google Calendar data:
1. Go to [Google Cloud Console](https://console.cloud.google.com/) and enable the **Google Calendar API**.
2. Create an **OAuth 2.0 Client ID** (Desktop Application) and download the JSON as `credentials.json` into this project root.
3. If omitted, the application operates in local simulated mode with seeded realistic events.

### 4. Run the Web Application

```powershell
python run.py
```
Open your browser to: **[http://localhost:8000](http://localhost:8000)**

---

## 📐 Architecture Diagram

```
User Query ──> [BERT Forward Pass] ──> Query Embedding Vector
                                             │
                                    [Cosine Similarity]
                                             │
Events Table ─> [BERT Forward Pass] ─> Hashed Vector Table
                                             │
                                     Top-K Matches
                                             │
                                             ▼
                                  [Groq AI Reasoning API]
                                             │
             ┌───────────────────────────────┴──────────────────────────────┐
             ▼                                                              ▼
    Conversational Answer                                            Action Dispatcher
   (Reasoning + Explanations)                                  (Create / Update / Delete)
                                                                            │
                                                                            ▼
                                                                  [Google Calendar API]
```
