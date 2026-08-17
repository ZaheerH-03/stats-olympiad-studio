from src.classifier import SYSTEM_PROMPT
import os
import re
from typing import Dict, List, Optional, Tuple,Any
from pydantic import BaseModel, Field

from src.schemas import LevelEnum, QuestionModel, TopicEnum, QuestionTypeEnum, DifficultyEnum
from src.parser import parse_docx
from src.classifier import get_llm

###################
#1) Parsing Agent
###################

class BasicParsedQuestion(BaseModel):
    statement : str = Field(description="The text of the question, preserving LaTeX")
    options : Optional[Dict[str, str]] = Field(
        default = None,
        description = "MCQ options mapped to A, B, C, D. None if Numeric."
    )
    type : QuestionTypeEnum = Field(description = "Strictly MCQ or Numeric")
    correct_answer: str = Field(description="Correct option letter (e.g. 'A) or numeric value")

class ParsingAgent:
    """

    Agent responsible for : 
    1. Parsing docx into markdown blocks using Docling.
    2. Using the LLM to structure each raw text block into statement , options, type and answers.
    """

    SYSTEM_PROMPT = """You are a mathematical document structuring assistant.
Your task is to parse a raw question block from an examination set and extract it into a clean JSON format matching the specified schema.

CRITICAL REQUIREMENT FOR TABLES:
If the raw question block contains any Markdown data tables, you MUST preserve the entire table exactly as-is in the statement field. Do NOT discard, summarize, or omit the table.

Guidelines:
1. Identify the Question Type: 'MCQ' (if options are provided) or 'Numeric' (if it is a direct math problem requiring a numerical answer without options).
2. Preserving LaTeX: Ensure all math formulas, symbols, and equations are preserved in LaTeX format using $...$ (inline) or $$...$$ notation.
3. Options: If MCQ, parse the options into a dictionary with keys A, B, C, D. If Numeric, options must be null/None.
4. Correct Answer: Extract the correct answer key. If an official answer is provided below, use that. Ensure correct_answer is just the letter (A, B, C, or D) for MCQs, or the exact numerical value/expression for Numeric questions.
5. Statement Clean-up: Keep the question statement text, any tables, and any formulas. Remove only leading original question numbers (e.g. "39. ", "Q1. ") and any trailing correct answer suffixes (e.g. "[A]", "[B]", "[Ans: D]") from the statement text.
"""
    def __init__(self):
        self.llm = get_llm().with_structured_output(BasicParsedQuestion)
    
    def parse_file(self,file_path: str) -> Tuple[List[str], Dict[int, str]]:
        """
        Parses the docx file into raw question blocks and retrieves the answer key. 
        """
        return parse_docx(file_path)
    
    def structure_block(self, raw_block: str, external_ans: Optional[str]= None) -> BasicParsedQuestion:
        """
        Sends a raw block to the LLM to extract the question statement and options.
        """
        import re
        import os
        
        # 1. Search for and extract any local image references
        image_match = re.search(r'!\[.*?\]\((.*?)\)', raw_block)
        image_path = None
        if image_match:
            image_path = image_match.group(1).strip()
            # Resolve to absolute path so Gradio Client can locate the file
            image_path = os.path.abspath(image_path)
            # Strip the image markdown link from raw_block
            raw_block = re.sub(r'!\[.*?\]\((.*?)\)', '', raw_block)
            
        cleaned_block = re.sub(r'\\_\\_\\_\\_\\_+','[blank]',raw_block)
        cleaned_block = re.sub(r'________+','[blank]',cleaned_block)
        ans_info = f"\nEXTERNAL ANSWER KEY NOTE: The correct answer is officially '{external_ans}'." if external_ans else ""
        
        return self.llm.invoke(
            [
                ("system", self.SYSTEM_PROMPT),
                ("user", f"Raw Question Text Block:\n\n{cleaned_block}{ans_info}")
            ],
            config={"configurable": {"image_path": image_path}}
        )
