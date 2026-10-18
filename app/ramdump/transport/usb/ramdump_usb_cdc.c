/*
 * ramdump_usb_cdc.c — USB CDC ACM device for ramdump communication
 *
 * Provides a virtual COM port over USB FS (DWC2 OTG).
 * Works in polling mode: call ramdump_usb_poll() from your main loop.
 *
 * Based on cherryusb demo/cdc_acm_template.c (advance descriptor mode)
 */

#include "usbd_core.h"
#include "usbd_cdc_acm.h"

/* STM32F4 hardware access (RCC, NVIC, DWT) */
#include <stm32f4xx.h>
#include "ramdump_utils.h"
#include "ramdump_port.h"   /* ramdump_deadline_ms/expired (used before line 447) */

/* ---- STM32F407 USB OTG FS base ---- */
#define USB_OTG_FS_BASE  0x50000000U

/* ---- CDC ACM endpoint addresses ---- */
#define CDC_IN_EP   0x81
#define CDC_OUT_EP  0x02
#define CDC_INT_EP  0x83

/* ---- USB descriptor constants ---- */
#define USBD_VID          0xFFFF
#define USBD_PID          0xFFFF
#define USBD_MAX_POWER    100
#define USBD_LANGID_STRING 1033

/* ---- CDC ACM max packet size (full-speed = 64) ---- */
#define CDC_MAX_MPS  64

/* ---- DWC2 IN EP1 register access (for abort recovery on timeout) ---- */
#define CDC_IN_EP_IDX       1U

/* IN EP1 registers (base 0x50000000 + 0x900 + idx*0x20 + offset) */
#define DWC2_INEP1_BASE     (USB_OTG_FS_BASE + 0x900U + (CDC_IN_EP_IDX * 0x20U))
#define DWC2_DIEPCTL1       (*(volatile uint32_t *)(DWC2_INEP1_BASE + 0x00U))
#define DWC2_DIEPINT1       (*(volatile uint32_t *)(DWC2_INEP1_BASE + 0x08U))

/* Device register: DIEPEMPMSK at DEVICE_BASE(0x800) + 0x34 */
#define DWC2_DIEPEMPMSK     (*(volatile uint32_t *)(USB_OTG_FS_BASE + 0x800U + 0x34U))

/* Global register: GRSTCTL at GLOBAL_BASE(0x000) + 0x10 */
#define DWC2_GRSTCTL        (*(volatile uint32_t *)(USB_OTG_FS_BASE + 0x10U))

/* --- DIEPCTL bit definitions (subset) --- */
#define DWC2_DIEPCTL_STALL   (1U << 21)
#define DWC2_DIEPCTL_CNAK    (1U << 26)
#define DWC2_DIEPCTL_SNAK    (1U << 27)
#define DWC2_DIEPCTL_EPDIS   (1U << 30)
#define DWC2_DIEPCTL_EPENA   (1U << 31)

/* --- DIEPINT bit definitions (subset) --- */
#define DWC2_DIEPINT_EPDISD  (1U << 1)

/* --- GRSTCTL bit definitions (subset) --- */
#define DWC2_GRSTCTL_TXFFLSH   (1U << 5)
#define DWC2_GRSTCTL_TXFNUM_Pos 6U
#define DWC2_GRSTCTL_AHBIDL    (1U << 31)

/* ---- Config descriptor size ---- */
#define USB_CONFIG_SIZE  (9 + CDC_ACM_DESCRIPTOR_LEN)

/* ---- Advance descriptor mode (CONFIG_USBDEV_ADVANCE_DESC is enabled) ---- */

static const uint8_t device_descriptor[] = {
    USB_DEVICE_DESCRIPTOR_INIT(USB_2_0, 0xEF, 0x02, 0x01,
                               USBD_VID, USBD_PID, 0x0100, 0x01)
};

static const uint8_t config_descriptor[] = {
    USB_CONFIG_DESCRIPTOR_INIT(USB_CONFIG_SIZE, 0x02, 0x01,
                               USB_CONFIG_BUS_POWERED, USBD_MAX_POWER),
    CDC_ACM_DESCRIPTOR_INIT(0x00, CDC_INT_EP, CDC_OUT_EP, CDC_IN_EP,
                            CDC_MAX_MPS, 0x02)
};

