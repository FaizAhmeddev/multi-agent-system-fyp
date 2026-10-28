# Sandbox data (synthetic)

Everything here is invented for demos and tests. No real people, addresses or numbers.

- `inbox.json` is the simulated Gmail inbox used by workspace-mcp when Google is not set up.
  One message is deliberately hostile (a prompt-injection attempt) to test that AgentsMind
  treats email text as data, not instructions.
- `drive/` is the simulated Google Drive. `HR/CVs/CV_Hostile_Candidate.txt` is a deliberately
  hostile CV for the same reason.

Results from these files are always marked `simulated: true` and shown as "Simulated".
