# PV transmission reliability

The existing PV blueprint gains optional report/source age checks, an
acknowledged-transmission helper, local transmission intervals and a deliberate
real-measurements-at-night mode. No charging Stop, battery fallback or automatic
resume policy is added here.

Defaults retain five-second daytime updates, thirty-second night zeros and
the sunset zero push. Age checking is off (`maximum_age_seconds: 0`), no helper
is written and night mode remains `zeros`. Existing target, phase-list,
PV-only, finite-number and unit-conversion behaviour is retained.

## Optional inputs

| Input | Behaviour |
|---|---|
| `transmission_interval` | `/5` (default), `/2` or `/1`. Faster polling is mainly for LAN. Night zeros still run once per thirty-second window. |
| `maximum_age_seconds` | A positive value rejects stale/future/missing report timestamps for used measurements. Use a value appropriate to the source's actual report interval. |
| `source_timestamp_entities` | Additional source measurement clocks; all must be fresh when age checks are enabled. Unused clocks are ignored when disabled. |
| `last_success_helper` | A dedicated `input_datetime` with date and time. Requires an explicit charger target. It advances only after a complete, matching API response. |
| `night_mode` | Default `zeros`, or explicit `measurements` for a controller that needs validated real measurements at night. Real mode suppresses the sunset zero push. |

Power value and report time are captured from the same HA state object once.
`last_reported` is used instead of `last_changed`: a stable, regularly reported
value must not be considered stale merely because it has not changed. HA report
time is not proof of the device's original sample age; select source timestamp
sensors when that distinction matters. The oldest selected clock governs
validity. An unavailable selected sensor is never replaced with a fabricated
zero. Disabled/unselected battery and intentional PV-only inputs retain their
existing semantics.

The helper records all acknowledged transmissions, including intentional
night/sunset zeros. It proves API acceptance, not vehicle power or physical
charging. Failed, incomplete or mismatched responses do not advance it. Give
each charger/automation its own helper; do not share it with another writer.
Real night measurements change energy-management behaviour and require a
separate controlled pilot. Keep independent stale-data/Stop protection.

## Validation and attribution

```sh
python -m pip install Jinja2 PyYAML pytest
python -m pytest tests/blueprints -q
```

Tests execute the actual YAML action tree with synthetic states/replies and the
current upstream service methods with fake LAN coordinators. They include the
previous compatibility cases plus timestamp boundaries, unchanged numeric
values, source clocks, failed acknowledgements, night modes and intervals.
They do not contact a charger or replace HA schema/runtime/device validation.

Original blueprint author: OliEder; original integration authorship and
Apache-2.0 licensing retained. This follows the previously discussed freshness
gap in PR #171 and acknowledges OliEder's related outage/helper proposals:
<https://github.com/marq24/ha-goecharger-api2/pull/171#issuecomment-6361765309>.
Those proposals' zero/notify/keep fallback policies are not copied or enabled
by this change. Prepared with AI assistance.

### Transport confirmation

A requested confirmation waits up to three seconds for the matching inner
WebSocket response. A successful socket send or secured-envelope response is
not an acknowledgement. Timeout, disconnect and rejected responses fail the
wait. Legacy send-only calls retain their existing behaviour. HTTP success
requires a literal JSON `true`; truthy error strings are not acceptance.
This small transport correction is shared with the other reliability
contribution and must not be applied twice. No hardware response/latency or
firmware expiry has been tested by these synthetic checks.
