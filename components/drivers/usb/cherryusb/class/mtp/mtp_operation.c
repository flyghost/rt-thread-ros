/*
 * Copyright (c) 2025, sakumisu
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * MTP操作命令处理实现
 */

#include "mtp_operation.h"
#include "usbd_mtp_config.h"
#include "usb_config.h"
#include "usbd_mtp.h"
#include "usb_mtp.h"
#include "usbd_mtp_support.h"
#include "mtp_filesystem.h"
#include <string.h>
#include "usbd_core.h"

#define MTP_STORAGE_ID          0xAAAA0001      //存储ID定义
#define MTP_ROOT_HANDLE         0xBBBB0001      // 根目录句柄
#define MTP_ROOT_PARENT_HANDLE  0x00000000      // 根目录下文件的父句柄

#define MTP_XFER_BUFFER_SIZE    (3 + sizeof(struct mtp_header)) // 传输缓冲区大小，包含头部
#define MTP_XFER_PAYLOAD_SIZE   (512)

static uint32_t g_mtp_storage_id_list[] = {
    MTP_STORAGE_ID,
    MTP_STORAGE_ID + 1,
};

#define MTP_PACK_UINT8_ARRAY(dest, offset, val) \
    (*(uint8_t *)((uint8_t *)dest + offset) = (uint8_t)(val), offset + sizeof(uint8_t))

#define MTP_PACK_UINT16_ARRAY(dest, offset, val) \
    (*(uint16_t *)((uint8_t *)dest + offset) = (uint16_t)(val), offset + sizeof(uint16_t))

#define MTP_PACK_UINT32_ARRAY(dest, offset, val) \
    (*(uint32_t *)((uint8_t *)dest + offset) = (uint32_t)(val), offset + sizeof(uint32_t))

typedef enum {
    MTP_TRANSFER_STATE_IDLE = 0,
    MTP_TRANSFER_STATE_SENDING_DATA,
    MTP_TRANSFER_STATE_SENDING_RESPONSE,
    MTP_TRANSFER_STATE_RECEIVING,
} MTP_OPERATION_XFER_STATE;

typedef struct {
    void* fp;
    MTP_OPERATION_XFER_STATE state;
    uint32_t trans_id;
    int (*function)(void);
    struct mtp_object *obj;
    ssize_t tx_count; // 当前发送字节数
} mtp_transfer_ctrl_t;

static mtp_transfer_ctrl_t g_mtp_transfer_ctrl = {0};

static int aaaaaaaaa = 0;

static int mtp_send_object_info_test(void);

// 对象句柄管理
static struct mtp_object object_pool[CONFIG_USBDEV_MTP_MAX_OBJECTS];
static uint32_t object_count = 0;

extern int usbd_mtp_start_write(uint8_t *buf, uint32_t len);

// 辅助函数：打包MTP字符串（返回新offset）
static uint32_t mtp_pack_string(uint8_t *buf, uint32_t offset, const char *str)
{
    if (!str || !str[0]) {
        buf[offset++] = 0; // 空字符串，长度为0
        return offset;
    }
    uint8_t len = 0;
    const char *p = str;
    while (*p) {
        len++;
        p++;
    }
    buf[offset++] = len;
    for (uint8_t i = 0; i < len; i++) {
        buf[offset++] = str[i];
        buf[offset++] = 0x00; // UTF-16LE低字节
    }

    return offset;
}

static uint32_t mtp_pack_string_utf_16le(uint8_t *buf, uint32_t offset, const char *str)
{
    if (!str || !str[0]) {
        buf[offset++] = 0; // 空字符串，长度为0
        return offset;
    }
    uint8_t len = 0;
    const char *p = str;
    while (*p) { len++; p++; }
    buf[offset++] = len + 1;
    for (uint8_t i = 0; i < len; i++) {
        buf[offset++] = str[i];
        buf[offset++] = 0x00; // UTF-16LE低字节
    }

    buf[offset++] = 0x00;
    buf[offset++] = 0x00;

    return offset;
}

static uint32_t mtp_parse_string_utf_16le(const uint8_t *buf, uint32_t offset, char *out_str)
{
    if (!buf || !out_str) return 0;

    // 读取长度字节
    uint8_t char_count = buf[offset++];
    if (char_count == 0) {
        out_str[0] = '\0';
        return offset + 2;  // 跳过终止符
    }

    // 实际字符数（减去终止符）
    uint8_t actual_len = char_count - 1;
    
    // 转换为UTF-8（简化处理）
    for (uint8_t i = 0; i < actual_len; i++) {
        out_str[i] = buf[offset];  // 取低字节
        offset += 2;               // 跳过高字节
    }
    out_str[actual_len] = '\0';

    return offset + 2;  // 跳过终止符
}

static uint32_t mtp_pack_array_utf_16le(uint8_t *buf, uint32_t offset, uint8_t *src, uint32_t len)
{
    if (!src || !src[0] || !len) {
        buf[offset++] = 0;
        return offset;
    }

    buf[offset++] = len + 1;
    for (uint8_t i = 0; i < len; i++) {
        buf[offset++] = src[i];
        buf[offset++] = 0x00; // UTF-16LE低字节
    }

    buf[offset++] = 0x00;
    buf[offset++] = 0x00;

    return offset;
}

static uint32_t mtp_pack_uint8_array(uint8_t *buf, uint32_t offset, uint8_t *arr, uint32_t len)
{
    for (uint32_t i = 0; i < len; i++) {
        *(uint8_t *)(buf + offset) = arr[i];
        offset += 1;
    }
    return offset;
}

// 辅助函数：打包MTP数组（返回新offset）
static uint32_t mtp_pack_uint16_array(uint8_t *buf, uint32_t offset, const uint16_t *arr, uint16_t count)
{
    *(uint32_t *)(buf + offset) = count;
    offset += 4;
    for (uint16_t i = 0; i < count; i++) {
        *(uint16_t *)(buf + offset) = arr[i];
        offset += 2;
    }
    return offset;
}

// 查找对象
static struct mtp_object *mtp_object_find(uint32_t handle)
{
    for (uint32_t i = 0; i < object_count; i++) {
        if (object_pool[i].handle == handle) {
            return &object_pool[i];
        }
    }
    return NULL;
}

static int g_tx_response_complete = 0;

void mtp_data_send_done(void)
{
    struct mtp_header *hdr = (struct mtp_header *)g_usbd_mtp.tx_buffer;
    int ret = 0;

    switch (g_mtp_transfer_ctrl.state) {
        case MTP_TRANSFER_STATE_IDLE:
            MTP_LOGI_SHELL("Transfer state is idle");
            if (hdr->contype != MTP_CONTAINER_TYPE_RESPONSE) {
                ret = mtp_send_response(MTP_RESPONSE_OK, hdr->trans_id);
            }
            else {
                // if (aaaaaaaaa) {
                //     aaaaaaaaa = 0;
                //     usb_osal_msleep(10);
                //     ret = mtp_send_object_info_test();
                //     break;
                // }
                g_tx_response_complete = 1;
            }
            break;

        case MTP_TRANSFER_STATE_SENDING_DATA:
            MTP_LOGI_SHELL("Transfer state is sending data");
            if (g_mtp_transfer_ctrl.function) {
                ret = g_mtp_transfer_ctrl.function();
            }
            else {
                MTP_LOGE_SHELL("No function to call for sending data");
                ret = -1;
            }
            break;
        case MTP_TRANSFER_STATE_SENDING_RESPONSE:
            MTP_LOGI_SHELL("Transfer state is sending response");
            g_mtp_transfer_ctrl.state = MTP_TRANSFER_STATE_IDLE;
            break;

        default:
            // 其他状态不处理
            MTP_LOGE_SHELL("Unhandled transfer state: %d", g_mtp_transfer_ctrl.state);
            ret = -1;
            break;
    }

    if (ret < 0) {
        g_mtp_transfer_ctrl.state = MTP_TRANSFER_STATE_IDLE;
    }
}

void mtp_data_recv_done(uint32_t len)
{
    /* 可由用户重写 */
}

static struct mtp_object *mtp_object_create(struct mtp_object *parent_obj, const char *name, uint16_t format, bool is_dir)
{
    struct mtp_object *obj = &object_pool[object_count];
    memset(obj, 0, sizeof(*obj));
    obj->storage_id = MTP_STORAGE_ID;
    obj->handle = MTP_ROOT_HANDLE + object_count; // 生成唯一句柄
    if (parent_obj) {
        obj->parent_handle = parent_obj->handle;
        snprintf(obj->file_full_path, CONFIG_USBDEV_MTP_MAX_PATHNAME, "%s/%s", parent_obj->file_full_path, name);
    }
    else {
        obj->parent_handle = MTP_ROOT_PARENT_HANDLE; // 无父对象
        snprintf(obj->file_full_path, CONFIG_USBDEV_MTP_MAX_PATHNAME, "%s/%s", usbd_fs_top_mtp_path(), name);
    }
    
    obj->format = format;
    obj->is_dir = is_dir;
    obj->file_full_name_length = usb_strlen(name);
    object_count++;

    snprintf(obj->file_full_name, CONFIG_USBDEV_MTP_MAX_PATHNAME, "%s", name);

    MTP_LOGI_SHELL("create file name: %s, path: %s", obj->file_full_name, obj->file_full_path);
    MTP_LOGI_SHELL("%15s %10s %10s %10s %10s",
                    "Object Name", "Storage ID", "Format", "Parent Handle", "Object Handle");
    MTP_LOGI_SHELL("%15s 0x%08X 0x%04X 0x%08X 0x%08X",
                    name, obj->storage_id, obj->format, obj->parent_handle, obj->handle);

    return obj;
}

// 添加新对象
static struct mtp_object *mtp_object_add(uint32_t parent_handle, const char *name, uint16_t format, bool is_dir)
{
    if (object_count >= CONFIG_USBDEV_MTP_MAX_OBJECTS) {
        MTP_LOGE_SHELL("Object pool is full, cannot add new object");
        return NULL;
    }

    struct mtp_object *parent_obj = NULL;

    if (parent_handle == MTP_ROOT_PARENT_HANDLE) {
        return mtp_object_create(NULL, name, format, is_dir);
    }

    parent_obj = mtp_object_find(parent_handle);
    if (!parent_obj) {
        MTP_LOGE_SHELL("Parent object not found: handle=0x%08X", parent_handle);
        return NULL;
    }

    return mtp_object_create(parent_obj, name, format, is_dir);
}