static const char *string_descriptors[] = {
    (const char[]){ 0x09, 0x04 },       /* Langid */
    "CherryUSB",                         /* Manufacturer */
    "Ramdump CDC ACM",                   /* Product */
    "2022123456",                        /* Serial Number */
};

static const uint8_t *device_descriptor_callback(uint8_t speed)
{
    (void)speed;
    return device_descriptor;
}

static const uint8_t *config_descriptor_callback(uint8_t speed)
{
    (void)speed;
    return config_descriptor;
}

static const char *string_descriptor_callback(uint8_t speed, uint8_t index)
{
    (void)speed;
    if (index > 3) return NULL;
    return string_descriptors[index];
}

static const struct usb_descriptor cdc_descriptor = {
    .device_descriptor_callback = device_descriptor_callback,
    .config_descriptor_callback = config_descriptor_callback,
    .string_descriptor_callback = string_descriptor_callback,
};

/* ---- Data buffers (aligned for DWC2) ---- */
USB_NOCACHE_RAM_SECTION USB_MEM_ALIGNX
static uint8_t usb_rx_pkt[CDC_MAX_MPS];   /* DWC2 DMA target for OUT ep */

USB_NOCACHE_RAM_SECTION USB_MEM_ALIGNX
static uint8_t usb_tx_buf[CDC_MAX_MPS];

/* RX ring buffer — filled by CDC OUT callback, drained by ramdump_usb_getc */
#define USB_RX_RING_SIZE  2048
static uint8_t  usb_rx_ring[USB_RX_RING_SIZE];
static volatile uint32_t usb_rx_wr = 0;  /* write index (ISR/callback context) */
static volatile uint32_t usb_rx_rd = 0;  /* read index (ramdump CLI context) */
static uint32_t usb_rx_total = 0;        /* total bytes available */

/* ---- State flags ---- */
static volatile bool g_usb_configured = false;
static volatile bool g_dtr_enable     = false;
static volatile bool g_ep_tx_busy     = false;

/* ---- CDC ACM callbacks (weak overrides from usbd_cdc_acm.c) ---- */

void usbd_cdc_acm_set_dtr(uint8_t busid, uint8_t intf, bool dtr)
{
    (void)busid;
    (void)intf;
    g_dtr_enable = dtr;
}

void usbd_cdc_acm_set_rts(uint8_t busid, uint8_t intf, bool rts)
{
    (void)busid;
    (void)intf;
    (void)rts;
}

/* ---- Endpoint callbacks ---- */

static void cdc_bulk_out(uint8_t busid, uint8_t ep, uint32_t nbytes)
{
    (void)ep;

    /* Copy received data into ring buffer */
    for (uint32_t i = 0; i < nbytes; i++) {
        uint32_t next = (usb_rx_wr + 1) % USB_RX_RING_SIZE;
        if (next != usb_rx_rd) {  /* not full */
            usb_rx_ring[usb_rx_wr] = usb_rx_pkt[i];
            usb_rx_wr = next;
            usb_rx_total++;
        }
    }

    /* Re-arm OUT endpoint for next packet */
    usbd_ep_start_read(busid, CDC_OUT_EP, usb_rx_pkt, CDC_MAX_MPS);
}

static void cdc_bulk_in(uint8_t busid, uint8_t ep, uint32_t nbytes)
{
    (void)nbytes;
    if ((nbytes % usbd_get_ep_mps(busid, ep)) == 0 && nbytes) {
        usbd_ep_start_write(busid, CDC_IN_EP, NULL, 0);  /* ZLP */
    } else {
        g_ep_tx_busy = false;
    }
}

/* ---- Endpoint descriptors ---- */

static struct usbd_endpoint cdc_out_ep = {
    .ep_addr = CDC_OUT_EP,
    .ep_cb   = cdc_bulk_out
};

static struct usbd_endpoint cdc_in_ep = {
    .ep_addr = CDC_IN_EP,
    .ep_cb   = cdc_bulk_in
};

