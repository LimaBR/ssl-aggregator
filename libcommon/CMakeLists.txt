find_package(PkgConfig REQUIRED)
pkg_check_modules(PQXX REQUIRED IMPORTED_TARGET libpqxx)
find_package(Threads REQUIRED)

add_library(common STATIC
    src/udp_receiver.cpp
    src/udp_unicast_receiver.cpp
    src/timestamp.cpp
    src/config.cpp
    src/signal.cpp
)

target_include_directories(common PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)
target_link_libraries(common PUBLIC PkgConfig::PQXX Threads::Threads)
