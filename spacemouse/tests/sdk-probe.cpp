#include <windows.h>
#include <stdio.h>
#include "siappdll.h"

int main()
{
    char directory[MAX_PATH];
    GetModuleFileNameA(NULL, directory, MAX_PATH);
    *strrchr(directory, '\\') = 0;
    char filename[MAX_PATH];
    snprintf(filename, sizeof(filename), "%s\\sdk-probe.log", directory);
    freopen(filename, "w", stdout);
    setbuf(stdout, NULL);
    HMODULE dll = LoadLibraryA("siappdll.dll");
    if (!dll) { printf("LOAD_FAILED %lu\n", GetLastError()); return 1; }
    auto init = (SpwRetVal (*)())GetProcAddress(dll, "SiInitialize");
    auto term = (void (*)())GetProcAddress(dll, "SiTerminate");
    auto open = (SiHdl *(*)(const char *, int, SiTypeMask *, int, SiOpenData *))GetProcAddress(dll, "SiOpen");
    auto close = (SpwRetVal (*)(SiHdl *))GetProcAddress(dll, "SiClose");
    auto get = (SpwRetVal (*)(SiHdl *, int, const SiGetEventData *, SiSpwEvent *))GetProcAddress(dll, "SiGetEvent");
    auto peek = (SpwRetVal (*)(SiHdl *, int, const SiGetEventData *, SiSpwEvent *))GetProcAddress(dll, "SiPeekEvent");
    if (!init || !term || !open || !close || !get || !peek) return 2;
    for (unsigned cycle = 0; cycle < 2; ++cycle) {
        if (init() != SPW_NO_ERROR || init() != SPW_NO_ERROR) return 3;
        HWND hwnd = CreateWindowExA(0, "STATIC", "Fusion SpaceMouse diagnostic", WS_OVERLAPPEDWINDOW | WS_VISIBLE,
                                   100, 100, 450, 130, NULL, NULL, GetModuleHandleA(NULL), NULL);
        SetForegroundWindow(hwnd);
        SiOpenData data = {}; data.win = hwnd;
        SiHdl *handle = open("Fusion SpaceMouse diagnostic", 0, NULL, 0, &data);
        if (!handle) return 4;
        printf("READY %u\n", cycle);
        snprintf(filename, sizeof(filename), "%s\\ready-%u", directory, cycle);
        FILE *ready = fopen(filename, "w");
        if (ready) { fputs("ready", ready); fclose(ready); }
        unsigned motions = 0, zero = 0, presses = 0, releases = 0, axes = 0;
        bool bad = false;
        const long values[] = {11, -22, 33, -44, 55, -66};
        ULONGLONG until = GetTickCount64() + 2500;
        MSG msg;
        while (GetTickCount64() < until) {
            for (unsigned batch = 0; batch < 100 && PeekMessageA(&msg, NULL, 0, 0, PM_REMOVE); ++batch) {
                SiGetEventData ed = {msg.message, (unsigned int)msg.wParam, (long)msg.lParam};
                SiSpwEvent preview = {}, event = {};
                SpwRetVal pr = peek(handle, 0, &ed, &preview);
                SpwRetVal result = get(handle, 0, &ed, &event);
                if (pr != result || (result == SI_IS_EVENT && preview.type != event.type)) bad = true;
                if (result == SI_IS_EVENT) {
                    if (event.type == SI_MOTION_EVENT) {
                        ++motions;
                        for (int i = 0; i < 6; ++i) {
                            if (event.u.spw_data.motion[i] == values[i]) axes |= 1u << i;
                            else bad = true;
                        }
                        if (event.u.spw_data.period != 17) bad = true;
                    }
                    if (event.type == SI_ZERO_EVENT) ++zero;
                    if (event.type == SI_BUTTON_EVENT) {
                        if (event.u.spw_data.button.pressed) ++presses;
                        if (event.u.spw_data.button.release) ++releases;
                    }
                }
                TranslateMessage(&msg); DispatchMessageA(&msg);
            }
            Sleep(2);
        }
        close(handle);
        term();
        term();
        DestroyWindow(hwnd);
        printf("RESULT %u motions=%u zeros=%u presses=%u releases=%u axes=%u bad=%u\n",
               cycle, motions, zero, presses, releases, axes, bad);
        if (!motions || !zero || presses != 2 || releases != 2 || axes != 63 || bad) return 5;
    }
    FreeLibrary(dll);
    return 0;
}
