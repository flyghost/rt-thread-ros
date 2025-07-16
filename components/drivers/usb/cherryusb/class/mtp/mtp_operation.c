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


#define MTP_ROOT_HANDLE 0x00000001 // 根目录句柄

// 对象句柄管理
struct mtp_object object_pool[CONFIG_USBDEV_MTP_MAX_OBJECTS];
uint32_t object_count = 0;

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

static uint32_t mtp_pack_string_with_zeroend(uint8_t *buf, uint32_t offset, const char *str) {
    if (!str || !str[0]) {
        buf[offset++] = 0; // 空字符串，长度为0
        return offset;
    }
    uint8_t len = 0;
    const char *p = str;
    while (*p) { len++; p++; }
    buf[offset++] = len;
    for (uint8_t i = 0; i < len; i++) {
        buf[offset++] = str[i];
        buf[offset++] = 0x00; // UTF-16LE低字节
    }

    buf[offset++] = 0x00;
    buf[offset++] = 0x00;

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

// 添加新对象
static struct mtp_object *mtp_object_add(uint32_t parent_handle, const char *name, uint16_t format, bool is_dir)
{
    if (object_count >= CONFIG_USBDEV_MTP_MAX_OBJECTS) {
        MTP_LOGE_SHELL("Object pool is full, cannot add new object");
        return NULL;
    }

    struct mtp_object *parent = mtp_object_find(parent_handle);
    if (!parent) {
        MTP_LOGE_SHELL("Parent object not found: handle=0x%08x", parent_handle);
        return NULL;
    }

    struct mtp_object *obj = &object_pool[object_count++];
    memset(obj, 0, sizeof(*obj));

    // 修改路径构建部分，确保不会出现双斜杠
    if (parent->file_full_name[strlen(parent->file_full_name)-1] == '/') {
        snprintf(obj->file_full_name, CONFIG_USBDEV_MTP_MAX_PATHNAME, 
             "%s%s", parent->file_full_name, name);
    } else {
        snprintf(obj->file_full_name, CONFIG_USBDEV_MTP_MAX_PATHNAME, 
             "%s/%s", parent->file_full_name, name);
    }
    
    // 设置对象属性
    obj->storage_id = MTP_STORAGE_ID;
    obj->handle = 0x80000000 + object_count; // 生成唯一句柄
    obj->parent_handle = parent_handle;
    obj->format = format;
    obj->is_dir = is_dir;

    MTP_LOGI_SHELL("mtp_object_add: parent_handle=0x%08x, name=%s, format=0x%04x, is_dir=%d",
                   parent_handle, name, format, is_dir);
    
    // 构建完整路径
    snprintf(obj->file_full_name, CONFIG_USBDEV_MTP_MAX_PATHNAME, 
             "%s/%s", parent->file_full_name, name);
    
    return obj;
}

// 存储初始化
void usbd_mtp_object_init(void)
{
    // 清空对象池
    memset(object_pool, 0, sizeof(object_pool));
    object_count = 0;
    
    // 添加根目录对象
    struct mtp_object *root = &object_pool[object_count++];
    root->storage_id = MTP_STORAGE_ID;
    root->handle = MTP_ROOT_HANDLE; // 根对象句柄
    root->parent_handle = 0x00000000; // 无父对象
    root->format = MTP_FORMAT_ASSOCIATION;
    root->is_dir = true;
    strncpy(root->file_full_name, usbd_mtp_fs_root_path(), CONFIG_USBDEV_MTP_MAX_PATHNAME);

    // 初始化一个txt文件
    const char *filename = "readme.txt";
    const char *content = "This is a readme text file for MTP storage";
    
    // 1. 在文件系统中创建文件
    int fd = usbd_mtp_fs_open(filename, MTP_FA_WRITE | MTP_FA_CREATE_ALWAYS);
    if (fd >= 0) {
        usbd_mtp_fs_write(fd, content, strlen(content));
        usbd_mtp_fs_close(fd);
    }
    
    // 2. 在MTP对象池中添加文件对象
    struct mtp_object *txt_file = mtp_object_add(root->handle, filename, MTP_FORMAT_TEXT, false);
    if (txt_file) {
        // 设置文件大小
        struct mtp_stat st;
        if (usbd_mtp_fs_stat(txt_file->file_full_name, &st) == 0) {
            txt_file->file_size = st.st_size;
        }
    }
    else {
        MTP_LOGE_SHELL("Failed to add text file object to MTP pool");
    }
}

// 获取存储信息
static int mtp_get_storage_info(uint32_t storage_id, uint8_t *buffer, uint32_t *len)
{
    if (storage_id != MTP_STORAGE_ID) {
        return -1;
    }

    // 获取文件系统信息
    struct mtp_statfs stat;
    if (usbd_mtp_fs_statfs(usbd_mtp_fs_root_path(), &stat) != 0) {
        return -1;
    }

    struct mtp_storage_info_header *mtp_storage_header = (struct mtp_storage_info_header *)buffer;
    uint32_t offset = sizeof(*mtp_storage_header);

    // 填充存储信息
    memset(mtp_storage_header, 0, sizeof(*mtp_storage_header));
    mtp_storage_header->StorageType = MTP_STORAGE_FIXED_RAM;
    mtp_storage_header->FilesystemType = MTP_STORAGE_FILESYSTEM_HIERARCHICAL;
    mtp_storage_header->AccessCapability = MTP_STORAGE_READ_WRITE;
    mtp_storage_header->MaxCapability = stat.f_bsize * stat.f_blocks;
    mtp_storage_header->FreeSpaceInBytes = stat.f_bsize * stat.f_bfree;
    mtp_storage_header->FreeSpaceInObjects = 0; // 不支持对象限制
    
    // 设置存储描述
    const char *desc = usbd_mtp_fs_description();
    offset = mtp_pack_string_with_zeroend(buffer, offset, desc);
    offset = mtp_pack_string_with_zeroend(buffer, offset, desc);

    *len = offset;
    
    return 0;
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
    offset = mtp_pack_uint16_array(tx_buf, offset, supported_op, SUPPORTED_OP_COUNT);

    // 5. EventsSupported
    offset = mtp_pack_uint16_array(tx_buf, offset, supported_event, SUPPORTED_EVENT_COUNT);

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

    MTP_LOGD_SHELL("mtp start send response: code=0x%04x, trans_id=0x%08x", code, trans_id);

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
    
    // 填充存储ID
    storage_ids->StorageIDS_len = 1;
    storage_ids->StorageIDS[0] = MTP_STORAGE_ID;
    
    // 设置响应头
    struct mtp_header *resp = (struct mtp_header *)g_usbd_mtp.tx_buffer;
    resp->conlen = sizeof(struct mtp_header) + 8; // 4字节长度 + 4字节存储ID
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
    uint8_t *info = (uint8_t *)(g_usbd_mtp.tx_buffer + sizeof(struct mtp_header));
    uint32_t offset = 0;
    
    // 获取存储信息
    if (mtp_get_storage_info(storage_id, info, &offset) != 0) {
        return mtp_send_response(MTP_RESPONSE_INVALID_STORAGE_ID, hdr->trans_id);
    }
    
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
    uint32_t parent_handle = hdr->param[2];

    MTP_LOGD_SHELL("storage id = 0x%x, format code = 0x%x, pareent hdl = 0x%x",
                    storage_id, format_code, parent_handle);
    
    struct mtp_object_handles *handles = (struct mtp_object_handles *)(g_usbd_mtp.tx_buffer + sizeof(struct mtp_header));
    handles->ObjectHandle_len = 0;
    
    // 遍历对象池，查找符合条件的对象
    for (uint32_t i = 0; i < object_count; i++) {
        struct mtp_object *obj = &object_pool[i];
        
        if (obj->storage_id != storage_id) {
            MTP_LOGE_SHELL("invalid storage_id:0x%x", obj->storage_id);
            continue;
        }
        
        if (format_code != 0x0000 && obj->format != format_code) {
            MTP_LOGE_SHELL("invalid format_code:0x%x", obj->format);
            continue;
        }
        
        if (parent_handle != 0xFFFFFFFF && obj->parent_handle != parent_handle) {
            MTP_LOGE_SHELL("invalid parent_handle:0x%x", obj->parent_handle);
            continue;
        }
        
        if (handles->ObjectHandle_len < 255) {
            handles->ObjectHandle[handles->ObjectHandle_len++] = obj->handle;
        }
    }
    
    // 设置响应头
    struct mtp_header *resp = (struct mtp_header *)g_usbd_mtp.tx_buffer;
    resp->conlen = sizeof(struct mtp_header) + 4 + (handles->ObjectHandle_len * 4);
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
    
    offset = mtp_pack_string_with_zeroend(buffer, offset, src);
    
    // 确保不超过缓冲区
    if (offset > max_bytes) {
        MTP_LOGE_SHELL("Filename overflow");
        offset = max_bytes;
        buffer[offset-1] = 0;
        buffer[offset-2] = 0;
    }
    
    return offset;
}

// 获取对象信息
static int _mtp_get_object_info(uint32_t handle, struct mtp_object_info *info)
{
    struct mtp_object *obj = mtp_object_find(handle);
    if (!obj) {
        return -1;
    }

    // 获取文件状态
    struct mtp_stat st;
    if (usbd_mtp_fs_stat(obj->file_full_name, &st) != 0) {
        return -1;
    }

    // 填充对象信息
    memset(info, 0, sizeof(*info));
    info->StorageId = obj->storage_id;
    info->ObjectFormat = obj->format;
    info->ObjectCompressedSize = st.st_size;
    info->ParentObject = obj->parent_handle;
    info->AssociationType = obj->is_dir ? MTP_ASSOCIATION_TYPE_GENERIC_FOLDER : 0;
    
    // 优雅地设置文件名
    const char *name = strrchr(obj->file_full_name, '/');
    if (name) name++; else name = obj->file_full_name;
    
    uint32_t bytes_used = mtp_pack_object_filename(
        info->Filename, 
        CONFIG_USBDEV_MTP_MAX_PATHNAME, 
        name
    );
    
    // 设置文件名长度（字符数，不是字节数）
    info->Filename_len = bytes_used > 0 ? ((bytes_used - 3) / 2) : 0;
    
    // 设置时间戳（示例）
    mtp_format_time(st.st_mtime, (char *)info->ModificationDate);
    mtp_format_time(st.st_ctime, (char *)info->CaptureDate);
    
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
    
    // 在发送缓冲区中预留空间
    struct mtp_header *resp = (struct mtp_header *)g_usbd_mtp.tx_buffer;
    struct mtp_object_info *info = (struct mtp_object_info *)(resp + 1);
    
    // 获取对象信息
    if (_mtp_get_object_info(handle, info) != 0) {
        return mtp_send_response(MTP_RESPONSE_INVALID_OBJECT_HANDLE, hdr->trans_id);
    }
    
    // 计算实际数据长度（可能需要调整）
    size_t actual_len = sizeof(struct mtp_header) + sizeof(struct mtp_object_info);
    
    // 设置响应头
    resp->conlen = actual_len;
    resp->contype = MTP_CONTAINER_TYPE_DATA;
    resp->code = MTP_OPERATION_GET_OBJECT_INFO;
    resp->trans_id = hdr->trans_id;
    
    return usbd_mtp_start_write(g_usbd_mtp.tx_buffer, actual_len);
}

// 获取对象数据
static int mtp_get_object(struct mtp_header *hdr)
{
    if (hdr->conlen != sizeof(struct mtp_header) + 4) {
        return mtp_send_response(MTP_RESPONSE_INVALID_PARAMETER, hdr->trans_id);
    }

    uint32_t handle = hdr->param[0];
    struct mtp_object *obj = mtp_object_find(handle);
    
    if (!obj) {
        return mtp_send_response(MTP_RESPONSE_INVALID_OBJECT_HANDLE, hdr->trans_id);
    }
    
    // 打开文件
    int fd = usbd_mtp_fs_open(obj->file_full_name, MTP_FA_READ);
    if (fd < 0) {
        return mtp_send_response(MTP_RESPONSE_ACCESS_DENIED, hdr->trans_id);
    }
    
    // 发送响应头
    struct mtp_header *resp = (struct mtp_header *)g_usbd_mtp.tx_buffer;
    resp->conlen = sizeof(struct mtp_header),
    resp->contype = MTP_CONTAINER_TYPE_RESPONSE;
    resp->code = MTP_RESPONSE_OK;
    resp->trans_id = hdr->trans_id;
    
    if (usbd_mtp_start_write((uint8_t *)g_usbd_mtp.tx_buffer, sizeof(struct mtp_header)) != 0) {
        usbd_mtp_fs_close(fd);
        return -1;
    }
    
    // 设置当前操作对象
    g_usbd_mtp.cur_object = obj;
    
    // 开始发送文件数据
    return mtp_send_object_data(fd);
}

// 发送对象数据
int mtp_send_object_data(int fd)
{
    // 读取文件数据
    int len = usbd_mtp_fs_read(fd, g_usbd_mtp.tx_buffer, MTP_BUFFER_SIZE);
    if (len < 0) {
        usbd_mtp_fs_close(fd);
        return mtp_send_response(MTP_RESPONSE_GENERAL_ERROR, g_usbd_mtp.transaction_id);
    }
    
    // 发送数据
    if (usbd_mtp_start_write(g_usbd_mtp.tx_buffer, len) != 0) {
        usbd_mtp_fs_close(fd);
        return -1;
    }
    
    // 如果读取完毕，关闭文件
    if (len < MTP_BUFFER_SIZE) {
        usbd_mtp_fs_close(fd);
    }
    
    return 0;
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
        ret = usbd_mtp_fs_rmdir(obj->file_full_name);
    } else {
        ret = usbd_mtp_fs_unlink(obj->file_full_name);
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
    if (hdr->conlen < sizeof(struct mtp_header) + sizeof(struct mtp_object_info)) {
        return mtp_send_response(MTP_RESPONSE_INVALID_PARAMETER, hdr->trans_id);
    }

    // 解析对象信息
    struct mtp_object_info *info = (struct mtp_object_info *)(hdr + 1);
    
    // 创建新对象
    struct mtp_object *obj = mtp_object_add(info->ParentObject, 
                                           (char *)info->Filename, 
                                           info->ObjectFormat,
                                           info->AssociationType == MTP_ASSOCIATION_TYPE_GENERIC_FOLDER);
    
    if (!obj) {
        return mtp_send_response(MTP_RESPONSE_STORAGE_FULL, hdr->trans_id);
    }
    
    // 设置当前操作对象
    g_usbd_mtp.cur_object = obj;
    
    // 发送响应
    struct mtp_header_withparam {
        struct mtp_header header;
        uint32_t handle;
    } *resp = (struct mtp_header_withparam *)g_usbd_mtp.tx_buffer;

    resp->header.conlen = sizeof(struct mtp_header) + 4,
    resp->header.contype = MTP_CONTAINER_TYPE_RESPONSE;
    resp->header.code = MTP_RESPONSE_OK;
    resp->header.trans_id = hdr->trans_id,
    resp->handle = obj->handle;
    
    return usbd_mtp_start_write((uint8_t *)g_usbd_mtp.tx_buffer, resp->header.conlen);
}

// 发送对象数据
static int mtp_send_object(struct mtp_header *hdr)
{
    if (!g_usbd_mtp.cur_object) {
        return mtp_send_response(MTP_RESPONSE_INVALID_OBJECT_HANDLE, hdr->trans_id);
    }

    // 打开文件准备写入
    int fd = usbd_mtp_fs_open(g_usbd_mtp.cur_object->file_full_name, MTP_FA_WRITE | MTP_FA_CREATE_ALWAYS);
    if (fd < 0) {
        return mtp_send_response(MTP_RESPONSE_ACCESS_DENIED, hdr->trans_id);
    }
    
    // 写入数据
    int len = usbd_mtp_fs_write(fd, (hdr + 1), hdr->conlen - sizeof(struct mtp_header));
    usbd_mtp_fs_close(fd);
    
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
    if (hdr->conlen != sizeof(struct mtp_header) + sizeof(uint32_t)) {
        return mtp_send_response(MTP_RESPONSE_INVALID_PARAMETER, hdr->trans_id);
    }

    uint16_t prop_code = hdr->param[0];
    struct mtp_device_prop_desc *desc = (struct mtp_device_prop_desc *)(g_usbd_mtp.tx_buffer + sizeof(struct mtp_header));
    struct mtp_device_prop_desc_u16 *desc_16 = (struct mtp_device_prop_desc_u16 *)(g_usbd_mtp.tx_buffer + sizeof(struct mtp_header));
    struct mtp_device_prop_desc_u32 *desc_32 = (struct mtp_device_prop_desc_u32 *)(g_usbd_mtp.tx_buffer + sizeof(struct mtp_header));

    // 查找支持的设备属性
    const profile_property *prop = NULL;
    for (int i = 0; support_device_properties[i].prop_code != 0xFFFF; i++) {
        if (support_device_properties[i].prop_code == prop_code) {
            prop = &support_device_properties[i];
            break;
        }
    }
    
    if (!prop) {
        return mtp_send_response(MTP_RESPONSE_DEVICE_PROP_NOT_SUPPORTED, hdr->trans_id);
    }

    // 设置响应头
    struct mtp_header *resp = (struct mtp_header *)g_usbd_mtp.tx_buffer;
    resp->conlen = sizeof(struct mtp_header) + sizeof(struct mtp_device_prop_desc);
    resp->contype = MTP_CONTAINER_TYPE_DATA;
    resp->code = MTP_OPERATION_GET_DEVICE_PROP_DESC;
    resp->trans_id = hdr->trans_id;
    
    // 设置默认值和当前值
    switch (prop->data_type) {
        case MTP_TYPE_UINT8:
            MTP_LOGI_SHELL("MTP prop type : u8");
            memset(desc, 0, sizeof(*desc));
            desc->DevicePropertyCode = prop->prop_code;
            desc->DataType = prop->data_type;
            desc->GetSet = prop->getset;
            desc->DefaultValue[0] = (uint8_t)prop->default_value;
            desc->CurrentValue[0] = (uint8_t)prop->default_value;
            desc->FormFlag = prop->form_flag;
            resp->conlen = sizeof(struct mtp_header) + sizeof(struct mtp_device_prop_desc);
            break;
        case MTP_TYPE_UINT16:
            MTP_LOGI_SHELL("MTP prop type : u16");
            memset(desc_16, 0, sizeof(*desc_16));
            desc_16->DevicePropertyCode = prop->prop_code;
            desc_16->DataType = prop->data_type;
            desc_16->GetSet = prop->getset;
            desc_16->DefaultValue[0] = (uint16_t)prop->default_value;
            desc_16->CurrentValue[0] = (uint16_t)prop->default_value;
            desc_16->FormFlag = prop->form_flag;
            resp->conlen = sizeof(struct mtp_header) + sizeof(struct mtp_device_prop_desc_u16);
            break;
        case MTP_TYPE_UINT32:
            MTP_LOGI_SHELL("MTP prop type : u32");
            memset(desc_32, 0, sizeof(*desc_32));
            desc_32->DevicePropertyCode = prop->prop_code;
            desc_32->DataType = prop->data_type;
            desc_32->GetSet = prop->getset;
            desc_32->DefaultValue[0] = (uint32_t)prop->default_value;
            desc_32->CurrentValue[0] = (uint32_t)prop->default_value;
            desc_32->FormFlag = prop->form_flag;
            resp->conlen = sizeof(struct mtp_header) + sizeof(struct mtp_device_prop_desc_u32);
            break;
        case MTP_TYPE_STR:
        MTP_LOGI_SHELL("MTP prop type : str");
            // 字符串类型需要特殊处理
            break;
        default:
            break;
    }
    
    
    return usbd_mtp_start_write(g_usbd_mtp.tx_buffer, resp->conlen);
}

// 获取对象支持的属性列表
static int mtp_get_object_props_supported(struct mtp_header *hdr)
{
    if (hdr->conlen != sizeof(struct mtp_header) + 4) {
        return mtp_send_response(MTP_RESPONSE_INVALID_PARAMETER, hdr->trans_id);
    }

    uint16_t format_code = hdr->param[0];
    struct mtp_object_props_support *props = (struct mtp_object_props_support *)(g_usbd_mtp.tx_buffer + sizeof(struct mtp_header));
    
    MTP_LOGD_SHELL("check object prop support : 0x%x", format_code);

    // 查找支持的格式属性
    props->ObjectPropCode_len = 0;
    for (int i = 0; support_format_properties[i].format_code != 0xFFFF; i++) {
        if (support_format_properties[i].format_code == format_code) {
            uint16_t *prop_list = support_format_properties[i].properties;
            while (*prop_list != 0xFFFF) {
                props->ObjectPropCode[props->ObjectPropCode_len++] = *prop_list++;
            }
            break;
        }
    }
    
    // 设置响应头
    struct mtp_header *resp = (struct mtp_header *)g_usbd_mtp.tx_buffer;
    resp->conlen = sizeof(struct mtp_header) + 4 + (props->ObjectPropCode_len * 2);
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

    uint16_t prop_code = hdr->param[0];
    uint16_t format_code = hdr->param[1];
    
    MTP_LOGD_SHELL("Get object prop desc: prop_code=0x%04x, format_code=0x%04x", 
                  prop_code, format_code);

    // 查找支持的属性
    const profile_property *prop = NULL;
    for (int i = 0; support_object_properties[i].prop_code != 0xFFFF; i++) {
        if (support_object_properties[i].prop_code == prop_code && 
            (support_object_properties[i].format_code == format_code || 
             support_object_properties[i].format_code == 0xFFFF)) {
            prop = &support_object_properties[i];
            break;
        }
    }
    
    if (!prop) {
        MTP_LOGE_SHELL("Object property not supported: prop_code=0x%04x, format_code=0x%04x", 
                      prop_code, format_code);
        return mtp_send_response(MTP_RESPONSE_OBJECT_PROP_NOT_SUPPORTED, hdr->trans_id);
    }

    // 设置响应头
    struct mtp_header *resp = (struct mtp_header *)g_usbd_mtp.tx_buffer;
    // resp->conlen = sizeof(struct mtp_header) + sizeof(struct mtp_object_prop_desc);
    resp->contype = MTP_CONTAINER_TYPE_DATA;
    resp->code = MTP_OPERATION_GET_OBJECT_PROP_DESC;
    resp->trans_id = hdr->trans_id;
    
    // 填充属性描述
    struct mtp_object_prop_desc_u8 *desc_u8 = (struct mtp_object_prop_desc_u8 *)(resp + 1);
    struct mtp_object_prop_desc_u16 *desc_u16 = (struct mtp_object_prop_desc_u16 *)(resp + 1);
    struct mtp_object_prop_desc_u32 *desc_u32 = (struct mtp_object_prop_desc_u32 *)(resp + 1);

    // memset(desc, 0, sizeof(*desc));
    // desc->ObjectPropertyCode = prop->prop_code;
    // desc->DataType = prop->data_type;
    // desc->GetSet = prop->getset;
    // desc->GroupCode = prop->group_code;
    // desc->FormFlag = prop->form_flag;
    
    // 根据数据类型设置默认值
    switch (prop->data_type) {
        case MTP_TYPE_UINT8:
            memset(desc_u8, 0, sizeof(*desc_u8));
            desc_u8->ObjectPropertyCode = prop->prop_code;
            desc_u8->DataType = prop->data_type;
            desc_u8->GetSet = prop->getset;
            desc_u8->GroupCode = prop->group_code;
            desc_u8->FormFlag = prop->form_flag;
            desc_u8->DefValue = (uint8_t)prop->default_value;
            resp->conlen = sizeof(struct mtp_header) + sizeof(struct mtp_object_prop_desc_u8);
            break;
        case MTP_TYPE_UINT16:
            memset(desc_u16, 0, sizeof(*desc_u16));
            desc_u16->ObjectPropertyCode = prop->prop_code;
            desc_u16->DataType = prop->data_type;
            desc_u16->GetSet = prop->getset;
            desc_u16->GroupCode = prop->group_code;
            desc_u16->FormFlag = prop->form_flag;
            desc_u16->DefValue = (uint16_t)prop->default_value;
            resp->conlen = sizeof(struct mtp_header) + sizeof(struct mtp_object_prop_desc_u16);
            break;
        case MTP_TYPE_UINT32:
            memset(desc_u32, 0, sizeof(*desc_u32));
            desc_u32->ObjectPropertyCode = prop->prop_code;
            desc_u32->DataType = prop->data_type;
            desc_u32->GetSet = prop->getset;
            desc_u32->GroupCode = prop->group_code;
            desc_u32->FormFlag = prop->form_flag;
            desc_u32->DefValue = (uint32_t)prop->default_value;
            resp->conlen = sizeof(struct mtp_header) + sizeof(struct mtp_object_prop_desc_u32);
            break;
        default:
            MTP_LOGE_SHELL("Unsupported property data type: %d", prop->data_type);
            break;
    }
    
    return usbd_mtp_start_write(g_usbd_mtp.tx_buffer, resp->conlen);
}

static int mtp_get_object_prop_list(struct mtp_header *hdr)
{
    int ret = 0;
    /* 参数检查（最小要求：头部12字节 + 对象句柄4字节 + 属性代码4字节 = 20字节） */
    if (hdr->conlen < sizeof(struct mtp_header) + 8) {
        MTP_LOGE_SHELL("Invalid parameter length %d for GET_OBJECT_PROP_LIST (min 20 bytes required)", 
                      hdr->conlen);
        return mtp_send_response(MTP_RESPONSE_INVALID_PARAMETER, hdr->trans_id);
    }

    uint32_t handle = hdr->param[0];
    uint32_t prop_code = hdr->param[1];  // 0x0000表示请求所有属性
    uint32_t group_code = (hdr->conlen >= 24) ? hdr->param[2] : 0;
    uint32_t depth = (hdr->conlen >= 28) ? hdr->param[3] : 1;

    MTP_LOGD_SHELL("GET_OBJECT_PROP_LIST: handle=0x%08x, prop=0x%04x, group=0x%x, depth=%d",
                  handle, prop_code, group_code, depth);

    /* 查找对象 */
    struct mtp_object *obj = mtp_object_find(handle);
    if (!obj) {
        MTP_LOGE_SHELL("Object not found: handle=0x%08x", handle);
        return mtp_send_response(MTP_RESPONSE_INVALID_OBJECT_HANDLE, hdr->trans_id);
    }

    /* 获取增强版文件状态信息 */
    struct mtp_stat st;
    memset(&st, 0, sizeof(st));
    st.st_blksize = 512; // 默认块大小
    
    if (!obj->is_dir) {
        ret = usbd_mtp_fs_stat(obj->file_full_name, &st);
        if (ret != 0) {
            MTP_LOGE_SHELL("Failed to stat file '%s': %s", 
                         obj->file_full_name, mtp_show_error_string(ret));
            return mtp_send_response(MTP_RESPONSE_GENERAL_ERROR, hdr->trans_id);
        }
    } else {
        // 对目录设置默认值
        st.st_mode = 0040777; // 目录权限
        st.st_size = 0;
    }

    // 确保时间有效（使用对象创建时间作为回退）
    // if (st.st_mtime == 0) st.st_mtime = obj->modify_time;
    // if (st.st_ctime == 0) st.st_ctime = obj->create_time;

    /* 查找该格式支持的属性 */
    uint16_t *prop_list = NULL;
    for (int i = 0; support_format_properties[i].format_code != 0xFFFF; i++) {
        if (support_format_properties[i].format_code == obj->format) {
            prop_list = support_format_properties[i].properties;
            break;
        }
    }

    if (!prop_list) {
        MTP_LOGE_SHELL("No properties defined for format: 0x%04x", obj->format);
        return mtp_send_response(MTP_RESPONSE_OBJECT_PROP_NOT_SUPPORTED, hdr->trans_id);
    }

    /* 计算需要返回的属性数量 */
    uint32_t prop_count = 0;
    if (prop_code == 0) {
        /* 返回所有支持的属性 */
        while (prop_list[prop_count] != 0xFFFF) {
            prop_count++;
        }
    } else {
        /* 检查请求的特定属性是否支持 */
        for (int i = 0; prop_list[i] != 0xFFFF; i++) {
            if (prop_list[i] == prop_code) {
                prop_count = 1;
                break;
            }
        }
        if (prop_count == 0) {
            MTP_LOGE_SHELL("Property 0x%04x not supported for object 0x%08x", prop_code, handle);
            return mtp_send_response(MTP_RESPONSE_OBJECT_PROP_NOT_SUPPORTED, hdr->trans_id);
        }
    }

    /* 准备响应数据 */
    uint8_t *tx_buf = g_usbd_mtp.tx_buffer;
    uint32_t offset = sizeof(struct mtp_header);

    /* 写入属性数量 */
    *(uint32_t *)(tx_buf + offset) = prop_count;
    offset += 4;

    /* 填充每个属性的值 */
    for (uint32_t i = 0; i < prop_count; i++) {
        uint16_t current_prop = (prop_code == 0) ? prop_list[i] : (uint16_t)prop_code;
        struct mtp_object_prop_element *elem = (struct mtp_object_prop_element *)(tx_buf + offset);

        elem->ObjectHandle = handle;
        elem->PropertyCode = current_prop;

        /* 根据属性代码填充值 */
        switch (current_prop) {
            case MTP_PROPERTY_STORAGE_ID:
                elem->Datatype = MTP_TYPE_UINT32;
                *(uint32_t *)elem->value = obj->storage_id;
                MTP_LOGD_SHELL("Property StorageID: 0x%08x", obj->storage_id);
                break;

            case MTP_PROPERTY_OBJECT_FORMAT:
                elem->Datatype = MTP_TYPE_UINT16;
                *(uint16_t *)elem->value = obj->format;
                MTP_LOGD_SHELL("Property ObjectFormat: 0x%04x", obj->format);
                break;

            case MTP_PROPERTY_OBJECT_SIZE:
                elem->Datatype = MTP_TYPE_UINT64;
                *(uint64_t *)elem->value = obj->is_dir ? 0 : st.st_size;
                MTP_LOGD_SHELL("Property ObjectSize: %d bytes", obj->is_dir ? 0 : st.st_size);
                break;

            case MTP_PROPERTY_OBJECT_FILE_NAME: {
                const char *name = strrchr(obj->file_full_name, '/');
                if (!name) {
                    name = obj->file_full_name;
                } else {
                    // 对于根目录特殊处理
                    if (obj->handle == MTP_ROOT_HANDLE) {
                        name = ""; // 根目录显示为空名称
                    } else {
                        name++; // 跳过'/'
                    }
                }

                elem->Datatype = MTP_TYPE_STR;
                offset += offsetof(struct mtp_object_prop_element, value);
                offset = mtp_pack_string(tx_buf, offset, name);
                MTP_LOGD_SHELL("Property FileName: %s", name);
                continue; // Skip normal offset increment
            }

            case MTP_PROPERTY_PARENT_OBJECT:
                elem->Datatype = MTP_TYPE_UINT32;
                *(uint32_t *)elem->value = obj->parent_handle;
                MTP_LOGD_SHELL("Property ParentObject: 0x%08x", obj->parent_handle);
                break;

            case MTP_PROPERTY_PROTECTION_STATUS:
                elem->Datatype = MTP_TYPE_UINT16;
                *(uint16_t *)elem->value = (st.st_mode & 0222) ? 0 : 1; // 0=可写, 1=只读
                MTP_LOGD_SHELL("Property ProtectionStatus: %s", 
                             (st.st_mode & 0222) ? "Read-Write" : "Read-Only");
                break;

            case MTP_PROPERTY_DATE_MODIFIED: {
                elem->Datatype = MTP_TYPE_STR;
                char time_str[16];
                snprintf(time_str, sizeof(time_str), "%08X", st.st_mtime);
                offset += offsetof(struct mtp_object_prop_element, value);
                offset = mtp_pack_string(tx_buf, offset, time_str);
                MTP_LOGD_SHELL("Property DateModified: %s", time_str);
                continue;
            }

            case MTP_PROPERTY_DATE_CREATED: {
                elem->Datatype = MTP_TYPE_STR;
                char time_str[16];
                snprintf(time_str, sizeof(time_str), "%08X", st.st_ctime);
                offset += offsetof(struct mtp_object_prop_element, value);
                offset = mtp_pack_string(tx_buf, offset, time_str);
                MTP_LOGD_SHELL("Property DateCreated: %s", time_str);
                continue;
            }

            case MTP_PROPERTY_PERSISTENT_UID:
                elem->Datatype = MTP_TYPE_UINT128;
                memset(elem->value, 0, 16); // 暂时使用全0
                // 可以改进为基于文件inode生成唯一ID
                MTP_LOGD_SHELL("Property PersistentUID: (not implemented)");
                break;

            case MTP_PROPERTY_NAME: {
                const char *name = strrchr(obj->file_full_name, '/');
                if (!name) {
                    name = obj->file_full_name;
                } else {
                    // 对于根目录特殊处理
                    if (obj->handle == MTP_ROOT_HANDLE) {
                        name = ""; // 根目录显示为空名称
                    } else {
                        name++; // 跳过'/'
                    }
                }

                elem->Datatype = MTP_TYPE_STR;
                offset += offsetof(struct mtp_object_prop_element, value);
                offset = mtp_pack_string(tx_buf, offset, name);
                MTP_LOGD_SHELL("Property Name: %s", name);
                continue;
            }

            case MTP_PROPERTY_DISPLAY_NAME: {
                const char *name = strrchr(obj->file_full_name, '/');
                if (!name) {
                    name = obj->file_full_name;
                } else {
                    // 对于根目录特殊处理
                    if (obj->handle == MTP_ROOT_HANDLE) {
                        name = ""; // 根目录显示为空名称
                    } else {
                        name++; // 跳过'/'
                    }
                }

                elem->Datatype = MTP_TYPE_STR;
                offset += offsetof(struct mtp_object_prop_element, value);
                offset = mtp_pack_string(tx_buf, offset, name);
                MTP_LOGD_SHELL("Property DisplayName: %s", name);
                continue;
            }
            default:
                MTP_LOGW_SHELL("Unhandled property: 0x%04x (returning default value)", current_prop);
                elem->Datatype = MTP_TYPE_UINT32;
                *(uint32_t *)elem->value = 0;
                break;
        }

        offset += sizeof(struct mtp_object_prop_element);
    }

    /* 检查缓冲区溢出 */
    if (offset > MTP_BUFFER_SIZE) {
        MTP_LOGE_SHELL("Response too large (%d > %d)", offset, MTP_BUFFER_SIZE);
        return mtp_send_response(MTP_RESPONSE_INCOMPLETE_TRANSFER, hdr->trans_id);
    }

    /* 设置响应头 */
    struct mtp_header *resp_hdr = (struct mtp_header *)tx_buf;
    resp_hdr->conlen = offset;
    resp_hdr->contype = MTP_CONTAINER_TYPE_DATA;
    resp_hdr->code = MTP_OPERATION_GET_OBJECT_PROP_LIST;
    resp_hdr->trans_id = hdr->trans_id;

    MTP_LOGI_SHELL("Returning %d properties for object 0x%08x (total size: %d bytes)", 
                  prop_count, handle, resp_hdr->conlen);
    
    ret = usbd_mtp_start_write(tx_buf, resp_hdr->conlen);
    if (ret != 0) {
        MTP_LOGE_SHELL("Failed to send response: %d", ret);
        return ret;
    }

    return 0;
}

static void mtp_command_check(struct mtp_header *hdr)
{
    static uint32_t last_conlen = 0;
    static uint16_t last_contype = 0;
    static uint16_t last_code = 0;
    static uint32_t last_trans;

    if (hdr->conlen != last_conlen || hdr->contype != last_contype || hdr->code != last_code) {
        last_conlen = hdr->conlen;
        last_contype = hdr->contype;
        last_code = hdr->code;
        last_trans = 0;
    }
    else {
        last_trans++;
    }

    if (last_trans >= 5) {
        last_trans = 0;
        MTP_LOGE_SHELL("MTP command flood detected!!!!!!!!!!!!!!!!!!!");
    }
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

    MTP_LOGD_SHELL("recv mtp header, conlen : 0x%x, contype : 0x%x, code : 0x%x, trans_id : 0x%x", 
                            hdr->conlen, hdr->contype, hdr->code, hdr->trans_id);
    uint32_t param_num = (len - sizeof(struct mtp_header)) / sizeof(hdr->param[0]);
    for (uint32_t i = 0; i < param_num; i++) {
        MTP_LOGD_SHELL("param[%d] = 0x%x", i, hdr->param[i]);
    }

    mtp_command_check(hdr);

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
        default:
            MTP_LOGE_SHELL("Unsupported MTP operation: 0x%x", hdr->code);
            return mtp_send_response(MTP_RESPONSE_OPERATION_NOT_SUPPORTED, hdr->trans_id);
    }
}