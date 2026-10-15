/*
 * ramdump_handlers.c - MemManage/BusFault/UsageFault handlers for STM32F407
 *
 * When RT-Thread + ramdump is enabled, these fault handlers forward to
 * HardFault_Handler (defined in libcpu/arm/cortex-m4/context_gcc.S)
 * which saves the exception frame and calls rt_hw_hard_fault_exception().
 *
 * The startup file defines these handlers as weak aliases to Default_Handler
 * (an infinite loop). These strong definitions override them, routing all
 * configurable faults through the RT-Thread exception handler for proper
 * diagnostics and ramdump capture.
 *
 * Uses naked branch to preserve the exception entry context (LR, SP, frame).
 */

#include <rtthread.h>

#ifdef RT_USING_RAMDUMP

/* Forward declaration from context_gcc.S */
void HardFault_Handler(void);

__attribute__((naked))
void MemManage_Handler(void)
{
    __asm volatile ("B HardFault_Handler");
}

__attribute__((naked))
void BusFault_Handler(void)
{
    __asm volatile ("B HardFault_Handler");
}

__attribute__((naked))
void UsageFault_Handler(void)
{
    __asm volatile ("B HardFault_Handler");
}

#endif /* RT_USING_RAMDUMP */
