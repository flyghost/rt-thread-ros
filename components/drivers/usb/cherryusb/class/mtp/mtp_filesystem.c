#include "mtp_filesystem.h"
#include "usbd_mtp_config.h"

#include <dirent.h>
#include <unistd.h>
#include <sys/stat.h>
#if USB_FS_USING_STANDARD
#include <stdio.h>
#else
#include <fcntl.h>
#include <sys/statfs.h>
#endif

#define MTP_FILESYSTEM_SIZE 1024
#define MTP_FILESYSTEM_BLOCK_SIZE 512
#define MTP_FILESYSTEM_BLOCK_NUM 512

int usbd_fs_mkdir(const char *path, mode_t mode)
{
    int ret = mkdir(path, mode);
    if (ret < 0) {
        MTP_LOGE_SHELL("Failed to create directory: %s", path);
    }
    return ret;
}

void *usbd_fs_opendir(const char *path)
{
    // 接口相同
    void *dp = opendir(path);
    if (dp == NULL) {
        MTP_LOGE_SHELL("Failed to open directory: %s", path);
    }
    return dp;
}

int usbd_fs_closedir(void *dp)
{
    // 接口相同
    int ret = closedir(dp);
    if (ret < 0) {
        MTP_LOGE_SHELL("Failed to close directory");
    }
    return ret;
}

void *usbd_fs_readdir(void *dp)
{
    // 接口相同
    return readdir(dp);
}

const char *usbd_fs_name_from_dent(void *dent)
{
    // 接口相同
    return ((struct dirent *)dent)->d_name;
}

bool usbd_fs_is_dir_from_dent(void *dent)
{
    // 接口相同
    return ((struct dirent *)dent)->d_type == DT_DIR;
}

int usbd_mtp_fs_rmdir(const char *path)
{
    // 接口相同
    int ret = rmdir(path);
    if (ret < 0) {
        MTP_LOGE_SHELL("Failed to remove directory: %s", path);
    }
    MTP_LOGD_SHELL("Removed directory: %s", path);
    return ret;
}

// 递归删除目录及其所有内容
int usbd_mtp_fs_rmdir_recursive(const char *path)
{
    struct stat statbuf;
    
    // 检查路径是否存在
    if (stat(path, &statbuf) != 0) {
        MTP_LOGE_SHELL("Path does not exist: %s", path);
        return -1;
    }
    
    // 如果是文件，直接删除
    if (!S_ISDIR(statbuf.st_mode)) {
        return usbd_mtp_fs_rm_file(path);
    }
    
    // 如果是目录，递归删除其内容
    void *dir = usbd_fs_opendir(path);
    if (!dir) {
        MTP_LOGE_SHELL("Failed to open directory: %s", path);
        return -1;
    }
    
    void *entry;
    int ret = 0;
    
    while ((entry = usbd_fs_readdir(dir)) != NULL) {
        const char *name = usbd_fs_name_from_dent(entry);
        
        // 跳过 "." 和 ".."
        if (strcmp(name, ".") == 0 || strcmp(name, "..") == 0) {
            continue;
        }
        
        // 构建完整路径
        char full_path[CONFIG_USBDEV_MTP_MAX_PATHNAME];
        snprintf(full_path, sizeof(full_path), "%s/%s", path, name);
        
        if (usbd_fs_is_dir_from_dent(entry)) {
            // 递归删除子目录
            ret = usbd_mtp_fs_rmdir_recursive(full_path);
        } else {
            // 删除文件
            ret = usbd_mtp_fs_rm_file(full_path);
        }
        
        if (ret != 0) {
            MTP_LOGE_SHELL("Failed to delete: %s", full_path);
            break;
        }
    }
    
    usbd_fs_closedir(dir);
    
    // 如果递归删除成功，删除空目录
    if (ret == 0) {
        ret = usbd_mtp_fs_rmdir(path);
        if (ret == 0) {
            MTP_LOGD_SHELL("Successfully removed directory: %s", path);
        }
    }
    
    return ret;
}

