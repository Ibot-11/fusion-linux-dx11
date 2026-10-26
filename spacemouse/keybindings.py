# SPDX-License-Identifier: GPL-3.0-or-later
"""Validated logical key bindings and the physical-button chord wire contract.

Printable keys are resolved in the focused Windows keyboard layout by the DLL.
The Linux side never captures a system keyboard or creates a virtual keyboard.
"""
import struct

PACKET = struct.Struct('<8i')
MODIFIERS = ('CTRL', 'SHIFT', 'ALT', 'META', 'ALTGR')
MODIFIER_BITS = {name: 1 << index for index, name in enumerate(MODIFIERS)}
LEGACY = ('ESC', 'I', 'F', 'HOME', '1', '2', '3', 'off', 'sdk')
# Windows VK values plus the mandatory extended-key bit for this named key.
NAMED_KEYS = {
    'ESC': (0x1b, False), 'TAB': (0x09, False), 'ENTER': (0x0d, False),
    'BACKSPACE': (0x08, False), 'DELETE': (0x2e, True), 'INSERT': (0x2d, True),
    'HOME': (0x24, True), 'END': (0x23, True), 'PAGEUP': (0x21, True),
    'PAGEDOWN': (0x22, True), 'LEFT': (0x25, True), 'RIGHT': (0x27, True),
    'UP': (0x26, True), 'DOWN': (0x28, True), 'PAUSE': (0x13, False),
    'PRINTSCREEN': (0x2c, True), 'CAPSLOCK': (0x14, False), 'NUMLOCK': (0x90, True),
    'SCROLLLOCK': (0x91, False), 'MENU': (0x5d, True), 'SPACE': (0x20, False),
    'NUMENTER': (0x0d, True), 'NUMADD': (0x6b, False), 'NUMSUBTRACT': (0x6d, False),
    'NUMMULTIPLY': (0x6a, False), 'NUMDIVIDE': (0x6f, True), 'NUMDECIMAL': (0x6e, False),
    **{f'NUM{index}': (0x60 + index, False) for index in range(10)},
    **{f'F{index}': (0x6f + index, False) for index in range(1, 25)},
}


def canonical_key(value):
    if not isinstance(value, str) or not value:
        raise ValueError('A shortcut needs a named key or one printable BMP character.')
    if value.upper() in NAMED_KEYS or value.upper() in MODIFIER_BITS:
        return value.upper()
    if len(value) != 1 or ord(value) > 0xffff or not value.isprintable():
        raise ValueError('A shortcut key must be a supported name or one printable Unicode BMP character.')
    if value == ' ':
        return 'SPACE'
    # Qt logical Latin keys are uppercase; explicit SHIFT determines the chord.
    return value.upper() if 'a' <= value <= 'z' else value


def normalize_binding(value):
    if isinstance(value, str):
        if value not in LEGACY:
            raise ValueError('Unknown legacy button binding; use a shortcut object for custom keys.')
        return value
    if not isinstance(value, dict) or set(value) != {'key', 'modifiers'}:
        raise ValueError('A custom binding must contain exactly key and modifiers.')
    key = canonical_key(value['key'])
    modifiers = value['modifiers']
    if not isinstance(modifiers, list) or any(not isinstance(item, str) for item in modifiers):
        raise ValueError('Shortcut modifiers must be a list of modifier names.')
    modifiers = [item.upper() for item in modifiers]
    if len(modifiers) > len(MODIFIERS) or any(item not in MODIFIER_BITS for item in modifiers):
        raise ValueError('Supported modifiers are CTRL, SHIFT, ALT, META and ALTGR.')
    if len(set(modifiers)) != len(modifiers):
        raise ValueError('A shortcut must not repeat a modifier.')
    return {'key': key, 'modifiers': [item for item in MODIFIERS if item in modifiers]}


def button_packet(index, pressed, binding):
    if type(index) is not int or index not in (0, 1) or type(pressed) is not bool:
        raise ValueError('A button packet needs a physical button ID and boolean state.')
    binding = normalize_binding(binding)
    if binding == 'off':
        return None
    if binding == 'sdk':
        return PACKET.pack(1 if pressed else 2, index, 0, 0, 0, 0, 0, 0)
    if isinstance(binding, str):
        binding = {'key': binding, 'modifiers': []}
    key = binding['key']
    mask = sum(MODIFIER_BITS[item] for item in binding['modifiers'])
    if key in MODIFIER_BITS:
        # Modifier-only holds have no main key; duplicate modifiers coalesce.
        return PACKET.pack(4, index, int(pressed), 0, 0, mask | MODIFIER_BITS[key], 0, 0)
    if key in NAMED_KEYS:
        vk, extended = NAMED_KEYS[key]
        return PACKET.pack(4, index, int(pressed), 0, vk, mask, int(extended), 0)
    return PACKET.pack(4, index, int(pressed), 1, ord(key), mask, 0, 0)
