/* =====================================================================
   UNIT STATUS VALIDATION
   ---------------------------------------------------------------------
   Goal: find residential units (dbo.Statistic) whose Status__c does not
   match the status they SHOULD have, based on their parent application's
   type and current process step (dbo.Application).

   How it works (3 steps):
     1. UnitData       -> join each unit to its application, keep only
                          live residential units, and tag each unit with
                          a "HousingForm" so the rules below stay short.
     2. ExpectedStatus -> a CASE works out what the status SHOULD be.
                          If no rule applies, it returns NULL (= "not
                          checked"), so we never flag something we have
                          no rule for.
     3. Final SELECT   -> keep only units where actual <> expected.
   ===================================================================== */

WITH UnitData AS
(
    SELECT
        s.Id                  AS UnitID,
        s.Status__c           AS ActualStatus,
        s.Type__c,
        s.Sub_Type__c,
        a.Id                  AS ApplicationID,
        a.Name                AS ApplicationName,
        a.Application_Type__c,
        a.Process_Step__c,

        /* HousingForm groups unit types so the CASE below doesn't have to
           repeat the same type/subtype conditions over and over.
             'Ground' = Single Detached, Semi-Detached, General townhouses
             'Multi'  = Apartments, Seniors, Block/Stacked townhouses
           A townhouse with a NULL subtype matches neither -> NULL, so it
           won't be checked (same behaviour as the original query).        */
        CASE
            WHEN s.Type__c IN ('Single Detached', 'Semi-Detached')
              OR (s.Type__c = 'Townhouses' AND s.Sub_Type__c = 'General')
                THEN 'Ground'
            WHEN s.Type__c IN ('Apartments', 'Seniors')
              OR (s.Type__c = 'Townhouses' AND s.Sub_Type__c IN ('Block', 'Stacked'))
                THEN 'Multi'
        END                   AS HousingForm

    FROM dbo.Statistic s
    INNER JOIN dbo.Application a
        ON s.Application__c = a.Id      -- each unit belongs to one application

    WHERE s.IsDeleted = 0               -- ignore soft-deleted units
      AND a.IsDeleted = 0               -- ignore soft-deleted applications

      /* Statistic has ScdStartDate/ScdEndDate, which usually means it keeps
         history (old versions of each unit). If so, uncomment ONE of these
         so only the current version of each unit is checked:              */
      -- AND s.ScdEndDate IS NULL
      -- AND s.ScdEndDate = '9999-12-31'

      /* Only residential unit types are validated.
         NOTE: there is NO Process_Step__c filter here anymore. The old
         step filter stopped units at other steps from ever being checked
         (e.g. LOPA units at 'In Force'). The CASE below decides which
         steps get checked instead.                                        */
      AND s.Type__c IN
      (
          'Single Detached',
          'Semi-Detached',
          'Townhouses',
          'Apartments',
          'Seniors'
      )
),

