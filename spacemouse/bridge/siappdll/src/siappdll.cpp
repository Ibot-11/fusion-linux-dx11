/*
SpaceNavigatorEmulator - 3dconnexion-compatible siappdll.dll replacement
Copyright (C) 2014  John Tsiombikas <nuclear@member.fsf.org>
Copyright (C) 2015  Luke Nuttall <lukenuttall@gmail.com>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
*/
#include "config.h"
#include <stdio.h>
#include <malloc.h>
#include "sock.h"
#include <windows.h>
#include "siappdll.h"
#include "siappdll_impl.h"
#include <iostream>
#include <fstream>
#include <string>
#include <deque>
#include "log.h"
#include "camera_scale.h"

#include "MinHook.h"


extern "C" {
	typedef UINT(__stdcall* GETRAWINPUTDEVICEINFOW)(HANDLE, UINT, LPVOID, PUINT);

	GETRAWINPUTDEVICEINFOW fpOldGetRawInput = NULL;

	typedef UINT(WINAPI* GetDeviceList)(PRAWINPUTDEVICELIST pRawInputDeviceList, PUINT puiNumDevices, UINT cbSize);

	GetDeviceList fpOldGetDeviceList = NULL;
}

static thread_local bool hookNext = false;
static bool hooks_ready = false;
UINT WINAPI DetourGetRawInputDeviceList(PRAWINPUTDEVICELIST pRawInputDeviceList, PUINT puiNumDevices, UINT cbSize)
{
	if (hookNext)
	{
		LOG(TRACE) << "Faking GetRawInputDeviceList";
		hookNext = false;
		return 1;
	}
	else
	{
		return fpOldGetDeviceList(pRawInputDeviceList, puiNumDevices, cbSize);
	}
}

UINT WINAPI DetourGetRawInputDeviceInfoW(HANDLE hDevice, UINT uiCommand, LPVOID pData, PUINT pcbSize)
{
	if (hookNext)
	{
		LOG(TRACE) << "Faking GetRawInputDeviceInfoW";
		hookNext = false;
		return 1;
	}
	else
	{
		return fpOldGetRawInput(hDevice, uiCommand, pData, pcbSize);
	}
}

int startHook()
{
	// Initialize MinHook.
	if (MH_Initialize() != MH_OK)
	{
		return 1;
	}

	// Create a hook in disabled state.
	if (MH_CreateHook(reinterpret_cast<LPVOID>(&GetRawInputDeviceInfoW), reinterpret_cast<LPVOID>(&DetourGetRawInputDeviceInfoW),
		reinterpret_cast<LPVOID*>(&fpOldGetRawInput)) != MH_OK)
	{
		return 1;
	}
	if (MH_CreateHook(reinterpret_cast<LPVOID>(&GetRawInputDeviceList), reinterpret_cast<LPVOID>(&DetourGetRawInputDeviceList),
		reinterpret_cast<LPVOID*>(&fpOldGetDeviceList)) != MH_OK)
	{
		return 1;
	}

	// Enable the hook
	if (MH_EnableHook(reinterpret_cast<LPVOID>(&GetRawInputDeviceInfoW)) != MH_OK)
	{
		LOG(ERROR) << "Could not hook GetRawInputDeviceInfoW";
		return 1;
	}

	// Enable the hook 
	if (MH_EnableHook(reinterpret_cast<LPVOID>(&GetRawInputDeviceList)) != MH_OK)
	{
		LOG(ERROR) << "Could not hook GetRawInputDeviceList";
		return 1;
	}
	return -1;
}

struct motion_t {
    long data[7];
    int type = SI_MOTION_EVENT;
};

std::deque <motion_t> m_queue;

HWND tgt_wndw;

HANDLE ghMutex = NULL;
HANDLE  hRcvThread = NULL;
SOCKET sock_fd = INVALID_SOCKET;


void clear_context(void)
{
    restore_camera_scale();
    sock_shutdown(sock_fd);
    if (hRcvThread) {
        // shutdown releases recv; never kill a thread while it owns the queue.
        WaitForSingleObject(hRcvThread, INFINITE);
        CloseHandle(hRcvThread);
        hRcvThread = NULL;
    }
    sock_close(sock_fd);
    sock_fd = INVALID_SOCKET;
    m_queue.clear();
    tgt_wndw = NULL;
    if (ghMutex) { CloseHandle(ghMutex); ghMutex = NULL; }
    if (hooks_ready) { MH_Uninitialize(); hooks_ready = false; }
    hookNext = false;
    initialised = false;
}

