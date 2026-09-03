# PrimaLux Data & AI Journey — Cora working knowledge

**Audience:** the operator in this thread, about **their** credit union.  
**Voice:** operator-facing. Cite this file as `primalux-data-ai-journey.md`. Separate **framework fact** from **general practice**.  
**Do not** invent a regulation, exam finding, phase, score, or **institution name**. You do not know the credit union unless they typed it in this thread. Say "your credit union" / "this institution." Never use a name from a demo, seed, or example. Regulator text lives in other Library files (NCUA, NIST AI RMF, FFIEC, CFPB, Federal Reserve, FDIC, OCC) — if those files are missing, say so.

**Sources (PrimaLux-authored):**

| Source | Where |
|---|---|
| Data & AI Journey Navigator Framework v1.1 (Continuous Discipline edition) | Google Drive `PrimaLux_Data_AI_Journey_Navigator_Framework.md` (file id `1NAVaDN5S0cqTsh09S83bWJ5eB5bcpFaW`, 2026-08-14) and Navigator repo `docs/framework-reference.md` |
| Customer language | Navigator repo `docs/customer-lexicon.md` |
| Domain enumerations and cadence labels | Navigator repo `packages/domain/src/constants.ts`, `packages/domain/src/journey.ts`, `docs/domain-model.md` |
| Product surface | Navigator repo `README.md` — hosted app at https://navigator.primaluxadvisory.com |
| Orchestration / intake pattern (advisory, not a Navigator screen) | Google Drive `navigator-orchestration-layer.md` (file id `1brNzIxoGpO2oFaLGQ7bWcHi9fKtEDRQS`) |

PPTX/DOCX Journey briefs on Drive (Master Program, Board Executive Briefing, LinkedIn Brief, Profile Framework, Assessment Workbook, KPI Framework) exist as originals. This file is the operator-safe digest of the **authoritative v1.1 framework** plus the **words on the screen**.

---

## 1. What this is (framework fact)

The **Data & AI Journey Navigator** is a practitioner-built framework that helps an organization move from fragmented AI activity to **continuous, defensible discipline**.

It exists because:

- AI is already inside most institutions (vendor products, copilots, scoring, automation).
- Snapshot governance (a policy written for an exam or a one-time board pack) does not last.
- Boards and examiners want a defensible answer to **“Are we exposed?”** — not a narrative and not a one-time assessment.
- Generic maturity models often assume enterprise staffing that a mid-sized credit union does not have, so nothing gets implemented.

The Navigator is designed to be:

- **Right-sized** — sequenced to real capacity, not an enterprise playbook.
- **Continuous** — an operating system, not a binder.
- **Evidence-oriented** — something leadership and examiners can actually look at, and that stays current.
- **Value-linked** — compliance and business value move together.
- **Adaptive** — a **journey** through changing conditions, not a fixed roadmap.

**Tagline (framework):** *Shoulder to shoulder, every step of the journey.*

**Closing orientation (preferred):**

> The goal is not a better set of documents. It is an organization that can answer, on any ordinary day, whether it is exposed — and what it is doing about it. This is a journey, not a fixed plan. Technology and regulation keep moving. The organizations that stay upright are the ones that can read conditions, adjust, and keep progressing safely.

---

## 2. Words to use with operators (customer language)

Internal engineering still says “swimlane” and “Critical Gap.” **Do not put those on a screenshotable answer.**

| Say this | Meaning | Do not say |
|---|---|---|
| Six **areas of the business** | Strategy, data, technology, governance, people, process | swimlane, heatmap |
| Discover → Stabilize → **Operationalize** → Scale → **Continuous Discipline** | Where the organization is | Embed as a final phase; “make it routine” as a phase name |
| Aware → Reactive → Proactive → Managed → Embedded | How strong an area is | Raw `L1`–`L5` as the headline |
| **What needs attention first** | Area lagging the strongest by two or more levels | “Critical Gaps” as a branded heading |
| **Journey Navigator** | This licensed workspace | Unqualified “Navigator” if it could mean the whole Program |
| **Journey Assessment** | The scored conversation that starts the path | “AI Readiness Assessment,” “quick check” |
| Journey, phased journey plan, sequenced to capacity | How work is ordered | Roadmap as a fixed perfect path |
| Record that stays current / something you can actually show | Evidence | “Evidence that travels”; black-box score |
| Operating rhythm / ordinary work | How it stays alive | Snapshot governance; “maturity project” |
| Read conditions, adjust, keep progressing safely | How you navigate | “Execute the plan” |

**Rule that does not change:** an area **needs attention first** when it lags the strongest area by **≥ 2 maturity levels**. If none do: “No area currently lags the strongest area by two or more maturity levels.”

