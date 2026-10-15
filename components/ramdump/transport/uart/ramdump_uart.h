/*
 * Copyright (c) 2006-2024, RT-Thread Development Team
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * ramdump_uart.h -- Bare-metal polled UART for ramdump
 *
 * Operates directly on STM32 USART registers with zero RT-Thread dependency.
 * Safe to use in exception context (HardFault, NMI, etc.) where interrupts
 * are disabled and the scheduler is stopped.
 */

#ifndef RAMDUMP_UART_H__
#define RAMDUMP_UART_H__

#include "ramdump_port.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Initialize a USART for polled (non-interrupt, non-DMA) operation.
 *
 * Configures 8N1 at the requested baud rate.  TX and RX are enabled;
 * interrupts and DMA are left disabled so nothing competes with the
 * polled read/write primitives.
 *
 * @param base    USART peripheral base address (e.g. USART1_BASE)
 * @param baud    baud rate (e.g. 115200)
 * @return RAMDUMP_EOK on success, RAMDUMP_ERR if base is NULL
 */
int ramdump_uart_init(uint32_t base, uint32_t baud);

/**
 * Send one byte (busy-wait for TXE).
 */
void ramdump_uart_putc(uint32_t base, uint8_t ch);

/**
 * Receive one byte with timeout (busy-wait for RXNE).
 *
 * @param timeout_ms  maximum wait in milliseconds, 0 = wait forever
 * @return byte value (0-255) on success, -1 on timeout
 */
int ramdump_uart_getc(uint32_t base, uint32_t timeout_ms);

/**
 * Send a block of bytes.  Each byte waits for TXE before writing.
 */
void ramdump_uart_put_bytes(uint32_t base, const uint8_t *data,
                            uint32_t len);

/**
 * Check whether the UART has been initialized.
 */
int ramdump_uart_is_ready(uint32_t base);

/**
 * De-initialize: disable USART, restore GPIOs to reset state (optional).
 */
void ramdump_uart_deinit(uint32_t base);

#ifdef __cplusplus
}
#endif

#endif /* RAMDUMP_UART_H__ */
