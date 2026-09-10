import os
import io
import json
import re
import base64
from typing import Dict, List, Any, Optional, Tuple
from docx import Document
from docx.shared import Pt, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from dotenv import load_dotenv

from src.schemas import LevelEnum
from src.uploader import RemotePaperUploader

# Ensure env vars are loaded
load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.env"), override=False)

def create_element(name):
    return OxmlElement(name)

def set_cell_border(cell, **kwargs):
    """
    Set cell's border
    Usage:
    set_cell_border(
        cell,
        top={"sz": 12, "val": "single", "color": "D3D3D3"},
        bottom={"sz": 12, "color": "00FF00", "val": "single"},
        start={"sz": 24, "val": "dashed", "shadow": "true"},
        end={"sz": 12, "val": "dashed"},
    )
    """
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    tcBorders = tcPr.first_child_found_in("w:tcBorders")
    if tcBorders is None:
        tcBorders = OxmlElement('w:tcBorders')
        tcPr.append(tcBorders)

    for edge in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'):
        edge_data = kwargs.get(edge)
        if edge_data:
            tag = 'w:{}'.format(edge)
            element = tcBorders.find(qn(tag))
            if element is None:
                element = OxmlElement(tag)
                tcBorders.append(element)
            for key, val in edge_data.items():
                element.set(qn('w:{}'.format(key)), str(val))

def export_paper_to_md(set_label: str, questions: List[Dict[str, Any]], level_name: str, is_solutions: bool = False) -> str:
    """Generates a beautiful markdown string for the paper."""
    md = []
    title = "STATISTICS OLYMPIAD"
    subtitle = f"{level_name} — {set_label}"
    if is_solutions:
        subtitle += " (Solutions Manual)"
        
    md.append(f"# {title}")
    md.append(f"## {subtitle}\n")
    
    if not is_solutions:
        md.append("**Candidate Name:** ___________________________  \n**Roll Number:** _______________________________  \n")
        md.append("**Time Allowed:** 2 Hours  \n**Maximum Marks:** 120  \n")
        md.append("---")
        md.append("### INSTRUCTIONS\n1. Attempt all questions.\n2. For Multiple Choice Questions (MCQs), select the single best option.\n3. For Numeric questions, write the calculated numerical value clearly in the answer box.\n")
        md.append("---")
    else:
        # Generate a quick answer key table
        md.append("### QUICK ANSWER KEY")
        md.append("| Question | Topic | Correct Answer |")
        md.append("|---|---|---|")
        for i, q in enumerate(questions, start=1):
            ans = q.get("correct_answer", "N/A")
            topic = q.get("topic", "General").replace("_", " ").title()
            md.append(f"| {i} | {topic} | **{ans}** |")
        md.append("\n---\n")
        
    md.append("### QUESTIONS\n")
    
    for i, q in enumerate(questions, start=1):
        statement = q.get("statement", "").strip()
        # Strip trailing correct answer tags like [B], **[D]** from the end of statement text
        statement = re.sub(r'\s*\**\[[A-D]\]\**\s*$', '', statement).strip()
        q_type = q.get("type", "MCQ")
        
        md.append(f"#### Question {i}")
        md.append(f"{statement}\n")
        
        # Display options if MCQ
        if q_type == "MCQ" and q.get("options"):
            for opt_key, opt_val in q["options"].items():
                md.append(f"- **({opt_key})** {opt_val}")
            md.append("")
            
        if not is_solutions:
            if q_type == "Numeric":
                md.append("\n**Answer:** ___________________\n")
            else:
                md.append("\n**Selected Option:** ( A / B / C / D )\n")
            md.append("---")
        else:
            correct_ans = q.get("correct_answer", "N/A")
            explanation = q.get("explanation", "No solution provided.")
            topic = q.get("topic", "General").replace("_", " ").title()
            
            md.append(f"> **Correct Answer: ({correct_ans})**  ")
            md.append(f"> **Topic:** *{topic}*  ")
            md.append(f">  ")
            md.append(f"> **Solution/Explanation:**  ")
            md.append(f"> {explanation}")
            md.append("\n---")
            
    return "\n".join(md)

