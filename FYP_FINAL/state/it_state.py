from typing import TypedDict, Optional

class ITState(TypedDict, total=False):
    user_name:   str
    it_problem:  str
    it_solution: str
    it_handled:  bool
    agent_used:  str
    message:     str
