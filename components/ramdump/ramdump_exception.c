#include <string.h>
#include <stdio.h>
/*
 * Copyright (c) 2006-2024, RT-Thread Development Team
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * ramdump_exception.c -- Exception context save, validate, and display
 *
 * The g_ramdump_exception structure is placed in the .noinit section to
 * survive a system reset, enabling post-mortem analysis.
 */

#include "ramdump_port.h"
#include "ramdump_exception.h"
#include "ramdump_cli.h"

/* Exception record placed in .noinit section.
 * This memory is NOT zeroed at startup, preserving crash info across resets. */
#if defined(__CC_ARM) || defined(__CLANG_ARM)
    __attribute__((section(".noinit")))
#elif defined(__GNUC__)
    __attribute__((section(".noinit")))
#endif
ramdump_exception_t g_ramdump_exception;

/* Set by ramdump_assert_hook before triggering a UsageFault via UDF.
 * The HardFault handler checks this to override fault_type to ASSERT. */
int g_ramdump_assert_pending = 0;

/*
 * rt_object_container is static in RT-Thread (src/object.c), invisible
 * to Trace32.  Save the thread-list head address here at init time so
 * Trace32 scripts can enumerate threads from the dump.
 */
uint32_t g_ramdump_thread_list_head = 0;

/* SCB register addresses for Cortex-M4 */
#define SCB_CFSR    (*(volatile const unsigned *)0xE000ED28)
#define SCB_HFSR    (*(volatile const unsigned *)0xE000ED2C)
#define SCB_MMFAR   (*(volatile const unsigned *)0xE000ED34)
#define SCB_BFAR    (*(volatile const unsigned *)0xE000ED38)

/**
 * Save exception context.
 * Uses a magic value check to prevent overwriting the first fault
 * on double-fault (nested exception during handler execution).
 */
void ramdump_exception_save(uint32_t  fault_type,
                            uint32_t  hw_frame_ptr,
                            ramdump_thread_t  current_thread)
{
    uint32_t *p;
    uint32_t sum;
    int i;

    /* Prevent overwrite on double-fault: keep the original (root cause) exception */
    if (g_ramdump_exception.magic == 0x52414D44)
    {
        return;
    }

    g_ramdump_exception.magic      = 0x52414D44;
    g_ramdump_exception.fault_type = fault_type;
    g_ramdump_exception.cfsr       = SCB_CFSR;
    g_ramdump_exception.hfsr       = SCB_HFSR;
    g_ramdump_exception.mmfar      = SCB_MMFAR;
    g_ramdump_exception.bfar       = SCB_BFAR;
    g_ramdump_exception.fpscr      = 0;
    g_ramdump_exception.hw_frame_ptr = hw_frame_ptr;
    g_ramdump_exception.tick       = ramdump_tick_get();

    if (current_thread != NULL)
    {
        g_ramdump_exception.current_thread_sp = ramdump_thread_sp(current_thread);
        strncpy(g_ramdump_exception.thread_name,
                   ramdump_thread_name(current_thread),
                   RAMDUMP_THREAD_NAME_MAX - 1);
        g_ramdump_exception.thread_name[RAMDUMP_THREAD_NAME_MAX - 1] = '\0';
    }
    else
    {
        g_ramdump_exception.current_thread_sp = 0;
        memset(g_ramdump_exception.thread_name, 0, RAMDUMP_THREAD_NAME_MAX);
    }

    /* Compute XOR checksum over everything except the checksum field itself */
    sum = 0;
    p = (uint32_t *)&g_ramdump_exception;
    for (i = 0; i < (int)(sizeof(ramdump_exception_t) / 4 - 1); i++)
    {
        sum ^= p[i];
    }
    g_ramdump_exception.checksum = sum;
}

/**
 * Validate the exception record.
 */
int ramdump_exception_is_valid(void)
{
    uint32_t sum = 0;
    uint32_t *p;
    int i;

    if (g_ramdump_exception.magic != 0x52414D44)
        return 0;

    p = (uint32_t *)&g_ramdump_exception;
    for (i = 0; i < (int)(sizeof(ramdump_exception_t) / 4 - 1); i++)
    {
        sum ^= p[i];
    }

    return (sum == g_ramdump_exception.checksum) ? 1 : 0;
}

/**
 * Print exception information.
 */