// 存储初始化
void usbd_mtp_object_init(void)
{
    // 清空对象池
    memset(object_pool, 0, sizeof(object_pool));
    object_count = 0;

    // 创建一个文件夹
    struct mtp_object *test_obj = mtp_object_create(NULL, "TEST", MTP_FORMAT_ASSOCIATION, true);
    struct mtp_object *test_obj2 = mtp_object_create(NULL, "test2", MTP_FORMAT_ASSOCIATION, true);

    // 初始化一个txt文件
    const char *filename = "readme.txt";
    const char *content = "This is a readme text file for MTP storage";

    MTP_LOGD_SHELL("parent path[%s], create object[%s] size[%d] : %s", test_obj->file_full_path, filename, strlen(content), content);
    
    struct mtp_object *obj = mtp_object_create(test_obj, filename, MTP_FORMAT_TEXT, false);
    if (!obj) {
        MTP_LOGE_SHELL("Failed to add text file object to MTP pool");
        return;
    }

    void *fp = usbd_mtp_fs_open_file(obj->file_full_path, MTP_FA_WRITE | MTP_FA_CREATE_ALWAYS);
    if (fp) {
        if (usbd_mtp_fs_write_file(fp, content, strlen(content)) < 0) {
            MTP_LOGE_SHELL("Create %s error", filename);
        }
        usbd_mtp_fs_close_file(fp);
    }

    obj->file_size = (uint32_t)usbd_mtp_fs_size(obj->file_full_path);
}

static int mtp_get_device_info(struct mtp_header *hdr)
{
    uint8_t *tx_buf = g_usbd_mtp.tx_buffer;
    uint32_t offset = sizeof(struct mtp_header);

    // 1. 固定长度字段
    *(uint16_t*)(tx_buf + offset) = MTP_VERSION;
    offset += 2;
    *(uint32_t*)(tx_buf + offset) = 6; // VendorExtensionID
    offset += 4;
    *(uint16_t*)(tx_buf + offset) = 100; // VendorExtensionVersion
    offset += 2;

    // 2. VendorExtensionDesc
    offset = mtp_pack_string(tx_buf, offset, mtp_extension_string);

    // 3. FunctionalMode
    *(uint16_t*)(tx_buf + offset) = 0;
    offset += 2;

    // 4. OperationsSupported
    offset = mtp_pack_uint16_array(tx_buf, offset, supported_op, sizeof(supported_op) / sizeof(supported_op[0]));

    // 5. EventsSupported
    offset = mtp_pack_uint16_array(tx_buf, offset, supported_event, sizeof(supported_event) / sizeof(supported_event[0]));

    // 6. DevicePropertiesSupported
    extern const profile_property support_device_properties[];
    uint16_t dev_prop_codes[16];
    int dev_prop_count = 0;
    for (int i = 0; support_device_properties[i].prop_code != 0xFFFF; i++) {
        dev_prop_codes[dev_prop_count++] = support_device_properties[i].prop_code;
    }
    offset = mtp_pack_uint16_array(tx_buf, offset, dev_prop_codes, dev_prop_count);

    // 7. CaptureFormats
    offset = mtp_pack_uint16_array(tx_buf, offset, supported_capture_formats, 0);

    // 8. PlaybackFormats
    offset = mtp_pack_uint16_array(tx_buf, offset, supported_playback_formats, SUPPORTED_PLAYBACK_FORMATS_COUNT);

    // 9. Manufacturer
    offset = mtp_pack_string(tx_buf, offset, MTP_MANUFACTURER_STRING);

    // 10. Model
    offset = mtp_pack_string(tx_buf, offset, MTP_MODEL_STRING);

    // 11. DeviceVersion
    offset = mtp_pack_string(tx_buf, offset, MTP_DEVICE_VERSION_STRING);

    // 12. SerialNumber
    offset = mtp_pack_string(tx_buf, offset, MTP_SERIAL_NUMBER_STRING);

    // === 构建响应头 ===
    struct mtp_header *resp_hdr = (struct mtp_header*)tx_buf;
    resp_hdr->conlen = offset;
    resp_hdr->contype = MTP_CONTAINER_TYPE_DATA;
    resp_hdr->code = MTP_OPERATION_GET_DEVICE_INFO;
    resp_hdr->trans_id = hdr->trans_id;

    return usbd_mtp_start_write(tx_buf, resp_hdr->conlen);
}

// 发送MTP响应
int mtp_send_response(uint16_t code, uint32_t trans_id)
{
    struct mtp_header *resp = (struct mtp_header *)g_usbd_mtp.tx_buffer;
    resp->conlen = sizeof(struct mtp_header);
    resp->contype = MTP_CONTAINER_TYPE_RESPONSE;
    resp->code = code;
    resp->trans_id = trans_id;

    MTP_LOGD_SHELL("mtp start send response: code=0x%04X, trans_id=0x%08X", code, trans_id);

    g_tx_response_complete = 0;

    return usbd_mtp_start_write(g_usbd_mtp.tx_buffer, sizeof(struct mtp_header));
}

// 打开会话
static int mtp_open_session(struct mtp_header *hdr)
{
    if (hdr->conlen != sizeof(struct mtp_header) + 4) {
        return mtp_send_response(MTP_RESPONSE_INVALID_PARAMETER, hdr->trans_id);
    }

    g_usbd_mtp.session_id = hdr->param[0];
    g_usbd_mtp.session_open = true;
    
    return mtp_send_response(MTP_RESPONSE_OK, hdr->trans_id);
}

// 关闭会话
static int mtp_close_session(struct mtp_header *hdr)
{
    if (hdr->conlen != sizeof(struct mtp_header)) {
        return mtp_send_response(MTP_RESPONSE_INVALID_PARAMETER, hdr->trans_id);
    }

    g_usbd_mtp.session_open = false;
    g_usbd_mtp.session_id = 0;
    
    return mtp_send_response(MTP_RESPONSE_OK, hdr->trans_id);
}

// 获取存储ID列表
static int mtp_get_storage_ids(struct mtp_header *hdr)
{
    struct mtp_storage_id *storage_ids = (struct mtp_storage_id *)(g_usbd_mtp.tx_buffer + sizeof(struct mtp_header));
    uint32_t offset = offsetof(struct mtp_storage_id, StorageIDS);

    storage_ids->StorageIDS_len = 1;
    offset = MTP_PACK_UINT32_ARRAY(storage_ids, offset, MTP_STORAGE_ID);

    // 设置响应头
    struct mtp_header *resp = (struct mtp_header *)g_usbd_mtp.tx_buffer;
    resp->conlen = sizeof(struct mtp_header) + offset;
    resp->contype = MTP_CONTAINER_TYPE_DATA;
    resp->code = MTP_OPERATION_GET_STORAGE_IDS;
    resp->trans_id = hdr->trans_id;
    
    return usbd_mtp_start_write(g_usbd_mtp.tx_buffer, resp->conlen);
}

// 获取存储信息
static int _mtp_get_storage_info(struct mtp_header *hdr)
{
    if (hdr->conlen != sizeof(struct mtp_header) + 4) {
        return mtp_send_response(MTP_RESPONSE_INVALID_PARAMETER, hdr->trans_id);
    }

    uint32_t storage_id = hdr->param[0];
    struct mtp_storage_info *info = (struct mtp_storage_info *)(g_usbd_mtp.tx_buffer + sizeof(struct mtp_header));
    uint8_t *buffer = (uint8_t *)info;
    uint32_t offset = offsetof(struct mtp_storage_info, StorageDescription_len);
    const char *fs_name = NULL;

    for (uint32_t i = 0; i < sizeof(g_mtp_storage_id_list) / sizeof(g_mtp_storage_id_list[0]); i++) {
        if (storage_id == g_mtp_storage_id_list[i]) {
            fs_name = usbd_mtp_fs_description(i);
            break;
        }
    }

    if (!fs_name) {
        MTP_LOGE_SHELL("Invalid storage ID: 0x%08X", storage_id);
        return mtp_send_response(MTP_RESPONSE_INVALID_STORAGE_ID, hdr->trans_id);
    }

    mtp_fs_bsize_t blocksize = 0;
    mtp_fs_blocks_t blocknum = 0;
    mtp_fs_bfree_t blockfree = 0;

    if (usbd_mtp_fs_block_size(fs_name, &blocksize)) {
        MTP_LOGE_SHELL("Failed to get filesystem blocksize for path: %s", fs_name);
        return mtp_send_response(MTP_RESPONSE_INVALID_STORAGE_ID, hdr->trans_id);
    }

    if (usbd_mtp_fs_block_number(fs_name, &blocknum)) {
        MTP_LOGE_SHELL("Failed to get filesystem blocknum for path: %s", fs_name);
        return mtp_send_response(MTP_RESPONSE_INVALID_STORAGE_ID, hdr->trans_id);
    }

    if (usbd_mtp_fs_block_free(fs_name, &blockfree)) {
        MTP_LOGE_SHELL("Failed to get filesystem blockfree for path: %s", fs_name);
        return mtp_send_response(MTP_RESPONSE_INVALID_STORAGE_ID, hdr->trans_id);
    }

    // 填充存储信息
    info->StorageType = MTP_STORAGE_FIXED_RAM;
    info->FilesystemType = MTP_STORAGE_FILESYSTEM_HIERARCHICAL;
    info->AccessCapability = MTP_STORAGE_READ_WRITE;
    info->MaxCapability = (uint64_t)(blocksize * blocknum);
    info->FreeSpaceInBytes = (uint64_t)(blocksize * blockfree);
    info->FreeSpaceInObjects = CONFIG_USBDEV_MTP_MAX_OBJECTS - object_count; // 计算剩余对象空间
    offset = mtp_pack_string_utf_16le(buffer, offset, fs_name);
    offset = mtp_pack_string_utf_16le(buffer, offset, fs_name);
    
    // 设置响应头
    struct mtp_header *resp = (struct mtp_header *)g_usbd_mtp.tx_buffer;
    resp->conlen = sizeof(struct mtp_header) + offset;
    resp->contype = MTP_CONTAINER_TYPE_DATA;
    resp->code = MTP_OPERATION_GET_STORAGE_INFO;
    resp->trans_id = hdr->trans_id;
    
    return usbd_mtp_start_write(g_usbd_mtp.tx_buffer, resp->conlen);
}

