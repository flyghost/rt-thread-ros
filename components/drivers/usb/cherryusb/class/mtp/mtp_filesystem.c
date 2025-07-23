#include "mtp_filesystem.h"
#include "usbd_mtp_config.h"

// ==== 全局变量 ====

#define MTP_ROOT_FILE_NUM 100
#define MTP_ROOT_DIR      "Documents"

#define MTP_FILESYSTEM_SIZE 1024
#define MTP_FILESYSTEM_BLOCK_SIZE 512
#define MTP_FILESYSTEM_BLOCK_NUM 512

static mtp_file_entry_t mtp_root_files[MTP_ROOT_FILE_NUM];
static mtp_dir_entry_t mtp_root_dir = { "/", { 0 }, 0 };
static mtp_file_entry_t *mtp_open_file = 0;
static size_t mtp_open_file_pos = 0;
static uint32_t mtp_current_time = 0x11111111;

static uint32_t mtp_get_current_time(void)
{
    return mtp_current_time++;
}

const char *mtp_show_error_string(int result)
{
    switch (result) {
        case 0:
            return "succeeded";
        case -1:
            return "general error";
        case -2:
            return "file not found";
        case -3:
            return "path not found";
        case -4:
            return "invalid name";
        case -5:
            return "access denied";
        case -6:
            return "file exists";
        case -7:
            return "invalid object";
        case -8:
            return "write protected";
        case -9:
            return "not enough space";
        case -10:
            return "too many open files";
        default:
            return "unknown error";
    }
}

const char *usbd_mtp_fs_root_path(void)
{
    return MTP_ROOT_DIR;
}

const char *usbd_mtp_fs_description(void)
{
    return "FLASH";
}

/**
 * @brief 从路径中去除MTP_ROOT_DIR前缀并规范化斜杠
 * @param path 原始路径
 * @param fixed_path 处理后的路径输出缓冲区
 * @return 处理后的路径指针（指向fixed_path）
 */
static char* remove_root_dir(const char* path, char* fixed_path) {
    const char *ptr = path;
    char *dst = fixed_path;

    // 检查并跳过MTP_ROOT_DIR前缀
    if (strncmp(ptr, MTP_ROOT_DIR, strlen(MTP_ROOT_DIR)) == 0) {
        ptr += strlen(MTP_ROOT_DIR);
        
        // 跳过连续的斜杠（兼容0:/、0://等情况）
        while (*ptr == '/') {
            ptr++;
        }
    }

    // 复制剩余路径
    strcpy(dst, ptr);
    return fixed_path;
}

static mtp_file_entry_t *mtp_find_file(const char *path)
{
    const char *filename = path;
    
    // 处理 MTP_ROOT_DIR 前缀
    if (strcmp(path, MTP_ROOT_DIR) == 0) {
        filename = path + sizeof(MTP_ROOT_DIR) - 1;
        if (*filename == '\0') {
            return NULL; // 路径为 MTP_ROOT_DIR 本身不是文件
        }
    }
    
    // 特殊处理根目录下的文件
    if (*filename == '\0') {
        return NULL;
    }

    // 如果路径以双斜杠开头，跳过第一个斜杠
    if (*filename == '/') {
        filename++;
    }

    for (int i = 0; i < mtp_root_dir.file_count; i++) {
        if (strcmp(mtp_root_dir.files[i]->name, filename) == 0) {
            return mtp_root_dir.files[i];
        }
    }
    return NULL;
}

static mtp_dir_entry_t *mtp_find_dir(const char *path)
{
    if (usb_strcmp(path, "/") == 0 || usb_strcmp(path, MTP_ROOT_DIR) == 0)
        return &mtp_root_dir;
    return 0;
}

mtp_time_t unix_time_to_mtp(time_t unix_time) {
    if (unix_time == 0) return MTP_TIME_NONE;
    // MTP时间是从1900-01-01开始的秒数
    return (mtp_time_t)(unix_time + 2208988800U);
}

