#include "mtp_filesystem.h"
#include "usbd_mtp_config.h"

// ==== 全局变量 ====

#define MTP_ROOT_FILE_NUM 100

static mtp_file_entry_t mtp_root_files[MTP_ROOT_FILE_NUM];
static mtp_dir_entry_t mtp_root_dir = { "/", { 0 }, 0 };
static mtp_file_entry_t *mtp_open_file = 0;
static size_t mtp_open_file_pos = 0;
static uint32_t mtp_current_time = 0;

const char mtp_driver_num_buf[4] = { '0', ':', '/', '\0' };

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
    return mtp_driver_num_buf;
}

const char *usbd_mtp_fs_description(void)
{
    return "Mock MTP File System";
}

static mtp_file_entry_t *mtp_find_file(const char *path)
{
    const char *filename = path;
    
    // 处理 "0:/" 前缀
    if (strncmp(path, "0:/", 3) == 0) {
        filename = path + 3;
        if (*filename == '\0') {
            return NULL; // 路径为 "0:/" 本身不是文件
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
    if (usb_strcmp(path, "/") == 0 || usb_strcmp(path, "0:/") == 0)
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
    if (usb_strncmp(path, "0:/", 3) == 0)
        dirname = path + 3;
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
    const char *ptr = path;
    char *dst = fixed_path;
    
    // 跳过开头的0:/或0://
    if (strncmp(ptr, "0:/", 3) == 0) {
        strncpy(fixed_path, "0:/", 3);
        dst += 3;
        ptr += 3;
        
        // 跳过额外的斜杠
        while (*ptr == '/') {
            ptr++;
        }
    }
    
    strcpy(dst, ptr);
    
    mtp_file_entry_t *file = mtp_find_file(fixed_path);
    if (file == NULL) {
        mtp_dir_entry_t *dir = mtp_find_dir(fixed_path);
        if (dir == NULL) return -2; // 不存在
        
        // 目录信息
        memset(buf, 0, sizeof(*buf));
        buf->st_mode = 0040777;
        buf->st_size = 0; // 目录大小应为0
        buf->st_blksize = 512;
        return 0;
    }

    // 文件信息
    memset(buf, 0, sizeof(*buf));
    buf->st_mode = 0100777;
    if (file->attributes & MTP_AM_RDO)
        buf->st_mode &= ~0222; // 清除写权限
        
    buf->st_size = file->size;
    buf->st_blksize = 512;
    buf->st_blocks = (file->size + 511) / 512;
    buf->st_mtime = unix_time_to_mtp(file->modify_time);
    buf->st_ctime = unix_time_to_mtp(file->create_time);
    
    return 0;
}


int usbd_mtp_fs_statfs(const char *path, struct mtp_statfs *buf)
{
    (void)path;
    buf->f_bsize = 512;
    buf->f_blocks = 1000;
    buf->f_bfree = 500;
    return 0;
}

int usbd_mtp_fs_open(const char *path, uint8_t mode)
{
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
            const char *filename = path;
            if (usb_strncmp(path, "0:/", 3) == 0)
                filename = path + 3;
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
    
    // 确保文件创建成功
    // int fd = usbd_mtp_fs_open("0:/readme.txt", MTP_FA_WRITE | MTP_FA_CREATE_ALWAYS);
    // if (fd >= 0) {
    //     const char *test_content = "Hello, this is mock file system demo\n";
    //     int len = usb_strlen(test_content);
    //     if (usbd_mtp_fs_write(fd, test_content, len) == len) {
    //         MTP_LOGI_SHELL("Successfully created readme.txt");
    //     }
    //     usbd_mtp_fs_close(fd);
    // } else {
    //     MTP_LOGE_SHELL("Failed to create readme.txt");
    // }
}