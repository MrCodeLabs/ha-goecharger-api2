"""Boundary/compatibility checks on the actual blueprint action tree."""
import pytest
from harness import BlueprintRun


@pytest.mark.parametrize("age,allowed", [(0,True),(74.9,True),(75,True),(75.01,False),(1000,False),(-1,False)])
@pytest.mark.parametrize("source", ["sensor.grid","sensor.pv","sensor.battery"])
def test_report_age_boundary(source,age,allowed):
    run=BlueprintRun(inputs={"maximum_age_seconds":75,"battery_entities":["sensor.battery"]},
        states={"sensor.battery":"400"},ages={source:age})
    assert bool(run.run()) is allowed


def test_unchanged_value_is_fresh_when_reported_recently():
    run=BlueprintRun(inputs={"maximum_age_seconds":75},ages={"sensor.grid":5})
    assert run.run() and run.variables["measurements_fresh"]


def test_default_keeps_legacy_numeric_state_behaviour():
    assert BlueprintRun(ages={"sensor.grid":100000}).run()


@pytest.mark.parametrize("stamp,allowed", [("1970-01-01T00:15:30+00:00",True),
    ("1970-01-01T00:10:00+00:00",False),("1970-01-01T00:17:00+00:00",False),
    ("unknown",False),("unavailable",False)])
def test_source_clock(stamp,allowed):
    run=BlueprintRun(inputs={"maximum_age_seconds":75,"source_timestamp_entities":["sensor.sample_clock"]},
        states={"sensor.sample_clock":stamp})
    assert bool(run.run()) is allowed


def test_disabled_age_check_does_not_require_optional_clocks():
    assert BlueprintRun(inputs={"source_timestamp_entities":["sensor.missing"]}).run()


@pytest.mark.parametrize("reply", [{},{"success":"true"},{"error":"offline"},
    {"success":"true","response":{"ids":{"pGrid":None,"pPv":2000,"pAkku":0}}},
    {"success":"true","response":{"ids":{"pGrid":50,"pPv":2000,"pAkku":0}}}])
def test_rejected_incomplete_or_wrong_reply_never_advances_helper(reply):
    run=BlueprintRun(target="entry_a",inputs={"last_success_helper":"input_datetime.only_a"},
        states={"input_datetime.only_a":"1970-01-01 00:00:00"},reply=reply)
    assert run.run() and not run.helper_writes


@pytest.mark.parametrize("daylight,trigger",[(True,"tick"),(False,"tick"),(False,"sunset")])
def test_acknowledged_transmission_advances_helper_on_every_path(daylight,trigger):
    run=BlueprintRun(target="entry_a",daylight=daylight,trigger=trigger,
        inputs={"last_success_helper":"input_datetime.only_a"},states={"input_datetime.only_a":"old"})
    assert len(run.run())==1
    assert run.helper_writes==[{"timestamp":1000}]


def test_helper_requires_explicit_charger():
    run=BlueprintRun(inputs={"last_success_helper":"input_datetime.only_a"},states={"input_datetime.only_a":"old"})
    assert not run.run() and not run.helper_writes


def test_missing_helper_stops_before_device_call():
    run=BlueprintRun(target="entry_a",inputs={"last_success_helper":"input_datetime.missing"})
    assert not run.run()


def test_real_night_measurements_are_opt_in_and_validated():
    run=BlueprintRun(daylight=False,inputs={"night_mode":"measurements","maximum_age_seconds":75})
    assert run.run()[0]["pgrid"]==-1200
    stale=BlueprintRun(daylight=False,inputs={"night_mode":"measurements","maximum_age_seconds":75},ages={"sensor.grid":100})
    assert not stale.run()
    assert not BlueprintRun(trigger="sunset",inputs={"night_mode":"measurements"}).run()


@pytest.mark.parametrize("interval",["/1","/2","/5"])
def test_night_zero_once_per_thirty_second_window(interval):
    step=int(interval[1:])
    calls=[second for second in range(0,60,step) if BlueprintRun(daylight=False,second=second,
        inputs={"transmission_interval":interval}).run()]
    assert calls==[0,30]