void mtp_format_time(mtp_time_t mtp_time, char* buffer) {
    if (mtp_time == MTP_TIME_NONE) {
        strcpy(buffer, "00000000");
        return;
    }
    snprintf(buffer, 9, "%08X", mtp_time);
}

// ==== MTP接口实现 ====
int usbd_mtp_fs_mkdir(const char *path)
{
    if (mtp_find_dir(path) != 0)
        return -6;
    if (mtp_root_dir.file_count >= MTP_ROOT_FILE_NUM)
        return -9;
    mtp_file_entry_t *new_dir = &mtp_root_files[mtp_root_dir.file_count];
    usb_memset(new_dir, 0, sizeof(mtp_file_entry_t));
    const char *dirname = path;
    if (usb_strncmp(path, MTP_ROOT_DIR, sizeof(MTP_ROOT_DIR) - 1) == 0)
        dirname = path + sizeof(MTP_ROOT_DIR) - 1;
    usb_strncpy(new_dir->name, dirname, 255);
    new_dir->type = MTP_FILE_TYPE_DIRECTORY;
    new_dir->attributes = MTP_AM_DIR;
    new_dir->create_time = mtp_get_current_time();
    new_dir->modify_time = new_dir->create_time;
    mtp_root_dir.files[mtp_root_dir.file_count] = new_dir;
    mtp_root_dir.file_count++;
    return 0;
}

int usbd_mtp_fs_rmdir(const char *path)
{
    mtp_file_entry_t *dir = mtp_find_file(path);
    if (dir == 0)
        return -2;
    if (!(dir->attributes & MTP_AM_DIR))
        return -7;
    usb_memset(dir, 0, sizeof(mtp_file_entry_t));
    return 0;
}

void *usbd_mtp_fs_opendir(const char *name)
{
    mtp_dir_entry_t *dir = mtp_find_dir(name);
    return (void *)dir;
}

int usbd_mtp_fs_closedir(void *dir)
{
    (void)dir;
    return 0;
}

struct mtp_dirent *usbd_mtp_fs_readdir(void *dir)
{
    static struct mtp_dirent dirent;
    mtp_dir_entry_t *d = (mtp_dir_entry_t *)dir;
    static int index = 0;
    if (index >= d->file_count) {
        index = 0;
        return 0;
    }
    usb_memset(&dirent, 0, sizeof(struct mtp_dirent));
    usb_strncpy(dirent.d_name, d->files[index]->name, 255);
    dirent.d_namlen = usb_strlen(dirent.d_name);
    index++;
    return &dirent;
}

int usbd_mtp_fs_stat(const char *path, struct mtp_stat *buf) 
{
    // 修正路径中的双斜杠问题
    char fixed_path[CONFIG_USBDEV_MTP_MAX_PATHNAME];
    
    // 调用独立函数处理路径
    remove_root_dir(path, fixed_path);

    MTP_LOGD_SHELL("Stat file: %s", fixed_path);
    
    mtp_file_entry_t *file = mtp_find_file(fixed_path);
    if (file == NULL) {
        mtp_dir_entry_t *dir = mtp_find_dir(fixed_path);
        if (dir == NULL) {
            MTP_LOGE_SHELL("File not found: %s", fixed_path);
            return -2; // 不存在
        }
        
        // 目录信息
        memset(buf, 0, sizeof(*buf));
        buf->st_mode = 0040777;
        buf->st_size = 0; // 目录大小应为0
        buf->st_blksize = MTP_FILESYSTEM_BLOCK_SIZE;
        return 0;
    }

    // 文件信息
    memset(buf, 0, sizeof(*buf));
    buf->st_mode = 0100777;
    if (file->attributes & MTP_AM_RDO)
        buf->st_mode &= ~0222; // 清除写权限
        
    buf->st_size = file->size;
    buf->st_blksize = MTP_FILESYSTEM_BLOCK_SIZE;
    buf->st_blocks = (file->size + MTP_FILESYSTEM_BLOCK_SIZE - 1) / MTP_FILESYSTEM_BLOCK_SIZE;
    buf->st_mtime = unix_time_to_mtp(file->modify_time);
    buf->st_ctime = unix_time_to_mtp(file->create_time);
    
    return 0;
}


