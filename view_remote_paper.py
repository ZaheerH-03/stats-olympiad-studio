import os
import sys
import json

# Ensure project root in sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.uploader import RemotePaperUploader

PAPERS = [
    ("4b7889b0-5b44-4dc2-bf57-03a487864b40", "Level 1 - Set A (Student Questions)"),
    ("1dd80c0f-c1e6-4ab7-b230-1325d593b02c", "Level 1 - Set A (Solutions & Answer Key)"),
    ("877b4d5a-7afa-4f2b-a06b-7a21d3ab4979", "Level 1 - Set B (Student Questions)"),
    ("8dbb8192-b782-48db-8f61-c1ea2d8bf170", "Level 1 - Set B (Solutions & Answer Key)"),
    ("ccc6a339-5fed-41e1-9dc4-c7db1cbf6517", "Level 1 - Set C (Student Questions)"),
    ("7089c3c3-32d1-4fea-8f0e-e68ffa8eaa66", "Level 1 - Set C (Solutions & Answer Key)"),
    ("15b91c85-d486-455c-930b-972c03f91fbb", "Level 2 - Set A (Student Questions)"),
    ("4b789a48-6819-4c36-9482-85b1f68a5310", "Level 2 - Set A (Solutions & Answer Key)"),
    ("895b10ee-818e-45b9-9ad1-fa31b9d2bf2e", "Level 2 - Set B (Student Questions)"),
    ("90516102-137b-4339-896c-cc96e4c21e61", "Level 2 - Set B (Solutions & Answer Key)"),
    ("7381f1c5-6cc8-41e4-9e69-740b02e4c82c", "Level 2 - Set C (Student Questions)"),
    ("24e89178-a45b-410a-99a4-59c1b95d0d94", "Level 2 - Set C (Solutions & Answer Key)"),
]

def main():
    print("=" * 65)
    print("       REMOTE QUESTION PAPER & SOLUTIONS INSPECTOR")
    print("=" * 65)
    
    uploader = RemotePaperUploader()
    print(f"Connecting to: {uploader.reconstruct_url_template}")
    print("\nAvailable Documents on Remote SSS Storage:\n")
    for idx, (doc_id, label) in enumerate(PAPERS, start=1):
        print(f"  [{idx:2d}] {label}")
        print(f"       ID: {doc_id}")
        
    print("\n" + "-" * 65)
    choice = input("\nEnter number (1-12) to download and inspect [or press Enter for 1]: ").strip()
    if not choice:
        choice = "1"
        
    try:
        idx = int(choice) - 1
        if not (0 <= idx < len(PAPERS)):
            print("Invalid selection.")
            return
        doc_id, label = PAPERS[idx]
    except ValueError:
        doc_id = choice
        label = "Custom ID"
        
    print(f"\nFetching and reconstructing document {doc_id} from SSS nodes...")
    raw_bytes = uploader.reconstruct_file(doc_id)
    print(f"Successfully reconstructed! Size: {len(raw_bytes)} bytes.\n")
    
    try:
        data = json.loads(raw_bytes.decode("utf-8"))
        print(f"Title:        {data.get('olympiad')}")
        print(f"Level & Set:  {data.get('level')} — {data.get('set')}")
        print(f"Type:         {data.get('document_type')}")
        print(f"Questions:    {data.get('total_questions')}")
        
        if "answer_key" in data:
            print("\nQuick Answer Key Sample (first 5 questions):")
            for q_k, q_v in list(data["answer_key"].items())[:5]:
                print(f"  {q_k}: {q_v.get('correct_answer')} ({q_v.get('topic')})")
                
        if "questions" in data and len(data["questions"]) > 0:
            print("\nQuestion #1 Preview:")
            q1 = data["questions"][0]
            print(f"  Statement: {q1.get('statement')}")
            if q1.get("options"):
                print(f"  Options:   {q1.get('options')}")
            if q1.get("correct_answer"):
                print(f"  Answer:    {q1.get('correct_answer')}")
                print(f"  Solution:  {q1.get('explanation')}")
    except Exception:
        print(f"Preview (raw):\n{raw_bytes[:400]}")

if __name__ == "__main__":
    main()