// 获取对象句柄列表
static int mtp_get_object_handles(struct mtp_header *hdr)
{
    if (hdr->conlen != sizeof(struct mtp_header) + sizeof(uint32_t) * 3) {
        MTP_LOGE_SHELL("mtp_get_object_handles error, conlen invalid");
        return mtp_send_response(MTP_RESPONSE_INVALID_PARAMETER, hdr->trans_id);
    }

    uint32_t storage_id = hdr->param[0];
    uint32_t format_code = hdr->param[1];
    uint32_t parent_handle = hdr->param[2];     // 如果为0xFFFFFFFF表示根目录
    
    struct mtp_object_handles *handles = (struct mtp_object_handles *)(g_usbd_mtp.tx_buffer + sizeof(struct mtp_header));
    handles->ObjectHandle_len = 0;

    MTP_LOGD_SHELL("existing object count: %d", object_count);

    MTP_LOGD_SHELL("%-*s %-*s %-*s %-*s %-*s", 
                    20, "Object Name", 
                    20, "Storage ID",
                    20, "Format",
                    20, "Parent Handle",
                    20, "Object Handle");
    
    // 遍历对象池，查找符合条件的对象
    for (uint32_t i = 0; i < object_count; i++) {
        struct mtp_object *obj = &object_pool[i];

        // MTP_LOGD_SHELL("| %-*s | 0x%08X | 0x%04X | 0x%08X | 0x%08X |",
        //                 20, obj->file_full_path,
        //                 obj->storage_id, obj->format,
        //                 obj->parent_handle, obj->handle);

        if (obj->storage_id != storage_id) {
            // MTP_LOGE_SHELL("invalid storage_id:0x%x", obj->storage_id);
            continue;
        }
        
        if (format_code != 0x0000 && obj->format != format_code) {
            // MTP_LOGE_SHELL("invalid format_code:0x%x", obj->format);
            continue;
        }
        
        if (parent_handle != 0xFFFFFFFF && obj->parent_handle != parent_handle) {
            // MTP_LOGE_SHELL("invalid parent_handle:0x%x", obj->parent_handle);
            continue;
        }

        // MTP根目录下的文件
        if (parent_handle == 0xFFFFFFFF && obj->parent_handle != MTP_ROOT_PARENT_HANDLE) {
            continue;
        }
        
        if (handles->ObjectHandle_len < 255) {
            handles->ObjectHandle[handles->ObjectHandle_len++] = obj->handle;
            MTP_LOGD_SHELL("| %-*s | 0x%08X | 0x%04X | 0x%08X | 0x%08X |",
                            20, obj->file_full_path,
                            obj->storage_id, obj->format,
                            obj->parent_handle, obj->handle);
        }
    }
    
    // 设置响应头
    struct mtp_header *resp = (struct mtp_header *)g_usbd_mtp.tx_buffer;
    resp->conlen = sizeof(struct mtp_header) + sizeof(handles->ObjectHandle_len) + (handles->ObjectHandle_len * sizeof(handles->ObjectHandle[0]));
    resp->contype = MTP_CONTAINER_TYPE_DATA;
    resp->code = MTP_OPERATION_GET_OBJECT_HANDLES;
    resp->trans_id = hdr->trans_id;
    
    return usbd_mtp_start_write(g_usbd_mtp.tx_buffer, resp->conlen);
}

static uint32_t mtp_pack_object_filename(uint16_t *dest, size_t dest_size, const char *src)
{
    if (!dest || !src || dest_size == 0) {
        return 0;
    }
    
    uint8_t *buffer = (uint8_t *)dest;
    uint32_t offset = 0;
    size_t max_bytes = dest_size * sizeof(uint16_t);
    
    // 预估所需空间
    size_t src_len = strlen(src);
    if (src_len > (max_bytes - 3) / 2) {
        MTP_LOGE_SHELL("Filename too long, truncating");
        src_len = (max_bytes - 3) / 2;
    }
    
    offset = mtp_pack_string_utf_16le(buffer, offset, src);
    
    // 确保不超过缓冲区
    if (offset > max_bytes) {
        MTP_LOGE_SHELL("Filename overflow");
        offset = max_bytes;
        buffer[offset-1] = 0;
        buffer[offset-2] = 0;
    }
    
    return offset;
}

static void mtp_pack_object_info(struct mtp_object_info *info, struct mtp_object *obj)
{
    
}

// 获取对象信息
static int _mtp_get_object_info(uint32_t handle, struct mtp_object_info *info, uint32_t *len)
{
    struct mtp_object *obj = mtp_object_find(handle);
    if (!obj) {
        return -1;
    }

    memset(info, 0, sizeof(*info));

    if (obj->format == MTP_FORMAT_ASSOCIATION) {
        info->ObjectCompressedSize = 0;
    }
    else {
        info->ObjectCompressedSize = 100;   // 临时测试
    }

    // 填充对象信息
    memset(info, 0, sizeof(*info));
    info->StorageId = obj->storage_id;
    info->ObjectFormat = obj->format;
    // info->ObjectCompressedSize = file_stat.st_size;
    info->ParentObject = obj->parent_handle;
    info->AssociationType = obj->is_dir ? MTP_ASSOCIATION_TYPE_GENERIC_FOLDER : 0;

    MTP_LOGI_SHELL("%15s %10s %10s %10s %10s",
                    "Object Name", "Storage ID", "Format", "Parent Handle", "Object Handle");
    MTP_LOGI_SHELL("%15s 0x%08X 0x%04X 0x%08X 0x%08X",
                    obj->file_full_path, obj->storage_id, obj->format, obj->parent_handle, obj->handle);

    // const char *name = strrchr(obj->file_full_path, '/');
    // if (name) name++; else name = obj->file_full_path;

    uint8_t *buffer = (uint8_t *)info;

    uint32_t offset = offsetof(struct mtp_object_info, Filename);
    offset = mtp_pack_string_utf_16le(buffer, offset, obj->file_full_name);

    // if (!name || !name[0]) {
    //     MTP_LOGE_SHELL("Object name is empty, pack empty string");
    // }

    for (uint8_t i = 0; i < 6; i++) {
        offset = MTP_PACK_UINT8_ARRAY(buffer, offset, 0x11);
    }

    for (uint8_t i = 0; i < 6; i++) {
        offset = MTP_PACK_UINT8_ARRAY(buffer, offset, 0x22);
    }

    *len = offset;
    
    return 0;
}

// 获取对象信息
static int mtp_get_object_info(struct mtp_header *hdr)
{
    if (hdr->conlen != sizeof(struct mtp_header) + 4) {
        MTP_LOGE_SHELL("Invalid parameter length");
        return mtp_send_response(MTP_RESPONSE_INVALID_PARAMETER, hdr->trans_id);
    }

    uint32_t handle = hdr->param[0];
    uint32_t len = 0;
    
    // 在发送缓冲区中预留空间
    struct mtp_header *resp = (struct mtp_header *)g_usbd_mtp.tx_buffer;
    struct mtp_object_info *info = (struct mtp_object_info *)(resp + 1);
    // uint8_t *info = (uint8_t *)(resp + 1);
    
    // 获取对象信息
    if (_mtp_get_object_info(handle, info, &len) != 0) {
        return mtp_send_response(MTP_RESPONSE_INVALID_OBJECT_HANDLE, hdr->trans_id);
    }
    
    // 设置响应头
    resp->conlen = sizeof(struct mtp_header) + len;
    resp->contype = MTP_CONTAINER_TYPE_DATA;
    resp->code = MTP_OPERATION_GET_OBJECT_INFO;
    resp->trans_id = hdr->trans_id;
    
    return usbd_mtp_start_write(g_usbd_mtp.tx_buffer, resp->conlen);
}

static int mtp_send_object_data(void)
{
    int ret;
    struct mtp_object *obj = g_mtp_transfer_ctrl.obj;

    g_mtp_transfer_ctrl.state = MTP_TRANSFER_STATE_SENDING_DATA;

    uint32_t chunk_size = (MTP_BUFFER_SIZE > UINT32_MAX) ? UINT32_MAX : MTP_BUFFER_SIZE;
    chunk_size = (chunk_size > MTP_XFER_PAYLOAD_SIZE) ? MTP_XFER_PAYLOAD_SIZE : chunk_size;
    int len = usbd_mtp_fs_read_file(g_mtp_transfer_ctrl.fp, g_usbd_mtp.tx_buffer + sizeof(struct mtp_header), chunk_size);
    if (len < 0) {
        g_mtp_transfer_ctrl.state = MTP_TRANSFER_STATE_IDLE;
        MTP_LOGE_SHELL("File read error: %s", obj->file_full_path);
        usbd_mtp_fs_close_file(g_mtp_transfer_ctrl.fp);
        ret = mtp_send_response(MTP_RESPONSE_INCOMPLETE_TRANSFER, g_mtp_transfer_ctrl.trans_id);
    }
    else if (len == 0) {
        g_mtp_transfer_ctrl.state = MTP_TRANSFER_STATE_SENDING_RESPONSE;
        MTP_LOGI_SHELL("File read [%d] complete: %s", g_mtp_transfer_ctrl.tx_count, obj->file_full_path);
        // 文件读取完成，发送响应
        usbd_mtp_fs_close_file(g_mtp_transfer_ctrl.fp);
        ret = mtp_send_response(MTP_RESPONSE_OK, g_mtp_transfer_ctrl.trans_id);
    }
    else {
        struct mtp_header *resp_hdr = (struct mtp_header *)g_usbd_mtp.tx_buffer;
        resp_hdr->conlen = sizeof(struct mtp_header) + len;
        resp_hdr->contype = MTP_CONTAINER_TYPE_DATA;
        resp_hdr->code = MTP_OPERATION_GET_OBJECT;
        resp_hdr->trans_id = g_mtp_transfer_ctrl.trans_id;

        g_mtp_transfer_ctrl.tx_count += len;
        MTP_LOGD_SHELL("Sending object data: %s, current send=%d, total send=%d", obj->file_full_path, len, g_mtp_transfer_ctrl.tx_count);

        ret = usbd_mtp_start_write(g_usbd_mtp.tx_buffer, resp_hdr->conlen);
        if (ret) {
            MTP_LOGE_SHELL("Failed to start write for object data: %s", obj->file_full_path);
            g_mtp_transfer_ctrl.state = MTP_TRANSFER_STATE_IDLE;
            usbd_mtp_fs_close_file(g_mtp_transfer_ctrl.fp);
        }
    }

    if (ret) {
        MTP_LOGE_SHELL("Failed to start write for object data: %s", obj->file_full_path);
        g_mtp_transfer_ctrl.state = MTP_TRANSFER_STATE_IDLE;
        usbd_mtp_fs_close_file(g_mtp_transfer_ctrl.fp);
    }

    return ret;
}

