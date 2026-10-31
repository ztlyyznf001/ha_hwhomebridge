"""Additional lamp-profile controls, keeping the existing curtain switch identity."""
import math

from .product_registry import HAMapping
from .virtual_device import VirtualDevice, ServiceEntry, SNManager

SUFFIX = ':curtain-controls-v1'


def companion_id(device_id):
    return device_id + SUFFIX


def cover_value(mapping, state):
    """Return a known position/motion/open value, or None when unavailable."""
    if state is None or state.state in ('unknown', 'unavailable', ''):
        return None
    if mapping.value_attr == 'current_position':
        value = state.attributes.get('current_position')
        if (isinstance(value, (int, float)) and not isinstance(value, bool)
                and math.isfinite(value) and 0 <= value <= 100):
            return round(value)
        return None
    if mapping.action == 'stop_cover':
        return int(state.state in ('opening', 'closing')) if state.state in (
            'open', 'closed', 'opening', 'closing') else None
    if state.state == 'closed':
        return 0
    if state.state in ('open', 'opening', 'closing'):
        return 1
    return None


def build_companion(router, parent, name):
    """Build one stable companion only for the existing cover-to-switch adapter."""
    switch = parent.product.services.get('switch')
    if (parent.product.pid != '008' or switch is None
            or switch.ha_mapping.domain != 'cover'):
        return None
    entity_id = parent.get_entity_for_service('switch')
    if not entity_id:
        return None
    product = router.registry.merge(router.registry.get_product('002'))
    product.name = (name or '窗帘') + ' 开度与暂停'
    product.services['switch'].ha_mapping = HAMapping(
        domain='cover', action='stop_cover', value_attr='state')
    product.services['brightness'].ha_mapping = HAMapping(
        domain='cover', action='set_cover_position', value_attr='current_position')
    product.services['cct'].ha_mapping = HAMapping(domain='')
    key = companion_id(parent.ha_device_id)
    vd = VirtualDevice(SNManager.generate_sn(key), product, key)
    vd.source_device_id = parent.ha_device_id
    vd.display_name = product.name
    for service in ('switch', 'brightness'):
        vd.add_service_entry(service, ServiceEntry(entity_id, 'cover', service))
    return vd