void collectMotionEvent(motion_t m)
{
    DWORD foreground_pid = 0;
    GetWindowThreadProcessId(GetForegroundWindow(), &foreground_pid);
    WaitForSingleObject(ghMutex, INFINITE);
    if (foreground_pid != GetCurrentProcessId() || !IsWindow(tgt_wndw)) {
        m_queue.clear();
        ReleaseMutex(ghMutex);
        return;
    }
    // Bound queued input if Fusion temporarily stops processing messages.
    if (m_queue.size() >= 256) m_queue.pop_front();
    m_queue.push_back(m);
    if (!PostMessage(tgt_wndw, space_ware_message, m.type, 1))
        m_queue.pop_back();
    ReleaseMutex(ghMutex);
}

DWORD WINAPI RcvThreadFunction(LPVOID lpParam)
{
    SOCKET fd = *(SOCKET *)lpParam;
    unsigned long button_state = 0;
    while (true) {
        int buf[8];
        if (sock_read(fd, (char *)buf, sizeof(buf)) != sizeof(buf)) break;
        motion_t m = {};
        if (buf[0] == 0) {
            bool moving = false;
            for (int i = 0; i < 7; ++i) {
                m.data[i] = buf[i + 1];
                if (i < 6 && buf[i + 1]) moving = true;
            }
            m.type = moving ? SI_MOTION_EVENT : SI_ZERO_EVENT;
            collectMotionEvent(m);
        } else if ((buf[0] == 1 || buf[0] == 2) && buf[1] >= 0 && buf[1] < 2) {
            m.type = SI_BUTTON_EVENT;
            unsigned long bit = 1UL << (buf[1] + 1);
            m.data[0] = button_state;
            if (buf[0] == 1) button_state |= bit;
            else button_state &= ~bit;
            m.data[1] = button_state;
            m.data[2] = buf[0] == 1 ? bit : 0;
            m.data[3] = buf[0] == 2 ? bit : 0;
            collectMotionEvent(m);
        }
    }
    return 0;
}

BOOL APIENTRY DllMain(HMODULE, DWORD, LPVOID)
{
    // Hook setup and all thread/socket work run outside the loader lock.
    return TRUE;
}

enum SpwRetVal SPWAPI SiInitialize(void)
{
	if (initialised) return SPW_NO_ERROR;
    if (startHook() != -1) { MH_Uninitialize(); return SPW_ERROR; }
    hooks_ready = true;

	LOG(TRACE) << "Stub called: " << __FUNCTION__;

	sock_fd = sock_connect(SPNAV_HOST, SPNAV_PORT);
	if (sock_fd == INVALID_SOCKET)
	{
		LOG(ERROR) << "connection to daemon failed";
		goto err;
	}

	if (!(space_ware_message = RegisterWindowMessage("SpaceWareMessage00")))
	{
		LOG(ERROR) << "failed to register window message";
		goto err;
	}

	ghMutex = CreateMutex(
		NULL,              // default security attributes
		FALSE,             // initially not owned
		NULL);             // unnamed mutex

	if (ghMutex == NULL)
	{
		LOG(ERROR) << "CreateMutex error " << GetLastError();
		goto err;
	}

	hRcvThread = CreateThread(
		NULL,                   // default security attributes
		0,                      // use default stack size  
		RcvThreadFunction,      // thread function name
		&sock_fd,               // argument to thread function 
		0,                      // use default creation flags 
		NULL);             // returns the thread identifier 

	if (!hRcvThread)
	{
		LOG(ERROR) << "failed to create thread";
		goto err;
	}

	initialised = true;
	apply_camera_scale();

	return SPW_NO_ERROR;

err:
	clear_context();

	return SPW_ERROR;
}

SPWbool SiIsInitialized()
{
	LOG(TRACE) << "Stub called: " << __FUNCTION__;
	return initialised;
}

void SPWAPI SiTerminate(void)
{
	LOG(TRACE) << "Stub called: " << __FUNCTION__;

	clear_context();

	initialised = false;
}

void SPWAPI SiGetLibraryInfo(SiVerInfo *info)
{
	LOG(TRACE) << "Stub called: " << __FUNCTION__;
	info->major = VER_MAJOR;
	info->minor = VER_MINOR;
	info->build = VER_BUILD;
	strcpy(info->version, VER_STR);
	info->data[0] = 0;
}

enum SpwRetVal SPWAPI SiGetDriverInfo(SiVerInfo *info)
{
	LOG(TRACE) << "Stub called: " << __FUNCTION__;
	info->major = VER_MAJOR;
	info->minor = VER_MINOR;
	info->build = VER_BUILD;
	strcpy(info->version, VER_STR);
	info->data[0] = 0;

