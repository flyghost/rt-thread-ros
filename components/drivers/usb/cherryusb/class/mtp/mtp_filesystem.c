#include "mtp_filesystem.h"
#include "usbd_mtp_config.h"

// ==== 全局变量 ====

#define MTP_ROOT_FILE_NUM 100

#define MTP_ROOT_DIRECT   "/MTP"            // MTP目录在文件系统中挂在的绝对路径

#define MTP_FILESYSTEM_SIZE 1024
#define MTP_FILESYSTEM_BLOCK_SIZE 512
#define MTP_FILESYSTEM_BLOCK_NUM 512

static mtp_file_entry_t mtp_root_files[MTP_ROOT_FILE_NUM];
static mtp_dir_entry_t mtp_root_dir = {0};

static mtp_file_entry_t *mtp_open_file = NULL;
static size_t mtp_open_file_pos = 0;

static const char *g_disk_list[] = {
    "FLASH",
    "RAM"
};

static uint32_t mtp_get_current_time(void)
{
    static uint32_t mtp_current_time = 0x11111111;
    return mtp_current_time++;
}

static void *usbd_fs_opendir(const char *path)
{
    return NULL;
}

static void *usbd_fs_readdir(void *dp)
{
    return NULL;
}

static const char *usbd_fs_name_from_dent(void *dent)
{
    return MTP_ROOT_DIRECT;
}

const char *usbd_fs_top_mtp_path(void)
{
    return MTP_ROOT_DIRECT;
}

static const char *usbd_mtp_fs_root_path(void)
{
    void *dp = usbd_fs_opendir(MTP_ROOT_DIRECT);
    const char *name;
    do {
        void *dent = usbd_fs_readdir(dp);
        name = usbd_fs_name_from_dent(dent);
    }
    while (0);

    return name;
}

const char *usbd_mtp_fs_description(uint8_t fs_disk_index)
{
    if (fs_disk_index >= sizeof(g_disk_list) / sizeof (char *)) {
        return NULL;
    }

    return g_disk_list[fs_disk_index];
}

static mtp_file_entry_t *mtp_find_file(const char *path)
{
    for (int i = 0; i < mtp_root_dir.file_count; i++) {
        if (strcmp(mtp_root_dir.files[i]->name, path) == 0) {
            return mtp_root_dir.files[i];
        }
    }
    return NULL;
}

static mtp_dir_entry_t *mtp_find_dir(const char *path)
{
    if (usb_strncmp(path, MTP_ROOT_DIRECT, sizeof(MTP_ROOT_DIRECT) + 1) == 0) {
        return &mtp_root_dir;
    }

    return NULL;
}


int usbd_mtp_fs_rmdir(const char *path)
{
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
    usb_strncpy(dirent.d_name, d->files[index]->name, USB_FS_PATH_MAX - 1);
    dirent.d_namlen = usb_strlen(dirent.d_name);
    index++;
    return &dirent;
}

int usbd_mtp_fs_statfs(const char *path, struct mtp_statfs *buf)
{
    (void)path;
    buf->f_bsize = MTP_FILESYSTEM_BLOCK_SIZE;
    buf->f_blocks = MTP_FILESYSTEM_BLOCK_NUM;
    buf->f_bfree = MTP_FILESYSTEM_BLOCK_NUM;
    return 0;
}

static void *usbd_mtp_create_file(const char *path)
{
    if (mtp_root_dir.file_count >= MTP_ROOT_FILE_NUM) {
        MTP_LOGE_SHELL("No space for new file: %s", path);
        // return -9; // 空间不足
        return NULL;
    }
    if (usb_strnlen(path, USB_FS_PATH_MAX + 1) > USB_FS_PATH_MAX) {
        MTP_LOGE_SHELL("path is too long");
        // return -9;
        return NULL;
    }

    mtp_file_entry_t *file = &mtp_root_files[mtp_root_dir.file_count];
    usb_memset(file, 0, sizeof(mtp_file_entry_t));
    usb_strncpy(file->name, path, USB_FS_PATH_MAX - 1);
    MTP_LOGE_SHELL("create file: %s", path);
    file->type = MTP_FILE_TYPE_REGULAR;
    file->create_time = mtp_get_current_time();
    file->modify_time = file->create_time;
    mtp_root_dir.files[mtp_root_dir.file_count] = file;
    mtp_root_dir.file_count++;

    return (void *)file;
}

/**
 * @brief 打开mtp目录下的文件
 * 
 * @param path          绝对路径
 * @param mode          
 * @return int 
 */
