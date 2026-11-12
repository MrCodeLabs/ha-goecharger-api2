"""Check that the PV timing tests catch two deliberate blueprint regressions."""

import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from xml.etree import ElementTree

SUITE = Path(__file__).resolve().parent
BLUEPRINT = SUITE.parents[1] / "example/blueprint/automation/go-echarger-pv-surplus-data.yaml"
CASES = (
    (
        "Bypass the freshness check",
        "measurements_valid and measurements_fresh and is_number",
        "measurements_valid or measurements_fresh and is_number",
        "test_daylight_pauses_on_stale_data_and_resumes_on_same_value_report",
        "stale measurements were sent",
    ),
    (
        "Remove the sunset trigger",
        "  - trigger: sun\n    event: sunset\n    id: sunset\n",
        "",
        "test_sunset_sends_zero_once_with_car_disconnected",
        "sunset did not send one zero payload",
    ),
)


def main():
    source = BLUEPRINT.read_text(encoding="utf-8")
    for label, before, after, test, expected_failure in CASES:
        if source.count(before) != 1:
            raise SystemExit(f"Could not locate exactly one mutation site for {label}")
        print(label, flush=True)
        with TemporaryDirectory() as directory:
            mutant = Path(directory) / BLUEPRINT.name
            result = Path(directory) / "result.xml"
            mutant.write_text(source.replace(before, after, 1), encoding="utf-8")
            # The harness uses these paths to substitute a copy while loading the blueprint.
            env = {
                **os.environ,
                "HA_BLUEPRINT_TEST_HARNESS_ORIGINAL": str(BLUEPRINT),
                "HA_BLUEPRINT_TEST_HARNESS_MUTANT": str(mutant),
            }
            completed = subprocess.run(
                [sys.executable, "-m", "pytest", "-c", str(SUITE / "pytest.ini"),
                 f"{SUITE / 'test_pv_surplus_timing.py'}::{test}",
                 "-q", "--tb=short", f"--junitxml={result}"],
                env=env,
                check=False,
                timeout=90,
            )
            if completed.returncode != 1 or not result.is_file():
                raise SystemExit(f"Expected an assertion failure for {label}")
            failures = ElementTree.parse(result).findall(".//testcase/failure")
            if len(failures) != 1 or expected_failure not in failures[0].get("message", ""):
                raise SystemExit(f"The test failed for a different reason than {label}")
        print(f"Regression caught by {test}", flush=True)


if __name__ == "__main__":
    main()
