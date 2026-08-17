import os
import json
import re
from typing import Dict, List, Any
from docx import Document
from docx.shared import Pt, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from src.schemas import LevelEnum

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

def export_all_compiled_papers(output_dir: str = "data/output"):
    """
    Scans the data/output folder for question_paper_level_1.json and
    question_paper_level_2.json, and exports all sets (A, B, C) to Word and Markdown.
    """
    levels = [
        (LevelEnum.LEVEL_1, "question_paper_level_1.json", "Level 1"),
        (LevelEnum.LEVEL_2, "question_paper_level_2.json", "Level 2")
    ]
    
    print("\n============================================================")
    print("      EXPORTING EXAM PAPERS TO WORD & MARKDOWN")
    print("============================================================\n")
    
    for lvl_enum, filename, lvl_label in levels:
        json_path = os.path.join(output_dir, filename)
        if not os.path.exists(json_path):
            print(f"[Warning] JSON file not found for {lvl_label}: {filename}. Skipping.")
            continue
            
        print(f"Reading generated booklets for {lvl_label} from: {filename}")
        with open(json_path, "r", encoding="utf-8") as f:
            booklets = json.load(f)
            
        # Create output folders
        lvl_out_dir = os.path.join(output_dir, lvl_label.lower().replace(" ", "_"))
        os.makedirs(lvl_out_dir, exist_ok=True)
        
        # Get the nested 'sets' dictionary from the JSON structure
        sets_dict = booklets.get("sets", {})
        
        for set_label, questions in sets_dict.items():
            set_clean_name = set_label.lower().replace(" ", "_")
            
            # 1. Export Student Version (.docx)
            student_doc_path = os.path.join(lvl_out_dir, f"{set_clean_name}_questions.docx")
            try:
                student_doc = export_paper_to_docx(set_label, questions, lvl_label, is_solutions=False)
                student_doc.save(student_doc_path)
                has_student_docx = True
            except PermissionError:
                print(f"  [Warning] Permission denied writing {os.path.basename(student_doc_path)}. (File open in Word? Skipping docx).")
                has_student_docx = False
            except Exception as e:
                print(f"  [ERROR] Failed to save student docx: {e}")
                has_student_docx = False
                
            # 2. Export Student Version (.md)
            student_md_path = os.path.join(lvl_out_dir, f"{set_clean_name}_questions.md")
            try:
                student_md = export_paper_to_md(set_label, questions, lvl_label, is_solutions=False)
                with open(student_md_path, "w", encoding="utf-8") as file:
                    file.write(student_md)
                has_student_md = True
            except Exception as e:
                print(f"  [ERROR] Failed to save student md: {e}")
                has_student_md = False
                
            # 3. Export Solutions Version (.docx)
            solutions_doc_path = os.path.join(lvl_out_dir, f"{set_clean_name}_solutions.docx")
            try:
                solutions_doc = export_paper_to_docx(set_label, questions, lvl_label, is_solutions=True)
                solutions_doc.save(solutions_doc_path)
                has_sol_docx = True
            except PermissionError:
                print(f"  [Warning] Permission denied writing {os.path.basename(solutions_doc_path)}. (File open in Word? Skipping docx).")
                has_sol_docx = False
            except Exception as e:
                print(f"  [ERROR] Failed to save solutions docx: {e}")
                has_sol_docx = False
                
            # 4. Export Solutions Version (.md)
            solutions_md_path = os.path.join(lvl_out_dir, f"{set_clean_name}_solutions.md")
            try:
                solutions_md = export_paper_to_md(set_label, questions, lvl_label, is_solutions=True)
                with open(solutions_md_path, "w", encoding="utf-8") as file:
                    file.write(solutions_md)
                has_sol_md = True
            except Exception as e:
                print(f"  [ERROR] Failed to save solutions md: {e}")
                has_sol_md = False
                
            print(f" -> Generated Set {set_label}:")
            if has_student_docx or has_student_md:
                print(f"    - Student Book: {os.path.basename(student_doc_path) if has_student_docx else '[Skipped]'} | {os.path.basename(student_md_path) if has_student_md else '[Skipped]'}")
            if has_sol_docx or has_sol_md:
                print(f"    - Solutions Key: {os.path.basename(solutions_doc_path) if has_sol_docx else '[Skipped]'} | {os.path.basename(solutions_md_path) if has_sol_md else '[Skipped]'}")
                
    print("\nExport completed successfully! Documents are stored in subfolders inside data/output/.")

if __name__ == "__main__":
    # Test execution
    export_all_compiled_papers()