/* ---- Interfaces ---- */

static struct usbd_interface intf0;
static struct usbd_interface intf1;

/* ---- Event handler ---- */

static void usbd_event_handler(uint8_t busid, uint8_t event)
{
    (void)busid;

    switch (event) {
    case USBD_EVENT_RESET:
        g_usb_configured = false;
        g_dtr_enable     = false;
        break;
    case USBD_EVENT_CONFIGURED:
        g_usb_configured = true;
        g_ep_tx_busy     = false;
        usbd_ep_start_read(0, CDC_OUT_EP, usb_rx_pkt, CDC_MAX_MPS);
        break;
    case USBD_EVENT_INIT:
        g_usb_configured = false;
        g_dtr_enable     = false;
        g_ep_tx_busy     = false;
        break;
    default:
        break;
    }
}

/* ---- Init ---- */

void ramdump_usb_init(void)
{
    ramdump_usb_dwt_init();

    usbd_desc_register(0, &cdc_descriptor);
    usbd_add_interface(0, usbd_cdc_acm_init_intf(0, &intf0));
    usbd_add_interface(0, usbd_cdc_acm_init_intf(0, &intf1));
    usbd_add_endpoint(0, &cdc_out_ep);
    usbd_add_endpoint(0, &cdc_in_ep);

    usbd_initialize(0, USB_OTG_FS_BASE, usbd_event_handler);

    /* Disable USB IRQ at NVIC — ramdump uses polling mode.
     * Placed here (not in usb_dc_low_level_init) so it runs exactly
     * once; usb_dc_low_level_init may be called again during re-init. */
    NVIC_DisableIRQ(OTG_FS_IRQn);
}

/* ---- Polling entry -- call this from your main loop ---- */

void ramdump_usb_poll(void)
{
    USBD_IRQHandler(0);
}

/* ---- DWC2 glue for STM32F407 (from cherryusb port/dwc2/usb_glue_st.c) ---- */

void usb_dc_low_level_init(uint8_t busid)
{
    (void)busid;

    /* Enable GPIOA clock (PA11=DM, PA12=DP) */
    RCC->AHB1ENR |= RCC_AHB1ENR_GPIOAEN;

    /* PA11, PA12 → AF10 (OTG_FS), push-pull, no pull, very high speed */
    GPIOA->MODER   &= ~(GPIO_MODER_MODER11 | GPIO_MODER_MODER12);
    GPIOA->MODER   |=  (GPIO_MODER_MODER11_1 | GPIO_MODER_MODER12_1);
    GPIOA->OTYPER  &= ~(GPIO_OTYPER_OT_11 | GPIO_OTYPER_OT_12);  /* push-pull */
    GPIOA->PUPDR   &= ~(GPIO_PUPDR_PUPDR11 | GPIO_PUPDR_PUPDR12); /* no pull */
    GPIOA->OSPEEDR |=  (GPIO_OSPEEDER_OSPEEDR11 | GPIO_OSPEEDER_OSPEEDR12); /* very high */
    /* AF10 = 0xA, AFR[1] covers pins 8-15 */
    GPIOA->AFR[1] &= ~(0xF << GPIO_AFRH_AFSEL11_Pos);
    GPIOA->AFR[1] &= ~(0xF << GPIO_AFRH_AFSEL12_Pos);
    GPIOA->AFR[1] |=  (0xA << GPIO_AFRH_AFSEL11_Pos);
    GPIOA->AFR[1] |=  (0xA << GPIO_AFRH_AFSEL12_Pos);

    /* Enable USB OTG FS clock */
    RCC->AHB2ENR |= RCC_AHB2ENR_OTGFSEN;
    __DSB();
    __ISB();
}

void usb_dc_low_level_deinit(uint8_t busid)
{
    (void)busid;
    RCC->AHB2ENR &= ~RCC_AHB2ENR_OTGFSEN;
}

