/*
 * ramdump_usb_osal.h — Minimal OSAL replacing cherryusb usb_osal.h
 *
 * Only provides what ramdump_usb actually needs:
 *   - msleep   →  busy-wait via DWT cycle counter (works with IRQs disabled)
 *
 * Thread/sem/mutex/mq/timer are NOT needed (no EP0 thread, no DMA).
 *
 * CRITICAL: Ramdump runs with global interrupts DISABLED in all exception
 * paths.  usb_osal_leave_critical_section() is intentionally a NO-OP —
 * interrupts must NEVER be re-enabled during ramdump operation.
 */

#ifndef RAMDUMP_USB_OSAL_H
#define RAMDUMP_USB_OSAL_H

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ---- DWT cycle counter (direct register access, no CMSIS dependency) ---- */

#define RAMDUMP_USB_DEMCR     (*(volatile uint32_t *)0xE000EDFCU)
#define RAMDUMP_USB_DEMCR_TRCENA  (1U << 24)

#define RAMDUMP_USB_DWT_CTRL   (*(volatile uint32_t *)0xE0001000U)
#define RAMDUMP_USB_DWT_CYCCNT (*(volatile uint32_t *)0xE0001004U)
#define RAMDUMP_USB_DWT_CTRL_CYCCNTENA (1U << 0)

extern uint32_t SystemCoreClock;

static inline void ramdump_usb_dwt_init(void)
{
    RAMDUMP_USB_DEMCR |= RAMDUMP_USB_DEMCR_TRCENA;
    RAMDUMP_USB_DWT_CYCCNT = 0;
    RAMDUMP_USB_DWT_CTRL |= RAMDUMP_USB_DWT_CTRL_CYCCNTENA;
}

/* ---- Busy-wait delay (works with IRQs disabled) ---- */
static inline void ramdump_usb_udelay(uint32_t us)
{
    uint32_t start = RAMDUMP_USB_DWT_CYCCNT;
    uint32_t target = us * (SystemCoreClock / 1000000U);
    while ((RAMDUMP_USB_DWT_CYCCNT - start) < target) {
        /* spin */
    }
}

static inline void usb_osal_msleep(uint32_t ms)
{
    for (uint32_t i = 0; i < ms; i++) {
        ramdump_usb_udelay(1000);
    }
}

/* ----
 * Critical section — NO-OP by design
 *
 * Ramdump enters with global IRQs disabled (rt_enter_critical or HardFault).
 * These must NEVER re-enable IRQs.  They exist only for API compatibility
 * with cherryusb — no code in ramdump_usb actually calls them.
 * ---- */
static inline size_t usb_osal_enter_critical_section(void)
{
    return 0;  /* IRQs already disabled, nothing to do */
}

static inline void usb_osal_leave_critical_section(size_t level)
{
    (void)level;
    /* INTENTIONALLY NO-OP: never re-enable interrupts in ramdump context */
}

/* ---- stubs for link compatibility ---- */
#define USB_OSAL_WAITING_FOREVER (0xFFFFFFFFU)

#ifdef __cplusplus
}
#endif

#endif /* RAMDUMP_USB_OSAL_H */