	return SPW_NO_ERROR;
}

enum SpwRetVal SPWAPI SiGetDevicePort(int devid, SiDevPort *port)
{
	LOG(TRACE) << "Stub called: " << __FUNCTION__;
	port->devID = 0;
	port->devClass = 
	port->devType = SI_SPACENAVIGATOR;
	strcpy(port->devName, "SpaceNavigatorEmulator");
	strcpy(port->portName, "Pretend Port");
	return SPW_NO_ERROR;
}

int SPWAPI SiGetNumDevices(void)
{
	LOG(TRACE) << "Stub called: " << __FUNCTION__;
	return 1;
}

int SPWAPI SiDeviceIndex(int idx)
{
	LOG(TRACE) << "Stub called: " << __FUNCTION__;
	return 0;
}

void SPWAPI SiOpenWinInit(SiOpenData *opendata, void *win)
{
	LOG(TRACE) << "Stub called: " << __FUNCTION__;
	opendata->win = win;
}

struct SiHdl *SPWAPI SiOpen(const char *appname, int devid, SiTypeMask *tmask, int mode, SiOpenData *opendata)
{
	LOG(TRACE) << "SiOpen called for app: " << appname;
	if (!initialised || !opendata || !IsWindow((HWND)opendata->win)) {
        SpwErrorVal = SPW_ERROR;
        return nullptr;
    }
    struct SiHdl *si = new SiHdl();

	if (!si)
	{
		SpwErrorVal = SPW_ERROR;
		return 0;
	}

	si->opendata = *opendata;
	si->opendata.lib_flag = 1;
	si->opendata.trans_ctl = nullptr;
	// FIXME - get an actual process id.
	si->opendata.pid = GetCurrentProcessId();

	WaitForSingleObject(ghMutex, INFINITE);
    m_queue.clear();
    tgt_wndw = (HWND)opendata->win;
    ReleaseMutex(ghMutex);

	SpwErrorVal = SPW_NO_ERROR;
	return si;
}

struct SiHdl* SPWAPI SiOpenPort(const char *pAppName, const SiDevPort *pPort, int mode, const SiOpenData *pData)
{
	LOG(TRACE) << __FUNCTION__ << " passing to SiOpen";
	// FIXME - copy data instead on const cast
	return SiOpen(pAppName, 0, nullptr, mode, const_cast<SiOpenData*>(pData));
}

enum SpwRetVal SPWAPI SiClose(struct SiHdl *si)
{
	LOG(TRACE) << "Stub called: " << __FUNCTION__;

    if (si && ghMutex) {
        WaitForSingleObject(ghMutex, INFINITE);
        if (tgt_wndw == (HWND)si->opendata.win) {
            tgt_wndw = NULL;
            m_queue.clear();
        }
        ReleaseMutex(ghMutex);
    }
    delete si;
	return SPW_NO_ERROR;
}

int SPWAPI SiGetDeviceID(struct SiHdl *si)
{
	LOG(TRACE) << "Stub called: " << __FUNCTION__;
	SpwErrorVal = SPW_NO_ERROR;
	return 0;	/* TODO */
}

enum SpwRetVal SPWAPI SiGetDeviceImageFileName(struct SiHdl *si, char *name, unsigned long *maxlen)
{
	LOG(TRACE) << "Stub called: " << __FUNCTION__;
	name[0] = 0;
	*maxlen = 0;
	return SPW_NO_ERROR;	/* TODO */
}

SpwRetVal SPWAPI SiGetDeviceInfo(struct SiHdl *si, SiDevInfo *info)
{
	LOG(TRACE) << "Stub called: " << __FUNCTION__;
	if (!info) return SI_BAD_VALUE;
    memset(info, 0, sizeof(*info));
    info->dev_type = SI_SPACENAVIGATOR;
	info->num_buttons = 2;
	info->num_degrees = 6;
	info->can_beep = 0;
	return SPW_NO_ERROR;
}

enum SpwRetVal SPWAPI SiGetDeviceName(struct SiHdl *si, SiDeviceName *name)
{
	LOG(TRACE) << "Stub called: " << __FUNCTION__;
	strcpy(name->name, "SpaceNavigatorEmulator");
	return SPW_NO_ERROR;
}


enum SpwRetVal SPWAPI SiGrabDevice(struct SiHdl *si, SPWbool exclusive)
{
	LOG(TRACE) << "Stub called: " << __FUNCTION__;
	return SPW_NO_ERROR;
}

