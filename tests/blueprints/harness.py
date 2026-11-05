"""Execute the blueprint's actual templates and action tree with synthetic HA data.

This is an isolated regression harness, not a Home Assistant runtime or a device
test. Registry/state helpers are doubles. Unsupported actions fail explicitly.
Template results use literal parsing as HA does for dict/bool/number results.
"""

import ast
import datetime
import logging
import math
from numbers import Number
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from jinja2 import StrictUndefined
from jinja2.sandbox import SandboxedEnvironment
import yaml

ROOT = Path(__file__).resolve().parents[2]
BLUEPRINT = ROOT / "example/blueprint/automation/go-echarger-pv-surplus-data.yaml"


class Input(str):
    pass


class Loader(yaml.SafeLoader):
    pass


Loader.add_constructor("!input", lambda loader, node: Input(loader.construct_scalar(node)))


def is_number(value):
    # Contract of HA is_number: numeric conversion must be finite.
    try:
        return math.isfinite(float(value))
    except (ValueError, TypeError, OverflowError):
        return False


def timestamp(value, default=None):
    try:
        if hasattr(value, "epoch"):
            return value.epoch
        if isinstance(value, (int, float)):
            return value
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError, AttributeError):
        return default


class BlueprintRun:
    def __init__(self, inputs=None, states=None, target="", connected="on",
                 registry=None, entries=None, daylight=True, second=0, trigger="tick", ages=None, clock=1000, reply="ok"):
        self.document = yaml.load(BLUEPRINT.read_text(encoding="utf-8"), Loader=Loader)
        self.inputs = {}
        for name, value in self.document["blueprint"]["input"].items():
            for key, field in value.get("input", {name: value}).items():
                if "default" in field:
                    self.inputs[key] = field["default"]
        self.inputs.update(car_connected_entity={"entity_id": "binary_sensor.car_a"},
                           charger_config_entry=target, grid_single_entity="sensor.grid",
                           pv_entities=["sensor.pv"])
        self.inputs.update(inputs or {})
        self.states = {"binary_sensor.car_a": connected, "binary_sensor.car_b": connected,
                       "sensor.grid": "-1200", "sensor.pv": "2000"}
        self.states.update(states or {})
        self.registry = registry if registry is not None else {
            "binary_sensor.car_a": "entry_a", "binary_sensor.car_b": "entry_b"}
        self.entries = entries if entries is not None else {
            "entry_a": "goecharger_api2", "entry_b": "goecharger_api2"}
        self.daylight, self.trigger = daylight, trigger
        self.clock, self.reply = clock, reply
        self.helper_writes = []
        ages = ages or {}
        raw_states = self.states
        class StateAccess:
            def __call__(this, key):
                return raw_states.get(key, "unknown")
            def __getitem__(this, key):
                if key not in raw_states:
                    return None
                return SimpleNamespace(state=raw_states[key], last_reported=clock-ages.get(key, 0),
                    last_changed=0, attributes={"has_date":True,"has_time":True})
        self.env = SandboxedEnvironment(undefined=StrictUndefined)
        self.env.globals.update(
            states=StateAccess(),
            expand=self.expand,
            config_entry_id=lambda entity: self.registry.get(entity),
            config_entry_attr=lambda entry, attr: self.entries.get(entry) if attr == "domain" else None,
            is_number=is_number,
            now=lambda: SimpleNamespace(second=second, epoch=clock),
            as_timestamp=timestamp,
        )
        self.variables = {}
        self.calls = []
        self.stopped = None

    def set_state_reader(self, reader):
        clock=self.clock
        class Access:
            def __call__(self, entity):
                return reader(entity)
            def __getitem__(self, entity):
                return SimpleNamespace(state=reader(entity), last_reported=clock,
                    attributes={"has_date":True,"has_time":True})
        self.env.globals["states"]=Access()

    def expand(self, entities):
        if isinstance(entities, str):
            entities = [entities]
        return [SimpleNamespace(entity_id=entity, state=self.states[entity])
                for entity in entities if entity in self.states]

    def render(self, value):
        if isinstance(value, Input):
            return self.inputs[value]
        if isinstance(value, dict):
            return {key: self.render(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.render(item) for item in value]
        if isinstance(value, str) and ("{{" in value or "{%" in value):
            rendered = self.env.from_string(value).render(self.variables).strip()
            try:
                return ast.literal_eval(rendered)
            except (ValueError, SyntaxError):
                return rendered
        return value

    def condition(self, condition):
        kind = condition["condition"]
        if kind == "template":
            result = self.render(condition["value_template"])
            assert isinstance(result, bool), result
            return result
        if kind == "trigger":
            return condition["id"] == self.trigger
        if kind == "sun":
            return self.daylight
        if kind == "or":
            return any(self.condition(item) for item in condition["conditions"])
        if kind == "and":
            return all(self.condition(item) for item in condition["conditions"])
        if kind == "not":
            return not any(self.condition(item) for item in condition["conditions"])
        raise AssertionError(f"Unsupported condition: {condition}")

    def actions(self, actions):
        for action in actions:
            if self.stopped:
                return
            if "if" in action:
                branch = "then" if all(self.condition(c) for c in action["if"]) else "else"
                self.actions(action.get(branch, []))
            elif "choose" in action:
                for choice in action["choose"]:
                    if all(self.condition(c) for c in choice["conditions"]):
                        self.actions(choice["sequence"])
                        break
            elif "stop" in action:
                self.stopped = action["stop"]
            elif "condition" in action:
                if not self.condition(action):
                    self.stopped = action.get("alias", "condition failed")
            elif "variables" in action:
                for key, value in action["variables"].items():
                    self.variables[key] = self.render(value)
            elif action.get("action") == "goecharger_api2.set_pv_data":
                payload = self.render(action["data"])
                assert isinstance(payload, dict)
                self.calls.append(payload)
                if "response_variable" in action:
                    self.variables[action["response_variable"]] = ({"success":"true", "response":{"ids":{
                        "pGrid":payload["pgrid"], "pPv":payload["ppv"], "pAkku":payload["pakku"]}}} if self.reply == "ok" else self.reply)
            elif action.get("action") == "input_datetime.set_datetime":
                self.helper_writes.append(self.render(action["data"]))
            else:
                raise AssertionError(f"Unsupported action: {action}")

    def run(self):
        for key, value in self.document["variables"].items():
            self.variables[key] = self.render(value)
        self.actions(self.document["actions"])
        return self.calls


def dispatch(payload, available=("entry_a", "entry_b")):
    tree = ast.parse((ROOT / "custom_components/goecharger_api2/service.py").read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "GoeChargerApiV2Service")
    methods = [n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in ("get_coordinator", "set_pv_data")]
    stub = ast.ClassDef(name="ActualService", bases=[], keywords=[], body=methods, decorator_list=[])
    helpers = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_is_finite_number"]
    module = ast.fix_missing_locations(ast.Module(body=helpers+[stub], type_ignores=[]))
    coordinators = {e: SimpleNamespace(name=e, _serial="synthetic", intg_type="charger", mode="LAN", async_write_key=AsyncMock(return_value={})) for e in available}
    class ServiceValidationError(KeyError):
        pass
    namespace = {"math":math, "ServiceCall":object, "Number":Number, "WAN":"WAN", "INTG_TYPE":SimpleNamespace(CHARGER=SimpleNamespace(value="charger")), "Tag":SimpleNamespace(IDS=SimpleNamespace(key="ids")), "_LOGGER":logging.getLogger(__name__), "_COORDINATOR_PER_CONFIG_ENTRY_ID_MAP":coordinators, "ServiceValidationError":ServiceValidationError}
    exec(compile(module,"release/service.py","exec"), namespace)
    instance=namespace["ActualService"]()
    instance._hass=SimpleNamespace(config_entries=SimpleNamespace(async_get_entry=lambda e: SimpleNamespace(disabled_by=None) if e in available else None))
    coro=instance.set_pv_data(SimpleNamespace(data=payload, return_response=False))
    try:
        coro.send(None)
    except StopIteration:
        pass
    else:
        coro.close()
        raise AssertionError("Unexpected asynchronous I/O")
    return {e:c.async_write_key.call_args_list for e,c in coordinators.items()}
