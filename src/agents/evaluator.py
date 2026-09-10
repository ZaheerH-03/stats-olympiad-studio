import re
from typing import List, Dict, Any
from src.schemas import QuestionModel, QuestionTypeEnum, DifficultyEnum

class EvaluationAgent:
    """
    Agent responsible for running post-generation QA checks on the generated sets to ensure accuracy, tracebility, and distribution standards.
    """

    @staticmethod
    def _validate_latex_delimiters(statement: str) -> List[str]:
        """
        Validates math delimiters in LaTeX statement text.
        Returns a list of warning messages if any delimiters are unbalanced.
        """
        warnings = []
        if not statement:
            return warnings

        # 1. Check unescaped $ signs count (must be even for matching pairs)
        # Exclude escaped dollar signs \$
        unescaped_dollars = re.findall(r'(?<!\\)\$', statement)
        if len(unescaped_dollars) % 2 != 0:
            warnings.append(f"Unbalanced '$' math delimiters (found {len(unescaped_dollars)}).")

        # 2. Check \( and \) pairs
        open_paren = len(re.findall(r'\\\(', statement))
        close_paren = len(re.findall(r'\\\)', statement))
        if open_paren != close_paren:
            warnings.append(f"Mismatched LaTeX inline delimiters: \\( ({open_paren}) vs \\) ({close_paren}).")

        # 3. Check \[ and \] pairs
        open_bracket = len(re.findall(r'\\\[', statement))
        close_bracket = len(re.findall(r'\\\]', statement))
        if open_bracket != close_bracket:
            warnings.append(f"Mismatched LaTeX block delimiters: \\[ ({open_bracket}) vs \\] ({close_bracket}).")

        return warnings


    def validate_paper_sets(
        self,
        paper_sets : Dict[str, List[QuestionModel]],
        target_size: int = 100,
        pct_easy: float=0.3,
        pct_medium: float=0.4,
        pct_hard: float = 0.3,
    ) -> Dict[str, Any]:
        """
        Runs comprehensive validation tests across all generated sets.
        Returns a validation reports dictionary.
        """

        report = {
            "is_valid": True,
            "errors" : [],
            "warnings": [],
            "sets_analysis": {}
        }
        if not paper_sets:
            report["is_valid"] = False
            report["errors"].append("No paper sets were generated.")
            return report
        
        set_ids = {}

        for set_label, questions in paper_sets.items():
            set_report = {
                "total_count":len(questions),
                "easy_count":0,
                "medium_count":0,
                "hard_count":0,
                "mcq_count":0,
                "numeric_count":0
            }
            # Save question IDs for this set to check cross-set equivalence
            set_ids[set_label] = set(q.id for q in questions)
            # 1. Assert exactly the target size (e.g. 100 questions)
            if len(questions) != target_size:
                report["is_valid"] = False
                report["errors"].append(
                    f"{set_label} contains {len(questions)} questions instead of requested {target_size}."
                )
            # Validate each question's structure and metadata
            for idx, q in enumerate(questions, start=1):
                # 2. Check Traceability Metadata
                if not q.id:
                    report["is_valid"] = False
                    report["errors"].append(f"{set_label} Question #{idx}: Missing ID.")
                if not q.source_file:
                    report["is_valid"] = False
                    report["errors"].append(f"{set_label} Question #{idx} ({q.id}): Missing source_file name.")
                if not q.topic:
                    report["is_valid"] = False
                    report["errors"].append(f"{set_label} Question #{idx} ({q.id}): Missing topic category.")
                # Increment difficulty counters
                if q.difficulty == DifficultyEnum.EASY:
                    set_report["easy_count"] += 1
                elif q.difficulty == DifficultyEnum.MEDIUM:
                    set_report["medium_count"] += 1
                elif q.difficulty == DifficultyEnum.HARD:
                    set_report["hard_count"] += 1
                # 3. Check MCQ Options and Correct Answer Links
                if q.type == QuestionTypeEnum.MCQ:
                    set_report["mcq_count"] += 1
                    if not q.options:
                        report["is_valid"] = False
                        report["errors"].append(
                            f"{set_label} Question #{idx} ({q.id}): MCQ type is missing options dictionary."
                        )
                    else:
                        # Verify options contain the correct answer key
                        if q.correct_answer not in q.options:
                            report["is_valid"] = False
                            report["errors"].append(
                                f"{set_label} Question #{idx} ({q.id}): Correct answer key '{q.correct_answer}' "
                                f"is missing from the options keys: {list(q.options.keys())}."
                            )
                else:
                    set_report["numeric_count"] += 1
                    # Ensure numeric questions don't have option keys
                    if q.options:
                        report["is_valid"] = False
                        report["errors"].append(
                            f"{set_label} Question #{idx} ({q.id}): Numeric question should not have option fields."
                        )
                
                # 4. Check LaTeX Math Delimiter Integrity
                latex_warnings = self._validate_latex_delimiters(q.statement)
                for lw in latex_warnings:
                    report["warnings"].append(f"{set_label} Question #{idx} ({q.id}): {lw}")

            # 4. Check difficulty distribution matches targets within tolerance
            actual_easy_pct = set_report["easy_count"] / target_size
            actual_medium_pct = set_report["medium_count"] / target_size
            actual_hard_pct = set_report["hard_count"] / target_size
            set_report["easy_pct"] = actual_easy_pct
            set_report["medium_pct"] = actual_medium_pct
            set_report["hard_pct"] = actual_hard_pct
            # Allow a tolerance of +/- 2% for rounding, otherwise log warning
            if abs(actual_easy_pct - pct_easy) > 0.02 or \
               abs(actual_medium_pct - pct_medium) > 0.02 or \
               abs(actual_hard_pct - pct_hard) > 0.02:
                report["warnings"].append(
                    f"{set_label} difficulty distribution deviates from target. "
                    f"Actual: Easy={actual_easy_pct:.2f}, Medium={actual_medium_pct:.2f}, Hard={actual_hard_pct:.2f} vs "
                    f"Target: Easy={pct_easy:.2f}, Medium={pct_medium:.2f}, Hard={pct_hard:.2f}."
                )
            report["sets_analysis"][set_label] = set_report
        # 5. Verify Equivalence (Sets contain the exact same question pool)
        labels = list(set_ids.keys())
        for i in range(len(labels)):
            for j in range(i + 1, len(labels)):
                set_i = labels[i]
                set_j = labels[j]
                if set_ids[set_i] != set_ids[set_j]:
                    report["is_valid"] = False
                    report["errors"].append(
                        f"Critical Error: {set_i} and {set_j} do not contain the same questions. "
                        f"Difference size: {len(set_ids[set_i] ^ set_ids[set_j])} questions."
                    )
        return report