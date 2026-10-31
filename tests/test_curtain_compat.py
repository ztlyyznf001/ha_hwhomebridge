"""Exercise the real adapter, router and dispatcher without loading HA or the SDK."""
import asyncio
import importlib
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = '_hwhomebridge_test'
package = ModuleType(PACKAGE)
package.__path__ = [str(ROOT / 'custom_components/hwhomebridge')]
sys.modules[PACKAGE] = package
router_module = importlib.import_module(PACKAGE + '.service_router')


class CurtainCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.router = router_module.ServiceRouter()
        self.assertTrue(await self.router.load_product_registry(str(
            ROOT / 'custom_components/hwhomebridge/config/product_registry.json')))
        self.state = SimpleNamespace(state='closed', attributes={'supported_features': 3})
        self.services = SimpleNamespace(async_call=AsyncMock())
        self.hass = SimpleNamespace(
            states=SimpleNamespace(get=Mock(side_effect=lambda _: self.state)),
            services=self.services, loop=asyncio.get_running_loop(),
            async_create_task=asyncio.create_task,
        )
        self.router.set_hass(self.hass)
        self.entity = 'cover.test_curtain'
        self.vd = self.router.register_device('curtain-device', '客厅窗帘', [
            {'entity_id': self.entity, 'domain': 'cover'},
            {'entity_id': 'sensor.energy', 'domain': 'sensor', 'device_class': 'energy'},
        ], model='xiaomi.curtain.acn010')
        self.assertIsNotNone(self.vd)

    async def test_registration_uses_existing_pid_without_electrical_sensors(self):
        self.assertEqual(self.vd.product.pid, '008')
        self.assertEqual(set(self.vd.service_entries), {'switch'})
        self.assertEqual(self.vd.get_entity_for_service('switch'), self.entity)

    async def test_open_and_close_reach_ha_services(self):
        for on, service in ((1, 'open_cover'), (0, 'close_cover')):
            self.assertTrue(self.router.route_action(self.vd.sn, json.dumps({'on': on})))
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            self.services.async_call.assert_awaited_with(
                domain='cover', service=service, target={'entity_id': self.entity}, service_data={})

    async def test_invalid_commands_never_move_cover(self):
        mapping = self.vd.product.services['switch'].ha_mapping
        for payload in ({}, {'on': None}, {'on': '1'}, {'on': -1}, {'on': 2}, {'on': 0.0}):
            with self.subTest(payload=payload):
                self.assertFalse(self.router.action_dispatcher.dispatch(
                    self.vd.sn, self.entity, mapping, payload))
        await asyncio.sleep(0)
        self.services.async_call.assert_not_called()

    async def test_unavailable_and_unsupported_commands_are_rejected(self):
        for state in (None, SimpleNamespace(state='unavailable', attributes={}),
                      SimpleNamespace(state='unknown', attributes={})):
            self.state = state
            self.assertFalse(self.router.route_action(self.vd.sn, {'on': 1}))
        self.state = SimpleNamespace(state='closed', attributes={'supported_features': 2})
        self.assertFalse(self.router.route_action(self.vd.sn, {'on': 1}))
        self.state.attributes['supported_features'] = 1
        self.assertFalse(self.router.route_action(self.vd.sn, {'on': 0}))
        await asyncio.sleep(0)
        self.services.async_call.assert_not_called()

    async def test_reports_and_sdk_queries_agree(self):
        report = Mock()
        self.router._update_hw_bridge_status = report
        for state, expected in [('open', 1), ('opening', 1), ('closing', 1), ('closed', 0),
                                ('unknown', None), ('unavailable', None), ('', None)]:
            with self.subTest(state=state):
                report.reset_mock()
                self.state.state = state
                self.router.report_state(self.vd.sn, self.entity, self.state)
                result = self.router.get_char_state(self.vd.sn, 'switch')
                if expected is None:
                    self.assertIsNone(result)
                    report.assert_not_called()
                else:
                    self.assertEqual(json.loads(result), {'on': expected})
                    report.assert_called_once_with(self.vd.sn, 'switch', {'on': expected})

    async def test_unrelated_cover_is_not_matched(self):
        self.assertIsNone(self.router.register_device('garage', 'Garage', [
            {'entity_id': 'cover.garage', 'domain': 'cover', 'device_class': 'garage'}
        ], model='garage.motor'))

    async def test_curtain_name_without_cover_cannot_register(self):
        self.assertIsNone(self.router.register_device('sensor-only', '窗帘', [
            {'entity_id': 'sensor.power', 'domain': 'sensor', 'device_class': 'power'}
        ]))

    async def test_normal_switch_still_routes_turn_on(self):
        vd = self.router.register_device('breaker', '空气开关', [
            {'entity_id': 'switch.main', 'domain': 'switch'}
        ], model='ykcn.valve.cbcs')
        self.assertTrue(self.router.route_action(vd.sn, {'on': 1}))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        self.services.async_call.assert_awaited_with(
            domain='switch', service='turn_on', target={'entity_id': 'switch.main'}, service_data={})


if __name__ == '__main__':
    unittest.main()
