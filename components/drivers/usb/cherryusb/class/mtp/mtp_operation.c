#include "mtp_operation.h"
#include "usbd_mtp_config.h"
#include "usbd_mtp.h"
#include "usb_mtp.h"
#include "usbd_mtp_support.h"
#include "mtp_filesystem.h"
#include <string.h>
#include "usbd_core.h"

#define MTP_STORAGE_ID          0xAAAA0001      // 存储ID定义
#define MTP_ROOT_HANDLE         0xBBBB0001      // 根目录句柄
#define MTP_ROOT_PARENT_HANDLE  0x00000000      // 根目录下文件的父句柄

#define MTP_XFER_BUFFER_SIZE    (3 + sizeof(struct mtp_header)) // 传输缓冲区大小，包含头部
#define MTP_XFER_PAYLOAD_SIZE   (MTP_BUFFER_SIZE - sizeof(struct mtp_header))

#define MTP_SCANNE_DIR_MAX_DEPTH  8               // 最大扫描目录深度

#define MTP_DIR_TRAVERSAL_DEPTH_MAX 32

static uint32_t g_mtp_storage_id_list[] = {
    MTP_STORAGE_ID,
    MTP_STORAGE_ID + 1,
};

typedef struct {
    uint32_t storage_id;
    const char *description;    // 文件系统描述
    const char *mount_point;    // MTP目录在文件系统中挂载的绝对路径
} mtp_storage_t;

static const mtp_storage_t g_disk_list[] = {
    {MTP_STORAGE_ID,     "SDCARD", "/sdcard"},
    {MTP_STORAGE_ID + 1, "FLASH",  "/flash"},
    {MTP_STORAGE_ID + 2, "RAM",    "/ram"},
    {0, NULL, NULL},
};

///////////////////////////////////////
//   接收大文件数据
///////////////////////////////////////
enum mtp_transfer_state {
    MTP_STATE_IDLE,
    MTP_XFER_HEADER_RECEIVED,  // 收到操作头
    MTP_XFER_DATA_RECEIVING,   // 数据接收中
    MTP_XFER_COMPLETE          // 传输完成
};

struct mtp_transfer_ctrl {
    uint32_t trans_id;
    uint32_t expected_size;
    uint32_t received_size;
    enum mtp_transfer_state state;
    uint32_t len;
    uint32_t tot_len;
    void *fp;
};

static struct mtp_transfer_ctrl g_mtp_data_transfer_ctrl = {0};

///////////////////////////////////////
//   接收大文件数据
///////////////////////////////////////
typedef enum {
    MTP_SEND_STATUS_IDLE,
    MTP_SEND_STATUS_HEADER,         // 收到操作头
    MTP_SEND_STATUS_SENDING,        // 数据接收中
    MTP_SEND_STATUS_COMPLETE        // 传输完成
} mtp_send_status;

typedef struct {
    mtp_send_status status;
    uint32_t trans_id;

    void *filename;

    uint32_t tot_len;
    uint32_t recv_len;
} mtp_send_ctrl;

static mtp_send_ctrl g_mtp_send_ctrl = {0};
static void mtp_send_ctrl_reset(void)
{
    g_mtp_send_ctrl.status = MTP_SEND_STATUS_IDLE;
    g_mtp_send_ctrl.tot_len = 0;
    g_mtp_send_ctrl.recv_len = 0;
    // trans_id不允许清零
}

///////////////////////////////////////
//   发送大文件数据
///////////////////////////////////////
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
    int (*function)(void *param);
    void *param;
    struct mtp_object *obj;
    ssize_t tx_count; // 当前发送字节数

    uint32_t total_len;
} mtp_transfer_ctrl_t;

static mtp_transfer_ctrl_t g_mtp_transfer_ctrl = {0};

// static const char *root_name = "ROOT";

const char *usbd_mtp_fs_description(uint8_t fs_disk_index)
{
    for (int i = 0; g_disk_list[i].description != NULL; i++) {
        if (i == fs_disk_index) {
            return g_disk_list[i].description;
        }
    }

    return NULL;
}

const char *usbd_mtp_fs_mount_path(uint8_t fs_disk_index)
{
    for (int i = 0; g_disk_list[i].mount_point != NULL; i++) {
        if (i == fs_disk_index) {
            return g_disk_list[i].mount_point;
        }
    }

    return NULL;
}

uint32_t usbd_mtp_storageid_from_mount_point(const char *full_path)
{
    for (int i = 0; g_disk_list[i].mount_point != NULL; i++) {
        size_t mount_len = strlen(g_disk_list[i].mount_point);
        if (strncmp(full_path, g_disk_list[i].mount_point, mount_len) == 0 && (full_path[0] == '/')) {
            return g_disk_list[i].storage_id;
        }
    }

    return 0;
}

const char *usbd_fs_top_mtp_path(void)
{
    return usbd_mtp_fs_mount_path(0);
}

#define MTP_PACK_UINT8_ARRAY(dest, offset, val) \
    (*(uint8_t *)((uint8_t *)dest + offset) = (uint8_t)(val), offset + sizeof(uint8_t))

#define MTP_PACK_UINT16_ARRAY(dest, offset, val) \
    (*(uint16_t *)((uint8_t *)dest + offset) = (uint16_t)(val), offset + sizeof(uint16_t))

#define MTP_PACK_UINT32_ARRAY(dest, offset, val) \
    (*(uint32_t *)((uint8_t *)dest + offset) = (uint32_t)(val), offset + sizeof(uint32_t))

static char mtp_current_path[CONFIG_USBDEV_MTP_MAX_PATHNAME] = {0};

// 对象句柄管理
static uint32_t object_count = 0;

extern int usbd_mtp_start_write(uint8_t *buf, uint32_t len);

// 通过扩展名获取文件类型描述
static uint16_t get_file_type_by_extension(const char *filename, bool is_dir)
{
    if (is_dir) {
        return MTP_FORMAT_ASSOCIATION; // 目录类型
    }

    if (!filename || !filename[0]) {
        return MTP_FORMAT_UNDEFINED; // 未知文件类型
    }

    const char *dot = strrchr(filename, '.');
    if (!dot || dot == filename) {
        return MTP_FORMAT_UNDEFINED;
    }

    for (int i = 0; support_format_extension[i].format != MTP_ARRAY_END_MARK; i++) {
        if (support_format_extension[i].extension == NULL) {
            continue;
        }
        if (strcmp(dot, support_format_extension[i].extension) == 0) {
            MTP_LOGD_SHELL("File: %s, Format: 0x%x", filename, support_format_extension[i].format);
            return support_format_extension[i].format;
        }
    }

    return MTP_FORMAT_UNDEFINED;
}

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

// 字符串打包上下文结构体
typedef struct {
    const char *str;        // 原始字符串指针
    uint32_t str_len;       // 字符串长度(字符数)
    uint32_t pos;           // 当前处理位置(字符索引)
    bool need_length_byte;  // 是否需要写入长度字节
    bool first_call;        // 是否是第一次调用
} mtp_string_packer_ctx_t;

/**
 * @brief 初始化字符串打包上下文
 * @param ctx 上下文指针
 * @param str 要打包的字符串
 * @note 如果str为NULL或空字符串，会初始化一个空字符串打包上下文
 */
static void mtp_pack_utf_16le_string_init(mtp_string_packer_ctx_t *ctx, const char *str)
{
    ctx->str = str;
    ctx->pos = 0;
    ctx->first_call = true;
    ctx->need_length_byte = true;
    
    // 计算字符串长度
    ctx->str_len = 0;
    if (str && str[0]) {
        const char *p = str;
        while (*p) { ctx->str_len++; p++; }
    }
}

/**
 * @brief 打包UTF-16LE字符串到缓冲区(分段处理)
 * @param ctx 打包上下文
 * @param buf 目标缓冲区
 * @param buf_size 缓冲区剩余大小(字节数)
 * @return 已使用的缓冲区字节数
 * @note 返回值可能小于buf_size，表示打包完成
 */
static uint32_t mtp_pack_utf_16le_string(mtp_string_packer_ctx_t *ctx, uint8_t *buf, uint32_t buf_size)
{
    if (!buf || buf_size == 0) {
        return 0;
    }
    
    uint32_t used = 0;  // 已使用的缓冲区字节数
    
    // 处理空字符串情况
    if (!ctx->str || ctx->str_len == 0) {
        if (ctx->first_call) {
            if (buf_size >= 1) {
                buf[0] = 0;  // 空字符串长度为0
                used = 1;
                ctx->first_call = false;
            }
        }
        return used;
    }
    
    // 第一次调用需要写入长度字节
    if (ctx->first_call && ctx->need_length_byte) {
        if (buf_size >= 1) {
            buf[0] = ctx->str_len + 1;  // UTF-16字符串长度(字符数+1表示结尾的null)
            used += 1;
            ctx->need_length_byte = false;
        } else {
            return 0;  // 缓冲区太小，连长度字节都放不下
        }
        ctx->first_call = false;
    }
    
    // 处理字符串内容
    while (ctx->pos < ctx->str_len && (buf_size - used) >= 2) {
        // 写入当前字符的UTF-16LE编码(低字节在前)
        buf[used++] = ctx->str[ctx->pos];    // ASCII字符或UTF-8的低字节
        buf[used++] = 0x00;                  // UTF-16LE高字节(对于ASCII是0)
        ctx->pos++;
    }
    
    // 检查是否已经处理完所有字符，需要写入结尾的null
    if (ctx->pos >= ctx->str_len && (buf_size - used) >= 2) {
        buf[used++] = 0x00;  // UTF-16LE null字符低字节
        buf[used++] = 0x00;  // UTF-16LE null字符高字节
        ctx->pos++;  // 标记为完成
    }
    
    return used;
}

/**
 * @brief 检查字符串打包是否完成
 * @param ctx 打包上下文
 * @return true如果打包完成，false如果还有数据需要处理
 */
static bool mtp_pack_utf_16le_is_end(mtp_string_packer_ctx_t *ctx)
{
    if (!ctx->str || ctx->str_len == 0) {
        return !ctx->first_call;  // 空字符串只需要一次调用就完成
    }
    return ctx->pos > ctx->str_len;  // 已经处理完所有字符和结尾null
}