---

## 3. Six areas of the business (framework fact)

Work is organized across six areas. Strength is scored **per area** and for the institution. Uneven strength creates friction and risk. Progress in one area is often constrained by a lagging area — that dependency is intentional.

| # | Area (say this) | Focus |
|---|---|---|
| 1 | **Strategy & Use Cases** | Which AI and data efforts matter most, who owns them, whether investment matches strategy and risk appetite. A living **use-case portfolio**. At Managed and Embedded, each **material** use case needs a **value hypothesis** and a measurement approach — **no invented ROI**. |
| 2 | **Data Foundations** | Whether critical data is owned, trustworthy, inventoried, and ready to support AI and analytics (quality, lineage, inventory). |
| 3 | **Technology & Infrastructure** | Platforms, tools, security, integrations — and the system choices that help or limit AI and data work. |
| 4 | **Governance & Risk** | Policies, oversight, risk classification, inventories of AI uses and important vendors, how exceptions are handled. |
| 5 | **People & Operating Model** | Roles, skills, accountability, who runs the meeting rhythm, training, cultural readiness. |
| 6 | **Process & Workflow** | Documented, recurring ways of working so governance and data/AI are ordinary operations — not one-off projects. |

---

## 4. Five phases (framework fact)

The journey moves through five phases. The last phase is **Continuous Discipline** (not “Embed”). Progress is not strictly linear. An institution may need to **re-stabilize** an area when conditions change.

| Phase | Intent |
|---|---|
| **Discover** | Get a clear picture: what is running, who owns it, where the biggest gaps and exposures are. |
| **Stabilize** | Close the most dangerous gaps. Name owners. Put basic controls in place so you are no longer flying blind. |
| **Operationalize** | Turn governance and data/AI management into recurring habits with owners, meetings, and proof. |
| **Scale** | Extend coverage and deepen strength across more areas and use cases — without overrunning capacity. |
| **Continuous Discipline** | Good practice becomes ordinary operations. You can answer “are we exposed?” on any normal day. |

**Journey river (product language):** Stabilize and Operationalize are the rapids (more active effort). Scale is clearer water. Continuous Discipline is ready for the next river. Do not describe this as a heatmap, hype curve, or pizza.

**Typical target strength for the current phase** (Navigator domain, `journey.ts` — this is a planning aid, not a grade):

| Phase of focus | Typical target |
|---|---|
| Discover | Reactive |
| Stabilize | Proactive |
| Operationalize | Proactive |
| Scale | Managed |
| Continuous Discipline | Embedded |

Next-focus logic (framework): if any area needs attention first, stabilize those areas before claiming the next phase. Prefer a few **owned actions with proof** over a plan that sits on a shelf.

---

## 5. Maturity words (framework fact)

Each area is scored on a five-level scale. Scoring is **evidence-based**. Black-box scores and unsupported self-ratings are rejected. **Human review is required.**

| Strength | Meaning |
|---|---|
| **Aware** | The topic is known. Little formal structure, ownership, or evidence. |
| **Reactive** | Activity mainly after a problem, exam, or outside pressure. Ownership unclear or inconsistent. |
| **Proactive** | Formal processes, owners, and some recurring practice. Coverage incomplete and still fragile. |
| **Managed** | Processes are reliable, owned, measured, and reviewed on cadence. Evidence is current and usable. |
| **Embedded** | Practices are part of normal operations (Continuous Discipline). Governance and value delivery continue without a special project. |

---

## 6. What needs attention first (framework fact)

**Working rule:** any area that lags the strongest area by **two or more levels** needs attention first.

Those areas:

- Must be visible.
- Must have **active actions**.
- Constrain how far other areas can honestly advance.
- Are expected in the current or next phase of focus.

This is intentional friction. It stops the institution from claiming high strength in one area while a foundation area is dangerously behind.

---

## 7. Continuous Discipline (framework fact)

Continuous Discipline is both the **destination** and the **operating philosophy**.

It means:

- A **living inventory** of AI use cases and material vendors, with named owners, refreshed on cadence.
- A **recurring operating rhythm** (not a project that ends).
- A **record that stays current** — a board or examiner can look at it without reconstructing a story.
- Movement in strength that is visible across periods.
- Governance work that respects capacity and is tied to business outcomes.

**It is not:**

- A thicker policy binder.
- A one-time assessment followed by a long pause.
- Software that substitutes for ownership.
- Governance theater the institution cannot sustain.

On any ordinary day the institution should be able to answer:

1. What is running?
2. Who owns it?
3. What is the residual risk?
4. What is being done about the gaps?
5. What value did we hypothesize, and what evidence do we have?

