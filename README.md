# Stats Olympiad Ingestion Studio

An end-to-end, multi-agent orchestrator built to ingest raw Word documents (.docx), structure mathematical content, and compile balanced Statistics Olympiad question paper booklets.

## 🌟 Key Features
* **Multimodal Extraction & Solving**: Automatically extracts charts, pie graphs, and complex diagrams from source documents, feeding them to vision LLMs (Qwen2.5-VL / Gemini) to resolve visual math questions.
* **Agentic Workflows**: Uses LangGraph to coordinate clean parsing, 13-topic taxonomy classification, Bloom's difficulty categorization, and ChromaDB vector indexing.
* **Balanced Paper Creator**: Shuffles and scrambles options dynamically while satisfying strict question distribution targets (Easy, Medium, Hard).
* **Word (.docx) & Markdown (.md) Exporters**: Generates beautiful print-ready student booklets and teacher solution keys, rendering math tables and centering images automatically.
* **Ingestion Studio Web UI**: A sleek, dark-mode FastAPI Single Page Application featuring drag-and-drop document uploaders, live Server-Sent Events (SSE) progress indicators, and a download center.

---

## 🛠️ Codebase Architecture

```text
├── data/
│   ├── raw/                   # Raw source .docx files (Level 1 / Level 2)
│   └── templates/             # Markdown template formats for questions
├── db/                        # Local ChromaDB Vector Database storage (git-ignored)
├── src/
│   ├── agents/
│   │   ├── data_processors.py # Prompts and logic for Ingestion, Topic, and Difficulty agents
│   │   ├── evaluator.py       # Booklet Validation Agent
│   │   ├── orchestrator.py    # Main Ingest Orchestration (LangGraph Flow)
│   │   └── paper_creator.py   # QuestionPaperCreatorAgent (scrambling & targeting)
│   ├── static/                # Single Page App frontend (index.html, style.css)
│   ├── classifier.py          # ChatGradio client, JSON escaping, and multimodal image mapping
│   ├── exporter.py            # Docx python-docx insert and Markdown booklet exporters
│   ├── indexer.py             # ChromaDB client & semantic duplicate check constraints
│   ├── parser.py              # Word docx Docling text converter & image extraction
│   └── web_server.py          # FastAPI web server serving UI, SSE progress, and downloads
├── config.env                 # API Keys and Model definitions (git-ignored)
├── generate_paper.py          # Standalone CLI entrypoint
└── requirements.txt           # Python library dependencies
```

---

## 🏗️ System Architecture

The following diagram illustrates the interaction between the frontend dashboard, backend services, multi-agent parsing pipeline, and external APIs/databases:

```mermaid
graph TD
    subgraph Frontend [Client Frontend]
        UI[Single Page App: HTML/CSS/JS]
        SSE[SSE Progress Listener]
        API[REST Forms: Config, Uploads, Compile]
    end

    subgraph Backend [FastAPI Backend Service]
        WS[FastAPI Web Server]
        BG[Background Ingestion Thread]
        PM[SSE Status Manager]
        EXP[Booklet Exporter Engine]
    end

    subgraph Agents [Multi-Agent Core Layer]
        ORC[LangGraph Ingestion Flow]
        P_A[ParsingAgent: Docling Content Extractor]
        T_C[TopicClassificationAgent: 13 Topics]
        D_C[DifficultyClassificationAgent: Bloom's]
        P_CR[QuestionPaperCreator: Shuffle & Scramble]
        E_V[EvaluatorAgent: Balance & Content Overlap]
    end

    subgraph External [Database, Disk & LLMs]
        DB[(ChromaDB Vector Store)]
        FS[(Local Storage: Raw/Output/Cache)]
        LLM[Upstream LLM: Gemini / Ollama / Qwen2.5-VL]
    end

    UI -->|Interactive UI Forms| WS
    WS -->|Spawns Background Task| BG
    BG -->|Intercepts sys.stdout| PM
    PM -->|Server-Sent Events| SSE
    
    BG --> ORC
    ORC --> P_A
    ORC --> T_C
    ORC --> D_C
    
    P_A -->|Saves Extracted Media| FS
    T_C & D_C -->|Structured JSON Schemas| LLM
    ORC -->|Stores Vectors & Embeddings| DB
    
    WS -->|Compiles Booklet Pool| P_CR
    P_CR -->|Queries Question Pools| DB
    P_CR -->|Validates Exam Rules| E_V
    P_CR -->|Calls| EXP
    EXP -->|Saves DOCX & Markdown| FS
    FS -->|Delivers Downloads| UI
```

---

## 🚀 Quick Start Guide

### 1. Installation
Clone the repository and set up a virtual environment:
```bash
git clone https://github.com/ZaheerH-03/stats-olympiad-studio.git
cd stats-olympiad-studio

# Create and activate virtual environment
python -m venv .env
source .env/bin/activate  # On Windows: .env\Scripts\activate

# Install dependencies
pip install -r requirements.txt
pip install fastapi uvicorn python-multipart
```

### 2. Configure Credentials
Create a `config.env` file in the root folder (modeled from configuration settings):
```env
LLM_PROVIDER=gemini
GEMINI_API_KEY=your_gemini_api_key
GEMINI_LLM_MODEL=models/gemini-2.5-flash
EMBEDDING_PROVIDER=local_api
```

### 3. Launch the Web Ingestion Studio
Start the local FastAPI server:
```bash
python src/web_server.py
```
Open **[http://127.0.0.1:8000](http://127.0.0.1:8000)** in your web browser to upload files, configure models, stream ingestion progress, and download booklets!

---

## 🤖 Agentic Ingestion Workflow (LangGraph)

When a question block is processed, it travels through a sequential LangGraph workflow. The diagram below details the state transitions and operations executed within each agent node:

```mermaid
flowchart TD
    startNode([START: graph.invoke]) --> IngestionState

    subgraph IngestionState ["IngestionState (TypedDict)"]
        direction LR
        s1["raw_block"]
        s2["level"]
        s3["filename"]
        s4["external_ans"]
    end

    IngestionState --> parse_raw_node

    subgraph parse_raw_node ["1. ParsingAgent (parse_raw)"]
        direction TB
        p1["Extract embedded chart images"] --> p2["Structure text with LLM"]
        p2 --> p3["Re-append extracted image links"]
        p3 --> p4["Normalize MCQ options & clean statement"]
    end

    parse_raw_node -->|"state updates: statement, options, correct_answer"| classify_topic_node

    subgraph classify_topic_node ["2. TopicClassificationAgent (classify_topic)"]
        direction TB
        t1["Evaluate statement text"] --> t2["Match with 13 math/stats topics"]
        t2 --> t3["Apply synonym normalizations"]
    end

    classify_topic_node -->|"state updates: topic"| classify_difficulty_node

    subgraph classify_difficulty_node ["3. DifficultyClassificationAgent (classify_difficulty)"]
        direction TB
        d1["Evaluate problem complexity"] --> d2["Apply Bloom's Taxonomy criteria"]
        d2 --> d3["Assign: Easy, Medium, or Hard"]
    end

    classify_difficulty_node -->|"state updates: difficulty, explanation"| compile_index_node

    subgraph compile_index_node ["4. Compiler & Indexer (compile_and_index)"]
        direction TB
        c1["Generate SHA-256 statement hash ID"] --> c2["Encrypt answer & explanation (AES Fernet)"]
        c2 --> c3["Cache QuestionModel JSON & index in ChromaDB"]
    end

    compile_index_node --> endNode([END: return final_question])
```

---

## 📄 License
This project is licensed under the MIT License.
