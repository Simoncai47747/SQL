# YorkTrax Data Quality Queries

Validation queries for the **Planning_YorkTrax_OWE** SQL Server database. Each query finds records that look wrong or need follow-up, so planners can review and fix them in YorkTrax.

- **Author:** Simon (co-op student, Winter 2026)
- **Last updated:** November 2026
- **Business rules source:** *YorkTrax Job Aid: Report Application Status*

> Items marked **TODO** need confirming by the team. They were open questions when this was written.

---

## How to run

1. Open the `.sql` file in SSMS (or VS Code with the SQL Server extension).
2. Connect to the server hosting `Planning_YorkTrax_OWE`.
3. Run it. Every query is read-only (`SELECT` only) and changes no data.
4. Each row in the result is a record to review. **An empty result means nothing is wrong.**

---

## Data model

| Table | What it holds | Key columns |
|---|---|---|
| `dbo.Application` | One row per planning application (Salesforce record) | `Id` (PK), `Name`, `Application_Type__c`, `Process_Stage__c`, `Process_Step__c`, `Parent_Application__c`, `Submission_Number__c` |
| `dbo.Statistic` | One row per **unit** (a row of housing/land-use stats on an application) | `Id` (PK), `Application__c` (FK → `Application.Id`), `Status__c`, `Type__c`, `Sub_Type__c`, `Record_Status__c`, `Submission_Number__c`, `GIS_ID__c` |

**Relationships**
- `Statistic.Application__c = Application.Id`: each unit belongs to one application.
- `Application.Parent_Application__c = Application.Id`: links a **Registered Plan of Subdivision (SUBR)** back to its **Draft Plan of Subdivision (SUBP)**. One SUBP can have several SUBRs (registered in phases).

**Values worth knowing**
- `Application_Type__c` stores full names (e.g. `Site Plan`, `Consent to Sever`, `Draft Plan of Subdivision`), not the job aid prefixes (SP, CONS, SUBP).
- `Statistic.Status__c` only ever holds: `Envisioned`, `Proposed`, `Draft Approved`, `Final Approved`, `Reference Only` (or NULL).
  The job aid's "Registered Unbuilt", "Under Construction" and "Built" are **not stored**. They're worked out for the Housing Supply Dashboard.
- Draft Plans finish at step `Fully Registered`; Registered Plans and Consents finish at step `Registered`.
- Common columns: `IsDeleted` (soft delete flag), `ScdStartDate`/`ScdEndDate` (history tracking on `Statistic`).

---

## Queries

### `unit_status_check.sql`: units with the wrong status
**Purpose:** Finds residential units whose `Status__c` doesn't match what their application's type and process step say it should be.

**Logic:**
1. `UnitData` joins units to applications, keeps live residential units (Single Detached, Semi-Detached, Townhouses, Apartments, Seniors), and tags each with a `HousingForm`:
   - `Ground` = singles, semis, General townhouses
   - `Multi` = apartments, seniors, Block/Stacked townhouses
2. `ExpectedStatus` uses a CASE to work out the correct status (first matching rule wins):

| Application type | Units | Step | Expected status |
|---|---|---|---|
| Adjacent Municipality, Block Plan, Engineering, Infrastructure Planning, Minor Variances, MOE ECA, Regional OPA, Zoning By-law Amendment | all | any | Reference Only |
| Provincial Application, Pre Submission Consultation, Local Official Plan (+ Amendment) | all | any | Envisioned |
| Draft/Registered Plans, Consent to Sever | Multi | any | Envisioned |
| Draft Plans (Subdivision, Condo, Vacant Land Condo) | Ground | Data Processing | Proposed |
| Draft Plans | Ground | Draft Approved, Appeal Period | Draft Approved |
| Registered Plans | Ground | Data Processing | Draft Approved |
| Registered Plans | Ground | Registered | Final Approved |
| Consent to Sever | Ground | Data Processing / Conditional Approval / Registered | Proposed / Draft Approved / Final Approved |
| Site Plan | all | Data Processing | Proposed |
| Site Plan | all | SP/ENG Approval, Financials, Final Approval Letter, Agreement | Draft Approved |
| Site Plan | all | Construction, Security Reduction/Release | Final Approved |

3. Returns units where the actual status ≠ expected. Units with **no** status are included.

