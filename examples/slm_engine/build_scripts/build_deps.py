#!/usr/bin/env python3
import glob
import os
import argparse
import platform
import shutil
import subprocess
import sys
import time

BLUE = "\033[34m"
MAGENTA = "\033[35m"
RED = "\033[31m"
CLEAR = "\033[0m"


def cmake_options_android(ndk_dir):
    if not os.path.exists(ndk_dir):
        raise Exception(f"NDK Directory doesn't exist: {ndk_dir}")
    cmake_option = [
        f"-DCMAKE_TOOLCHAIN_FILE={ndk_dir}/build/cmake/android.toolchain.cmake",
        "-DANDROID_PLATFORM=android-33",
        "-DANDROID_ABI=arm64-v8a",
    ]
    return cmake_option


def get_platform_dirname(args):
    # Get the name of the OS

    platform_name = platform.system()
    if platform_name == "Darwin":
        platform_name = "MacOS"

    if args.android:
        platform_name = "Android"

    return platform_name


def get_target_specific_oga_build_dirname():
    # Get the name of the OS
    platform_name = platform.system()
    if platform_name == "Darwin":
        platform_name = "macOS"

    return platform_name


def get_machine_type(args):
    machine_type = platform.machine()
    if args.android:
        machine_type = "aarch64"

    return machine_type


def copy_files_without_hidden(src, dest):
    """
    Recursively copies files from the source directory to the destination directory,
    excluding hidden files and directories.

    Args:
      src: Path to the source directory.
      dest: Path to the destination directory.
    """
    try:
        os.makedirs(
            dest, exist_ok=True
        )  # Create destination directory if it doesn't exist

        for root, dirs, files in os.walk(src):
            for file in files:
                if not file.startswith("."):  # Exclude hidden files
                    src_file = os.path.join(root, file)
                    dest_file = os.path.join(dest, os.path.relpath(src_file, src))
                    os.makedirs(
                        os.path.dirname(dest_file), exist_ok=True
                    )  # Create necessary directories
                    shutil.copy2(src_file, dest_file)

    except OSError as e:
        print(f"Error: {e}")
        raise e


def copy_files_keeping_symlinks(src_files, dest):
    if not type(src_files) == list:
        raise Exception("src_files must be a list")

    for file in src_files:
        # Preserve symlinks
        if os.path.islink(file):
            # Get the name of the link without the rest of the path
            linkname = f"{dest}/{os.path.basename(file)}"
            linkto = os.readlink(file)

            if not os.path.exists(linkname):
                os.symlink(linkto, linkname)
        elif os.path.isdir(file):
            shutil.copytree(
                file, f"{dest}/{os.path.basename(file)}", dirs_exist_ok=True
            )
        else:
            shutil.copy2(file, dest)


def copy_artifacts(args, artifacts_dir):
    """
    Copy the artifacts from the prebuilt directory to the artifacts directory
    """
    # Determine the top level directory
    top_level_dir = f"{os.path.dirname(os.path.realpath(__file__))}/../../../"
    target_specific_dir = f"{top_level_dir}/build/{get_target_specific_oga_build_dirname()}/{args.build_type}/_deps/ortlib-src"
    src_include_dir = os.path.abspath(f"{target_specific_dir}/build/native/include")

    # Get the platform and machine type
    platform_name = platform.system()
    if platform_name == "Darwin":
        platform_name = "osx"
    elif platform_name == "Linux":
        platform_name = "linux"
    elif platform_name == "Windows":
        platform_name = "win"

    machine_type = platform.machine()
    if machine_type == "x86_64":
        machine_type = "x64"
    elif machine_type == "aarch64":
        machine_type = "arm64"
    elif machine_type == "x86":
        machine_type = "x86"
    elif machine_type.lower() == "amd64":
        machine_type = "x64"
    elif machine_type.lower() == "arm64":
        machine_type = "arm64"

    src_lib_dir = os.path.abspath(
        f"{target_specific_dir}/runtimes/{platform_name}-{machine_type}/native"
    )
    print(f"Copying Source Lib Dir: {src_lib_dir}")
    copy_files_keeping_symlinks(
        glob.glob(f"{src_lib_dir}/*"),
        f"{artifacts_dir}/lib",
    )

    print(f"Source Include Dir: {src_include_dir}")
    os.makedirs(f"{artifacts_dir}/include/onnxruntime", exist_ok=True)
    copy_files_keeping_symlinks(
        glob.glob(f"{src_include_dir}/*"),
        f"{artifacts_dir}/include/onnxruntime",
    )


