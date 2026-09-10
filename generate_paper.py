import os
import sys
import json
import traceback

# Ensure project root is in path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.schemas import LevelEnum
from src.agents.orchestrator import MainOrchestrator

def main():
    import sys
    # Reconfigure stdout/stderr to UTF-8 to prevent character encoding crashes on Windows console output
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
        
    print("=" * 60)
    print("      STATISTICS OLYMPIAD MULTI-AGENT INGESTION PIPELINE")
    print("=" * 60)
    
    # Initialize the orchestrator (this compiles the LangGraph internally)
    print("\nInitializing Main Orchestrator and agents...")
    try:
        orchestrator = MainOrchestrator()
        print("LangGraph compiled and indexer active.")
    except Exception as e:
        print(f"[CRITICAL ERROR] Failed to initialize orchestrator: {e}")
        traceback.print_exc()
        sys.exit(1)

    # 1. Parallel Ingestion
    print("\nStarting parallel document ingestion stream...")
    try:
        stats = orchestrator.ingest_level_parallel()
        print("\n" + "-" * 40)
        print("          INGESTION STATISTICS REPORT")
        print("-" * 40)
        print(f"  Total questions parsed:        {stats['total']}")
        print(f"  Successfully indexed:          {stats['indexed']}")
        print(f"  Skipped (ID duplicate):        {stats['skipped_id']}")
        print(f"  Skipped (Semantic duplicate):   {stats['skipped_semantic']}")
        print(f"  Failed:                        {stats['failed']}")
        print("-" * 40)
    except Exception as e:
        print(f"[ERROR] Parallel ingestion failed: {e}")
        traceback.print_exc()

    # 2. Paper Generation & Evaluation
    for level in [LevelEnum.LEVEL_1, LevelEnum.LEVEL_2]:
        try:
            paper_sets, report = orchestrator.create_and_evaluate_papers(
                level=level,
                target_size=80,  # We generate a full 80-question paper booklet
                pct_easy=0.3,
                pct_medium=0.4,
                pct_hard=0.3
            )
            
            print(f"\n--- {level.value.upper()} EVALUATION REPORT ---")
            print(f"  Validation Status: {'PASSED' if report['is_valid'] else 'FAILED'}")
            print(f"  Total Sets Checked: {len(report['sets_analysis'])}")
            
            for set_label, analysis in report["sets_analysis"].items():
                print(f"  - {set_label}: {analysis['total_count']} questions | Easy: {analysis['easy_count']} ({analysis['easy_pct']:.0%}), Medium: {analysis['medium_count']} ({analysis['medium_pct']:.0%}), Hard: {analysis['hard_count']} ({analysis['hard_pct']:.0%})")
                
            if report["warnings"]:
                print("  Warnings:")
                for w in report["warnings"]:
                    print(f"    * {w}")
                    
            if report["errors"]:
                print("  Errors:")
                for err in report["errors"]:
                    print(f"    * {err}")
                    
        except Exception as e:
            print(f"\n[ERROR] Paper generation/evaluation failed for {level.value}: {e}")
            traceback.print_exc()

    # 3. Export & Remote Upload Booklets
    try:
        from src.exporter import export_all_compiled_papers
        upload_results = export_all_compiled_papers(in_memory_booklets=orchestrator.last_compiled_papers)
        
        if upload_results:
            print("\n" + "=" * 70)
            print("                 REMOTE ENDPOINT UPLOAD REPORT")
            print("=" * 70)
            for res in upload_results:
                label = res.get("label", "Unknown")
                doc_id = res.get("doc_id", "N/A")
                verif = res.get("verification_status", "SKIPPED")
                shares = res.get("shares_count", 0)
                print(f"  • {label}")
                print(f"    - Document ID:    {doc_id}")
                print(f"    - SSS Shares:     {shares} nodes (Scheme: {res.get('scheme', 'SSS')} n={res.get('n')} k={res.get('k')})")
                print(f"    - Verification:   {verif}")
            print("=" * 70)
    except Exception as e:
        print(f"\n[ERROR] Exporting/uploading papers failed: {e}")
        traceback.print_exc()

    print("\nPipeline execution complete.\n")

if __name__ == "__main__":
    main()
