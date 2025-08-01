#ifndef MTP_OPERATION_H
#define MTP_OPERATION_H

#include <stdint.h>
#include "usb_mtp.h"

int mtp_command_handler(uint8_t *data, uint32_t len);
int mtp_send_response(uint16_t code, uint32_t trans_id);



void usbd_mtp_object_init(void);
// int mtp_get_storage_info(uint32_t storage_id, uint8_t *buffer, uint32_t *len);
// struct mtp_object *mtp_object_find(uint32_t handle);
// struct mtp_object *mtp_object_add(uint32_t parent_handle, const char *name, uint16_t format, bool is_dir);
// int __mtp_get_object_info(uint32_t handle, struct mtp_object_info *info);

#endif