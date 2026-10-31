import ast
import asyncio
import importlib
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import test_curtain_compat as base

controls = importlib.import_module(base.PACKAGE + '.curtain_controls')


def bridge_functions(names, globals):
    tree = ast.parse((base.ROOT / 'custom_components/hwhomebridge/hwbridge.py').read_text())
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert len(nodes) == len(names)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'hwbridge.py', 'exec'), globals)
    return globals


class CurtainAdvancedTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = base.CurtainCompatibilityTests.asyncSetUp

    def companion(self):
        self.state.attributes.update(supported_features=15, current_position=40)
        vd = controls.build_companion(self.router, self.vd, '客厅窗帘')
        self.router.sn_manager.register(vd)
        return vd

    async def settle(self):
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    async def test_position_range_and_mixed_payload_order(self):
        vd = self.companion()
        for payload, expected in [({'brightness': 0}, 0), ({'on': 1, 'brightness': 50}, 50),
                                  ({'brightness': 100, 'on': 1}, 100)]:
            self.assertTrue(self.router.route_action(vd.sn, payload))
            await self.settle()
            self.services.async_call.assert_awaited_with(domain='cover', service='set_cover_position',
                target={'entity_id': self.entity}, service_data={'position': expected})
        self.assertEqual(self.services.async_call.await_count, 3)

    async def test_either_power_button_stops_and_never_closes(self):
        vd = self.companion()
        for on in (0, 1):
            self.assertTrue(self.router.route_action(vd.sn, {'on': on}))
            await self.settle()
            self.services.async_call.assert_awaited_with(domain='cover', service='stop_cover',
                target={'entity_id': self.entity}, service_data={})

    async def test_bad_positions_and_missing_capabilities_do_not_move(self):
        vd = self.companion()
        for value in (-1, 101, True, None, '50', float('nan'), float('inf')):
            self.assertFalse(self.router.route_action(vd.sn, {'on': 1, 'brightness': value}))
        self.state.attributes['supported_features'] = 3
        self.assertFalse(self.router.route_action(vd.sn, {'brightness': 50}))
        self.assertFalse(self.router.route_action(vd.sn, {'on': 1}))
        await self.settle()
        self.services.async_call.assert_not_called()

    async def test_actual_position_and_motion_reports_match_sdk_queries(self):
        vd = self.companion()
        self.router._update_hw_bridge_status = Mock()
        for state, moving in [('opening', 1), ('closing', 1), ('open', 0), ('closed', 0)]:
            self.state.state = state
            self.router.report_state(vd.sn, self.entity, self.state)
            self.assertEqual(json.loads(self.router.get_char_state(vd.sn, 'brightness')), {'brightness': 40})
            self.assertEqual(json.loads(self.router.get_char_state(vd.sn, 'switch')), {'on': moving})
            self.router._update_hw_bridge_status.assert_any_call(vd.sn, 'brightness', {'brightness': 40})
            self.router._update_hw_bridge_status.assert_any_call(vd.sn, 'switch', {'on': moving})
        for value in (None, -1, 101, True, float('nan')):
            self.state.attributes['current_position'] = value
            self.assertIsNone(self.router.get_char_state(vd.sn, 'brightness'))
        self.state.state = 'unavailable'
        self.assertIsNone(self.router.get_char_state(vd.sn, 'switch'))

    async def test_stable_separate_identity_and_multi_device_events(self):
        vd = self.companion()
        self.assertNotEqual(vd.sn, self.vd.sn)
        self.assertEqual(vd.sn, controls.build_companion(self.router, self.vd, '重命名').sn)
        self.assertIs(self.router.sn_manager.get_by_device_id('curtain-device'), self.vd)
        self.assertEqual(len(self.router.sn_manager.get_virtual_devices_by_entity(self.entity)), 2)
        self.router.report_state = Mock()
        self.router.register_device_to_hilink = Mock()
        env = bridge_functions(['handle_state_event'], dict(bridge_work=True, service_router=self.router,
            _is_device_disabled=lambda _: False, _excluded_device_sns=set()))
        event = SimpleNamespace(data={'entity_id': self.entity, 'old_state': None, 'new_state': self.state})
        env['handle_state_event'](event)
        self.assertEqual(self.router.report_state.call_count, 2)
        event.data['new_state'] = None
        env['handle_state_event'](event)
        self.router.register_device_to_hilink.assert_any_call(vd.sn, 0)
        self.router.register_device_to_hilink.assert_any_call(self.vd.sn, 0)

    async def test_excluded_companion_receives_no_reports(self):
        vd = self.companion()
        self.router.report_state = Mock()
        self.router.register_device_to_hilink = Mock()
        env = bridge_functions(['handle_state_event'], dict(bridge_work=True, service_router=self.router,
            _is_device_disabled=lambda _: False, _excluded_device_sns={vd.sn}))
        env['handle_state_event'](SimpleNamespace(data={'entity_id': self.entity, 'new_state': self.state}))
        self.router.report_state.assert_called_once_with(self.vd.sn, self.entity, self.state)

    async def test_integer_sdk_callback_uses_cover_position_and_motion(self):
        vd = self.companion()
        env = bridge_functions(['OnDevStatusCB'], dict(service_router=self.router, ghass=self.hass,
            cover_value=controls.cover_value, _LOGGER=Mock()))
        self.state.state = 'opening'
        self.assertEqual(env['OnDevStatusCB'](vd.sn.encode(), b'brightness'), 40)
        self.assertEqual(env['OnDevStatusCB'](vd.sn.encode(), b'switch'), 1)
        self.assertEqual(env['OnDevStatusCB'](self.vd.sn.encode(), b'switch'), 1)

    async def test_registration_persists_companion_and_does_not_duplicate(self):
        saved = set()
        self.router.register_device_to_hilink = Mock()
        env = bridge_functions(['_register_curtain_controls'], dict(service_router=self.router,
            build_companion=controls.build_companion, saved_device_ids=saved,
            _save_device_id=saved.add, _excluded_device_sns=set(), _is_device_disabled=lambda _: False,
            _create_bridge_device_entry=Mock()))
        fn = env['_register_curtain_controls']
        fn(self.vd, '客厅窗帘', 'curtain.model', 'xiaomi')
        fn(self.vd, '客厅窗帘', 'curtain.model', 'xiaomi')
        self.assertEqual(len(self.router.sn_manager.get_all_devices()), 2)
        statuses = [c.args[1] for c in self.router.register_device_to_hilink.call_args_list]
        self.assertEqual(statuses, [3, 1, 1])
        fn(self.vd, '客厅窗帘', 'curtain.model', 'xiaomi', enabled=False)
        self.assertEqual(self.router.register_device_to_hilink.call_args.args[1], 0)
