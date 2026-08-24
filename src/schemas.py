from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field

class LevelEnum(str, Enum):
    LEVEL_1 = "level_1"  # School Students
    LEVEL_2 = "level_2"  # College Students (11th, 12th, and Higher)

class QuestionTypeEnum(str, Enum):
    MCQ = "MCQ"
    NUMERIC = "Numeric"

class DifficultyEnum(str, Enum):
    EASY = "Easy"
    MEDIUM = "Medium"
    HARD = "Hard"

class TopicEnum(str, Enum):
    BASIC_SET_THEORY = "basic_set_theory"
    BASIC_ALGEBRA = "basic_algebra"
    BASIC_DESCRIPTIVE_STATISTICS = "basic_descriptive_statistics"
    PROBLEM_SOLVING = "problem_solving"
    DATA_REPRESENTATION = "data_representation"
    DATA_HANDLING = "data_handling"
    COUNTING_TECHNIQUES = "counting_techniques"
    ELEMENTARY_PROBABILITY_THEORY = "elementary_probability_theory"
    FUNCTIONS_AND_DISTANCES = "functions_and_distances"
    PERMUTATIONS_AND_COMBINATIONS = "permutations_and_combinations"
    ELEMENTARY_GEOMETRY = "elementary_geometry"
    ELEMENTARY_NUMBER_THEORY = "elementary_number_theory"
    BASICS_OF_STATISTICS = "basics_of_statistics"

class QuestionModel(BaseModel):
    id: str = Field(description="SHA-256 hash of the question text to guarantee uniqueness")
    level: LevelEnum = Field(description="Audience level: level_1 (School) or level_2 (College)")
    topic: TopicEnum = Field(description="Strictly mapped topic from the 13 defined categories")
    type: QuestionTypeEnum = Field(description="Strictly MCQ or Numeric")
    difficulty: DifficultyEnum = Field(description="LLM-assigned difficulty rating: Easy, Medium, or Hard")
    statement: str = Field(description="The core text prompt of the question. LaTeX equations should use $...$ or $$...$$ notation.")
    options: Optional[Dict[str, str]] = Field(
        default=None, 
        description="MCQ options (e.g. {'A': 'Option text', 'B': 'Option text'}). None for Numeric questions. LaTeX is preserved."
    )
    correct_answer: str = Field(description="The correct answer key (e.g., 'A') or exact numeric value/expression")
    explanation: Optional[str] = Field(default=None, description="Concise step-by-step mathematical explanation (max 2-3 sentences).")
    source_file: str = Field(description="Name/path of the original document parsed")
    used_in_years: Optional[List[str]] = Field(
        default=[], 
        description="List of calendar years when this question was selected and used in an active exam paper."
    )
