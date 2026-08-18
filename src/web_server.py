import os
import sys
import glob
import json
import re
import asyncio
import shutil
import concurrent.futures
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, UploadFile, File, Query, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv

# Define workspace directories
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(PROJECT_DIR)

# Reload variables from config.env
load_dotenv(os.path.join(PROJECT_DIR, "config.env"), override=True)

app = FastAPI(title="Statscomp CRRAO Web Server")

# Serve UI static assets
os.makedirs(os.path.join(PROJECT_DIR, "src", "static"), exist_ok=True)
app.mount("/static", StaticFiles(directory=os.path.join(PROJECT_DIR, "src", "static")), name="static")

# Thread-safe SSE Progress State Manager
class SSEProgressManager:
    def __init__(self):
        self.logs_queue = asyncio.Queue()
        self.is_running = False
        self.files_state = {}
        self.estimated_total = 184
        self.finished = False

    def reset(self):
        # Clear queue in a thread-safe manner
        while not self.logs_queue.empty():
            try:
                self.logs_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        self.is_running = True
        self.finished = False
        self.files_state = {}

    def add_log(self, text: str, log_type: str = "info"):
        if not text.strip():
            return
        
        # Simple parsing of log text to maintain parallel files status
        clean_text = text.strip()
        if "[Parallel Ingestion] Starting:" in clean_text:
            match = re.search(r'Starting:\s*([^\s]+)', clean_text)
            if match:
                self.files_state[match.group(1)] = "parsing"
        elif "[Parallel Ingestion] Finished:" in clean_text:
            match = re.search(r'Finished:\s*([^\s]+)', clean_text)
            if match:
                self.files_state[match.group(1)] = "complete"

        # Determine log category for UI color coding
        if "[ERROR]" in clean_text or "[CRITICAL ERROR]" in clean_text or "Error" in clean_text:
            log_type = "error"
        elif "[Warning]" in clean_text:
            log_type = "warning"
        elif "Successfully" in clean_text or "PASSED" in clean_text:
            log_type = "success"
        elif "[System]" in clean_text:
            log_type = "info"
        else:
            log_type = "info"

        try:
            # We use asyncio.run_coroutine_threadsafe to push to the queue from background threads
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.call_soon_threadsafe(self.logs_queue.put_nowait, (clean_text, log_type))
        except Exception:
            pass

global_sse_manager = SSEProgressManager()

# Thread-safe Sys.Stdout capture wrapper
class SSELogCaptureStream:
    def __init__(self, original_stream):
        self.original_stream = original_stream

    def write(self, message):
        self.original_stream.write(message)
        if message.strip():
            global_sse_manager.add_log(message.strip())

    def flush(self):
        self.original_stream.flush()

    def isatty(self):
        return False

# Setup captured stdout
sys.stdout = SSELogCaptureStream(sys.stdout)
sys.stderr = SSELogCaptureStream(sys.stderr)

# API Endpoint: Serve UI Single Page Application (index.html)
@app.get("/", response_class=HTMLResponse)
async def get_index():
    index_path = os.path.join(PROJECT_DIR, "src", "static", "index.html")
    if not os.path.exists(index_path):
        raise HTTPException(status_code=404, detail="index.html not found.")
    with open(index_path, "r", encoding="utf-8") as f:
        return f.read()

# API Endpoint: Get Current System State
@app.get("/api/system/status")
async def get_status():
    return {
        "is_running": global_sse_manager.is_running,
        "files_state": global_sse_manager.files_state
    }

# API Endpoint: Load config.env key-values
@app.get("/api/config")
async def get_config():
    config_path = os.path.join(PROJECT_DIR, "config.env")
    config_dict = {}
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            for line in f:
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.strip().split("=", 1)
                    config_dict[k.strip()] = v.strip()
    return config_dict

# API Endpoint: Save config.env key-values
class ConfigSchema(BaseModel):
    LLM_PROVIDER: str
    GEMINI_API_KEY: Optional[str] = ""
    GEMINI_LLM_MODEL: Optional[str] = ""
    GRADIO_LLM_URL: Optional[str] = ""
    OLLAMA_BASE_URL: Optional[str] = ""
    OLLAMA_LLM_MODEL: Optional[str] = ""
    EMBEDDING_PROVIDER: Optional[str] = ""

