cmake_minimum_required(VERSION 3.22.1)

project(standaloneencodersurfacebridge)

add_library(
    standaloneencodersurfacebridge
    SHARED
    ../../../../../../../NativeSources/StandaloneVideoEncoderPlugin/src/main/cpp/StandaloneEncoderSurfaceBridge.cpp
)

find_library(log-lib log)
find_library(android-lib android)
find_library(EGL-lib EGL)
find_library(GLESv3-lib GLESv3)
find_library(cpp-shared-lib c++_shared)

target_link_libraries(
    standaloneencodersurfacebridge
    ${log-lib}
    ${android-lib}
    ${EGL-lib}
    ${GLESv3-lib}
    ${cpp-shared-lib}
)
