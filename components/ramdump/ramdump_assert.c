/*
 * Copyright (c) 2006-2024, RT-Thread Development Team
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * ramdump_assert.c -- Standalone assertion implementation
 *
 * Follows the RISC-V pattern:
 *   RISC-V:  OS_ASSERT → osAssertHandler (save file/line) → ecall → HardFault
 *   ARM:     RAMDUMP_ASSERT → ramdump_assert_trigger (save file/line) → UDF → HardFault
 *
 * The key insight: the assertion info is saved BEFORE triggering the
 * exception.  The HardFault handler picks it up and tags the exception
 * record with fault_type = RAMDUMP_FAULT_ASSERT.
 */

#include <string.h>
#include "ramdump_assert.h"
#include "ramdump_exception.h"
/* Placed in regular .bss (not .noinit) — this is a volatile trigger flag,
 * not crash-persistent state.  The exception record in .noinit is the
 * authoritative crash-persistent store. */
ramdump_assert_info_t g_ramdump_assert_info;

/**
 * Trigger an assertion failure.
 *
 * 1. Init ramdump UART (if not already done)
 * 2. Save file + line to g_ramdump_assert_info
 * 3. Print the assertion via ramdump's polled UART
 * 4. Execute UDF #0 → UsageFault → HardFault_Handler → ramdump CLI
 *
 * This function NEVER returns.
 */
void ramdump_assert_trigger(const char *file, int line)
{
    /* Save assertion info BEFORE triggering UDF.
     * The HardFault handler reads these to tag the exception record. */
    g_ramdump_assert_pending = 1;
    g_ramdump_assert_info.file = file;
    g_ramdump_assert_info.line = line;

    /*
     * Trigger UsageFault via UDF (Undefined Instruction).
     *
     * The CPU automatically:
     *   1. Pushes hardware frame (R0-R3,R12,LR,PC,xPSR)
     *   2. Disables interrupts
     *   3. Takes UsageFault → our trampoline → HardFault_Handler
     *   4. rt_hw_hard_fault_exception prints registers via normal console
     *   5. ramdump_exception_save() stores to .noinit
     *   6. ramdump_enter() → ramdump_cli_loop() → @ramdump>
     *
     * UART takeover happens in ramdump_cli_loop (step 6), AFTER the
     * existing rt_kprintf register dump in step 4 completes normally.
     */
    __asm volatile("UDF #0");

    /* Never reached */
    while (1);
}

/**
 * Assert hook: registered as rt_assert_hook so RT_ASSERT also triggers dump.
 * Sets pending flag then executes UDF #0 to enter the HardFault path.
 */
static void ramdump_assert_hook(const char *ex, const char *func, uint32_t line)
{
    (void)ex;
    (void)func;
    (void)line;
    g_ramdump_assert_pending = 1;
    __asm volatile("UDF #0");
    while (1);
}

int ramdump_assert_hook_init(void)
{
    ramdump_assert_hook_register(ramdump_assert_hook);
    return 0;
}
