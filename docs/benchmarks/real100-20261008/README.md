# REAL100 correlation and parameterization baseline

Read [the executive report](REAL100_EXECUTIVE_REPORT.md) for measured results and remaining assessment gaps. The unchanged engine converted 100 new HARs from 55 applications; protected regression converted 202 inputs and all 533 repository tests passed.

This directory contains the fifteen requested reports, supplemental scorecards, source/hash evidence, pytest XML, validation scripts and 100 recorded UI/API action records.

The reports describe the actual frozen local working tree, including accepted repairs that were uncommitted at collection time. `ENGINE_FREEZE.json` and `SOURCE_HASH_REPORT.json` identify it; the parent Git commit alone does not reproduce that working tree.

Captured credentials, session cookies and authentication/CSRF token values are redacted with stable hash markers. Raw HARs (340 MB), browser HTML/screenshots, generated request bundles and wire header dumps remain in the original local benchmark directory. Their original hashes and source locations remain in the reports. `PUBLICATION_AUDIT.json` maps original report hashes to published hashes. CSV files here are audit evidence, not live replay data.

The scripts are archived from the original workspace layout. Running them requires the original corpora, Python/browser/JMeter dependencies, explicit permitted application access and path adaptation. They are not a standalone public replay harness.

Overall parameter precision and fresh/live runtime readiness remain unassessed. This publication does not claim that all requested validation is complete or that the engine is replay-ready.
