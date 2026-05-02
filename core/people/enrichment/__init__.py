"""Candidate enrichment strategy boundary for Stage 2.

Owner reuse contract:
- Storage owner stays `core/db.py::insert_person_portrait`.
- Field provenance owner stays `core/db_ingest.py::insert_field_provenance`.
- Shared person/portrait schema owners stay `core/types/python/models.py::Person` and
  `core/types/python/models.py::PersonPortrait`.

This package only defines enrichment acquisition and merge strategy logic.
"""