static uint32_t mtp_pack_string_utf_16le_length(const char *str)
{
    uint32_t offset = 0;

    if (!str || !str[0]) {
        offset++;
        return offset;
    }
    uint8_t len = 0;
    const char *p = str;
    while (*p) { len++; p++; }
    offset++;
    for (uint8_t i = 0; i < len; i++) {
        offset++;
        offset++;
    }

    offset++;
    offset++;

    return offset;
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

typedef struct {
    bool utf_16le_half;
    uint32_t utf_16le_pos;
    uint32_t tot_len;
    char *str_addr;
} mtp_utf_16le_ctrl_t;

static void mtp_unpack_utf_16le_string_init(mtp_utf_16le_ctrl_t *ctrl, uint32_t str_exp_len, uint32_t str_max_len)
{
    ctrl->tot_len       = str_exp_len;
    ctrl->utf_16le_pos  = 0;
    ctrl->utf_16le_half = false;
    ctrl->str_addr      = usb_malloc(CONFIG_USBDEV_MTP_MAX_PATHNAME);
    memset(ctrl->str_addr, 0, CONFIG_USBDEV_MTP_MAX_PATHNAME);
}

static void mtp_unpack_utf_16le_string_deinit(mtp_utf_16le_ctrl_t *ctrl)
{
    if (ctrl->str_addr) {
        usb_free(ctrl->str_addr);
        ctrl->str_addr = NULL;
    }
}

static uint32_t mtp_unpack_utf_16le_string(mtp_utf_16le_ctrl_t *ctrl, uint8_t *src, uint32_t len)
{
    uint16_t *data_ptr = (uint16_t *)src;
    uint32_t name_start = 0;
    uint32_t utf_16le_pos_start = ctrl->utf_16le_pos;

    if (ctrl->utf_16le_half) {
        data_ptr = (uint16_t *)((uint8_t *)src + 1);
        ctrl->utf_16le_half = false;
    }

    // 提取文件名
    while ((name_start + 1 <= len - 1) && 
            ctrl->utf_16le_pos < CONFIG_USBDEV_MTP_MAX_PATHNAME - 1 && 
            ctrl->utf_16le_pos < ctrl->tot_len) {
        ctrl->str_addr[ctrl->utf_16le_pos] = (char)(data_ptr[ctrl->utf_16le_pos - utf_16le_pos_start] & 0xFF); // 取低8位作为ASCII
        ctrl->utf_16le_pos++;
        name_start += 2;
    }

    if (name_start + 1 > len - 1) {
        ctrl->str_addr[ctrl->utf_16le_pos] = ((uint8_t *)src)[len - 1];
        ctrl->utf_16le_pos++;
        ctrl->utf_16le_half = true;
    }

    ctrl->str_addr[ctrl->utf_16le_pos] = '\0';

    MTP_LOGD_SHELL("name tot len=%d, name pos=%d, name_start=%d", ctrl->tot_len, ctrl->utf_16le_pos, name_start);

    MTP_DUMP_SHELL(16, ctrl->str_addr, ctrl->utf_16le_pos);

    return ctrl->utf_16le_pos - utf_16le_pos_start;
}

static int mtp_unpack_utf_16le_is_end(mtp_utf_16le_ctrl_t *ctrl)
{
    return (ctrl->utf_16le_pos >= ctrl->tot_len);
}


static uint32_t simple_hash(const char *str)
{
    uint32_t hash = 0x811C9DC5;
    while (*str) {
        hash ^= *str++;
        hash *= 0x01000193;
    }
    return hash;
}

// FNV-1a哈希初始值
static uint64_t mtp_path_hash(const char *path)
{
#define FNV_64_INIT 0xCBF29CE484222325ULL
#define FNV_64_PRIME 0x100000001B3ULL

    uint64_t hash = FNV_64_INIT;
    for (int i = 0; path[i]; i++) {
        hash ^= (uint64_t)path[i];
        hash *= FNV_64_PRIME;
    }
    return hash;
#undef FNV_64_INIT
#undef FNV_64_PRIME
}

static uint64_t mtp_path_name_hash(const char *path, const char *name)
{
#define FNV_64_INIT 0xCBF29CE484222325ULL
#define FNV_64_PRIME 0x100000001B3ULL

    uint64_t hash = FNV_64_INIT;
    int path_len = strlen(path);
    
    for (int i = 0; i < path_len; i++) {
        hash ^= (uint64_t)path[i];
        hash *= FNV_64_PRIME;
    }
    
    // 只有当path不以'/'结尾时才添加路径分隔符
    if (path_len == 0 || path[path_len - 1] != '/') {
        hash ^= '/'; // 添加路径分隔符
        hash *= FNV_64_PRIME;
    }
    
    for (int i = 0; name[i]; i++) {
        hash ^= (uint64_t)name[i];
        hash *= FNV_64_PRIME;
    }
    return hash;
#undef FNV_64_INIT
#undef FNV_64_PRIME
}

uint32_t mtp_generate_handle(const char *path, uint32_t storage_id)
{
    // 特殊对象处理
    // if (strcmp(path, "/") == 0) return MTP_ROOT_HANDLE;
    // if (strcmp(path, "/Trash") == 0) return MTP_TRASH_HANDLE;

    if (strcmp(usbd_fs_top_mtp_path(), path) == 0) {
        return MTP_ROOT_PARENT_HANDLE;
    }

    // 组合存储ID和路径哈希（24位哈希）
    uint64_t hash = mtp_path_hash(path);
    return (storage_id << 24) | (hash & 0x00FFFFFF);
}

uint32_t mtp_generate_handle_with_path_name(const char *path, const char *name, uint32_t storage_id)
{
    // 特殊对象处理
    // if (strcmp(path, "/") == 0) return MTP_ROOT_HANDLE;
    // if (strcmp(path, "/Trash") == 0) return MTP_TRASH_HANDLE;

    // 组合存储ID和路径哈希（24位哈希）
    uint64_t hash = mtp_path_name_hash(path, name);
    return (storage_id << 24) | (hash & 0x00FFFFFF);
}

// 生成128位持久化UID
void mtp_generate_uid(uint8_t uid[16], uint32_t storage_id, uint32_t handle, const char *path)
{
    uint64_t path_hash = mtp_path_hash(path);
    
    // 结构布局（小端序）：
    // 0-3:   storage_id
    // 4-7:   handle
    // 8-15:  path_hash
    memcpy(uid, &storage_id, 4);
    memcpy(uid + 4, &handle, 4);
    memcpy(uid + 8, &path_hash, 8);
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

// 定义目录遍历回调函数类型
typedef bool (*mtp_dir_visitor)(const char *path, const char *name, bool is_dir, void *user_data);

typedef struct mtp_dir_traversal_node {
    char *full_path;
    void *dir_handle;
    int depth;
    struct mtp_dir_traversal_node *next;
} mtp_dir_traversal_node_t;

typedef struct {
    mtp_dir_traversal_node_t *head;
    mtp_dir_traversal_node_t *tail;
} mtp_dir_traversal_queue_t;

static void mtp_dir_traversal_queue_push(mtp_dir_traversal_queue_t *q, mtp_dir_traversal_node_t *node)
{
    node->next = NULL;
    if (!q->tail) {
        q->head = q->tail = node;
    } else {
        q->tail->next = node;
        q->tail = node;
    }
}

static mtp_dir_traversal_node_t *mtp_dir_traversal_queue_pop(mtp_dir_traversal_queue_t *q)
{
    if (!q->head)
        return NULL;
    mtp_dir_traversal_node_t *node = q->head;
    q->head = node->next;
    if (!q->head)
        q->tail = NULL;
    return node;
}

static int mtp_traverse_directory(const char *root_path, mtp_dir_visitor visitor, void *user_data, int max_depth)
{
    if (!root_path || root_path[0] != '/' || !visitor || max_depth < 0 || max_depth > MTP_DIR_TRAVERSAL_DEPTH_MAX) {
        MTP_LOGE_SHELL("Invalid params");
        return -1;
    }

    size_t root_len = strlen(root_path);
    if (root_len >= CONFIG_USBDEV_MTP_MAX_PATHNAME) {
        MTP_LOGE_SHELL("Path too long");
        return -1;
    }

    mtp_dir_traversal_queue_t queue = {0};
    mtp_dir_traversal_node_t *root = usb_malloc(sizeof(mtp_dir_traversal_node_t));
    root->full_path = usb_malloc(root_len + 1);
    strcpy(root->full_path, root_path);
    root->dir_handle = NULL;
    root->depth = 0;
    root->next = NULL;
    mtp_dir_traversal_queue_push(&queue, root);

    bool result = true;
    int ret = 0;

    MTP_LOGD_SHELL("Traversing directory: %s, max depth: %d", root_path, max_depth);

    while (queue.head && result) {
        mtp_dir_traversal_node_t *current = mtp_dir_traversal_queue_pop(&queue);

        if (current->depth > max_depth) {
            if (current->dir_handle) usbd_fs_closedir(current->dir_handle);
            usb_free(current->full_path);
            usb_free(current);
            continue;
        }

        if (!current->dir_handle) {
            current->dir_handle = usbd_fs_opendir(current->full_path);
            if (!current->dir_handle) {
                result = false;
                ret = -1;
                usb_free(current->full_path);
                usb_free(current);
                break;
            }
        }

        void *dent;
        while ((dent = usbd_fs_readdir(current->dir_handle)) != NULL && result) {
            const char *name = usbd_fs_name_from_dent(dent);
            if (!name || name[0] == '\0' || !strcmp(name, ".") || !strcmp(name, "..")) continue;

            bool is_dir = usbd_fs_is_dir_from_dent(dent);

            MTP_LOGD_SHELL("find file path: %s, name: %s, is_dir: %d", current->full_path, name, is_dir);

            if (!visitor(current->full_path, name, is_dir, user_data)) {
                result = false;
                ret = 0;
                break;
            }

            if (is_dir && current->depth + 1 < max_depth) {
                size_t new_path_len = strlen(current->full_path);
                size_t name_len = strlen(name);
                char *subdir_path = usb_malloc(new_path_len + 1 + name_len + 1);
                strcpy(subdir_path, current->full_path);
                if (new_path_len > 0 && subdir_path[new_path_len - 1] != '/') {
                    subdir_path[new_path_len] = '/';
                    subdir_path[new_path_len + 1] = '\0';
                    strcat(subdir_path, name);
                } else {
                    strcat(subdir_path, name);
                }

                mtp_dir_traversal_node_t *subdir = usb_malloc(sizeof(mtp_dir_traversal_node_t));
                subdir->full_path = subdir_path;
                subdir->dir_handle = NULL;
                subdir->depth = current->depth + 1;
                subdir->next = NULL;
                mtp_dir_traversal_queue_push(&queue, subdir);
            }
        }

        if (current->dir_handle) usbd_fs_closedir(current->dir_handle);
        usb_free(current->full_path);
        usb_free(current);
    }

    return ret;
}

static void mtp_fullname_concat(char *file_full_path, const char *path, const char *name)
{
    if (strcmp(path, "/") == 0) {
        snprintf(file_full_path, CONFIG_USBDEV_MTP_MAX_PATHNAME, "/%s", name);
    } else {
        snprintf(file_full_path, CONFIG_USBDEV_MTP_MAX_PATHNAME, "%s/%s", path, name);
    }
}

struct reverse_handle_ctx {
    uint32_t target_hash;
    uint32_t storage_id;
    bool found;
    struct mtp_object *obj;
};

static bool reverse_handle_visitor(const char *path, const char *name, bool is_dir, void *user_data)
{
    struct reverse_handle_ctx *ctx = (struct reverse_handle_ctx *)user_data;
    
    // 计算当前路径哈希
    uint32_t current_hash = mtp_path_name_hash(path, name) & 0x00FFFFFF;
    
    if (current_hash == ctx->target_hash) {
        uint32_t current_storage_id = MTP_STORAGE_ID;
        if ((current_storage_id >> 24) == (ctx->storage_id >> 24)) {

            ctx->found = true;

            mtp_fullname_concat(ctx->obj->file_full_path, path, name);

            ctx->obj->file_full_name = strstr(ctx->obj->file_full_path, name);
            ctx->obj->file_full_name_length = usb_strlen(name);
            ctx->obj->format = get_file_type_by_extension(ctx->obj->file_full_name, is_dir);
            ctx->obj->is_dir = is_dir;
            ctx->obj->parent_handle = mtp_generate_handle(path, ctx->obj->storage_id);
            
            return false; // 终止遍历
        }
    }
    return true; // 继续遍历
}

static struct mtp_object *mtp_object_new(struct mtp_object *parent_obj, const char *name, uint16_t format, bool is_dir)
{
    struct mtp_object *obj = usb_malloc(sizeof(struct mtp_object));
    memset(obj, 0, sizeof(*obj));
    obj->storage_id = MTP_STORAGE_ID;
    // obj->handle = MTP_ROOT_HANDLE + object_count; // 生成唯一句柄
    if (parent_obj) {
        obj->parent_handle = parent_obj->handle;
        snprintf(obj->file_full_path, CONFIG_USBDEV_MTP_MAX_PATHNAME, "%s/%s", parent_obj->file_full_path, name);
    }
    else {
        obj->parent_handle = MTP_ROOT_PARENT_HANDLE; // 无父对象
        if (strcmp(usbd_fs_top_mtp_path(), "/") == 0) {
            snprintf(obj->file_full_path, CONFIG_USBDEV_MTP_MAX_PATHNAME, "/%s", name);
        }
        else {
            snprintf(obj->file_full_path, CONFIG_USBDEV_MTP_MAX_PATHNAME, "%s/%s", usbd_fs_top_mtp_path(), name);
        }
    }

    obj->handle = mtp_generate_handle(obj->file_full_path, obj->storage_id);
    
    obj->format = format;
    obj->is_dir = is_dir;
    obj->file_full_name_length = usb_strlen(name);
    object_count++;

    // 分配内存给文件名
    obj->file_full_name = usb_malloc(obj->file_full_name_length + 1);
    if (obj->file_full_name) {
        usb_strncpy(obj->file_full_name, name, obj->file_full_name_length + 1);
    }

    MTP_LOGI_SHELL("create file name: %s, path: %s", 
                   obj->file_full_name ? obj->file_full_name : "NULL", obj->file_full_path);
    MTP_LOGI_SHELL("%15s %10s %10s %10s %10s",
                    "Object Name", "Storage ID", "Format", "Parent Handle", "Object Handle");
    MTP_LOGI_SHELL("%15s 0x%08X 0x%04X 0x%08X 0x%08X",
                    obj->file_full_name ? obj->file_full_name : "NULL", 
                    obj->storage_id, obj->format, obj->parent_handle, obj->handle);

    return obj;
}

struct mtp_object *mtp_obj_reverse_handle(uint32_t storage_id, uint32_t handle)
{
    // 参数验证
    if ((storage_id >> 24) != (MTP_STORAGE_ID >> 24)) {
        MTP_LOGE_SHELL("Invalid storage ID: 0x%08X", storage_id);
        return NULL;
    }

    struct mtp_object *obj = usb_malloc(sizeof(struct mtp_object));
    memset(obj, 0, sizeof(*obj));

    obj->handle = handle;
    obj->storage_id = storage_id;

    // 特殊句柄处理
    if (handle == MTP_ROOT_HANDLE) {
        snprintf(obj->file_full_path, CONFIG_USBDEV_MTP_MAX_PATHNAME, "%s", usbd_fs_top_mtp_path());
        obj->file_full_name = obj->file_full_path;
        obj->format = MTP_FORMAT_ASSOCIATION;
        obj->is_dir = true;
        obj->file_full_name_length = usb_strlen(usbd_fs_top_mtp_path());
        obj->parent_handle = MTP_ROOT_PARENT_HANDLE; // 默认根目录下
        goto __ret;
    }

    // 准备回调上下文
    struct reverse_handle_ctx ctx = {
        .target_hash = handle & 0x00FFFFFF,
        .storage_id = storage_id,
        .found = false,
        .obj = obj,
    };

    snprintf(mtp_current_path, CONFIG_USBDEV_MTP_MAX_PATHNAME, "%s", usbd_fs_top_mtp_path());

    mtp_traverse_directory(mtp_current_path, reverse_handle_visitor, &ctx, MTP_SCANNE_DIR_MAX_DEPTH);

    if (!ctx.found) {
        usb_free(obj);
        MTP_LOGD_SHELL("No path found for storage:0x%08X handle:0x%08X", storage_id, handle);
        return NULL;
    }

__ret:
    MTP_LOGI_SHELL("find file name: %s, path: %s", obj->file_full_name, obj->file_full_path);
    MTP_LOGI_SHELL("%15s %10s %10s %10s %10s",
                    "Name", "Storage ID", "Format", "Parent", "Handle");
    MTP_LOGI_SHELL("%15s 0x%08X 0x%04X 0x%08X 0x%08X",
                    obj->file_full_name, obj->storage_id, obj->format, obj->parent_handle, obj->handle);

    return obj;
}

static int mtp_write(uint8_t *data, uint32_t len, uint16_t contype, uint16_t code, uint32_t trans_id)
{
    struct mtp_header *resp = (struct mtp_header *)data;
    resp->conlen = len;
    resp->contype = contype;
    resp->code = code;
    resp->trans_id = trans_id;

    return usbd_mtp_start_write(data, len);
}

// 发送MTP响应
static int mtp_send_response(uint16_t code, uint32_t trans_id)
{
    return mtp_write(g_usbd_mtp.tx_buffer, sizeof(struct mtp_header), MTP_CONTAINER_TYPE_RESPONSE, code, trans_id);
}

static int mtp_send_data(uint8_t *data, uint32_t len, uint16_t contype, uint32_t trans_id)
{
    return mtp_write(data, len, contype, MTP_CONTAINER_TYPE_DATA, trans_id);
}

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
                // 清理当前事务ID，表示操作完成
                g_usbd_mtp.cur_trans_id = 0;
            }
            break;

        case MTP_TRANSFER_STATE_SENDING_DATA:
            MTP_LOGI_SHELL("Transfer state is sending data");
            if (g_mtp_transfer_ctrl.function) {
                ret = g_mtp_transfer_ctrl.function(g_mtp_transfer_ctrl.param);
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
    return mtp_write(tx_buf, offset, MTP_CONTAINER_TYPE_DATA, MTP_OPERATION_GET_DEVICE_INFO, hdr->trans_id);
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
    return mtp_write(g_usbd_mtp.tx_buffer, sizeof(struct mtp_header) + offset, MTP_CONTAINER_TYPE_DATA, MTP_OPERATION_GET_STORAGE_IDS, hdr->trans_id);
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
    const char *fs_mount_path = NULL;

    for (uint32_t i = 0; i < sizeof(g_mtp_storage_id_list) / sizeof(g_mtp_storage_id_list[0]); i++) {
        if (storage_id == g_mtp_storage_id_list[i]) {
            fs_name = usbd_mtp_fs_description(i);
            fs_mount_path = usbd_mtp_fs_mount_path(i);
            break;
        }
    }

    if (!fs_name || !fs_mount_path) {
        MTP_LOGE_SHELL("Invalid storage ID: 0x%08X", storage_id);
        return mtp_send_response(MTP_RESPONSE_INVALID_STORAGE_ID, hdr->trans_id);
    }

    struct mtp_statfs statfs_param;
    if (usbd_mtp_fs_statfs(fs_mount_path, &statfs_param)) {
        MTP_LOGE_SHELL("Failed to get filesystem stats for path: %s", fs_mount_path);
        return mtp_send_response(MTP_RESPONSE_INVALID_STORAGE_ID, hdr->trans_id);
    }

    void *dir_hdl = usbd_fs_opendir(fs_mount_path);
    if (dir_hdl == NULL) {
        if (usbd_fs_mkdir(fs_mount_path, 0777) < 0) {
            MTP_LOGE_SHELL("Failed to create root for path: %s", fs_mount_path);
            return mtp_send_response(MTP_RESPONSE_INVALID_STORAGE_ID, hdr->trans_id);
        }
    }
    else {
        usbd_fs_closedir(dir_hdl);
    }

    // 填充存储信息
    info->StorageType = MTP_STORAGE_FIXED_RAM;
    info->FilesystemType = MTP_STORAGE_FILESYSTEM_HIERARCHICAL;
    info->AccessCapability = MTP_STORAGE_READ_WRITE;
    info->MaxCapability = (uint64_t)(statfs_param.f_bsize * statfs_param.f_blocks);
    info->FreeSpaceInBytes = (uint64_t)(statfs_param.f_bsize * statfs_param.f_bfree);
    info->FreeSpaceInObjects = CONFIG_USBDEV_MTP_MAX_OBJECTS - object_count; // 计算剩余对象空间
    offset = mtp_pack_string_utf_16le(buffer, offset, fs_name);
    offset = mtp_pack_string_utf_16le(buffer, offset, fs_name);
    
    // 设置响应头
    return mtp_write(g_usbd_mtp.tx_buffer, sizeof(struct mtp_header) + offset, MTP_CONTAINER_TYPE_DATA, MTP_OPERATION_GET_STORAGE_INFO, hdr->trans_id);
}

// 上下文结构体用于回调传参
struct get_handles_ctx {
    uint32_t storage_id;
    uint16_t format_code;
    uint32_t target_handle;
    struct mtp_object_handles *handles;
    int max_handles;
};

// 从文件名获取格式代码
static uint16_t mtp_get_format_from_filename(const char *filename)
{
    const char *ext = strrchr(filename, '.');
    if (!ext) return MTP_FORMAT_UNDEFINED;

    if (usb_strcmp(ext, ".jpg") == 0 || usb_strcmp(ext, ".jpeg") == 0) {
        return MTP_FORMAT_EXIF_JPEG;
    } else if (usb_strcmp(ext, ".png") == 0) {
        return MTP_FORMAT_PNG;
    } else if (usb_strcmp(ext, ".txt") == 0) {
        return MTP_FORMAT_TEXT;
    }
    // 添加更多格式...
    MTP_LOGE_SHELL("Unsupported file format: %s", filename);
    return MTP_FORMAT_UNDEFINED;
}

// 获取父对象句柄
static uint32_t mtp_get_parent_handle(const char *path, uint32_t storage_id)
{
    char *parent_path = (char *)usb_malloc(CONFIG_USBDEV_MTP_MAX_PATHNAME + 1);
    usb_memset(parent_path, 0, CONFIG_USBDEV_MTP_MAX_PATHNAME + 1);

    snprintf(parent_path, CONFIG_USBDEV_MTP_MAX_PATHNAME, "%s", path);
    
    // 找到最后一个分隔符
    char *last_slash = strrchr(parent_path, '/');
    if (!last_slash || last_slash == parent_path) {
        usb_free(parent_path);
        return MTP_ROOT_PARENT_HANDLE; // 已经是根目录
    }
    
    // 截断得到父路径
    *last_slash = '\0';
    uint32_t handle = mtp_generate_handle(parent_path, storage_id);
    usb_free(parent_path);

    return handle;
}

static bool get_handles_visitor(const char *path, const char *name, bool is_dir, void *user_data)
{
    struct get_handles_ctx *ctx = (struct get_handles_ctx *)user_data;

    // 生成当前对象句柄（与创建时相同算法）
    uint32_t current_handle = mtp_generate_handle_with_path_name(path, name, ctx->storage_id);
    
    // 获取对象格式（目录使用MTP_FORMAT_ASSOCIATION）
    uint16_t format = is_dir ? MTP_FORMAT_ASSOCIATION : mtp_get_format_from_filename(name);
    
    // 获取父句柄（通过路径解析）
    // uint32_t parent_handle = mtp_get_parent_handle(path, ctx->storage_id);
    // uint32_t parent_handle = mtp_generate_handle(path, ctx->storage_id);

    MTP_LOGD_SHELL("calc parent_handle : 0x%08X, current_handle : 0x%08X", mtp_generate_handle(path, ctx->storage_id), current_handle);

    // 检查格式是否匹配
    if (ctx->format_code != 0x0000 && format != ctx->format_code) {
        MTP_LOGD_SHELL("format code not equal");
        return true; // 继续遍历但不添加
    }
    
    // 检查父句柄匹配
    if (ctx->target_handle != 0xFFFFFFFF && current_handle != ctx->target_handle) {
        MTP_LOGD_SHELL("current_handle code not equal 0x%08X, expected 0x%08X", current_handle, ctx->target_handle);
        // 特殊处理根目录下的对象
        if (!(ctx->target_handle == 0xFFFFFFFF && current_handle == MTP_ROOT_PARENT_HANDLE)) {
            MTP_LOGD_SHELL("current_handle code not equal return true");
            return true;
        }
    }

    // 添加到结果列表
    if (ctx->handles->ObjectHandle_len < ctx->max_handles) {
        ctx->handles->ObjectHandle[ctx->handles->ObjectHandle_len++] = current_handle;
        
        MTP_LOGD_SHELL("| %-20s | 0x%08X | 0x%04X | 0x%08X | 0x%08X |",
                      name, ctx->storage_id, format,
                       mtp_generate_handle(path, ctx->storage_id), current_handle);
    }

    return ctx->handles->ObjectHandle_len < ctx->max_handles; // 缓冲区满时终止
}

static bool get_handles_path_visitor(const char *path, const char *name, bool is_dir, void *user_data)
{
    struct get_handles_ctx *ctx = (struct get_handles_ctx *)user_data;
    uint32_t current_handle = mtp_generate_handle_with_path_name(path, name, ctx->storage_id);
    uint16_t format = is_dir ? MTP_FORMAT_ASSOCIATION : mtp_get_format_from_filename(name);
    // uint32_t parent_handle = mtp_generate_handle(path, ctx->storage_id);

    MTP_LOGD_SHELL("calc parent_handle : 0x%08X, current_handle : 0x%08X", mtp_generate_handle(path, ctx->storage_id), current_handle);

    // 检查格式是否匹配
    if (ctx->format_code != 0x0000 && format != ctx->format_code) {
        MTP_LOGD_SHELL("format code not equal");
        return true; // 继续遍历但不添加
    }
    
    // 检查父句柄匹配
    if (ctx->target_handle != 0xFFFFFFFF && current_handle != ctx->target_handle) {
        MTP_LOGD_SHELL("current_handle code not equal 0x%08X, expected 0x%08X", current_handle, ctx->target_handle);
        // 特殊处理根目录下的对象
        if (!(ctx->target_handle == 0xFFFFFFFF && current_handle == MTP_ROOT_PARENT_HANDLE)) {
            MTP_LOGD_SHELL("current_handle code not equal return true");
            return true;
        }
    }

    mtp_fullname_concat(mtp_current_path, path, name);

    return false; // 找到目标，停止遍历
}

static bool get_handles_visitor_list_all(const char *path, const char *name, bool is_dir, void *user_data)
{
    struct get_handles_ctx *ctx = (struct get_handles_ctx *)user_data;
    uint32_t current_handle = mtp_generate_handle_with_path_name(path, name, ctx->storage_id);
    // uint16_t format = is_dir ? MTP_FORMAT_ASSOCIATION : mtp_get_format_from_filename(name);
    // uint32_t parent_handle = mtp_generate_handle(path, ctx->storage_id);

    // 添加到结果列表
    if (ctx->handles->ObjectHandle_len < ctx->max_handles) {
        ctx->handles->ObjectHandle[ctx->handles->ObjectHandle_len++] = current_handle;
        
        MTP_LOGD_SHELL("| %-20s | 0x%08X | 0x%04X | 0x%08X | 0x%08X |",
                      name, ctx->storage_id, is_dir ? MTP_FORMAT_ASSOCIATION : mtp_get_format_from_filename(name),
                      mtp_generate_handle(path, ctx->storage_id), current_handle);
    }

    return ctx->handles->ObjectHandle_len < ctx->max_handles; // 缓冲区满时终止
}

static int mtp_get_object_handles(struct mtp_header *hdr)
{
    // 参数验证
    if (hdr->conlen != sizeof(struct mtp_header) + sizeof(uint32_t) * 3) {
        MTP_LOGE_SHELL("Invalid parameter length");
        return mtp_send_response(MTP_RESPONSE_INVALID_PARAMETER, hdr->trans_id);
    }

    // 解析参数
    uint32_t storage_id = hdr->param[0];
    uint16_t format_code = (uint16_t)hdr->param[1];
    uint32_t target_handle = hdr->param[2]; // 如果为0xFFFFFFFF表示根目录

    // 准备响应数据
    struct mtp_object_handles *handles = (struct mtp_object_handles *)(g_usbd_mtp.tx_buffer + sizeof(struct mtp_header));
    handles->ObjectHandle_len = 0;

    // 构建遍历上下文
    struct get_handles_ctx ctx = {
        .storage_id = storage_id,
        .format_code = format_code,
        .target_handle = target_handle,
        .handles = handles,
        .max_handles = 255 // MTP协议限制
    };
    
    MTP_LOGD_SHELL("Scanning storage:0x%08X format:0x%04X target_handle:0x%08X", storage_id, format_code, target_handle);

    // 确定起始路径
    if (target_handle == 0xFFFFFFFF || !mtp_current_path[0]) {
        snprintf(mtp_current_path, CONFIG_USBDEV_MTP_MAX_PATHNAME, "%s", usbd_fs_top_mtp_path());
        MTP_LOGD_SHELL("Setting current path to root: %s, rootpath: %s", mtp_current_path, usbd_fs_top_mtp_path());

        // 直接扫描根目录
        if (mtp_traverse_directory(mtp_current_path, get_handles_visitor, &ctx, 1)) {
            MTP_LOGE_SHELL("Failed to traverse directory");
            return mtp_send_response(MTP_RESPONSE_INVALID_PARAMETER, hdr->trans_id);
        }
    }
    else {
        if (mtp_traverse_directory(mtp_current_path, get_handles_path_visitor, &ctx, MTP_SCANNE_DIR_MAX_DEPTH)) {
            MTP_LOGE_SHELL("Failed to traverse directory");
            return mtp_send_response(MTP_RESPONSE_INVALID_PARAMETER, hdr->trans_id);
        }

        MTP_LOGD_SHELL("find path: %s", mtp_current_path);

        if (mtp_traverse_directory(mtp_current_path, get_handles_visitor_list_all, &ctx, 1)) {
            MTP_LOGE_SHELL("Failed to traverse directory");
            return mtp_send_response(MTP_RESPONSE_INVALID_PARAMETER, hdr->trans_id);
        }
    }

    MTP_LOGD_SHELL("Found %d object handles", handles->ObjectHandle_len);

    return mtp_write(g_usbd_mtp.tx_buffer, 
                     sizeof(struct mtp_header) + sizeof(handles->ObjectHandle_len) + (handles->ObjectHandle_len * sizeof(handles->ObjectHandle[0])),
                     MTP_CONTAINER_TYPE_DATA, MTP_OPERATION_GET_OBJECT_HANDLES, hdr->trans_id);
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

typedef struct {
    struct mtp_object *obj;
    uint32_t handle;
    mtp_string_packer_ctx_t string_ctx;
} mtp_get_object_info_param_t;

static int mtp_get_object_info_fsm(void *parameter)
{
    mtp_get_object_info_param_t *param = (mtp_get_object_info_param_t *)parameter;

    if (g_mtp_transfer_ctrl.state == MTP_TRANSFER_STATE_SENDING_DATA) {
        uint32_t used = 0;
        if (mtp_pack_utf_16le_is_end(&param->string_ctx)) {
            g_mtp_transfer_ctrl.state = MTP_TRANSFER_STATE_IDLE;
            MTP_LOGD_SHELL("send [%d] complete", g_mtp_transfer_ctrl.tx_count);
            usb_free(param->obj);
            return mtp_send_response(MTP_RESPONSE_OK, g_mtp_transfer_ctrl.trans_id);
        }
        else {
            used = mtp_pack_utf_16le_string(&param->string_ctx, g_usbd_mtp.tx_buffer, MTP_BUFFER_SIZE);
        }
        
        // 这里边界需要再多做一个处理，todo
        for (uint8_t i = 0; i < 6; i++) {
            used = MTP_PACK_UINT8_ARRAY(g_usbd_mtp.tx_buffer, used, 0x11);
        }

        for (uint8_t i = 0; i < 6; i++) {
            used = MTP_PACK_UINT8_ARRAY(g_usbd_mtp.tx_buffer, used, 0x22);
        }

        return mtp_write(g_usbd_mtp.tx_buffer, used, MTP_CONTAINER_TYPE_DATA, MTP_OPERATION_GET_OBJECT_INFO, g_mtp_transfer_ctrl.trans_id);
    }
    else {
        MTP_LOGE_SHELL("Invalid state in get_object_info_fsm: %d", g_mtp_transfer_ctrl.state);
    }
}

// 获取对象信息
static int mtp_get_object_info(struct mtp_header *hdr, uint32_t len)
{
    static mtp_get_object_info_param_t param = {0};

    if (hdr->conlen != sizeof(struct mtp_header) + sizeof(hdr->param[0])) {
        MTP_LOGE_SHELL("Invalid parameter length");
        return mtp_send_response(MTP_RESPONSE_INVALID_PARAMETER, hdr->trans_id);
    }

    if (g_mtp_transfer_ctrl.state != MTP_SEND_STATUS_IDLE) {
        MTP_LOGE_SHELL("Invalid ctrl status: %d", g_mtp_transfer_ctrl.state);
        return mtp_send_response(MTP_RESPONSE_ACCESS_DENIED, hdr->trans_id);
    }

    param.handle = hdr->param[0];

    // 在发送缓冲区中预留空间
    uint32_t used;
    struct mtp_header *resp = (struct mtp_header *)g_usbd_mtp.tx_buffer;
    struct mtp_object_info *info = (struct mtp_object_info *)(resp + 1);
    uint32_t offset = offsetof(struct mtp_object_info, Filename) + sizeof(struct mtp_header);

    struct mtp_object *obj = mtp_obj_reverse_handle(MTP_STORAGE_ID, param.handle);
    if (!obj) {
        return -1;
    }

    if (obj->format == MTP_FORMAT_ASSOCIATION) {
        info->ObjectCompressedSize = 0;
    }
    else {
        info->ObjectCompressedSize = 100;   // 临时测试
    }

    // 填充对象信息
    info->StorageId = obj->storage_id;
    info->ObjectFormat = obj->format;
    // info->ObjectCompressedSize = file_stat.st_size;
    info->ParentObject = obj->parent_handle;
    info->AssociationType = obj->is_dir ? MTP_ASSOCIATION_TYPE_GENERIC_FOLDER : 0;

    param.obj = obj;

    mtp_pack_utf_16le_string_init(&param.string_ctx, obj->file_full_name);

    used = mtp_pack_utf_16le_string(&param.string_ctx, g_usbd_mtp.tx_buffer + offset, MTP_BUFFER_SIZE - offset);

    usb_memset(&g_mtp_transfer_ctrl, 0, sizeof(mtp_transfer_ctrl_t));
    g_mtp_transfer_ctrl.trans_id = hdr->trans_id;
    g_mtp_transfer_ctrl.tx_count = 0;
    g_mtp_transfer_ctrl.function = mtp_get_object_info_fsm;
    g_mtp_transfer_ctrl.param = &param;
    
    g_mtp_transfer_ctrl.total_len = sizeof(struct mtp_header) + offsetof(struct mtp_object_info, Filename) +
                                    mtp_pack_string_utf_16le_length(obj->file_full_name) + 6 + 6;

    if (used + offset >= MTP_BUFFER_SIZE) {
        MTP_LOGD_SHELL("String too long, need multiple packets : %d %d", used, offset);
        g_mtp_transfer_ctrl.state = MTP_TRANSFER_STATE_SENDING_DATA;
    }
    
    return mtp_write(g_usbd_mtp.tx_buffer, used + offset, MTP_CONTAINER_TYPE_DATA, MTP_OPERATION_GET_OBJECT_INFO, g_mtp_transfer_ctrl.trans_id);
    
}

static int mtp_send_object_data(void *param)
{
    int ret;
    struct mtp_object *obj = g_mtp_transfer_ctrl.obj;

    g_mtp_transfer_ctrl.state = MTP_TRANSFER_STATE_SENDING_DATA;

    uint32_t chunk_size = (MTP_BUFFER_SIZE > UINT32_MAX) ? UINT32_MAX : MTP_BUFFER_SIZE;
    int len;

    if (g_mtp_transfer_ctrl.tx_count == 0) {
    chunk_size = (chunk_size > MTP_XFER_PAYLOAD_SIZE) ? MTP_XFER_PAYLOAD_SIZE : chunk_size;
        len = usbd_mtp_fs_read_file(g_mtp_transfer_ctrl.fp, g_usbd_mtp.tx_buffer + sizeof(struct mtp_header), chunk_size);
    }
    else {
        len = usbd_mtp_fs_read_file(g_mtp_transfer_ctrl.fp, g_usbd_mtp.tx_buffer, chunk_size);
    }

    MTP_LOGD_SHELL("file read %d %d", len, chunk_size);

    if (len < 0) {
        g_mtp_transfer_ctrl.state = MTP_TRANSFER_STATE_IDLE;
        MTP_LOGE_SHELL("File read error: %s", obj->file_full_path);
        usbd_mtp_fs_close_file(g_mtp_transfer_ctrl.fp);
        usb_free(obj);
        ret = mtp_send_response(MTP_RESPONSE_INCOMPLETE_TRANSFER, g_mtp_transfer_ctrl.trans_id);
    }
    else if (len == 0) {
        g_mtp_transfer_ctrl.state = MTP_TRANSFER_STATE_SENDING_RESPONSE;
        MTP_LOGI_SHELL("File read [%d] complete: %s", g_mtp_transfer_ctrl.tx_count, obj->file_full_path);
        // 文件读取完成，发送响应
        usbd_mtp_fs_close_file(g_mtp_transfer_ctrl.fp);
        usb_free(obj);
        ret = mtp_send_response(MTP_RESPONSE_OK, g_mtp_transfer_ctrl.trans_id);
    }
    else {
        if (g_mtp_transfer_ctrl.tx_count == 0) {
        g_mtp_transfer_ctrl.tx_count += len;

            struct mtp_header *resp = (struct mtp_header *)g_usbd_mtp.tx_buffer;
            resp->conlen = sizeof(struct mtp_header) + obj->file_size;
            resp->contype = MTP_CONTAINER_TYPE_DATA;
            resp->code = MTP_OPERATION_GET_OBJECT;
            resp->trans_id = g_mtp_transfer_ctrl.trans_id;

            ret = usbd_mtp_start_write(g_usbd_mtp.tx_buffer, sizeof(struct mtp_header) + len);

        }
        else {
            g_mtp_transfer_ctrl.tx_count += len;
            ret = usbd_mtp_start_write(g_usbd_mtp.tx_buffer, len);
        }
        
        MTP_LOGD_SHELL("Sending object data: %s, current send=%d, total send=%d", obj->file_full_path, len, g_mtp_transfer_ctrl.tx_count);

        if (ret) {
            MTP_LOGE_SHELL("Failed to start write for object data: %s", obj->file_full_path);
            g_mtp_transfer_ctrl.state = MTP_TRANSFER_STATE_IDLE;
            usb_free(obj);
            usbd_mtp_fs_close_file(g_mtp_transfer_ctrl.fp);
        }
    }

    if (ret) {
        MTP_LOGE_SHELL("Failed to start write for object data: %s", obj->file_full_path);
        g_mtp_transfer_ctrl.state = MTP_TRANSFER_STATE_IDLE;
        usb_free(obj);
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
    struct mtp_object *obj = mtp_obj_reverse_handle(MTP_STORAGE_ID, handle);

    // 2. 对象验证
    if (!obj) {
        MTP_LOGE_SHELL("Invalid object handle: 0x%08X", handle);
        return mtp_send_response(MTP_RESPONSE_INVALID_OBJECT_HANDLE, hdr->trans_id);
    }
    
    if (obj->is_dir) {
        MTP_LOGE_SHELL("Cannot get directory object data: 0x%08X", handle);
        usb_free(obj);
        return mtp_send_response(MTP_RESPONSE_INVALID_OBJECT_HANDLE, hdr->trans_id);
    }

    // 3. 打开文件
    void *fp = usbd_mtp_fs_open_file(obj->file_full_path, "r+");
    if (!fp) {
        MTP_LOGE_SHELL("File open failed: %s", obj->file_full_path);
        usb_free(obj);
        return mtp_send_response(MTP_RESPONSE_ACCESS_DENIED, hdr->trans_id);
    }

    // 4. 获取文件大小并更新对象信息
    obj->file_size = (uint32_t)usbd_mtp_fs_size(obj->file_full_path);
    if (obj->file_size == 0) {
        usbd_mtp_fs_close_file(fp);
        MTP_LOGE_SHELL("File is empty: %s", obj->file_full_path);
        usb_free(obj);
        return mtp_send_response(MTP_RESPONSE_INVALID_OBJECT_HANDLE, hdr->trans_id);
    }

    MTP_LOGD_SHELL("object file size = %d", obj->file_size);

    // 5. 根据文件大小选择发送策略
    if (obj->file_size <= MTP_XFER_PAYLOAD_SIZE) {
        // 小文件策略：头和体合并发送
        int len = usbd_mtp_fs_read_file(fp, g_usbd_mtp.tx_buffer + sizeof(struct mtp_header), obj->file_size);
        if (len != obj->file_size) {
            usbd_mtp_fs_close_file(fp);
            MTP_LOGE_SHELL("File read error: expected %d, got %d", obj->file_size, len);
            usb_free(obj);
            return mtp_send_response(MTP_RESPONSE_INCOMPLETE_TRANSFER, hdr->trans_id);
        }

        usbd_mtp_fs_close_file(fp);
        usb_free(obj);
        return mtp_write(g_usbd_mtp.tx_buffer, sizeof(struct mtp_header) + obj->file_size, MTP_CONTAINER_TYPE_DATA, MTP_OPERATION_GET_OBJECT, hdr->trans_id);
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
        g_mtp_transfer_ctrl.param = NULL;

        return mtp_send_object_data(NULL);
    }
}

uint32_t mtp_handle_get_from_fullpath(const char *fullpath)
{
    uint32_t storage_id = usbd_mtp_storageid_from_mount_point(fullpath);
    if (storage_id == 0) {
        return 0;
    }

    return mtp_generate_handle(fullpath, storage_id);
}

uint32_t mtp_parent_handle_get_from_fullpath(const char *fullpath)
{
    uint32_t storage_id = usbd_mtp_storageid_from_mount_point(fullpath);
    if (storage_id == 0) {
        return 0;
    }

    // 提取父目录路径
    char *parent_path = usb_malloc(CONFIG_USBDEV_MTP_MAX_PATHNAME + 1);
    const char *last_slash = strrchr(fullpath, '/');
    
    if (last_slash == NULL || last_slash == fullpath) {
        // 如果没有找到斜杠，或者斜杠在开头，父目录就是根目录
        strcpy(parent_path, "/");
    } else {
        // 复制到最后一个斜杠之前的部分作为父目录路径
        size_t parent_len = last_slash - fullpath;
        snprintf(parent_path, parent_len, "%s", fullpath);
        parent_path[parent_len] = '\0';
        
        // 如果父目录路径为空，说明父目录是根目录
        if (parent_path[0] == '\0') {
            strcpy(parent_path, "/");
        }
    }

    if (strcmp(usbd_fs_top_mtp_path(), parent_path) == 0) {
        usb_free(parent_path);
        return MTP_ROOT_HANDLE;
    }

    MTP_LOGI_SHELL("parent_path: %s, storage_id: 0x%08X", parent_path, storage_id);

    uint32_t handle = mtp_generate_handle(parent_path, storage_id);
    usb_free(parent_path);
    return handle;
}

// int mtp_delete_obj(uint32_t handle)
// {
//     struct mtp_object *obj = mtp_obj_reverse_handle(MTP_STORAGE_ID, handle);
//     if (!obj) {
//         MTP_LOGD_SHELL("Object not found: 0x%08X", handle);
//         return 0;
//     }
    
//     // 删除文件或目录
//     int ret;
//     if (obj->is_dir) {
//         ret = usbd_mtp_fs_rmdir(obj->file_full_path);
//     } else {
//         ret = usbd_mtp_fs_rm_file(obj->file_full_path);
//     }

//     usb_free(obj);

//     return 0;
// }

// 删除对象
static int mtp_delete_object(struct mtp_header *hdr)
{
    if (hdr->conlen < sizeof(struct mtp_header) + sizeof(hdr->param[0])) {
        MTP_LOGE_SHELL("Invalid parameter length");
        return mtp_send_response(MTP_RESPONSE_INVALID_PARAMETER, hdr->trans_id);
    }

    uint32_t handle = hdr->param[0];
    struct mtp_object *obj = mtp_obj_reverse_handle(MTP_STORAGE_ID, handle);
    if (!obj) {
        MTP_LOGD_SHELL("Object not found: 0x%08X", handle);
        return mtp_send_response(MTP_RESPONSE_INVALID_OBJECT_HANDLE, hdr->trans_id);
    }
    
    // 删除文件或目录
    int ret;
    if (obj->is_dir) {
        ret = usbd_mtp_fs_rmdir_recursive(obj->file_full_path);
    } else {
        ret = usbd_mtp_fs_rm_file(obj->file_full_path);
    }

    usb_free(obj);

    if (ret != 0) {
        MTP_LOGE_SHELL("Failed to delete object: %s", obj->file_full_path);
        return mtp_send_response(MTP_RESPONSE_ACCESS_DENIED, hdr->trans_id);
    }
    
    return mtp_send_response(MTP_RESPONSE_OK, hdr->trans_id);
}

typedef struct {
    uint32_t storage_id;
    uint32_t parent_handle;
    uint16_t obj_format;

    mtp_utf_16le_ctrl_t utf16le_name_ctrl;

} mtp_send_object_info_param_t;

static void mtp_send_object_info_clear(mtp_send_object_info_param_t *param)
{
    mtp_unpack_utf_16le_string_deinit(&param->utf16le_name_ctrl);

    usb_memset(param, 0, sizeof(mtp_send_object_info_param_t));
}

// 发送对象信息（由于存在长文件名的情况，所以发送可能会分包）
static int mtp_send_object_info(struct mtp_header *hdr, uint32_t len)
{
    uint32_t name_start = 0;

    struct mtp_object_info *obj_info = NULL;

    static mtp_send_object_info_param_t trans_param = {0};

    bool is_dir;
    struct mtp_object *parent_obj;
    struct mtp_object *obj;

    if (g_mtp_send_ctrl.status == MTP_SEND_STATUS_IDLE) {
        MTP_LOGD_SHELL("MTP_SEND_STATUS_IDLE");
        if (hdr->conlen != sizeof(struct mtp_header) + sizeof(hdr->param[0]) * 2) {
        MTP_LOGE_SHELL("Invalid parameter length");
        return mtp_send_response(MTP_RESPONSE_INVALID_PARAMETER, hdr->trans_id);
    }

        mtp_send_object_info_clear(&trans_param);

        trans_param.storage_id = hdr->param[0];
        trans_param.parent_handle = hdr->param[1];

        if (trans_param.storage_id != MTP_STORAGE_ID) {
            MTP_LOGE_SHELL("Invalid storage ID: 0x%08X", trans_param.storage_id);
        return mtp_send_response(MTP_RESPONSE_INVALID_STORAGE_ID, hdr->trans_id);
    }

        g_mtp_send_ctrl.status = MTP_SEND_STATUS_HEADER;

        MTP_LOGD_SHELL("mtp send obj info : storage_id=0x%08X, parent_handle=0x%08X", trans_param.storage_id, trans_param.parent_handle);

        return 0;
    }
    else if (g_mtp_send_ctrl.status == MTP_SEND_STATUS_HEADER) {
        MTP_LOGD_SHELL("MTP_SEND_STATUS_HEADER");
        name_start = sizeof(struct mtp_header) + offsetof(struct mtp_object_info, Filename);

        // 非法的数据包
        if (hdr->conlen <= name_start) {
            MTP_LOGE_SHELL("Invalid parameter length");
            mtp_send_ctrl_reset();
            mtp_send_object_info_clear(&trans_param);
            return mtp_send_response(MTP_RESPONSE_INVALID_PARAMETER, hdr->trans_id);
        }

        if (len <= name_start) {
            MTP_LOGE_SHELL("Invalid parameter length");
            mtp_send_ctrl_reset();
            mtp_send_object_info_clear(&trans_param);
            return mtp_send_response(MTP_RESPONSE_INVALID_PARAMETER, hdr->trans_id);
        }

        obj_info = (struct mtp_object_info *)(hdr + 1);
    if (obj_info->Filename_len == 0 || obj_info->Filename[0] == 0) {
        MTP_LOGE_SHELL("Invalid filename length");
        return mtp_send_response(MTP_RESPONSE_INVALID_PARAMETER, hdr->trans_id);
    }

        g_mtp_send_ctrl.tot_len  = hdr->conlen;
        g_mtp_send_ctrl.recv_len = len;
        g_mtp_send_ctrl.trans_id = hdr->trans_id;

        trans_param.obj_format = obj_info->ObjectFormat;

        mtp_unpack_utf_16le_string_init(&trans_param.utf16le_name_ctrl, obj_info->Filename_len, CONFIG_USBDEV_MTP_MAX_PATHNAME);

        mtp_unpack_utf_16le_string(&trans_param.utf16le_name_ctrl, (uint8_t *)hdr + name_start, len - name_start);

        // obj_info已经全部接收完
        if (g_mtp_send_ctrl.recv_len < g_mtp_send_ctrl.tot_len) {
            g_mtp_send_ctrl.status = MTP_SEND_STATUS_SENDING;
            return 0;
        }
        else {
            MTP_LOGD_SHELL("recv ok, ");
        }

        goto __trans_ok;
    }
    else if (g_mtp_send_ctrl.status == MTP_SEND_STATUS_SENDING) {
        // 继续接收文件名（可能收到多个512字节的包，直到收完）
        g_mtp_send_ctrl.recv_len += len;
        name_start = 0;

        if (!mtp_unpack_utf_16le_is_end(&trans_param.utf16le_name_ctrl)) {
            mtp_unpack_utf_16le_string(&trans_param.utf16le_name_ctrl, (uint8_t *)hdr + name_start, len - name_start);
    }

        if (g_mtp_send_ctrl.recv_len < g_mtp_send_ctrl.tot_len) {
            // keep receiving
            return 0;
        }

        MTP_LOGD_SHELL("recv ok, ");

        goto __trans_ok;
    }

__trans_ok:
    // 创建新对象
    is_dir = (trans_param.obj_format == MTP_FORMAT_ASSOCIATION);
    parent_obj = NULL;
    
    // 如果有父句柄，查找父对象
    if (trans_param.parent_handle != 0xFFFFFFFF) {
        parent_obj = mtp_obj_reverse_handle(trans_param.storage_id, trans_param.parent_handle);
        if (!parent_obj) {
            MTP_LOGE_SHELL("Parent object not found: 0x%08X", trans_param.parent_handle);
            mtp_send_ctrl_reset();
            mtp_send_object_info_clear(&trans_param);
            return mtp_send_response(MTP_RESPONSE_INVALID_OBJECT_HANDLE, g_mtp_send_ctrl.trans_id);
        }
    }
    
    obj = mtp_object_new(parent_obj, trans_param.utf16le_name_ctrl.str_addr, trans_param.obj_format, is_dir);
    if (!obj) {
        MTP_LOGE_SHELL("Failed to create object");
        if (parent_obj) {
            usb_free(parent_obj);
        }
        mtp_send_ctrl_reset();
        mtp_send_object_info_clear(&trans_param);
        return mtp_send_response(MTP_RESPONSE_STORAGE_FULL, g_mtp_send_ctrl.trans_id);
    }

    // 设置当前操作对象
    g_usbd_mtp.cur_object = obj;
    g_usbd_mtp.cur_trans_id = g_mtp_send_ctrl.trans_id;

    // 创建响应：返回存储ID、父句柄和新创建的对象句柄
    uint8_t *tx_buffer = (uint8_t *)(g_usbd_mtp.tx_buffer);
    uint32_t offset = sizeof(struct mtp_header);
    
    offset = MTP_PACK_UINT32_ARRAY(tx_buffer, offset, trans_param.storage_id);
    offset = MTP_PACK_UINT32_ARRAY(tx_buffer, offset, trans_param.parent_handle);
    offset = MTP_PACK_UINT32_ARRAY(tx_buffer, offset, obj->handle);
    
    // 设置传输状态为IDLE，这样在发送完成后会自动发送OK响应
    g_mtp_transfer_ctrl.state = MTP_TRANSFER_STATE_IDLE;
    
    // 清理父对象临时数据
    if (parent_obj) {
        usb_free(parent_obj);
    }

    if (is_dir) {
        if (usbd_fs_mkdir(obj->file_full_path, 0777) < 0) {
            MTP_LOGE_SHELL("Failed to create directory: %s", obj->file_full_path);
            usb_free(obj);
            g_usbd_mtp.cur_object = NULL;
            mtp_send_ctrl_reset();
            mtp_send_object_info_clear(&trans_param);
            return mtp_send_response(MTP_RESPONSE_STORAGE_FULL, g_mtp_send_ctrl.trans_id);
        }
        MTP_LOGD_SHELL("Created directory: %s", obj->file_full_path);
    }

    mtp_send_ctrl_reset();
    mtp_send_object_info_clear(&trans_param);
    return mtp_write(g_usbd_mtp.tx_buffer, offset, MTP_CONTAINER_TYPE_RESPONSE, MTP_RESPONSE_OK, g_mtp_send_ctrl.trans_id);
}

static inline void mtp_send_object_param_init(void)
{
    usb_free(g_usbd_mtp.cur_object);
    g_usbd_mtp.cur_object = NULL;
    g_mtp_data_transfer_ctrl.state = MTP_STATE_IDLE;
}

// 发送对象数据
static int mtp_send_object_data2(struct mtp_header *hdr, uint32_t len)
{
    if (!g_usbd_mtp.cur_object) {
        g_mtp_data_transfer_ctrl.state = MTP_STATE_IDLE;
        MTP_LOGE_SHELL("object is null");
        return mtp_send_response(MTP_RESPONSE_INVALID_OBJECT_HANDLE, hdr->trans_id);
    }

    if (g_mtp_data_transfer_ctrl.state != MTP_STATE_IDLE &&
        g_mtp_data_transfer_ctrl.state != MTP_XFER_HEADER_RECEIVED &&
        g_mtp_data_transfer_ctrl.state != MTP_XFER_DATA_RECEIVING)
    {
        mtp_send_object_param_init();
        return mtp_send_response(MTP_RESPONSE_TRANSACTION_CANCELLED, hdr->trans_id);
    }

    if (g_mtp_data_transfer_ctrl.state == MTP_STATE_IDLE) {

        MTP_LOGD_SHELL("MTP_STATE_IDLE");

        if (len != sizeof(struct mtp_header) || len != hdr->conlen) {
            MTP_LOGE_SHELL("Invalid parameter length");
            return mtp_send_response(MTP_RESPONSE_INVALID_PARAMETER, hdr->trans_id);
        }

        MTP_LOGI_SHELL("recv object data : len = %d payload len=%d", hdr->conlen, hdr->conlen - sizeof(struct mtp_header));

        g_mtp_data_transfer_ctrl.fp = usbd_mtp_fs_open_file(g_usbd_mtp.cur_object->file_full_path, "w+");
        if (!g_mtp_data_transfer_ctrl.fp) {
            mtp_send_object_param_init();
            MTP_LOGE_SHELL("Failed to open file");
            return mtp_send_response(MTP_RESPONSE_ACCESS_DENIED, hdr->trans_id);
        }

        // 初始化传输控制块
        g_mtp_data_transfer_ctrl.trans_id = hdr->trans_id;
        g_mtp_data_transfer_ctrl.state = MTP_XFER_HEADER_RECEIVED;

        return 0;
    }

    int recv_len;

    if (g_mtp_data_transfer_ctrl.state == MTP_XFER_HEADER_RECEIVED) {
        if (g_mtp_data_transfer_ctrl.trans_id != hdr->trans_id) {
            g_mtp_data_transfer_ctrl.state = MTP_STATE_IDLE;
            MTP_LOGE_SHELL("Transaction ID mismatch");
            return mtp_send_response(MTP_RESPONSE_TRANSACTION_CANCELLED, hdr->trans_id);
        }

        recv_len = usbd_mtp_fs_write_file(g_mtp_data_transfer_ctrl.fp, (hdr + 1), len - sizeof(struct mtp_header));

        // MTP_LOGI_SHELL("recv object data : len =%d payload len=%d", hdr->conlen, hdr->conlen - sizeof(struct mtp_header));
    }
    else {
        recv_len = usbd_mtp_fs_write_file(g_mtp_data_transfer_ctrl.fp, (hdr), len);

        // MTP_LOGI_SHELL("recv object data : len =%d payload len=%d", hdr->conlen, hdr->conlen - sizeof(struct mtp_header));
    }

    if (recv_len < 0) {
        MTP_LOGE_SHELL("Failed to write file");
        usbd_mtp_fs_close_file(g_mtp_data_transfer_ctrl.fp);
        mtp_send_object_param_init();
        return mtp_send_response(MTP_RESPONSE_STORAGE_FULL, hdr->trans_id);
    }

    if (g_mtp_data_transfer_ctrl.state == MTP_XFER_HEADER_RECEIVED) {
        g_mtp_data_transfer_ctrl.tot_len = hdr->conlen;
        g_mtp_data_transfer_ctrl.len = len;
        g_usbd_mtp.cur_object->file_size = recv_len;
    }
    else {
        g_mtp_data_transfer_ctrl.len += len;
        g_usbd_mtp.cur_object->file_size += recv_len;
    }

    MTP_LOGD_SHELL("current write %d bytes, tot write %d bytes, tot = %d", recv_len, g_mtp_data_transfer_ctrl.len, g_mtp_data_transfer_ctrl.tot_len);

    if (g_mtp_data_transfer_ctrl.len >= g_mtp_data_transfer_ctrl.tot_len) {
        usbd_mtp_fs_close_file(g_mtp_data_transfer_ctrl.fp);
        mtp_send_object_param_init();

        MTP_LOGI_SHELL("write ok, tot write %d bytes", g_mtp_data_transfer_ctrl.tot_len - sizeof(struct mtp_header));

        return mtp_send_response(MTP_RESPONSE_OK, hdr->trans_id);
    }
    else {
        if (g_mtp_data_transfer_ctrl.state == MTP_XFER_HEADER_RECEIVED) {
            g_mtp_data_transfer_ctrl.state = MTP_XFER_DATA_RECEIVING;
        }
    }

    return 0;
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
    return mtp_write(g_usbd_mtp.tx_buffer, sizeof(struct mtp_header) + offset, MTP_CONTAINER_TYPE_DATA, MTP_OPERATION_GET_DEVICE_PROP_DESC, hdr->trans_id);
}

// 获取对象支持的属性列表
static int mtp_get_object_props_supported(uint8_t *tx_buffer, struct mtp_header *hdr)
{
    if (hdr->conlen != sizeof(struct mtp_header) + sizeof(hdr->param[0])) {
        MTP_LOGE_SHELL("Invalid parameter length for get object props supported");
        return mtp_send_response(MTP_RESPONSE_INVALID_PARAMETER, hdr->trans_id);
    }

    uint16_t format_code = (uint16_t)(hdr->param[0] & 0xFFFF);
    struct mtp_object_props_support *props = (struct mtp_object_props_support *)(tx_buffer + sizeof(struct mtp_header));
    
    MTP_LOGD_SHELL("check object prop format support : 0x%x", format_code);

    // 查找支持的格式属性
    props->ObjectPropCode_len = 0;
    for (int i = 0; support_format_properties[i].format_code != MTP_ARRAY_END_MARK; i++) {
        if (support_format_properties[i].format_code == format_code) {
            uint16_t *prop_list = support_format_properties[i].properties;
            MTP_LOGRAW_SHELL("found supported object property : ", *prop_list);
            while (*prop_list != MTP_ARRAY_END_MARK) {
                MTP_LOGRAW_SHELL("0x%04X ", *prop_list);
                props->ObjectPropCode[props->ObjectPropCode_len++] = *prop_list++;
            }
            MTP_LOGRAW_SHELL("\r\n");
            break;
        }
    }

    uint32_t tx_length = sizeof(struct mtp_header) + sizeof(props->ObjectPropCode_len) + (props->ObjectPropCode_len * sizeof(props->ObjectPropCode[0]));

    return mtp_write(tx_buffer, tx_length, MTP_CONTAINER_TYPE_DATA, MTP_OPERATION_GET_OBJECT_PROPS_SUPPORTED, hdr->trans_id);
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
    return mtp_write(g_usbd_mtp.tx_buffer, 
                     sizeof(struct mtp_header) + offset, 
                     MTP_CONTAINER_TYPE_DATA, 
                     MTP_OPERATION_GET_OBJECT_PROP_DESC, 
                     hdr->trans_id);
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

static uint32_t mtp_fill_property_value_length(const struct mtp_object *obj, uint16_t prop_code, uint8_t *buf, uint32_t offset, uint16_t *data_type)
{
    uint32_t length = 0;

    switch (prop_code) {
        case MTP_PROPERTY_STORAGE_ID:
            length += sizeof(uint32_t);
            break;

        case MTP_PROPERTY_OBJECT_FORMAT:
            length += sizeof(uint16_t);
            break;

        case MTP_PROPERTY_OBJECT_SIZE:
            length += sizeof(uint32_t);
            length += sizeof(uint32_t);
            break;

        case MTP_PROPERTY_OBJECT_FILE_NAME:
            length += mtp_pack_string_utf_16le_length(mtp_get_object_name(obj));
            // MTP_DUMP_SHELL(16, mtp_get_object_name(obj), usb_strlen(mtp_get_object_name(obj)));
            break;
        case MTP_PROPERTY_NAME:
            length += mtp_pack_string_utf_16le_length(mtp_get_base_name(obj));
            // MTP_DUMP_SHELL(16, mtp_get_base_name(obj), usb_strlen(mtp_get_base_name(obj)));
            break;
        case MTP_PROPERTY_DISPLAY_NAME:
            length += mtp_pack_string_utf_16le_length(mtp_get_display_name(obj));
            // MTP_DUMP_SHELL(16, mtp_get_display_name(obj), usb_strlen(mtp_get_display_name(obj)));
            break;

        case MTP_PROPERTY_PARENT_OBJECT:
            length += sizeof(uint32_t);
            break;

        case MTP_PROPERTY_PROTECTION_STATUS:
            length += sizeof(uint16_t);
            break;

        case MTP_PROPERTY_DATE_MODIFIED: {
            length += mtp_pack_string_utf_16le_length(usbd_mtp_fs_modify_time(obj->file_full_path));
            break;
        }

        case MTP_PROPERTY_DATE_CREATED: {
            length += mtp_pack_string_utf_16le_length(usbd_mtp_fs_create_time(obj->file_full_path));
            break;
        }

        case MTP_PROPERTY_PERSISTENT_UID:
            length += 16;
            break;

        default:
            length += sizeof(uint32_t);
            break;
    }
    return length;
}

// 注意：这里面的数据长度一旦超过，会出问题，需要增加边界检测
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
            uint8_t uid[16] = {0};
            mtp_generate_uid(uid, MTP_STORAGE_ID, obj->handle, obj->file_full_name);
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

typedef struct {
    uint8_t *buf;
    uint32_t length;
    uint32_t offset;
} mtp_prop_list_node_t;

typedef struct {
    struct mtp_object *obj;
    const uint16_t *prop_list;
    uint32_t prop_count;
    uint32_t handle;
    uint16_t prop_code;
    uint32_t trans_id;
    bool request_all_props;

    mtp_prop_list_node_t *prop_list_node;
    uint32_t prop_list_cur_node;

    bool all_sent;

    uint32_t total_len;
} mtp_get_object_prop_list_t;

static mtp_get_object_prop_list_t g_mtp_get_object_prop_list_param = {0};

static int mtp_get_object_prop_list_send(void *param)
{
    mtp_get_object_prop_list_t *mtp_get_object_prop_list_ptr = (mtp_get_object_prop_list_t *)param;

    const uint16_t *prop_list = mtp_get_object_prop_list_ptr->prop_list;
    struct mtp_object *obj    = mtp_get_object_prop_list_ptr->obj;
    uint32_t prop_count       = mtp_get_object_prop_list_ptr->prop_count;
    uint32_t handle           = mtp_get_object_prop_list_ptr->handle;
    uint16_t prop_code        = mtp_get_object_prop_list_ptr->prop_code;
    uint32_t trans_id         = mtp_get_object_prop_list_ptr->trans_id;
    bool request_all_props    = mtp_get_object_prop_list_ptr->request_all_props;
    mtp_prop_list_node_t *prop_list_node = mtp_get_object_prop_list_ptr->prop_list_node;
    uint32_t cur_node = 0;

    // 写入属性数量
    uint8_t *tx_buf  = g_usbd_mtp.tx_buffer;
    uint32_t offset = sizeof(struct mtp_header);
    struct mtp_object_prop_list *elem_list = (struct mtp_object_prop_list *)(tx_buf + offset);
    elem_list->element_len = prop_count;
    offset += offsetof(struct mtp_object_prop_list, element);

    MTP_LOGD_SHELL("Request prob count : %d", prop_count);

    // MTP_LOGD_SHELL("222222----------------- %d --------------", tot_len);

    uint16_t current_prop;
    uint16_t data_type;
    uint32_t tx_counter = 0;
    uint32_t tx_remain;

    if (g_mtp_transfer_ctrl.state == MTP_TRANSFER_STATE_IDLE) {
        struct mtp_object_prop_element *elem;
        struct mtp_object_prop_list *elem_list = (struct mtp_object_prop_list *)(tx_buf + sizeof(struct mtp_header));
        elem_list->element_len = prop_count;
        tx_counter = sizeof(struct mtp_header) + offsetof(struct mtp_object_prop_list, element);

        if (request_all_props) {
            for (uint32_t i = 0; i < prop_count; i++) {
                current_prop = prop_list[i];
                elem = (struct mtp_object_prop_element *)prop_list_node[i].buf;

                mtp_fill_property_value(obj, current_prop, prop_list_node[i].buf, offsetof(struct mtp_object_prop_element, value), &data_type);
                elem->ObjectHandle = handle;
                elem->PropertyCode = current_prop;
                elem->Datatype = data_type;
                // MTP_DUMP_SHELL(16, prop_list_node[i].buf, prop_list_node[i].length);
            }
        }
        else {
            current_prop = prop_code;
            elem = (struct mtp_object_prop_element *)prop_list_node[0].buf;

            mtp_fill_property_value(obj, current_prop, prop_list_node[0].buf, offsetof(struct mtp_object_prop_element, value), &data_type);
            elem->ObjectHandle = handle;
            elem->PropertyCode = current_prop;
            elem->Datatype = data_type;

            // MTP_DUMP_SHELL(16, prop_list_node[0].buf, prop_list_node[0].length);
        }

        mtp_get_object_prop_list_ptr->prop_list_cur_node = 0;
        mtp_get_object_prop_list_ptr->all_sent = false;
        uint32_t cur_node = mtp_get_object_prop_list_ptr->prop_list_cur_node;
        uint32_t total_len = tx_counter + mtp_get_object_prop_list_ptr->total_len;

        for (uint32_t i = 0; i < prop_count; i++) {
            tx_remain = MTP_BUFFER_SIZE - tx_counter;

            // 当前节点已经发送完
            if (tx_remain >= prop_list_node[i].length) {
                usb_memcpy(tx_buf + tx_counter, prop_list_node[i].buf, prop_list_node[i].length);
                tx_counter += prop_list_node[i].length;
                prop_list_node[i].offset = prop_list_node[i].length;
                cur_node = i + 1;

                if (i + 1 == prop_count) {
                    mtp_get_object_prop_list_ptr->all_sent = true;
                    MTP_LOGI_SHELL("All properties sent");
                }
            }
            // 还未发送完
            else {
                usb_memcpy(tx_buf + tx_counter, prop_list_node[i].buf, tx_remain);
                tx_counter += tx_remain;
                prop_list_node[i].offset = tx_remain;
                cur_node = i;
                // MTP_LOGI_SHELL("Partial property sent, node=%d, remain=%d", i, prop_list_node[i].length - prop_list_node[i].offset);
                // MTP_DUMP_SHELL(16, prop_list_node[i].buf + prop_list_node[i].offset, prop_list_node[i].length - prop_list_node[i].offset);
            }

            if (tx_counter >= MTP_BUFFER_SIZE) {
                break;
            }
        }

        mtp_get_object_prop_list_ptr->prop_list_cur_node = cur_node;

        g_mtp_transfer_ctrl.state = MTP_TRANSFER_STATE_SENDING_DATA;

        struct mtp_header *resp = (struct mtp_header *)g_usbd_mtp.tx_buffer;
        resp->conlen = total_len;
        resp->contype = MTP_CONTAINER_TYPE_DATA;
        resp->code = MTP_OPERATION_GET_OBJECT_PROP_LIST;
        resp->trans_id = trans_id;

        return usbd_mtp_start_write(g_usbd_mtp.tx_buffer, tx_counter);
        // return mtp_write(g_usbd_mtp.tx_buffer, tx_counter, MTP_CONTAINER_TYPE_DATA, MTP_OPERATION_GET_OBJECT_PROP_LIST, trans_id);
    }
    else if (g_mtp_transfer_ctrl.state == MTP_TRANSFER_STATE_SENDING_DATA) 
    {
        if (mtp_get_object_prop_list_ptr->all_sent) {
            for (uint32_t i = 0; i < prop_count; i++) {
                usb_free(prop_list_node[i].buf);
            }
            usb_free(prop_list_node);
            usb_free(obj);
            MTP_LOGD_SHELL("All properties sent");
            g_mtp_transfer_ctrl.state = MTP_TRANSFER_STATE_SENDING_RESPONSE;
            return mtp_send_response(MTP_RESPONSE_OK, trans_id);
        }
        
        cur_node = mtp_get_object_prop_list_ptr->prop_list_cur_node;
        tx_counter = 0;

        uint32_t start = cur_node;

        for (uint32_t i = start; i < prop_count; i++) {
            tx_remain = MTP_BUFFER_SIZE - tx_counter;

            // 当前节点已经发送完
            if (tx_remain >= prop_list_node[i].length - prop_list_node[i].offset) {
                usb_memcpy(tx_buf + tx_counter, prop_list_node[i].buf + prop_list_node[i].offset, prop_list_node[i].length - prop_list_node[i].offset);
                tx_counter += prop_list_node[i].length - prop_list_node[i].offset;
                prop_list_node[i].offset = prop_list_node[i].length;
                cur_node = i + 1;

                if (i + 1 == prop_count) {
                    mtp_get_object_prop_list_ptr->all_sent = true;
                    MTP_LOGI_SHELL("All properties sent");
                }
            }
            // 还未发送完
            else {
                usb_memcpy(tx_buf + tx_counter, prop_list_node[i].buf + prop_list_node[i].offset, tx_remain);
                tx_counter += tx_remain;
                prop_list_node[i].offset += tx_remain;
                cur_node = i;
                // MTP_LOGI_SHELL("Partial property sent, node=%d, remain=%d", i, prop_list_node[i].length - prop_list_node[i].offset);
                // MTP_DUMP_SHELL(16, prop_list_node[i].buf + prop_list_node[i].offset, prop_list_node[i].length - prop_list_node[i].offset);
            }

            if (tx_counter >= MTP_BUFFER_SIZE) {
                break;
            }
        }

        mtp_get_object_prop_list_ptr->prop_list_cur_node = cur_node;

        return usbd_mtp_start_write(g_usbd_mtp.tx_buffer, tx_counter);

        // return mtp_write(g_usbd_mtp.tx_buffer, tx_counter, MTP_CONTAINER_TYPE_DATA, MTP_OPERATION_GET_OBJECT_PROP_LIST, trans_id);
    }
    else {
        MTP_LOGE_SHELL("Invalid transfer state %d", g_mtp_transfer_ctrl.state);
        return mtp_send_response(MTP_RESPONSE_GENERAL_ERROR, trans_id);
    }
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

    /* 检测请求类型 */
    is_windows_special_request(hdr->param, &handle, &prop_code, &group_code, &depth, &format_code);

    struct mtp_object *obj = mtp_obj_reverse_handle(MTP_STORAGE_ID, handle);
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
        usb_free(obj);
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
        MTP_LOGE_SHELL("Property not supported: prop_code=0x%04X, format_code=0x%04X", prop_code, obj->format);
        usb_free(obj);
        return mtp_send_response(MTP_RESPONSE_OBJECT_PROP_NOT_SUPPORTED, hdr->trans_id);
    }

    usb_memset(&g_mtp_transfer_ctrl, 0, sizeof(mtp_transfer_ctrl_t));
    g_mtp_transfer_ctrl.obj = obj;
    g_mtp_transfer_ctrl.trans_id = hdr->trans_id;
    g_mtp_transfer_ctrl.tx_count = 0;
    g_mtp_transfer_ctrl.function = mtp_get_object_prop_list_send;
    g_mtp_transfer_ctrl.param = &g_mtp_get_object_prop_list_param;
    g_mtp_transfer_ctrl.state = MTP_TRANSFER_STATE_IDLE;

    g_mtp_get_object_prop_list_param.obj = obj;
    g_mtp_get_object_prop_list_param.prop_list = prop_list;
    g_mtp_get_object_prop_list_param.prop_count = prop_count;
    g_mtp_get_object_prop_list_param.handle = handle;
    g_mtp_get_object_prop_list_param.prop_code = prop_code;
    g_mtp_get_object_prop_list_param.trans_id = hdr->trans_id;
    g_mtp_get_object_prop_list_param.request_all_props = request_all_props;

    g_mtp_get_object_prop_list_param.prop_list_node = usb_malloc(sizeof(mtp_prop_list_node_t) * prop_count);
    usb_memset(g_mtp_get_object_prop_list_param.prop_list_node, 0, sizeof(mtp_prop_list_node_t) * prop_count);

    uint16_t current_prop;
    uint32_t total_len = 0;
    /* 处理属性请求 */
    if (request_all_props) {
        for (uint32_t i = 0; i < prop_count; i++) {
            current_prop = prop_list[i];
            g_mtp_get_object_prop_list_param.prop_list_node[i].length = offsetof(struct mtp_object_prop_element, value);
            g_mtp_get_object_prop_list_param.prop_list_node[i].length += mtp_fill_property_value_length(obj, current_prop, NULL, 0, NULL);
            g_mtp_get_object_prop_list_param.prop_list_node[i].buf = usb_malloc(g_mtp_get_object_prop_list_param.prop_list_node[i].length);
            total_len += g_mtp_get_object_prop_list_param.prop_list_node[i].length;
        }
    }
    else {
        current_prop = prop_code;
        g_mtp_get_object_prop_list_param.prop_list_node[0].length = offsetof(struct mtp_object_prop_element, value);
        g_mtp_get_object_prop_list_param.prop_list_node[0].length += mtp_fill_property_value_length(obj, current_prop, NULL, 0, NULL);
        g_mtp_get_object_prop_list_param.prop_list_node[0].buf = usb_malloc(g_mtp_get_object_prop_list_param.prop_list_node[0].length);
        total_len += g_mtp_get_object_prop_list_param.prop_list_node[0].length;
    }

    MTP_LOGI_SHELL(" ------------------------------ Total property data length: %d bytes", total_len);

    g_mtp_get_object_prop_list_param.total_len = total_len;

    return mtp_get_object_prop_list_send(&g_mtp_get_object_prop_list_param);
}

struct reverse_handle_ctx2 {
    struct mtp_object_handles *handles;
    uint32_t storage_id;
    uint32_t max_handles;
};

static bool get_handles_visitor_list_all2(const char *path, const char *name, bool is_dir, void *user_data)
{
    struct reverse_handle_ctx2 *ctx = (struct reverse_handle_ctx2 *)user_data;
    uint32_t current_handle = mtp_generate_handle_with_path_name(path, name, ctx->storage_id);

    MTP_LOGD_SHELL("Traversing path: %s, name: %s, is_dir: %d, handle: 0x%08X", path, name, is_dir, current_handle);

    // 添加到结果列表
    if (ctx->handles->ObjectHandle_len < ctx->max_handles) {
        ctx->handles->ObjectHandle[ctx->handles->ObjectHandle_len++] = current_handle;
    }

    return ctx->handles->ObjectHandle_len < ctx->max_handles; // 缓冲区满时终止
}

static int mtp_get_object_references(struct mtp_header *hdr)
{
    if (hdr->conlen != sizeof(struct mtp_header) + sizeof(hdr->param[0])) {
        MTP_LOGE_SHELL("Invalid parameter length");
        return mtp_send_response(MTP_RESPONSE_INVALID_PARAMETER, hdr->trans_id);
    }

    uint32_t handle = hdr->param[0];
    struct mtp_object *obj = mtp_obj_reverse_handle(MTP_STORAGE_ID, handle);
    if (!obj) {
        MTP_LOGE_SHELL("Object not found: handle=0x%08X", handle);
        return mtp_send_response(MTP_RESPONSE_INVALID_OBJECT_HANDLE, hdr->trans_id);
    }

    // 准备响应数据
    struct mtp_object_handles *handles = (struct mtp_object_handles *)(g_usbd_mtp.tx_buffer + sizeof(struct mtp_header));
    handles->ObjectHandle_len = 0;

    // 如果是目录对象，返回其包含的文件对象句柄
    if (obj->is_dir) {
        struct reverse_handle_ctx2 ctx = {
            .handles = handles,
            .storage_id = obj->storage_id,
            .max_handles = 255 // 限制最大句柄数量
        };

        mtp_traverse_directory(obj->file_full_path, get_handles_visitor_list_all2, &ctx, 1);
    } else {
        // 对于普通文件，通常没有关联对象，返回空列表
        MTP_LOGD_SHELL("Object is not a directory, returning empty reference list");
    }

    MTP_LOGD_SHELL("Found %d references for object 0x%08X", handles->ObjectHandle_len, handle);

    usb_free(obj);

    return mtp_write(g_usbd_mtp.tx_buffer, 
                     sizeof(struct mtp_header) + sizeof(handles->ObjectHandle_len) + (handles->ObjectHandle_len * sizeof(handles->ObjectHandle[0])), 
                     MTP_CONTAINER_TYPE_DATA, MTP_OPERATION_GET_OBJECT_REFERENCES, hdr->trans_id);
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

    MTP_LOGI_SHELL("============================ [%d] ===============================", msg_count);
    MTP_LOGI_SHELL("recv %d types, mtp header, conlen : %d, contype : 0x%04X, code : 0x%04X, trans_id : 0x%08X, param_num : %d", 
                    len, hdr->conlen, hdr->contype, hdr->code, hdr->trans_id, param_num);

    if (hdr->contype == MTP_CONTAINER_TYPE_DATA) {
        param_num = (param_num >= 10 ? 10 : param_num);
    }

    // for (uint32_t i = 0; i < param_num; i++) {
    //     MTP_LOGI_SHELL("param[%d] = 0x%08X", i, hdr->param[i]);
    // }
    MTP_LOGI_SHELL("===========================================================");

    msg_count++;

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

    // PC发送文件过来，会存在最后一包小于mtp头长度的
    if (len < sizeof(struct mtp_header) && g_mtp_data_transfer_ctrl.state != MTP_XFER_DATA_RECEIVING && g_mtp_send_ctrl.status != MTP_SEND_STATUS_SENDING) {
        MTP_LOGE_SHELL("mtp header len invalid : %d", len);
        return mtp_send_response(MTP_RESPONSE_INVALID_PARAMETER, hdr->trans_id);
    }

    mtp_packet_print(data, len);

    if (g_mtp_data_transfer_ctrl.state == MTP_XFER_DATA_RECEIVING) {
        return mtp_send_object_data2(hdr, len);
    }

    if (g_mtp_send_ctrl.status == MTP_SEND_STATUS_SENDING) {
        return mtp_send_object_info(hdr, len);
    }

    // 每次收到数据，说明当前TX进程需要重置
    g_mtp_transfer_ctrl.state = MTP_TRANSFER_STATE_IDLE;

    uint8_t *tx_buffer = g_usbd_mtp.tx_buffer;

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
            return mtp_get_object_info(hdr, len);
        case MTP_OPERATION_GET_OBJECT:
            MTP_LOGI_SHELL("Get object data");
            return mtp_get_object(hdr);
        case MTP_OPERATION_DELETE_OBJECT:
            MTP_LOGI_SHELL("Delete object");
            return mtp_delete_object(hdr);
        case MTP_OPERATION_SEND_OBJECT_INFO:
            MTP_LOGI_SHELL("Send object info");
            return mtp_send_object_info(hdr, len);
        case MTP_OPERATION_SEND_OBJECT:
            MTP_LOGI_SHELL("Send object data");
            return mtp_send_object_data2(hdr, len);
        case MTP_OPERATION_GET_DEVICE_PROP_DESC:
            MTP_LOGI_SHELL("Get device property description");
            return mtp_get_device_prop_desc(hdr);
        case MTP_OPERATION_GET_OBJECT_PROPS_SUPPORTED:
            MTP_LOGI_SHELL("Get object properties supported");
            return mtp_get_object_props_supported(tx_buffer, hdr);
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


extern void mtp_notify_object_added(uint32_t handle, uint32_t parent_handle);
extern void mtp_notify_object_removed(uint32_t handle);


