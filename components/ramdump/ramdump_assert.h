/*
 * Copyright (c) 2006-2024, RT-Thread Development Team
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * ramdump_assert.h -- Standalone assertion mechanism
 *
 * Fully independent of RT-Thread's RT_ASSERT.  On assertion failure:
 *   1. Saves file/line to a static struct (.noinit safe)
 *   2. Prints the assertion via ramdump's polled UART (no ramdump_printf)
 *   3. Executes UDF #0 → UsageFault → HardFault_Handler → ramdump
 *
 * This follows the RISC-V pattern:  OS_ASSERT → save info → ecall → handler
 * The ARM equivalent is:           RAMDUMP_ASSERT → save info → UDF → HardFault
 */

#ifndef RAMDUMP_ASSERT_H__
#define RAMDUMP_ASSERT_H__

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * Assertion info, saved before triggering the hardware exception.
 * The HardFault handler reads this to tag the exception record.
 */
typedef struct {
    const char *file;       /* source file name (__FILE__) */
    int         line;       /* line number (__LINE__)     */
} ramdump_assert_info_t;

extern ramdump_assert_info_t g_ramdump_assert_info;

/**
 * Trigger an assertion failure.  Does NOT return.
 *
 * @param file  source file name (use __FILE__)
 * @param line  line number (use __LINE__)
 */
void ramdump_assert_trigger(const char *file, int line);

/**
 * Assertion macro.
 *
 * Usage:
 *   RAMDUMP_ASSERT(ptr != NULL);
 *   RAMDUMP_ASSERT(ret == 0);
 *
 * When the expression is false, the system enters ramdump mode
 * via the full hardware exception path.
 */
#define RAMDUMP_ASSERT(EX)                                             \
    do {                                                               \
        if (!(EX)) {                                                   \
            ramdump_assert_trigger(__FILE__, __LINE__);                \
        }                                                              \
    } while (0)


#ifdef __cplusplus
}
#endif

#endif /* RAMDUMP_ASSERT_H__ */
