# Managed charging blueprint

This optional blueprint coordinates one charger's requested current and force
state with total house load, grid import, individual main phases, home-battery
reserve and a timed grid-charging window. It belongs alongside the existing PV
data blueprint; it does not transmit PV values itself or change inverter
settings. Use exactly one PV sender and one current/force controller per charger.
Do not run an existing controller in parallel with this one.

Import `example/blueprint/automation/go-echarger-managed-charging.yaml` into
the automation blueprint library. This is development code requiring a
controlled pilot before replacing a working installation.

## Configuration

Create one `input_boolean` enable switch and one dedicated `input_text` helper
with maximum length **255**, initially empty and **without an `initial` value**
so it restores its state after HA restarts. Select the charger entry, its
car-connected binary sensor, `frc` select, requested-current `amp` number,
total EV power and phase-current sensors. Helpers must not be shared or edited
while management is active. A corrupt/shared/future-dated record causes a Stop
request rather than guessing ownership. Deleting/editing helper state loses
the ability to restore the previous setting safely.

Select total house **including EV** power, signed import-positive grid power,
and one or three EV supply voltages/currents in matching electrical phase
order. Set the total power ceiling explicitly. The optional import ceiling and
main-phase target add further independent constraints; all limits apply at
once. Main-phase sensors must use that same phase order, signed import positive.
Known units are required: W, A, V and %. Normalize kW and battery signs before
selecting the sensors. Verify mapping rather than assuming L1 names match
between different devices. A three-phase configuration conservatively budgets
all three supplied voltages even while fewer phases are drawing current.
It does not command 1/3-phase switching.

Limits do not imply instantaneous electrical protection: input/report delay,
communication and firmware behaviour matter. Keep physical protection and an
independent watchdog outside HA. A `last_reported` age check cannot prove the
freshness of a cached device measurement. The additional source timestamp
input can reject a stale original clock. Choose report age limits appropriate
to the actual sources; unchanged values must still be reported sufficiently
often by those integrations.

## Control policy

- The minimum of total-load, enabled grid-import and enabled main-phase budgets
  constrains current. Reductions apply immediately on the next tick. Increases
  are limited to **1 A** after the configured settling time.
- Default `surplus` mode subtracts measured home-battery discharge from apparent
  surplus. Select both home-battery SOC and signed discharge-positive power, or
  neither. `prefer_ev` is an explicit opt-in above the configured house reserve
  plus recovery margin; it can use grid/battery within the power/phase budgets.
- Optional timed grid charging uses a local-time start/end window, including
  overnight windows. The clock deadline is exclusive; an optional sunrise
  cutoff can end boost earlier. When battery sensors are selected, the separate
  maximum SOC for timed grid boost also applies. This requests available
  protected charging current; it cannot promise 100% vehicle SOC by a deadline.
- Boost uses `frc=2` after its current command passes the selected mode's checks
  and a last-moment Stop check passes. Only temporary mode checks a transport
  acknowledgement through the upstream TCL Number write path; requested-current
  mode checks HA state, which can be optimistic over WebSocket. Returning to
  ECO (`frc=0`) happens only for a
  force setting this controller owns. An external current change stops
  management instead of overwriting that manual setting.
- **Stop is latched.** Invalid/stale data, too little power for the minimum
  charging current, an unconfirmed command or uncertain restart state does not
  cause an automatic restart. Once checked, release Stop explicitly in the app
  or HA. The blueprint never automatically clears `frc=1`. After an uncertain
  write, disable management to complete safe cleanup before rearming.

The persistent helper contains a write intent before a command and a completed
record only after API/HA readback checks. A restart between those steps leads to
a Stop request. A manual Stop arriving between current calculation and force
control is rechecked immediately before the force action. Repeating an
already-identical setting in another app cannot always be detected; use Stop
or the dedicated management switch to express an override.

On disable/disconnect, restore only a current value still matching this
controller's last write. If connected, first request and confirm Stop, then
restore. Failed readback retains ownership for retry. Manual current changes
are preserved. A completed boost hitting a Stop condition restores the previous
current only after Stop is confirmed. Disabling this automation entity directly
bypasses cleanup: switch off its **management helper** first and wait for the
state record to clear.

## Optional temporary-current mode

Default mode works with the upstream integration's requested-current `amp`
entity and does not depend on another contribution. Temporary mode uses
`number.set_value` on the matching, enabled `tcl` number entity. It requires
upstream Number write-error propagation from main commit `5c44c123` or a release
containing that change; unmodified 2026.11.0 is not sufficient. The dedicated
temporary-current service was removed from that main and is not used here.
Select the charger's Temporary current limit entity explicitly; standard
current units/class and the config
entry are checked, without custom attributes or assumptions about its name.
These checks cannot distinguish tcl from amp/ama on the same charger;
verify the selection before the pilot. Initialize a known
temporary limit before enabling this mode; an inactive/unknown number is not
guessed. A repeated limit is renewed every 60 seconds with an actual Number
call, even when the state already equals the requested value. The upstream TCL
Number method requests an acknowledgement and raises an HA error for a missing
or rejected result. Number does not return a response object: successful call
completion and the following HA state check replace the old service's
`acknowledged/current.tcl` check. Write errors abort the sequence, so an unchanged
cached value cannot turn a rejected renewal into success. Failed renewal retains
the pending write intent; failed restoration retains the existing ownership
record for cleanup retry. No renewal continues when
disabled. Its firmware expiry is not a Stop/watchdog guarantee.

The unmodified 2026.11.0 has a reproduced stale Number value after TCL expiry,
and its Number write path can hide a rejected acknowledgement. New main propagates
Number write failures and fixes the cache overlay, but freshness of a TCL read
still depends on polling/hibernation behaviour. This local adaptation is tested
against synthetic failures and does not prove physical expiry/readback. Temporary
mode remains a development draft until the complete read/write/restore path
passes a controlled pilot. Requested-current mode also
needs a verified acknowledgement path before its optional boost can be described
as charger-confirmed. Keep the working controller until that validation is done.

## Verification and migration

```sh
python -m pip install -r tests/requirements-managed.txt
python -m pytest tests -q
```

Tests interpret the actual templates/actions with synthetic state and command
replies, including rejected writes, persistent restart intent, manual changes,
phase/total/import ceilings, battery hysteresis, deadlines and both daylight
saving changes. They are not physical tests, transport tests or an independent
implementation of electrical protection. API acceptance/HA state agreement
does not demonstrate the current actually drawn by a vehicle.

For a pilot, archive the existing controller and state, ensure only this one
owns writes, validate the HA schema, start with a constrained load and verify
actual power/current and Stop. Verify firmware, phase mapping, stale data,
unavailable HA/network, sunrise/end time, manual Stop and cleanup. Keep a
documented return to the previous controller. No production installation or
physical pilot is included in this contribution.

New blueprint by MrCodeLabs, prepared with AI assistance, under the repository's
Apache-2.0 licence. The original go-e integration authorship is retained.