uint32_t usbd_get_dwc2_gccfg_conf(uint32_t reg_base)
{
    (void)reg_base;
    /* NOVBUSSENS(bit16) — no external VBUS sensing needed
     * bit21 — required by cherryusb for STM32F4 */
    return (1 << 16) | (1 << 21);
}

/* ---- NVIC ISR (for MSH-mode testing with interrupts enabled) ---- */

void OTG_FS_IRQHandler(void)
{
    USBD_IRQHandler(0);
}

/* ---- Helpers ---- */

bool ramdump_usb_is_configured(void)
{
    return g_usb_configured;
}

bool ramdump_usb_dtr_enabled(void)
{
    return g_dtr_enable;
}

/*
 * Abort a stuck IN transfer on EP1.  Called when the busy-wait poll loop
 * times out (host disconnected, suspended, or not polling the BULK IN ep).
 *
 * Sequence: NAK → EPDIS → wait EPDISD → clear DIEPEMPMSK → flush TxFIFO
 *           → clear pending interrupts → reset DIEPCTL to post-open state.
 *
 * After this call g_ep_tx_busy is cleared and the endpoint is ready for a
 * new usbd_ep_start_write().
 *
 * Returns true on success, false on timeout (still clears g_ep_tx_busy).
 */
static bool ramdump_usb_abort_tx(void)
{
    uint32_t diectl, txfnum;
    volatile uint32_t count;

    /* If endpoint was never opened (USBAEP not set), nothing to abort */
    diectl = DWC2_DIEPCTL1;
    if (!(diectl & (1U << 15))) {       /* USBAEP */
        g_ep_tx_busy = false;
        return true;
    }

    /* 1. NAK the endpoint — stop responding to IN tokens */
    DWC2_DIEPCTL1 = diectl | DWC2_DIEPCTL_SNAK;

    /* 2. Disable the endpoint */
    DWC2_DIEPCTL1 |= DWC2_DIEPCTL_EPDIS;

    /* 3. Wait for endpoint disabled (EPDISD), ~5ms timeout */
    count = 0;
    do {
        if (++count > 50000U) break;
    } while ((DWC2_DIEPINT1 & DWC2_DIEPINT_EPDISD) != DWC2_DIEPINT_EPDISD);
    DWC2_DIEPINT1 = DWC2_DIEPINT_EPDISD;  /* W1C */

    /* 4. Disable Tx FIFO Empty mask for EP1 */
    DWC2_DIEPEMPMSK &= ~(1U << CDC_IN_EP_IDX);

    /* 5. Flush TxFIFO for this endpoint */
    txfnum = (diectl >> 22) & 0xFU;  /* TXFNUM field in DIEPCTL */

    /* Wait for AHB master idle */
    count = 0;
    do {
        if (++count > 200000U) break;
    } while ((DWC2_GRSTCTL & DWC2_GRSTCTL_AHBIDL) == 0U);

    /* Trigger TxFIFO flush */
    DWC2_GRSTCTL = DWC2_GRSTCTL_TXFFLSH | (txfnum << DWC2_GRSTCTL_TXFNUM_Pos);

    /* Wait for flush complete */
    count = 0;
    do {
        if (++count > 200000U) break;
    } while ((DWC2_GRSTCTL & DWC2_GRSTCTL_TXFFLSH) == DWC2_GRSTCTL_TXFFLSH);

    /* 6. Clear all pending IN EP1 interrupts */
    DWC2_DIEPINT1 = 0xFBFFU;

    /* 7. Restore DIEPCTL to post-open state (same config as usbd_ep_open).
     *    Keep MPSIZ, EPTYPE, TXFNUM, USBAEP, SD0PID from original.
     *    Strip SNAK, EPDIS, EPENA, STALL, CNAK (control bits we toggled). */
    DWC2_DIEPCTL1 = (diectl & ~(DWC2_DIEPCTL_SNAK | DWC2_DIEPCTL_EPDIS |
                                 DWC2_DIEPCTL_EPENA | DWC2_DIEPCTL_STALL |
                                 DWC2_DIEPCTL_CNAK))
                    | DWC2_DIEPCTL_CNAK | DWC2_DIEPCTL_EPENA;

    /* 8. Clear software state */
    g_ep_tx_busy = false;
    return true;
}

