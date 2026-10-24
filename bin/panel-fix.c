/* Fusion's owned tool panels need managed X11 windows under Wine.
 * Use the WS_EX_APPWINDOW workaround documented by stonegray/fusion360-linux.
 * No application data or graphics settings are changed.
 * Build with Clang and the MinGW headers/import libraries; no C runtime needed.
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <tlhelp32.h>

static DWORD fusion_pid;
static BOOL inspect_only;
static HANDLE output;
static const WCHAR applied_property[] = L"AutodeskFusionPanelFixOriginalStyle";

static BOOL starts_with(const WCHAR *text, const WCHAR *prefix)
{
    while (*prefix) {
        if (*text++ != *prefix++) return FALSE;
    }
    return TRUE;
}

static void log_line(const char *line)
{
    DWORD written;
    WriteFile(output, line, (DWORD)lstrlenA(line), &written, NULL);
}

static DWORD find_fusion(void)
{
    PROCESSENTRY32W entry;
    HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    DWORD result = 0;
    if (snapshot == INVALID_HANDLE_VALUE) return 0;
    entry.dwSize = sizeof(entry);
    if (Process32FirstW(snapshot, &entry)) {
        do {
            if (lstrcmpiW(entry.szExeFile, L"Fusion360.exe") == 0) {
                result = entry.th32ProcessID;
                break;
            }
        } while (Process32NextW(snapshot, &entry));
    }
    CloseHandle(snapshot);
    return result;
}

static BOOL is_qt_tool(HWND window)
{
    char name[128];
    const char suffix[] = "QWindowToolSaveBits";
    int length;
    if (!GetClassNameA(window,name,sizeof(name))) return FALSE;
    length = lstrlenA(name);
    return name[0]=='Q' && name[1]=='t' && length >= (int)sizeof(suffix)-1 &&
        lstrcmpA(name+length-(sizeof(suffix)-1),suffix)==0;
}

/* The model browser and sketch palette are tall Qt tool panels.
 * Small input boxes, constraints and cursor previews also use WS_TOOLWINDOW;
 * they must keep Wine's unmanaged popup behavior so they move with the cursor.
 */
static BOOL is_vertical_panel(HWND window, HWND owner, const RECT *rect)
{
    RECT parent;
    LONG width=rect->right-rect->left, height=rect->bottom-rect->top;
    UINT dpi=GetDpiForWindow(owner);
    if (!dpi) dpi=96;
    if (!is_qt_tool(window) || !GetWindowRect(owner,&parent)) return FALSE;
    return width >= MulDiv(180,dpi,96) && height >= MulDiv(200,dpi,96) &&
        height > width && width < (parent.right-parent.left)/2;
}

struct companion_search { HWND owner; RECT rect; BOOL found; };
static BOOL CALLBACK find_companion(HWND window,LPARAM data)
{
    struct companion_search *search=(struct companion_search *)data;
    DWORD pid; RECT rect;
    GetWindowThreadProcessId(window,&pid);
    if (pid!=fusion_pid || GetWindow(window,GW_OWNER)!=search->owner ||
        !IsWindowVisible(window) || !GetWindowRect(window,&rect)) return TRUE;
    if (is_vertical_panel(window,search->owner,&rect) &&
        rect.left >= search->rect.left-2 && rect.left <= search->rect.left+2 &&
        rect.right >= search->rect.right-2 && rect.right <= search->rect.right+2) {
        search->found=TRUE;
        return FALSE;
    }
    return TRUE;
}

static BOOL is_persistent_panel(HWND window,HWND owner,const RECT *rect)
{
    struct companion_search search;
    UINT dpi=GetDpiForWindow(owner);
    LONG height=rect->bottom-rect->top;
    if (is_vertical_panel(window,owner,rect)) return TRUE;
    if (!dpi) dpi=96;
    if (!is_qt_tool(window) || height>MulDiv(40,dpi,96) || height<=1) return FALSE;
    /* The narrow comment bar has the same horizontal extent as the browser. */
    search.owner=owner; search.rect=*rect; search.found=FALSE;
    EnumWindows(find_companion,(LPARAM)&search);
    return search.found;
}

