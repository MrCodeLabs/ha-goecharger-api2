"""Actual service/HTTP paths; no HA import, sockets or device commands."""
import ast
import datetime
import logging
import math
from numbers import Number
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

ROOT=Path(__file__).resolve().parents[1]/'custom_components/goecharger_api2'
PAYLOAD={'pGrid':-100.0,'pPv':200.0,'pAkku':0.0}


def run(coroutine):
    try:coroutine.send(None)
    except StopIteration as result:return result.value
    finally:coroutine.close()
    raise AssertionError('Unexpected real I/O')


def service(reply):
    tree=ast.parse((ROOT/'service.py').read_text())
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='GoeChargerApiV2Service')
    cls.body=[n for n in cls.body if getattr(n,'name','') in ('set_pv_data','get_coordinator')]
    co=SimpleNamespace(name='synthetic',_serial='example',intg_type='charger',mode='LAN',
        async_write_key=AsyncMock(return_value=reply))
    ns={'math':math,'datetime':datetime,'Number':Number,'ServiceCall':object,
        'ServiceValidationError':ValueError,'_LOGGER':logging.getLogger(__name__),'WAN':'WAN',
        'INTG_TYPE':SimpleNamespace(CHARGER=SimpleNamespace(value='charger')),
        'Tag':SimpleNamespace(IDS=SimpleNamespace(key='ids')),
        '_COORDINATOR_PER_CONFIG_ENTRY_ID_MAP':{'entry_a':co}}
    helper=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_is_finite_number')
    exec(compile(ast.fix_missing_locations(ast.Module(body=[helper,cls],type_ignores=[])),'actual-service','exec'),ns)
    obj=ns['GoeChargerApiV2Service']()
    obj._hass=SimpleNamespace(config_entries=SimpleNamespace(async_get_entry=lambda e:SimpleNamespace(disabled_by=None)))
    return obj,co


@pytest.mark.parametrize('reply',[{},None,{'err':'rejected'},{'ids':{}},{'ids':{'pGrid':1}}])
def test_service_does_not_report_success_without_matching_ack(reply):
    obj,co=service(reply)
    result=run(obj.set_pv_data(SimpleNamespace(data={'configid':'entry_a','pgrid':-100,'ppv':200},return_response=True)))
    assert 'error' in result and 'success' not in result
    assert co.async_write_key.call_args.kwargs=={'require_ack':True}


def test_matching_ack_is_reported_and_legacy_call_remains_send_only():
    obj,co=service({'ids':PAYLOAD})
    call=SimpleNamespace(data={'configid':'entry_a','pgrid':-100,'ppv':200},return_response=True)
    assert run(obj.set_pv_data(call))['success']=='true'
    call.return_response=False
    assert run(obj.set_pv_data(call)) is None
    assert co.async_write_key.call_args.kwargs=={'require_ack':False}


@pytest.mark.parametrize('acceptance,accepted',[(True,True),(False,False),('invalid key',False),(1,False),({'pGrid':0},False)])
def test_http_error_strings_and_truthy_nonbooleans_are_not_acknowledgements(acceptance,accepted):
    tree=ast.parse((ROOT/'pygoecharger_ha/__init__.py').read_text())
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='GoeChargerApiV2Bridge')
    method=next(n for n in cls.body if getattr(n,'name','')=='_write_values_int')
    ns={'Tag':SimpleNamespace(IDS=SimpleNamespace(key='ids')),'_LOGGER':logging.getLogger(__name__)}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[method],type_ignores=[])),'actual-http','exec'),ns)
    class Response:
        status=200
        json=AsyncMock(return_value={'ids':acceptance})
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
    obj=SimpleNamespace(_logkey='synthetic',host_url='example.invalid',token=None,_timeout=None,
        web_session=SimpleNamespace(get=lambda *a,**kw:Response()),isCharger=True)
    result=run(ns['_write_values_int'](obj,{},'ids',PAYLOAD))
    assert (result=={'ids':PAYLOAD}) is accepted
