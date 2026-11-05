import datetime as dt
import json

import pytest

from managed_harness import Run


def owned(**updates):
    return json.dumps({'v':1,'owner':'entry_a','base':6,'last':10,'at':0,'fo':False,'br':False,'pending':False,**updates})


def test_default_never_forces_grid_or_battery_charging():
    r=Run();r.run()
    assert all(c[0]!='select.select_option' for c in r.commands())


def test_immediate_reduction_to_total_budget():
    r=Run(values={'number.current':'16','sensor.total':'7000'},memory=owned(last=16),inputs={'total_limit_w':9000})
    r.run()
    assert r.values['number.current']=='8'


def test_ramp_is_one_amp_after_settling():
    r=Run(memory=owned(last=6));r.run()
    assert r.values['number.current']=='7'
    later=Run(memory=r.values['input_text.memory'],values={'number.current':'7'},clock=r.clock+dt.timedelta(seconds=5))
    later.run();assert later.values['number.current']=='7'


@pytest.mark.parametrize('entity',['sensor.total','sensor.grid','sensor.ev','sensor.v1','sensor.e1'])
@pytest.mark.parametrize('bad',['unknown','unavailable','NaN','inf'])
def test_invalid_measurements_stop_without_raising_current(entity,bad):
    r=Run(values={entity:bad});r.run()
    assert r.values['select.force']=='1'
    assert not any(c[0]=='number.set_value' for c in r.commands())


@pytest.mark.parametrize('age',[91,-1])
def test_stale_or_future_reports_stop(age):
    r=Run(ages={'sensor.grid':age});r.run()
    assert r.values['select.force']=='1'


def test_manual_stop_is_not_cleared_by_boost():
    r=Run(values={'select.force':'1'},inputs={'priority_mode':'prefer_ev','battery_soc_entity':'sensor.soc','battery_power_entity':'sensor.battery'})
    r.run();assert not any(c[0]=='select.select_option' for c in r.commands())


def test_one_overloaded_phase_reduces_current():
    r=Run(inputs={'phase_limit_a':23,'main_current_entities':['sensor.m1','sensor.m2','sensor.m3']},
        values={'number.current':'10','sensor.m1':'25','sensor.e1':'10'},memory=owned())
    r.run();assert float(r.values['number.current'])<=8


def test_battery_discharge_is_not_counted_as_exported_surplus():
    r=Run(inputs={'battery_soc_entity':'sensor.soc','battery_power_entity':'sensor.battery'},values={'sensor.battery':'8000'})
    r.run();assert r.values['select.force']=='1'


def test_prefer_ev_only_above_battery_reserve_and_recovery_margin():
    opts={'priority_mode':'prefer_ev','battery_soc_entity':'sensor.soc','battery_power_entity':'sensor.battery'}
    ready=Run(inputs=opts);ready.run();assert ready.values['select.force']=='2'
    low=Run(inputs=opts,values={'sensor.soc':'30','sensor.grid':'1000'});low.run();assert low.values['select.force']=='1'


@pytest.mark.parametrize('hour,minute,boost',[(22,0,True),(23,0,True),(6,59,True),(7,0,False),(12,0,False)])
def test_overnight_window_boundary(hour,minute,boost):
    r=Run(inputs={'night_enabled':True,'sunrise_cutoff':False},clock=dt.datetime(2026,1,15,hour,minute,tzinfo=dt.timezone.utc))
    r.run();assert bool(r.variables['in_window']) is boost


def test_sunrise_ends_grid_boost_before_clock_deadline():
    r=Run(inputs={'night_enabled':True},clock=dt.datetime(2026,1,15,6,tzinfo=dt.timezone.utc))
    r.values['sun.sun']='above_horizon';r.run();assert not r.variables['in_window']


def test_failed_current_write_retains_intent_and_blocks_force_start():
    r=Run(memory=owned(last=6),reject=('number.set_value',),inputs={'priority_mode':'prefer_ev','battery_soc_entity':'sensor.soc','battery_power_entity':'sensor.battery'})
    r.run()
    assert r.memo()['pending'] and r.values['select.force']=='0' and r.stopped=='service failed'
    restarted=Run(memory=r.values['input_text.memory']);restarted.run()
    assert restarted.values['select.force']=='1'


