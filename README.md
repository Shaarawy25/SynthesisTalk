# SynthesisTalk

**SynthesisTalk** is an intelligent research assistant built with a FastAPI backend and a React/Tailwind CSS frontend. It supports:
- Conversational chat with a large language model (LLM)
- Document upload (PDF/DOCX/TXT) and retrieval-augmented generation (RAG)
- Web search, summarization, and extraction tools
- Chain-of-Thought and ReAct reasoning patterns
- Note-taking and research insights

---

## Table of Contents

1. [Project Structure](#project-structure)  
2. [Prerequisites](#prerequisites)  
3. [Backend Setup](#backend-setup)  
4. [Frontend Setup](#frontend-setup)  
5. [Environment Variables](#environment-variables)  
6. [Running the Application](#running-the-application)  
7. [Usage Overview](#usage-overview)  
8. [Additional Notes](#additional-notes)  

---

## Project Structure

```

SYNTHESISTALK/
│
├── backend/
│   ├── **init**.py
│   ├── main.py
│   ├── llm\_integration.py
│   ├── requirements.txt
│   └── .env
│
├── frontend/
│   ├── node\_modules/
│   ├── public/
│   │   └── index.html
│   ├── src/
│   │   ├── App.js
│   │   ├── index.js
│   │   └── index.css
│   ├── package.json
│   ├── package-lock.json
│   ├── postcss.config.js
│   └── tailwind.config.js
│
├── venv/                   ← (example virtual environment folder; not checked into Git)
├── .gitignore
└── README.md

````

- **backend/**  
  - `main.py`  
  - `llm_integration.py`  
  - `requirements.txt`  
  - `.env` (stores the GROQ API key)  

- **frontend/**  
  - `src/` containing `App.js`, `index.js`, and styling  
  - `public/index.html`  
  - Tailwind & PostCSS configuration files  
  - `package.json` / `package-lock.json`  

---

## Prerequisites

1. **Python 3.8+** (to run the FastAPI backend)  
2. **Node.js 16+ & npm** (to run the React frontend)  
3. **GROQ API Key** (for LLM calls)  

---

## Backend Setup

1. **Create (and activate) a Python virtual environment**  
   ```bash
   cd SYNTHESISTALK/backend
   python3 -m venv ../venv
   source ../venv/bin/activate           # On macOS/Linux
   # or
   ../venv/Scripts/activate              # On Windows
````

2. **Install backend dependencies**

   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

3. **Configure environment variables**
   Create (or update) the file `backend/.env` with your GROQ API key:

   ```
   GROQ_API_KEY=your_groq_api_key_goes_here
   ```

---

## Frontend Setup

1. **Install npm dependencies**

   ```bash
   cd SYNTHESISTALK/frontend
   npm install
   ```

2. (Optional) If Tailwind CSS isn’t already built automatically, build once:

   ```bash
   npx tailwindcss build src/index.css -o src/tailwind-output.css
   ```

---

## Environment Variables

* **backend/.env**

  * `GROQ_API_KEY`: Your API key for Groq’s LLM endpoint

No other API keys are required. The web-search functionality does not require additional keys (it uses DuckDuckGo Lite internally).

---

## Running the Application

You need two separate terminal sessions (or tabs):

### 1. Start the Backend

From the project root or the `backend` folder:

```bash
# If not already activated, activate your Python venv:
cd SYNTHESISTALK/backend
source ../venv/bin/activate       # macOS/Linux
# or ../venv/Scripts/activate     # Windows

# Run the FastAPI/Uvicorn server:
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

* The backend will now listen on `http://localhost:8000/`.
* Endpoints:

  * `POST /api/upload` – document upload
  * `POST /api/chat` – chat queries (with optional RAG or reasoning)
  * `POST /api/tools/{tool_name}` – direct tool calls
  * `GET /api/insights/{conversation_id}` – retrieve insights
  * `GET /api/notes/{conversation_id}` – retrieve notes
  * `POST /api/notes/{conversation_id}` – add a note
  * `GET /api/conversations/{conversation_id}` – fetch full chat history
  * `GET /api/documents` – list uploaded docs
  * `DELETE /api/documents/{collection_id}` – delete a doc
  * `GET /api/export/{conversation_id}` – export conversation to JSON/PDF
  * `GET /api/health` – health check
  * `GET /api/stats` – statistics

### 2. Start the Frontend

Open a second terminal, navigate to the frontend folder, and run:

```bash
cd SYNTHESISTALK/frontend
npm start
```

* The React dev server will launch and open `http://localhost:3000` by default.
* If the browser doesn’t open automatically, navigate manually.

---

## Usage Overview

1. **Chat Interface**

   * Type a question or prompt in the input box.
   * Optionally toggle:

     * **Chain of Thought** – uses CoT reasoning in the backend.
     * **ReAct (Tool-Calling)** – triggers reasoning + tool usage (web search, doc extract, etc.).

2. **Upload Documents**

   * Click the paperclip / “Upload” icon.
   * Select a PDF, DOCX, or TXT—Backend will chunk, embed, and store it for RAG.
   * Once uploaded, you can reference that collection when chatting.

3. **Quick Actions**

   * **Web Search** – prefills “Search for information about: …”.
   * **Summarize Docs** – summarization of the first uploaded document.
   * **Extract** – open a modal to ask a query against doc chunks.
   * **Generate Insights** – produces a bullet-point summary of the last \~10 messages.
   * **Take Note** – saves a note tied to the current conversation.

4. **Tabs**

   * **Chat** – main conversation view.
   * **Insights** – see all generated insights in an organized card layout.
   * **Analytics** – simple bar chart counts of Summaries, Extractions, CoT uses, and ReAct uses.
   * **Documents** – view/delete your uploads, Summarize or Extract from each.
   * **Notes** – view/add research notes, each tagged with a category and timestamp.

5. **Context Reset**

   * Typing `/reset` in the chat box will clear only the chat history (document uploads remain).

---

## Additional Notes

* **Context Limit**
  Backend only sends up to `context_limit` most recent turns (default 10) to maintain token budgets.

* **Error Handling**
  If the LLM call fails or web search yields no results, user sees a friendly error in chat.

* **Extensibility**

  * You can add more tools inside `llm_integration.py` under `ToolManager`.
  * To support a different LLM provider, modify the Groq‐based calls in `ReasoningEngine` and `ToolManager`.

* **Deployment**

  * For production, consider using environment variables (e.g., `GROQ_API_KEY`) via a managed secrets store.
  * Serve the React build statically and run Uvicorn + Gunicorn or another WSGI setup.

* **License**
  This project is open for educational purposes (no license file included by default).

---

**Enjoy using SynthesisTalk!**
