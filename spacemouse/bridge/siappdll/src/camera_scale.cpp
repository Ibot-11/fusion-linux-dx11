// GPL-3.0-or-later. Changes process data only; no Autodesk file is patched.
#include "camera_scale.h"
#include "log.h"
#include <bcrypt.h>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>

namespace {
constexpr size_t camera_rva = 0x8e4fe0;
constexpr size_t camera_size = 0x886;
constexpr size_t normalizer_rva = 0x21755b0;
constexpr unsigned char camera_sha256[32] = {
    0x87,0x29,0x76,0xe2,0xa4,0xea,0x49,0x86,0x0e,0x48,0x2f,0x5a,0x62,0x7a,0x9a,0x36,
    0x45,0x8e,0xfb,0x15,0xcc,0x29,0x5e,0x7f,0xc7,0x6a,0x8c,0x6d,0xd1,0x00,0x0e,0x11
};
double* changed_normalizer = nullptr;
double installed_normalizer = 0;

bool camera_matches(unsigned char* code) {
    BCRYPT_ALG_HANDLE algorithm = nullptr;
    BCRYPT_HASH_HANDLE hash = nullptr;
    unsigned char actual[32];
    bool ok = BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0) >= 0;
    if (ok) ok = BCryptCreateHash(algorithm, &hash, nullptr, 0, nullptr, 0, 0) >= 0;
    if (ok) ok = BCryptHashData(hash, code, camera_size, 0) >= 0;
    if (ok) ok = BCryptFinishHash(hash, actual, sizeof(actual), 0) >= 0;
    if (hash) BCryptDestroyHash(hash);
    if (algorithm) BCryptCloseAlgorithmProvider(algorithm, 0);
    return ok && std::memcmp(actual, camera_sha256, sizeof(actual)) == 0;
}
}

double* fusion_camera_normalizer(HMODULE module) {
    if (!module) return nullptr;
    auto base = reinterpret_cast<unsigned char*>(module);
    auto dos = reinterpret_cast<IMAGE_DOS_HEADER*>(base);
    if (dos->e_magic != IMAGE_DOS_SIGNATURE || dos->e_lfanew <= 0 || dos->e_lfanew > 4096)
        return nullptr;
    auto nt = reinterpret_cast<IMAGE_NT_HEADERS64*>(base + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE ||
        nt->OptionalHeader.Magic != IMAGE_NT_OPTIONAL_HDR64_MAGIC ||
        nt->FileHeader.TimeDateStamp != 0x6abeff5c ||
        nt->OptionalHeader.SizeOfImage != 0x2300000 ||
        !camera_matches(base + camera_rva)) return nullptr;

    // All six camera divisions (three rotation, two pan, one zoom) use this
    // same double. Check the RIP targets as well as the complete code digest.
    constexpr size_t divisions[] = {0x39b, 0x3cb, 0x47f, 0x6c9, 0x6df, 0x7b5};
    for (size_t offset : divisions) {
        auto instruction = base + camera_rva + offset;
        std::int32_t displacement;
        std::memcpy(&displacement, instruction + 4, sizeof(displacement));
        if (instruction[0] != 0xf2 || instruction[1] != 0x0f || instruction[2] != 0x5e ||
            instruction + 8 + displacement != base + normalizer_rva) return nullptr;
    }
    auto result = reinterpret_cast<double*>(base + normalizer_rva);
    MEMORY_BASIC_INFORMATION memory{};
    if (!VirtualQuery(result, &memory, sizeof(memory)) || memory.State != MEM_COMMIT ||
        (memory.Protect != PAGE_READWRITE && memory.Protect != PAGE_WRITECOPY)) return nullptr;
    return result;
}

bool set_camera_normalizer(double* normalizer, double scale) {
    if (!normalizer || !std::isfinite(scale) || scale < 0.04 || scale > 1.0 ||
        *normalizer != 1024.0) return false;
    *normalizer = 1024.0 / scale;
    return true;
}

void apply_camera_scale() {
    if (changed_normalizer) return;
    char value[64];
    DWORD size = GetEnvironmentVariableA("FUSION_SPACEMOUSE_CAMERA_SCALE", value, sizeof(value));
    if (!size) return;
    char* end = nullptr;
    double scale = size < sizeof(value) ? std::strtod(value, &end) : 0;
    if (scale == 1.0 && end && *end == '\0') return;
    auto normalizer = fusion_camera_normalizer(GetModuleHandleW(L"NuBase10.dll"));
    if (!end || *end != '\0' || !set_camera_normalizer(normalizer, scale)) {
        LOG(ERROR) << "Camera scale not applied: invalid setting or unsupported Fusion camera routine";
        return;
    }
    changed_normalizer = normalizer;
    installed_normalizer = *normalizer;
    LOG(INFO) << "Camera floating-point scale applied: " << scale
              << "; all six input integers remain unchanged";
}

void restore_camera_scale() {
    if (changed_normalizer && *changed_normalizer == installed_normalizer)
        *changed_normalizer = 1024.0;
    changed_normalizer = nullptr;
}