def export_paper_to_docx(set_label: str, questions: List[Dict[str, Any]], level_name: str, is_solutions: bool = False) -> Document:
    """Generates a highly-polished, print-ready Word document."""
    doc = Document()
    
    # Page setup
    section = doc.sections[0]
    section.top_margin = Inches(1.0)
    section.bottom_margin = Inches(1.0)
    section.left_margin = Inches(1.0)
    section.right_margin = Inches(1.0)
    
    # Styles config
    styles = doc.styles
    normal_style = styles['Normal']
    normal_style.font.name = 'Arial'
    normal_style.font.size = Pt(10.5)
    
    # 1. Header
    title_p = doc.add_paragraph()
    title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_run = title_p.add_run("STATISTICS OLYMPIAD")
    title_run.font.size = Pt(20)
    title_run.bold = True
    
    sub_p = doc.add_paragraph()
    sub_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    subtitle_text = f"{level_name} — {set_label}"
    if is_solutions:
        subtitle_text += " (Solutions Manual)"
    sub_run = sub_p.add_run(subtitle_text)
    sub_run.font.size = Pt(13)
    sub_run.bold = True
    
    doc.add_paragraph("_" * 60) # Divider line
    
    # Student Metadata fields
    if not is_solutions:
        meta_table = doc.add_table(rows=2, cols=2)
        meta_table.autofit = False
        meta_table.columns[0].width = Inches(3.2)
        meta_table.columns[1].width = Inches(3.2)
        
        c00 = meta_table.cell(0, 0).paragraphs[0]
        c00.add_run("Candidate Name: ___________________________").bold = True
        
        c01 = meta_table.cell(0, 1).paragraphs[0]
        c01.add_run("Roll Number: _______________________").bold = True
        
        c10 = meta_table.cell(1, 0).paragraphs[0]
        c10.add_run("Time Allowed: 2 Hours").font.italic = True
        
        c11 = meta_table.cell(1, 1).paragraphs[0]
        c11.add_run("Maximum Marks: 120").font.italic = True
        
        doc.add_paragraph("_" * 60)
        
        # Instructions Box
        inst_p = doc.add_paragraph()
        inst_run = inst_p.add_run("INSTRUCTIONS:\n")
        inst_run.bold = True
        inst_p.add_run("1. Attempt all questions.\n2. For Multiple Choice Questions (MCQs), circle or write the correct letter choice.\n3. For Numeric questions, compute the value and write it clearly in the answer blank.")
        
        # Add light borders around instructions
        for cell in inst_p.paragraph_format.element:
            pass # Docx margins handles spacing
            
        doc.add_page_break()
    else:
        # Teacher Answer Key table
        doc.add_heading("Quick Answer Key", level=2)
        table = doc.add_table(rows=1, cols=3)
        table.style = 'Light Shading Accent 1'
        hdr_cells = table.rows[0].cells
        hdr_cells[0].paragraphs[0].add_run("Question #").bold = True
        hdr_cells[1].paragraphs[0].add_run("Topic").bold = True
        hdr_cells[2].paragraphs[0].add_run("Answer Key").bold = True
        
        for i, q in enumerate(questions, start=1):
            row_cells = table.add_row().cells
            row_cells[0].paragraphs[0].add_run(str(i))
            row_cells[1].paragraphs[0].add_run(q.get("topic", "General").replace("_", " ").title())
            row_cells[2].paragraphs[0].add_run(f"({q.get('correct_answer', 'N/A')})").bold = True
            
        doc.add_page_break()
        
    # 2. Questions Listing
    doc.add_heading("QUESTIONS", level=1)
    
    for i, q in enumerate(questions, start=1):
        qp = doc.add_paragraph()
        q_num = qp.add_run(f"Question {i}.  ")
        q_num.bold = True
        q_num.font.size = Pt(11)
        
        statement = q.get("statement", "").strip()
        # Strip trailing correct answer tags like [B], **[D]** from the end of statement text
        statement = re.sub(r'\s*\**\[[A-D]\]\**\s*$', '', statement).strip()
        # Find any image markdown references
        img_match = re.search(r'!\[.*?\]\((.*?)\)', statement)
        if img_match:
            img_path = img_match.group(1).strip()
            # Remove the markdown image reference from the text we write
            clean_statement = re.sub(r'!\[.*?\]\((.*?)\)', '', statement).strip()
            qp.add_run(clean_statement)
            
            # Add the picture physically to the docx
            if os.path.exists(img_path):
                try:
                    img_p = doc.add_paragraph()
                    img_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    img_p.add_run().add_picture(img_path, width=Inches(4.5))
                except Exception as e:
                    doc.add_paragraph(f"[Image Render Error: {e}]")
            else:
                doc.add_paragraph(f"[Image file not found: {img_path}]")
        else:
            qp.add_run(statement)
        
        # Options spacing
        q_type = q.get("type", "MCQ")
        if q_type == "MCQ" and q.get("options"):
            options_dict = q["options"]
            # Render options in a 2x2 grid for clean vertical layout
            opt_table = doc.add_table(rows=2, cols=2)
            opt_table.autofit = True
            
            keys = ["A", "B", "C", "D"]
            for idx, key in enumerate(keys):
                row = idx // 2
                col = idx % 2
                cell = opt_table.cell(row, col)
                cell_p = cell.paragraphs[0]
                cell_p.add_run(f"({key}) ").bold = True
                cell_p.add_run(options_dict.get(key, ""))
            
            doc.add_paragraph() # Add vertical spacing
            
        if not is_solutions:
            ans_p = doc.add_paragraph()
            if q_type == "Numeric":
                ans_p.add_run("Answer: _______________________").bold = True
            else:
                ans_p.add_run("Selected Option:   [  A  /  B  /  C  /  D  ]").bold = True
            doc.add_paragraph("_" * 40)
        else:
            sol_p = doc.add_paragraph()
            ans_run = sol_p.add_run(f"Correct Answer: ({q.get('correct_answer', 'N/A')})\n")
            ans_run.bold = True
            ans_run.font.color.rgb = None # Standard colors
            
            sol_p.add_run("Solution / Explanation:\n").bold = True
            sol_p.add_run(q.get("explanation", ""))
            
            doc.add_paragraph("_" * 40)
            
    return doc