##############################
# 2. TOPIC CLASSIFIER AGENT
##############################

class TopicExtractionModel(BaseModel):
    topic: TopicEnum = Field(description="Strictly mapped topic from the 13 categories")

class TopicClassificationAgent:
    """
    Agent Responsible for classifying the question statement into one of the 13 defined topic areas.
    """ 
    SYSTEM_PROMPT = """You are a mathematics and statistics topic classification assistant.
Your task is to analyze a math question statement and map it to the single most relevant topic out of these 13 categories:
1. basic_set_theory
2. basic_algebra (includes polynomials, quadratic equations, linear algebra, simultaneous equations, matrices)
3. basic_descriptive_statistics
4. problem_solving (includes word problems, arithmetic progressions, percentage change, simple interest, age problems, gears/ratios)
5. data_representation (includes bar/pie/line diagrams, frequency tables, histograms, cumulative curves, ogives)
6. data_handling (includes data grouping, class intervals, tally marks, adjusted frequency)
7. counting_techniques
8. elementary_probability_theory (includes dice/coin tosses, random experiments, prime number chances, expectation, Poisson distribution)
9. functions_and_distances (includes function mappings, domain, absolute values, distance between tops/trees)
10. permutations_and_combinations (includes circular permutations, combinations, arrangement sequences, factorials)
11. elementary_geometry (includes hexagon diagonals, adjacent angles, rhombus, tangents to circle/parabola)
12. elementary_number_theory (includes divisibility, HCF, Chinese Remainder Theorem, Euclid's algorithm)
13. basics_of_statistics (includes mean, median, mode, standard deviation, variance, coefficient of variation, positively skewed distributions)
"""
    def __init__(self):
        self.llm = get_llm().with_structured_output(TopicExtractionModel)

    def classify_topic(self, statement: str) -> TopicEnum:
        """Classifies the topic category for a given statement."""
        result = self.llm.invoke([
            ("system", self.SYSTEM_PROMPT),
            ("user",f"Question Statement:\n\n{statement}")
        ])
        return result.topic

############################################
# 3. DIFFICULTY CLASSIFICATION AGENT
###########################################

class DifficultyExtractionModel(BaseModel):
    difficulty : DifficultyEnum = Field(description="LLM-assigned difficulty rating: Easy, Medium, or Hard.")
    explanation: str = Field(description="Concise step-by-step mathematical explanation/working out (strictly max 2-3 sentences).")

class DifficultyClassificationAgent:
    """
    Agent responsible for evaluating the mathematical complexity of a statement,assigning a difficulty rating and writing a concise solution explanation.
    """
    SYSTEM_PROMPT = """You are an expert mathematics grader.
Your task is to analyze the difficulty of a question statement using Bloom's Taxonomy and write a very concise step-by-step mathematical explanation of the solution.

Guidelines:
1. Difficulty Rating: Evaluate the cognitive complexity based on these Bloom's Taxonomy mappings:
   - 'Easy' (Remembering & Understanding): Recalling definitions, basic formulas, reading tables directly, or direct single-step calculations.
   - 'Medium' (Applying & Analyzing): Translating word problems into equations, multi-step algebra, grouping data, or analyzing geometric/algebraic relations.
   - 'Hard' (Evaluating & Creating): Synthesizing multiple advanced concepts, formulating proofs, analyzing complex probability spaces, or creating combinations under complex constraints.
   
2. Explanation: Provide a very concise step-by-step mathematical explanation/working out of the solution (strictly maximum 2-3 sentences).
"""
    def __init__(self):
        self.llm = get_llm().with_structured_output(DifficultyExtractionModel)
    
    def classify_difficulty(self, statement:str) -> Tuple[DifficultyEnum, str]:
        """Evaluates complexity and generates explanation."""
        result = self.llm.invoke([
            ("system",self.SYSTEM_PROMPT),
            ("user",f"Question Statement:\n\n{statement}")
        ])
        return result.difficulty, result.explanation