// 获取对象数据
static int mtp_get_object(struct mtp_header *hdr) 
{
    // 1. 参数验证
    if (hdr->conlen != sizeof(struct mtp_header) + sizeof(hdr->param[0])) {
        MTP_LOGE_SHELL("Invalid parameter length");
        return mtp_send_response(MTP_RESPONSE_INVALID_PARAMETER, hdr->trans_id);
    }

    uint32_t handle = hdr->param[0];
    struct mtp_object *obj = mtp_object_find(handle);
    
    // 2. 对象验证
    if (!obj) {
        MTP_LOGE_SHELL("Invalid object handle: 0x%08X", handle);
        return mtp_send_response(MTP_RESPONSE_INVALID_OBJECT_HANDLE, hdr->trans_id);
    }
    
    if (obj->is_dir) {
        MTP_LOGE_SHELL("Cannot get directory object data: 0x%08X", handle);
        return mtp_send_response(MTP_RESPONSE_INVALID_OBJECT_HANDLE, hdr->trans_id);
    }

    // 3. 打开文件
    void *fp = usbd_mtp_fs_open_file(obj->file_full_path, MTP_FA_READ);
    if (!fp) {
        MTP_LOGE_SHELL("File open failed: %s", obj->file_full_path);
        return mtp_send_response(MTP_RESPONSE_ACCESS_DENIED, hdr->trans_id);
    }

    // 4. 获取文件大小并更新对象信息
    obj->file_size = (uint32_t)usbd_mtp_fs_size(obj->file_full_path);
    if (obj->file_size == 0) {
        usbd_mtp_fs_close_file(fp);
        MTP_LOGE_SHELL("File is empty: %s", obj->file_full_path);
        return mtp_send_response(MTP_RESPONSE_INVALID_OBJECT_HANDLE, hdr->trans_id);
    }

    // 5. 根据文件大小选择发送策略
    if (obj->file_size <= MTP_XFER_PAYLOAD_SIZE) {
        // 小文件策略：头和体合并发送
        struct mtp_header *resp_hdr = (struct mtp_header *)g_usbd_mtp.tx_buffer;
        resp_hdr->conlen = sizeof(struct mtp_header) + obj->file_size;
        resp_hdr->contype = MTP_CONTAINER_TYPE_DATA;
        resp_hdr->code = MTP_OPERATION_GET_OBJECT;
        resp_hdr->trans_id = hdr->trans_id;

        // 读取文件内容到缓冲区
        int len = usbd_mtp_fs_read_file(fp, g_usbd_mtp.tx_buffer + sizeof(struct mtp_header), obj->file_size);
        if (len != obj->file_size) {
            usbd_mtp_fs_close_file(fp);
            MTP_LOGE_SHELL("File read error: expected %d, got %d", obj->file_size, len);
            return mtp_send_response(MTP_RESPONSE_INCOMPLETE_TRANSFER, hdr->trans_id);
        }

        usbd_mtp_fs_close_file(fp);
        return usbd_mtp_start_write(g_usbd_mtp.tx_buffer, resp_hdr->conlen);
    } else {
        // 大文件策略：分块发送
        // struct mtp_header *resp_hdr = (struct mtp_header *)g_usbd_mtp.tx_buffer;
        // resp_hdr->conlen = sizeof(struct mtp_header) + MTP_XFER_PAYLOAD_SIZE;
        // resp_hdr->contype = MTP_CONTAINER_TYPE_DATA;
        // resp_hdr->code = MTP_OPERATION_GET_OBJECT;
        // resp_hdr->trans_id = hdr->trans_id;

        usb_memset(&g_mtp_transfer_ctrl, 0, sizeof(mtp_transfer_ctrl_t));
        g_mtp_transfer_ctrl.obj = obj;
        g_mtp_transfer_ctrl.fp = fp;
        g_mtp_transfer_ctrl.trans_id = hdr->trans_id;
        g_mtp_transfer_ctrl.tx_count = 0;
        g_mtp_transfer_ctrl.function = mtp_send_object_data;

        return mtp_send_object_data();

        // if (usbd_mtp_start_write(g_usbd_mtp.tx_buffer, sizeof(struct mtp_header)) != 0) {
        //     g_mtp_transfer_ctrl.state = MTP_TRANSFER_STATE_IDLE;
        //     MTP_LOGE_SHELL("Failed to start write for object data");
        //     usbd_mtp_fs_close_file(fp);
        //     return -1;
        // }

        // // 再分块发送数据
        // uint32_t remaining = obj->file_size;
        // while (remaining > 0) {
        //     uint32_t chunk_size = (remaining > MTP_BUFFER_SIZE) ? MTP_BUFFER_SIZE : remaining;
            
        //     int len = usbd_mtp_fs_read_file(fp, g_usbd_mtp.tx_buffer, chunk_size);
        //     if (len <= 0) {
        //         usbd_mtp_fs_close_file(fp);
        //         return mtp_send_response(MTP_RESPONSE_INCOMPLETE_TRANSFER, hdr->trans_id);
        //     }

        //     if (usbd_mtp_start_write(g_usbd_mtp.tx_buffer, len) != 0) {
        //         usbd_mtp_fs_close_file(fp);
        //         return -1;
        //     }

        //     remaining -= len;
        // }
        
        // usbd_mtp_fs_close_file(fp);
        // return 0;
    }
}

// 删除对象
static int mtp_delete_object(struct mtp_header *hdr)
{
    if (hdr->conlen != sizeof(struct mtp_header) + 4) {
        return mtp_send_response(MTP_RESPONSE_INVALID_PARAMETER, hdr->trans_id);
    }

    uint32_t handle = hdr->param[0];
    struct mtp_object *obj = mtp_object_find(handle);
    
    if (!obj) {
        return mtp_send_response(MTP_RESPONSE_INVALID_OBJECT_HANDLE, hdr->trans_id);
    }
    
    // 删除文件或目录
    int ret;
    if (obj->is_dir) {
        ret = usbd_mtp_fs_rmdir(obj->file_full_path);
    } else {
        ret = usbd_mtp_fs_unlink(obj->file_full_path);
    }
    
    if (ret != 0) {
        return mtp_send_response(MTP_RESPONSE_ACCESS_DENIED, hdr->trans_id);
    }
    
    // 从对象池中移除
    memset(obj, 0, sizeof(struct mtp_object));
    
    return mtp_send_response(MTP_RESPONSE_OK, hdr->trans_id);
}

// 发送对象信息
static int mtp_send_object_info(struct mtp_header *hdr)
{
    static uint32_t storage_id = 0;
    static uint32_t parent_handle = 0;

    if (hdr->conlen == sizeof(struct mtp_header) + sizeof(hdr->param[0]) * 2) {
        storage_id = hdr->param[0];
        parent_handle = hdr->param[1];
        MTP_LOGD_SHELL("mtp_send_object_info: storage_id=0x%08X, parent_handle=0x%08X", storage_id, parent_handle);
        // return mtp_send_response(MTP_RESPONSE_OK, hdr->trans_id);
        return 0;
    }
    else if(hdr->conlen <= offsetof(struct mtp_object_info, Filename)) {
        MTP_LOGE_SHELL("Invalid parameter length");
        return mtp_send_response(MTP_RESPONSE_INVALID_PARAMETER, hdr->trans_id);
    }

    struct mtp_object_info *obj_info = (struct mtp_object_info *)(hdr + 1);

    if (storage_id != MTP_STORAGE_ID) {
        MTP_LOGE_SHELL("Invalid storage ID: 0x%08X", storage_id);
        return mtp_send_response(MTP_RESPONSE_INVALID_STORAGE_ID, hdr->trans_id);
    }

    if (obj_info->Filename_len == 0 || obj_info->Filename[0] == 0) {
        MTP_LOGE_SHELL("Invalid filename length");
        return mtp_send_response(MTP_RESPONSE_INVALID_PARAMETER, hdr->trans_id);
    }

    uint16_t Filename[CONFIG_USBDEV_MTP_MAX_PATHNAME];

    // 解析文件名
    uint32_t offset = 0;
    offset = mtp_parse_string_utf_16le((uint8_t *)obj_info->Filename, offset, (char *)Filename);
    if (offset == 0) {
        return mtp_send_response(MTP_RESPONSE_INVALID_PARAMETER, hdr->trans_id);
    }

    // 创建新对象
    struct mtp_object *obj = mtp_object_add(parent_handle, (const char *)Filename, obj_info->ObjectFormat, obj_info->ObjectFormat == MTP_FORMAT_ASSOCIATION);
    if (!obj) {
        return mtp_send_response(MTP_RESPONSE_STORAGE_FULL, hdr->trans_id);
    }

    // 等待发送完成
    // return mtp_send_response(MTP_RESPONSE_OK, hdr->trans_id - 1);
    // while (g_usbd_mtp.tx_length > 0) {
    //     MTP_LOGD_SHELL("Waiting for MTP response to complete");
    //     usb_osal_msleep(10);
    // }
    
    // 设置当前操作对象
    g_usbd_mtp.cur_object = obj;
    g_usbd_mtp.cur_trans_id = hdr->trans_id;
    aaaaaaaaa = 1;

    return mtp_send_response(MTP_RESPONSE_OK, hdr->trans_id);

    uint8_t *tx_buffer = (uint8_t *)(g_usbd_mtp.tx_buffer);
    offset = sizeof(struct mtp_header);
    offset = MTP_PACK_UINT32_ARRAY(tx_buffer, offset, obj->handle);
    offset = MTP_PACK_UINT32_ARRAY(tx_buffer, offset, parent_handle);

    struct mtp_header *resp = (struct mtp_header *)g_usbd_mtp.tx_buffer;
    resp->conlen = offset;
    resp->contype = MTP_OPERATION_SEND_OBJECT_INFO;
    resp->code = MTP_RESPONSE_OK;
    resp->trans_id = hdr->trans_id;
    
    return usbd_mtp_start_write((uint8_t *)g_usbd_mtp.tx_buffer, resp->conlen);
}

static int mtp_send_object_info_test(void)
{
    uint8_t *tx_buffer = (uint8_t *)(g_usbd_mtp.tx_buffer);
    uint32_t offset = sizeof(struct mtp_header);
    offset = MTP_PACK_UINT32_ARRAY(tx_buffer, offset, g_usbd_mtp.cur_object->handle);
    offset = MTP_PACK_UINT32_ARRAY(tx_buffer, offset, g_usbd_mtp.cur_object->parent_handle);

    struct mtp_header *resp = (struct mtp_header *)g_usbd_mtp.tx_buffer;
    resp->conlen = offset;
    resp->contype = MTP_OPERATION_SEND_OBJECT_INFO;
    resp->code = MTP_RESPONSE_OK;
    resp->trans_id = g_usbd_mtp.cur_trans_id;
    
    return usbd_mtp_start_write((uint8_t *)g_usbd_mtp.tx_buffer, resp->conlen);
}