void *usbd_mtp_fs_open_file(const char *path, const char *mode)
{
#if USB_FS_USING_STANDARD
    void *fileptr = fopen(path, mode);
    if (fileptr == NULL) {
        MTP_LOGE_SHELL("Failed to open file: %s", path);
    }
    return fileptr;
#else
    int mode_flags = 0;
    bool plus = false, binary = false;
    char m = mode[0];
    const char *p = mode + 1;
    while (*p) {
        if (*p == '+') plus = true;
        else if (*p == 'b') binary = true;
        else {
            MTP_LOGE_SHELL("Unsupported mode character: %c", *p);
            return NULL;
        }
        ++p;
    }

    switch (m) {
    case 'r':   // 只读模式
        mode_flags = plus ? O_RDWR : O_RDONLY;
        break;
    case 'w':   // 写入模式
        mode_flags = O_CREAT | O_TRUNC | (plus ? O_RDWR : O_WRONLY);
        break;
    case 'a':   // 追加模式
        mode_flags = O_CREAT | O_APPEND | (plus ? O_RDWR : O_WRONLY);
        break;
    default:
        MTP_LOGE_SHELL("Unsupported mode: %s", mode);
        return NULL;
    }

    int ret = open(path, mode_flags, 0666);
    if (ret < 0) {
        MTP_LOGE_SHELL("Failed to open file: %s, error: %d", path, ret);
        return NULL;
    }
    MTP_LOGD_SHELL("Opened file: %s, fd: %d, flags: 0x%x", path, ret, mode_flags);
    return (void *)(intptr_t)ret;
#endif
}

int usbd_mtp_fs_close_file(void *fp)
{
    int ret;
#if USB_FS_USING_STANDARD
    ret = fclose(fp);
#else
    ret = close((intptr_t)fp);
#endif
    if (ret < 0) {
        MTP_LOGE_SHELL("Failed to close file, error: %d", ret);
        return -1; // 关闭失败
    }
    MTP_LOGD_SHELL("Closed file successfully");
    return 0; // 关闭成功
}

int usbd_mtp_fs_read_file(void *fp, void *buf, size_t len)
{
#if USB_FS_USING_STANDARD
    ssize_t length = fread(buf, 1, len, fp);
#else
    ssize_t length = read((intptr_t)fp, buf, len);
#endif
    if (length < 0) {
        MTP_LOGE_SHELL("Failed to read file, error: %d", length);
        return -1;
    }
    return (int)length;
}

int usbd_mtp_fs_write_file(void *fp, const void *buf, size_t len)
{
#if USB_FS_USING_STANDARD
    ssize_t length = fwrite(buf, 1, len, fp);
#else
    ssize_t length = write((intptr_t)fp, buf, len);
#endif
    if (length < 0) {
        MTP_LOGE_SHELL("Failed to write file, error: %d", length);
        return -1;
    }
    return (int)length;
}

int usbd_mtp_fs_rm_file(const char *path)
{
#if USB_FS_USING_STANDARD
    int ret = remove(path);
#else
    int ret = unlink(path);
#endif

    if (ret < 0) {
        MTP_LOGE_SHELL("Failed to unlink file: %s, error: %d", path, ret);
    }
    MTP_LOGD_SHELL("Unlinked file: %s", path);
    return ret;
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
    // 接口相同
    struct stat file_stat;
    if (stat(path, &file_stat) == 0) {
        if (file_stat.st_mode & S_IWUSR) {
            return 0; // 可写
        }
        else {
            return 1; // 只读
        }
    }
    else {
        MTP_LOGE_SHELL("Failed to check protection for path: %s", path);
        return 1; // 错误
    }
}

size_t usbd_mtp_fs_size(const char *path)
{
    // 接口相同
    struct stat file_stat;
    if (stat(path, &file_stat) == 0) {
        return file_stat.st_size;
    }
    else {
        MTP_LOGE_SHELL("Failed to get size for path: %s", path);
        return 0;
    }
}

int usbd_mtp_fs_statfs(const char *path, struct mtp_statfs *buf)
{
#if USB_FS_USING_STANDARD
    (void)path;
    buf->f_bsize = MTP_FILESYSTEM_BLOCK_SIZE;
    buf->f_blocks = MTP_FILESYSTEM_BLOCK_NUM;
    buf->f_bfree = MTP_FILESYSTEM_BLOCK_NUM;
    return 0;
#else
    (void)path;
    struct statfs fs_stat;
    int ret = statfs(path, &fs_stat);
    if (ret < 0) {
        MTP_LOGE_SHELL("Failed to get filesystem stats for %s: %d", path, ret);
        return -1; // 获取失败
    }

    buf->f_bsize = fs_stat.f_bsize;
    buf->f_blocks = fs_stat.f_blocks;
    buf->f_bfree = fs_stat.f_bfree;

    MTP_LOGD_SHELL("Filesystem stats for %s: bsize=%d, blocks=%d, bfree=%d", path, buf->f_bsize, buf->f_blocks, buf->f_bfree);
    return 0; // 获取成功
#endif
}