void ramdump_exception_print(void)
{
    const char *fault_names[] = {
        "HardFault", "MemManage", "BusFault", "UsageFault", "Assert"
    };
    arm_hw_stack_frame_t *frame;

    if (!ramdump_exception_is_valid())
    {
        ramdump_dbg_printf("[ramdump] No valid exception record.\r\n");
        return;
    }

    ramdump_dbg_printf("\r\n===== RAMDUMP EXCEPTION RECORD =====\r\n");
    ramdump_dbg_printf("Fault Type : %s\r\n",
               fault_names[g_ramdump_exception.fault_type]);
    ramdump_dbg_printf("Thread     : %s\r\n",
               g_ramdump_exception.thread_name);
    ramdump_dbg_printf("Tick       : %lu\r\n",
               (unsigned long)g_ramdump_exception.tick);
    ramdump_dbg_printf("CFSR       : 0x%08lx\r\n",
               (unsigned long)g_ramdump_exception.cfsr);
    ramdump_dbg_printf("HFSR       : 0x%08lx\r\n",
               (unsigned long)g_ramdump_exception.hfsr);
    ramdump_dbg_printf("MMFAR      : 0x%08lx\r\n",
               (unsigned long)g_ramdump_exception.mmfar);
    ramdump_dbg_printf("BFAR       : 0x%08lx\r\n",
               (unsigned long)g_ramdump_exception.bfar);
    ramdump_dbg_printf("Frame @    : 0x%08lx\r\n",
               (unsigned long)g_ramdump_exception.hw_frame_ptr);

    frame = (arm_hw_stack_frame_t *)g_ramdump_exception.hw_frame_ptr;
    if (frame != NULL)
    {
        ramdump_dbg_printf("  r0=0x%08lx r1=0x%08lx r2=0x%08lx r3=0x%08lx\r\n",
                   (unsigned long)frame->r0, (unsigned long)frame->r1,
                   (unsigned long)frame->r2, (unsigned long)frame->r3);
        ramdump_dbg_printf("  r12=0x%08lx lr=0x%08lx pc=0x%08lx xpsr=0x%08lx\r\n",
                   (unsigned long)frame->r12, (unsigned long)frame->lr,
                   (unsigned long)frame->pc, (unsigned long)frame->xpsr);
    }

    ramdump_dbg_printf("=====================================\r\n\r\n");
}

/**
 * Clear the exception record.
 */
void ramdump_exception_clear(void)
{
    memset(&g_ramdump_exception, 0, sizeof(ramdump_exception_t));
}

/*
 * Save the thread list head for Trace32 scripts.
 * rt_object_container is static in RT-Thread, making it invisible to
 * Trace32.  We cache the list-head address here so show_thread.cmm
 * can access it.
 */
int ramdump_thread_list_init(void)
{
    g_ramdump_thread_list_head = ramdump_thread_list_head();
    return 0;
}

/*
 * ---- RT-Thread fault hook (zero-intrusion integration) ----
 *
 * RT-Thread exposes a public fault hook: include/rthw.h declares
 * rt_hw_exception_install(), and rt_hw_hard_fault_exception()
 * (libcpu/<arch>/cpuport.c) invokes the installed hook FIRST, before any of
 * its own register dumping, handing over the hardware-stacked exception
 * frame.  Registering through that API keeps the CPU port and src/ files
 * byte-identical to upstream, so they never conflict on an upgrade.
 *
 * The installed hook receives the same pointer the CPU-port integration used
 * to pass to ramdump_exception_save(): the hardware frame (r0-r3, r12, lr,
 * pc, xpsr).
 *
 * Behavioural difference vs. the old in-core integration: RT-Thread's own
 * register dump no longer runs, because ramdump_enter() never returns
 * (except via the 'reboot' command).  ramdump_cli_loop() prints its own,
 * richer crash summary instead.
 */

/* CFSR views: the fault bits live in separate byte/halfword fields */
#define SCB_CFSR_MFSR   (*(volatile const uint8_t  *)0xE000ED28)  /* MemManage fault status */
#define SCB_CFSR_BFSR   (*(volatile const uint8_t  *)0xE000ED29)  /* BusFault status */
#define SCB_CFSR_UFSR   (*(volatile const uint16_t *)0xE000ED2A)  /* UsageFault status */

static int ramdump_fault_hook(void *context)
{
    uint32_t fault_type = RAMDUMP_FAULT_HARD;

    if (g_ramdump_assert_pending)
    {
        /* Software assertion: ramdump_assert_trigger() set this flag, saved
         * file/line, then executed UDF #0 to raise a UsageFault. */
        fault_type = RAMDUMP_FAULT_ASSERT;
        g_ramdump_assert_pending = 0;
    }
    else if (SCB_HFSR & (1UL << 30))
    {
        /* FORCED: a configurable fault escalated into HardFault */
        if (SCB_CFSR_BFSR & 0xFF)
            fault_type = RAMDUMP_FAULT_BUS;
        else if (SCB_CFSR_MFSR & 0xFF)
            fault_type = RAMDUMP_FAULT_MEMMANAGE;
        else if (SCB_CFSR_UFSR & 0xFFFF)
            fault_type = RAMDUMP_FAULT_USAGE;
    }
    else
    {
        /* Direct configurable fault: board/ramdump_handlers.c forwards
         * MemManage/BusFault/UsageFault into HardFault_Handler. */
        if (SCB_CFSR_UFSR & 0xFFFF)
            fault_type = RAMDUMP_FAULT_USAGE;
        else if (SCB_CFSR_BFSR & 0xFF)
            fault_type = RAMDUMP_FAULT_BUS;
        else if (SCB_CFSR_MFSR & 0xFF)
            fault_type = RAMDUMP_FAULT_MEMMANAGE;
    }

    ramdump_exception_save(fault_type, (uint32_t)context, ramdump_thread_self());

    ramdump_enter();

    /* Unreachable unless the CLI was left via 'reboot'; returning non-zero
     * would let RT-Thread continue with its own fault handling. */
    return RAMDUMP_ERR;
}

int ramdump_exception_hook_init(void)
{
    ramdump_fault_hook_install(ramdump_fault_hook);
    return 0;
}