// 发送对象数据
static int mtp_send_object(struct mtp_header *hdr)
{
    if (!g_usbd_mtp.cur_object) {
        return mtp_send_response(MTP_RESPONSE_INVALID_OBJECT_HANDLE, hdr->trans_id);
    }

    // 打开文件准备写入
    void *fp = usbd_mtp_fs_open_file(g_usbd_mtp.cur_object->file_full_path, MTP_FA_WRITE | MTP_FA_CREATE_ALWAYS);
    if (!fp) {
        return mtp_send_response(MTP_RESPONSE_ACCESS_DENIED, hdr->trans_id);
    }
    
    // 写入数据
    int len = usbd_mtp_fs_write_file(fp, (hdr + 1), hdr->conlen - sizeof(struct mtp_header));
    usbd_mtp_fs_close_file(fp);
    
    if (len < 0) {
        return mtp_send_response(MTP_RESPONSE_STORAGE_FULL, hdr->trans_id);
    }
    
    // 更新对象大小
    g_usbd_mtp.cur_object->file_size = len;
    
    // 清除当前操作对象
    g_usbd_mtp.cur_object = NULL;
    
    return mtp_send_response(MTP_RESPONSE_OK, hdr->trans_id);
}

// 获取设备属性描述
static int mtp_get_device_prop_desc(struct mtp_header *hdr)
{
    if (hdr->conlen != sizeof(struct mtp_header) + sizeof(hdr->param[0])) {
        MTP_LOGE_SHELL("Invalid parameter length for get device prop desc");
        return mtp_send_response(MTP_RESPONSE_INVALID_PARAMETER, hdr->trans_id);
    }

    uint16_t prop_code = (uint16_t)(hdr->param[0] & 0xFFFF);
    struct mtp_device_prop_desc *desc = (struct mtp_device_prop_desc *)(g_usbd_mtp.tx_buffer + sizeof(struct mtp_header));
    uint8_t *desc_addr = (uint8_t *)(desc);
    uint32_t offset = offsetof(struct mtp_device_prop_desc, DefaultValue);

    // 查找支持的设备属性
    const profile_property *prop = NULL;
    for (int i = 0; support_device_properties[i].prop_code != MTP_ARRAY_END_MARK; i++) {
        if (support_device_properties[i].prop_code == prop_code) {
            prop = &support_device_properties[i];
            break;
        }
    }
    
    if (!prop) {
        return mtp_send_response(MTP_RESPONSE_DEVICE_PROP_NOT_SUPPORTED, hdr->trans_id);
    }

    memset(desc, 0, sizeof(*desc));
    desc->DevicePropertyCode = prop->prop_code; // 2 bytes
    desc->DataType = prop->data_type;           // 2 bytes
    desc->GetSet = prop->getset;                // 1 byte

    // 设置默认值和当前值
    switch (prop->data_type) {
        case MTP_TYPE_UINT8:
            MTP_LOGI_SHELL("MTP prop type : u8");
            // 这个地方怎么赋值？
            offset = MTP_PACK_UINT8_ARRAY(desc_addr, offset, (uint8_t)(prop->default_value & 0xFF));// DefaultValue
            offset = MTP_PACK_UINT8_ARRAY(desc_addr, offset, (uint8_t)(prop->default_value & 0xFF));// CurrentValue
            offset = MTP_PACK_UINT8_ARRAY(desc_addr, offset, (uint8_t)(prop->form_flag & 0xFF));// FormFlag
            break;

        case MTP_TYPE_UINT16:
            MTP_LOGI_SHELL("MTP prop type : u16");
            offset = MTP_PACK_UINT16_ARRAY(desc_addr, offset, (uint16_t)(prop->default_value & 0xFFFF));
            offset = MTP_PACK_UINT16_ARRAY(desc_addr, offset, (uint16_t)(prop->default_value & 0xFFFF));
            offset = MTP_PACK_UINT8_ARRAY(desc_addr, offset, (uint8_t)(prop->form_flag & 0xFF));
            break;

        case MTP_TYPE_UINT32:
            MTP_LOGI_SHELL("MTP prop type : u32");
            offset = MTP_PACK_UINT32_ARRAY(desc_addr, offset, (uint32_t)(prop->default_value & 0xFFFFFFFF));
            offset = MTP_PACK_UINT32_ARRAY(desc_addr, offset, (uint32_t)(prop->default_value & 0xFFFFFFFF));
            offset = MTP_PACK_UINT8_ARRAY(desc_addr, offset, (uint8_t)(prop->form_flag & 0xFF));
            break;

        case MTP_TYPE_STR:
            MTP_LOGI_SHELL("MTP prop type : str");
            offset = mtp_pack_string(desc_addr, offset, NULL);
            offset = mtp_pack_string(desc_addr, offset, NULL);
            offset = MTP_PACK_UINT8_ARRAY(desc_addr, offset, (uint8_t)(prop->form_flag & 0xFF));
            break;

        default:
            MTP_LOGE_SHELL("Unsupported property data type: %d", prop->data_type);
            return mtp_send_response(MTP_RESPONSE_DEVICE_PROP_NOT_SUPPORTED, hdr->trans_id);
    }

    // 设置响应头
    struct mtp_header *resp = (struct mtp_header *)g_usbd_mtp.tx_buffer;
    resp->conlen = sizeof(struct mtp_header) + offset;
    resp->contype = MTP_CONTAINER_TYPE_DATA;
    resp->code = MTP_OPERATION_GET_DEVICE_PROP_DESC;
    resp->trans_id = hdr->trans_id;

    return usbd_mtp_start_write(g_usbd_mtp.tx_buffer, resp->conlen);
}

// 获取对象支持的属性列表
static int mtp_get_object_props_supported(struct mtp_header *hdr)
{
    if (hdr->conlen != sizeof(struct mtp_header) + sizeof(hdr->param[0])) {
        MTP_LOGE_SHELL("Invalid parameter length for get object props supported");
        return mtp_send_response(MTP_RESPONSE_INVALID_PARAMETER, hdr->trans_id);
    }

    uint16_t format_code = (uint16_t)(hdr->param[0] & 0xFFFF);
    struct mtp_object_props_support *props = (struct mtp_object_props_support *)(g_usbd_mtp.tx_buffer + sizeof(struct mtp_header));
    
    MTP_LOGD_SHELL("check object prop format support : 0x%x", format_code);

    // 查找支持的格式属性
    props->ObjectPropCode_len = 0;
    for (int i = 0; support_format_properties[i].format_code != MTP_ARRAY_END_MARK; i++) {
        if (support_format_properties[i].format_code == format_code) {
            uint16_t *prop_list = support_format_properties[i].properties;
            while (*prop_list != MTP_ARRAY_END_MARK) {
                MTP_LOGD_SHELL("Found supported object property: 0x%04X", *prop_list);
                props->ObjectPropCode[props->ObjectPropCode_len++] = *prop_list++;
            }
            break;
        }
    }
    
    // 设置响应头
    struct mtp_header *resp = (struct mtp_header *)g_usbd_mtp.tx_buffer;
    resp->conlen = sizeof(struct mtp_header) + sizeof(props->ObjectPropCode_len) + (props->ObjectPropCode_len * sizeof(props->ObjectPropCode[0]));
    resp->contype = MTP_CONTAINER_TYPE_DATA;
    resp->code = MTP_OPERATION_GET_OBJECT_PROPS_SUPPORTED;
    resp->trans_id = hdr->trans_id;
    
    return usbd_mtp_start_write(g_usbd_mtp.tx_buffer, resp->conlen);
}