def build_ort(args, build_dir, artifacts_dir):
    """
    Build the ONNX Runtime library and ORT-GenAI library
    """

    os.chdir(build_dir)

    # Make the src directory if needed
    os.makedirs("src", exist_ok=True)
    os.chdir("src")

    if not os.path.exists("onnxruntime"):
        # Clone the ORT Repo
        print("Cloning ONNX Runtime")
        if (
            subprocess.call(
                ["git", "clone", "https://github.com/microsoft/onnxruntime.git"]
            )
            != 0
        ):
            raise Exception("Failed to clone ONNX Runtime")

    # Now get the dependencies
    os.chdir("onnxruntime")

    # Checkout the correct version
    version = args.ort_version_to_use
    print(f"Checking out ONNX Runtime version: {version}")
    if subprocess.call(["git", "fetch", "--tags", "origin"]) != 0:
        raise Exception("Failed to fetch tags for ONNX Runtime")
    if subprocess.call(["git", "checkout", version]) != 0:
        raise Exception("Failed to checkout ONNX Runtime version")

    if (
        subprocess.call(
            [
                "git",
                "submodule",
                "update",
                "--init",
                "--recursive",
            ]
        )
        != 0
    ):
        raise Exception("Failed to  update ONNX Runtime submodules")

    # Return to the original directory
    os.chdir("../..")

    # Prepare the command arguments
    cmd_args = [
        "--build_shared_lib",
        "--skip_tests",
        "--parallel",
        "--config",
        args.build_type,
    ]
    if args.android:
        cmd_args.extend(
            [
                "--android",
                "--android_sdk_path",
                args.android_sdk_path,
                "--android_ndk_path",
                args.android_ndk_path,
                "--android_abi",
                "arm64-v8a",
                "--android_api",
                args.api_level,
            ]
        )
        if args.qnn_sdk_path:
            cmd_args.extend(["--use_qnn", "--qnn_home", args.qnn_sdk_path])

    # now build the ORT library
    print(f"{BLUE}Building ONNX Runtime{CLEAR}")
    os.chdir("src/onnxruntime")

    build_script = "build.bat" if platform.system() == "Windows" else "./build.sh"
    print(f"{BLUE}Running {build_script} with args: {cmd_args}{CLEAR}")
    result = subprocess.call([build_script] + cmd_args)
    if result != 0:
        raise Exception("Failed to build ONNX Runtime")

    # Now add the symbolic links
    # First save the current directory
    current_dir = os.getcwd()

    # Get the absolute path tot he build directory
    build_dir_name = f"build/{get_platform_dirname(args)}/{args.build_type}"
    build_dir_name = os.path.abspath(build_dir_name)
    ort_home = os.path.abspath(f"{build_dir_name}/install")
    print(f"{MAGENTA}ORT Home: {ort_home}{CLEAR}")

    os.chdir(build_dir_name)

    # Run install
    print(f"{MAGENTA}Running install{CLEAR}")
    result = subprocess.call(
        [
            "cmake",
            "--install",
            ".",
            "--prefix",
            ort_home,
        ]
    )

    if result != 0:
        raise Exception("Failed to install ONNX Runtime")

    # Now create the symbolic links only if Android Build
    os.chdir(ort_home)
    if args.android:
        # Create the symbolic links only in doesn't exist
        if not os.path.exists("headers"):
            os.symlink("include/onnxruntime", "headers")

        # Make the jni directory
        os.makedirs("jni", exist_ok=True)
        os.chdir("jni")
        if not os.path.exists("arm64-v8a"):
            os.symlink("../lib", "arm64-v8a")
        os.chdir("..")
    else:
        # Copy the include/onnxruntime/* to include directory
        copy_files_keeping_symlinks(
            glob.glob(f"include/onnxruntime/*"),
            f"include",
        )

        # If we are on Windows - then we need to copy the .dll files to the
        # lib directory as well
        if platform.system() == "Windows":
            copy_files_keeping_symlinks(
                glob.glob(f"bin/*.dll"),
                f"lib",
            )

    print(f"{MAGENTA}Copying ORT artifacts to 3P Artifacts: {artifacts_dir}{CLEAR}")
    os.makedirs(artifacts_dir, exist_ok=True)
    copy_files_keeping_symlinks(glob.glob(f"{ort_home}/*"), artifacts_dir)

    # Back to the original directory
    os.chdir(current_dir)

    return ort_home