int usbd_mtp_fs_statfs(const char *path, struct mtp_statfs *buf)
{
    (void)path;
    buf->f_bsize = MTP_FILESYSTEM_BLOCK_SIZE;
    buf->f_blocks = MTP_FILESYSTEM_BLOCK_NUM;
    buf->f_bfree = MTP_FILESYSTEM_BLOCK_NUM;
    return 0;
}

int usbd_mtp_fs_open(const char *path, uint8_t mode)
{
    const char *filename;
    mtp_file_entry_t *file = mtp_find_file(path);
    if (mode == MTP_FA_READ) {
        if (file == NULL) {
            MTP_LOGE_SHELL("File not found: %s", path);
            return -2; // 文件不存在
        }
    }
    else if (mode & MTP_FA_WRITE) {
        if (file == NULL) {
            if (mtp_root_dir.file_count >= MTP_ROOT_FILE_NUM) {
                MTP_LOGE_SHELL("No space for new file: %s", path);
                return -9; // 空间不足
            }
            file = &mtp_root_files[mtp_root_dir.file_count];
            usb_memset(file, 0, sizeof(mtp_file_entry_t));
            filename = path;
            if (usb_strncmp(path, MTP_ROOT_DIR, sizeof(MTP_ROOT_DIR) - 1) == 0)
                filename = path + sizeof(MTP_ROOT_DIR) - 1;
            usb_strncpy(file->name, filename, 255);
            file->type = MTP_FILE_TYPE_REGULAR;
            file->create_time = mtp_get_current_time();
            file->modify_time = file->create_time;
            mtp_root_dir.files[mtp_root_dir.file_count] = file;
            mtp_root_dir.file_count++;
        }
    }
    else {
        MTP_LOGE_SHELL("Unsupported mode: 0x%x", mode);
        return -1;
    }
    mtp_open_file = file;
    mtp_open_file_pos = 0;

    MTP_LOGD_SHELL("Opened file: %s, mode: 0x%x, filename: %s", path, mode, filename);

    return 0;
}

int usbd_mtp_fs_close(int fd)
{
    (void)fd;
    mtp_open_file = 0;
    mtp_open_file_pos = 0;
    return 0;
}

int usbd_mtp_fs_read(int fd, void *buf, size_t len)
{
    (void)fd;
    if (mtp_open_file == 0)
        return -1;
    size_t remaining = mtp_open_file->size - mtp_open_file_pos;
    if (len > remaining)
        len = remaining;
    if (len > 0) {
        usb_mtp_memcpy(buf, mtp_open_file->data + mtp_open_file_pos, len);
        mtp_open_file_pos += len;
    }
    return (int)len;
}

int usbd_mtp_fs_write(int fd, const void *buf, size_t len)
{
    (void)fd;
    if (mtp_open_file == 0)
        return -1;
    if (mtp_open_file_pos + len > mtp_open_file->size) {
        size_t new_size = mtp_open_file_pos + len;
        uint8_t *new_data = (uint8_t *)usb_malloc(new_size);
        if (new_data == 0)
            return -9;
        if (mtp_open_file->data && mtp_open_file->size > 0)
            usb_mtp_memcpy(new_data, mtp_open_file->data, mtp_open_file->size);
        mtp_open_file->data = new_data;
        mtp_open_file->size = new_size;
    }
    usb_mtp_memcpy(mtp_open_file->data + mtp_open_file_pos, buf, len);
    mtp_open_file_pos += len;
    mtp_open_file->modify_time = mtp_get_current_time();
    return (int)len;
}