// 获取对象属性描述
static int mtp_get_object_prop_desc(struct mtp_header *hdr)
{
    if (hdr->conlen != sizeof(struct mtp_header) + 8) {
        return mtp_send_response(MTP_RESPONSE_INVALID_PARAMETER, hdr->trans_id);
    }

    uint32_t offset = 0;
    uint16_t prop_code = hdr->param[0];
    uint16_t format_code = hdr->param[1];
    
    // 查找支持的属性
    MTP_LOGD_SHELL("Searching for supported object property: prop_code = 0x%04X, format_code = 0x%04X", prop_code, format_code);
    const profile_property *prop = NULL;
    const profile_property *prop_format_undefined = NULL;

    // 满足要求的第一个属性
    for (int i = 0; support_object_properties[i].prop_code != MTP_ARRAY_END_MARK; i++) {
        if (support_object_properties[i].prop_code == prop_code && support_object_properties[i].format_code == format_code) {
                /*support_object_properties[i].format_code == MTP_FORMAT_UNDEFINED || format_code == MTP_FORMAT_UNDEFINED*/
            prop = &support_object_properties[i];
            MTP_LOGD_SHELL("Found supported property: prop_code=0x%04X, format_code=0x%04X", prop->prop_code, prop->format_code);
            break;
        }
        // 保存第一个匹配的MTP_FORMAT_UNDEFINED格式的prop
        else if (format_code != MTP_FORMAT_UNDEFINED && prop_format_undefined == NULL) {
            if (support_object_properties[i].prop_code == prop_code && support_object_properties[i].format_code == MTP_FORMAT_UNDEFINED) {
                prop_format_undefined = &support_object_properties[i];
            }
        }
    }

    if (!prop && !prop_format_undefined) {
        MTP_LOGE_SHELL("Object property not supported: prop_code=0x%04X, format_code=0x%04X", prop_code, format_code);
        return mtp_send_response(MTP_RESPONSE_OBJECT_PROP_NOT_SUPPORTED, hdr->trans_id);
    }
    else if (!prop) {
        MTP_LOGD_SHELL("Object Property use Undefined format");
        prop = prop_format_undefined;
    }
    
    // 填充属性描述
    struct mtp_object_prop_desc *desc = (struct mtp_object_prop_desc *)(g_usbd_mtp.tx_buffer + sizeof(struct mtp_header));
    uint8_t *desc_addr = (uint8_t *)(desc);
    offset = offsetof(struct mtp_object_prop_desc, DefValue);

    desc->ObjectPropertyCode = prop->prop_code; // 2 bytes
    desc->DataType = prop->data_type;           // 2 bytes
    desc->GetSet = prop->getset;                // 1 byte

    switch (prop->data_type) {
        case MTP_TYPE_UINT8:
            MTP_LOGI_SHELL("MTP get obj prop desc type : u8");
            offset = MTP_PACK_UINT8_ARRAY(desc_addr, offset, (uint8_t)prop->default_value);
            break;
        case MTP_TYPE_UINT16:
            MTP_LOGI_SHELL("MTP get obj prop desc type : u16");
            offset = MTP_PACK_UINT16_ARRAY(desc_addr, offset, (uint16_t)prop->default_value);
            break;
        case MTP_TYPE_UINT32:
            MTP_LOGI_SHELL("MTP get obj prop desc type : u32");
            offset = MTP_PACK_UINT32_ARRAY(desc_addr, offset, (uint32_t)prop->default_value);
            break;
        case MTP_TYPE_UINT64:
            MTP_LOGI_SHELL("MTP get obj prop desc type : u64");
            offset = MTP_PACK_UINT32_ARRAY(desc_addr, offset, (uint32_t)(prop->default_value & UINT32_MAX));
            offset = MTP_PACK_UINT32_ARRAY(desc_addr, offset, (uint32_t)((prop->default_value >> 32) & UINT32_MAX));
            break;
        case MTP_TYPE_UINT128:
            MTP_LOGI_SHELL("MTP get obj prop desc type : u128");
            offset = MTP_PACK_UINT32_ARRAY(desc_addr, offset, (uint32_t)(prop->default_value & UINT32_MAX));
            offset = MTP_PACK_UINT32_ARRAY(desc_addr, offset, (uint32_t)((prop->default_value >> 32) & UINT32_MAX));
            offset = MTP_PACK_UINT32_ARRAY(desc_addr, offset, 0);
            offset = MTP_PACK_UINT32_ARRAY(desc_addr, offset, 0);
            break;
        case MTP_TYPE_STR:
            MTP_LOGI_SHELL("MTP get obj prop desc type : str");
            offset = mtp_pack_string(desc_addr, offset, NULL); // 默认值为空字符串
            break;
            
        default:
            MTP_LOGE_SHELL("Unsupported property data type: 0x%04X", prop->data_type);
            return mtp_send_response(MTP_RESPONSE_OBJECT_PROP_NOT_SUPPORTED, hdr->trans_id);
    }

    offset = MTP_PACK_UINT32_ARRAY(desc_addr, offset, prop->group_code);
    offset = MTP_PACK_UINT8_ARRAY(desc_addr, offset, prop->form_flag);

    // 设置响应头
    struct mtp_header *resp = (struct mtp_header *)g_usbd_mtp.tx_buffer;
    resp->conlen = sizeof(struct mtp_header) + offset;
    resp->contype = MTP_CONTAINER_TYPE_DATA;
    resp->code = MTP_OPERATION_GET_OBJECT_PROP_DESC;
    resp->trans_id = hdr->trans_id;
    
    return usbd_mtp_start_write(g_usbd_mtp.tx_buffer, resp->conlen);
}

static const char* mtp_get_object_name(const struct mtp_object *obj)
{
    return obj->file_full_name;
}

// // 获取文件系统实际名称（含扩展名）
// static const char* mtp_get_filesystem_name(const struct mtp_object *obj) {
//     // /* 直接返回完整路径中的文件名部分（与mtp_get_object_name逻辑一致）*/
//     // const char *name = strrchr(obj->file_full_path, '/');
//     // if (!name) {
//     //     return obj->file_full_path; // 无路径分隔符时返回全名
//     // }
//     // return (obj->handle == MTP_ROOT_HANDLE) ? "" : name + 1; // 根目录返回空字符串
//     const char *name = strrchr(obj->file_full_path, '/');
//     if (!name) {
//         name = obj->file_full_path;
//     } else {
//         if (obj->handle == MTP_ROOT_HANDLE) {
//             name = "";
//         } else {
//             name++;
//         }
//     }
//     return (obj->handle == MTP_ROOT_HANDLE) ? NULL : name;
// }
// 获取逻辑名称（不含扩展名）
static const char* mtp_get_base_name(const struct mtp_object *obj) {
    /* 先获取原始文件名 */
    // const char *name = mtp_get_filesystem_name(obj);
    // if (!name || obj->handle == MTP_ROOT_HANDLE) {
    //     return name; // 处理根目录或空指针
    // }

    // /* 剥离扩展名 */
    // char *dot = strrchr(name, '.');
    // if (dot) {
    //     char *base = strndup(name, dot - name); // 动态分配内存截取扩展名前内容
    //     return base;
    // }
    // return name; // 无扩展名时直接返回
    // if (obj->handle == MTP_ROOT_HANDLE) {
    //     return NULL; // 根目录没有逻辑名称
    // }
    // else {
        // return "readme"; // 逻辑名称示例，实际应用中可以根据需要修改
    // }

    return obj->file_full_name;
}

static const char* mtp_get_display_name(const struct mtp_object *obj) {
    /* 优先使用元数据中的标题（如EXIF信息） */
    // if (obj->metadata && obj->metadata->title) {
    //     return obj->metadata->title;
    // }

    // /* 次选逻辑名称（不含扩展名） */
    // const char *base_name = mtp_get_base_name(obj);
    // if (base_name && *base_name) {
    //     return base_name;
    // }

    // /* 默认返回文件系统名称 */
    // return mtp_get_filesystem_name(obj);

    // if (obj->handle == MTP_ROOT_HANDLE) {
    //     return NULL; // 根目录没有逻辑名称
    // }
    // else {
        // return "readme"; // 逻辑名称示例，实际应用中可以根据需要修改
    // }

    return obj->file_full_name;
}

static uint64_t simple_hash(const char *str)
{
    uint64_t hash = 0x811C9DC5;
    while (*str) {
        hash ^= *str++;
        hash *= 0x01000193;
    }
    return hash;
}

// 扩展为128位UID    16字节
static void mtp_generate_persistent_uid(uint8_t *uid, uint32_t storage_id, uint32_t handle, const char *path)
{
    // 基于文件路径生成固定哈希（示例使用FNV-1a）
    uint64_t hash_value = 0xCBF29CE484222325;
    for (int i = 0; path[i]; i++) {
        hash_value ^= path[i];
        hash_value *= 0x100000001B3;
    }

    memcpy(uid, &storage_id, 4);
    memcpy(uid + 4, &handle, 4);
    memcpy(uid + 4 + 4, &hash_value, 8);
}

static uint32_t mtp_fill_property_value(const struct mtp_object *obj, uint16_t prop_code, uint8_t *buf, uint32_t offset, uint16_t *data_type)
{
    switch (prop_code) {
        case MTP_PROPERTY_STORAGE_ID:
            MTP_LOGD_SHELL("MTP_PROPERTY_STORAGE_ID: 0x%x", obj->storage_id);
            *data_type = MTP_TYPE_UINT32;
            offset = MTP_PACK_UINT32_ARRAY(buf, offset, obj->storage_id);
            break;

        case MTP_PROPERTY_OBJECT_FORMAT:
            MTP_LOGD_SHELL("MTP_PROPERTY_OBJECT_FORMAT: 0x%x", obj->format);
            *data_type = MTP_TYPE_UINT16;
            *(uint16_t *)(buf + offset) = obj->format;
            offset += sizeof(uint16_t);
            break;

        case MTP_PROPERTY_OBJECT_SIZE:
            *data_type = MTP_TYPE_UINT64;
            uint64_t size = 0;
            if (!obj->is_dir) {
                size = (uint64_t)usbd_mtp_fs_size(obj->file_full_path);
                MTP_LOGD_SHELL("MTP_PROPERTY_OBJECT_SIZE: %d", size);
            }
            else {
                size = 0;
                MTP_LOGD_SHELL("MTP_PROPERTY_OBJECT_SIZE: obj is DIR = 0");
            }
            
            *(uint32_t *)(buf + offset) = (uint32_t)(size & 0xFFFFFFFF);
            offset += sizeof(uint32_t);
            *(uint32_t *)(buf + offset) = (uint32_t)((size >> 32) & 0xFFFFFFFF);
            offset += sizeof(uint32_t);
            break;

        case MTP_PROPERTY_OBJECT_FILE_NAME: // 包含扩展名
            MTP_LOGD_SHELL("MTP_PROPERTY_OBJECT_FILE_NAME: %s", mtp_get_object_name(obj));
            *data_type = MTP_TYPE_STR;
            offset = mtp_pack_string_utf_16le(buf, offset, mtp_get_object_name(obj));
            break;
        case MTP_PROPERTY_NAME:             // 不包含扩展名
            MTP_LOGD_SHELL("MTP_PROPERTY_NAME: %s", mtp_get_base_name(obj));
            *data_type = MTP_TYPE_STR;
            offset = mtp_pack_string_utf_16le(buf, offset, mtp_get_base_name(obj));
            break;
        case MTP_PROPERTY_DISPLAY_NAME:     // 别称
            MTP_LOGD_SHELL("MTP_PROPERTY_DISPLAY_NAME: %s", mtp_get_display_name(obj));
            *data_type = MTP_TYPE_STR;
            offset = mtp_pack_string_utf_16le(buf, offset, mtp_get_display_name(obj));
            break;

        case MTP_PROPERTY_PARENT_OBJECT:
            *data_type = MTP_TYPE_UINT32;
            *(uint32_t *)(buf + offset) = obj->parent_handle;
            MTP_LOGD_SHELL("MTP_PROPERTY_PARENT_OBJECT: 0x%08X", obj->parent_handle);
            offset += sizeof(uint32_t);
            break;

        case MTP_PROPERTY_PROTECTION_STATUS:
            *data_type = MTP_TYPE_UINT16;
            *(uint16_t *)(buf + offset) = usbd_mtp_fs_is_protect(obj->file_full_path);;
            MTP_LOGD_SHELL("MTP_PROPERTY_PROTECTION_STATUS: 0x%x", *(uint16_t *)(buf + offset));
            offset += sizeof(uint16_t);
            break;

        case MTP_PROPERTY_DATE_MODIFIED: {
            MTP_LOGD_SHELL("MTP_PROPERTY_DATE_MODIFIED: %s", usbd_mtp_fs_modify_time(obj->file_full_path));
            *data_type = MTP_TYPE_STR;
            offset = mtp_pack_string_utf_16le(buf, offset, usbd_mtp_fs_modify_time(obj->file_full_path));
            break;
        }

        case MTP_PROPERTY_DATE_CREATED: {
            MTP_LOGD_SHELL("MTP_PROPERTY_DATE_CREATED: %s", usbd_mtp_fs_create_time(obj->file_full_path));
            *data_type = MTP_TYPE_STR;
            offset = mtp_pack_string_utf_16le(buf, offset, usbd_mtp_fs_create_time(obj->file_full_path));
            break;
        }

        case MTP_PROPERTY_PERSISTENT_UID:
            // *data_type = MTP_TYPE_STR;
            *data_type = MTP_TYPE_UINT128;
            uint8_t uid[20] = {0};
            mtp_generate_persistent_uid(uid, MTP_STORAGE_ID, obj->handle, obj->file_full_name);
            // offset = mtp_pack_array_utf_16le(buf, offset, uid, 16);
            offset = mtp_pack_uint8_array(buf, offset, uid, 16);
            MTP_LOGD_SHELL("MTP_PROPERTY_PERSISTENT_UID");
            break;

        default:
            *data_type = MTP_TYPE_UINT32; // 默认类型
            *(uint32_t *)(buf + offset) = 0;
            MTP_LOGE_SHELL("Unsupported property code: 0x%04X", prop_code);
            offset += sizeof(uint32_t);
            break;
    }
    return offset;
}