enum SpwRetVal SPWAPI SiReleaseDevice(struct SiHdl *si)
{
	LOG(TRACE) << "Stub called: " << __FUNCTION__;
	return SPW_NO_ERROR;
}

enum SpwRetVal SPWAPI SiRezero(struct SiHdl *si)
{
	LOG(TRACE) << "Stub called: " << __FUNCTION__;
	return SPW_NO_ERROR;
}

enum SpwRetVal SPWAPI SiBeep(struct SiHdl *si, char *str)
{
	LOG(TRACE) << "Stub called: " << __FUNCTION__;
	return SPW_NO_ERROR;
}

enum SpwRetVal SPWAPI SiSetLEDs(struct SiHdl *si, unsigned long mask)
{
	LOG(TRACE) << "Stub called: " << __FUNCTION__;
	return SPW_NO_ERROR;
}

enum SpwRetVal SPWAPI SiSetUiMode(struct SiHdl *si, unsigned long mode)
{
	LOG(TRACE) << "Stub called: " << __FUNCTION__;
	return SPW_NO_ERROR;
}

#define CALL_CB(cb, od, evdata, ev)	cb.func(od, evdata, ev, cb.cls)

int SPWAPI SiDispatch(struct SiHdl *si, SiGetEventData *data, SiSpwEvent *ev, SiSpwHandlers *handlers)
{
	LOG(TRACE) << "Stub called: " << __FUNCTION__ << " - event: " << ev->type;

	if (handlers != nullptr && si && ev && data)
	{
		switch (ev->type) {
		case SI_BUTTON_EVENT:
			if (handlers->button.func) return CALL_CB(handlers->button, &si->opendata, data, ev);
            break;
		case SI_MOTION_EVENT:
			if (handlers->motion.func != nullptr)
				return CALL_CB(handlers->motion, &si->opendata, data, ev);
			break;
		case SI_COMBO_EVENT:
			if (handlers->combo.func) return CALL_CB(handlers->combo, &si->opendata, data, ev);
            break;
		case SI_ZERO_EVENT:
			if (handlers->zero.func) return CALL_CB(handlers->zero, &si->opendata, data, ev);
            break;
		default:
			break;
		}
	}
	return 0;
}

void SPWAPI SiGetEventWinInit(SiGetEventData *evdata, unsigned int msg, unsigned int wparam, long lparam)
{
	LOG(TRACE) << "Stub called: " << __FUNCTION__;
	if (evdata == nullptr)
	{
		LOG(ERROR) << __FUNCTION__ << " called with null pointer for event storage";
        return;
	}
	evdata->msg = msg;
	evdata->lparam = lparam;
	evdata->wparam = wparam;
}

static SpwRetVal read_event(struct SiHdl *si, int flags, const SiGetEventData *data, SiSpwEvent *ev, bool consume)
{
	LOG(TRACE) << "called: " << __FUNCTION__;
	
	// If we weren't given a valid pointer, we return bad value.
	if (!ev || !si || !data || !ghMutex)
		return SI_BAD_VALUE;
	DWORD foreground_pid = 0;
	GetWindowThreadProcessId(GetForegroundWindow(), &foreground_pid);
	if (foreground_pid != GetCurrentProcessId()) {
		WaitForSingleObject(ghMutex, INFINITE);
		m_queue.clear();
		ReleaseMutex(ghMutex);
		return SI_NOT_EVENT;
	}

    if (data->msg == space_ware_message)
    {
        long buf[7];
        WaitForSingleObject(ghMutex, INFINITE);
        if (m_queue.empty()) {
            ReleaseMutex(ghMutex);
            return SI_NOT_EVENT;
        }
        motion_t m = m_queue.front();
        if (consume) m_queue.pop_front();
        memcpy(buf, m.data, sizeof(buf));
        auto size = m_queue.size();
        ReleaseMutex(ghMutex);
        memset(ev, 0, sizeof(*ev));

		LOG(TRACE) << "Queue size: " << size;

		// completely fake an event
		if (m.type == SI_MOTION_EVENT || m.type == SI_ZERO_EVENT)
		{
			ev->type = m.type;
			ev->u.spw_data.button.last = 0;
			ev->u.spw_data.button.current = 0;
			ev->u.spw_data.button.release = 0;
			ev->u.spw_data.button.pressed = 0;

			ev->u.spw_data.motion[0] = buf[0];
			ev->u.spw_data.motion[1] = buf[1];
			ev->u.spw_data.motion[2] = buf[2];
			ev->u.spw_data.motion[3] = buf[3];
			ev->u.spw_data.motion[4] = buf[4];
			ev->u.spw_data.motion[5] = buf[5];

			ev->u.spw_data.period = buf[6];


			if (consume && m.type == SI_MOTION_EVENT)
                hookNext = true;
		}
		else if (m.type == SI_BUTTON_EVENT)
		{
			ev->type = m.type;
			ev->u.spw_data.button.last = buf[0];
			ev->u.spw_data.button.current = buf[1];
			ev->u.spw_data.button.pressed = buf[2];
			ev->u.spw_data.button.release = buf[3];
			ev->u.spw_data.motion[0] = 0;
			ev->u.spw_data.motion[1] = 0;
			ev->u.spw_data.motion[2] = 0;
			ev->u.spw_data.motion[3] = 0;
			ev->u.spw_data.motion[4] = 0;
			ev->u.spw_data.motion[5] = 0;
			ev->u.spw_data.period = 0;
		}
		else if (data->wparam == SI_BUTTON_PRESS_EVENT || data->wparam == SI_BUTTON_RELEASE_EVENT)
		{
			ev->type = data->wparam;
			ev->u.hwButtonEvent.buttonNumber = data->lparam;
		}

		return SI_IS_EVENT;
	}
	else
	{
		return SI_NOT_EVENT;
	}
}

