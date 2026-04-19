cmake_minimum_required(VERSION 3.22.1)

project(standaloneencodersurfacebridge)

add_library(
    standaloneencodersurfacebridge
    SHARED
    StandaloneEncoderSurfaceBridge.cpp
)

find_library(log-lib log)
find_library(android-lib android)
find_library(EGL-lib EGL)
find_library(GLESv3-lib GLESv3)

target_link_libraries(
    standaloneencodersurfacebridge
    ${log-lib}
    ${android-lib}
    ${EGL-lib}
    ${GLESv3-lib}
)
