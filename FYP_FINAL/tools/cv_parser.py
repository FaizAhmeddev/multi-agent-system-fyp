"""
CV FILE PARSER - COMPLETELY FIXED
==================================
Extracts text from uploaded PDF and DOCX CV files with full error handling
"""

import os
import re


def extract_text_from_pdf(file_path: str) -> str:
    """Extract text from PDF file with error handling."""
    try:
        from pypdf import PdfReader
        
        if not os.path.exists(file_path):
            return f"Error: File not found at {file_path}"
        
        reader = PdfReader(file_path)
        text = ""
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
        
        if not text.strip():
            return "Error: Could not extract text from PDF. The file might be scanned or password-protected."
        
        return text.strip()
        
    except ImportError:
        return "Error: pypdf library not installed. Run: pip install pypdf"
    except Exception as e:
        return f"Error reading PDF: {str(e)}"


def extract_text_from_docx(file_path: str) -> str:
    """Extract text from DOCX file with error handling."""
    try:
        from docx import Document
        
        if not os.path.exists(file_path):
            return f"Error: File not found at {file_path}"
        
        doc = Document(file_path)
        text = ""
        for para in doc.paragraphs:
            if para.text.strip():
                text += para.text + "\n"
        
        if not text.strip():
            return "Error: Could not extract text from DOCX. The file might be empty or corrupted."
        
        return text.strip()
        
    except ImportError:
        return "Error: python-docx library not installed. Run: pip install python-docx"
    except Exception as e:
        return f"Error reading DOCX: {str(e)}"


def extract_candidate_name(text: str, filename: str = "") -> str:
    """
    Try to extract candidate name from CV text or filename.
    """
    if not text or text.startswith("Error:"):
        # Try to get name from filename
        if filename:
            # Remove extension and common CV words
            name = os.path.splitext(os.path.basename(filename))[0]
            name = re.sub(r'(?i)(cv|resume|_|-)', ' ', name)
            name = ' '.join(name.split()).strip()
            if name and len(name) > 2:
                return name.title()
        return "Candidate"
    
    # Take first 500 chars where name usually appears
    header = text[:500]
    
    # Common name patterns
    lines = header.split('\n')
    for line in lines[:10]:  # Check first 10 lines
        line = line.strip()
        # Skip empty lines, emails, phone numbers, addresses
        if not line:
            continue
        if '@' in line or 'http' in line.lower():
            continue
        if any(char.isdigit() for char in line) and len([c for c in line if c.isdigit()]) > 3:
            continue
        if len(line) > 50:  # Names are usually short
            continue
            
        # Name is usually 2-4 words, all capitalized or title case
        words = line.split()
        if 2 <= len(words) <= 4:
            # Check if it looks like a name
            if all(word[0].isupper() for word in words if word and len(word) > 1):
                # Exclude common headers
                if not any(header_word in line.upper() for header_word in 
                          ['CURRICULUM', 'RESUME', 'CV', 'PROFILE', 'OBJECTIVE']):
                    return line
    
    # Try filename as backup
    if filename:
        name = os.path.splitext(os.path.basename(filename))[0]
        name = re.sub(r'(?i)(cv|resume|_|-)', ' ', name)
        name = ' '.join(name.split()).strip()
        if name and len(name) > 2:
            return name.title()
    
    # Fallback: return first non-empty line
    for line in lines[:5]:
        if line.strip() and '@' not in line and len(line) < 50:
            return line.strip()
    
    return "Candidate"


def parse_cv_file(file_path: str) -> dict:
    """
    Parse a CV file (PDF or DOCX) and return name + content.
    
    Returns:
        {
            "name": str,
            "content": str,
            "file_name": str,
            "status": "success" | "error",
            "error_message": str (if status is error)
        }
    """
    result = {
        "name": "Candidate",
        "content": "",
        "file_name": os.path.basename(file_path) if file_path else "unknown",
        "status": "success",
        "error_message": ""
    }
    
    try:
        if not file_path:
            result["status"] = "error"
            result["error_message"] = "No file path provided"
            result["content"] = "Error: No file path provided"
            return result
        
        if not os.path.exists(file_path):
            result["status"] = "error"
            result["error_message"] = f"File not found: {file_path}"
            result["content"] = f"Error: File not found at {file_path}"
            return result
        
        file_name = os.path.basename(file_path)
        ext = file_name.lower().split('.')[-1]
        
        # Extract text based on file type
        if ext == 'pdf':
            text = extract_text_from_pdf(file_path)
        elif ext in ['docx', 'doc']:
            text = extract_text_from_docx(file_path)
        else:
            result["status"] = "error"
            result["error_message"] = f"Unsupported file type: {ext}"
            result["content"] = f"Error: Unsupported file type: {ext}. Please upload PDF or DOCX files."
            return result
        
        # Check if extraction had errors
        if text.startswith("Error:"):
            result["status"] = "error"
            result["error_message"] = text
            result["content"] = text
            result["name"] = extract_candidate_name("", file_name)
            return result
        
        # Try to extract candidate name
        name = extract_candidate_name(text, file_name)
        
        result["name"] = name
        result["content"] = text
        result["file_name"] = file_name
        
        return result
        
    except Exception as e:
        result["status"] = "error"
        result["error_message"] = str(e)
        result["content"] = f"Error processing file: {str(e)}"
        result["name"] = extract_candidate_name("", file_path)
        return result


def parse_multiple_cvs(file_paths: list) -> list:
    """
    Parse multiple CV files with error handling.
    
    Args:
        file_paths: List of file paths
    
    Returns:
        List of dicts with name, content, file_name, status, error_message
    """
    if not file_paths:
        return []
    
    results = []
    for path in file_paths:
        cv_data = parse_cv_file(path)
        results.append(cv_data)
    
    return results


def validate_cv_content(cv: dict) -> tuple:
    """
    Validate if CV was parsed successfully.
    
    Returns:
        (is_valid: bool, error_message: str)
    """
    if cv.get("status") == "error":
        return False, cv.get("error_message", "Unknown error")
    
    content = cv.get("content", "")
    if not content or len(content.strip()) < 50:
        return False, "CV content is too short or empty"
    
    if content.startswith("Error:"):
        return False, content
    
    return True, ""