int ramdump_usb_send(const uint8_t *data, uint32_t len)
{
    if (!g_usb_configured || !g_dtr_enable) return -1;
    if (len > CDC_MAX_MPS) len = CDC_MAX_MPS;

    /* Start the transfer */
    memcpy(usb_tx_buf, data, len);
    g_ep_tx_busy = true;
    usbd_ep_start_write(0, CDC_IN_EP, usb_tx_buf, len);

    /*
     * Wait for THIS transfer to complete before returning.
     * Polls DWC2 to drive TXFE → FIFO write → XFRC → g_ep_tx_busy cleared.
     * This makes ramdump_usb_send() fully synchronous: when it returns 0,
     * the data has been ACKed by the host (or aborted on timeout).
     */
    {
        uint32_t deadline = ramdump_deadline_ms(100);   /* ~100 ms */
        while (g_ep_tx_busy && !ramdump_deadline_expired(deadline)) {
            ramdump_usb_poll();
        }
        if (g_ep_tx_busy)
            ramdump_usb_abort_tx();
    }
    return 0;
}

/* ---- Non-blocking getc/putc for ramdump_io integration ---- */

int ramdump_usb_getc(void)
{
    if (usb_rx_rd == usb_rx_wr)
        return -1;  /* no data */

    uint8_t ch = usb_rx_ring[usb_rx_rd];
    usb_rx_rd = (usb_rx_rd + 1) % USB_RX_RING_SIZE;
    usb_rx_total--;
    return ch;
}

int ramdump_usb_putc(uint8_t ch)
{
    /* Blocking: ramdump_usb_send() polls internally until the previous
     * TX completes (or aborts on timeout).  Returns 0 on success,
     * -1 if USB is not configured / DTR not set. */
    return ramdump_usb_send(&ch, 1);
}

void ramdump_usb_put_bytes(const uint8_t *data, uint32_t len)
{
    /* Each ramdump_usb_send() call blocks until the previous frame
     * completes via internal poll + abort-on-timeout.  No manual
     * poll loop needed here. */
    while (len > 0) {
        uint32_t chunk = len > CDC_MAX_MPS ? CDC_MAX_MPS : len;
        if (ramdump_usb_send(data, chunk) != 0)
            break;  /* USB not configured or DTR not set */
        data += chunk;
        len  -= chunk;
    }
}

/* ================================================================
 *  Transport registration (USB CDC ACM)
 * ================================================================ */

#include "ramdump_io.h"

static bool g_usb_active;

static void usb_putc(uint8_t ch)
{
    if (g_usb_active)
        ramdump_usb_putc(ch);
}

static void usb_put_bytes(const uint8_t *data, uint32_t len)
{
    if (g_usb_active) {
        ramdump_usb_put_bytes(data, len);
        ramdump_usb_poll();
    }
}

static int usb_getc(uint32_t timeout_ms)
{
    int ch;
    uint32_t deadline;

    if (!g_usb_active)
        return -1;

    /* One poll always happens, so timeout_ms == 0 keeps its
     * "look once, do not wait" meaning. */
    ramdump_usb_poll();
    ch = ramdump_usb_getc();
    if (ch >= 0 || timeout_ms == 0)
        return ch;

    deadline = ramdump_deadline_ms(timeout_ms);
    do {
        ramdump_usb_poll();
        ch = ramdump_usb_getc();
    } while (ch < 0 && !ramdump_deadline_expired(deadline));

    return ch;
}

static void usb_poll(void)
{
    if (g_usb_active)
        ramdump_usb_poll();
}

static void usb_deinit(void)
{
    g_usb_active = false;
}

static int usb_transport_init(void)
{
    ramdump_usb_init();
    g_usb_active = true;
    return RAMDUMP_EOK;
}

const ramdump_transport_ops_t ramdump_transport_usb = {
    .init          = usb_transport_init,
    .putc          = usb_putc,
    .put_bytes     = usb_put_bytes,
    .getc          = usb_getc,
    .poll          = usb_poll,
    .deinit        = usb_deinit,
};
