name: VM1 offline tests

on:
  push:
    branches:
      - vm1-pilot-issue5-icp-foundation
      - vm1-engine6-v2-context-classification
    paths:
      - 'pilot/**'
      - '.github/workflows/vm1-tests.yml'
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: vm1-issue5-tests
  cancel-in-progress: true

jobs:
  offline-tests:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - name: Check out repository
        uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.13'
      - name: Run stdlib-only unit suite
        working-directory: pilot
        run: python3 -m unittest discover -s tests -t .
      - name: Validate illustrative ICP policies
        working-directory: pilot
        run: |
          python3 -m vm1 validate-icp icp/frontend-studio.json
          python3 -m vm1 validate-icp icp/ai-automation-service-businesses.json
          python3 -m vm1 validate-icp icp/ecommerce-marketing-agency.json
      - name: Exercise fictional offline pipeline
        working-directory: pilot
        run: python3 -m vm1 synthetic --out "$RUNNER_TEMP/vm1-synthetic"
      - name: Exercise fictional directory seed ingestion
        working-directory: pilot
        run: |
          python3 -m vm1 seed-directory --csv fixtures/directory_seed/fictional_smoke_seed.csv \
            --source-catalog fixtures/directory_seed/fixture_catalog.json --out "$RUNNER_TEMP/vm1-directory-seed"
