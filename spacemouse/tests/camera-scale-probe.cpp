// Run under the actual Proton against the installed, unmodified NuBase10.dll.
// Map its PE sections as inert data: no Fusion entry point or imports are run.
#include "camera_scale.h"
#include <cassert>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <iterator>
#include <limits>
#include <string>
#include <vector>

int main(int argc, char** argv) {
    char executable[MAX_PATH];
    GetModuleFileNameA(nullptr, executable, sizeof(executable));
    std::string log(executable);
    log = log.substr(0, log.find_last_of("\\/")) + "\\camera-scale-probe.log";
    std::freopen(log.c_str(), "w", stdout);
    assert(argc == 2);
    std::ifstream input(argv[1], std::ios::binary);
    assert(input);
    std::vector<char> raw((std::istreambuf_iterator<char>(input)), {});
    auto dos = reinterpret_cast<IMAGE_DOS_HEADER*>(raw.data());
    auto nt = reinterpret_cast<IMAGE_NT_HEADERS64*>(raw.data() + dos->e_lfanew);
    auto image = static_cast<unsigned char*>(VirtualAlloc(nullptr, nt->OptionalHeader.SizeOfImage,
                                                        MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE));
    assert(image);
    std::memcpy(image, raw.data(), nt->OptionalHeader.SizeOfHeaders);
    auto section = IMAGE_FIRST_SECTION(nt);
    for (unsigned i = 0; i < nt->FileHeader.NumberOfSections; ++i)
        std::memcpy(image + section[i].VirtualAddress, raw.data() + section[i].PointerToRawData,
                    section[i].SizeOfRawData);
    auto module = reinterpret_cast<HMODULE>(image);
    auto normalizer = fusion_camera_normalizer(module);
    assert(normalizer && *normalizer == 1024.0);
    double original = *normalizer;
    assert(set_camera_normalizer(normalizer, .8));
    assert(*normalizer == 1280.0);
    // Exact requested ratio; every neighboring integer remains distinguishable.
    for (int axis = 0; axis < 6; ++axis) {
        for (int sample = -350; sample <= 350; ++sample) {
            assert(double(sample) / *normalizer != double(sample + 1) / *normalizer);
            assert(std::abs(double(sample) / *normalizer - .8 * sample / original) < 1e-15);
        }
    }
    *normalizer = original;
    for (double scale : {0., -1., .009, 4.1, std::numeric_limits<double>::quiet_NaN()}) {
        assert(!set_camera_normalizer(normalizer, scale));
        assert(*normalizer == original);
    }
    *normalizer = 512.; // Unexpected concurrent/custom value is not overwritten.
    assert(!set_camera_normalizer(normalizer, .8));
    *normalizer = original;
    // A launch at any native factor (including an old 15% / basis-1 launch)
    // can change across the full percentage range without touching integers
    // or pretending the newly saved next-start basis is already in memory.
    for(int basis=1;basis<=4;++basis) {
        for(int percent:{15,100,1,75,20,50,25,100,1}) {
            auto result=update_camera_percent(module,basis,percent);
            assert(result.status==0 && result.percent==percent);
            assert(std::abs(*normalizer-1024.*25*basis/percent)<1e-8);
            for(int sample=-350;sample<=350;++sample) {
                double actual=double(sample*basis)/ *normalizer;
                assert(std::abs(actual-double(sample*4)/1024.*percent/100.)<1e-14);
                assert(actual!=double((sample+1)*basis)/ *normalizer);
            }
        }
        restore_camera_scale();assert(*normalizer==original);
    }
    assert(update_camera_percent(module,0,15).status==2);
    assert(update_camera_percent(module,5,15).status==2);
    assert(update_camera_percent(module,1,101).status==4);
    assert(update_camera_percent(nullptr,1,15).status==5);
    assert(update_camera_percent(module,1,15).status==0);
    *normalizer=512.;
    assert(update_camera_percent(module,1,20).status==3);
    restore_camera_scale();assert(*normalizer==512.); // Never undo an outside writer.
    *normalizer=original;
    // A different camera routine / build is rejected without a data write.
    image[0x8e4fe0] ^= 1;
    assert(!fusion_camera_normalizer(module));
    assert(update_camera_percent(module,1,20).status==1);
    assert(*normalizer == original);
    image[0x8e4fe0] ^= 1;
    assert(fusion_camera_normalizer(module) == normalizer);
    auto mapped_nt = reinterpret_cast<IMAGE_NT_HEADERS64*>(image + dos->e_lfanew);
    mapped_nt->FileHeader.TimeDateStamp ^= 1;
    assert(!fusion_camera_normalizer(module));
    assert(*normalizer == original);
    VirtualFree(image, 0, MEM_RELEASE);
    std::puts("PASS: actual Fusion PE, live 1..100% for native bases 1..4, repeated updates, raw-count distinction, restore, invalid/conflicting data and unknown builds");
}
