// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <array>
#include <cstdint>
#include <functional>
#include <vector>

namespace fusion_keys {
struct Key {
    unsigned short vk = 0;
    bool extended = false;
};
struct Chord {
    std::vector<Key> modifiers;
    Key main;
};

// Validate the fixed physical-button protocol before resolving any layout key.
// The named VK list is deliberately identical to keybindings.py.
inline bool named_key(int vk, int extended) {
    switch (vk) {
    case 0x08: case 0x09: case 0x13: case 0x14: case 0x1b:
    case 0x20: case 0x6a: case 0x6b: case 0x6d: case 0x6e: case 0x91:
        return extended == 0;
    case 0x0d: return extended == 0 || extended == 1; // Enter / keypad Enter.
    case 0x21: case 0x22: case 0x23: case 0x24: case 0x25: case 0x26:
    case 0x27: case 0x28: case 0x2c: case 0x2d: case 0x2e: case 0x5d: case 0x6f: case 0x90:
        return extended == 1;
    default:
        return ((vk >= 0x60 && vk <= 0x69) || (vk >= 0x70 && vk <= 0x87)) && extended == 0;
    }
}
inline bool valid_packet(const int* p) {
    if (p[0] != 4 || p[1] < 0 || p[1] > 1 || (p[2] != 0 && p[2] != 1) ||
        p[5] < 0 || (p[5] & ~31) || p[7] != 0) return false;
    if (p[3] == 0)
        return p[4] == 0 ? p[5] != 0 && p[6] == 0 : named_key(p[4], p[6]);
    return p[3] == 1 && p[6] == 0 && p[4] >= 0x20 && p[4] <= 0xfffd &&
        !(p[4] >= 0x7f && p[4] <= 0x9f) && !(p[4] >= 0xd800 && p[4] <= 0xdfff);
}

// Resolved presses belong to physical buttons, independent of later rebinding
// or keyboard-layout changes. Shared VKs remain down until their last owner
// releases them. The callback is also used by the native regression test.
class State {
    struct Hold { Chord chord; bool active = false; };
    std::array<Hold, 2> buttons_{};
    std::array<Key, 256> legacy_{};
    std::array<unsigned int, 512> refs_{};
    std::array<bool, 512> actual_{};
    std::function<bool(Key, bool)> send_;

    bool acquire(Key key) {
        if (!key.vk || key.vk > 255) return false;
        const unsigned int id = key.vk + (key.extended ? 256 : 0);
        if (!refs_[id] && !actual_[id]) {
            if (!send_(key, true)) return false;
            actual_[id] = true;
        }
        ++refs_[id];
        return true;
    }
    void release(Key key) {
        if (!key.vk || key.vk > 255) return;
        const unsigned int id = key.vk + (key.extended ? 256 : 0);
        if (!refs_[id]) return;
        --refs_[id];
        if (!refs_[id] && actual_[id] && send_(key, false)) actual_[id] = false;
    }
public:
    explicit State(std::function<bool(Key, bool)> send) : send_(send) {}
    bool press(unsigned int button, const Chord& chord) {
        if (button >= buttons_.size()) return false;
        if (buttons_[button].active) return true; // No repeat or rebinding while held.
        std::vector<Key> acquired;
        for (Key key : chord.modifiers) {
            if (!acquire(key)) {
                for (auto it = acquired.rbegin(); it != acquired.rend(); ++it) release(*it);
                return false;
            }
            acquired.push_back(key);
        }
        if (chord.main.vk && !acquire(chord.main)) {
            for (auto it = acquired.rbegin(); it != acquired.rend(); ++it) release(*it);
            return false;
        }
        buttons_[button] = {chord, true};
        return true;
    }
    void release_button(unsigned int button) {
        if (button >= buttons_.size() || !buttons_[button].active) return;
        auto& hold = buttons_[button];
        release(hold.chord.main); // Main key always precedes its modifiers.
        for (auto it = hold.chord.modifiers.rbegin(); it != hold.chord.modifiers.rend(); ++it)
            release(*it);
        hold = {};
    }
    void legacy(Key key, bool down) {
        if (!key.vk || key.vk > 255 || (legacy_[key.vk].vk != 0) == down) return;
        if (down) { if (acquire(key)) legacy_[key.vk] = key; }
        else { release(legacy_[key.vk]); legacy_[key.vk] = {}; }
    }
    void retry_releases() {
        for (unsigned int id = 1; id < 512; ++id)
            if (!refs_[id] && actual_[id] && send_({(unsigned short)(id & 255), id >= 256}, false)) actual_[id] = false;
    }
    void clear() {
        release_button(0);
        release_button(1);
        for (unsigned short vk = 1; vk < 256; ++vk)
            if (legacy_[vk].vk) { release(legacy_[vk]); legacy_[vk] = {}; }
        retry_releases();
    }
};
} // namespace fusion_keys
