/*
 * Copyright (c) 2025, sakumisu
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#ifndef USBD_MTP_SUPPORT_H
#define USBD_MTP_SUPPORT_H

#define MTP_VERSION 100

#define MTP_ARRAY_END_MARK 0xFFFF

typedef struct _profile_property {
    uint16_t prop_code;
    uint16_t data_type;
    uint8_t getset;
    uint64_t default_value;
    uint32_t group_code;
    uint8_t form_flag;
    uint16_t format_code;
} profile_property;

typedef struct _format_property {
    uint16_t format_code;
    uint16_t *properties;
} formats_property;

const char mtp_extension_string[] = "microsoft.com: 1.0; android.com: 1.0;";

const uint16_t supported_op[] = {
    MTP_OPERATION_GET_DEVICE_INFO,  //0x1001
    MTP_OPERATION_OPEN_SESSION,     //0x1002
    MTP_OPERATION_CLOSE_SESSION,    //0x1003
    MTP_OPERATION_GET_STORAGE_IDS,  //0x1004
    MTP_OPERATION_GET_STORAGE_INFO, //0x1005
    MTP_OPERATION_GET_NUM_OBJECTS                        ,//0x1006
    MTP_OPERATION_GET_OBJECT_HANDLES, //0x1007
    MTP_OPERATION_GET_OBJECT_INFO,    //0x1008
    MTP_OPERATION_GET_OBJECT,         //0x1009
    MTP_OPERATION_GET_THUMB                              ,//0x100A
    MTP_OPERATION_DELETE_OBJECT,        //0x100B
    MTP_OPERATION_SEND_OBJECT_INFO,     //0x100C
    MTP_OPERATION_SEND_OBJECT,          //0x100D
    MTP_OPERATION_GET_DEVICE_PROP_DESC, //0x1014
    MTP_OPERATION_GET_DEVICE_PROP_VALUE                  ,//0x1015
    MTP_OPERATION_SET_DEVICE_PROP_VALUE                  ,//0x1016
    MTP_OPERATION_RESET_DEVICE_PROP_VALUE                ,//0x1017
    MTP_OPERATION_GET_PARTIAL_OBJECT                     ,//0x101B
    MTP_OPERATION_GET_OBJECT_PROPS_SUPPORTED, //0x9801
    MTP_OPERATION_GET_OBJECT_PROP_DESC,       //0x9802
    MTP_OPERATION_GET_OBJECT_PROP_VALUE                  ,//0x9803
    MTP_OPERATION_SET_OBJECT_PROP_VALUE                  ,//0x9804
    MTP_OPERATION_GET_OBJECT_PROP_LIST                   ,//0x9805
    MTP_OPERATION_GET_OBJECT_REFERENCES                  ,//0x9810
    MTP_OPERATION_SET_OBJECT_REFERENCES                  ,//0x9811
    MTP_OPERATION_GET_PARTIAL_OBJECT_64                  ,//0x95C1
    MTP_OPERATION_SEND_PARTIAL_OBJECT                    ,//0x95C2
    MTP_OPERATION_TRUNCATE_OBJECT                        ,//0x95C3
    MTP_OPERATION_BEGIN_EDIT_OBJECT                      ,//0x95C4
    MTP_OPERATION_END_EDIT_OBJECT                         //0x95C5
};

const uint16_t supported_event[] = {
    MTP_EVENT_OBJECT_ADDED,         // 0x4002
    MTP_EVENT_OBJECT_REMOVED,       // 0x4003
    // MTP_EVENT_STORE_ADDED,          // 0x4004
    // MTP_EVENT_STORE_REMOVED,        // 0x4005
    // MTP_EVENT_STORAGE_INFO_CHANGED, // 0x400C
    // MTP_EVENT_OBJECT_INFO_CHANGED,  // 0x4007
    // MTP_EVENT_DEVICE_PROP_CHANGED,  // 0x4006
    // MTP_EVENT_OBJECT_PROP_CHANGED   // 0xC801
};

int supported_event_size = sizeof(supported_event);

const formats_property support_format_properties[] = {
    // format code                       prop code
    { MTP_FORMAT_UNDEFINED, (uint16_t[]){ MTP_PROPERTY_STORAGE_ID, MTP_PROPERTY_OBJECT_FORMAT, MTP_PROPERTY_PROTECTION_STATUS, MTP_PROPERTY_OBJECT_SIZE,
                                          MTP_PROPERTY_OBJECT_FILE_NAME, MTP_PROPERTY_DATE_MODIFIED, MTP_PROPERTY_PARENT_OBJECT, MTP_PROPERTY_PERSISTENT_UID,
                                          MTP_PROPERTY_NAME, MTP_PROPERTY_DISPLAY_NAME, MTP_PROPERTY_DATE_CREATED,
                                          0xFFFF } },
    { MTP_FORMAT_ASSOCIATION, (uint16_t[]){ MTP_PROPERTY_STORAGE_ID, MTP_PROPERTY_OBJECT_FORMAT, MTP_PROPERTY_PROTECTION_STATUS, MTP_PROPERTY_OBJECT_SIZE,
                                            MTP_PROPERTY_OBJECT_FILE_NAME, MTP_PROPERTY_DATE_MODIFIED, MTP_PROPERTY_PARENT_OBJECT, MTP_PROPERTY_PERSISTENT_UID,
                                            MTP_PROPERTY_NAME, MTP_PROPERTY_DISPLAY_NAME, MTP_PROPERTY_DATE_CREATED,
                                            0xFFFF } },
	{ MTP_FORMAT_TEXT         , (uint16_t[]){   MTP_PROPERTY_STORAGE_ID, MTP_PROPERTY_OBJECT_FORMAT, MTP_PROPERTY_PROTECTION_STATUS, MTP_PROPERTY_OBJECT_SIZE,
												MTP_PROPERTY_OBJECT_FILE_NAME, MTP_PROPERTY_DATE_MODIFIED, MTP_PROPERTY_PARENT_OBJECT, MTP_PROPERTY_PERSISTENT_UID,
												MTP_PROPERTY_NAME, MTP_PROPERTY_DISPLAY_NAME, MTP_PROPERTY_DATE_CREATED,
												0xFFFF}
	}
#if 0
	{ MTP_FORMAT_HTML         , (uint16_t[]){   MTP_PROPERTY_STORAGE_ID, MTP_PROPERTY_OBJECT_FORMAT, MTP_PROPERTY_PROTECTION_STATUS, MTP_PROPERTY_OBJECT_SIZE,
												MTP_PROPERTY_OBJECT_FILE_NAME, MTP_PROPERTY_DATE_MODIFIED, MTP_PROPERTY_PARENT_OBJECT, MTP_PROPERTY_PERSISTENT_UID,
												MTP_PROPERTY_NAME, MTP_PROPERTY_DISPLAY_NAME, MTP_PROPERTY_DATE_CREATED,
												0xFFFF}
	},
	{ MTP_FORMAT_MP4_CONTAINER, (uint16_t[]){   MTP_PROPERTY_STORAGE_ID, MTP_PROPERTY_OBJECT_FORMAT, MTP_PROPERTY_PROTECTION_STATUS, MTP_PROPERTY_OBJECT_SIZE,
												MTP_PROPERTY_OBJECT_FILE_NAME, MTP_PROPERTY_DATE_MODIFIED, MTP_PROPERTY_PARENT_OBJECT, MTP_PROPERTY_PERSISTENT_UID,
												MTP_PROPERTY_NAME, MTP_PROPERTY_DISPLAY_NAME, MTP_PROPERTY_DATE_CREATED, MTP_PROPERTY_ARTIST, MTP_PROPERTY_ALBUM_NAME,
												MTP_PROPERTY_DURATION, MTP_PROPERTY_DESCRIPTION, MTP_PROPERTY_WIDTH, MTP_PROPERTY_HEIGHT, MTP_PROPERTY_DATE_AUTHORED,
												0xFFFF}
	},
	{ MTP_FORMAT_3GP_CONTAINER, (uint16_t[]){   MTP_PROPERTY_STORAGE_ID, MTP_PROPERTY_OBJECT_FORMAT, MTP_PROPERTY_PROTECTION_STATUS, MTP_PROPERTY_OBJECT_SIZE,
												MTP_PROPERTY_OBJECT_FILE_NAME, MTP_PROPERTY_DATE_MODIFIED, MTP_PROPERTY_PARENT_OBJECT, MTP_PROPERTY_PERSISTENT_UID,
												MTP_PROPERTY_NAME, MTP_PROPERTY_DISPLAY_NAME, MTP_PROPERTY_DATE_CREATED, MTP_PROPERTY_ARTIST, MTP_PROPERTY_ALBUM_NAME,
												MTP_PROPERTY_DURATION, MTP_PROPERTY_DESCRIPTION, MTP_PROPERTY_WIDTH, MTP_PROPERTY_HEIGHT, MTP_PROPERTY_DATE_AUTHORED,
												0xFFFF}
	},
	{ MTP_FORMAT_WAV          , (uint16_t[]){   MTP_PROPERTY_STORAGE_ID, MTP_PROPERTY_OBJECT_FORMAT, MTP_PROPERTY_PROTECTION_STATUS, MTP_PROPERTY_OBJECT_SIZE,
												MTP_PROPERTY_OBJECT_FILE_NAME, MTP_PROPERTY_DATE_MODIFIED, MTP_PROPERTY_PARENT_OBJECT, MTP_PROPERTY_PERSISTENT_UID,
												MTP_PROPERTY_NAME, MTP_PROPERTY_DISPLAY_NAME, MTP_PROPERTY_DATE_CREATED,MTP_PROPERTY_ARTIST,MTP_PROPERTY_ALBUM_NAME,
												MTP_PROPERTY_ALBUM_ARTIST, MTP_PROPERTY_TRACK, MTP_PROPERTY_ORIGINAL_RELEASE_DATE, MTP_PROPERTY_GENRE, MTP_PROPERTY_COMPOSER,
												MTP_PROPERTY_AUDIO_WAVE_CODEC, MTP_PROPERTY_BITRATE_TYPE, MTP_PROPERTY_AUDIO_BITRATE, MTP_PROPERTY_NUMBER_OF_CHANNELS,MTP_PROPERTY_SAMPLE_RATE,
												0xFFFF}
	},
	{ MTP_FORMAT_MP3          , (uint16_t[]){   MTP_PROPERTY_STORAGE_ID, MTP_PROPERTY_OBJECT_FORMAT, MTP_PROPERTY_PROTECTION_STATUS, MTP_PROPERTY_OBJECT_SIZE,
												MTP_PROPERTY_OBJECT_FILE_NAME, MTP_PROPERTY_DATE_MODIFIED, MTP_PROPERTY_PARENT_OBJECT, MTP_PROPERTY_PERSISTENT_UID,
												MTP_PROPERTY_NAME, MTP_PROPERTY_DISPLAY_NAME, MTP_PROPERTY_DATE_CREATED,MTP_PROPERTY_ARTIST,MTP_PROPERTY_ALBUM_NAME,
												MTP_PROPERTY_ALBUM_ARTIST, MTP_PROPERTY_TRACK, MTP_PROPERTY_ORIGINAL_RELEASE_DATE, MTP_PROPERTY_GENRE, MTP_PROPERTY_COMPOSER,
												MTP_PROPERTY_AUDIO_WAVE_CODEC, MTP_PROPERTY_BITRATE_TYPE, MTP_PROPERTY_AUDIO_BITRATE, MTP_PROPERTY_NUMBER_OF_CHANNELS,MTP_PROPERTY_SAMPLE_RATE,
												0xFFFF}
	},
	{ MTP_FORMAT_MPEG         , (uint16_t[]){   MTP_PROPERTY_STORAGE_ID, MTP_PROPERTY_OBJECT_FORMAT, MTP_PROPERTY_PROTECTION_STATUS, MTP_PROPERTY_OBJECT_SIZE,
												MTP_PROPERTY_OBJECT_FILE_NAME, MTP_PROPERTY_DATE_MODIFIED, MTP_PROPERTY_PARENT_OBJECT, MTP_PROPERTY_PERSISTENT_UID,
												MTP_PROPERTY_NAME, MTP_PROPERTY_DISPLAY_NAME, MTP_PROPERTY_DATE_CREATED, MTP_PROPERTY_ARTIST, MTP_PROPERTY_ALBUM_NAME,
												MTP_PROPERTY_DURATION, MTP_PROPERTY_DESCRIPTION, MTP_PROPERTY_WIDTH, MTP_PROPERTY_HEIGHT, MTP_PROPERTY_DATE_AUTHORED,
												0xFFFF}
	},
	{ MTP_FORMAT_EXIF_JPEG    , (uint16_t[]){   MTP_PROPERTY_STORAGE_ID, MTP_PROPERTY_OBJECT_FORMAT, MTP_PROPERTY_PROTECTION_STATUS, MTP_PROPERTY_OBJECT_SIZE,
												MTP_PROPERTY_OBJECT_FILE_NAME, MTP_PROPERTY_DATE_MODIFIED, MTP_PROPERTY_PARENT_OBJECT, MTP_PROPERTY_PERSISTENT_UID,
												MTP_PROPERTY_NAME, MTP_PROPERTY_DISPLAY_NAME, MTP_PROPERTY_DATE_CREATED, MTP_PROPERTY_DESCRIPTION, MTP_PROPERTY_WIDTH,
												MTP_PROPERTY_HEIGHT, MTP_PROPERTY_DATE_AUTHORED,
												0xFFFF}
	},
	{ MTP_FORMAT_BMP          , (uint16_t[]){   MTP_PROPERTY_STORAGE_ID, MTP_PROPERTY_OBJECT_FORMAT, MTP_PROPERTY_PROTECTION_STATUS, MTP_PROPERTY_OBJECT_SIZE,
												MTP_PROPERTY_OBJECT_FILE_NAME, MTP_PROPERTY_DATE_MODIFIED, MTP_PROPERTY_PARENT_OBJECT, MTP_PROPERTY_PERSISTENT_UID,
												MTP_PROPERTY_NAME, MTP_PROPERTY_DISPLAY_NAME, MTP_PROPERTY_DATE_CREATED, MTP_PROPERTY_DESCRIPTION, MTP_PROPERTY_WIDTH,
												MTP_PROPERTY_HEIGHT, MTP_PROPERTY_DATE_AUTHORED,
												0xFFFF}
	},
	{ MTP_FORMAT_GIF          , (uint16_t[]){   MTP_PROPERTY_STORAGE_ID, MTP_PROPERTY_OBJECT_FORMAT, MTP_PROPERTY_PROTECTION_STATUS, MTP_PROPERTY_OBJECT_SIZE,
												MTP_PROPERTY_OBJECT_FILE_NAME, MTP_PROPERTY_DATE_MODIFIED, MTP_PROPERTY_PARENT_OBJECT, MTP_PROPERTY_PERSISTENT_UID,
												MTP_PROPERTY_NAME, MTP_PROPERTY_DISPLAY_NAME, MTP_PROPERTY_DATE_CREATED, MTP_PROPERTY_DESCRIPTION, MTP_PROPERTY_WIDTH,
												MTP_PROPERTY_HEIGHT, MTP_PROPERTY_DATE_AUTHORED,
												0xFFFF}
	},
	{ MTP_FORMAT_JFIF         , (uint16_t[]){   MTP_PROPERTY_STORAGE_ID, MTP_PROPERTY_OBJECT_FORMAT, MTP_PROPERTY_PROTECTION_STATUS, MTP_PROPERTY_OBJECT_SIZE,
												MTP_PROPERTY_OBJECT_FILE_NAME, MTP_PROPERTY_DATE_MODIFIED, MTP_PROPERTY_PARENT_OBJECT, MTP_PROPERTY_PERSISTENT_UID,
												MTP_PROPERTY_NAME, MTP_PROPERTY_DISPLAY_NAME, MTP_PROPERTY_DATE_CREATED, MTP_PROPERTY_DESCRIPTION, MTP_PROPERTY_WIDTH,
												MTP_PROPERTY_HEIGHT, MTP_PROPERTY_DATE_AUTHORED,
												0xFFFF}
	},
	{ MTP_FORMAT_WMA          , (uint16_t[]){   MTP_PROPERTY_STORAGE_ID, MTP_PROPERTY_OBJECT_FORMAT, MTP_PROPERTY_PROTECTION_STATUS, MTP_PROPERTY_OBJECT_SIZE,
												MTP_PROPERTY_OBJECT_FILE_NAME, MTP_PROPERTY_DATE_MODIFIED, MTP_PROPERTY_PARENT_OBJECT, MTP_PROPERTY_PERSISTENT_UID,
												MTP_PROPERTY_NAME, MTP_PROPERTY_DISPLAY_NAME, MTP_PROPERTY_DATE_CREATED, MTP_PROPERTY_ARTIST, MTP_PROPERTY_ALBUM_NAME,
												MTP_PROPERTY_ALBUM_ARTIST, MTP_PROPERTY_TRACK, MTP_PROPERTY_ORIGINAL_RELEASE_DATE, MTP_PROPERTY_DURATION, MTP_PROPERTY_DESCRIPTION,
												MTP_PROPERTY_GENRE, MTP_PROPERTY_COMPOSER, MTP_PROPERTY_AUDIO_WAVE_CODEC, MTP_PROPERTY_BITRATE_TYPE, MTP_PROPERTY_AUDIO_BITRATE,
												MTP_PROPERTY_NUMBER_OF_CHANNELS, MTP_PROPERTY_SAMPLE_RATE,
												0xFFFF}
	},
	{ MTP_FORMAT_OGG          , (uint16_t[]){   MTP_PROPERTY_STORAGE_ID, MTP_PROPERTY_OBJECT_FORMAT, MTP_PROPERTY_PROTECTION_STATUS, MTP_PROPERTY_OBJECT_SIZE,
												MTP_PROPERTY_OBJECT_FILE_NAME, MTP_PROPERTY_DATE_MODIFIED, MTP_PROPERTY_PARENT_OBJECT, MTP_PROPERTY_PERSISTENT_UID,
												MTP_PROPERTY_NAME, MTP_PROPERTY_DISPLAY_NAME, MTP_PROPERTY_DATE_CREATED, MTP_PROPERTY_ARTIST, MTP_PROPERTY_ALBUM_NAME,
												MTP_PROPERTY_ALBUM_ARTIST, MTP_PROPERTY_TRACK, MTP_PROPERTY_ORIGINAL_RELEASE_DATE, MTP_PROPERTY_DURATION, MTP_PROPERTY_DESCRIPTION,
												MTP_PROPERTY_GENRE, MTP_PROPERTY_COMPOSER, MTP_PROPERTY_AUDIO_WAVE_CODEC, MTP_PROPERTY_BITRATE_TYPE, MTP_PROPERTY_AUDIO_BITRATE,
												MTP_PROPERTY_NUMBER_OF_CHANNELS, MTP_PROPERTY_SAMPLE_RATE,
												0xFFFF}
	},
	{ MTP_FORMAT_AAC          , (uint16_t[]){   MTP_PROPERTY_STORAGE_ID, MTP_PROPERTY_OBJECT_FORMAT, MTP_PROPERTY_PROTECTION_STATUS, MTP_PROPERTY_OBJECT_SIZE,
												MTP_PROPERTY_OBJECT_FILE_NAME, MTP_PROPERTY_DATE_MODIFIED, MTP_PROPERTY_PARENT_OBJECT, MTP_PROPERTY_PERSISTENT_UID,
												MTP_PROPERTY_NAME, MTP_PROPERTY_DISPLAY_NAME, MTP_PROPERTY_DATE_CREATED, MTP_PROPERTY_ARTIST, MTP_PROPERTY_ALBUM_NAME,
												MTP_PROPERTY_ALBUM_ARTIST, MTP_PROPERTY_TRACK, MTP_PROPERTY_ORIGINAL_RELEASE_DATE, MTP_PROPERTY_DURATION, MTP_PROPERTY_DESCRIPTION,
												MTP_PROPERTY_GENRE, MTP_PROPERTY_COMPOSER, MTP_PROPERTY_AUDIO_WAVE_CODEC, MTP_PROPERTY_BITRATE_TYPE, MTP_PROPERTY_AUDIO_BITRATE,
												MTP_PROPERTY_NUMBER_OF_CHANNELS, MTP_PROPERTY_SAMPLE_RATE,
												0xFFFF}
	},
	{ MTP_FORMAT_ABSTRACT_AV_PLAYLIST, (uint16_t[]){   MTP_PROPERTY_STORAGE_ID, MTP_PROPERTY_OBJECT_FORMAT, MTP_PROPERTY_PROTECTION_STATUS, MTP_PROPERTY_OBJECT_SIZE,
												MTP_PROPERTY_OBJECT_FILE_NAME, MTP_PROPERTY_DATE_MODIFIED, MTP_PROPERTY_PARENT_OBJECT, MTP_PROPERTY_PERSISTENT_UID,
												MTP_PROPERTY_NAME, MTP_PROPERTY_DISPLAY_NAME, MTP_PROPERTY_DATE_CREATED,
												0xFFFF}
	},
	{ MTP_FORMAT_WPL_PLAYLIST,  (uint16_t[]){   MTP_PROPERTY_STORAGE_ID, MTP_PROPERTY_OBJECT_FORMAT, MTP_PROPERTY_PROTECTION_STATUS, MTP_PROPERTY_OBJECT_SIZE,
												MTP_PROPERTY_OBJECT_FILE_NAME, MTP_PROPERTY_DATE_MODIFIED, MTP_PROPERTY_PARENT_OBJECT, MTP_PROPERTY_PERSISTENT_UID,
												MTP_PROPERTY_NAME, MTP_PROPERTY_DISPLAY_NAME, MTP_PROPERTY_DATE_CREATED,
												0xFFFF}
	},
	{ MTP_FORMAT_M3U_PLAYLIST,  (uint16_t[]){   MTP_PROPERTY_STORAGE_ID, MTP_PROPERTY_OBJECT_FORMAT, MTP_PROPERTY_PROTECTION_STATUS, MTP_PROPERTY_OBJECT_SIZE,
												MTP_PROPERTY_OBJECT_FILE_NAME, MTP_PROPERTY_DATE_MODIFIED, MTP_PROPERTY_PARENT_OBJECT, MTP_PROPERTY_PERSISTENT_UID,
												MTP_PROPERTY_NAME, MTP_PROPERTY_DISPLAY_NAME, MTP_PROPERTY_DATE_CREATED,
												0xFFFF}
	},
	{ MTP_FORMAT_PLS_PLAYLIST,  (uint16_t[]){   MTP_PROPERTY_STORAGE_ID, MTP_PROPERTY_OBJECT_FORMAT, MTP_PROPERTY_PROTECTION_STATUS, MTP_PROPERTY_OBJECT_SIZE,
												MTP_PROPERTY_OBJECT_FILE_NAME, MTP_PROPERTY_DATE_MODIFIED, MTP_PROPERTY_PARENT_OBJECT, MTP_PROPERTY_PERSISTENT_UID,
												MTP_PROPERTY_NAME, MTP_PROPERTY_DISPLAY_NAME, MTP_PROPERTY_DATE_CREATED,
												0xFFFF}
	},
	{ MTP_FORMAT_XML_DOCUMENT,  (uint16_t[]){   MTP_PROPERTY_STORAGE_ID, MTP_PROPERTY_OBJECT_FORMAT, MTP_PROPERTY_PROTECTION_STATUS, MTP_PROPERTY_OBJECT_SIZE,
												MTP_PROPERTY_OBJECT_FILE_NAME, MTP_PROPERTY_DATE_MODIFIED, MTP_PROPERTY_PARENT_OBJECT, MTP_PROPERTY_PERSISTENT_UID,
												MTP_PROPERTY_NAME, MTP_PROPERTY_DISPLAY_NAME, MTP_PROPERTY_DATE_CREATED,
												0xFFFF}
	},
	{ MTP_FORMAT_FLAC        ,  (uint16_t[]){   MTP_PROPERTY_STORAGE_ID, MTP_PROPERTY_OBJECT_FORMAT, MTP_PROPERTY_PROTECTION_STATUS, MTP_PROPERTY_OBJECT_SIZE,
												MTP_PROPERTY_OBJECT_FILE_NAME, MTP_PROPERTY_DATE_MODIFIED, MTP_PROPERTY_PARENT_OBJECT, MTP_PROPERTY_PERSISTENT_UID,
												MTP_PROPERTY_NAME, MTP_PROPERTY_DISPLAY_NAME, MTP_PROPERTY_DATE_CREATED,
												0xFFFF}
	},
	{ MTP_FORMAT_AVI          , (uint16_t[]){   MTP_PROPERTY_STORAGE_ID, MTP_PROPERTY_OBJECT_FORMAT, MTP_PROPERTY_PROTECTION_STATUS, MTP_PROPERTY_OBJECT_SIZE,
												MTP_PROPERTY_OBJECT_FILE_NAME, MTP_PROPERTY_DATE_MODIFIED, MTP_PROPERTY_PARENT_OBJECT, MTP_PROPERTY_PERSISTENT_UID,
												MTP_PROPERTY_NAME, MTP_PROPERTY_DISPLAY_NAME, MTP_PROPERTY_DATE_CREATED, MTP_PROPERTY_ARTIST, MTP_PROPERTY_ALBUM_NAME,
												MTP_PROPERTY_DURATION, MTP_PROPERTY_DESCRIPTION, MTP_PROPERTY_WIDTH, MTP_PROPERTY_HEIGHT, MTP_PROPERTY_DATE_AUTHORED,
												0xFFFF}
	},
	{ MTP_FORMAT_ASF          , (uint16_t[]){   MTP_PROPERTY_STORAGE_ID, MTP_PROPERTY_OBJECT_FORMAT, MTP_PROPERTY_PROTECTION_STATUS, MTP_PROPERTY_OBJECT_SIZE,
												MTP_PROPERTY_OBJECT_FILE_NAME, MTP_PROPERTY_DATE_MODIFIED, MTP_PROPERTY_PARENT_OBJECT, MTP_PROPERTY_PERSISTENT_UID,
												MTP_PROPERTY_NAME, MTP_PROPERTY_DISPLAY_NAME, MTP_PROPERTY_DATE_CREATED, MTP_PROPERTY_ARTIST, MTP_PROPERTY_ALBUM_NAME,
												MTP_PROPERTY_DURATION, MTP_PROPERTY_DESCRIPTION, MTP_PROPERTY_WIDTH, MTP_PROPERTY_HEIGHT, MTP_PROPERTY_DATE_AUTHORED,
												0xFFFF}
	},
	{ MTP_FORMAT_MS_WORD_DOCUMENT, (uint16_t[]){   MTP_PROPERTY_STORAGE_ID, MTP_PROPERTY_OBJECT_FORMAT, MTP_PROPERTY_PROTECTION_STATUS, MTP_PROPERTY_OBJECT_SIZE,
												MTP_PROPERTY_OBJECT_FILE_NAME, MTP_PROPERTY_DATE_MODIFIED, MTP_PROPERTY_PARENT_OBJECT, MTP_PROPERTY_PERSISTENT_UID,
												MTP_PROPERTY_NAME, MTP_PROPERTY_DISPLAY_NAME, MTP_PROPERTY_DATE_CREATED,
												0xFFFF}
	},
	{ MTP_FORMAT_MS_EXCEL_SPREADSHEET, (uint16_t[]){   MTP_PROPERTY_STORAGE_ID, MTP_PROPERTY_OBJECT_FORMAT, MTP_PROPERTY_PROTECTION_STATUS, MTP_PROPERTY_OBJECT_SIZE,
												MTP_PROPERTY_OBJECT_FILE_NAME, MTP_PROPERTY_DATE_MODIFIED, MTP_PROPERTY_PARENT_OBJECT, MTP_PROPERTY_PERSISTENT_UID,
												MTP_PROPERTY_NAME, MTP_PROPERTY_DISPLAY_NAME, MTP_PROPERTY_DATE_CREATED,
												0xFFFF}
	},
	{ MTP_FORMAT_MS_POWERPOINT_PRESENTATION, (uint16_t[]){   MTP_PROPERTY_STORAGE_ID, MTP_PROPERTY_OBJECT_FORMAT, MTP_PROPERTY_PROTECTION_STATUS, MTP_PROPERTY_OBJECT_SIZE,
												MTP_PROPERTY_OBJECT_FILE_NAME, MTP_PROPERTY_DATE_MODIFIED, MTP_PROPERTY_PARENT_OBJECT, MTP_PROPERTY_PERSISTENT_UID,
												MTP_PROPERTY_NAME, MTP_PROPERTY_DISPLAY_NAME, MTP_PROPERTY_DATE_CREATED,
												0xFFFF}
	}
#endif
    ,

    { 0xFFFF, (uint16_t[]){ 0xFFFF } }

};

const profile_property support_object_properties[] = {
    // prop_code               data_type      getset    default_value group_code  form_flag format_code
    { MTP_PROPERTY_STORAGE_ID, MTP_TYPE_UINT32, 0x00, 0x00000000, 0x000000001, 0x00, 0xFFFF },
    { MTP_PROPERTY_OBJECT_FORMAT, MTP_TYPE_UINT16, 0x00, MTP_FORMAT_UNDEFINED, 0x000000000, 0x00, MTP_FORMAT_UNDEFINED },
    { MTP_PROPERTY_OBJECT_FORMAT, MTP_TYPE_UINT16, 0x00, MTP_FORMAT_ASSOCIATION, 0x000000000, 0x00, MTP_FORMAT_ASSOCIATION },
    { MTP_PROPERTY_OBJECT_FORMAT, MTP_TYPE_UINT16, 0x00, MTP_FORMAT_TEXT, 0x000000000, 0x00, MTP_FORMAT_TEXT },
    { MTP_PROPERTY_OBJECT_FORMAT, MTP_TYPE_UINT16, 0x00, MTP_FORMAT_HTML, 0x000000000, 0x00, MTP_FORMAT_HTML },
    { MTP_PROPERTY_OBJECT_FORMAT, MTP_TYPE_UINT16, 0x00, MTP_FORMAT_WAV, 0x000000000, 0x00, MTP_FORMAT_WAV },
    { MTP_PROPERTY_OBJECT_FORMAT, MTP_TYPE_UINT16, 0x00, MTP_FORMAT_MP3, 0x000000000, 0x00, MTP_FORMAT_MP3 },
    { MTP_PROPERTY_OBJECT_FORMAT, MTP_TYPE_UINT16, 0x00, MTP_FORMAT_MPEG, 0x000000000, 0x00, MTP_FORMAT_MPEG },
    { MTP_PROPERTY_OBJECT_FORMAT, MTP_TYPE_UINT16, 0x00, MTP_FORMAT_EXIF_JPEG, 0x000000000, 0x00, MTP_FORMAT_EXIF_JPEG },
    { MTP_PROPERTY_OBJECT_FORMAT, MTP_TYPE_UINT16, 0x00, MTP_FORMAT_BMP, 0x000000000, 0x00, MTP_FORMAT_BMP },
    { MTP_PROPERTY_OBJECT_FORMAT, MTP_TYPE_UINT16, 0x00, MTP_FORMAT_AIFF, 0x000000000, 0x00, MTP_FORMAT_AIFF },
    { MTP_PROPERTY_OBJECT_FORMAT, MTP_TYPE_UINT16, 0x00, MTP_FORMAT_MPEG, 0x000000000, 0x00, MTP_FORMAT_MPEG },
    { MTP_PROPERTY_OBJECT_FORMAT, MTP_TYPE_UINT16, 0x00, MTP_FORMAT_WMA, 0x000000000, 0x00, MTP_FORMAT_WMA },
    { MTP_PROPERTY_OBJECT_FORMAT, MTP_TYPE_UINT16, 0x00, MTP_FORMAT_OGG, 0x000000000, 0x00, MTP_FORMAT_OGG },
    { MTP_PROPERTY_OBJECT_FORMAT, MTP_TYPE_UINT16, 0x00, MTP_FORMAT_AAC, 0x000000000, 0x00, MTP_FORMAT_AAC },
    { MTP_PROPERTY_OBJECT_FORMAT, MTP_TYPE_UINT16, 0x00, MTP_FORMAT_MP4_CONTAINER, 0x000000000, 0x00, MTP_FORMAT_MP4_CONTAINER },
    { MTP_PROPERTY_OBJECT_FORMAT, MTP_TYPE_UINT16, 0x00, MTP_FORMAT_3GP_CONTAINER, 0x000000000, 0x00, MTP_FORMAT_3GP_CONTAINER },
    { MTP_PROPERTY_OBJECT_FORMAT, MTP_TYPE_UINT16, 0x00, MTP_FORMAT_ABSTRACT_AV_PLAYLIST, 0x000000000, 0x00, MTP_FORMAT_ABSTRACT_AV_PLAYLIST },
    { MTP_PROPERTY_OBJECT_FORMAT, MTP_TYPE_UINT16, 0x00, MTP_FORMAT_WPL_PLAYLIST, 0x000000000, 0x00, MTP_FORMAT_WPL_PLAYLIST },
    { MTP_PROPERTY_OBJECT_FORMAT, MTP_TYPE_UINT16, 0x00, MTP_FORMAT_M3U_PLAYLIST, 0x000000000, 0x00, MTP_FORMAT_M3U_PLAYLIST },
    { MTP_PROPERTY_OBJECT_FORMAT, MTP_TYPE_UINT16, 0x00, MTP_FORMAT_PLS_PLAYLIST, 0x000000000, 0x00, MTP_FORMAT_PLS_PLAYLIST },
    { MTP_PROPERTY_OBJECT_FORMAT, MTP_TYPE_UINT16, 0x00, MTP_FORMAT_XML_DOCUMENT, 0x000000000, 0x00, MTP_FORMAT_XML_DOCUMENT },
    { MTP_PROPERTY_OBJECT_FORMAT, MTP_TYPE_UINT16, 0x00, MTP_FORMAT_FLAC, 0x000000000, 0x00, MTP_FORMAT_FLAC },
    { MTP_PROPERTY_OBJECT_FORMAT, MTP_TYPE_UINT16, 0x00, MTP_FORMAT_AVI, 0x000000000, 0x00, MTP_FORMAT_AVI },
    { MTP_PROPERTY_OBJECT_FORMAT, MTP_TYPE_UINT16, 0x00, MTP_FORMAT_ASF, 0x000000000, 0x00, MTP_FORMAT_ASF },
    { MTP_PROPERTY_OBJECT_FORMAT, MTP_TYPE_UINT16, 0x00, MTP_FORMAT_MS_WORD_DOCUMENT, 0x000000000, 0x00, MTP_FORMAT_MS_WORD_DOCUMENT },
    { MTP_PROPERTY_OBJECT_FORMAT, MTP_TYPE_UINT16, 0x00, MTP_FORMAT_MS_EXCEL_SPREADSHEET, 0x000000000, 0x00, MTP_FORMAT_MS_EXCEL_SPREADSHEET },
    { MTP_PROPERTY_OBJECT_FORMAT, MTP_TYPE_UINT16, 0x00, MTP_FORMAT_MS_POWERPOINT_PRESENTATION, 0x000000000, 0x00, MTP_FORMAT_MS_POWERPOINT_PRESENTATION },

    { MTP_PROPERTY_OBJECT_SIZE, MTP_TYPE_UINT64, 0x00, 0x0000000000000000, 0x000000000, 0x00, MTP_FORMAT_ASSOCIATION },
    { MTP_PROPERTY_STORAGE_ID, MTP_TYPE_UINT32, 0x00, 0x00000000, 0x000000000, 0x00, MTP_FORMAT_ASSOCIATION },
    { MTP_PROPERTY_PROTECTION_STATUS, MTP_TYPE_UINT16, 0x00, 0x0000, 0x000000000, 0x00, MTP_FORMAT_ASSOCIATION },
    { MTP_PROPERTY_DISPLAY_NAME, MTP_TYPE_STR, 0x00, 0x0000, 0x000000000, 0x00, MTP_FORMAT_ASSOCIATION },
    { MTP_PROPERTY_OBJECT_FILE_NAME, MTP_TYPE_STR, 0x01, 0x0000, 0x000000000, 0x00, MTP_FORMAT_ASSOCIATION },
    { MTP_PROPERTY_DATE_CREATED, MTP_TYPE_STR, 0x00, 0x00, 0x000000000, 0x00, MTP_FORMAT_ASSOCIATION },
    { MTP_PROPERTY_DATE_MODIFIED, MTP_TYPE_STR, 0x00, 0x00, 0x000000000, 0x00, MTP_FORMAT_ASSOCIATION },
    { MTP_PROPERTY_PARENT_OBJECT, MTP_TYPE_UINT32, 0x00, 0x00000000, 0x000000000, 0x00, MTP_FORMAT_ASSOCIATION },
    { MTP_PROPERTY_PERSISTENT_UID, MTP_TYPE_UINT128, 0x00, 0x00, 0x000000000, 0x00, MTP_FORMAT_ASSOCIATION },
    { MTP_PROPERTY_NAME, MTP_TYPE_STR, 0x00, 0x00, 0x000000000, 0x00, MTP_FORMAT_ASSOCIATION },

    { MTP_PROPERTY_OBJECT_SIZE, MTP_TYPE_UINT64, 0x00, 0x0000000000000000, 0x000000000, 0x00, MTP_FORMAT_UNDEFINED },
    { MTP_PROPERTY_STORAGE_ID, MTP_TYPE_UINT32, 0x00, 0x00000000, 0x000000000, 0x00, MTP_FORMAT_UNDEFINED },
    { MTP_PROPERTY_PROTECTION_STATUS, MTP_TYPE_UINT16, 0x00, 0x0000, 0x000000000, 0x00, MTP_FORMAT_UNDEFINED },
    { MTP_PROPERTY_DISPLAY_NAME, MTP_TYPE_STR, 0x00, 0x0000, 0x000000000, 0x00, MTP_FORMAT_UNDEFINED },
    { MTP_PROPERTY_OBJECT_FILE_NAME, MTP_TYPE_STR, 0x01, 0x0000, 0x000000000, 0x00, MTP_FORMAT_UNDEFINED },
    { MTP_PROPERTY_DATE_CREATED, MTP_TYPE_STR, 0x00, 0x00, 0x000000000, 0x00, MTP_FORMAT_UNDEFINED },
    { MTP_PROPERTY_DATE_MODIFIED, MTP_TYPE_STR, 0x00, 0x00, 0x000000000, 0x00, MTP_FORMAT_UNDEFINED },
    { MTP_PROPERTY_PARENT_OBJECT, MTP_TYPE_UINT32, 0x00, 0x00000000, 0x000000000, 0x00, MTP_FORMAT_UNDEFINED },
    { MTP_PROPERTY_PERSISTENT_UID, MTP_TYPE_UINT128, 0x00, 0x00, 0x000000000, 0x00, MTP_FORMAT_UNDEFINED },
    { MTP_PROPERTY_NAME, MTP_TYPE_STR, 0x00, 0x00, 0x000000000, 0x00, MTP_FORMAT_UNDEFINED },

    //{MTP_PROPERTY_ASSOCIATION_TYPE,    MTP_TYPE_UINT16,    0x00,   0x0001             , 0x000000000 , 0x00 , 0xFFFF },
    { MTP_PROPERTY_ASSOCIATION_DESC, MTP_TYPE_UINT32, 0x00, 0x00000000, 0x000000000, 0x00, 0xFFFF },
    { MTP_PROPERTY_PROTECTION_STATUS, MTP_TYPE_UINT16, 0x00, 0x0000, 0x000000000, 0x00, 0xFFFF },
    { MTP_PROPERTY_HIDDEN, MTP_TYPE_UINT16, 0x00, 0x0000, 0x000000000, 0x00, 0xFFFF },

	// 特殊指定
    // { MTP_PROPERTY_OBJECT_SIZE, MTP_TYPE_UINT64, 0x00, MTP_FORMAT_TEXT, 0x000000000, 0x00, MTP_FORMAT_TEXT },
    // { MTP_PROPERTY_STORAGE_ID, MTP_TYPE_UINT32, 0x00, MTP_FORMAT_TEXT, 0x000000000, 0x00, MTP_FORMAT_TEXT },
    // { MTP_PROPERTY_PROTECTION_STATUS, MTP_TYPE_UINT16, 0x00, MTP_FORMAT_TEXT, 0x000000000, 0x00, MTP_FORMAT_TEXT },
    // { MTP_PROPERTY_DISPLAY_NAME, MTP_TYPE_STR, 0x00, MTP_FORMAT_TEXT, 0x000000000, 0x00, MTP_FORMAT_TEXT },
    // { MTP_PROPERTY_OBJECT_FILE_NAME, MTP_TYPE_STR, 0x01, MTP_FORMAT_TEXT, 0x000000000, 0x00, MTP_FORMAT_TEXT },
    // { MTP_PROPERTY_DATE_CREATED, MTP_TYPE_STR, 0x00, MTP_FORMAT_TEXT, 0x000000000, 0x00, MTP_FORMAT_TEXT },
    // { MTP_PROPERTY_DATE_MODIFIED, MTP_TYPE_STR, 0x00, MTP_FORMAT_TEXT, 0x000000000, 0x00, MTP_FORMAT_TEXT },
    // { MTP_PROPERTY_PARENT_OBJECT, MTP_TYPE_UINT32, 0x00, MTP_FORMAT_TEXT, 0x000000000, 0x00, MTP_FORMAT_TEXT },
    // { MTP_PROPERTY_PERSISTENT_UID, MTP_TYPE_UINT128, 0x00, MTP_FORMAT_TEXT, 0x000000000, 0x00, MTP_FORMAT_TEXT },
    // { MTP_PROPERTY_NAME, MTP_TYPE_STR, 0x00, MTP_FORMAT_TEXT, 0x000000000, 0x00, MTP_FORMAT_TEXT },

    { 0xFFFF, MTP_TYPE_UINT32, 0x00, 0x00000000, 0x000000000, 0x00 }
};

const profile_property support_device_properties[] = {
    { MTP_DEVICE_PROPERTY_SYNCHRONIZATION_PARTNER, MTP_TYPE_UINT32, 0x00, 0, 0, 0x00 },
    { MTP_DEVICE_PROPERTY_DEVICE_FRIENDLY_NAME,    MTP_TYPE_STR,    0x00, 0, 0, 0x00 },
    { MTP_DEVICE_PROPERTY_IMAGE_SIZE,              MTP_TYPE_STR,    0x00, 0, 0, 0x00 },
    // { MTP_DEVICE_PROPERTY_BATTERY_LEVEL,           MTP_TYPE_UINT8,  0x00, 0, 0, 0x00 },
    // { MTP_DEVICE_PROPERTY_PERCEIVED_DEVICE_TYPE,   MTP_TYPE_UINT32, 0x00, 0, 0, 0x00 },
    // { MTP_DEVICE_PROPERTY_SESSION_INITIATOR_VERSION_INFO, MTP_TYPE_STR, 0x00, 0, 0, 0x00 },
    { 0xFFFF, MTP_TYPE_UINT32, 0x00, 0, 0, 0x00 }
};

// 常见图片、音频、视频、文档格式，参考安卓手机和U盘MTP响应
const uint16_t supported_capture_formats[] = {
    MTP_FORMAT_UNDEFINED, 
    0x3801, 
    // 0x3804, 
    /*MTP_FORMAT_GIF,*/ 
    // MTP_FORMAT_JFIF, 
    // MTP_FORMAT_PNG, 
    // 0x380D, 0x380E
};

const uint16_t supported_playback_formats[] = {
    MTP_FORMAT_UNDEFINED, MTP_FORMAT_ASSOCIATION, MTP_FORMAT_TEXT, 
    // 0x3005, 0x3008, 0x3009, 0x300B,
    // 0x3801, 0x3804, 
    /*MTP_FORMAT_GIF,*/ 
    // MTP_FORMAT_JFIF, 
    // MTP_FORMAT_PNG, 
    // 0x380D, 0x380E, 0x3810, 0x3811, 0x3812, 0x3813, 0x3814, 0x3815
};
#define SUPPORTED_CAPTURE_FORMATS_COUNT (sizeof(supported_capture_formats)/sizeof(supported_capture_formats[0]))
#define SUPPORTED_PLAYBACK_FORMATS_COUNT (sizeof(supported_playback_formats)/sizeof(supported_playback_formats[0]))

#define MTP_MANUFACTURER_STRING   "CherryUSB"
#define MTP_MODEL_STRING          "CherryUSB MTP"
#define MTP_DEVICE_VERSION_STRING "1.0"
#define MTP_SERIAL_NUMBER_STRING  "1234567890"

#endif