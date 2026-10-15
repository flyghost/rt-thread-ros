/*
 * ramdump_port.h — OS abstraction layer
 *
 * All ramdump source files use standard C types (<stdint.h>, <stdbool.h>)
 * and standard library functions directly.  This header provides ONLY the
 * OS-specific wrappers that differ between RTOS / bare-metal targets.
 *
 * Usage:
 *   // Files needing OS services:
 *   #include "ramdump_port.h"
 *   #include "port/rtthread/ramdump_port_rtthread.h"   // RT-Thread macros
 *
 *   // Files only needing standard C:
 *   #include <stdint.h>
 *   #include <stdbool.h>
 *   #include <string.h>
 */

#ifndef RAMDUMP_PORT_H__
#define RAMDUMP_PORT_H__

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ---- DWT cycle counter (Cortex-M3/4/7) ---- */
#define RD_DWT_CYCCNT  (*(volatile uint32_t *)0xE0001004U)

/** Set a deadline in ms from now.  Returns DWT cycle count at expiry. */
static inline uint32_t ramdump_deadline_ms(uint32_t ms)
{
    extern uint32_t SystemCoreClock;
    return RD_DWT_CYCCNT + SystemCoreClock / 1000 * ms;
}

/** Check if a deadline has expired (handles DWT wraparound). */
static inline bool ramdump_deadline_expired(uint32_t deadline)
{
    return (int32_t)(RD_DWT_CYCCNT - deadline) > 0;
}

/* ---- Return codes ---- */
#define RAMDUMP_EOK   0
#define RAMDUMP_ERR  (-1)

/* ---- OS abstraction (implemented in port/<os>/) ---- */

/** Get system tick count (may return 0 if scheduler unavailable) */
uint32_t ramdump_tick_get(void);

/** Busy-wait delay in milliseconds (safe in exception context) */
void     ramdump_delay_ms(uint32_t ms);

/** Init debug UART (polling, safe in exception context). */
void     ramdump_dbg_init(void);

/** Output one char to debug UART. */
void     ramdump_dbg_putc(char c);

/** Debug printf — for status/log messages, NOT dump data.
 *  Uses polling UART, safe in exception context. */
void     ramdump_dbg_printf(const char *fmt, ...);

/** Reboot the system */
void     ramdump_reboot(void);

/** Opaque thread handle; NULL when scheduler unavailable */
typedef void *ramdump_thread_t;
#define RAMDUMP_THREAD_NULL  ((ramdump_thread_t)0)

/** Max thread name length (matches RT_NAME_MAX) */
#define RAMDUMP_THREAD_NAME_MAX  8

/** Get thread stack pointer (returns 0 if unavailable) */
uint32_t    ramdump_thread_sp(ramdump_thread_t thread);

/** Get thread name (returns "unknown" if unavailable) */
const char *ramdump_thread_name(ramdump_thread_t thread);

/** Get thread object list head address (0 if unavailable, for Trace32) */
uint32_t ramdump_thread_list_head(void);

/** Register the ramdump assert hook with the OS */
void ramdump_assert_hook_register(void (*hook)(const char *, const char *, uint32_t));

/** Get the currently running thread handle (RAMDUMP_THREAD_NULL if unavailable) */
ramdump_thread_t ramdump_thread_self(void);

/**
 * Fault hook signature — invoked from the OS exception handler with a pointer
 * to the hardware-stacked exception frame.  Return 0 to swallow the fault,
 * non-zero to let the OS run its own handling afterwards.
 */
typedef int (*ramdump_fault_hook_t)(void *context);

/**
 * Install the fault hook through the OS-provided hook API.
 * Keeps the CPU/core exception handler files untouched (zero-intrusion).
 * No-op if the OS exposes no such hook.
 */
void ramdump_fault_hook_install(ramdump_fault_hook_t hook);

#ifdef __cplusplus
}
#endif

#endif /* RAMDUMP_PORT_H__ */
