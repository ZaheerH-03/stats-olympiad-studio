import os
import hashlib
import json
from typing import Dict, Optional, Any, List
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Import Pydantic models and Enums
from src.schemas import QuestionModel, LevelEnum, TopicEnum, QuestionTypeEnum, DifficultyEnum

# Load config.env to avoid collision with the .env folder on Windows
load_dotenv("config.env")

# System prompt outlining the strict mapping rules and LaTeX requirements
SYSTEM_PROMPT = """You are an expert mathematics and statistics professor classification assistant.
Your task is to analyze a raw question block from an examination set and structure it into a clean JSON format matching the specified schema.

Topic categories are restricted to these 13 topics:
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

Guidelines:
1. Identify the Question Type: 'MCQ' (if options are provided) or 'Numeric' (if it is a direct math problem requiring a numerical answer without options).
2. Preserving LaTeX: Ensure all math formulas, symbols, and equations are preserved in LaTeX format using $...$ (inline) or $$...$$ (block) notation.
3. Options: If MCQ, parse the options into a dictionary with keys A, B, C, D (normalize 1, 2, 3, 4 to A, B, C, D if needed). If Numeric, options must be null/None.
4. Correct Answer: Extract the correct answer. We might supply a known answer key; if so, use that. Ensure correct_answer is just the letter (A, B, C, or D) for MCQs, or the exact numerical value/expression for Numeric questions.
5. Difficulty Rating: Evaluate the math complexity and assign:
   - 'Easy': Direct definition or single-step arithmetic.
   - 'Medium': Requires 2-3 algebraic steps, formula lookup, or basic logical deduction.
   - 'Hard': Requires advanced synthesis, multi-stage calculation, proofs, or complex probability/counting logic.
6. Topic: Choose the single best topic from the 13 categories list above.
7. Explanation: Provide a very concise step-by-step mathematical explanation/working out of the solution (strictly maximum 2-3 sentences). Keep it brief to speed up processing.
8. Table Preservation: If the raw question block contains a Markdown table (e.g., class intervals, frequencies), you MUST preserve the entire table exactly as-is in the statement field. Do NOT discard, summarize, or omit the table data.

Input Level Context: {level}
Input Source File: {source_file}
{external_answer_info}
"""

class QuestionExtractionModel(BaseModel):
    """
    Temporary schema for structured output extraction (id is generated separately in Python).
    """
    topic: TopicEnum = Field(description="Strictly mapped topic from the 13 categories")
    type: QuestionTypeEnum = Field(description="Strictly MCQ or Numeric")
    difficulty: DifficultyEnum = Field(description="LLM-assigned difficulty rating: Easy, Medium, or Hard")
    statement: str = Field(description="The core text of the question, preserving LaTeX")
    options: Optional[Dict[str, str]] = Field(
        default=None, 
        description="MCQ options mapped to A, B, C, D. None if Numeric."
    )
    correct_answer: str = Field(description="Correct option letter (e.g. 'A') or numeric value")
    explanation: Optional[str] = Field(default=None, description="Concise step-by-step mathematical explanation (max 2-3 sentences).")

def fix_json_escapes(json_str: str) -> str:
    result = []
    i = 0
    n = len(json_str)
    while i < n:
        char = json_str[i]
        if char == '\\':
            if i + 1 < n:
                next_char = json_str[i+1]
                after_next = json_str[i+2] if i + 2 < n else ''
                is_json_control = next_char in ['n', 't', 'r'] and not after_next.isalpha()
                is_other_escape = next_char in ['"', '\\', '/']
                if is_json_control or is_other_escape:
                    result.append('\\')
                    result.append(next_char)
                    i += 2
                else:
                    result.append('\\\\')
                    result.append(next_char)
                    i += 2
            else:
                result.append('\\\\')
                i += 1
        else:
            result.append(char)
            i += 1
    return "".join(result)

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.outputs import ChatResult, ChatGeneration
from langchain_core.messages import BaseMessage, AIMessage, SystemMessage

# Global cache for Gradio Clients to bypass Pydantic v2 ModelPrivateAttr constraints
_GRADIO_CLIENT_CACHE = {}

def get_gradio_client(url: str) -> Any:
    """Helper to lazily load and cache the Gradio Client connection."""
    if url not in _GRADIO_CLIENT_CACHE:
        from gradio_client import Client
        print(f"Performing handshake and caching client connection for: {url}")
        # Configure a high handshake and read timeout (10 minutes) via httpx_kwargs
        _GRADIO_CLIENT_CACHE[url] = Client(url, httpx_kwargs={"timeout": 600.0})
    return _GRADIO_CLIENT_CACHE[url]


