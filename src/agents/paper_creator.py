import random
import secrets
import json
import re
from collections import defaultdict
from typing import List, Dict, Tuple
from src.schemas import LevelEnum, QuestionModel, QuestionTypeEnum, TopicEnum, DifficultyEnum
from src.indexer import QuestionIndexer

# Cryptographically secure random generator
cryptogen = secrets.SystemRandom()

class QuestionPaperCreatorAgent:
    """
    Agent Responsible for:
    1. Retrieving all indexed questions for a given level from ChromaDB.
    2. Selecting a balanced pool of questions based on configurable difficulty ratios.
    3. Generating 3 distinct sets (Set A, B, C) by shuffling the order of questions and shuffling the options of the MCQ Questions.
    """

    def __init__(self, indexer:QuestionIndexer):
        self.indexer = indexer
    
    def get_all_questions_for_level(self,level:LevelEnum) -> List[QuestionModel]:
        """
        Queries ChromaDB to retrieve all questions matching the target level.
        """
        import hashlib
        from src.classifier import decrypt_string
        
        results = self.indexer.collection.get()
        questions = []
        for idx in range(len(results["ids"])):
            metadata = results["metadatas"][idx]
            if metadata.get("level")==level.value:
                statement_text = results["documents"][idx]
                
                # Check SHA-256 integrity (Self-Validating Tamper Detection)
                computed_id = hashlib.sha256(statement_text.encode("utf-8")).hexdigest()
                if computed_id != results['ids'][idx]:
                    print(f"[Warning] Question statement has been tampered with! Discarding question ID: {results['ids'][idx]}")
                    continue
                
                options_str = metadata.get('options_json',"")
                options = json.loads(options_str) if options_str else None
                if options:
                    options = {k.upper(): v for k, v in options.items()}
                
                # Decrypt answer in memory
                correct_ans_encrypted = metadata.get("correct_answer")
                correct_ans = decrypt_string(correct_ans_encrypted)
                
                q_type = metadata.get("type")
                if correct_ans and q_type == QuestionTypeEnum.MCQ.value:
                    correct_ans = correct_ans.upper()
                
                # Decrypt explanation in memory
                explanation_encrypted = metadata.get("explanation")
                explanation = decrypt_string(explanation_encrypted)
                
                # Extract used_in_years history list
                used_in_years_str = metadata.get("used_in_years_json", "[]")
                try:
                    used_in_years = json.loads(used_in_years_str)
                except Exception:
                    used_in_years = []
                    
                q = QuestionModel(
                    id = results['ids'][idx],
                    level = level,
                    topic = TopicEnum(metadata.get("topic")),
                    type = QuestionTypeEnum(q_type),
                    difficulty = DifficultyEnum(metadata.get("difficulty")),
                    statement = statement_text,
                    options = options,
                    correct_answer = correct_ans,
                    explanation = explanation,
                    source_file = metadata.get("source_file"),
                    used_in_years = used_in_years
                )
                questions.append(q)
        return questions

    def select_balanced_pool(
        self,
        questions: List[QuestionModel],
        target_size: int = 100,
        pct_easy: float = 0.3,
        pct_medium: float = 0.4,
        pct_hard: float = 0.3) -> List[QuestionModel]:
        """
        Selects a pool of questions that matches target difficulty distributions.
        Borrows from other categories if there is a deficit.
        """
        if not (0.99 <= (pct_easy + pct_medium + pct_hard) <= 1.01):
            raise ValueError(
                f"Difficulty percentages must sum to 1.0. Got : {pct_easy}+{pct_medium}+{pct_hard} = {pct_easy + pct_medium + pct_hard}"
            )
        
        pools = {
            DifficultyEnum.EASY: [q for q in questions if q.difficulty == DifficultyEnum.EASY],
            DifficultyEnum.MEDIUM: [q for q in questions if q.difficulty == DifficultyEnum.MEDIUM],
            DifficultyEnum.HARD: [q for q in questions if q.difficulty == DifficultyEnum.HARD],
        }

        # Calculate target counts
        target_counts = {
            DifficultyEnum.EASY : int(round(target_size * pct_easy)),
            DifficultyEnum.MEDIUM : int(round(target_size * pct_medium)),
            DifficultyEnum.HARD : int(round(target_size * pct_hard)),
        }
        diff = target_size - sum(target_counts.values())
        if diff != 0:
            target_counts[DifficultyEnum.MEDIUM]+= diff
        
        selected = []
        deficits = 0
        leftover_pools = {}
        
        for diff_level in pools:
            # Group by topic for stratified selection across the syllabus
            by_topic = defaultdict(list)
            for q in pools[diff_level]:
                by_topic[q.topic].append(q)
            for t in by_topic:
                cryptogen.shuffle(by_topic[t])
            # Round-robin interleave topics to ensure maximum topic diversity
            interleaved = []
            topic_lists = list(by_topic.values())
            cryptogen.shuffle(topic_lists)
            max_len = max((len(lst) for lst in topic_lists), default=0)
            for i in range(max_len):
                for t_lst in topic_lists:
                    if i < len(t_lst):
                        interleaved.append(t_lst[i])
            pools[diff_level] = interleaved

        for diff_level, target in target_counts.items():
            pool = pools[diff_level]
            if len(pool) >= target:
                selected.extend(pool[:target])
                leftover_pools[diff_level] = pool[target:]
            else:
                selected.extend(pool)
                deficits += (target - len(pool))
                leftover_pools[diff_level] = []
                print(f"[Warning] Deficit of {target - len(pool)} '{diff_level.value}' questions. Will borrow from other pools.")

        if deficits > 0:
            all_leftovers = []
            for pref in [DifficultyEnum.HARD, DifficultyEnum.MEDIUM, DifficultyEnum.EASY]:
                all_leftovers.extend(leftover_pools[pref])
            if len(all_leftovers) < deficits:
                raise ValueError(
                    f"Not enough total questions in the database to satisfy paper size {target_size}."
                    f"Available unique questions: {len(questions)}."
                )
            selected.extend(all_leftovers[:deficits])
        return selected
    
    @staticmethod
    def _is_positional_option(text: str) -> bool:
        """
        Detects if an option text refers to relative position such as
        'All of the above', 'None of the above', 'Both A and B', etc.
        """
        if not text:
            return False
        pattern = r'\b(all\s+of\s+the\s+above|none\s+of\s+the\s+above|all\s+the\s+above|none\s+of\s+these|all\s+of\s+these|both\s+(?:\([a-d]\)|[a-d])\s+and\s+(?:\([a-d]\)|[a-d]))\b'
        return bool(re.search(pattern, text.strip(), re.IGNORECASE))

    def generate_three_sets(self, pool: List[QuestionModel]) -> Dict[str, List[QuestionModel]]:
        """
        Generate 3 sets (Set A, Set B, Set C) from the selected pool by
        cryptographically shuffling questions and option choices while preserving
        positional option semantics (e.g., 'None of the above').
        """
        sets = {}
        for set_label in ["Set A", "Set B", "Set C"]:
            shuffled_pool = list(pool)
            cryptogen.shuffle(shuffled_pool)
            set_questions = []
            for q in shuffled_pool:
                q_copy = q.model_copy(deep=True)
                # Shuffle options if MCQ
                if q_copy.type == QuestionTypeEnum.MCQ and q_copy.options:
                    orig_options = q_copy.options
                    orig_correct_ans = q_copy.correct_answer
                    correct_option_text = orig_options.get(orig_correct_ans)
                    
                    # Detect if any option contains positional keywords
                    positional_keys = [k for k, v in orig_options.items() if self._is_positional_option(v)]
                    
                    if positional_keys:
                        # Lock positional options to their original bottom slots and shuffle only independent options
                        indep_keys = [k for k in ["A", "B", "C", "D"] if k in orig_options and k not in positional_keys]
                        indep_vals = [orig_options[k] for k in indep_keys]
                        cryptogen.shuffle(indep_vals)
                        
                        new_options = {}
                        for k, v in zip(indep_keys, indep_vals):
                            new_options[k] = v
                        for pk in positional_keys:
                            new_options[pk] = orig_options[pk]
                    else:
                        # Shuffle all options
                        keys = [k for k in ["A", "B", "C", "D"] if k in orig_options]
                        vals = [orig_options[k] for k in keys]
                        cryptogen.shuffle(vals)
                        new_options = {k: v for k, v in zip(keys, vals)}
                        
                    # Re-map correct answer to the new key matching correct_option_text
                    new_correct_ans = None
                    for k, v in new_options.items():
                        if v == correct_option_text:
                            new_correct_ans = k
                            break
                    if new_correct_ans:
                        q_copy.options = new_options
                        q_copy.correct_answer = new_correct_ans
                    
                set_questions.append(q_copy)
                
            sets[set_label] = set_questions
            
        return sets