**Output:** one row per mismatched unit, with application name, type, step, unit type and both statuses.

**Notes / TODO:**
- TODO: confirm the Site Plan steps and Appeal Period rules (marked `CONFIRM` in the file).
- TODO: uncomment the right `ScdEndDate` filter if `Statistic` keeps history rows.
- Steps not in the table aren't checked (the CASE returns NULL). Run the sanity check at the bottom of the file to see what isn't covered.

---

### `subpFinalizationQuery.sql`: SUBPs that should be Fully Registered
**Purpose:** Finds Draft Plans of Subdivision that are **not** at `Fully Registered`, even though every SUBR linked to them is already `Registered`.

**Logic:** A SUBP is returned when:
- its step is not `Fully Registered`, **and**
- at least one SUBR points to it and is `Registered` (`EXISTS`), **and**
- no SUBR points to it that is still unregistered (`NOT EXISTS`).

**Output:** `SUBP_Id`, `SUBP_Name`: draft plans to move to Fully Registered.

---

### `subpFinalizationValidationQuery.sql`: review version of the above
**Purpose:** Same rule as `subpFinalizationQuery.sql`, but shows each SUBP **alongside its registered SUBRs** so a reviewer can check the evidence before updating anything.

**Output:** `Draft_Name`, the SUBP step, `Registered_Name`, the SUBR step. One row per SUBP–SUBR pair, sorted by draft name.

**Notes:** The alias `SUBR` is reused inside the subqueries. SQL Server allows this (the inner alias takes over inside the brackets), but renaming the inner ones (e.g. `SUBR2`) would make it easier to read.

---

### `subpPre2026NoSubr.sql`: old draft plans with no registered plan
**Purpose:** Finds Draft Plans of Subdivision last modified **before 2026-01-01** that have **no** Registered Plan of Subdivision linked to them at all. These are possibly stale or abandoned files.

**Output:** SUBP `Id`, `Name`, `CreatedDate`, `LastModifiedDate`.

**Notes:** The cutoff date is hard-coded. Change `'2026-01-01'` to move the window.

---

### `rentalQuery.sql`: rental housing records
**Purpose:** Lists units/applications that are flagged as rental housing in any of three ways, and labels which way caught them.

**Logic:** A row is included if **any** of these is true:
- `Description__c` contains "Rental" → labelled `Description`
- `Rental_Housing_Included__c = 'Yes'` → labelled `Rental Housing Included`
- `Ownership_Status__c = 'Rental'` → labelled `Ownership Type`

If more than one is true, the label shows only the **first** match.

**Output:** description, ownership status, rental flag, number of rental apartments, and the `Type` label.

**Notes / TODO:**
- `LIKE '%Rental%'` also matches text like "non-rental" or "no rental units". Spot-check the Description matches.
- Columns aren't prefixed with `A.` / `S.`, so it isn't obvious which table each comes from. Adding prefixes would help.
- Because it joins to `Statistic`, an application with several units shows up several times.

---

### `SQLQuery7.sql`: units left on the previous submission
**Purpose:** TODO: describe the business purpose. *(Suggested rename: something descriptive like `unitsOnPreviousSubmission.sql`.)*

**Logic:** Returns units (with a GIS ID) where:
- the application's `Submission_Number__c` is exactly **one higher** than the unit's (the application has moved to a new submission but the unit is still on the old one), **and**
- the application has a submission group (application + submission number, units with a GIS ID) containing **exactly one** `Archived` unit and **at least one** `Active` unit.

**Output:** unit ID, GIS ID, created date/by, application ID and name, record status, and both submission numbers.

**Notes:** The `HAVING` check is grouped by application **and** submission number, but the `IN (...)` only matches on application. So the unit returned may be in a different submission from the group that passed the check. TODO: confirm this is intended.

---

## Conventions

- **Aliases:** `s` / `S` = Statistic (unit), `a` / `A` = Application, `SUBP` = draft plan, `SUBR` = registered plan.
- **File names:** camelCase, describing what the query finds.
- **Comments:** each file should start with a header (purpose, author, date, tables, assumptions). Inline comments explain *why*, not *what*.
- **Exact text matching:** status, type and step values are matched as exact strings. A typo won't error. It will just never match. Check spellings against the database when adding rules.