#include <dfs.h>
char *usbd_mtp_fs_normalize_path(const char *base, const char *path)
{
    return dfs_normalize_path(base, path);
}

// 测试代码
#if 0
#include <rtthread.h>
// #include <dfs_romfs.h>
#include <dfs_fs.h>
#include <dfs_file.h>
#include <dfs_ramfs.h>
// #include <dfs_posix.h>
#include <dfs.h>

extern int open(const char *file, int flags, ...);
extern int close(int fd);
extern ssize_t write(int fd, const void *buf, size_t len);
extern ssize_t read(int fd, void *buf, size_t len);

#define RAMFS_POOL_SIZE (4 * 1024) // 4KB 内存池

int ramfs_sample(void)
{
    struct dfs_ramfs *ramfs;
    rt_uint8_t *ramfs_pool;

    // 1. 分配内存池（需 4 字节对齐）
    ramfs_pool = rt_malloc(RAMFS_POOL_SIZE);
    if (ramfs_pool == RT_NULL) {
        rt_kprintf("RAMFS pool malloc failed!\n");
        return -1;
    }

    // 先注册文件系统类型
    // if (dfs_register(&dfs_ramfs) != 0) {
    //     rt_kprintf("RAMFS register failed!\n");
    //     return -1;
    // }

    // if (dfs_mkdir("/ram", 0) != 0) {
    //     rt_kprintf("Failed to create /ram directory\n");
    //     // 处理错误...
    // }

    // 2. 创建 RAMFS 实例
    ramfs = dfs_ramfs_create(ramfs_pool, RAMFS_POOL_SIZE);
    if (ramfs == RT_NULL) {
        rt_kprintf("RAMFS create failed!\n");
        rt_free(ramfs_pool);
        return -1;
    }

    // 3. 挂载到文件系统（例如挂载到 "/ram" 目录）
    if (dfs_mount(RT_NULL, "/ram", "ram", 0, ramfs) != 0) {
        rt_kprintf("RAMFS mount failed!\n");
        rt_free(ramfs_pool);
        return -1;
    }

    rt_kprintf("RAMFS mounted at /ram\n");
    return 0;
}
// INIT_APP_EXPORT(ramfs_sample);
MSH_CMD_EXPORT(ramfs_sample, "init ramfs sample");

void ramfs_write_file(void)
{
    FILE *fp;
    char *data = "Hello, RAMFS!";

    // 0. 先创建文件夹（如果不存在）
    if (mkdir("/ram", 0) != 0) {
        // 如果文件夹已存在，错误码是 EEXIST，这是可以接受的
        if (rt_get_errno() != EEXIST) {
            rt_kprintf("Create directory failed! errno=%d\n", rt_get_errno());
            return;
        }
    }

    // 1. 打开文件（如果不存在则创建）
    fp = fopen("/ram/test.txt", "w");
    if (fp == NULL) {
        rt_kprintf("Open file failed!\n");
        return;
    }

    // 2. 写入数据
    fwrite(data, 1, rt_strlen(data), fp);
    rt_kprintf("Write data: %s\n", data);

    // 3. 关闭文件
    fclose(fp);
}
MSH_CMD_EXPORT(ramfs_write_file, "Write file to RAMFS");

void ramfs_read_file(void)
{
    FILE *fp;
    char buf[64];
    size_t len;

    // 1. 打开文件
    fp = fopen("/ram/test.txt", "r");
    if (fp == NULL) {
        rt_kprintf("Open file failed!\n");
        return;
    }

    // 2. 读取数据
    len = fread(buf, 1, sizeof(buf), fp);
    buf[len] = '\0';  // 确保字符串结尾
    rt_kprintf("Read data: %s\n", buf);

    // 3. 关闭文件
    fclose(fp);
}
MSH_CMD_EXPORT(ramfs_read_file, "Read file from RAMFS");

#endif