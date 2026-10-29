-- One row per interventional drug trial with a final status, started 2005-2019.
-- Portable between AACT Postgres (search_path=ctgov) and DuckDB over AACT flat files.
-- Placeholders {start_min} / {start_max} are filled in by dtp.ingest.aact.
--
-- LEAKAGE NOTE: columns prefixed with `post_` or `label_` are known only after the
-- trial ends. They are kept for labels/EDA and must never be model features.

WITH base AS (
    SELECT
        s.nct_id,
        UPPER(s.overall_status)            AS overall_status,
        UPPER(REPLACE(s.phase, ' ', ''))   AS phase,
        CAST(s.start_date AS DATE)         AS start_date,
        CAST(s.study_first_submitted_date AS DATE) AS first_submitted_date,
        s.number_of_arms,
        s.has_dmc,
        s.enrollment                       AS post_enrollment_final,   -- overwritten with actual at end
        UPPER(s.enrollment_type)           AS post_enrollment_type,
        s.why_stopped                      AS post_why_stopped
    FROM studies s
    WHERE UPPER(s.study_type) = 'INTERVENTIONAL'
      AND UPPER(s.overall_status) IN ('COMPLETED', 'TERMINATED', 'WITHDRAWN')
      AND CAST(s.start_date AS DATE) BETWEEN DATE '{start_min}' AND DATE '{start_max}'
      AND EXISTS (SELECT 1 FROM interventions i
                  WHERE i.nct_id = s.nct_id AND UPPER(i.intervention_type) = 'DRUG')
),

-- Every aggregate below is restricted to the trials in `base` so it doesn't scan whole tables.
ids AS (SELECT nct_id FROM base),

lead_sponsor AS (
    SELECT nct_id,
           MAX(UPPER(agency_class)) AS lead_agency_class,
           MAX(name)                AS lead_sponsor_name
    FROM sponsors
    WHERE nct_id IN (SELECT nct_id FROM ids) AND LOWER(lead_or_collaborator) = 'lead'
    GROUP BY nct_id
),

collab AS (
    SELECT nct_id, COUNT(*) AS n_collaborators
    FROM sponsors
    WHERE nct_id IN (SELECT nct_id FROM ids) AND LOWER(lead_or_collaborator) = 'collaborator'
    GROUP BY nct_id
),

sites AS (
    SELECT nct_id, COUNT(*) AS n_sites
    FROM facilities
    WHERE nct_id IN (SELECT nct_id FROM ids)
    GROUP BY nct_id
),

ctry AS (
    SELECT nct_id,
           COUNT(DISTINCT name) AS n_countries,
           MAX(CASE WHEN name = 'United States' THEN 1 ELSE 0 END) AS has_us_site
    FROM countries
    WHERE nct_id IN (SELECT nct_id FROM ids)
      AND (removed IS NULL OR CAST(removed AS VARCHAR) IN ('f', 'false', 'False'))
    GROUP BY nct_id
),

mesh AS (
    -- First MeSH ancestor term is a coarse disease-area label; refined in Python.
    SELECT nct_id,
           COUNT(DISTINCT mesh_term) AS n_mesh_terms,
           MIN(mesh_term)            AS mesh_term_first
    FROM browse_conditions
    WHERE nct_id IN (SELECT nct_id FROM ids) AND LOWER(mesh_type) IN ('mesh-list', 'mesh-ancestor')
    GROUP BY nct_id
),

n_drugs AS (
    SELECT nct_id,
           COUNT(DISTINCT LOWER(name)) AS n_drug_interventions,
           MIN(name)                   AS first_drug_name
    FROM interventions
    WHERE nct_id IN (SELECT nct_id FROM ids) AND UPPER(intervention_type) = 'DRUG'
    GROUP BY nct_id
),

primary_p AS (
    -- Target B: smallest reported p-value across primary-outcome analyses.
    SELECT o.nct_id,
           MIN(CAST(oa.p_value AS DOUBLE PRECISION)) AS label_min_primary_p,
           COUNT(*)        AS label_n_primary_analyses
    FROM outcomes o
    JOIN outcome_analyses oa ON oa.outcome_id = o.id
    WHERE o.nct_id IN (SELECT nct_id FROM ids)
      AND UPPER(o.outcome_type) = 'PRIMARY'
      AND oa.p_value IS NOT NULL
    GROUP BY o.nct_id
)

SELECT
    b.*,
    ls.lead_agency_class,
    ls.lead_sponsor_name,
    COALESCE(c.n_collaborators, 0)       AS n_collaborators,
    COALESCE(st.n_sites, 0)              AS n_sites,
    COALESCE(ct.n_countries, 0)          AS n_countries,
    COALESCE(ct.has_us_site, 0)          AS has_us_site,
    d.allocation,
    d.intervention_model,
    d.masking,
    d.primary_purpose,
    e.gender                             AS elig_gender,
    e.healthy_volunteers                 AS elig_healthy_volunteers,
    e.criteria                           AS elig_criteria,
    m.n_mesh_terms,
    m.mesh_term_first,
    nd.n_drug_interventions,
    nd.first_drug_name,
    pp.label_min_primary_p,
    pp.label_n_primary_analyses
FROM base b
LEFT JOIN lead_sponsor ls ON ls.nct_id = b.nct_id
LEFT JOIN collab       c  ON c.nct_id  = b.nct_id
LEFT JOIN sites        st ON st.nct_id = b.nct_id
LEFT JOIN ctry         ct ON ct.nct_id = b.nct_id
LEFT JOIN designs      d  ON d.nct_id  = b.nct_id
LEFT JOIN eligibilities e ON e.nct_id  = b.nct_id
LEFT JOIN mesh         m  ON m.nct_id  = b.nct_id
LEFT JOIN n_drugs      nd ON nd.nct_id = b.nct_id
LEFT JOIN primary_p    pp ON pp.nct_id = b.nct_id
