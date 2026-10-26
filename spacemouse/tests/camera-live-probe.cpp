// SPDX-License-Identifier: GPL-3.0-or-later
// Private test process only. Autodesk's PE is mapped without entry points or
// imports (DONT_RESOLVE_DLL_REFERENCES); none of its functions are called.
#include <windows.h>
#include <cassert>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <string>
#include "siappdll.h"

int main(int argc,char** argv) {
    assert(argc==4);
    char executable[MAX_PATH];GetModuleFileNameA(nullptr,executable,sizeof(executable));
    *strrchr(executable,'\\')=0;SetCurrentDirectoryA(executable);
    freopen("camera-live-probe.log","w",stdout);setbuf(stdout,nullptr);
    SetEnvironmentVariableA("FUSION_SPACEMOUSE_CAMERA_SCALE","0.6");
    SetEnvironmentVariableA("FUSION_SPACEMOUSE_CAMERA_BASE",argv[3]);
    SetEnvironmentVariableA("FUSION_SPACEMOUSE_CAMERA_SESSION",argv[2]);
    HMODULE sdk=LoadLibraryA("siappdll.dll");assert(sdk);
    auto init=(SpwRetVal(*)())GetProcAddress(sdk,"SiInitialize");
    auto term=(void(*)())GetProcAddress(sdk,"SiTerminate");
    assert(init&&term&&init()==SPW_NO_ERROR);
    HMODULE module=nullptr;double* normalizer=nullptr;int seen=0;bool tampered=false,conflict=false;
    const ULONGLONG deadline=GetTickCount64()+45000;
    bool stopped=false;
    while(GetTickCount64()<deadline) {
        int sequence=0;std::string command;std::ifstream input("probe-command");input>>sequence>>command;
        if(sequence>seen) {
            if(command=="load") {
                module=LoadLibraryExA(argv[1],nullptr,DONT_RESOLVE_DLL_REFERENCES);assert(module);
                assert(GetModuleHandleW(L"NuBase10.dll")==module);
                normalizer=reinterpret_cast<double*>(reinterpret_cast<unsigned char*>(module)+0x21755b0);
                assert(*normalizer==1024.);
            } else if(command=="tamper"||command=="restore-code") {
                assert(module);auto code=reinterpret_cast<unsigned char*>(module)+0x8e4fe0;
                DWORD previous=0,ignored=0;assert(VirtualProtect(code,1,PAGE_EXECUTE_READWRITE,&previous));
                *code^=1;assert(VirtualProtect(code,1,previous,&ignored));tampered=!tampered;
            } else if(command=="conflict") {
                assert(normalizer);*normalizer=512.;conflict=true;
            } else if(command=="stop") {stopped=true;break;}
            else assert(false);
            seen=sequence;
        }
        DWORD pid=0;GetWindowThreadProcessId(GetForegroundWindow(),&pid);
        FILE* state=fopen("probe-state.json","w");assert(state);
        fprintf(state,"{\"sequence\":%d,\"normalizer\":%.17g,\"background\":%s}",seen,
                normalizer?*normalizer:0.,pid!=GetCurrentProcessId()?"true":"false");fclose(state);
        Sleep(30);
    }
    assert(stopped&&!tampered);
    term();
    assert(normalizer&&*normalizer==(conflict?512.:1024.));
    *normalizer=1024.;FreeLibrary(module);FreeLibrary(sdk);
    puts("PASS inert Fusion PE through real DLL/TCP: late module, background live updates, session basis, unknown build and outside-write refusal, teardown");
}