/* 
 * MTP协议参数标准实现 vs Windows实现对比表
 * 
 * 参数定位        | 标准MTP协议                                | Windows实现                          | 差异分析
 * ----------------|-------------------------------------------|---------------------------------------|-----------------------------------------
 * Param0          | ObjectHandle (对象句柄)                    | ObjectHandle (对象句柄)                | 完全一致
 * Param1          | PropertyCode (属性代码)                    | 固定填0x00000000                      | Windows将属性代码移至Param2
 *                 | • 0x0000：无效值                           |                                       | 
 *                 | • 0xFFFF：请求所有属性                     |                                       |
 * Param2          | GroupCode (属性组)                         | PropertyCode (属性代码)               | 关键差异点
 *                 | • 0x00000000：默认组                       | • 实际属性代码放在此位置               |
 *                 | • 0xFFFFFFFF：不分组                       |                                       |
 * Param3          | Depth (递归深度)                           | 固定填0x00000000                      | Windows不支持递归查询
 *                 | • 0x00000001：仅当前对象                   |                                       |
 *                 | • 0xFFFFFFFF：递归所有子对象               |                                       |
 * Param4          | FormatCode (格式筛选)                      | 固定填0x00000000                      | Windows忽略格式筛选
 *                 | • 0x0000：不筛选                          |                                       |
 * 
 * 特殊值处理对比表
 * 
 * 场景            | 标准MTP协议                                | Windows实现                          | 技术建议
 * ----------------|-------------------------------------------|---------------------------------------|-----------------------------------------
 * Param1=0x0000   | 返回RESPONSE_INVALID_OBJECT_PROP_CODE      | 不会出现（固定填0）                   | 代码中统一转换为0xFFFF
 * Param1=0xFFFF   | 返回对象所有支持的属性                      | 通过Param2指定属性代码                | 需区分处理两种模式
 * Param2=0x00000000 | 返回默认属性组（基础属性）                | 表示属性代码（如0xDC02）              | 通过is_windows_special_request()检测
 * Param2=0xFFFFFFFF | 返回所有属性（不分组）                   | 表示属性代码（如0xDC07）              | Windows模式下强制group_code=0xFFFFFFFF
 * Param3=0xFFFFFFFF | 递归查询所有子对象属性                   | 固定填0，不支持递归                   | 可忽略depth参数
 */
/**
 * @brief 请求设备返回指定对象的属性列表（包括属性值和描述信息）
 * 
 * ​参数位置​       ​参数名​           ​数据类型​	      ​描述​
 * ​Param 0    ObjectHandle     UINT32          要查询属性的对象的句柄（Object Handle）。
 * ​Param 1    PropertyCode     UINT16          指定要查询的属性代码（Property Code）。如果为 0x0000或者0xFFFF，表示请求所有支持的属性。
 * ​Param 2    GroupCode        UINT32          按属性组（Property Group）筛选。如果为 0x00000000，表示不按组筛选。
 *                                              • 0x00000000：请求基本/默认属性组（较少使用）
                                                • 0xFFFFFFFF：请求所有可用属性（Windows常用）
                                                • 其他值：请求特定属性组（需要设备实现组分类逻辑）
                                                在实际实现中，如果设备没有复杂的属性分组需求，可以统一将全0和全F都处理为"返回所有属性"，这是最安全且与Windows兼容的做法。
 * ​Param 3    Depth	        UINT32          递归查询深度（仅适用于关联对象，如文件夹）。
                                                • 0x00000001：仅查询当前对象。
                                                • 0xFFFFFFFF：递归查询所有子对象。
 * ​Param 4     FormatCode      UINT16          指定返回值的格式（如 0x0000 表示默认格式）。
 * 
 * @param hdr 
 * @return int 
 * 
 * @attention windows下：第一次查询发送prop_code=0获取所有支持属性，后续查询针对特定属性发送具体代码
 * 
 * windows有数处理
 * Param1	PropertyCode	固定填0	微软将属性代码移至Param2
    Param2	GroupCode	​PropertyCode​	关键差异点
    Param3	Depth	固定填0	Windows不实现递归查询
    Param4	FormatCode	固定填0	忽略格式筛选
 */
/* 判断是否为Windows风格请求 */
static bool is_windows_special_request(const uint32_t *params, uint32_t *handle, uint16_t *prop_code,uint32_t *group_code, uint32_t *depth,  uint16_t *format_code)
{
    bool is_windows = false;
    /* Windows特征：
       1. Param1固定为0
       2. Param3固定为0  
       3. Param4固定为0
       4. Param2是合法的属性代码(0xDC00-0xDCFF) */
    is_windows = (params[1] == 0) &&
                 (params[3] == 0) &&
                 (params[4] == 0) &&
                 ((params[2] >= 0xDC00 && params[2] <= 0xDCFF) || params[2] == 0xFFFFFFFF);

    if (is_windows) {
        *handle      = params[0];
        *prop_code   = (uint16_t)params[2]; // 属性代码在Param2
        *group_code  = 0xFFFFFFFF;              // Windows总是需要全部属性
        *depth       = 1;                       // Windows不递归查询
        *format_code = 0;
        MTP_LOGD_SHELL("Windows Request : handle=0x%08X, prop=0x%04X", *handle, *prop_code);
    }
    else {
        *handle      = params[0];
        *prop_code   = (uint16_t)params[1];
        *group_code  = params[2];
        *depth       = params[3];
        *format_code = (uint16_t)params[4];
        MTP_LOGD_SHELL("Standard Request: handle=0x%08X, prop=0x%04X, group=0x%08X", *handle, *prop_code, *group_code);
    }

    return is_windows;
}

/* 主处理函数（兼容Windows和标准协议）*/
static int mtp_get_object_prop_list(struct mtp_header *hdr)
{
    /* 参数验证 */
    if (hdr->conlen < sizeof(struct mtp_header) + 5 * sizeof(hdr->param[0])) {
        MTP_LOGE_SHELL("mtp request len invalid");
        return mtp_send_response(MTP_RESPONSE_INVALID_PARAMETER, hdr->trans_id);
    }

    uint32_t handle, group_code, depth;
    uint16_t prop_code, format_code;
    // bool is_windows = false;
    // 准备响应缓冲区
    uint8_t *tx_buf;
    uint32_t offset;

    /* 检测请求类型 */
    is_windows_special_request(hdr->param, &handle, &prop_code, &group_code, &depth, &format_code);

    /* 对象验证 */
    struct mtp_object *obj = mtp_object_find(handle);
    if (!obj) {
        MTP_LOGE_SHELL("find obj handle failed : 0x%08X", handle);
        return mtp_send_response(MTP_RESPONSE_INVALID_OBJECT_HANDLE, hdr->trans_id);
    }

    /* 特殊值转换 */
    if (prop_code == 0x0000) {
        prop_code = 0xFFFF;  // 0x0000转换为获取全部属性
        MTP_LOGD_SHELL("transport prop_code 0x0000 -> 0xFFFF");
    }

    /////////////////
    // 根据HANDLE的format查找支持的属性列表
    const uint16_t *prop_list = NULL;
    for (int i = 0; support_format_properties[i].format_code != MTP_ARRAY_END_MARK; i++) {
        if (support_format_properties[i].format_code == obj->format) {
            prop_list = support_format_properties[i].properties;
            break;
        }
    }

    if (!prop_list) {
        MTP_LOGE_SHELL("No supported properties for format: 0x%04X", obj->format);
        return mtp_send_response(MTP_RESPONSE_OBJECT_PROP_NOT_SUPPORTED, hdr->trans_id);
    }

    // 计算需要返回的属性数量
    uint32_t prop_count = 0;
    bool request_all_props = (prop_code == 0xFFFF);
    
    if (request_all_props) {
        // 计算所有支持的属性数量
        while (prop_list[prop_count] != MTP_ARRAY_END_MARK) {
            prop_count++;
        }
    } else {
        // 检查请求的属性是否支持
        for (uint32_t i = 0; prop_list[i] != MTP_ARRAY_END_MARK; i++) {
            if (prop_list[i] == prop_code) {
                prop_count = 1;
                break;
            }
        }
    }

    if (prop_count == 0) {
        MTP_LOGE_SHELL("Property not supported: prop_code=0x%04X, format_code=0x%04X", 
                      prop_code, obj->format);
        return mtp_send_response(MTP_RESPONSE_OBJECT_PROP_NOT_SUPPORTED, hdr->trans_id);
    }

    // 写入属性数量
    tx_buf = g_usbd_mtp.tx_buffer;
    offset = sizeof(struct mtp_header);
    struct mtp_object_prop_list *elem_list = (struct mtp_object_prop_list *)(tx_buf + offset);
    elem_list->element_len = prop_count;
    offset += offsetof(struct mtp_object_prop_list, element);

    MTP_LOGD_SHELL("Request prob count : %d", prop_count);

    uint16_t current_prop;
    /* 处理属性请求 */
    if (request_all_props) {
        for (uint32_t i = 0; i < prop_count; i++) {
            current_prop = prop_list[i];
            
            // 检查缓冲区剩余空间
            if (offset + sizeof(struct mtp_object_prop_element) > MTP_BUFFER_SIZE) { // 预留64字节给单个属性
                MTP_LOGE_SHELL("Buffer overflow");
                return mtp_send_response(MTP_RESPONSE_INCOMPLETE_TRANSFER, hdr->trans_id);
            }

            // 填充属性头
            struct mtp_object_prop_element *elem = (struct mtp_object_prop_element *)(tx_buf + offset);
            uint16_t data_type;
            elem->ObjectHandle = handle;
            elem->PropertyCode = current_prop;
            offset += offsetof(struct mtp_object_prop_element, value);

            // 填充属性值
            offset = mtp_fill_property_value(obj, current_prop, tx_buf, offset, &data_type);
            elem->Datatype = data_type; // 解决编译告警，提示未对齐
        }
    }
    else {
        current_prop = prop_code;

        // 检查缓冲区剩余空间
        if (offset + sizeof(struct mtp_object_prop_element) > MTP_BUFFER_SIZE) { // 预留64字节给单个属性
            MTP_LOGE_SHELL("Buffer overflow");
            return mtp_send_response(MTP_RESPONSE_INCOMPLETE_TRANSFER, hdr->trans_id);
        }

        // 填充属性头
        struct mtp_object_prop_element *elem = (struct mtp_object_prop_element *)(tx_buf + offset);
        uint16_t data_type;
        elem->ObjectHandle = handle;
        elem->PropertyCode = current_prop;
        offset += offsetof(struct mtp_object_prop_element, value);

        // 填充属性值
        offset = mtp_fill_property_value(obj, current_prop, tx_buf, offset, &data_type);
        elem->Datatype = data_type; // 解决编译告警，提示未对齐
    }

    // 设置响应头
    struct mtp_header *resp = (struct mtp_header *)g_usbd_mtp.tx_buffer;
    resp->conlen = offset;
    resp->contype = MTP_CONTAINER_TYPE_DATA;
    resp->code = MTP_OPERATION_GET_OBJECT_PROP_LIST;
    resp->trans_id = hdr->trans_id;
    
    return usbd_mtp_start_write(g_usbd_mtp.tx_buffer, offset);
}

