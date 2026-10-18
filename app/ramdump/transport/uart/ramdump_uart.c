#include <string.h>
#include <stdio.h>
/*
 * Copyright (c) 2006-2024, RT-Thread Development Team
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * ramdump_uart.c -- Bare-metal polled UART driver for STM32F4
 *
 * Operates directly on USART registers.  No interrupts, no DMA, no
 * RT-Thread device framework dependency.  Safe to call from exception
 * context (HardFault etc.) where the scheduler is stopped.
 *
 * The init routine saves the current USART configuration, disables
 * interrupts/DMA, and switches to polled mode.  deinit restores the
 * original state so the console can resume normal operation.
 */

#include "ramdump_uart.h"
#include "ramdump_config.h"
#include "ramdump_port.h"   /* ramdump_deadline_ms/expired (DWT time base) */

/*
 * Convenience: cast base address to USART_TypeDef pointer.
 * STM32F4 USART registers (offsets from base):
 *   SR(0x00)  DR(0x04)  BRR(0x08)  CR1(0x0C)  CR2(0x10)  CR3(0x14)  GTPR(0x18)
 */
typedef struct {
    volatile uint32_t SR;
    volatile uint32_t DR;
    volatile uint32_t BRR;
    volatile uint32_t CR1;
    volatile uint32_t CR2;
    volatile uint32_t CR3;
    volatile uint32_t GTPR;
} ramdump_usart_t;

#define UART(base)  ((ramdump_usart_t *)(base))

/* ---- SR bits ---- */
#define UART_SR_TXE    (1U << 7)
#define UART_SR_TC     (1U << 6)
#define UART_SR_RXNE   (1U << 5)

/* ---- CR1 bits ---- */
#define UART_CR1_UE       (1U << 13)
#define UART_CR1_TE       (1U << 3)
#define UART_CR1_RE       (1U << 2)
/* Interrupt enable bits -- we clear these for polled operation */
#define UART_CR1_INT_MASK                                               \
    ((1U << 7)  /* TXEIE  */                                            \
   | (1U << 6)  /* TCIE   */                                            \
   | (1U << 5)  /* RXNEIE */                                            \
   | (1U << 4)  /* IDLEIE */                                            \
   | (1U << 8)  /* PEIE   */)

/* ---- CR3 bits ---- */
#define UART_CR3_DMAT  (1U << 7)
#define UART_CR3_DMAR  (1U << 6)
#define UART_CR3_EIE   (1U << 0)

/* ---- Per-instance saved state ---- */
#define RAMDUMP_UART_MAX  2

static struct {
    uint32_t  base;
    uint32_t  saved_cr1;
    uint32_t  saved_cr3;
    int          ready;
} g_uart[RAMDUMP_UART_MAX];

/* ------------------------------------------------------------------ */
/*  Internal: find slot by base, or allocate a free one               */
/* ------------------------------------------------------------------ */
static int uart_find_slot(uint32_t base)
{
    int i;
    for (i = 0; i < RAMDUMP_UART_MAX; i++)
    {
        if (g_uart[i].base == base)
            return i;
    }
    return -1;
}

static int uart_alloc_slot(uint32_t base)
{
    int i;
    for (i = 0; i < RAMDUMP_UART_MAX; i++)
    {
        if (g_uart[i].base == 0)
        {
            g_uart[i].base = base;
            return i;
        }
    }
    return -1;
}

/* ------------------------------------------------------------------ */
/*  Public API                                                       */
/* ------------------------------------------------------------------ */

/**
 * Initialize USART for polled operation.
 *
 * - Saves current CR1 / CR3 so deinit can restore them.
 * - Waits for any in-flight TX to complete.
 * - Disables all UART interrupts and DMA requests.
 * - Keeps TE + RE + UE enabled.
 */
int ramdump_uart_init(uint32_t base, uint32_t baud)
{
    ramdump_usart_t *u;
    int slot;
    uint32_t cr1, cr3;

    if (base == 0)
        return RAMDUMP_ERR;

    slot = uart_find_slot(base);
    if (slot >= 0 && g_uart[slot].ready)
        return RAMDUMP_EOK;  /* already initialized, avoid double-save of CR1 */
    if (slot < 0)
        slot = uart_alloc_slot(base);
    if (slot < 0)
        return RAMDUMP_ERR;

    u = UART(base);

    /* Wait for any ongoing transmission to finish (up to ~10 ms worth of
     * bytes at 115200 — about 115 bytes, so ~15000 iterations is plenty) */
    {
        volatile uint32_t timeout = 200000;
        while (!(u->SR & UART_SR_TC) && --timeout) {}
        if (timeout == 0)
            return RAMDUMP_ERR;
    }

    /* Save current state, then disable interrupts + DMA */
    cr1 = u->CR1;
    cr3 = u->CR3;

    g_uart[slot].saved_cr1 = cr1;
    g_uart[slot].saved_cr3 = cr3;

    /* Disable UART while modifying */
    u->CR1 = cr1 & ~(uint32_t)UART_CR1_UE;

    /* Clear interrupt enable bits in CR1; keep TE + RE + M + PCE + PS + UE */
    cr1 &= ~(uint32_t)(UART_CR1_INT_MASK);
    /* Clear DMA request + EIE bits in CR3 */
    cr3 &= ~(uint32_t)(UART_CR3_DMAT | UART_CR3_DMAR | UART_CR3_EIE);

    u->CR3 = cr3;
    /* Re-enable USART with TE + RE (polled mode, no interrupts) */
    cr1 |= (UART_CR1_TE | UART_CR1_RE | UART_CR1_UE);
    u->CR1 = cr1;

    g_uart[slot].ready = 1;

    return RAMDUMP_EOK;
}