void *usbd_mtp_fs_open_file(const char *path, uint8_t mode)
{
    // 1:打开MTP目录 MTP_ROOT_DIRECT
    // 模拟操作，忽略

    MTP_LOGD_SHELL("@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@ usbd_mtp_fs_open_file %s", path);

    if (!path || !path[0]) {
        MTP_LOGE_SHELL("open path is NULL");
        // return -1;
        return NULL;
    }

    mtp_file_entry_t *file = mtp_find_file(path);
    if (mode == MTP_FA_READ) {
        if (file == NULL) {
            MTP_LOGE_SHELL("File not found: %s", path);
            // return -2; // 文件不存在
            return NULL;
        }
    }
    else if (mode & MTP_FA_WRITE) {
        if (file == NULL) {
            file = usbd_mtp_create_file(path);
        }
    }
    else {
        MTP_LOGE_SHELL("Unsupported mode: 0x%x", mode);
        // return -1;
        return NULL;
    }
    mtp_open_file = file;
    mtp_open_file_pos = 0;

    MTP_LOGD_SHELL("Opened file: %s, mode: 0x%x", path, mode);

    return (void *)file;
}

int usbd_mtp_fs_close_file(void *fp)
{
    (void)fp;
    mtp_open_file = NULL;
    mtp_open_file_pos = 0;
    return 0;
}

int usbd_mtp_fs_read_file(void *fp, void *buf, size_t len)
{
    (void)fp;

    if (!buf) {
        return -1;
    }

    if (!mtp_open_file) {
        MTP_LOGE_SHELL("read error : file not open");
        return -1;
    }

    if (!mtp_open_file->data || !mtp_open_file->size) {
        MTP_LOGE_SHELL("read error : file data NULL");
        return -1;
    }

    if (mtp_open_file->size <= mtp_open_file_pos) {
        return 0;
    }

    size_t remaining = mtp_open_file->size - mtp_open_file_pos;
    if (len > remaining) {
        len = remaining;
    }

    usb_mtp_memcpy(buf, mtp_open_file->data + mtp_open_file_pos, len);
    mtp_open_file_pos += len;

    return (int)len;
}

int usbd_mtp_fs_write_file(void *fp, const void *buf, size_t len)
{
    (void)fp;

    if (mtp_open_file == 0) {
        return -1;
    }

    if (mtp_open_file_pos + len > mtp_open_file->size) {
        size_t new_size = mtp_open_file_pos + len;
        uint8_t *new_data = (uint8_t *)usb_malloc(new_size);
        if (!new_data) {
            return -9;
        }

        // 保存旧的数据
        if (mtp_open_file->data) {
            if (mtp_open_file->size > 0) {
                usb_mtp_memcpy(new_data, mtp_open_file->data, mtp_open_file->size);
            }
            usb_free(mtp_open_file->data);
        }

        mtp_open_file->data = new_data;
        mtp_open_file->size = new_size;
    }

    usb_mtp_memcpy(mtp_open_file->data + mtp_open_file_pos, buf, len);
    mtp_open_file_pos += len;

    MTP_DUMP_SHELL(16, mtp_open_file->data, mtp_open_file_pos);

    mtp_open_file->modify_time = 0;

    return (int)len;
}

int usbd_mtp_fs_unlink(const char *path)
{
    mtp_file_entry_t *file = mtp_find_file(path);
    if (file == NULL)
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
    usb_strncpy(mtp_root_dir.name, MTP_ROOT_DIRECT, USB_FS_PATH_MAX - 1);
    mtp_root_dir.file_count = 0;
}

const char* usbd_mtp_fs_modify_time(const char *path)
{
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

size_t usbd_mtp_fs_size(const char *path)
{
    mtp_file_entry_t *file = mtp_find_file(path);
    if (file == NULL || file->data == NULL) {
        return 0;
    }

    return file->size;
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
    *size = 15;

    return 0;
}


// #define MTP_FS_USE_SIM_RAMFS   1

// void *usbd_fs_opendir(const char *path)
// {
// #if MTP_FS_USE_SIM_RAMFS
//     if (usb_strncmp(path, MTP_ROOT_DIRECT, sizeof(MTP_ROOT_DIRECT) + 1) == 0) {
//         return (void *)&mtp_root_dir;
//     }
//     return NULL;
// #endif
// }

// void *usbd_fs_readdir(void *dp)
// {
//     mtp_dir_entry_t *dir = (mtp_dir_entry_t *)dp;
//     static int index = 0;
//     if (index >= dir->file_count) {
//         index = 0;
//         return NULL;
//     }
//     return &dir->files[index++];
// }