#ifndef MTP_FILESYSTEM_H
#define MTP_FILESYSTEM_H

#include <string.h>
#include <stdlib.h>
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
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
    uint64_t st_size;       // 文件大小（字节）
    uint32_t st_blksize;    // 文件系统块大小
    uint64_t st_blocks;     // 分配的块数量
};
#define USB_FS_PATH_MAX 256
typedef struct mtp_file_entry {
    char name[USB_FS_PATH_MAX];
    mtp_file_type_t type;
    size_t size;
    uint8_t *data;
    uint32_t create_time;
    uint32_t modify_time;
    uint8_t attributes;
} mtp_file_entry_t;

typedef struct mtp_dir_entry {
    char name[USB_FS_PATH_MAX];
    mtp_file_entry_t *files[100];
    int file_count;
} mtp_dir_entry_t;

// 目录操作
int usbd_fs_mkdir(const char *path, mode_t mode);
void *usbd_fs_opendir(const char *path);
void *usbd_fs_readdir(void *dp);
int usbd_fs_closedir(void *dp);
int usbd_mtp_fs_rmdir(const char *path);

const char *usbd_fs_name_from_dent(void *dent);
bool usbd_fs_is_dir_from_dent(void *dent);

int usbd_mtp_fs_statfs(const char *path, struct mtp_statfs *buf);

// 文件操作
void *usbd_mtp_fs_open_file(const char *path, const char *mode);
int usbd_mtp_fs_close_file(void *fp);
int usbd_mtp_fs_read_file(void *fp, void *buf, size_t len);
int usbd_mtp_fs_write_file(void *fp, const void *buf, size_t len);

int usbd_mtp_fs_rm_file(const char *path);

const char* usbd_mtp_fs_modify_time(const char *path);
const char* usbd_mtp_fs_create_time(const char *path);
int usbd_mtp_fs_is_protect(const char *path);
size_t usbd_mtp_fs_size(const char *path);

const char *usbd_fs_top_mtp_path(void);

#endif