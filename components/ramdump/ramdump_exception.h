/*
 * Copyright (c) 2006-2024, RT-Thread Development Team
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * ramdump_exception.h -- ARM Cortex-M exception frame definitions
 *
 * The exception record is placed in the .noinit section so that it
 * survives a system reset. This allows post-mortem analysis even if
 * the dump process itself triggers a watchdog reset.
 */

#ifndef RAMDUMP_EXCEPTION_H__
#define RAMDUMP_EXCEPTION_H__

#include "ramdump_port.h"

#ifdef __cplusplus
extern "C" {
#endif

/* ARM Cortex-M hardware-stacked frame (8 registers, 32 bytes).
 * This is automatically pushed by the CPU on exception entry. */
typedef struct __attribute__((packed)) {
    uint32_t r0;
    uint32_t r1;
    uint32_t r2;
    uint32_t r3;
    uint32_t r12;
    uint32_t lr;       /* EXC_RETURN value when entering handler */
    uint32_t pc;       /* faulting instruction address */
    uint32_t xpsr;     /* program status register */
} arm_hw_stack_frame_t;

/* Exception record stored in .noinit section.
 * This captures the complete crash context for offline analysis.
 * Fields are naturally aligned (all uint32_t except char[RAMDUMP_THREAD_NAME_MAX]
 * which falls at an aligned offset), so no packed attribute needed. */
typedef struct {
    uint32_t magic;                  /* 0x52414D44 ("RAMD") -- validity marker */
    uint32_t fault_type;             /* 0=HardFault, 1=MemManage, 2=BusFault, 3=UsageFault, 4=Assert */
    uint32_t cfsr;                   /* SCB->CFSR (Configurable Fault Status Register) */
    uint32_t hfsr;                   /* SCB->HFSR (HardFault Status Register) */
    uint32_t mmfar;                  /* SCB->MMFAR (MemManage Fault Address) */
    uint32_t bfar;                   /* SCB->BFAR (BusFault Fault Address) */
    uint32_t fpscr;                  /* FPSCR (floating-point status, reserved for FPU) */
    uint32_t hw_frame_ptr;           /* pointer to hardware-stacked exception frame */
    uint32_t current_thread_sp;      /* SP of the crashed thread */
    char        thread_name[RAMDUMP_THREAD_NAME_MAX]; /* name of the crashed thread */
    uint32_t tick;                   /* system tick at crash time */
    uint32_t checksum;               /* XOR checksum of all fields above */
} ramdump_exception_t;

/* Fault type enumeration */
enum {
    RAMDUMP_FAULT_HARD      = 0,
    RAMDUMP_FAULT_MEMMANAGE = 1,
    RAMDUMP_FAULT_BUS       = 2,
    RAMDUMP_FAULT_USAGE     = 3,
    RAMDUMP_FAULT_ASSERT    = 4,  /* software assertion */
};

/* Global exception record pointer (defined in ramdump_exception.c, .noinit section) */
extern ramdump_exception_t g_ramdump_exception;

/* Flag: set to 1 by ramdump_assert_hook before triggering UDF,
 * so the HardFault handler knows this was a software assertion. */
extern int g_ramdump_assert_pending;

/* Saved address of the RT-Thread thread object list head.
 * rt_object_container is static, so Trace32 can't find it directly.
 * This global is populated at init time for Trace32 scripts to use. */
extern uint32_t g_ramdump_thread_list_head;

/* ---- API ---- */

/**
 * Save exception context to the .noinit record.
 * Call this from the fault handler BEFORE entering the dump CLI.
 * Only the first fault is saved (magic check prevents overwrite on double-fault).
 *
 * @param fault_type     one of RAMDUMP_FAULT_*
 * @param hw_frame_ptr   pointer to the hardware-stacked frame (from exception_info)
 * @param current_thread pointer to the current thread or NULL
 */
void ramdump_exception_save(uint32_t  fault_type,
                            uint32_t  hw_frame_ptr,
                            ramdump_thread_t  current_thread);

/**
 * Check if the exception record contains valid data.
 *
 * @return 1 if valid, 0 otherwise
 */
int ramdump_exception_is_valid(void);

/**
 * Print the exception record to the console.
 */
void ramdump_exception_print(void);

/**
 * Clear the exception record (magic to 0).
 */
void ramdump_exception_clear(void);

#ifdef __cplusplus
}
#endif

#endif /* RAMDUMP_EXCEPTION_H__ */
