# Smart Complaint Management System (SCMS)
​
A planned web-based system for registering, routing, resolving, and tracking campus and hostel complaints at PES University, Bangalore.
​
**Team:** Team 6  
**Course:** UE24CS341A — Software Engineering
​
## Repository Contents
​
The current folder contains this README and four project documents.
​
```text
smart-complaint-management-system/
├── README.md
└── docs/
    ├── Team6_Synopsis.pdf
    ├── Team6_SRS.pdf
    ├── Team6_SAD.pdf
    └── Team6_STP.pdf
```
​
## Documentation
​
| Document | Description |
| --- | --- |
| [Synopsis / Project Proposal](docs/Team6_Synopsis.pdf) | Project overview, objectives, team responsibilities, and development plan |
| [Software Requirements Specification](docs/Team6_SRS.pdf) | System features, use cases, security requirements, and requirement traceability |
| [Software Architecture and Design](docs/Team6_SAD.pdf) | Planned architecture, components, data design, diagrams, and web interfaces |
| [Software Test Plan](docs/Team6_STP.pdf) | Testing approach, responsibilities, and representative test cases |
​
## Planned Features
​
- Complaint submission with optional evidence attachments
- Anonymous complaint submission and reference-based tracking
- Automatic routing by category and location
- Department queues and resolver assignment
- Due dates and escalation of overdue complaints
- Status tracking and complaint history
- Resolution confirmation, feedback, and reopening
- In-app and email notifications
- Role-based access, dashboards, reports, and CSV export
​
### Main Workflow
​
**Submit → Route to Department → Assign Resolver → Work in Progress → Resolve → Confirm / Give Feedback → Close**
​
The documents also cover reopening and automatic closure. Escalation increases visibility of overdue work; it does not automatically reassign a complaint.
​
## Team and Functional Areas
​
| Member | Area | Responsibilities |
| --- | --- | --- |
| Anushka K Kishore | F1 — Foundation and Access | Authentication, roles and permissions, user/department management, administrator reports, and CSV export |
| Atul Suresh | F2 — Complaint Intake and Evidence | Complaint submission, validation, IDs, attachments, and anonymous submission/tracking |
| Chaitanya Krishna Makkena | F3 — Routing, Assignment and Escalation | Routing rules, queues, assignment/reassignment, due dates, and escalation |
| Tanmay Sridhar | F4 — Resolution, Notifications and Tracking | Complaint lifecycle/history, resolution, feedback/reopening, notifications, and Complainant/Head dashboards |
​
## Planned Technology
​
The SAD describes a single layered Django application with F1–F4 functional modules.
​
- **Application:** Python and Django
- **Frontend:** Django templates, HTML, CSS, and JavaScript
- **Database:** PostgreSQL for deployment and SQLite for local development
- **Files and email:** Django file storage and email backend with SMTP
- **Scheduled tasks:** Django management commands
- **Version control and planning:** Git, GitHub, and GitHub Projects
- **Testing:** pytest, Django test client, and coverage reporting
- **Delivery and quality:** Jenkins, Docker, code review, security validation, and static analysis
​
## Development Plan
​
The Synopsis outlines six Agile sprints: setup and access, complaint intake, routing and assignment, lifecycle management, escalation and notifications, then reporting, validation, and the final demonstration.
​
## Testing
​
The Test Plan includes 15 representative cases for functional behaviour, security, and nonfunctional requirements. Their recorded status is **Not Executed**. It also describes reliability checks, usability walkthroughs, and code/build reviews. Refer to the STP for the detailed testing approach and expected results.
​
## Scope
​
The documents describe Release 1.0 as a single-campus, English-language, online browser application. SCMS manages the complaint workflow; physical repairs and emergency response are outside its scope. Other exclusions and items requiring clarification are listed in the SRS and SAD.
​
## Getting Started
​
Start with the Synopsis, then review the SRS, SAD, and Test Plan in `docs/`. The supplied folder does not contain application source code or setup files, so this README does not include installation or run commands.