class ChatGradio(BaseChatModel):
    gradio_url: str
    api_name: str = "/generate"
    
    @property
    def client(self) -> Any:
        return get_gradio_client(self.gradio_url)

    @property
    def _llm_type(self) -> str:
        return "gradio-client"
        
    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> ChatResult:
        prompt_parts = []
        for msg in messages:
            if msg.type == "system":
                prompt_parts.append(f"System:\n{msg.content}")
            elif msg.type == "human" or msg.type == "user":
                prompt_parts.append(f"User:\n{msg.content}")
            elif msg.type == "ai" or msg.type == "assistant":
                prompt_parts.append(f"Assistant:\n{msg.content}")
            else:
                prompt_parts.append(f"{msg.type.capitalize()}:\n{msg.content}")
                
        prompt = "\n\n".join(prompt_parts)
        image_path = kwargs.get("image_path", None)
        
        # Reuse the cached client
        try:
            # Try calling with prompt and optional image (multimodal vision server)
            res = self.client.predict(prompt=prompt, image_path=image_path, api_name=self.api_name)
        except Exception as e:
            # Fallback to text-only if server signature does not match
            res = self.client.predict(prompt=prompt, api_name=self.api_name)
        
        ai_msg = AIMessage(content=res)
        return ChatResult(generations=[ChatGeneration(message=ai_msg)])
        
    def with_structured_output(self, schema: Any, **kwargs: Any):
        from langchain_core.runnables import RunnableLambda
        from langchain_core.output_parsers import JsonOutputParser
        
        parser = JsonOutputParser(pydantic_object=schema)
        
        def _invoke_and_parse(input_messages, config=None):
            format_instructions = parser.get_format_instructions()
            
            # Extract image_path from configurable config if passed
            configurable = config.get("configurable", {}) if config else {}
            image_path = configurable.get("image_path", None)
            
            new_messages = []
            for msg in input_messages:
                if isinstance(msg, tuple):
                    role, content = msg
                    if role == "system":
                        content = f"{content}\n\n{format_instructions}"
                    new_messages.append((role, content))
                elif isinstance(msg, BaseMessage):
                    if msg.type == "system":
                        new_messages.append(SystemMessage(content=f"{msg.content}\n\n{format_instructions}"))
                    else:
                        new_messages.append(msg)
                else:
                    new_messages.append(msg)
                    
            response = self.invoke(new_messages, image_path=image_path)
            content = response.content
            
            clean_content = content.strip()
            if clean_content.startswith("```"):
                lines = clean_content.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                clean_content = "\n".join(lines).strip()
                
            fixed_content = fix_json_escapes(clean_content)
            parsed_dict = parser.parse(fixed_content)
            
            # Normalize common LLM classification synonyms for topics
            if "topic" in parsed_dict:
                topic_val = str(parsed_dict["topic"]).strip().lower().replace(" ", "_")
                topic_mapping = {
                    "basic_geometry": "elementary_geometry",
                    "geometry": "elementary_geometry",
                    "elementary_geometry": "elementary_geometry",
                    "basic_probability": "elementary_probability_theory",
                    "probability": "elementary_probability_theory",
                    "probability_theory": "elementary_probability_theory",
                    "elementary_probability": "elementary_probability_theory",
                    "basic_number_theory": "elementary_number_theory",
                    "number_theory": "elementary_number_theory",
                    "descriptive_statistics": "basic_descriptive_statistics",
                    "descriptive": "basic_descriptive_statistics",
                    "algebra": "basic_algebra",
                    "set_theory": "basic_set_theory",
                    "statistics": "basics_of_statistics",
                    "basic_statistics": "basics_of_statistics"
                }
                if topic_val in topic_mapping:
                    parsed_dict["topic"] = topic_mapping[topic_val]
                    
            return schema(**parsed_dict)
            
        return RunnableLambda(_invoke_and_parse)

def get_llm():
    """
    Instantiate LLM client based on config.env provider settings.
    """
    provider = os.getenv("LLM_PROVIDER", "gemini").lower()
    
    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        model_name = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
        
        if not api_key:
            raise ValueError("GEMINI_API_KEY or GOOGLE_API_KEY must be set in config.env for Gemini provider.")
            
        return ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=api_key,
            temperature=0.1,
            timeout=60.0  # Prevents hanging indefinitely on slow queries
        )
        
    elif provider == "ollama":
        from langchain_ollama import ChatOllama
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        model_name = os.getenv("OLLAMA_MODEL", "llama3")
        
        return ChatOllama(
            model=model_name,
            base_url=base_url,
            temperature=0.1,
            timeout=60.0  # Prevents hanging indefinitely on slow queries
        )
    elif provider == "local_api":
        from langchain_openai import ChatOpenAI
        base_url = os.getenv("LOCAL_API_BASE_URL", "http://localhost:8000/v1")
        model_name = os.getenv("LOCAL_API_MODEL", "google/gemma-2-27b-it")
        
        return ChatOpenAI(
            model=model_name,
            api_key="dummy-key",
            base_url=base_url,
            temperature=0.1,
            timeout=60.0
        )
    elif provider == "gradio":
        gradio_url = os.getenv("GRADIO_LLM_URL")
        if not gradio_url:
            raise ValueError("GRADIO_LLM_URL must be set in config.env for Gradio provider.")
        return ChatGradio(gradio_url=gradio_url)
    else:
        raise ValueError(f"Unknown LLM provider: {provider}")

