// SPDX-License-Identifier: GPL-3.0-or-later
#include "key_chords.h"
#include <cassert>
#include <iostream>
#include <tuple>
using namespace fusion_keys;
using Event = std::tuple<unsigned short, bool, bool>;

int main() {
    std::vector<Event> events;
    bool fail_down = false, fail_up = false;
    unsigned short fail_vk = 0;
    State state([&](Key key, bool down) {
        if ((down && (fail_down || key.vk == fail_vk)) || (!down && fail_up)) return false;
        events.emplace_back(key.vk, key.extended, down);
        return true;
    });
    auto expect = [&](std::vector<Event> wanted) { assert(events == wanted); events.clear(); };
    const Key ctrl = {0xa2, false}, shift = {0xa0, false};
    const Chord save = {{ctrl}, {'S', false}}, undo = {{ctrl}, {'Z', false}};
    assert(state.press(0, save)); assert(state.press(1, undo));
    state.release_button(0);
    expect({{0xa2,false,true},{'S',false,true},{'Z',false,true},{'S',false,false}});
    state.release_button(1);
    expect({{'Z',false,false},{0xa2,false,false}});

    // Identical chords and repeated physical-down packets never double-inject.
    assert(state.press(0, save)); assert(state.press(0, undo)); assert(state.press(1, save));
    state.release_button(0);
    expect({{0xa2,false,true},{'S',false,true}});
    state.release_button(1);
    expect({{'S',false,false},{0xa2,false,false}});

    // A modifier-only hold overlaps a modified shortcut.
    assert(state.press(0, {{ctrl,shift}, {}}));
    assert(state.press(1, {{ctrl}, {'A',false}}));
    state.release_button(0);
    expect({{0xa2,false,true},{0xa0,false,true},{'A',false,true},{0xa0,false,false}});
    state.clear();
    expect({{'A',false,false},{0xa2,false,false}});
    state.clear(); expect({});

    // Stored press survives rebinding; kind-3 owners share the same key.
    assert(state.press(0, {{}, {0x1b,false}}));
    state.legacy({0x1b,false}, true); state.release_button(0);
    expect({{0x1b,false,true}});
    state.legacy({0x1b,false},false); expect({{0x1b,false,false}});
    assert(state.press(0, save)); assert(state.press(0, undo)); state.release_button(0);
    expect({{0xa2,false,true},{'S',false,true},{'S',false,false},{0xa2,false,false}});

    // Ordinary Enter and keypad Enter keep their distinct scan prefixes.
    assert(state.press(0, {{}, {0x0d,false}})); assert(state.press(1, {{}, {0x0d,true}}));
    state.clear(); expect({{0x0d,false,true},{0x0d,true,true},{0x0d,false,false},{0x0d,true,false}});

    // Failed injection is rolled back; failed release remains retryable.
    fail_down = true; assert(!state.press(0, save)); expect({});
    fail_down = false; fail_vk = 'S'; assert(!state.press(0, save));
    expect({{0xa2,false,true},{0xa2,false,false}}); // Partial press rolled back.
    fail_vk = 0; assert(state.press(0, save)); events.clear();
    fail_up = true; state.clear(); expect({});
    fail_up = false; state.retry_releases();
    expect({{'S',false,false},{0xa2,false,false}});
    state.retry_releases(); expect({});

    int p[8] = {4,0,1,1,'S',3,0,0}; assert(valid_packet(p));
    for (auto pair : std::vector<std::pair<int,int>>{{1,2},{2,2},{3,2},{4,0xd800},{4,0x7f},{5,32},{6,1},{7,1}}) {
        int bad[8]; for(int i=0;i<8;++i)bad[i]=p[i]; bad[pair.first]=pair.second;
        assert(!valid_packet(bad));
    }
    int modifier[8] = {4,1,1,0,0,16,0,0}; assert(valid_packet(modifier));
    modifier[5]=0; assert(!valid_packet(modifier));
    assert(named_key(0x0d,0) && named_key(0x0d,1));
    assert(named_key(0x6f,1) && !named_key(0x6f,0));
    assert(!named_key('A',0) && !named_key(0x24,0));
    // Python supplies every named-key/modifier packet, proving the producer's
    // schema and the actual DLL whitelist agree (including keypad variants).
    int wire[8];
    while(std::cin >> wire[0]) {
        for(int i=1;i<8;++i) assert(bool(std::cin >> wire[i]));
        assert(valid_packet(wire));
    }
}
