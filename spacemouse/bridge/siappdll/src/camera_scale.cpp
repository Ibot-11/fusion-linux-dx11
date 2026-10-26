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
HMODULE changed_module = nullptr;
int session_basis = 0;
bool session_initialized = false, session_authenticated = false;
unsigned char session_token[16] = {};

bool readable(const void* pointer, size_t length) {
    MEMORY_BASIC_INFORMATION memory{};
    if (!VirtualQuery(pointer,&memory,sizeof(memory)) || memory.State!=MEM_COMMIT ||
        (memory.Protect & (PAGE_NOACCESS|PAGE_GUARD))) return false;
    return reinterpret_cast<std::uintptr_t>(pointer)+length <=
           reinterpret_cast<std::uintptr_t>(memory.BaseAddress)+memory.RegionSize;
}

bool exchange_normalizer(double* normalizer, double expected, double value) {
    LONG64 expected_bits, value_bits;
    std::memcpy(&expected_bits, &expected, sizeof(expected_bits));
    std::memcpy(&value_bits, &value, sizeof(value_bits));
    return InterlockedCompareExchange64(reinterpret_cast<volatile LONG64*>(normalizer), value_bits, expected_bits) == expected_bits;
}

int owned_scale(HMODULE module, double scale) {
    if (!module) return 5;
    auto normalizer = fusion_camera_normalizer(module);
    if (!normalizer) return 1;
    if (!std::isfinite(scale) || scale < .01 || scale > 4.) return 4;
    if (changed_normalizer && normalizer != changed_normalizer) return 3;
    const double expected = changed_normalizer ? installed_normalizer : 1024.;
    const double value = 1024. / scale;
    if (!exchange_normalizer(normalizer, expected, value)) return 3;
    changed_module = module;
    changed_normalizer = normalizer;
    installed_normalizer = value;
    return *normalizer == value ? 0 : 3;
}

void initialize_session() {
    if (session_initialized) return;
    session_initialized = true;
    char basis[16], token[64];
    DWORD size = GetEnvironmentVariableA("FUSION_SPACEMOUSE_CAMERA_BASE", basis, sizeof(basis));
    char* end = nullptr;
    long native = size && size < sizeof(basis) ? std::strtol(basis, &end, 10) : -1;
    if (!end || *end || native < 0 || native > 4) return;
    session_basis = (int)native;
    if (GetEnvironmentVariableA("FUSION_SPACEMOUSE_CAMERA_SESSION", token, sizeof(token)) != 32) return;
    auto digit = [](char c) -> int {
        if(c>='0'&&c<='9')return c-'0'; if(c>='a'&&c<='f')return c-'a'+10;
        if(c>='A'&&c<='F')return c-'A'+10; return -1;
    };
    for(int i=0;i<16;++i) {
        int hi=digit(token[i*2]), lo=digit(token[i*2+1]);
        if(hi<0||lo<0)return;
        session_token[i]=(unsigned char)((hi<<4)|lo);
    }
    session_authenticated = true;
}

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
    if (!module || !readable(module,sizeof(IMAGE_DOS_HEADER))) return nullptr;
    auto base = reinterpret_cast<unsigned char*>(module);
    auto dos = reinterpret_cast<IMAGE_DOS_HEADER*>(base);
    if (dos->e_magic != IMAGE_DOS_SIGNATURE || dos->e_lfanew <= 0 || dos->e_lfanew > 4096)
        return nullptr;
    if (!readable(base+dos->e_lfanew,sizeof(IMAGE_NT_HEADERS64))) return nullptr;
    auto nt = reinterpret_cast<IMAGE_NT_HEADERS64*>(base + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE ||
        nt->OptionalHeader.Magic != IMAGE_NT_OPTIONAL_HDR64_MAGIC ||
        nt->FileHeader.TimeDateStamp != 0x6abeff5c ||
        nt->OptionalHeader.SizeOfImage != 0x2300000 || !readable(base+camera_rva,camera_size) ||
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
    return normalizer && std::isfinite(scale) && scale >= .01 && scale <= 4. &&
           exchange_normalizer(normalizer, 1024., 1024. / scale);
}

void apply_camera_scale() {
    initialize_session();
    if (changed_normalizer) return;
    char value[64];
    DWORD size = GetEnvironmentVariableA("FUSION_SPACEMOUSE_CAMERA_SCALE", value, sizeof(value));
    if (!size) return;
    char* end = nullptr;
    double scale = size < sizeof(value) ? std::strtod(value, &end) : 0;
    if (!end || *end != '\0') {
        LOG(ERROR) << "Camera scale not applied: invalid numeric setting";
        return;
    }
    int status=owned_scale(GetModuleHandleW(L"NuBase10.dll"), scale);
    if(status==5) {
        LOG(INFO) << "Camera module is not loaded; live control will retry when available";
        return;
    }
    if(status) {
        LOG(ERROR) << "Camera scale not applied: invalid setting or unsupported Fusion camera routine";
        return;
    }
    LOG(INFO) << "Camera floating-point scale applied: " << scale
              << "; all six input integers remain unchanged";
}

void restore_camera_scale() {
    if (changed_normalizer && fusion_camera_normalizer(changed_module) == changed_normalizer)
        exchange_normalizer(changed_normalizer, installed_normalizer, 1024.);
    changed_normalizer = nullptr;
    changed_module = nullptr;
    session_initialized = session_authenticated = false;
    session_basis = 0;
}

CameraResult update_camera_percent(HMODULE module, int basis, int percent) {
    if (basis < 1 || basis > 4) return {2, 0};
    if (percent < 1 || percent > 100) return {4, 0};
    int status = owned_scale(module, percent / (25. * basis));
    if (status) return {status, 0};
    // Confirm the current data value; do not echo an unverified request.
    const double actual = 25. * basis * 1024. / *changed_normalizer;
    int rounded = (int)std::lround(actual);
    if (rounded != percent || std::abs(actual-rounded) > 1e-8) return {3, 0};
    return {0, rounded};
}

bool camera_protocol_hello(int* packet) {
    initialize_session();
    if (!session_authenticated) return false;
    packet[0]=5; packet[1]=1;
    std::memcpy(packet+2,session_token,sizeof(session_token));
    packet[6]=session_basis; packet[7]=(int)GetCurrentProcessId();
    return true;
}

bool camera_protocol_reply(const int* request, int* reply) {
    if (request[0]!=6 || request[1]<=0 || request[7]!=1 || !session_authenticated) return false;
    CameraResult result = update_camera_percent(GetModuleHandleW(L"NuBase10.dll"), session_basis, request[6]);
    std::memcpy(reply,request,6*sizeof(int));
    reply[0]=7; reply[6]=result.status; reply[7]=result.percent;
    return true;
}
