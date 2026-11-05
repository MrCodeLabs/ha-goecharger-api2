"""Interpret the actual blueprint templates/actions with synthetic HA state.

Unsupported actions fail. Writes affect only this in-memory fixture. This is
not a device, Home Assistant schema test or proof of electrical protection.
"""
import ast
import datetime as dt
import json
import math
from pathlib import Path
from types import SimpleNamespace

from jinja2 import StrictUndefined
from jinja2.sandbox import SandboxedEnvironment
import yaml

ROOT=Path(__file__).resolve().parents[1]


class Input(str):
    pass


class Loader(yaml.SafeLoader):
    pass


Loader.add_constructor("!input",lambda l,n:Input(l.construct_scalar(n)))


def is_number(value):
    try:
        return math.isfinite(float(value))
    except (ValueError,TypeError,OverflowError):
        return False


class Halt(Exception):
    pass


class Run:
    def __init__(self, inputs=None, values=None, ages=None, clock=None, memory="", reject=(), registry=None, no_readback=()):
        self.doc=yaml.load((ROOT/"example/blueprint/automation/go-echarger-managed-charging.yaml").read_text(),Loader=Loader)
        self.inputs={}
        for group in self.doc['blueprint']['input'].values():
            for name,field in group['input'].items():
                if 'default' in field:self.inputs[name]=field['default']
        self.inputs.update(charger_entry='entry_a',enabled_entity='input_boolean.manage',memory_entity='input_text.memory',
            connected_entity='binary_sensor.car',force_entity='select.force',current_entity='number.current',
            total_power_entity='sensor.total',grid_power_entity='sensor.grid',ev_power_entity='sensor.ev',
            voltage_entities=['sensor.v1','sensor.v2','sensor.v3'],ev_current_entities=['sensor.e1','sensor.e2','sensor.e3'],
            total_limit_w=12000,reserve_w=200,increase_interval_s=60)
        self.inputs.update(inputs or {})
        self.clock=clock or dt.datetime(2026,1,15,12,tzinfo=dt.timezone.utc)
        self.values={'input_boolean.manage':'on','input_text.memory':memory,'binary_sensor.car':'on',
            'select.force':'0','number.current':'6','sensor.total':'4000','sensor.grid':'-5000','sensor.ev':'4000',
            'sensor.v1':'230','sensor.v2':'230','sensor.v3':'230','sensor.e1':'6','sensor.e2':'6','sensor.e3':'6',
            'sensor.m1':'10','sensor.m2':'10','sensor.m3':'10','sensor.soc':'70','sensor.battery':'0','sun.sun':'above_horizon'}
        self.values.update(values or {})
        self.attrs={'input_text.memory':{'max':255},'number.current':{'min':6,'max':32,'unit_of_measurement':'A','device_class':'current'},
            'sun.sun':{'next_rising':(self.clock+dt.timedelta(hours=8)).isoformat()}}
        for k in self.values:
            if k.startswith('sensor.'):
                unit='V' if k.startswith('sensor.v') else 'A' if k.startswith(('sensor.e1','sensor.e2','sensor.e3','sensor.m')) else '%' if k=='sensor.soc' else 'W'
                self.attrs[k]={'unit_of_measurement':unit}
        self.no_readback=no_readback
        self.ages=ages or {};self.reject=reject;self.calls=[];self.stopped=None;self.variables={}
        self.registry={'binary_sensor.car':'entry_a','select.force':'entry_a','number.current':'entry_a','sensor.ev':'entry_a',
            'sensor.e1':'entry_a','sensor.e2':'entry_a','sensor.e3':'entry_a'}
        self.registry.update(registry or {})
        outer=self
        class StateAccess:
            def __call__(self,key):return outer.values.get(key,'unknown')
            def __getitem__(self,key):
                if key not in outer.values:return None
                return SimpleNamespace(state=outer.values[key],attributes=outer.attrs.get(key,{}),
                    last_reported=outer.clock-dt.timedelta(seconds=outer.ages.get(key,0)))
        def timestamp(value,default=None):
            try:
                if isinstance(value,dt.datetime):return value.timestamp()
                if isinstance(value,(int,float)):return value
                return dt.datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()
            except (TypeError,ValueError,AttributeError):return default
        def from_json(value,default=None):
            try:return json.loads(value)
            except (ValueError,TypeError):return default
        self.env=SandboxedEnvironment(undefined=StrictUndefined)
        self.env.filters.update(from_json=from_json,to_json=lambda v:json.dumps(v,separators=(',',':')))
        self.env.globals.update(states=StateAccess(),is_number=is_number,now=lambda:self.clock,
            as_timestamp=timestamp,timedelta=dt.timedelta,
            today_at=lambda s:self.clock.replace(hour=int(s[:2]),minute=int(s[3:5]),second=int(s[6:8]),microsecond=0),
            is_state=lambda e,v:self.values.get(e)==v,state_attr=lambda e,k:self.attrs.get(e,{}).get(k),
            config_entry_id=lambda e:self.registry.get(e),config_entry_attr=lambda e,k:'goecharger_api2' if e=='entry_a' else None)

    def render(self,value):
        if isinstance(value,Input):return self.inputs[value]
        if isinstance(value,list):return [self.render(v) for v in value]
        if isinstance(value,dict):return {k:self.render(v) for k,v in value.items()}
        if isinstance(value,str) and ('{{' in value or '{%' in value):
            text=self.env.from_string(value).render(self.variables).strip()
            try:return ast.literal_eval(text)
            except (SyntaxError,ValueError):return text
        return value

    def condition(self,c):
        if isinstance(c,str):return self.render(c) is True
        if isinstance(c,list):return all(self.condition(x) for x in c)
        if c['condition']=='template':return self.render(c['value_template']) is True
        raise AssertionError(c)

    def actions(self,actions):
        for action in actions:
            if 'if' in action:
                self.actions(action.get('then' if self.condition(action['if']) else 'else',[]))
            elif 'choose' in action:
                for branch in action['choose']:
                    if self.condition(branch['conditions']):
                        self.actions(branch['sequence']);break
                else:self.actions(action.get('default',[]))
            elif 'variables' in action:
                for k,v in action['variables'].items():self.variables[k]=self.render(v)
            elif 'stop' in action:
                raise Halt(action['stop'])
            elif 'condition' in action:
                if not self.condition(action):raise Halt('condition failed')
            elif 'wait_template' in action:
                if self.render(action['wait_template']) is not True:raise Halt('readback failed')
            elif 'action' in action:
                name=action['action'];data=self.render(action.get('data',{}));target=self.render(action.get('target',{})).get('entity_id')
                self.calls.append((name,target,data))
                if name in self.reject:
                    # HA aborts an action sequence on a service exception by default.
                    raise Halt('service failed')
                if name in self.no_readback:
                    continue
                if name=='input_text.set_value':
                    value=data['value']
                    assert isinstance(value,str) and len(value)<=255,(type(value),value)
                    self.values[target]=value
                elif name=='number.set_value':self.values[target]=str(data['value'])
                elif name=='select.select_option':self.values[target]=str(data['option'])
                else:raise AssertionError(name)
            else:raise AssertionError(action)

    def run(self):
        try:
            for k,v in self.doc['variables'].items():self.variables[k]=self.render(v)
            self.actions(self.doc['actions'])
        except Halt as stopped:self.stopped=str(stopped)
        return self.calls

    def memo(self):return json.loads(self.values['input_text.memory'])

    def commands(self):return [c for c in self.calls if c[0]!='input_text.set_value']