@app.post("/api/config")
async def save_config(config: ConfigSchema):
    config_path = os.path.join(PROJECT_DIR, "config.env")
    
    # Load current content to preserve formatting or other variables
    lines = []
    keys_updated = set()
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

    new_lines = []
    config_dict = config.dict()
    for line in lines:
        if "=" in line and not line.strip().startswith("#"):
            k, _ = line.strip().split("=", 1)
            k = k.strip()
            if k in config_dict:
                new_lines.append(f"{k}={config_dict[k]}\n")
                keys_updated.add(k)
                continue
        new_lines.append(line)

    for k, v in config_dict.items():
        if k not in keys_updated:
            new_lines.append(f"{k}={v}\n")

    with open(config_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    # Force reload dotenv config in active runtime memory
    load_dotenv(config_path, override=True)
    return {"status": "success"}

# API Endpoint: List Uploaded Level Raw Documents
@app.get("/api/files")
async def list_files():
    data_dir = os.path.join(PROJECT_DIR, "data", "raw")
    result = {"level_1": [], "level_2": []}
    for lvl in ["level_1", "level_2"]:
        lvl_path = os.path.join(data_dir, lvl)
        if os.path.exists(lvl_path):
            files = glob.glob(os.path.join(lvl_path, "*.docx"))
            for f in files:
                result[lvl].append({
                    "name": os.path.basename(f),
                    "size": os.path.getsize(f)
                })
    return result

# API Endpoint: Upload Raw Documents
@app.post("/api/upload")
async def upload_document(level: str = Query(..., regex="^(level_1|level_2)$"), files: List[UploadFile] = File(...)):
    target_dir = os.path.join(PROJECT_DIR, "data", "raw", level)
    os.makedirs(target_dir, exist_ok=True)
    
    uploaded_names = []
    for f in files:
        if not f.filename.endswith(".docx"):
            raise HTTPException(status_code=400, detail=f"Only Microsoft Word .docx files are allowed: {f.filename}")
        
        file_path = os.path.join(target_dir, f.filename)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(f.file, buffer)
        uploaded_names.append(f.filename)

    return {"status": "success", "uploaded": uploaded_names}

# API Endpoint: Clear Vector Database and processed cache
@app.post("/api/db/wipe")
async def wipe_database():
    db_dir = os.path.join(PROJECT_DIR, "db", "chromadb")
    processed_dir = os.path.join(PROJECT_DIR, "data", "processed")
    extracted_images_dir = os.path.join(PROJECT_DIR, "data", "extracted_images")

    # Error handler to remove read-only attribute before deleting a file
    def remove_readonly(func, path, excinfo):
        import stat
        try:
            os.chmod(path, stat.S_IWRITE)
            func(path)
        except Exception:
            pass

    # Wipe DB & processed paths
    for path in [db_dir, processed_dir, extracted_images_dir]:
        if os.path.exists(path):
            try:
                shutil.rmtree(path, onerror=remove_readonly)
            except Exception as e:
                # SQLite locks can occasionally throw permission errors. Try file-level delete fallback
                print(f"[Warning] Failed to completely delete {os.path.basename(path)}: {e}")
                
    # Recreate empty folders
    os.makedirs(processed_dir, exist_ok=True)
    os.makedirs(extracted_images_dir, exist_ok=True)
    return {"status": "success"}

# Background Thread: Runs the ingestion pipeline
def run_ingestion_background():
    global_sse_manager.reset()
    try:
        # Reload settings from disk
        load_dotenv(os.path.join(PROJECT_DIR, "config.env"), override=True)
        
        print("\n[System] Starting Multi-Agent Parallel Ingestion Stream...")
        from src.agents.orchestrator import MainOrchestrator
        orchestrator = MainOrchestrator()
        
        # Run parallel ingestion stream
        stats = orchestrator.ingest_level_parallel()
        
        print("\n----------------------------------------")
        print("          INGESTION STATISTICS REPORT")
        print("----------------------------------------")
        print(f"  Total questions parsed:        {stats['total']}")
        print(f"  Successfully indexed:          {stats['indexed']}")
        print(f"  Skipped (ID duplicate):        {stats['skipped_id']}")
        print(f"  Skipped (Semantic duplicate):   {stats['skipped_semantic']}")
        print(f"  Failed:                        {stats['failed']}")
        print("----------------------------------------")
        
        # Trigger default paper generation & docx booklet exports
        print("\n[System] Compiling default 80-question balanced booklets...")
        orchestrator.create_and_evaluate_papers(level=orchestrator.level_1_enum, target_size=80)
        orchestrator.create_and_evaluate_papers(level=orchestrator.level_2_enum, target_size=80)
        
        from src.exporter import export_all_compiled_papers
        export_all_compiled_papers()
        print("\n[System] Ingestion pipeline execution completed successfully.")
        
    except Exception as e:
        print(f"\n[CRITICAL ERROR] Background Ingestion Crashed: {e}")
    finally:
        global_sse_manager.finished = True
        global_sse_manager.is_running = False

# API Endpoint: Start Parallel Ingestion Process
@app.post("/api/ingestion/start")
async def start_ingestion(background_tasks: BackgroundTasks):
    if global_sse_manager.is_running:
        raise HTTPException(status_code=400, detail="Ingestion pipeline is already running.")
    
    # Calculate estimated question count based on .docx count * 50
    level_1_files = glob.glob(os.path.join(PROJECT_DIR, "data", "raw", "level_1", "*.docx"))
    level_2_files = glob.glob(os.path.join(PROJECT_DIR, "data", "raw", "level_2", "*.docx"))
    total_files = len(level_1_files) + len(level_2_files)
    global_sse_manager.estimated_total = max(10, total_files * 50)
    
    background_tasks.add_task(run_ingestion_background)
    return {"status": "started"}

# API Endpoint: SSE Progress event stream
@app.get("/api/ingestion/stream")
async def get_stream():
    async def sse_event_generator():
        from src.indexer import QuestionIndexer
        indexer = None
        try:
            indexer = QuestionIndexer()
        except Exception:
            pass

        last_db_count = 0
        while global_sse_manager.is_running or not global_sse_manager.logs_queue.empty():
            # 1. Fetch any logs from queue
            log_msg = None
            log_type = "info"
            if not global_sse_manager.logs_queue.empty():
                log_msg, log_type = await global_sse_manager.logs_queue.get()

            # 2. Periodically check ChromaDB question count
            db_count = last_db_count
            if indexer:
                try:
                    db_count = indexer.collection.count()
                except Exception:
                    pass
            last_db_count = db_count

            # 3. Build SSE event data
            pct = 0
            if global_sse_manager.estimated_total > 0:
                pct = min(100, int((db_count / global_sse_manager.estimated_total) * 100))

            event_data = {
                "indexed": db_count,
                "total": global_sse_manager.estimated_total,
                "pct": pct,
                "files_state": global_sse_manager.files_state,
                "log": log_msg,
                "log_type": log_type,
                "finished": global_sse_manager.finished
            }

            yield f"data: {json.dumps(event_data)}\n\n"
            await asyncio.sleep(0.5)

        # Send final completion event
        event_data = {
            "indexed": last_db_count,
            "total": global_sse_manager.estimated_total,
            "pct": 100,
            "files_state": global_sse_manager.files_state,
            "log": "[System] Live progress stream closed.",
            "log_type": "info",
            "finished": True
        }
        yield f"data: {json.dumps(event_data)}\n\n"

    return StreamingResponse(sse_event_generator(), media_type="text/event-stream")

# API Endpoint: Custom Shuffle & Scramble Papers Compilation
class CompileSchema(BaseModel):
    target_size: int = 80
    pct_easy: float = 0.3
    pct_medium: float = 0.4
    pct_hard: float = 0.3

@app.post("/api/compile/start")
async def start_compilation(params: CompileSchema):
    try:
        from src.agents.orchestrator import MainOrchestrator
        from src.exporter import export_all_compiled_papers
        
        load_dotenv(os.path.join(PROJECT_DIR, "config.env"), override=True)
        orchestrator = MainOrchestrator()
        
        # 1. Compile Level 1
        _, l1_report = orchestrator.create_and_evaluate_papers(
            level=orchestrator.level_1_enum,
            target_size=params.target_size,
            pct_easy=params.pct_easy,
            pct_medium=params.pct_medium,
            pct_hard=params.pct_hard
        )
        
        # 2. Compile Level 2
        _, l2_report = orchestrator.create_and_evaluate_papers(
            level=orchestrator.level_2_enum,
            target_size=params.target_size,
            pct_easy=params.pct_easy,
            pct_medium=params.pct_medium,
            pct_hard=params.pct_hard
        )
        
        # 3. Export booklets
        export_all_compiled_papers()
        
        return {
            "status": "success",
            "level_1_report": l1_report,
            "level_2_report": l2_report
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Paper compilation failed: {e}")

# API Endpoint: Download Compiled Booklets
@app.get("/download/{level}/{filename}")
async def download_file(level: str, filename: str):
    # Map level directory
    lvl_dir = "level_1" if level == "level_1" else "level_2"
    file_path = os.path.join(PROJECT_DIR, "data", "output", lvl_dir, filename)
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"Booklet file {filename} not found.")
        
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type="application/octet-stream"
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
