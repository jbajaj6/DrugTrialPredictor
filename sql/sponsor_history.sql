-- Every interventional trial with its lead sponsor, for sponsor track-record features.
-- Not limited to drug trials or to 2005-2019: a sponsor's history includes all its trials.
-- Features built from this use only trials that started / ended BEFORE the target trial started.
SELECT
    s.nct_id,
    sp.name                                         AS lead_sponsor_name,
    UPPER(s.overall_status)                         AS overall_status,
    CAST(s.start_date AS DATE)                      AS start_date,
    -- end date: completion if reported, otherwise the last record update (e.g. withdrawn trials)
    CAST(COALESCE(s.completion_date, s.last_update_submitted_date) AS DATE) AS end_date
FROM studies s
JOIN sponsors sp ON sp.nct_id = s.nct_id AND LOWER(sp.lead_or_collaborator) = 'lead'
WHERE UPPER(s.study_type) = 'INTERVENTIONAL'
  AND s.start_date IS NOT NULL
