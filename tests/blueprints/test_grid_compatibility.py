"""Compatibility regressions and rejection boundaries, using synthetic states."""
from collections import Counter

import pytest

from harness import BlueprintRun


@pytest.mark.parametrize('target', ['', 'entry_a'])
def test_pv_only_preserves_values_conversion_and_target(target):
    run = BlueprintRun(target=target, inputs={
        'grid_single_entity': None, 'power_multiplier': 1000,
        'battery_entities': ['sensor.battery']},
        states={'sensor.pv': '2.5', 'sensor.battery': '-0.25'})
    expected = {'pgrid': 0, 'ppv': 2500, 'pakku': -250}
    if target:
        expected['configid'] = target
    assert run.run() == [expected]


@pytest.mark.parametrize('tail', [
    ['sensor.l4'], ['sensor.missing'], ['sensor.l1'], ['', None]])
@pytest.mark.parametrize('target', ['', 'entry_a'])
def test_extra_phase_entries_are_not_read_or_summed(tail, target):
    run = BlueprintRun(target=target, inputs={
        'grid_single_entity': None,
        'grid_phase_entities': ['sensor.l1', 'sensor.l2', 'sensor.l3'] + tail},
        states={'sensor.l1': '-100', 'sensor.l2': '-200', 'sensor.l3': '50',
                'sensor.l4': '9999'})
    reads = Counter()

    def read(entity):
        reads[entity] += 1
        return run.states.get(entity, 'unknown')

    run.env.globals['states'] = read
    expected = {'pgrid': -250, 'ppv': 2000, 'pakku': 0}
    if target:
        expected['configid'] = target
    assert run.run() == [expected]
    assert reads == {'sensor.l1': 1, 'sensor.l2': 1, 'sensor.l3': 1, 'sensor.pv': 1}


@pytest.mark.parametrize('source', ['sensor.pv', 'sensor.battery'])
@pytest.mark.parametrize('bad', ['unavailable', 'NaN', 'inf', '1e999'])
def test_pv_only_still_rejects_invalid_required_measurements(source, bad):
    run = BlueprintRun(inputs={'grid_single_entity': None,
        'battery_entities': ['sensor.battery']},
        states={'sensor.battery': '0', source: bad})
    assert run.run() == []


@pytest.mark.parametrize('phases', [
    ['sensor.l1'], ['sensor.l1', 'sensor.l2'],
    ['sensor.l1', 'sensor.l1', 'sensor.l3'],
    ['sensor.l1', 'sensor.l2', ''], ['sensor.l1', 'sensor.l2', None],
    ['sensor.l1', 'sensor.l1', 'sensor.l3', 'sensor.l4']])
def test_invalid_selected_phase_method_never_becomes_pv_only(phases):
    run = BlueprintRun(inputs={'grid_single_entity': None, 'grid_phase_entities': phases},
        states={f'sensor.l{i}': '0' for i in range(1, 5)})
    assert run.run() == []


@pytest.mark.parametrize('phase', ['sensor.l1', 'sensor.l2', 'sensor.l3'])
@pytest.mark.parametrize('bad', ['unavailable', 'NaN'])
def test_valid_extra_phase_cannot_replace_invalid_selected_phase(phase, bad):
    run = BlueprintRun(inputs={'grid_single_entity': None,
        'grid_phase_entities': ['sensor.l1', 'sensor.l2', 'sensor.l3', 'sensor.l4']},
        states={'sensor.l1': '-100', 'sensor.l2': '-200', 'sensor.l3': '-300',
                'sensor.l4': '-400', phase: bad})
    assert run.run() == []


@pytest.mark.parametrize('method,expected', [('single', -1200), ('dual', 500)])
def test_existing_method_precedence_is_preserved(method, expected):
    inputs = {'grid_phase_entities': ['sensor.missing'] * 4,
        'grid_consumption_entity': 'sensor.import', 'grid_feedin_entity': 'sensor.export'}
    if method == 'dual':
        inputs['grid_single_entity'] = None
    run = BlueprintRun(inputs=inputs,
        states={'sensor.import': '1500', 'sensor.export': '1000'})
    assert run.run()[0]['pgrid'] == expected


@pytest.mark.parametrize('phases', [[], ['sensor.l1', 'sensor.l2'],
    ['sensor.l1', 'sensor.l2', 'sensor.l3', 'sensor.missing']])
@pytest.mark.parametrize('trigger,connected', [('tick', 'on'), ('sunset', 'off')])
def test_night_and_sunset_are_independent_of_grid_selection(phases, trigger, connected):
    run = BlueprintRun(daylight=False, trigger=trigger, connected=connected,
        inputs={'grid_single_entity': None, 'grid_phase_entities': phases})
    assert run.run() == [{'pgrid': 0, 'ppv': 0, 'pakku': 0}]