def classify_question(
    raw_block: str, 
    level: LevelEnum, 
    source_file: str, 
    external_ans: Optional[str] = None
) -> QuestionModel:
    """
    Sends the raw text block to the LLM for classification and returns a validated QuestionModel.
    """
    import re
    
    # 1. Search for and extract any local image references
    image_match = re.search(r'!\[.*?\]\((.*?)\)', raw_block)
    image_path = None
    if image_match:
        image_path = image_match.group(1).strip()
        # Resolve to absolute path so Gradio Client can locate the file
        image_path = os.path.abspath(image_path)
        # Strip the image markdown link from raw_block
        raw_block = re.sub(r'!\[.*?\]\((.*?)\)', '', raw_block)
        
    # Replace escaped underscores or long underscores with a clean [blank] placeholder
    # to prevent local LLMs (like Ollama models) from looping infinitely on backslashed underscores.
    cleaned_block = re.sub(r'\\_\\_\\_\\_\\_+', '[blank]', raw_block)
    cleaned_block = re.sub(r'_____+', '[blank]', cleaned_block)
    
    llm = get_llm()
    
    # Format external answer helper if available
    if external_ans:
        ans_info = f"EXTERNAL ANSWER KEY NOTE: The correct answer key for this question is officially verified as '{external_ans}'."
    else:
        ans_info = ""
        
    prompt = SYSTEM_PROMPT.format(
        level=level.value,
        source_file=source_file,
        external_answer_info=ans_info
    )
    
    # Configure structured extraction
    structured_llm = llm.with_structured_output(QuestionExtractionModel)
    
    # Call the model, forwarding the config with the image path
    result = structured_llm.invoke(
        [
            ("system", prompt),
            ("user", f"Raw Question Text Block:\n\n{cleaned_block}")
        ],
        config={"configurable": {"image_path": image_path}}
    )
    
    # Create deterministic SHA-256 ID based on the statement text
    cleaned_statement = result.statement.strip()
    sha_hash = hashlib.sha256(cleaned_statement.encode("utf-8")).hexdigest()
    
    # Package into the final validated QuestionModel
    question_data = QuestionModel(
        id=sha_hash,
        level=level,
        topic=result.topic,
        type=result.type,
        difficulty=result.difficulty,
        statement=cleaned_statement,
        options=result.options,
        correct_answer=result.correct_answer,
        explanation=result.explanation,
        source_file=source_file
    )
    
    return question_data

def save_question_to_json(question: QuestionModel, base_processed_dir: str):
    """
    Saves a QuestionModel instance as a JSON file in the corresponding level/topic directory.
    """
    import stat
    # E.g., data/processed/level_1/basic_set_theory/
    topic_dir = os.path.join(base_processed_dir, question.level.value, question.topic.value)
    os.makedirs(topic_dir, exist_ok=True)
    
    file_path = os.path.join(topic_dir, f"q_{question.id}.json")
    
    # Temporarily make file writable if it already exists to allow overwrite
    if os.path.exists(file_path):
        try:
            os.chmod(file_path, stat.S_IWRITE)
        except Exception:
            pass
    
    # Save formatted JSON
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(question.model_dump(), f, indent=2, ensure_ascii=False)
        
    # Mark the file as read-only to prevent manual tampering
    try:
        os.chmod(file_path, stat.S_IREAD)
    except Exception:
        pass
        
    return file_path

import base64
from cryptography.fernet import Fernet

def get_fernet_cipher() -> Fernet:
    """Derives a cryptographically secure 32-byte Fernet key from EXAM_SECRET_KEY."""
    secret = os.environ.get("EXAM_SECRET_KEY", "default_super_secret_olympiad_key_12345!")
    # Generate 32 bytes using SHA-256
    key_32 = hashlib.sha256(secret.encode("utf-8")).digest()
    # URL-safe base64 encode
    fernet_key = base64.urlsafe_b64encode(key_32)
    return Fernet(fernet_key)

def encrypt_string(text: str) -> str:
    """Encrypts a plaintext string using the secret key."""
    if not text:
        return ""
    cipher = get_fernet_cipher()
    return cipher.encrypt(text.encode("utf-8")).decode("utf-8")

def decrypt_string(ciphertext: str) -> str:
    """Decrypts a ciphertext token back to plaintext. Falls back to original text on failure."""
    if not ciphertext:
        return ""
    # Fernet tokens start with gAAAA
    if not ciphertext.startswith("gAAAA"):
        return ciphertext
    try:
        cipher = get_fernet_cipher()
        return cipher.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except Exception as e:
        # Fallback to return ciphertext directly if wrong key/corrupt
        return ciphertext
