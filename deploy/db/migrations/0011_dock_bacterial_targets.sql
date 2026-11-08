-- Let a docking job name a bacterial target (issue #21).
--
-- dock_jobs.target_id only accepted a human Ensembl gene ID. The prepared bacterial
-- structures (S. aureus GyrB, P. aeruginosa LpxC) are identified by their UniProt
-- accession, so the column now accepts either form. The pattern is UniProt's own
-- (uniprot.org/help/accession_numbers). Apply with db/migrate.py.

alter table dock_jobs drop constraint dock_jobs_target_id_check;
alter table dock_jobs add constraint dock_jobs_target_id_check
  check (
    target_id ~ '^ENSG[0-9]{11}$'
    or target_id ~ '^([OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9]([A-Z][A-Z0-9]{2}[0-9]){1,2})$'
  );