def test_external_current_edit_is_preserved_and_stops_management():
    r=Run(memory=owned(),values={'number.current':'12'});r.run()
    assert r.values['number.current']=='12' and r.values['select.force']=='1'


def test_disabling_stops_before_restoring_owned_current():
    r=Run(memory=owned(),values={'input_boolean.manage':'off','number.current':'10','select.force':'2'})
    r.run();assert r.commands()[0][0]=='select.select_option'
    assert float(r.values['number.current'])==6 and r.values['select.force']=='1'
    assert r.values['input_text.memory']==''


def test_disabling_does_not_overwrite_manual_current():
    r=Run(memory=owned(),values={'input_boolean.manage':'off','number.current':'12'})
    r.run();assert r.values['number.current']=='12'


@pytest.mark.parametrize('memory',['broken','[]','{"v":1,"owner":"entry_b"}'])
def test_corrupt_or_shared_helper_never_starts_charging(memory):
    r=Run(memory=memory);r.run()
    assert r.values['select.force']=='1'


def test_wrong_charger_is_never_written():
    r=Run(registry={'number.current':'entry_b'});r.run()
    assert r.commands()==[]


def test_temporary_mode_failed_number_write_keeps_intent():
    r=Run(inputs={'use_temporary_limit':True},reject=('number.set_value',),memory=owned(last=6))
    r.run();assert r.memo()['pending'] and r.stopped=='service failed'
    assert not any(c[0]=='select.select_option' for c in r.commands())


def test_temporary_lease_is_renewed_after_sixty_seconds_not_every_tick():
    opts={'use_temporary_limit':True,'maximum_current_a':6}
    r=Run(inputs=opts);r.run()
    first=r.memo()['renew']
    tick=Run(inputs=opts,memory=r.values['input_text.memory'],clock=r.clock+dt.timedelta(seconds=5))
    tick.run();assert tick.memo()['renew']==first
    assert not tick.commands()
    due=Run(inputs=opts,memory=tick.values['input_text.memory'],clock=r.clock+dt.timedelta(seconds=60))
    due.run();assert due.commands()[0]==('number.set_value','number.current',{'value':6})


def test_rejected_same_value_renewal_cannot_pass_cached_readback():
    r=Run(inputs={'use_temporary_limit':True,'maximum_current_a':6},
        memory=owned(last=6,renew=0),reject=('number.set_value',))
    r.run()
    assert r.values['number.current']=='6'
    assert r.stopped=='service failed' and r.memo()['pending']
    assert r.commands()==[('number.set_value','number.current',{'value':6})]
    restarted=Run(inputs={'use_temporary_limit':True,'maximum_current_a':6},
        memory=r.values['input_text.memory'])
    restarted.run()
    assert restarted.values['select.force']=='1'
    assert not any(c[0]=='number.set_value' for c in restarted.commands())


@pytest.mark.parametrize('temporary',[False,True])
def test_successful_call_without_readback_keeps_pending_intent(temporary):
    r=Run(inputs={'use_temporary_limit':temporary},memory=owned(last=6),no_readback=('number.set_value',))
    r.run()
    assert r.stopped=='readback failed' and r.memo()['pending']
    assert not any(c[0]=='select.select_option' for c in r.commands())


@pytest.mark.parametrize('temporary',[False,True])
def test_restoration_failure_keeps_ownership_and_can_retry(temporary):
    opts={'use_temporary_limit':temporary}
    r=Run(inputs=opts,memory=owned(),values={'input_boolean.manage':'off','number.current':'10','select.force':'2'},
        reject=('number.set_value',))
    r.run()
    assert r.stopped=='service failed' and r.values['select.force']=='1'
    assert r.memo()['last']==10 and r.memo()['base']==6
    retry=Run(inputs=opts,memory=r.values['input_text.memory'],
        values={'input_boolean.manage':'off','number.current':'10','select.force':'1'})
    retry.run()
    assert float(retry.values['number.current'])==6
    assert retry.values['input_text.memory']=='' and retry.values['select.force']=='1'


def test_temporary_manual_stop_never_renews_or_restarts():
    r=Run(inputs={'use_temporary_limit':True},memory=owned(last=6),values={'select.force':'1'})
    r.run()
    assert not r.commands() and r.values['select.force']=='1'


