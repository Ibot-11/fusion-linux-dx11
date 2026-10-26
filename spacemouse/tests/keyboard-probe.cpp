#include <windows.h>
#include <stdio.h>
#include <string.h>
#include "siappdll.h"

static unsigned down[256] = {}, up[256] = {};
static LRESULT CALLBACK window_proc(HWND w, UINT m, WPARAM k, LPARAM l) {
    if (m == WM_KEYDOWN && k < 256) ++down[k];
    if (m == WM_KEYUP && k < 256) ++up[k];
    return DefWindowProcA(w, m, k, l);
}
static void pump(unsigned ms) {
    ULONGLONG until = GetTickCount64() + ms;
    while (GetTickCount64() < until) {
        MSG msg;
        while (PeekMessageA(&msg, NULL, 0, 0, PM_REMOVE)) {
            TranslateMessage(&msg); DispatchMessageA(&msg);
        }
        Sleep(2);
    }
}
static void mark(const char *name) {
    FILE *f = fopen(name, "w");
    if (f) { fputs("ready", f); fclose(f); }
}
int main(int argc, char **argv) {
    char executable[MAX_PATH], directory[MAX_PATH];
    GetModuleFileNameA(NULL, executable, MAX_PATH);
    strcpy(directory, executable); *strrchr(directory, '\\') = 0;
    SetCurrentDirectoryA(directory);
    bool child = argc > 1 && strcmp(argv[1], "--child") == 0;
    if (!child) freopen("keyboard-probe.log", "w", stdout); setbuf(stdout, NULL);
    HMODULE dll = child ? NULL : LoadLibraryA("siappdll.dll");
    if (!child && !dll) return 1;
    auto init = (SpwRetVal (*)())(child ? NULL : GetProcAddress(dll, "SiInitialize"));
    auto term = (void (*)())(child ? NULL : GetProcAddress(dll, "SiTerminate"));
    auto open = (SiHdl *(*)(const char *, int, SiTypeMask *, int, SiOpenData *))(child ? NULL : GetProcAddress(dll, "SiOpen"));
    auto close = (SpwRetVal (*)(SiHdl *))(child ? NULL : GetProcAddress(dll, "SiClose"));
    if (!child && (!init || !term || !open || !close || init() != SPW_NO_ERROR)) return 2;
    WNDCLASSA wc = {};
    wc.lpfnWndProc = window_proc; wc.hInstance = GetModuleHandleA(NULL);
    wc.lpszClassName = "FusionKeyboardProbe";
    RegisterClassA(&wc);
    HWND hwnd = CreateWindowA(wc.lpszClassName, child ? "Other process" : "Fusion keyboard test",
                              WS_OVERLAPPEDWINDOW | WS_VISIBLE, 50, 50, 400, 200,
                              NULL, NULL, wc.hInstance, NULL);
    SetForegroundWindow(hwnd); SetFocus(hwnd); pump(200);
    if (child) {
        mark("child-ready");
        for (int i = 0; i < 40 && GetFileAttributesA("child-stop") == INVALID_FILE_ATTRIBUTES; ++i)
            pump(50);
        FILE *f = fopen("child-result", "w");
        if (f) { fprintf(f, "%u\n", down['I']); fclose(f); }
        return down['I'] ? 20 : 0;
    }
    SiOpenData data = {}; data.win = hwnd;
    SiHdl *handle = open("Input test", 0, NULL, 0, &data);
    if (!handle) return 3;
    SetForegroundWindow(hwnd); SetActiveWindow(hwnd); SetFocus(hwnd); pump(100);
    DWORD foreground = 0;
    GetWindowThreadProcessId(GetForegroundWindow(), &foreground);
    char title[256] = {};
    GetWindowTextA(GetForegroundWindow(), title, sizeof(title));
    printf("foreground title=%s\n", title);
    printf("focus foreground=%lu self=%lu hwnd=%p foreground_hwnd=%p\n", foreground, GetCurrentProcessId(), hwnd, GetForegroundWindow());
    mark("phase-keys"); pump(800);
    printf("keys I=%u/%u A=%u\n", down['I'], up['I'], down['A']);
    if (down['I'] != 1 || up['I'] != 1 || down['A']) return 4;

    mark("phase-restart"); pump(1900);
    printf("restart ESC=%u/%u HOME=%u/%u\n", down[VK_ESCAPE], up[VK_ESCAPE], down[VK_HOME], up[VK_HOME]);
    if (down[VK_ESCAPE] != 1 || up[VK_ESCAPE] != 1 || down[VK_HOME] != 1 || up[VK_HOME] != 1) return 5;

    mark("phase-focus"); pump(350);
    if (down['F'] != 1 || up['F']) return 6;
    char command[2 * MAX_PATH]; snprintf(command, sizeof(command), "\"%s\" --child", executable);
    STARTUPINFOA startup = {}; startup.cb = sizeof(startup);
    PROCESS_INFORMATION process = {};
    if (!CreateProcessA(NULL, command, NULL, NULL, FALSE, 0, NULL, NULL, &startup, &process)) return 7;
    pump(800);
    if (GetForegroundWindow() == hwnd || (GetAsyncKeyState('F') & 0x8000)) return 8;
    mark("child-stop");
    WaitForSingleObject(process.hProcess, 1500);
    DWORD code = 99; GetExitCodeProcess(process.hProcess, &code);
    CloseHandle(process.hThread); CloseHandle(process.hProcess);
    if (code != 0) return 9;

    SetForegroundWindow(hwnd); SetFocus(hwnd); pump(150);
    mark("phase-final"); pump(900);
    printf("focus F=%u/%u I=%u/%u\n", down['F'], up['F'], down['I'], up['I']);
    if (down['F'] != 2 || up['F'] != 1 || down['I'] != 1 || (GetAsyncKeyState('F') & 0x8000)) return 10;
    close(handle); term();
    ULONGLONG before = GetTickCount64();
    if (init() != SPW_NO_ERROR) return 11; // Driver may be absent at startup.
    pump(100); term(); term();
    if (GetTickCount64() - before > 1200) return 12;
    printf("PASS keyboard, focus loss, reconnect, partial packet and absent driver teardown\n");
    DestroyWindow(hwnd); FreeLibrary(dll);
    return 0;
}
