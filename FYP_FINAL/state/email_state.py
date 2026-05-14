from typing import TypedDict, List

class EmailState(TypedDict, total=False):
    action:        str
    recipient:     str
    subject:       str
    body:          str
    emails:        List[dict]
    email_content: str
    sender_name:   str
    sender_email:  str
