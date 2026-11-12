# PV blueprint timing tests

Run these tests with Python 3.14.2 or newer on Linux in a separate virtual
environment from the integration tests. The two suites use different Home
Assistant pytest plugins. Run the commands from the repository root.

```sh
python3.14 -m venv pythonenv-pv-harness
pythonenv-pv-harness/bin/python -m pip install -r tests/blueprint_harness/requirements.txt
pythonenv-pv-harness/bin/python -m pytest -c tests/blueprint_harness/pytest.ini tests/blueprint_harness -q
pythonenv-pv-harness/bin/python tests/blueprint_harness/check_mutations.py
```

OliEder's [harness](https://github.com/OliEder/ha-blueprint-test-harness/tree/v0.4.1)
loads the repository blueprint into Home Assistant and advances a frozen clock.
The tests record `set_pv_data` calls against synthetic states and exercise the
transition from fresh to stale measurements and back, as well as the sunset
trigger with the car disconnected. Keep using the integration tests to verify
the implementation of `set_pv_data`.

The mutation check runs each timing test with one deliberate regression in a
temporary copy and requires the corresponding assertion to fail.