static int mtp_get_object_references(struct mtp_header *hdr)
{
    if (hdr->conlen != sizeof(struct mtp_header) + sizeof(hdr->param[0])) {
        MTP_LOGE_SHELL("Invalid parameter length");
        return mtp_send_response(MTP_RESPONSE_INVALID_PARAMETER, hdr->trans_id);
    }

    uint32_t handle = hdr->param[0];
    struct mtp_object *obj = mtp_object_find(handle);
    
    if (!obj) {
        MTP_LOGE_SHELL("Object not found: handle=0x%08X", handle);
        return mtp_send_response(MTP_RESPONSE_INVALID_OBJECT_HANDLE, hdr->trans_id);
    }

    // 准备响应数据
    struct mtp_object_handles *handles = (struct mtp_object_handles *)(g_usbd_mtp.tx_buffer + sizeof(struct mtp_header));
    handles->ObjectHandle_len = 0;

    // 如果是目录对象，返回其包含的文件对象句柄
    if (obj->is_dir) {
        // 查找所有父对象为当前对象的子对象
        for (uint32_t i = 0; i < object_count; i++) {
            if (object_pool[i].parent_handle == handle) {
                if (handles->ObjectHandle_len < 255) {
                    handles->ObjectHandle[handles->ObjectHandle_len++] = object_pool[i].handle;
                }
            }
        }
    } else {
        // 对于普通文件，通常没有关联对象，返回空列表
        MTP_LOGD_SHELL("Object is not a directory, returning empty reference list");
    }

    // 设置响应头
    struct mtp_header *resp = (struct mtp_header *)g_usbd_mtp.tx_buffer;
    resp->conlen = sizeof(struct mtp_header) + sizeof(handles->ObjectHandle_len) + (handles->ObjectHandle_len * sizeof(handles->ObjectHandle[0]));
    resp->contype = MTP_CONTAINER_TYPE_DATA;
    resp->code = MTP_OPERATION_GET_OBJECT_REFERENCES;
    resp->trans_id = hdr->trans_id;

    MTP_LOGD_SHELL("Found %d references for object 0x%08X", handles->ObjectHandle_len, handle);
    
    return usbd_mtp_start_write(g_usbd_mtp.tx_buffer, resp->conlen);
}

static void mtp_command_check(struct mtp_header *hdr, uint32_t param_num)
{
#define PARAM_NUM_MAX 5
#define MONITOR_NUM_MAX 5

    static uint32_t last_conlen = 0;
    static uint16_t last_contype = 0;
    static uint16_t last_code = 0;
    static uint32_t last_trans;
    static uint32_t last_param[PARAM_NUM_MAX] = {0};
    static uint32_t last_param_num = 0;
    bool same = true;
    if (hdr->conlen == last_conlen && hdr->contype == last_contype && hdr->code == last_code && param_num == last_param_num) {
        // 检查参数是否一致
        
        if (last_param_num == param_num) {
            for (uint32_t i = 0; i < param_num; i++) {
                if (last_param[i] != hdr->param[i]) {
                    same = false;
                    break;
                }
            }
        }
        else {
            same = false; // 参数数量不一致
        }
    }
    else {
        same = false; // 其他字段不一致
    }

    if (same) {
        last_trans++;
        if (last_trans >= MONITOR_NUM_MAX) {
            last_trans = MONITOR_NUM_MAX; // 限制最大值为5
        }
    }
    else {
        last_trans = 0; // 重置计数
    }

    last_conlen = hdr->conlen;
    last_contype = hdr->contype;
    last_code = hdr->code;
    last_param_num = param_num;

    for (uint32_t i = 0; i < param_num; i++) {
        if (i >= PARAM_NUM_MAX) {
            break; // 防止数组越界
        }
        last_param[i] = hdr->param[i];
    }

    if (last_trans >= PARAM_NUM_MAX) {
        MTP_LOGE_SHELL("===================== MTP command flood detected!!!!!!!!!!!!!!!!!!! =====================");
    }

#undef PARAM_NUM_MAX
#undef MONITOR_NUM_MAX
}

static void mtp_packet_print(uint8_t *data, uint32_t len)
{
    struct mtp_header *hdr = (struct mtp_header *)data;
    static uint32_t msg_count = 0;
    uint32_t param_num = (len - sizeof(struct mtp_header)) / sizeof(hdr->param[0]);

    MTP_LOGI_SHELL("============================ [%d] ===============================", msg_count++);
    MTP_LOGI_SHELL("recv mtp header, conlen : %d, contype : 0x%04X, code : 0x%04X, trans_id : 0x%08X", 
                    hdr->conlen, hdr->contype, hdr->code, hdr->trans_id);

    for (uint32_t i = 0; i < param_num; i++) {
        MTP_LOGI_SHELL("param[%d] = 0x%08X", i, hdr->param[i]);
    }
    MTP_LOGI_SHELL("===========================================================");

    mtp_command_check(hdr, param_num);
}

// 处理MTP命令
int mtp_command_handler(uint8_t *data, uint32_t len)
{
    struct mtp_header *hdr = (struct mtp_header *)data;
    
    // 检查会话状态(除OpenSession外都需要有效会话)
    if (hdr->code != MTP_OPERATION_OPEN_SESSION && !g_usbd_mtp.session_open) {
        MTP_LOGE_SHELL("session is not open : %d %d", hdr->code, g_usbd_mtp.session_open);
        return mtp_send_response(MTP_RESPONSE_SESSION_NOT_OPEN, hdr->trans_id);
    }

    if (len < sizeof(struct mtp_header)) {
        MTP_LOGE_SHELL("mtp header len invalid : %d", len);
        return mtp_send_response(MTP_RESPONSE_INVALID_PARAMETER, hdr->trans_id);
    }

    mtp_packet_print(data, len);

    // 每次收到数据，说明当前TX进程需要重置
    g_mtp_transfer_ctrl.state = MTP_TRANSFER_STATE_IDLE;

    // 根据操作码分发处理
    switch (hdr->code) {
        case MTP_OPERATION_OPEN_SESSION:
            MTP_LOGI_SHELL("Open MTP session");
            return mtp_open_session(hdr);
        case MTP_OPERATION_CLOSE_SESSION:
            MTP_LOGI_SHELL("Close MTP session");
            return mtp_close_session(hdr);
        case MTP_OPERATION_GET_DEVICE_INFO:
            MTP_LOGI_SHELL("Get device info");
            return mtp_get_device_info(hdr);
        case MTP_OPERATION_GET_STORAGE_IDS:
            MTP_LOGI_SHELL("Get storage IDs");
            return mtp_get_storage_ids(hdr);
        case MTP_OPERATION_GET_STORAGE_INFO:
            MTP_LOGI_SHELL("Get storage info");
            return _mtp_get_storage_info(hdr);
        case MTP_OPERATION_GET_OBJECT_HANDLES:
            MTP_LOGI_SHELL("Get object handles");
            return mtp_get_object_handles(hdr);
        case MTP_OPERATION_GET_OBJECT_INFO:
            MTP_LOGI_SHELL("Get object info");
            return mtp_get_object_info(hdr);
        case MTP_OPERATION_GET_OBJECT:
            MTP_LOGI_SHELL("Get object data");
            return mtp_get_object(hdr);
        case MTP_OPERATION_DELETE_OBJECT:
            MTP_LOGI_SHELL("Delete object");
            return mtp_delete_object(hdr);
        case MTP_OPERATION_SEND_OBJECT_INFO:
            MTP_LOGI_SHELL("Send object info");
            return mtp_send_object_info(hdr);
        case MTP_OPERATION_SEND_OBJECT:
            MTP_LOGI_SHELL("Send object data");
            return mtp_send_object(hdr);
        case MTP_OPERATION_GET_DEVICE_PROP_DESC:
            MTP_LOGI_SHELL("Get device property description");
            return mtp_get_device_prop_desc(hdr);
        case MTP_OPERATION_GET_OBJECT_PROPS_SUPPORTED:
            MTP_LOGI_SHELL("Get object properties supported");
            return mtp_get_object_props_supported(hdr);
        case MTP_OPERATION_GET_OBJECT_PROP_DESC:
            MTP_LOGI_SHELL("Get object property description");
            return mtp_get_object_prop_desc(hdr);
        case MTP_OPERATION_GET_OBJECT_PROP_LIST:
            MTP_LOGI_SHELL("Get object property list");
            return mtp_get_object_prop_list(hdr);
        case MTP_OPERATION_GET_OBJECT_REFERENCES:
            MTP_LOGI_SHELL("Get object references");
            return mtp_get_object_references(hdr);
        default:
            MTP_LOGE_SHELL("Unsupported MTP operation: 0x%x", hdr->code);
            return mtp_send_response(MTP_RESPONSE_OPERATION_NOT_SUPPORTED, hdr->trans_id);
    }
}