def export_paper_to_docx_bytes(
    set_label: str,
    questions: List[Dict[str, Any]],
    level_name: str,
    is_solutions: bool = False
) -> bytes:
    """Generates an in-memory byte buffer of the Word document."""
    doc = export_paper_to_docx(set_label, questions, level_name, is_solutions=is_solutions)
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.read()

def _process_statement_images(statement: str) -> Tuple[str, Optional[str]]:
    """
    Detects markdown image links ![caption](path), reads the image from disk if present,
    and converts it into a self-contained base64 data URI (data:image/...;base64,...).
    """
    img_match = re.search(r'!\[.*?\]\((.*?)\)', statement)
    if not img_match:
        return statement, None
    img_path = img_match.group(1).strip()
    data_uri = None
    if os.path.exists(img_path):
        try:
            with open(img_path, "rb") as f:
                raw_bytes = f.read()
            b64_str = base64.b64encode(raw_bytes).decode("utf-8")
            ext = os.path.splitext(img_path)[1].lstrip(".").lower() or "png"
            data_uri = f"data:image/{ext};base64,{b64_str}"
        except Exception:
            data_uri = None
    return statement, data_uri

def export_paper_to_json_bytes(
    set_label: str,
    questions: List[Dict[str, Any]],
    level_name: str,
    is_solutions: bool = False
) -> bytes:
    """Generates an in-memory JSON byte representation of the paper or solutions set."""
    if not is_solutions:
        # Student question paper: exclude correct answers & solutions
        clean_questions = []
        for i, q in enumerate(questions, start=1):
            statement = q.get("statement", "").strip()
            statement = re.sub(r'\s*\**\[[A-D]\]\**\s*$', '', statement).strip()
            statement, img_uri = _process_statement_images(statement)
            
            item = {
                "question_number": i,
                "statement": statement,
                "type": q.get("type", "MCQ")
            }
            if img_uri:
                item["image_data_uri"] = img_uri
            if q.get("type") == "MCQ" and q.get("options"):
                item["options"] = q["options"]
            clean_questions.append(item)
            
        payload = {
            "olympiad": "STATISTICS OLYMPIAD",
            "level": level_name,
            "set": set_label,
            "document_type": "Student Question Paper",
            "time_allowed": "2 Hours",
            "maximum_marks": 120,
            "instructions": [
                "Attempt all questions.",
                "For Multiple Choice Questions (MCQs), select the single best option.",
                "For Numeric questions, write the calculated numerical value clearly in the answer box."
            ],
            "total_questions": len(clean_questions),
            "questions": clean_questions
        }
    else:
        # Teacher solutions manual: include full answer keys, explanations, topics, and difficulties
        answer_key = {}
        full_questions = []
        for i, q in enumerate(questions, start=1):
            statement = q.get("statement", "").strip()
            statement = re.sub(r'\s*\**\[[A-D]\]\**\s*$', '', statement).strip()
            statement, img_uri = _process_statement_images(statement)
            correct_ans = q.get("correct_answer", "N/A")
            topic = q.get("topic", "General").replace("_", " ").title()
            explanation = q.get("explanation", "No solution provided.")
            
            answer_key[f"Question {i}"] = {
                "topic": topic,
                "correct_answer": correct_ans
            }
            
            item = {
                "question_number": i,
                "statement": statement,
                "type": q.get("type", "MCQ"),
                "topic": topic,
                "difficulty": q.get("difficulty", "medium"),
                "correct_answer": correct_ans,
                "explanation": explanation
            }
            if img_uri:
                item["image_data_uri"] = img_uri
            if q.get("type") == "MCQ" and q.get("options"):
                item["options"] = q["options"]
            full_questions.append(item)
            
        payload = {
            "olympiad": "STATISTICS OLYMPIAD",
            "level": level_name,
            "set": set_label,
            "document_type": "Solutions Manual & Answer Key",
            "total_questions": len(full_questions),
            "answer_key": answer_key,
            "questions": full_questions
        }
        
    return json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")