SpwRetVal SPWAPI SiGetEvent(struct SiHdl *si, int flags, const SiGetEventData *data, SiSpwEvent *ev)
{
    return read_event(si, flags, data, ev, true);
}

SpwRetVal SPWAPI SiPeekEvent(struct SiHdl *si, int flags, const SiGetEventData *data, SiSpwEvent *ev)
{
    return read_event(si, flags, data, ev, false);
}

SPWbool SPWAPI SiIsSpaceWareEvent(const SiGetEventData *data, struct SiHdl *si)
{
	LOG(TRACE) << "Stub called: " << __FUNCTION__;
	return data && data->msg == space_ware_message;
}

int SPWAPI SiButtonPressed(SiSpwEvent *ev)
{
	LOG(TRACE) << "Stub called: " << __FUNCTION__;

	long pressed = ev->u.spw_data.button.pressed;

	for (unsigned int i = 0; i < 32; i++)
	{
		if ((1UL << i) & pressed)
		{
			return i;
		}
	}
	return 0;
}

int SPWAPI SiButtonReleased(SiSpwEvent *ev)
{
	LOG(TRACE) << "Stub called: " << __FUNCTION__;

	long released = ev->u.spw_data.button.release;

	for (unsigned int i = 0; i < 32; i++)
	{
		if ((1UL << i) & released)
		{
			return i;
		}
	}
	return 0;
}

enum SpwRetVal SPWAPI SiGetButtonName(struct SiHdl *si, unsigned long bnum, SiButtonName *name)
{
	LOG(TRACE) << "Stub called: " << __FUNCTION__;
	if (!name) return SI_BAD_VALUE;
    strcpy(name->name, bnum == 1 ? "Left button" : "Right button");
	return SPW_NO_ERROR;
}

void *SPWAPI SiGetCompanyIcon(void)
{
	LOG(TRACE) << "Stub called: " << __FUNCTION__;

	return NULL;
}

enum SpwRetVal SPWAPI SiGetCompanyLogoFileName(char *name, unsigned long *maxlen)
{
	LOG(TRACE) << "Stub called: " << __FUNCTION__;

	return SPW_ERROR;
}


static const char *errnames[] = {
	"no error",
	"error -- function failed",
	"invalid 3DxWare handle",
	"invalid device ID",
	"invalid argument value",
	"event is a 3DxWare event",
	"skip this 3DxWare event",
	"event is not a 3DxWare event",
	"3DxWare driver is not running",
	"3DxWare driver is not responding",
	"the function is unsupported by this version",
	"3DxWare Input Library is uninitialized",
	"incorrect driver for this 3DxWare version",
	"internal 3DxWare error"
};

const char *SPWAPI SpwErrorString(enum SpwRetVal err)
{
	LOG(TRACE) << "Stub called: " << __FUNCTION__;
	return (unsigned int)err < sizeof(errnames) / sizeof(errnames[0]) ? errnames[(int)err] : "unknown error";
}

/* deprecated */
enum SpwRetVal SiSetTypeMask(SiTypeMask *mask, int type1, ...)
{
	LOG(TRACE) << "Stub called: " << __FUNCTION__;
	return SPW_NO_ERROR;
}

