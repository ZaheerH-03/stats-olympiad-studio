import os
import hashlib
import json
import re
import concurrent.futures
from typing import List, Dict, Any, Tuple, Optional
from typing_extensions import TypedDict

# LangGraph imports
from langgraph.graph import StateGraph, START, END

from src.schemas import LevelEnum, QuestionModel, TopicEnum, QuestionTypeEnum, DifficultyEnum
from src.indexer import QuestionIndexer
from src.agents.data_processors import ParsingAgent, TopicClassificationAgent, DifficultyClassificationAgent
from src.agents.paper_creator import QuestionPaperCreatorAgent
from src.agents.evaluator import EvaluationAgent

# 1. Define the LangGraph State
class IngestionState(TypedDict):
    # Inputs
    raw_block: str
    level: LevelEnum
    filename: str
    external_ans: Optional[str]
    
    # Intermediate state filled by agents
    statement: Optional[str]
    options: Optional[Dict[str, str]]
    type: Optional[QuestionTypeEnum]
    correct_answer: Optional[str]
    topic: Optional[TopicEnum]
    difficulty: Optional[DifficultyEnum]
    explanation: Optional[str]
    
    # Final output
    final_question: Optional[QuestionModel]


class MainOrchestrator:
    """
    Main Orchestrator managing parallel ingestion via LangGraph,
    paper creation, and evaluation.
    """
    def __init__(self, raw_dir: str = "data/raw", processed_dir: str = "data/processed", output_dir: str = "data/output"):
        self.raw_dir = raw_dir
        self.processed_dir = processed_dir
        self.output_dir = output_dir
        os.makedirs(self.processed_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)
        
        # Initialize databases and agents
        self.indexer = QuestionIndexer()
        self.parsing_agent = ParsingAgent()
        self.topic_agent = TopicClassificationAgent()
        self.difficulty_agent = DifficultyClassificationAgent()
        self.paper_creator = QuestionPaperCreatorAgent(self.indexer)
        self.evaluator = EvaluationAgent()
        
        self.level_1_enum = LevelEnum.LEVEL_1
        self.level_2_enum = LevelEnum.LEVEL_2
        self.last_compiled_papers: Dict[str, Any] = {}
        
        # Build and compile the Ingestion LangGraph
        self.graph = self._build_ingestion_graph()

    def _build_ingestion_graph(self):
        """Compiles the StateGraph of collaborating agents."""
        workflow = StateGraph(IngestionState)
        
        # Define the node functions
        def parse_node(state: IngestionState) -> Dict[str, Any]:
            basic_info = self.parsing_agent.structure_block(
                state["raw_block"], 
                state["external_ans"]
            )
            # Normalize correct_answer to uppercase for MCQ questions
            correct_ans = basic_info.correct_answer
            if basic_info.type == QuestionTypeEnum.MCQ and correct_ans:
                correct_ans = correct_ans.upper()
                
            # Normalize options keys to uppercase
            options = basic_info.options
            if options:
                options = {k.upper(): v for k, v in options.items()}
                
            statement = basic_info.statement.strip()
            
            # Re-append the image markdown reference if it was present in the raw block
            image_match = re.search(r'!\[.*?\]\((.*?)\)', state["raw_block"])
            if image_match:
                img_ref = image_match.group(0)
                statement = f"{statement}\n\n{img_ref}"
                
            return {
                "statement": statement,
                "options": options,
                "type": basic_info.type,
                "correct_answer": correct_ans
            }
            
        def topic_node(state: IngestionState) -> Dict[str, Any]:
            topic = self.topic_agent.classify_topic(state["statement"])
            return {"topic": topic}
            
        def difficulty_node(state: IngestionState) -> Dict[str, Any]:
            difficulty, explanation = self.difficulty_agent.classify_difficulty(state["statement"])
            return {"difficulty": difficulty, "explanation": explanation}
            
        def compile_and_index_node(state: IngestionState) -> Dict[str, Any]:
            # Generate ID
            sha_hash = hashlib.sha256(state["statement"].encode("utf-8")).hexdigest()
            
            # Encrypt answers and explanations before database/cache writing to keep them secure
            from src.classifier import encrypt_string
            encrypted_answer = encrypt_string(state["correct_answer"])
            encrypted_explanation = encrypt_string(state.get("explanation", "") or "")
            
            # Build Pydantic model
            question_obj = QuestionModel(
                id=sha_hash,
                level=state["level"],
                topic=state["topic"],
                type=state["type"],
                difficulty=state["difficulty"],
                statement=state["statement"],
                options=state["options"],
                correct_answer=encrypted_answer,
                explanation=encrypted_explanation,
                source_file=state["filename"]
            )
            
            # Save to JSON cache
            from src.classifier import save_question_to_json
            save_question_to_json(question_obj, self.processed_dir)
            
            # Store in ChromaDB
            self.indexer.add_question(question_obj)
            
            return {"final_question": question_obj}

        # Add nodes to graph
        workflow.add_node("parse_raw", parse_node)
        workflow.add_node("classify_topic", topic_node)
        workflow.add_node("classify_difficulty", difficulty_node)
        workflow.add_node("compile_and_index", compile_and_index_node)
        
        # Add sequential edges to ensure exactly 1 LLM request runs at a time (preventing CUDA VRAM OOM)
        workflow.add_edge(START, "parse_raw")
        workflow.add_edge("parse_raw", "classify_topic")
        workflow.add_edge("classify_topic", "classify_difficulty")
        workflow.add_edge("classify_difficulty", "compile_and_index")
        workflow.add_edge("compile_and_index", END)
        
        return workflow.compile()

    def process_single_block(self, raw_block: str, level: LevelEnum, filename: str, external_ans: str = None) -> QuestionModel:
        """Runs the compiled LangGraph flow for a single block."""
        state = self.graph.invoke({
            "raw_block": raw_block,
            "level": level,
            "filename": filename,
            "external_ans": external_ans
        })
        return state["final_question"]

    def ingest_document(self, file_path: str, level: LevelEnum) -> Dict[str, int]:
        """
        Processes a single raw .docx file and indexes all valid questions.
        """
        stats = {"total": 0, "indexed": 0, "skipped_id": 0, "skipped_semantic": 0, "failed": 0}
        filename = os.path.basename(file_path)
        print(f"\n[Parallel Ingestion] Starting: {filename} ({level.value})")
        
        try:
            # Parse text into blocks
            blocks, answer_key = self.parsing_agent.parse_file(file_path)
            stats["total"] = len(blocks)
            
            for idx, block in enumerate(blocks, start=1):
                try:
                    external_ans = answer_key.get(idx)
                    # Run agents pipeline
                    question_obj = self.process_single_block(block, level, filename, external_ans)
                    
                    # Store in ChromaDB
                    status = self.indexer.add_question(question_obj)
                    stats[status] += 1
                    
                except Exception as e:
                    stats["failed"] += 1
                    print(f"  [ERROR] {filename} Question #{idx} failed: {e}")
                    
            print(f"[Parallel Ingestion] Finished: {filename} ({level.value}) -> Indexed: {stats['indexed']}/{stats['total']}")
        except Exception as e:
            print(f"[CRITICAL ERROR] Failed to parse document {filename}: {e}")
            
        return stats

    def ingest_level_parallel(self) -> Dict[str, int]:
        """
        Runs document ingestion for Level 1 and Level 2 in parallel using concurrent threads.
        """
        import glob
        level_1_files = glob.glob(os.path.join(self.raw_dir, "level_1", "*.docx"))
        level_2_files = glob.glob(os.path.join(self.raw_dir, "level_2", "*.docx"))
        
        all_tasks = []
        for f in level_1_files:
            all_tasks.append((f, LevelEnum.LEVEL_1))
        for f in level_2_files:
            all_tasks.append((f, LevelEnum.LEVEL_2))
            
        overall_stats = {"total": 0, "indexed": 0, "skipped_id": 0, "skipped_semantic": 0, "failed": 0}
        
        # Run document ingestions sequentially (max_workers=1) to prevent overwhelming the server
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            futures = {executor.submit(self.ingest_document, path, lvl): (path, lvl) for path, lvl in all_tasks}
            for future in concurrent.futures.as_completed(futures):
                path, lvl = futures[future]
                try:
                    res = future.result()
                    for k in overall_stats:
                        overall_stats[k] += res.get(k, 0)
                except Exception as e:
                    print(f"[Parallel Stream Error] Ingestion crashed for {os.path.basename(path)}: {e}")
                    
        return overall_stats

    def create_and_evaluate_papers(
        self, 
        level: LevelEnum, 
        target_size: int = 100,
        pct_easy: float = 0.3,
        pct_medium: float = 0.4,
        pct_hard: float = 0.3,
        exam_year: str = "2026"
    ) -> Tuple[Dict[str, List[QuestionModel]], Dict[str, Any]]:
        """
        Queries ChromaDB, creates the 3 sets, runs evaluation, and saves outputs.
        """
        print(f"\n[Paper Creator] Generating papers for {level.value}...")
        
        # 1. Retrieve all indexed questions for the level (will automatically run tamper-check and decrypt in memory)
        questions_pool = self.paper_creator.get_all_questions_for_level(level)
        print(f"[Paper Creator] Found {len(questions_pool)} total indexed questions for {level.value}.")
        
        # Exclude questions that have been used in any previous year (yearly exclusion filter)
        unused_questions = [q for q in questions_pool if not q.used_in_years]
        print(f"[Paper Creator] Found {len(unused_questions)} unused questions available for selection.")
        
        # 2. Select balanced 100 questions pool from unused questions only
        balanced_pool = self.paper_creator.select_balanced_pool(
            questions=unused_questions,
            target_size=target_size,
            pct_easy=pct_easy,
            pct_medium=pct_medium,
            pct_hard=pct_hard
        )
        
        # 3. Create 3 Sets (Set A, B, C)
        paper_sets = self.paper_creator.generate_three_sets(balanced_pool)
        
        # 4. Evaluate Sets
        report = self.evaluator.validate_paper_sets(
            paper_sets=paper_sets,
            target_size=target_size,
            pct_easy=pct_easy,
            pct_medium=pct_medium,
            pct_hard=pct_hard
        )
        
        # 5. Mark selected questions as used in the current exam year
        for q in balanced_pool:
            if not q.used_in_years:
                q.used_in_years = []
            if exam_year not in q.used_in_years:
                q.used_in_years.append(exam_year)
            
            # Make a copy and encrypt correct_answer / explanation before writing back to DB and cache
            from src.classifier import encrypt_string, save_question_to_json
            q_to_save = q.model_copy(deep=True)
            q_to_save.correct_answer = encrypt_string(q_to_save.correct_answer)
            q_to_save.explanation = encrypt_string(q_to_save.explanation or "")
            
            # Save back to database
            self.indexer.update_question_metadata(q_to_save)
            # Save back to local JSON cache
            save_question_to_json(q_to_save, self.processed_dir)
        
        # 6. Save sets to output folder or retain in-memory
        serialized_sets = {
            set_label: [q.model_dump() for q in qs] for set_label, qs in paper_sets.items()
        }
        
        output_data = {
            "level": level.value,
            "target_distribution": {"easy": pct_easy, "medium": pct_medium, "hard": pct_hard},
            "evaluation_report": report,
            "sets": serialized_sets
        }
        self.last_compiled_papers[level.value] = output_data
        
        save_local = os.getenv("SAVE_LOCAL_FILES", "false").lower() in ("true", "1", "yes")
        if save_local:
            output_file = os.path.join(self.output_dir, f"question_paper_{level.value}.json")
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(output_data, f, indent=2, ensure_ascii=False)
            print(f"[Paper Creator] Successfully saved question papers and report to: {output_file}")
        else:
            print(f"[Paper Creator] In-Memory mode active (SAVE_LOCAL_FILES=false). Skipping local disk write for question_paper_{level.value}.json.")
        
        return paper_sets, report