def export_all_compiled_papers(
    output_dir: str = "data/output",
    in_memory_booklets: Optional[Dict[str, Any]] = None,
    format_override: Optional[str] = None,
    save_local_override: Optional[bool] = None
) -> List[Dict[str, Any]]:
    """
    Exports question papers and answer sets.
    - If SAVE_LOCAL_FILES is True: writes .docx and .md files to output_dir.
    - If SAVE_LOCAL_FILES is False: streams directly in-memory without saving any files to device.
    - If AUTO_UPLOAD_ON_GENERATION is True: uploads files/bytes to the remote endpoint.
    """
    save_local = save_local_override if save_local_override is not None else (os.getenv("SAVE_LOCAL_FILES", "false").lower() in ("true", "1", "yes"))
    file_format = (format_override or os.getenv("UPLOAD_FILE_FORMAT", "json")).lower()
    auto_upload = os.getenv("AUTO_UPLOAD_ON_GENERATION", "true").lower() in ("true", "1", "yes")


    levels = [
        (LevelEnum.LEVEL_1, "question_paper_level_1.json", "Level 1"),
        (LevelEnum.LEVEL_2, "question_paper_level_2.json", "Level 2")
    ]
    
    print("\n============================================================")
    print("      STATISTICS OLYMPIAD EXPORT & UPLOAD PIPELINE")
    print(f"  Local File Storage:      {'ENABLED (data/output/)' if save_local else 'DISABLED (Pure In-Memory)'}")
    print(f"  Remote Upload:           {'ENABLED' if auto_upload else 'DISABLED'}")
    print(f"  Transmission Format:     {file_format.upper()}")
    print("============================================================\n")
    
    uploader = RemotePaperUploader(file_format=file_format, save_local_files=save_local) if auto_upload else None
    upload_results = []
    
    for lvl_enum, filename, lvl_label in levels:
        booklets = None
        
        # 1. Check in-memory booklets first
        if in_memory_booklets and lvl_enum.value in in_memory_booklets:
            booklets = in_memory_booklets[lvl_enum.value]
        elif in_memory_booklets and lvl_label in in_memory_booklets:
            booklets = in_memory_booklets[lvl_label]
            
        # 2. Otherwise fall back to local JSON file if it exists
        if not booklets:
            json_path = os.path.join(output_dir, filename)
            if os.path.exists(json_path):
                try:
                    with open(json_path, "r", encoding="utf-8") as f:
                        booklets = json.load(f)
                except Exception as e:
                    print(f"[Warning] Could not read {json_path}: {e}")
                    
        if not booklets:
            print(f"[Notice] No booklet data available for {lvl_label} ({filename}). Skipping.")
            continue
            
        print(f"\nProcessing {lvl_label} booklets...")
        sets_dict = booklets.get("sets", {})
        
        lvl_out_dir = os.path.join(output_dir, lvl_label.lower().replace(" ", "_"))
        if save_local:
            os.makedirs(lvl_out_dir, exist_ok=True)
            
        for set_label, questions in sets_dict.items():
            set_clean_name = set_label.lower().replace(" ", "_")
            lvl_clean_name = lvl_label.lower().replace(" ", "_")
            
            # Prepare in-memory byte contents for both questions and answers
            if file_format == "docx":
                student_bytes = export_paper_to_docx_bytes(set_label, questions, lvl_label, is_solutions=False)
                solutions_bytes = export_paper_to_docx_bytes(set_label, questions, lvl_label, is_solutions=True)
                student_filename = f"{lvl_clean_name}_{set_clean_name}_questions.docx"
                solutions_filename = f"{lvl_clean_name}_{set_clean_name}_solutions.docx"
            else: # default: json
                student_bytes = export_paper_to_json_bytes(set_label, questions, lvl_label, is_solutions=False)
                solutions_bytes = export_paper_to_json_bytes(set_label, questions, lvl_label, is_solutions=True)
                student_filename = f"{lvl_clean_name}_{set_clean_name}_questions.json"
                solutions_filename = f"{lvl_clean_name}_{set_clean_name}_solutions.json"
                
            # Optional Local Disk Saving
            if save_local:
                student_doc_path = os.path.join(lvl_out_dir, f"{set_clean_name}_questions.docx")
                student_md_path = os.path.join(lvl_out_dir, f"{set_clean_name}_questions.md")
                solutions_doc_path = os.path.join(lvl_out_dir, f"{set_clean_name}_solutions.docx")
                solutions_md_path = os.path.join(lvl_out_dir, f"{set_clean_name}_solutions.md")
                
                try:
                    student_doc = export_paper_to_docx(set_label, questions, lvl_label, is_solutions=False)
                    student_doc.save(student_doc_path)
                except Exception as e:
                    print(f"  [Warning] Failed saving student docx locally: {e}")
                    
                try:
                    student_md = export_paper_to_md(set_label, questions, lvl_label, is_solutions=False)
                    with open(student_md_path, "w", encoding="utf-8") as f:
                        f.write(student_md)
                except Exception as e:
                    print(f"  [Warning] Failed saving student md locally: {e}")
                    
                try:
                    sol_doc = export_paper_to_docx(set_label, questions, lvl_label, is_solutions=True)
                    sol_doc.save(solutions_doc_path)
                except Exception as e:
                    print(f"  [Warning] Failed saving solutions docx locally: {e}")
                    
                try:
                    sol_md = export_paper_to_md(set_label, questions, lvl_label, is_solutions=True)
                    with open(solutions_md_path, "w", encoding="utf-8") as f:
                        f.write(sol_md)
                except Exception as e:
                    print(f"  [Warning] Failed saving solutions md locally: {e}")
                    
                print(f"  -> Saved local files for {lvl_label} Set {set_label} in {lvl_out_dir}/")
            else:
                print(f"  -> Generated {lvl_label} Set {set_label} strictly in-memory (0 disk writes).")
                
            # Remote Upload Stream
            if uploader:
                try:
                    # 1. Upload Student Question Paper
                    q_res = uploader.upload_paper_item(
                        item_bytes=student_bytes,
                        filename=student_filename,
                        meta_label=f"{lvl_label} - Set {set_label} (Questions)"
                    )
                    upload_results.append(q_res)
                    
                    # 2. Upload Solutions Manual & Answer Key
                    a_res = uploader.upload_paper_item(
                        item_bytes=solutions_bytes,
                        filename=solutions_filename,
                        meta_label=f"{lvl_label} - Set {set_label} (Solutions & Answer Key)"
                    )
                    upload_results.append(a_res)
                except Exception as e:
                    print(f"  [Remote Uploader Error] Failed to upload Set {set_label}: {e}")
                    
    print("\nExport & upload pipeline complete.")
    return upload_results


if __name__ == "__main__":
    # Test execution
    export_all_compiled_papers()
