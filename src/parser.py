import os
import re
from typing import Dict, List, Tuple
from docling.document_converter import DocumentConverter

def extract_answer_key(text: str) -> Tuple[str, Dict[int, str]]:
    """
    Search for a consolidated Answers section at the end of the text.
    If found, parse it into a dictionary mapping question number -> answer key,
    and return the text without the Answers section.
    """
    # Matches markdown headers or bold text saying "Answers" or "Answer Key"
    match = re.search(r"\n\s*(?:\*\*|\*|#+)?\s*Answers?\s*(?:Key)?\s*(?:\*\*|\*|#+)?\s*\n", text, re.IGNORECASE)
    if not match:
        return text, {}
        
    split_idx = match.start()
    main_text = text[:split_idx]
    answers_text = text[split_idx:]
    
    ans_dict = {}
    # Matches lines like: "1. D" or "1. A" or "1) A" or "1.D" or "1: A"
    pattern = re.compile(r"^\s*(\d+)\s*[\.\:\-]?\s*([A-D])\s*$", re.MULTILINE | re.IGNORECASE)
    
    for m in pattern.finditer(answers_text):
        q_num = int(m.group(1))
        ans_val = m.group(2).upper()
        ans_dict[q_num] = ans_val
        
    return main_text, ans_dict

def split_questions(text: str) -> List[str]:
    """
    Split the markdown text into discrete question blocks.
    Uses a sequential-tracking heuristic to distinguish question starts from numbered options.
    """
    # Matches line starting with a number (e.g. "1.", "1)", "**1.**", "1. ")
    pattern = re.compile(r"^\s*(?:\*\*|\*|)?(\d+)\s*[\.\)]\s*(.*)$")
    
    lines = text.split("\n")
    questions = []
    current_q = []
    expected_num = 1
    
    for line in lines:
        match = pattern.match(line)
        if match:
            num = int(match.group(1))
            content = match.group(2).strip()
            # Enforce that the question statement must be at least 15 characters long
            # to filter out option list lines (e.g., "1. Universal", "2. Null")
            if len(content) >= 15:
                # Normal sequence or duplicate of previous question (e.g. two 5s in Level 2 Set 1)
                # We enforce num > 4 for the duplicate check to prevent matching options 1..4.
                if num == expected_num or (num == expected_num - 1 and num > 4):
                    if current_q:
                        questions.append("\n".join(current_q).strip())
                    current_q = [line]
                    if num == expected_num:
                        expected_num += 1
                    continue
        current_q.append(line)
        
    if current_q:
        questions.append("\n".join(current_q).strip())
        
    # Return questions starting from index 1 (index 0 is the preamble before Q1)
    if len(questions) > 1:
        return questions[1:]
    return []

def extract_and_replace_images(result, file_path: str, markdown_text: str) -> str:
    """
    Extracts all images from the parsed document, saves them to disk,
    and replaces the '<!-- image -->' comment placeholders in the markdown sequentially
    with markdown image links.
    """
    from docling_core.types.doc import PictureItem
    
    # Extract clean filename base, e.g. "Set2_Level-2"
    base_name = os.path.splitext(os.path.basename(file_path))[0].replace(" ", "_")
    
    # Target directory in workspace
    target_dir = os.path.join("data", "extracted_images", base_name)
    abs_target_dir = os.path.abspath(target_dir)
    os.makedirs(abs_target_dir, exist_ok=True)
    
    # 1. Extract and save all images
    extracted_images = []
    pic_index = 1
    
    try:
        for element, _ in result.document.iterate_items():
            if isinstance(element, PictureItem):
                image = element.get_image(result.document)
                if image:
                    pic_name = f"image_{pic_index}.png"
                    save_path = os.path.join(abs_target_dir, pic_name)
                    image.save(save_path, "PNG")
                    
                    # Store relative path for markdown reference
                    rel_ref_path = os.path.join("data", "extracted_images", base_name, pic_name).replace("\\", "/")
                    extracted_images.append(rel_ref_path)
                    pic_index += 1
    except Exception as e:
        print(f"[Warning] Failed to extract images for {base_name}: {e}")
        
    # 2. Sequentially replace '<!-- image -->' placeholders
    def replace_placeholder(match):
        nonlocal extracted_images
        if extracted_images:
            img_path = extracted_images.pop(0)
            return f"![]({img_path})"
        return "" # If no pictures left, remove the placeholder
        
    cleaned_markdown = re.sub(r"<!--\s*image\s*-->", replace_placeholder, markdown_text)
    return cleaned_markdown

def parse_docx(file_path: str) -> Tuple[List[str], Dict[int, str]]:
    """
    Converts a docx file to Markdown, extracts the answer key, and splits into question blocks.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
        
    converter = DocumentConverter()
    result = converter.convert(file_path)
    markdown_text = result.document.export_to_markdown()
    
    # Extract images and insert local links
    markdown_text = extract_and_replace_images(result, file_path, markdown_text)
    
    # Extract answers from end if they exist
    main_text, ans_dict = extract_answer_key(markdown_text)
    
    # Split questions
    question_blocks = split_questions(main_text)
    
    return question_blocks, ans_dict
