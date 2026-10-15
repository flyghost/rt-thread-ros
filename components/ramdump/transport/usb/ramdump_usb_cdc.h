/*
 * ramdump_usb_cdc.h — USB CDC ACM public API
 */

#ifndef RAMDUMP_USB_CDC_H__
#define RAMDUMP_USB_CDC_H__

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

void ramdump_usb_init(void);
void ramdump_usb_poll(void);
bool ramdump_usb_is_configured(void);
bool ramdump_usb_dtr_enabled(void);

/* Non-blocking: returns byte 0-255, or -1 if no data */
int  ramdump_usb_getc(void);
/* Blocking: polls with 100ms timeout + hardware abort recovery.
 * Returns 0 on success, -1 if USB is not configured / DTR not set. */
int  ramdump_usb_putc(uint8_t ch);
void ramdump_usb_put_bytes(const uint8_t *data, uint32_t len);

#ifdef __cplusplus
}
#endif

#endif /* RAMDUMP_USB_CDC_H__ */
