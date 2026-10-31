/*
 * libVkLayer_fusion_present_sync
 *
 * Vulkan Layer for Autodesk Fusion 360 under Wine/DXVK.
 * Synchronizes presentation on the main 3D canvas to ensure child window Blt
 * copies in Wine do not display stale (N-1) frames during snapping/sketching,
 * while safely ignoring small floating HUDs/FIFO swapchains to prevent deadlocks.
 *
 * Wine copies the canvas (a WS_CHILD window) to its parent right after
 * vkQueuePresentKHR returns, but Mesa's X11 WSI hands the frame to Xwayland
 * from a background thread. vkQueueWaitIdle only covers the GPU, so the copy
 * could win the race and show the previous frame. DXVK 3.x attaches a present
 * fence (VK_KHR_swapchain_maintenance1) to every present; the layer waits on it,
 * which returns once the WSI has handed the frame over. Without a present fence
 * it falls back to vkQueueWaitIdle alone.
 *
 * Compilation:
 *   gcc -shared -fPIC -O2 -o libVkLayer_fusion_present_sync.so libVkLayer_fusion_present_sync.c
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <unistd.h>

#define FUSION_PRESENT_SYNC_VERSION "1.0.0"

typedef int VkResult;
typedef void* VkQueue;
typedef void* VkDevice;
typedef void* VkInstance;
typedef void* VkPhysicalDevice;
typedef void (*PFN_vkVoidFunction)(void);

#define VK_SUCCESS 0
#define VK_TIMEOUT 2
#define VK_STRUCTURE_TYPE_LOADER_INSTANCE_CREATE_INFO 47
#define VK_STRUCTURE_TYPE_LOADER_DEVICE_CREATE_INFO 48
#define VK_PRESENT_MODE_IMMEDIATE_KHR 0
#define VK_STRUCTURE_TYPE_SWAPCHAIN_PRESENT_FENCE_INFO_KHR 1000275001

typedef enum VkLayerFunction_ {
    VK_LAYER_LINK_INFO = 0,
    VK_LOADER_DATA_CALLBACK = 1,
    VK_LOADER_LAYER_CREATE_DEVICE_CALLBACK = 2,
    VK_LOADER_FEATURES = 3,
} VkLayerFunction;

typedef struct {
    uint32_t width;
    uint32_t height;
} VkExtent2D;

typedef struct VkSwapchainCreateInfoKHR_ {
    int sType;
    const void* pNext;
    uint32_t flags;
    void *surface;
    uint32_t minImageCount;
    int imageFormat;
    int imageColorSpace;
    VkExtent2D imageExtent;
    uint32_t imageArrayLayers;
    uint32_t imageUsage;
    int imageSharingMode;
    uint32_t queueFamilyIndexCount;
    const uint32_t* pQueueFamilyIndices;
    int preTransform;
    int compositeAlpha;
    int presentMode;
    int clipped;
    void *oldSwapchain;
} VkSwapchainCreateInfoKHR;

typedef struct VkPresentInfoKHR_ {
    int sType;
    const void *pNext;
    uint32_t waitSemaphoreCount;
    const void *pWaitSemaphores;
    uint32_t swapchainCount;
    const void **pSwapchains;
    const uint32_t *pImageIndices;
    int *pResults;
} VkPresentInfoKHR;

typedef struct VkBaseInStructure_ {
    int sType;
    const struct VkBaseInStructure_ *pNext;
} VkBaseInStructure;

typedef uint64_t VkFence;

typedef struct VkSwapchainPresentFenceInfoKHR_ {
    int sType;
    const void *pNext;
    uint32_t swapchainCount;
    const VkFence *pFences;
} VkSwapchainPresentFenceInfoKHR;

typedef PFN_vkVoidFunction (*PFN_vkGetInstanceProcAddr)(VkInstance instance, const char *pName);
typedef PFN_vkVoidFunction (*PFN_vkGetDeviceProcAddr)(VkDevice device, const char *pName);
typedef PFN_vkVoidFunction (*PFN_GetPhysicalDeviceProcAddr)(VkInstance instance, const char *pName);

typedef VkResult (*PFN_vkCreateInstance)(const void *pCreateInfo, const void *pAllocator, VkInstance *pInstance);
typedef VkResult (*PFN_vkCreateDevice)(VkPhysicalDevice physicalDevice, const void *pCreateInfo, const void *pAllocator, VkDevice *pDevice);
typedef VkResult (*PFN_vkQueuePresentKHR)(VkQueue queue, const VkPresentInfoKHR *pPresentInfo);
typedef VkResult (*PFN_vkQueueWaitIdle)(VkQueue queue);
typedef VkResult (*PFN_vkCreateSwapchainKHR)(VkDevice device, const VkSwapchainCreateInfoKHR *pCreateInfo, const void *pAllocator, void **pSwapchain);
typedef void (*PFN_vkDestroySwapchainKHR)(VkDevice device, void *swapchain, const void *pAllocator);
typedef VkResult (*PFN_vkWaitForFences)(VkDevice device, uint32_t fenceCount, const VkFence *pFences, uint32_t waitAll, uint64_t timeout);

typedef struct VkLayerInstanceLink_ {
    struct VkLayerInstanceLink_ *pNext;
    PFN_vkGetInstanceProcAddr pfnNextGetInstanceProcAddr;
    PFN_vkGetDeviceProcAddr pfnNextGetDeviceProcAddr;
} VkLayerInstanceLink;

typedef struct VkLayerInstanceCreateInfo_ {
    int sType;
    const void *pNext;
    VkLayerFunction function;
    union {
        VkLayerInstanceLink *pLayerInfo;
        void *dummy[4];
    } u;
} VkLayerInstanceCreateInfo;

typedef struct VkLayerDeviceLink_ {
    struct VkLayerDeviceLink_ *pNext;
    PFN_vkGetInstanceProcAddr pfnNextGetInstanceProcAddr;
    PFN_vkGetDeviceProcAddr pfnNextGetDeviceProcAddr;
} VkLayerDeviceLink;

typedef struct VkLayerDeviceCreateInfo_ {
    int sType;
    const void *pNext;
    VkLayerFunction function;
    union {
        VkLayerDeviceLink *pLayerInfo;
        void *dummy[2];
    } u;
} VkLayerDeviceCreateInfo;

typedef struct VkNegotiateLayerInterface_ {
    int sType;
    void *pNext;
    uint32_t loaderLayerInterfaceVersion;
    PFN_vkGetInstanceProcAddr pfnGetInstanceProcAddr;
    PFN_vkGetDeviceProcAddr pfnGetDeviceProcAddr;
    PFN_GetPhysicalDeviceProcAddr pfnGetPhysicalDeviceProcAddr;
} VkNegotiateLayerInterface;

// Globals
static PFN_vkGetInstanceProcAddr g_next_gipa = NULL;
static PFN_vkGetDeviceProcAddr g_next_gdpa = NULL;
static PFN_vkQueuePresentKHR g_real_vkQueuePresentKHR = NULL;
static PFN_vkQueueWaitIdle g_real_vkQueueWaitIdle = NULL;
static PFN_vkCreateSwapchainKHR g_real_vkCreateSwapchainKHR = NULL;
static PFN_vkDestroySwapchainKHR g_real_vkDestroySwapchainKHR = NULL;
static PFN_vkWaitForFences g_real_vkWaitForFences = NULL;

#define MAX_CANVAS_SWAPCHAINS 16
static void *g_canvas_swapchains[MAX_CANVAS_SWAPCHAINS] = {0};
static VkDevice g_canvas_devices[MAX_CANVAS_SWAPCHAINS] = {0};
static volatile int g_canvas_lock = 0;

// After this many consecutive timeouts (fence never signalled) only every
// FENCE_WAIT_PROBE_EVERY-th present waits again.
#define FENCE_WAIT_BACKOFF_AFTER 3
#define FENCE_WAIT_PROBE_EVERY 32

static unsigned long long g_present_count = 0;
static int g_debug = 0;
static int g_sync_enabled = 1;
static int g_wait_fence = 1;
static uint64_t g_wait_timeout_ns = 25000000ull;
static unsigned g_wait_timeouts = 0;
static int g_env_inited = 0;

static void canvas_lock(void) {
    while (__sync_lock_test_and_set(&g_canvas_lock, 1)) {
    }
}

static void canvas_unlock(void) {
    __sync_lock_release(&g_canvas_lock);
}

static void init_env(void) {
    if (g_env_inited) return;
    g_env_inited = 1;

    const char *dbg = getenv("FUSION_SYNC_DEBUG");
    if (dbg && atoi(dbg) > 0) g_debug = 1;

    const char *dis = getenv("FUSION_SYNC_DISABLE");
    if (dis && atoi(dis) > 0) g_sync_enabled = 0;

    const char *fence = getenv("FUSION_SYNC_WAIT_FENCE");
    if (fence && atoi(fence) == 0) g_wait_fence = 0;

    const char *wait_ms = getenv("FUSION_SYNC_WAIT_MS");
    if (wait_ms && atoi(wait_ms) > 0) g_wait_timeout_ns = (uint64_t)atoi(wait_ms) * 1000000ull;

    if (g_debug) {
        fprintf(stderr, "[fusion-sync-layer] Initialized in pid %d: sync_enabled=%d wait_fence=%d timeout=%llums\n",
                getpid(), g_sync_enabled, g_wait_fence, (unsigned long long)(g_wait_timeout_ns / 1000000ull));
    }
}

static void track_canvas_swapchain(void *sc, VkDevice device) {
    int slot = 0;
    canvas_lock();
    for (int i = 0; i < MAX_CANVAS_SWAPCHAINS; i++) {
        if (g_canvas_swapchains[i] == NULL || g_canvas_swapchains[i] == sc) {
            slot = i;
            break;
        }
    }
    g_canvas_devices[slot] = device;
    g_canvas_swapchains[slot] = sc;
    canvas_unlock();
}

static void untrack_canvas_swapchain(void *sc) {
    canvas_lock();
    for (int i = 0; i < MAX_CANVAS_SWAPCHAINS; i++) {
        if (g_canvas_swapchains[i] == sc) {
            g_canvas_swapchains[i] = NULL;
        }
    }
    canvas_unlock();
}

struct canvas_present {
    VkDevice device;
    VkFence fence;  // 0: this present carries no present fence
};

static int find_canvas_present(const VkPresentInfoKHR *pPresentInfo, struct canvas_present *out) {
    memset(out, 0, sizeof(*out));
    if (!pPresentInfo || !pPresentInfo->pSwapchains || pPresentInfo->swapchainCount == 0) {
        return 0;
    }

    const VkSwapchainPresentFenceInfoKHR *fences = NULL;
    for (const VkBaseInStructure *b = (const VkBaseInStructure *)pPresentInfo->pNext; b; b = b->pNext) {
        if (b->sType == VK_STRUCTURE_TYPE_SWAPCHAIN_PRESENT_FENCE_INFO_KHR) {
            fences = (const VkSwapchainPresentFenceInfoKHR *)b;
            break;
        }
    }

    int found = 0;
    canvas_lock();
    for (uint32_t i = 0; i < pPresentInfo->swapchainCount && !found; i++) {
        void *sc = (void *)pPresentInfo->pSwapchains[i];
        for (int j = 0; j < MAX_CANVAS_SWAPCHAINS; j++) {
            if (g_canvas_swapchains[j] && g_canvas_swapchains[j] == sc) {
                out->device = g_canvas_devices[j];
                if (fences && fences->pFences && i < fences->swapchainCount) {
                    out->fence = fences->pFences[i];
                }
                found = 1;
                break;
            }
        }
    }
    canvas_unlock();
    return found;
}

// Block until the WSI has handed the frame we just presented to the display
// server, so Wine's follow-up child window copy cannot pick up the previous one.
// (vkWaitForPresent2KHR would also work, but the display server only completes
// copy presents on a ~17 ms timer, which would cap Fusion at ~58 fps.)
// Bounded: a fence that is never signalled must not stall Fusion.
// Returns the vkWaitForFences result, or -1 if no wait was done.
static VkResult wait_for_present_fence(const struct canvas_present *cp) {
    if (!g_wait_fence || !g_real_vkWaitForFences || !cp->fence) {
        return -1;
    }
    if (g_wait_timeouts >= FENCE_WAIT_BACKOFF_AFTER && g_present_count % FENCE_WAIT_PROBE_EVERY != 0) {
        return -1;
    }

    VkResult res = g_real_vkWaitForFences(cp->device, 1, &cp->fence, 1, g_wait_timeout_ns);
    if (res == VK_SUCCESS) {
        g_wait_timeouts = 0;
    } else if (res == VK_TIMEOUT) {
        g_wait_timeouts++;
    }
    return res;
}

static VkResult fusion_CreateSwapchainKHR(VkDevice device, const VkSwapchainCreateInfoKHR *pCreateInfo, const void *pAllocator, void **pSwapchain) {
    init_env();
    if (!g_real_vkCreateSwapchainKHR) return VK_SUCCESS;

    VkResult res = g_real_vkCreateSwapchainKHR(device, pCreateInfo, pAllocator, pSwapchain);
    if (res == VK_SUCCESS && pSwapchain && *pSwapchain && pCreateInfo) {
        uint32_t w = pCreateInfo->imageExtent.width;
        uint32_t h = pCreateInfo->imageExtent.height;
        int mode = pCreateInfo->presentMode;

        // ONLY synchronize the main 3D canvas (large viewport > 500x500 in IMMEDIATE mode)
        // NEVER synchronize tiny floating tool windows, dimension HUDs (150x45), or FIFO swapchains
        if (w >= 500 && h >= 500 && mode == VK_PRESENT_MODE_IMMEDIATE_KHR) {
            track_canvas_swapchain(*pSwapchain, device);
            if (g_debug) {
                fprintf(stderr, "[fusion-sync-layer] Tracking 3D canvas swapchain %p (%ux%u, mode=%d)\n",
                        *pSwapchain, w, h, mode);
            }
        } else {
            if (g_debug) {
                fprintf(stderr, "[fusion-sync-layer] Ignoring secondary swapchain %p (%ux%u, mode=%d)\n",
                        *pSwapchain, w, h, mode);
            }
        }
    }
    return res;
}

static void fusion_DestroySwapchainKHR(VkDevice device, void *swapchain, const void *pAllocator) {
    untrack_canvas_swapchain(swapchain);
    if (g_real_vkDestroySwapchainKHR) {
        g_real_vkDestroySwapchainKHR(device, swapchain, pAllocator);
    }
}

static VkResult fusion_vkQueuePresentKHR(VkQueue queue, const VkPresentInfoKHR *pPresentInfo) {
    init_env();
    VkResult res = VK_SUCCESS;
    if (g_real_vkQueuePresentKHR) {
        res = g_real_vkQueuePresentKHR(queue, pPresentInfo);
    }

    // Only synchronize if this present is for the main 3D canvas!
    struct canvas_present canvas;
    if (g_sync_enabled && g_real_vkQueueWaitIdle && queue && find_canvas_present(pPresentInfo, &canvas)) {
        g_real_vkQueueWaitIdle(queue);
        g_present_count++;
        VkResult wait_res = res >= VK_SUCCESS ? wait_for_present_fence(&canvas) : -1;
        if (g_debug && (g_present_count <= 5 || g_present_count % 300 == 0 || wait_res == VK_TIMEOUT)) {
            fprintf(stderr, "[fusion-sync-layer] Canvas frame #%llu synchronized (res=%d, fence_wait=%d)\n",
                    g_present_count, res, wait_res);
        }
    }

    return res;
}

static PFN_vkVoidFunction fusion_GetDeviceProcAddr(VkDevice device, const char *pName);

static VkResult fusion_CreateDevice(VkPhysicalDevice physicalDevice, const void *pCreateInfo, const void *pAllocator, VkDevice *pDevice) {
    init_env();
    struct BaseStruct {
        int sType;
        void *pNext;
    };
    struct BaseStruct *curr = (struct BaseStruct *)pCreateInfo;
    PFN_vkGetInstanceProcAddr next_gipa = NULL;
    PFN_vkGetDeviceProcAddr next_gdpa = NULL;

    while (curr && curr->pNext) {
        struct BaseStruct *next = (struct BaseStruct *)curr->pNext;
        if (next->sType == VK_STRUCTURE_TYPE_LOADER_DEVICE_CREATE_INFO) {
            VkLayerDeviceCreateInfo *dev_info = (VkLayerDeviceCreateInfo *)next;
            if (dev_info->function == VK_LAYER_LINK_INFO) {
                next_gipa = dev_info->u.pLayerInfo->pfnNextGetInstanceProcAddr;
                next_gdpa = dev_info->u.pLayerInfo->pfnNextGetDeviceProcAddr;
                dev_info->u.pLayerInfo = dev_info->u.pLayerInfo->pNext;
                break;
            }
        }
        curr = next;
    }

    if (!next_gipa && g_next_gipa) next_gipa = g_next_gipa;
    if (!next_gdpa && g_next_gdpa) next_gdpa = g_next_gdpa;

    PFN_vkCreateDevice next_create_device = (PFN_vkCreateDevice)next_gipa(NULL, "vkCreateDevice");
    VkResult res = next_create_device(physicalDevice, pCreateInfo, pAllocator, pDevice);
    if (res == VK_SUCCESS && pDevice && *pDevice && next_gdpa) {
        g_next_gdpa = next_gdpa;
        g_real_vkQueuePresentKHR = (PFN_vkQueuePresentKHR)next_gdpa(*pDevice, "vkQueuePresentKHR");
        g_real_vkQueueWaitIdle = (PFN_vkQueueWaitIdle)next_gdpa(*pDevice, "vkQueueWaitIdle");
        g_real_vkCreateSwapchainKHR = (PFN_vkCreateSwapchainKHR)next_gdpa(*pDevice, "vkCreateSwapchainKHR");
        g_real_vkDestroySwapchainKHR = (PFN_vkDestroySwapchainKHR)next_gdpa(*pDevice, "vkDestroySwapchainKHR");
        g_real_vkWaitForFences = (PFN_vkWaitForFences)next_gdpa(*pDevice, "vkWaitForFences");
        if (g_debug) {
            fprintf(stderr, "[fusion-sync-layer] Device created! QueuePresent=%p WaitIdle=%p CreateSwapchain=%p WaitForFences=%p\n",
                    g_real_vkQueuePresentKHR, g_real_vkQueueWaitIdle, g_real_vkCreateSwapchainKHR,
                    g_real_vkWaitForFences);
        }
    }
    return res;
}

static PFN_vkVoidFunction fusion_GetDeviceProcAddr(VkDevice device, const char *pName) {
    if (!pName) return NULL;
    if (strcmp(pName, "vkGetDeviceProcAddr") == 0) return (PFN_vkVoidFunction)fusion_GetDeviceProcAddr;
    if (strcmp(pName, "vkQueuePresentKHR") == 0) return (PFN_vkVoidFunction)fusion_vkQueuePresentKHR;
    if (strcmp(pName, "vkCreateSwapchainKHR") == 0) return (PFN_vkVoidFunction)fusion_CreateSwapchainKHR;
    if (strcmp(pName, "vkDestroySwapchainKHR") == 0) return (PFN_vkVoidFunction)fusion_DestroySwapchainKHR;

    if (g_next_gdpa) return g_next_gdpa(device, pName);
    return NULL;
}

static VkResult fusion_CreateInstance(const void *pCreateInfo, const void *pAllocator, VkInstance *pInstance) {
    init_env();
    struct BaseStruct {
        int sType;
        void *pNext;
    };
    struct BaseStruct *curr = (struct BaseStruct *)pCreateInfo;
    PFN_vkGetInstanceProcAddr next_gipa = NULL;

    while (curr && curr->pNext) {
        struct BaseStruct *next = (struct BaseStruct *)curr->pNext;
        if (next->sType == VK_STRUCTURE_TYPE_LOADER_INSTANCE_CREATE_INFO) {
            VkLayerInstanceCreateInfo *inst_info = (VkLayerInstanceCreateInfo *)next;
            if (inst_info->function == VK_LAYER_LINK_INFO) {
                next_gipa = inst_info->u.pLayerInfo->pfnNextGetInstanceProcAddr;
                inst_info->u.pLayerInfo = inst_info->u.pLayerInfo->pNext;
                break;
            }
        }
        curr = next;
    }

    if (!next_gipa && g_next_gipa) next_gipa = g_next_gipa;
    g_next_gipa = next_gipa;

    PFN_vkCreateInstance next_create_instance = (PFN_vkCreateInstance)next_gipa(NULL, "vkCreateInstance");
    return next_create_instance(pCreateInfo, pAllocator, pInstance);
}

static PFN_vkVoidFunction fusion_GetInstanceProcAddr(VkInstance instance, const char *pName) {
    if (!pName) return NULL;
    if (strcmp(pName, "vkGetInstanceProcAddr") == 0) return (PFN_vkVoidFunction)fusion_GetInstanceProcAddr;
    if (strcmp(pName, "vkGetDeviceProcAddr") == 0) return (PFN_vkVoidFunction)fusion_GetDeviceProcAddr;
    if (strcmp(pName, "vkCreateInstance") == 0) return (PFN_vkVoidFunction)fusion_CreateInstance;
    if (strcmp(pName, "vkCreateDevice") == 0) return (PFN_vkVoidFunction)fusion_CreateDevice;
    if (strcmp(pName, "vkQueuePresentKHR") == 0) return (PFN_vkVoidFunction)fusion_vkQueuePresentKHR;
    if (strcmp(pName, "vkCreateSwapchainKHR") == 0) return (PFN_vkVoidFunction)fusion_CreateSwapchainKHR;
    if (strcmp(pName, "vkDestroySwapchainKHR") == 0) return (PFN_vkVoidFunction)fusion_DestroySwapchainKHR;

    if (g_next_gipa) return g_next_gipa(instance, pName);
    return NULL;
}

static PFN_vkVoidFunction fusion_GetPhysicalDeviceProcAddr(VkInstance instance, const char *pName) {
    if (!pName) return NULL;
    if (g_next_gipa) return g_next_gipa(instance, pName);
    return NULL;
}

__attribute__((visibility("default")))
VkResult vkNegotiateLoaderLayerInterfaceVersion(VkNegotiateLayerInterface *pVersionStruct) {
    init_env();
    if (pVersionStruct->loaderLayerInterfaceVersion >= 2) {
        pVersionStruct->loaderLayerInterfaceVersion = 2;
    }
    pVersionStruct->pfnGetInstanceProcAddr = fusion_GetInstanceProcAddr;
    pVersionStruct->pfnGetDeviceProcAddr = fusion_GetDeviceProcAddr;
    pVersionStruct->pfnGetPhysicalDeviceProcAddr = fusion_GetPhysicalDeviceProcAddr;
    return VK_SUCCESS;
}