def build_ort_genai(args, artifacts_dir, ort_home=None):

    # Navigate to the directory where this Python file is located
    os.chdir(os.path.dirname(os.path.realpath(__file__)))

    # Save the current directory
    current_dir = os.getcwd()

    # Go to the toplevel directory. To determine the top level directory, we need to
    # find the directory of this python file and then go from there
    top_level_dir = f"../../../"
    os.chdir(top_level_dir)

    if subprocess.call(["git", "submodule", "update", "--init", "--recursive"]) != 0:
        raise Exception("Failed to update submodules")

    # Now build the ORT-GenAI library
    print(f"{BLUE}Building ONNX Runtime-GenAI{CLEAR}")
    # Prepare the command arguments
    cmd_args = [
        "--skip_wheel",
        "--skip_tests",
        "--parallel",
        "--config",
        args.build_type,
        "--cmake_extra_defines",
        "ENABLE_PYTHON=OFF",
    ]
    if ort_home is not None:
        cmd_args.extend(["--ort_home", ort_home])

    if args.android:
        cmd_args.extend(
            [
                "--android",
                "--android_home",
                args.android_sdk_path,
                "--android_ndk_path",
                args.android_ndk_path,
                "--android_abi",
                "arm64-v8a",
                "--android_api",
                args.api_level,
            ]
        )

    print(f"{BLUE}Running build.py with args: {cmd_args}{CLEAR}")
    python_executable = sys.executable
    result = subprocess.call([python_executable, "build.py"] + cmd_args)
    if result != 0:
        raise Exception(f"{RED}Failed to build ORT-GenAI{CLEAR}")

    # Now install the ORT-GenAI library
    build_dir_name = f"build/{get_platform_dirname(args)}/{args.build_type}"
    build_dir_name = os.path.abspath(build_dir_name)

    os.chdir(build_dir_name)

    # Run install
    print("Running install")
    result = subprocess.call(
        [
            "cmake",
            "--install",
            ".",
            "--prefix",
            f"{build_dir_name}/install",
        ]
    )

    if result != 0:
        print(f"Current Directory: {os.getcwd()}")
        raise Exception(f"{RED}Failed to install ONNX Runtime{CLEAR}")

    # Copy the artifacts only if ort_home is None
    if ort_home is not None:
        # Now copy the ORT Libs to the ORT-GenAI directory installation location
        dest_dir = f"{build_dir_name}/install/lib"
        copy_files_keeping_symlinks(
            glob.glob(f"{ort_home}/lib/*onnxruntime*"), dest_dir
        )

        # For Windows build, the .dll files are stored in the bin directory.
        # For Linux/Mac this is a no-op
        copy_files_keeping_symlinks(
            glob.glob(f"{ort_home}/bin/*onnxruntime*"), dest_dir
        )

    # The "current_dir" is the "build_scripts" directory.
    os.chdir(current_dir)

    os.makedirs(f"{artifacts_dir}/include", exist_ok=True)
    os.makedirs(f"{artifacts_dir}/lib", exist_ok=True)

    copy_files_keeping_symlinks(
        glob.glob(f"{build_dir_name}/install/lib/*"), f"{artifacts_dir}/lib"
    )
    copy_files_keeping_symlinks(
        glob.glob(f"{build_dir_name}/install/bin/*"), f"{artifacts_dir}/lib"
    )

    copy_files_keeping_symlinks(
        glob.glob(f"{build_dir_name}/install/include/*"),
        f"{artifacts_dir}/include",
    )
    print(f"{BLUE}Artifacts are available in: {artifacts_dir}{CLEAR}")

    print(f"{MAGENTA}ONNX Runtime Built{CLEAR}")


def build_header_only(args, build_dir, artifacts_dir):
    """
    Build the header-only libraries
    """
    # List of header-only libraries
    header_only_libs = [
        {
            "name": "json",
            "url": "https://github.com/nlohmann/json.git",
            "version": "v3.11.3",
            "common_dest": False,
            "directory": "include",
        },
        {
            "name": "argparse",
            "url": "https://github.com/p-ranav/argparse.git",
            "version": "v3.2",
            "common_dest": False,
            "directory": "include",
        },
        {
            "name": "cpp-httplib",
            "url": "https://github.com/yhirose/cpp-httplib.git",
            "version": "v0.18.5",
            "common_dest": True,
            "files": ["httplib.h"],
        },
    ]

    # Copy the headers to the artifacts directory
    dest_root_dir = os.path.abspath(f"{artifacts_dir}/include")

    os.chdir(build_dir)

    print(f"Current Directory: {os.getcwd()}")
    os.makedirs("src", exist_ok=True)

    for lib in header_only_libs:
        print(f"Building {lib['name']}")
        # Clone the repo
        if not os.path.exists(f"src/{lib['name']}"):
            # Clone the ORT Repo
            print(f"{BLUE}Cloning {lib['name']}{CLEAR}")
            os.chdir("src")
            result = subprocess.call(["git", "clone", lib["url"]])
            if result != 0:
                print(f"Failed to clone {lib['name']}")
                return
            os.chdir("..")

        # Go to src
        os.chdir("src")

        # Checkout the specific version
        os.chdir(lib["name"])
        result = subprocess.call(["git", "fetch", "--tags", "origin"])
        if result != 0:
            print(f"{RED}Failed to get tags for {lib['name']}{CLEAR}")
            return

        result = subprocess.call(["git", "checkout", lib["version"]])
        if result != 0:
            print(
                f"{RED}Failed to checkout version: {lib['version']} {lib['name']}{CLEAR}"
            )
            return

        if not os.path.exists(dest_root_dir):
            os.makedirs(dest_root_dir, exist_ok=True)

        # If the files key is defined, then copy the files
        if "files" in lib:
            for file in lib["files"]:
                shutil.copy2(file, dest_root_dir)
        elif "directory" in lib:
            os.chdir("..")
            copy_files_without_hidden(
                f"{lib['name']}/{lib['directory']}", dest_root_dir
            )
        else:
            # Copy the entire directory
            os.chdir("..")
            copy_files_without_hidden(lib["name"], dest_root_dir)

        # Return to the original directory
        os.chdir("..")
    print(f"{MAGENTA}Header Only Libraries Built{CLEAR}")
    print(f"{BLUE}Artifacts are available in: {dest_root_dir}{CLEAR}")