ExpectedStatus AS
(
    SELECT
        *,
        /* CASE checks rules top to bottom and stops at the FIRST match,
           so the broad rules (whole application types) go first and the
           step-specific rules go after.                                   */
        CASE
            /* ---------------------------------------------------------
               1. REFERENCE ONLY
               Units on these application types are never real supply,
               whatever the step.
               --------------------------------------------------------- */
            WHEN Application_Type__c IN
            (
                'Adjacent Municipality',
                'Block Plan',
                'Engineering Application',
                'Infrastructure Planning and Delivery',
                'Minor Variances',
                'MOE ECA Application',
                'Regional Official Plan Amendment',
                'Zoning By-law Amendment'
            )
                THEN 'Reference Only'

            /* ---------------------------------------------------------
               2. ALWAYS ENVISIONED
               Provincial (MZO), pre-consultations and official plan
               amendments are always Envisioned, whatever the step.
               --------------------------------------------------------- */
            WHEN Application_Type__c IN
            (
                'Provincial Application',
                'Pre Submission Consultation',
                'Local Official Plan',
                'Local Official Plan Amendment'
            )
                THEN 'Envisioned'

            /* ---------------------------------------------------------
               3. MULTI UNITS ON PLANS / CONSENTS -> ENVISIONED
               Apartments, Seniors and Block/Stacked townhouses on a plan
               of subdivision/condo or a consent are Envisioned at any
               step (they'll come back later through a Site Plan).
               --------------------------------------------------------- */
            WHEN Application_Type__c IN
            (
                'Draft Plan of Subdivision',
                'Draft Vacant Land Plan of Condominium',
                'Draft Plan of Condominium',
                'Registered Plan of Subdivision',
                'Registered Vacant Land Plan of Condominium',
                'Registered Plan of Condominium',
                'Consent to Sever'
            )
             AND HousingForm = 'Multi'
                THEN 'Envisioned'

            /* ---------------------------------------------------------
               4. DRAFT PLANS (ground-related units only)
               --------------------------------------------------------- */
            WHEN Application_Type__c IN
            (
                'Draft Plan of Subdivision',
                'Draft Vacant Land Plan of Condominium',
                'Draft Plan of Condominium'
            )
             AND HousingForm = 'Ground'
             AND Process_Step__c = 'Data Processing'
                THEN 'Proposed'

            WHEN Application_Type__c IN
            (
                'Draft Plan of Subdivision',
                'Draft Vacant Land Plan of Condominium',
                'Draft Plan of Condominium'
            )
             AND HousingForm = 'Ground'
             /* 'Appeal Period' added: the job aid footnote says Appeal
                Period counts as Draft Approved. Remove if not wanted.     */
             AND Process_Step__c IN ('Draft Approved', 'Appeal Period')
                THEN 'Draft Approved'

            /* Draft plans at 'Fully Registered' are NOT checked: once
               registered, the units should live on the Registered Plan
               (that's what your separate SUBP/SUBR query checks).          */

            /* ---------------------------------------------------------
               5. REGISTERED PLANS (ground-related units only)
               --------------------------------------------------------- */
            WHEN Application_Type__c IN
            (
                'Registered Plan of Subdivision',
                'Registered Vacant Land Plan of Condominium',
                'Registered Plan of Condominium'
            )
             AND HousingForm = 'Ground'
             AND Process_Step__c = 'Data Processing'
                THEN 'Draft Approved'

            WHEN Application_Type__c IN
            (
                'Registered Plan of Subdivision',
                'Registered Vacant Land Plan of Condominium',
                'Registered Plan of Condominium'
            )
             AND HousingForm = 'Ground'
             /* FIX: the data uses 'Registered' for registered plans, not
                'Fully Registered'. Both are listed to be safe.            */
             AND Process_Step__c IN ('Registered', 'Fully Registered')
                THEN 'Final Approved'

            /* ---------------------------------------------------------
               6. CONSENT TO SEVER (ground-related units only)
               --------------------------------------------------------- */
            WHEN Application_Type__c = 'Consent to Sever'
             AND HousingForm = 'Ground'
             AND Process_Step__c = 'Data Processing'
                THEN 'Proposed'

            WHEN Application_Type__c = 'Consent to Sever'
             AND HousingForm = 'Ground'
             AND Process_Step__c = 'Conditional Approval'
                THEN 'Draft Approved'

            WHEN Application_Type__c = 'Consent to Sever'
             AND HousingForm = 'Ground'
             /* FIX: consents use 'Registered', not 'Fully Registered'.    */
             AND Process_Step__c = 'Registered'
                THEN 'Final Approved'

            /* ---------------------------------------------------------
               7. SITE PLAN (all residential types)
               --------------------------------------------------------- */
            WHEN Application_Type__c = 'Site Plan'
             AND Process_Step__c = 'Data Processing'
                THEN 'Proposed'

            WHEN Application_Type__c = 'Site Plan'
             /* CONFIRM: the extra Approvals steps come from the job aid
                (yellow = Draft Approved). Remove any you don't want.      */
             AND Process_Step__c IN
             (
                 'SP/ENG Approval',
                 'Awaiting Financials',
                 'Preparing Financials Letter',
                 'Preparing Final Approval Letter',
                 'Agreement Prep/Execution'
             )
                THEN 'Draft Approved'

            WHEN Application_Type__c = 'Site Plan'
             /* CONFIRM: Finalization steps -> Final Approved.             */
             AND Process_Step__c IN
             (
                 'Construction',
                 'Security Reduction',
                 'Security Release'
             )
                THEN 'Final Approved'

            /* No ELSE: anything not covered above gets NULL, meaning
               "no rule, don't check it".                                  */
        END AS ExpectedStatus
    FROM UnitData
)

/* =====================================================================
   FINAL RESULT: units whose actual status doesn't match the expected one
   ===================================================================== */
SELECT
    UnitID,
    ApplicationID,
    ApplicationName,
    Application_Type__c,
    Process_Step__c,
    Type__c,
    Sub_Type__c,
    ActualStatus,
    ExpectedStatus
FROM ExpectedStatus
WHERE ExpectedStatus IS NOT NULL                    -- only units we have a rule for
  /* ISNULL turns a missing status into '' so units with NO status are
     flagged too. A plain <> would silently skip them, because any
     comparison with NULL is "unknown", not true.                          */
  AND ISNULL(ActualStatus, '') <> ExpectedStatus
ORDER BY
    Application_Type__c,
    ApplicationName,
    UnitID;


/* =====================================================================
   OPTIONAL SANITY CHECK: run separately
   ---------------------------------------------------------------------
   Lists residential units that got NO expected status, grouped by type
   and step. Use it to spot rules you're missing, or names that are
   misspelled (a typo doesn't error, it just never matches).
   ===================================================================== */
-- WITH ... (paste the two CTEs above) ...
-- SELECT Application_Type__c, Process_Step__c, Type__c, Sub_Type__c, COUNT(*) AS n
-- FROM ExpectedStatus
-- WHERE ExpectedStatus IS NULL
-- GROUP BY Application_Type__c, Process_Step__c, Type__c, Sub_Type__c
-- ORDER BY n DESC;