int usbd_mtp_fs_unlink(const char *path)
{
    mtp_file_entry_t *file = mtp_find_file(path);
    if (file == 0)
        return -2;
    if (file->attributes & MTP_AM_DIR)
        return -7;
    if (file->data != 0)
        usb_free(file->data);
    usb_memset(file, 0, sizeof(mtp_file_entry_t));
    return 0;
}

void usbd_mtp_mount(void)
{
    MTP_LOGI_SHELL("Mounting MTP file system...");
    usb_memset(&mtp_root_dir, 0, sizeof(mtp_root_dir));
    usb_strncpy(mtp_root_dir.name, "/", 255);
    mtp_root_dir.file_count = 0;
}

const char* usbd_mtp_fs_modify_time(const char *path)
{
    // if (usbd_mtp_fs_stat(obj->file_full_path, file_stat) != 0) {
    //     MTP_LOGE_SHELL("Failed to stat object: %s", obj->file_full_path);
    //     // return mtp_send_response(MTP_RESPONSE_GENERAL_ERROR, hdr->trans_id);
    // }
    return "20240501T120000";
}

const char* usbd_mtp_fs_create_time(const char *path)
{
    return "20240501T120000";
}

int usbd_mtp_fs_is_protect(const char *path)
{
    return 0;
}

uint32_t usbd_mtp_fs_size(const char *path)
{
            // if (obj->is_dir) {
            //     MTP_LOGD_SHELL("Object is a directory, size set to 0");
            // }
            // if (usbd_mtp_fs_stat(obj->file_full_path, file_stat) != 0) {
            //     MTP_LOGE_SHELL("Failed to stat object: %s", obj->file_full_path);
            //     // return mtp_send_response(MTP_RESPONSE_GENERAL_ERROR, hdr->trans_id);
            // }

    // file_stat->st_size;
    return 15;
}

// void fill_timestamp(uint8_t *buf, time_t timestamp) {
//     char iso8601[20];
//     strftime(iso8601, sizeof(iso8601), "%Y%m%dT%H%M%S", gmtime(&timestamp));
    
//     // 转换为UTF-16LE
//     uint8_t len = strlen(iso8601);
//     buf[0] = len;  // 长度前缀
//     for (int i = 0; i < len; i++) {
//         buf[1 + i*2] = iso8601[i];
//         buf[2 + i*2] = 0x00;
//     }
//     buf[1 + len*2] = 0x00; // 终止符
//     buf[2 + len*2] = 0x00;
// }


// typedef size_t mtp_fs_bsize_t;
// typedef size_t mtp_fs_blocks_t;
// typedef size_t mtp_fs_bfree_t;

int usbd_mtp_fs_block_size(const char *path, mtp_fs_bsize_t *size)
{
    struct mtp_statfs stat;
    *size = 0;

    if (usbd_mtp_fs_statfs(usbd_mtp_fs_root_path(), &stat) != 0) {
        return -1;
    }

    *size = stat.f_bsize;

    return 0;
}

int usbd_mtp_fs_block_number(const char *path, mtp_fs_blocks_t *num)
{
    struct mtp_statfs stat;
    *num = 0;

    if (usbd_mtp_fs_statfs(usbd_mtp_fs_root_path(), &stat) != 0) {
        return -1;
    }

    *num = stat.f_blocks;

    return 0;
}

int usbd_mtp_fs_block_free(const char *path, mtp_fs_bfree_t *num)
{
    struct mtp_statfs stat;
    *num = 0;

    if (usbd_mtp_fs_statfs(usbd_mtp_fs_root_path(), &stat) != 0) {
        return -1;
    }

    *num = stat.f_bfree;

    return 0;
}

int usbd_mtp_fs_filesize(const char *path, mtp_fs_filesize_t *size)
{
    // struct mtp_stat file_stat;
    // if (usbd_mtp_fs_stat(txt_file->file_full_path, &file_stat) == 0) {
    //     MTP_LOGD_SHELL("readme.txt size = %d", txt_file->file_size);
    // }

    *size = 15;

    return 0;
}


