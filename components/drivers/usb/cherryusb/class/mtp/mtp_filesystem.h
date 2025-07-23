#ifndef MTP_FILESYSTEM_H
#define MTP_FILESYSTEM_H

#include <string.h>
#include <stdlib.h>
#include <stdio.h>
#include <stdint.h>
#include "usb_config.h"

#define MTP_AM_RDO  0x01
#define MTP_AM_HID  0x02
#define MTP_AM_SYS  0x04
#define MTP_AM_DIR  0x10
#define MTP_AM_ARC  0x20

#define MTP_FA_READ          0x01
#define MTP_FA_WRITE         0x02
#define MTP_FA_OPEN_EXISTING 0x00
#define MTP_FA_CREATE_NEW    0x04
#define MTP_FA_CREATE_ALWAYS 0x08
#define MTP_FA_OPEN_ALWAYS   0x10

typedef uint32_t mtp_time_t;
#define MTP_TIME_NONE 0

typedef size_t mtp_fs_bsize_t;
typedef size_t mtp_fs_blocks_t;
typedef size_t mtp_fs_bfree_t;
typedef size_t mtp_fs_filesize_t;

/* gcc toolchain does not implement dirent.h, so we define our own MTP_DIR and mtp_dirent */

typedef void MTP_DIR;

struct mtp_statfs {
    size_t f_bsize;  /* block size */
    size_t f_blocks; /* total data blocks in file system */
    size_t f_bfree;  /* free blocks in file system */
};

struct mtp_dirent {
    uint8_t d_type;                              /* The type of the file */
    uint8_t d_namlen;                            /* The length of the not including the terminating null file name */
    uint16_t d_reclen;                           /* length of this record */
    char d_name[CONFIG_USBDEV_MTP_MAX_PATHNAME]; /* The null-terminated file name */
};

typedef enum {
    MTP_FILE_TYPE_REGULAR,
    MTP_FILE_TYPE_DIRECTORY
} mtp_file_type_t;

struct mtp_stat {
    uint32_t st_mode;       // 文件类型和权限
    uint64_t st_size;       // 文件大小（字节）
    mtp_time_t st_mtime;    // 最后修改时间（MTP时间格式）
    mtp_time_t st_ctime;    // 创建时间（MTP时间格式）
    uint32_t st_blksize;    // 文件系统块大小
    uint64_t st_blocks;     // 分配的块数量
};

typedef struct mtp_file_entry {
    char name[256];
    mtp_file_type_t type;
    size_t size;
    uint8_t *data;
    uint32_t create_time;
    uint32_t modify_time;
    uint8_t attributes;
} mtp_file_entry_t;

typedef struct mtp_dir_entry {
    char name[256];
    mtp_file_entry_t *files[100];
    int file_count;
} mtp_dir_entry_t;

const char *mtp_show_error_string(int result);

void mtp_format_time(mtp_time_t mtp_time, char* buffer);

// 用于MTP协议调用
const char *usbd_mtp_fs_root_path(void);
const char *usbd_mtp_fs_description(void);

int usbd_mtp_fs_mkdir(const char *path);
int usbd_mtp_fs_rmdir(const char *path);
MTP_DIR *usbd_mtp_fs_opendir(const char *name);
int usbd_mtp_fs_closedir(MTP_DIR *d);
struct mtp_dirent *usbd_mtp_fs_readdir(MTP_DIR *d);

int usbd_mtp_fs_statfs(const char *path, struct mtp_statfs *buf);
int usbd_mtp_fs_stat(const char *file, struct mtp_stat *buf);

int usbd_mtp_fs_open(const char *path, uint8_t mode);
int usbd_mtp_fs_close(int fd);
int usbd_mtp_fs_read(int fd, void *buf, size_t len);
int usbd_mtp_fs_write(int fd, const void *buf, size_t len);

int usbd_mtp_fs_unlink(const char *path);

void usbd_mtp_mount(void);

const char* usbd_mtp_fs_modify_time(const char *path);
const char* usbd_mtp_fs_create_time(const char *path);
int usbd_mtp_fs_is_protect(const char *path);
uint32_t usbd_mtp_fs_size(const char *path);


int usbd_mtp_fs_block_size(const char *path, mtp_fs_bsize_t *size);
int usbd_mtp_fs_block_number(const char *path, mtp_fs_blocks_t *num);
int usbd_mtp_fs_block_free(const char *path, mtp_fs_bfree_t *num);
int usbd_mtp_fs_filesize(const char *path, mtp_fs_filesize_t *size);

#endif