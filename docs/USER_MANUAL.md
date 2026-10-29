# User manual

Open AgentsMind at the address your administrator gives you (on the demo laptop:
http://127.0.0.1:8000) and sign in with your email and password.

## Everyone

**Hub.** Your departments, anything waiting for your approval, and your recent conversations.
A locked tile tells you which role it needs.

**Assistant.** Type what you need in plain language:

- "Schedule a design review tomorrow at 3 pm for 45 minutes with a Google Meet link"
- "Am I free Friday afternoon?"
- "Move my 3 pm meeting to 4 pm", or "Cancel Monday's review meeting"
- "My laptop keeps disconnecting from the VPN, please raise a ticket"
- "What's the status of ITK-000123?"
- "Show my unread emails", "Reply to Usman saying Friday 3 pm works", "Draft replies to my unread emails"

While it works you see each step. Results come back as cards:

- **Approval card.** Shows exactly what will happen: the time it understood in your time zone, conflicts, attendees, recipients and the message. Press **Approve** or **Reject**. For a delete or cancel, you type the name first.
- **Question.** When a detail is missing, the assistant asks. Answer in the next message or press one of the suggested options.
- **Not available to your role.** That department needs a role you do not have.
- **Simulated.** No real calendar, mailbox, file store or model was used, and nothing reached real people.

**Approvals.** Every proposed action with its exact arguments, pending or decided. You can
approve or reject from here as well.

**IT.** Press **New complaint**, choose your department, category and priority, and describe
the problem. You get a ticket number, the expected response time, and links to the IT
Helpdesk confirmation and tracking pages. You see only your own tickets.

**Communications.**

- **Inbox:** messages marked **Suspicious** contain instructions aimed at an AI. Do not act on them without checking with the sender.
- **New email** and **Reply:** you always review the email before it is sent.
- **Calendar:** shows the next 14 days. **New event** checks for conflicts as you choose a time.

**Settings.** Your account details, the Light, Dark or Match system theme, and password change.

## HR (role: hr)

Open **HR** or ask the Assistant. Anything that reaches people or other systems (emails, IT tickets, payroll,
calendar invites, WhatsApp, rows in your sheets) is shown on one approval card first; after you approve, every
step runs in order and ticks off its checklist item. A failed step shows the reason and a **Retry** button.

| Tab | What you do there | Ask the Assistant, for example |
|---|---|---|
| Overview | Headcount, joiners, leave to decide, overdue items, quick reports | "New joiners report for this month" |
| Employees | Records, checklists (onboarding, induction, compliance, separation), letters, leave, attendance | "Onboard Sara Khan as Python Developer in Engineering joining 1 December, salary 150,000, email sara@company.pk, phone 03001234567" |
| Recruitment | Gather CVs from Gmail, the CV folders and Drive; only Karachi candidates are screened; job openings; candidates board | "Screen CVs from Gmail for the Python Developer role", "Issue an offer letter to Sara Khan" |
| Attendance and leave | Pending leave (approve/reject), attendance summary, mark attendance, import from your sheet | "Mark Bilal absent today", "Approve Ahmed's leave", "Import attendance from my attendance sheet" |
| Payroll | Monthly payroll from salaries, attendance and unpaid leave; post to the Finance Portal | "Run payroll for October" |
| Letters | Offer, contract, welcome, conduct, resignation acceptance, final settlement, experience: Word and PDF; email them | "Warning letter for Bilal for repeated late arrival" |
| Reports | New joiners, induction, onboarding, separations, attendance, leave, compliance, payroll, headcount; Excel download | "Who resigned this month?", "Induction report for October" |
| Sheets | Register your Google Sheets and Excel files and what each holds | "Where do I keep the leave records?", "Show Ahmed's leaves from my leave sheet" |
| HR settings | Company details for letters, candidate city, office hours, leave entitlements, payroll rules | "How many casual leaves do we get per year?" |

Separation: "Ahmed Raza resigned, last working day 30 November" starts the checklist, the acceptance letter, the IT
asset ticket and the exit interview. "Final settlement for Ahmed Raza" shows every line of the settlement and, after
approval, issues the final settlement letter and experience certificate and closes payroll.

Your own letter formats: put `offer.docx`, `contract.docx` and so on in `data\hr_templates` with placeholders such
as `{{name}}`, `{{job_title}}`, `{{joining_date}}`, `{{salary}}`.

Statutory rates (income tax, EOBI, SESSI) change every year, so AgentsMind never invents them: set them in HR
settings, or leave them at 0 and the payroll card says they were not applied.

## Everyone: attendance and leave

On the Hub, **My attendance and leave** has Check in / Check out, your leave balance and a leave form. You can also
say "Check in", "I want casual leave on 5 November" or "How many leaves do I have left?". Your sign-in email must
match your employee record.

## IT staff (role: it)

- See every ticket, filter by status and priority, and open a ticket to read its comments.
- Move a ticket along the workflow: open, then in progress, then resolved, then closed. A resolved ticket can be reopened; a closed ticket is final.
- Comment on any ticket. Or ask the assistant: "Mark ITK-000123 as resolved".
- The IT Helpdesk staff screens (http://127.0.0.1:8202/staff) show the same tickets with SLA due times.

## Finance (role: finance)

- **Summary.** Headcount and monthly payroll per currency and department, computed by SQL in the Finance Portal.
- **People:**
  - Search, filter, add and edit records.
  - **Download CSV** gives the rows on screen.
  - Deleting a person also deletes their payment records, and you must type their full name first.
- **Payments.** Filter by month and status.
- **Assistant:** "What is the total monthly payroll?", "Find Ahmed Raza", "Change Ahmed Raza's salary to 150,000" (approval card), "Delete the record for Ahmed Raza" (approval card with typed name).

## Documents (roles: hr, it, finance)

Search Drive by name or text, open a file to read it, press **Summarize**, or **Compare** it
with another file. File text is outside content: AgentsMind never follows instructions found
in it.

## Admin (role: admin)

Admins can use every department and see everything in Approvals. The Admin page has five tabs:

| Tab | What you can do |
|---|---|
| Users | Create accounts, set roles, unlock locked accounts |
| System | See whether each MCP server is reachable and has all its tools; see queue counts and retry dead tasks |
| Tool calls | See every tool call with its status and latency, including denials |
| Audit log | See sign-ins, denials, approvals and changes |
| Outbox | Read system emails, such as password reset codes, while no mail server is configured |

## Forgot your password

On the sign-in page, press **Forgot your password?** and enter your email. While no mail
server is set up, ask an admin for the code from the Outbox tab. Then open **I have a reset
code** and choose a new password of at least 12 characters.
