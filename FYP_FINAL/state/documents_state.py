from typing import TypedDict, List, Dict, Any, Optional

class DocumentsState(TypedDict, total=False):
    action:           str
    query:            str
    file_ids:         List[str]
    file_names:       List[str]
    folder_name:      str
    document_content: str
    documents:        List[Dict]
    user_name:        str
    output:           str
    metadata:         Dict[str, Any]