/**
 * Send one byte — busy-wait for TXE.
 */
void ramdump_uart_putc(uint32_t base, uint8_t ch)
{
    ramdump_usart_t *u = UART(base);
    volatile uint32_t timeout = 200000;
    while (!(u->SR & UART_SR_TXE) && --timeout) {}
    if (timeout)
        u->DR = ch;
}

/**
 * Receive one byte with timeout — poll RXNE until a cycle-count deadline.
 *
 * The time base is the DWT cycle counter, armed once by ramdump_io_init().
 * This replaces a hand-calibrated "iterations ≈ µs" count-down, which was
 * tied to 168 MHz and to the compiler's code generation.
 *
 * timeout_ms == 0 keeps its "look once, do not wait" meaning.
 */
int ramdump_uart_getc(uint32_t base, uint32_t timeout_ms)
{
    ramdump_usart_t *u = UART(base);
    uint32_t deadline;

    if (u->SR & UART_SR_RXNE)
        return (int)(u->DR & 0xFF);

    if (timeout_ms == 0)
        return -1;

    deadline = ramdump_deadline_ms(timeout_ms);

    do
    {
        if (u->SR & UART_SR_RXNE)
        {
            return (int)(u->DR & 0xFF);
        }
    } while (!ramdump_deadline_expired(deadline));

    return -1;   /* timeout */
}

/**
 * Send a block of bytes.
 */
void ramdump_uart_put_bytes(uint32_t base, const uint8_t *data,
                            uint32_t len)
{
    ramdump_usart_t *u = UART(base);
    uint32_t i;

    for (i = 0; i < len; i++)
    {
        volatile uint32_t timeout = 200000;
        while (!(u->SR & UART_SR_TXE) && --timeout) {}
        if (timeout)
            u->DR = data[i];
    }
}

/**
 * Check readiness.
 */
int ramdump_uart_is_ready(uint32_t base)
{
    int slot = uart_find_slot(base);
    if (slot < 0)
        return 0;
    return g_uart[slot].ready;
}

/**
 * De-initialize: disable USART, restore original CR1/CR3, wait for TX
 * completion, then flip UE back on with the saved configuration.
 */
void ramdump_uart_deinit(uint32_t base)
{
    ramdump_usart_t *u = UART(base);
    int slot = uart_find_slot(base);

    if (slot < 0 || !g_uart[slot].ready)
        return;

    /* Drain last TX byte */
    {
        volatile uint32_t timeout = 200000;
        while (!(u->SR & UART_SR_TC) && --timeout) {}
    }

    /* Disable USART */
    u->CR1 &= ~(uint32_t)UART_CR1_UE;

    /* Restore saved configuration */
    u->CR1 = g_uart[slot].saved_cr1;
    u->CR3 = g_uart[slot].saved_cr3;

    g_uart[slot].base  = 0;
    g_uart[slot].ready = 0;
}

/* ================================================================
 *  Transport registration (UART)
 * ================================================================ */

#include "ramdump_io.h"

/* Device-name → base-address mapping (STM32F4) */
#define UART_BASE_USART1   0x40011000UL
#define UART_BASE_USART2   0x40004400UL
#define UART_BASE_USART3   0x40004800UL
#define UART_BASE_UART4    0x40004C00UL
#define UART_BASE_UART5    0x40005000UL
#define UART_BASE_USART6   0x40011400UL

typedef struct {
    const char *name;
    uint32_t    base;
} uart_entry_t;

static const uart_entry_t uart_table[] = {
    { "uart1", UART_BASE_USART1 },
    { "uart2", UART_BASE_USART2 },
    { "uart3", UART_BASE_USART3 },
    { "uart4", UART_BASE_UART4  },
    { "uart5", UART_BASE_UART5  },
    { "uart6", UART_BASE_USART6 },
};

static uint32_t g_uart_base;

static uint32_t uart_name_to_base(const char *name)
{
    for (uint32_t i = 0; i < sizeof(uart_table) / sizeof(uart_table[0]); i++)
        if (strcmp(uart_table[i].name, name) == 0)
            return uart_table[i].base;
    return 0;
}

/* ---- Ops wrappers ---- */

static void uart_putc(uint8_t ch)
{
    if (g_uart_base)
        ramdump_uart_putc(g_uart_base, ch);
}

static void uart_put_bytes(const uint8_t *data, uint32_t len)
{
    if (g_uart_base)
        ramdump_uart_put_bytes(g_uart_base, data, len);
}

static int uart_getc(uint32_t timeout_ms)
{
    if (!g_uart_base) return -1;
    return ramdump_uart_getc(g_uart_base, timeout_ms);
}

static void uart_poll(void)           { /* UART is always ready, no poll needed */ }

static void uart_deinit(void)
{
    if (g_uart_base) {
        ramdump_uart_deinit(g_uart_base);
        g_uart_base = 0;
    }
}

static int uart_transport_init(void)
{
    static const char *dev_list[]  = { RAMDUMP_UART_DEVICE, "uart1" };
    static const uint32_t baud_list[] = { RAMDUMP_UART_BAUDRATE, 115200 };

    for (int i = 0; i < 2; i++) {
        uint32_t base = uart_name_to_base(dev_list[i]);
        if (base == 0) continue;
        if (ramdump_uart_init(base, baud_list[i]) != RAMDUMP_EOK) continue;

        g_uart_base = base;
        return RAMDUMP_EOK;
    }
    return RAMDUMP_ERR;
}

const ramdump_transport_ops_t ramdump_transport_uart = {
    .init          = uart_transport_init,
    .putc          = uart_putc,
    .put_bytes     = uart_put_bytes,
    .getc          = uart_getc,
    .poll          = uart_poll,
    .deinit        = uart_deinit,
};