static BOOL CALLBACK visit_window(HWND window, LPARAM unused)
{
    DWORD pid;
    LONG_PTR style, extended;
    HWND owner;
    RECT position;
    char message[512], class_name[256];
    GetWindowThreadProcessId(window, &pid);
    if (pid != fusion_pid || (!inspect_only && !IsWindowVisible(window))) return TRUE;
    style = GetWindowLongPtrW(window, GWL_STYLE);
    extended = GetWindowLongPtrW(window, GWL_EXSTYLE);
    owner = GetWindow(window, GW_OWNER);
    if (!(style & WS_POPUP) || !owner) return TRUE;
    GetWindowRect(window, &position);
    if (inspect_only) {
        GetClassNameA(window,class_name,sizeof(class_name));
        wsprintfA(message, "panel hwnd=%p owner=%p style=%08lx ex=%08lx size=%ldx%ld visible=%d persistent=%d class=%s\r\n",
                  window, owner, (DWORD)style, (DWORD)extended,
                  position.right-position.left, position.bottom-position.top,
                  IsWindowVisible(window),is_persistent_panel(window,owner,&position),class_name);
        log_line(message);
        return TRUE;
    }
    if (extended & WS_EX_APPWINDOW) return TRUE;
    if (!(extended & WS_EX_TOOLWINDOW)) {
        if (style & (WS_CAPTION | WS_DLGFRAME | WS_SYSMENU)) return TRUE;
        if (extended & WS_EX_DLGMODALFRAME) return TRUE;
    }
    if (position.right-position.left <= 1 || position.bottom-position.top <= 1)
        return TRUE;
    if (!is_persistent_panel(window,owner,&position)) return TRUE;
    SetLastError(0);
    if (!SetWindowLongPtrW(window, GWL_EXSTYLE, extended | WS_EX_APPWINDOW) && GetLastError()) {
        wsprintfA(message, "style change failed: hwnd=%p error=%lu\r\n", window, GetLastError());
        log_line(message);
        return TRUE;
    }
    SetWindowPos(window, NULL, position.left, position.top,
                 position.right-position.left, position.bottom-position.top,
                 SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED);
    SetPropW(window,applied_property,(HANDLE)(UINT_PTR)(extended+1));
    wsprintfA(message, "managed panel hwnd=%p owner=%p size=%ldx%ld\r\n",
              window, owner, position.right-position.left, position.bottom-position.top);
    log_line(message);
    return TRUE;
}

void WINAPI WinMainCRTStartup(void)
{
    HANDLE mutex = NULL, process;
    BOOL once = FALSE;
    unsigned retries = 0;
    const WCHAR *command = GetCommandLineW();
    /* Windows command lines here contain a fixed helper path plus one option. */
    for (; *command; command++) {
        if (starts_with(command, L"--inspect")) inspect_only = once = TRUE;
        if (starts_with(command, L"--once")) once = TRUE;
    }
    output = GetStdHandle(STD_OUTPUT_HANDLE);
    SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
    if (!once) {
        mutex = CreateMutexW(NULL, TRUE, L"Local\\AutodeskFusionPanelFix");
        if (!mutex || GetLastError() == ERROR_ALREADY_EXISTS) ExitProcess(0);
    }
    while (!(fusion_pid = find_fusion()) && !once && retries++ < 60) Sleep(2000);
    if (!fusion_pid) ExitProcess(0);
    process = OpenProcess(SYNCHRONIZE, FALSE, fusion_pid);
    if (!process) ExitProcess(1);
    log_line("Fusion panel helper started\r\n");
    do {
        EnumWindows(visit_window, 0);
    } while (!once && WaitForSingleObject(process, 2000) == WAIT_TIMEOUT);
    log_line("Fusion panel helper stopped\r\n");
    CloseHandle(process);
    if (mutex) CloseHandle(mutex);
    ExitProcess(0);
}