def test_rejected_force_write_retains_uncertain_intent():
    r=Run(inputs={'priority_mode':'prefer_ev','battery_soc_entity':'sensor.soc','battery_power_entity':'sensor.battery'},
        reject=('select.select_option',))
    r.run();assert r.memo()['pending'] and r.values['select.force']=='0'


def test_end_of_grid_window_stops_then_restores_previous_current():
    r=Run(inputs={'night_enabled':True,'sunrise_cutoff':False},clock=dt.datetime(2026,1,15,7,tzinfo=dt.timezone.utc),
        memory=owned(fo=True,reason='timed'),values={'number.current':'10','select.force':'2','sensor.grid':'2000'})
    r.run()
    assert r.commands()[0][0]=='select.select_option'
    assert r.values['select.force']=='1' and float(r.values['number.current'])==6


def test_failed_restoration_keeps_state_for_retry():
    r=Run(memory=owned(),values={'input_boolean.manage':'off','number.current':'10'},reject=('number.set_value',))
    r.run();assert r.values['input_text.memory'] and r.stopped=='service failed'


@pytest.mark.parametrize('value',[None,'A','kW'])
def test_wrong_power_units_stop(value):
    r=Run();r.attrs['sensor.grid']['unit_of_measurement']=value
    r.run();assert r.values['select.force']=='1'


def test_mixed_charger_phase_currents_rejected():
    r=Run(registry={'sensor.e2':'entry_b'});r.run()
    assert not r.commands()


@pytest.mark.parametrize('bad',['unknown','not-a-date','2026-01-15T12:10:00+00:00','2026-01-15T10:00:00+00:00'])
def test_bad_source_clock_stops(bad):
    r=Run(inputs={'source_clock_entity':'sensor.clock'},values={'sensor.clock':bad})
    r.run();assert r.values['select.force']=='1'


def test_manual_stop_persists_across_restart():
    r=Run(memory=owned(fo=True),values={'number.current':'10','select.force':'1'})
    r.run();assert r.values['select.force']=='1' and not r.commands()


@pytest.mark.parametrize('soc,previous,expected',[(30,True,False),(31,False,False),(31,True,True),(32,False,True)])
def test_battery_hysteresis(soc,previous,expected):
    r=Run(inputs={'priority_mode':'prefer_ev','battery_soc_entity':'sensor.soc','battery_power_entity':'sensor.battery'},
        values={'sensor.soc':str(soc),'select.force':'1'},memory=owned(last=6,br=previous))
    r.run();assert r.variables['battery_ready'] is expected


@pytest.mark.parametrize('invalid',['NaN','inf',-1])
def test_invalid_limits_fail_closed(invalid):
    r=Run(inputs={'maximum_current_a':invalid});r.run()
    assert r.values['select.force']=='1'


def test_single_phase_configuration_uses_its_voltage_and_phase_budget():
    r=Run(inputs={'voltage_entities':['sensor.v1'],'ev_current_entities':['sensor.e1'],
        'main_current_entities':['sensor.m1'],'phase_limit_a':20},memory=owned(last=6))
    r.run();assert r.values['number.current']=='7'


def test_import_limit_is_independent_of_total_power_limit():
    r=Run(inputs={'import_limit_w':6000,'priority_mode':'prefer_ev',
        'battery_soc_entity':'sensor.soc','battery_power_entity':'sensor.battery'},memory=owned(),
        values={'number.current':'10','sensor.grid':'5000'})
    r.run();assert float(r.values['number.current'])<=6


@pytest.mark.parametrize('date',['2026-03-29','2026-10-25'])
def test_schedule_across_daylight_saving_changes(date):
    from zoneinfo import ZoneInfo
    zone=ZoneInfo('Europe/Berlin')
    for hour,expected in [(1,True),(4,True),(7,False)]:
        clock=dt.datetime.fromisoformat(f'{date}T{hour:02d}:00:00').replace(tzinfo=zone)
        r=Run(clock=clock,inputs={'night_enabled':True,'sunrise_cutoff':False})
        r.run();assert bool(r.variables['in_window']) is expected