def main():
    parser = argparse.ArgumentParser(
        description="Build script for dependency libraries"
    )

    # Adding arguments
    parser.add_argument("--android_sdk_path", type=str, help="Path to ANDROID SDK")
    parser.add_argument("--android_ndk_path", type=str, help="Path to ANDROID NDK")
    parser.add_argument(
        "--api_level", type=str, help="Android API Level", default="27"
    )  # e.g., 29
    parser.add_argument(
        "--qnn_sdk_path",
        type=str,
        help="Path to Qualcomm QNN SDK (AI Engine Direct)",
    )
    parser.add_argument(
        "--build_type",
        type=str,
        default="Release",
        help="{Release|RelWithDebInfo|Debug}",
    )

    parser.add_argument(
        "--build_ort_from_source",
        action="store_true",
        help="If set, ONNX Runtime is built from source",
    )

    parser.add_argument(
        "--ort_version_to_use",
        type=str,
        help="ONNX Runtime version to use. Must be a git tag or branch",
    )

    # Parsing arguments
    args = parser.parse_args()

    if args.android_sdk_path or args.android_ndk_path:
        args.android = True
        # If the user didn't specify build_ort_from_source assert
        if not args.build_ort_from_source:
            raise Exception(
                "For Android build ONNX Runtime use: --build_ort_from_source"
            )
    else:
        args.android = False

    if args.ort_version_to_use is None:
        # If not Windows then use 1.20.2
        if platform.system() != "Windows":
            args.ort_version_to_use = "v1.20.2"
        else:
            args.ort_version_to_use = "main"

    # Change directory to where this Python file is located to avoid any issues
    # related to running this script from another directory
    os.chdir(os.path.dirname(os.path.realpath(__file__)))

    # The following directory contains the following directories:
    # - artifacts
    #   -- Contains the artifacts of onnxruntime and onnxruntime-genai
    #      This applies for both - downloaded or built from source
    # - slm_deps
    #   -- src
    #      Contains the source code of the dependencies. The repos downloaded here
    dep_src_dir = os.path.abspath("../../../build/slm_deps")
    os.makedirs(dep_src_dir, exist_ok=True)

    artifacts_dir = os.path.abspath(
        f"slm_deps/artifacts/{get_platform_dirname(args)}-{get_machine_type(args)}"
    )

    os.makedirs(artifacts_dir, exist_ok=True)

    common_artifacts_dir = os.path.abspath(f"slm_deps/artifacts/common")
    os.makedirs(common_artifacts_dir, exist_ok=True)

    time_build_start = time.time()
    # Initialize the ort_home to None. Default behavior is to download the
    # ONNX Runtime library and use that. If the user however chooses to build
    # the ONNX Runtime library from source (e.g., for Android or other embedded targets)
    # then we will use the location of the ort_home as set by the build_ort()
    ort_home = None
    if args.build_ort_from_source:
        ort_home = build_ort(args, dep_src_dir, artifacts_dir)

    # Now build the ORT-GenAI library
    build_ort_genai(args, artifacts_dir, ort_home)

    if not args.build_ort_from_source:
        # The ORT binaries are available as they were downloaded during the GenAI build
        # Copy the ORT artifacts to the artifacts directory
        copy_artifacts(args, artifacts_dir)

    # Now build the header-only libraries
    build_header_only(args, dep_src_dir, common_artifacts_dir)

    # Return to the original directory
    os.chdir("..")
    time_build_end = time.time()

    print(f"Build Time: {time_build_end - time_build_start:.2f} seconds")


if __name__ == "__main__":
    main()