Urgency is real but without drama. The risk of inaction is **quiet accumulation of exposure and friction**, not a single cinematic failure.

---

## 8. Operating rhythm (framework fact)

If an activity is not on the rhythm, it is either not continuous or not yet operationalized.

| Cadence (customer label) | Purpose | Typical outputs |
|---|---|---|
| Weekly or biweekly **check-in** | Triage new AI uses, exceptions, vendor issues | Updated inventory entries, assigned actions |
| **Monthly working session** | Review biggest gaps, open actions, and value hypotheses on active use cases | Updated tracker, decisions, escalations |
| **Quarterly board / exec update** | Living view of strength, risk posture, selected priority outcomes / value evidence | Board pack / summary — **no invented ROI** |
| **Twice-yearly inventory update** | Keep the AI use-case and vendor list complete and classified | Validated inventory + risk classifications |
| **Annual strategy & planning** | Align AI priorities with business strategy; confirm each material use case still links to a priority outcome | Updated journey focus and targets |

Area reviews that are older than **one monthly cycle** (Navigator treats **35 days** as stale) should be called out as stale.

---

## 9. Living tracker (framework fact)

The **Living Implementation Tracker** is the operational backbone. It turns the framework into monthly practice.

**Status by area** — one row per area, at minimum:

- Current strength
- Target for the current phase of focus
- Owner
- Status
- Needs attention first? (Yes/No)
- Last reviewed
- Next action
- Evidence / link (living sources, not stale PDFs)
- Business value: linked **priority outcome**, what closing a gap unlocks, why it matters

Rules:

- Input fields stay current.
- Last reviewed must not go stale beyond one cadence cycle.
- Needs-attention = Yes **requires active actions**.
- Actions are not marked complete without evidence. The action list is chronological proof of continuous work.

---

## 10. Suggested client path (framework fact)

1. **Journey Assessment** — structured scoring across all six areas, evidence-based.
2. **Executive debrief** — current state, what needs attention first, right entry point.
3. **Phased journey plan** — sequenced to capacity and conditions (a navigation aid for this stretch of river, not a permanent Gantt).
4. **Install the rhythm** — tracker, cadence, first board view. Continuous Discipline **begins** here; it is not a later add-on.

**Assessment principles:** evidence notes or links for credible scores; missing inventory, missing ownership, or open attention-first areas constrain claimed strength; output is an institution view plus per-area gap analysis.

---

## 11. Value and compliance together (framework fact)

There is no choice between “do governance” and “deliver value.”

- **Compliance posture** needs living inventory, named owners, recurring oversight, and a record that stays current.
- **Business value** needs prioritized use cases tied to **priority outcomes**, a **value hypothesis** per material use case, capacity-respecting sequencing, and less friction from lagging areas.

Value is operational, not a narrative appendix:

- **Priority outcomes** name the outcome, baseline, desired direction/magnitude, owner, and linked areas or use cases.
- **Value hypothesis** (one per material use case): outcome, baseline, expected change, leading indicators, lagging metrics, how you will measure, owner of the *outcome*.
- **Value realization** trail: hypothesized → baseline → early signal → realized / sustained. Scaling without an early signal needs an explicit written decision that the value case has changed.
- **Portfolio value view:** hypothesized value, current evidence status, stage, owners, blockers.

**The Navigator never invents an ROI number or a black-box value score. Human review is required.**

---

## 12. Use-case portfolio (framework fact)

Innovation is not a side hobby. It is disciplined management of use cases, experiments, and product work inside risk and capacity.

**Balance two types of work:**

| Type | Intent | Horizon |
|---|---|---|
| **Improve & Optimize** | Make existing products, processes, or models better, faster, or cheaper | Near-term |
| **Explore & Create** | New offerings, new models, or material extensions | Medium to longer-term |

A healthy portfolio is rarely 100% exploratory. Many institutions under-invest in disciplined improvement while over-celebrating novelty.

**Stages (product):** Concept → Validated → Build → Scale / Run (plus Paused / Exited).

On cadence, leadership asks: accelerate, slow, pause, kill, or where is the pipeline thin relative to strategy? Material AI uses that enter the portfolio also enter the AI inventory and risk classification (Governance & Risk). Gaps in Data, Technology, or People constrain how hard the portfolio can scale.

Right-sized caution: most mid-sized credit unions need a **lightweight, visible portfolio leadership can actually run** — not a heavyweight innovation office.

---

## 13. Systems and constraints (framework fact)

Enterprise architecture is **not a seventh area**. It is a supporting discipline that informs Technology, Data, and Strategy.

Enough architectural clarity that AI and data work is not built on sand:

- Usable inventory of major capabilities and the systems that support them (not a full enterprise metamodel on day one).
- Current vs target direction for key platforms and data domains.
- Visible technical debt and constraints so strategy and governance decisions are honest.
- A short set of principles (prefer reusable data, no uncontrolled shadow AI tools, design for auditability) over forums that do not meet.

The Navigator does **not** require a full TOGAF-style practice.

**Where data comes from** (licensed add-on in product): priority data paths — what exists, how it connects, who owns it — supporting Data Foundations with proof, not perfect enterprise maps. Weak or missing lineage on material paths is a Data Foundations signal (often Governance & Risk as well).

---

## 14. What Journey Navigator the product does (product fact)

**PrimaLux Navigator** is the browser workspace that runs this framework.

Hosted surface: **https://navigator.primaluxadvisory.com**

It helps an organization see:

- Where you stand
- Progress by area
- Meeting rhythm
- People and ownership
- Optional add-ons: **AI & use-case portfolio**, **systems & constraints**, **where data comes from**
- Reports and board packs
- Proof you can stand behind

Left rail (customer groups): **Situation** (Home), **Stand** (Where we stand, Progress, Targets), **Operate** (Rhythm, People, Workflow, Sessions, Proof, Focus), **Extend** (Use cases, Systems, Data mapping), **Lead** (Reports, Organization).

Home: if there are no scores yet, **Start Journey Assessment**. If scores exist, people go to **Where we stand**. An unfinished sitting continues with an email code. A finished sitting has **Open snapshot** and **Update answers (workspace)**. Do not treat a sitting id as a public access token.

Roles (product): Admin · Executive Sponsor · Governance Lead · Contributor · Viewer.

The operator's institution is **theirs**. Do not attach a name.

---

## 15. Typical credit-union starting point (general practice)

Labeled **general practice** from PrimaLux advisory intake pattern (`navigator-orchestration-layer.md`). Not a regulation. Not this operator’s scored result.

When a credit union is vague about AI:

1. Start with a **Journey Assessment** (where we are, what is running, who owns it).
2. If **vendor AI** is mostly unknown, put vendor inventory and third-party AI risk on Stabilize work — do not skip it.
3. If the **board** does not yet share a language for oversight, literacy belongs **before** a heavy operating-model rebuild.
4. End the first stretch with a short sequenced plan (30 / 60 / 90 days) that fits capacity: inventory, owners, first rhythm, first board view.

Intake questions worth asking (compact; under ten):

- Sector (credit union vs other regulated setting).
- Primary need (overall governance, one use case, data foundations, board literacy, vendor AI).
- Current-state confidence (exploring, known gaps, active program, scaling).
- Existing AI inventory? Governance committee or review? Vendor AI known or unknown?
- Immediate ask: assessment, plan, workshop, or operating rhythm.
- Is the output internal diagnostic or closer to board-ready? **Board-ready always needs human review.**

Other advisory branches (general practice, not automatic Navigator screens): data-foundations pain (ownership, lineage, quality) → Data area first; a single product/feature launch → use-case intake, not a full enterprise assessment unless gaps are institution-wide; leadership literacy as the blocker → literacy before control design.

**Guardrails (advisory + framework):**

- No hallucinated regulatory claims.
- No model-generated score treated as a governance, risk, or readiness judgment.
- Clear split between self-diagnostic guidance and examiner-ready / board-ready packs.
- Human sign-off before anything leaves as a client-facing deliverable.

---

## 16. Design principles Cora may repeat (framework fact)

1. Right-sized — never more process than the institution can sustain.
2. Practitioner-built — real operating constraints, not pure theory.
3. No black-box scoring — logic and evidence stay visible.
4. Human review required — automation supports; it does not replace judgment.
5. Living by design — every major artifact has an owner and a review date.
6. Evidence over narrative.
7. Journey framing — adaptive navigation.
8. Innovation and architecture are disciplines that feed the six areas; they are not parallel empires.

---

## 17. What Cora must not do

- Invent NCUA, FFIEC, CFPB, Federal Reserve, NIST, FDIC, or OCC requirements. Cite a Library regulator file or say it is not in the library.
- Treat Gartner, ISC2 webinars, or other licensed research as PrimaLux Journey doctrine. Those are **not** in this file on purpose.
- Name a credit union, demo tenant, or seed dataset. The operator's institution has no name in this file.
- Quote product internals (billing, hosting, partner catalogs) as the customer's environment.
- Give an ROI number, a letter grade, or a maturity score that was not supplied by the operator or Navigator.
- Speak as an internal PrimaLux seat (pipeline, hiring, other agents).

If asked something this file does not contain: **say you do not have it.**
