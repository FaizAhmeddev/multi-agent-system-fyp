from typing import TypedDict, List, Dict, Any

class HRState(TypedDict, total=False):
    action:          str
    job_description: str
    cvs:             List[Dict[str, Any]]
    results:         List[Dict[str, Any]]
    candidate_name:  str
    cv_content:      str
    job_title:       str
    department:      str
    query:           str
    user_name:       str
    output:          Any
    policy_context:  str
    top_n:           int
    company_name:    str
