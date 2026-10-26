#include <windows.h>
#include <stdio.h>
#include <string.h>
#include <vector>
#include "siappdll.h"

static unsigned down[256] = {}, up[256] = {};
struct KeyEvent { unsigned vk; bool down, extended, ctrl, shift, left_alt, right_alt; };
static std::vector<KeyEvent> events;
static LRESULT CALLBACK window_proc(HWND w, UINT m, WPARAM k, LPARAM l) {
    const bool key_down = m == WM_KEYDOWN || m == WM_SYSKEYDOWN;
    const bool key_up = m == WM_KEYUP || m == WM_SYSKEYUP;
    if ((key_down || key_up) && k < 256) {
        if (key_down) ++down[k]; else ++up[k];
        events.push_back({(unsigned)k,key_down,(l & (1L<<24)) != 0,
                          (GetKeyState(VK_CONTROL)&0x8000)!=0,(GetKeyState(VK_SHIFT)&0x8000)!=0,
                          (GetKeyState(VK_LMENU)&0x8000)!=0,(GetKeyState(VK_RMENU)&0x8000)!=0});
    }
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

    // Resolve the same logical characters against an explicit German layout.
    // The parent writes packets while this message-pump thread owns focus/HKL.
    HKL layout = LoadKeyboardLayoutW(L"00000407", KLF_ACTIVATE);
    if (!layout || !ActivateKeyboardLayout(layout,0)) return 21;
    const SHORT umlaut = VkKeyScanExW(L'\x00e4', layout);
    const SHORT question = VkKeyScanExW(L'?', layout);
    const SHORT at = VkKeyScanExW(L'@', layout);
    printf("layout=%p active=%p umlaut=%04x question=%04x at=%04x\n",layout,GetKeyboardLayout(0),
           (unsigned short)umlaut,(unsigned short)question,(unsigned short)at);
    if (question == -1 || at == -1) return 22;
    events.clear();
    mark("phase-chords"); pump(2100);
    for (const auto& e : events)
        printf("chord vk=%u down=%d ext=%d ctrl=%d shift=%d lalt=%d ralt=%d\n",
               e.vk,e.down,e.extended,e.ctrl,e.shift,e.left_alt,e.right_alt);
    auto count = [&](unsigned vk,bool pressed) {
        unsigned result=0;for(const auto& e:events)if(e.vk==vk&&e.down==pressed)++result;return result;
    };
    if(count(VK_CONTROL,true)!=4 || count(VK_CONTROL,false)!=4 ||
       count('S',true)!=1 || count('S',false)!=1 || count('Z',true)!=1 || count('Z',false)!=1 ||
       count(VK_F24,true)!=1 || count(VK_F24,false)!=1 ||
       count(VK_RETURN,true)!=2 || count(VK_RETURN,false)!=2 || count('A',true)!=1) return 23;
    unsigned extended_enter=0; bool saved_ctrl=false, undo_ctrl=false, plain_a=false, shifted_question=false, altgr_at=false, umlaut_seen=umlaut==-1;
    for(const auto& e:events) {
        if(e.vk==VK_RETURN&&e.down&&e.extended)++extended_enter;
        if(e.vk=='S'&&!e.down&&e.ctrl)saved_ctrl=true;
        if(e.vk=='Z'&&!e.down&&e.ctrl)undo_ctrl=true;
        if(e.vk=='A'&&e.down&&!e.shift)plain_a=true;
        if(e.vk==(unsigned)(umlaut&255)&&e.down)umlaut_seen=true;
        if(e.vk==(unsigned)(question&255)&&e.down&&e.shift)shifted_question=true;
        if(e.vk==(unsigned)(at&255)&&e.down&&e.ctrl&&e.right_alt&&!e.left_alt)altgr_at=true;
    }
    if(extended_enter!=1||!saved_ctrl||!undo_ctrl||!plain_a||!umlaut_seen||!shifted_question||!altgr_at) return 24;
    for(int vk:{VK_CONTROL,VK_SHIFT,VK_MENU,VK_LWIN,(int)'S',(int)'Z',VK_F24,VK_RETURN})
        if(GetAsyncKeyState(vk)&0x8000)return 25;

    mark("phase-restart"); pump(1900);
    printf("restart ESC=%u/%u HOME=%u/%u\n", down[VK_ESCAPE], up[VK_ESCAPE], down[VK_HOME], up[VK_HOME]);
    if (down[VK_ESCAPE] != 1 || up[VK_ESCAPE] != 1 || down[VK_HOME] != 1 || up[VK_HOME] != 1) return 5;
    if ((GetAsyncKeyState(VK_CONTROL)&0x8000) || (GetAsyncKeyState(VK_SHIFT)&0x8000)) return 26;

    mark("phase-focus"); pump(350);
    if (down['F'] != 1 || up['F']) return 6;
    char command[2 * MAX_PATH]; snprintf(command, sizeof(command), "\"%s\" --child", executable);
    STARTUPINFOA startup = {}; startup.cb = sizeof(startup);
    PROCESS_INFORMATION process = {};
    if (!CreateProcessA(NULL, command, NULL, NULL, FALSE, 0, NULL, NULL, &startup, &process)) return 7;
    pump(800);
    if (GetForegroundWindow() == hwnd || (GetAsyncKeyState('F') & 0x8000) ||
        (GetAsyncKeyState(VK_CONTROL)&0x8000) || (GetAsyncKeyState(VK_SHIFT)&0x8000)) return 8;
    mark("child-stop");
    WaitForSingleObject(process.hProcess, 1500);
    DWORD code = 99; GetExitCodeProcess(process.hProcess, &code);
    CloseHandle(process.hThread); CloseHandle(process.hProcess);
    if (code != 0) return 9;

    SetForegroundWindow(hwnd); SetFocus(hwnd); pump(150);
    mark("phase-final"); pump(900);
    printf("focus F=%u/%u I=%u/%u\n", down['F'], up['F'], down['I'], up['I']);
    if (down['F'] != 2 || up['F'] != 1 || down['I'] != 1 || (GetAsyncKeyState('F') & 0x8000) ||
        (GetAsyncKeyState(VK_CONTROL)&0x8000) || (GetAsyncKeyState(VK_SHIFT)&0x8000)) return 10;
    mark("phase-teardown"); pump(700);
    if(down['G']!=1 || up['G'] || !(GetAsyncKeyState(VK_CONTROL)&0x8000)) return 27;
    term(); pump(100); // SDK termination releases a chord even with a live socket.
    if(up['G']!=1 || (GetAsyncKeyState('G')&0x8000) ||
       (GetAsyncKeyState(VK_CONTROL)&0x8000) || (GetAsyncKeyState(VK_SHIFT)&0x8000)) return 28;
    mark("phase-terminated"); close(handle);
    ULONGLONG before = GetTickCount64();
    if (init() != SPW_NO_ERROR) return 11; // Driver may be absent at startup.
    pump(100); term(); term();
    if (GetTickCount64() - before > 1200) return 12;
    printf("PASS legacy/custom keys, shared chords, modifier holds, keypad, German layout, focus loss, reconnect and teardown\n");
    DestroyWindow(hwnd); FreeLibrary(dll);
    return 0;
}
