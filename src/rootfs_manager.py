"""
RootFS Manager Module
Manages rootfs directory creation with proper permissions and extended ACLs.
"""

import os
import shutil
import subprocess
import stat
from pathlib import Path
from typing import Tuple, Optional

# Minimum required free space in GB
MIN_FREE_SPACE_GB = 20


class RootFSManager:
    """
    Manages the creation and permission setup of rootfs directories.
    """

    def __init__(self, base_path: str):
        """
        Initialize the RootFS manager.

        Args:
            base_path: Base path where rootfs directory will be created.
        """
        self.base_path = Path(base_path).resolve()
        self.rootfs_path = self.base_path / "rootfs"

    def check_filesystem_acl_support(self) -> Tuple[bool, str]:
        """
        Check if the filesystem supports extended ACLs.

        Returns:
            Tuple of (success, message)
        """
        try:
            # Check if setfacl command is available
            result = subprocess.run(
                ["which", "setfacl"],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                return False, "setfacl command not found. Install acl package."

            # Check if getfacl command is available
            result = subprocess.run(
                ["which", "getfacl"],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                return False, "getfacl command not found. Install acl package."

            # Create a test file to check ACL support on the filesystem
            test_file = self.base_path / ".acl_test"
            
            try:
                # Ensure base path exists
                self.base_path.mkdir(parents=True, exist_ok=True)
                
                # Create test file
                test_file.touch()
                
                # Try to set an ACL
                result = subprocess.run(
                    ["setfacl", "-m", f"u:{os.getuid()}:rwx", str(test_file)],
                    capture_output=True,
                    text=True
                )
                
                if result.returncode != 0:
                    return False, f"Filesystem does not support ACLs: {result.stderr}"
                
                return True, "Filesystem supports extended ACLs"
                
            finally:
                # Clean up test file
                if test_file.exists():
                    # Remove ACL first
                    subprocess.run(
                        ["setfacl", "-b", str(test_file)],
                        capture_output=True
                    )
                    test_file.unlink()
                    
        except Exception as e:
            return False, f"Error checking ACL support: {e}"

    def check_write_permission(self) -> Tuple[bool, str]:
        """
        Check if we can write to the base path.

        Returns:
            Tuple of (success, message)
        """
        try:
            # Ensure base path exists
            self.base_path.mkdir(parents=True, exist_ok=True)
            
            # Check if we can write
            if not os.access(self.base_path, os.W_OK):
                return False, f"No write permission on {self.base_path}"
            
            # Try to create a test directory
            test_dir = self.base_path / ".write_test"
            try:
                test_dir.mkdir()
                test_dir.rmdir()
                return True, f"Write permission verified on {self.base_path}"
            except PermissionError:
                return False, f"Cannot create directories in {self.base_path}"
                
        except Exception as e:
            return False, f"Error checking write permission: {e}"

    def check_free_space(self, min_gb: int = MIN_FREE_SPACE_GB) -> Tuple[bool, str]:
        """
        Check if the filesystem has at least the minimum required free space.

        Args:
            min_gb: Minimum required free space in gigabytes (default: 20GB)

        Returns:
            Tuple of (success, message)
        """
        try:
            # Ensure base path exists
            self.base_path.mkdir(parents=True, exist_ok=True)
            
            # Get disk usage statistics
            disk_usage = shutil.disk_usage(self.base_path)
            
            # Calculate free space in GB
            free_gb = disk_usage.free / (1024 ** 3)
            total_gb = disk_usage.total / (1024 ** 3)
            used_gb = disk_usage.used / (1024 ** 3)
            
            if free_gb >= min_gb:
                return True, (
                    f"Sufficient disk space: {free_gb:.1f}GB free "
                    f"(required: {min_gb}GB, total: {total_gb:.1f}GB)"
                )
            else:
                return False, (
                    f"Insufficient disk space: {free_gb:.1f}GB free, "
                    f"but {min_gb}GB required. "
                    f"(used: {used_gb:.1f}GB / {total_gb:.1f}GB)"
                )
                
        except Exception as e:
            return False, f"Error checking disk space: {e}"

    def validate_path(self) -> Tuple[bool, str]:
        """
        Validate that the path is suitable for rootfs creation.

        Returns:
            Tuple of (success, message)
        """
        # Check write permission
        can_write, msg = self.check_write_permission()
        if not can_write:
            return False, msg
        print(f"✓ {msg}")
        
        # Check free disk space (minimum 20GB required)
        has_space, msg = self.check_free_space()
        if not has_space:
            return False, msg
        print(f"✓ {msg}")
        
        # Check ACL support
        acl_support, msg = self.check_filesystem_acl_support()
        if not acl_support:
            return False, msg
        print(f"✓ {msg}")
        
        return True, "Path is valid for rootfs creation"

    def create_rootfs_directory(self) -> Tuple[bool, str]:
        """
        Create the rootfs directory with proper permissions and ACLs.

        Sets:
        - rwx for the current user
        - rwx for the current group
        - SGID bit to ensure files inherit the group

        Returns:
            Tuple of (success, message)
        """
        try:
            # Validate path first
            valid, msg = self.validate_path()
            if not valid:
                return False, msg

            # Create the rootfs directory
            self.rootfs_path.mkdir(parents=True, exist_ok=True)
            print(f"✓ Created directory: {self.rootfs_path}")

            # Get current user and group
            uid = os.getuid()
            gid = os.getgid()
            
            # Get username and groupname for ACL commands
            import pwd
            import grp
            
            try:
                username = pwd.getpwuid(uid).pw_name
            except KeyError:
                username = str(uid)
            
            try:
                groupname = grp.getgrgid(gid).gr_name
            except KeyError:
                groupname = str(gid)

            # Set base permissions (rwx for user and group)
            base_mode = stat.S_IRWXU | stat.S_IRWXG  # 0770
            os.chmod(self.rootfs_path, base_mode)
            print(f"✓ Set base permissions: {oct(base_mode)} (rwx for user and group)")
            
            # Set SGID bit on directory
            # SGID (2000) ensures new files/directories inherit the group ownership
            sgid_mode = base_mode | stat.S_ISGID  # 2770
            os.chmod(self.rootfs_path, sgid_mode)
            print(f"✓ Set SGID bit on directory: {oct(sgid_mode)} (new files inherit group)")

            # Set ownership
            os.chown(self.rootfs_path, uid, gid)
            print(f"✓ Set ownership: {username}:{groupname}")

            # Set extended ACLs
            # User ACL: rwx
            result = subprocess.run(
                ["setfacl", "-m", f"u:{username}:rwx", str(self.rootfs_path)],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                return False, f"Failed to set user ACL: {result.stderr}"
            print(f"✓ Set user ACL: u:{username}:rwx")

            # Group ACL: rwx
            result = subprocess.run(
                ["setfacl", "-m", f"g:{groupname}:rwx", str(self.rootfs_path)],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                return False, f"Failed to set group ACL: {result.stderr}"
            print(f"✓ Set group ACL: g:{groupname}:rwx")

            # Set default ACLs (for new files/directories created inside)
            # These ACLs will be inherited by all new files and subdirectories
            
            # Default ACL for the specific user: rwx
            result = subprocess.run(
                ["setfacl", "-d", "-m", f"u:{username}:rwx", str(self.rootfs_path)],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                return False, f"Failed to set default user ACL: {result.stderr}"
            print(f"✓ Set default ACL for user: d:u:{username}:rwx")

            # Default ACL for the specific group: rwx
            result = subprocess.run(
                ["setfacl", "-d", "-m", f"g:{groupname}:rwx", str(self.rootfs_path)],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                return False, f"Failed to set default group ACL: {result.stderr}"
            print(f"✓ Set default ACL for group: d:g:{groupname}:rwx")
            
            # Default ACL for owner user: rwx
            result = subprocess.run(
                ["setfacl", "-d", "-m", "u::rwx", str(self.rootfs_path)],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                return False, f"Failed to set default owner ACL: {result.stderr}"
            print(f"✓ Set default ACL for owner: d:u::rwx")
            
            # Default ACL for owner group: rwx
            result = subprocess.run(
                ["setfacl", "-d", "-m", "g::rwx", str(self.rootfs_path)],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                return False, f"Failed to set default group owner ACL: {result.stderr}"
            print(f"✓ Set default ACL for group owner: d:g::rwx")
            
            # Default mask: rwx (ensures effective permissions)
            result = subprocess.run(
                ["setfacl", "-d", "-m", "m::rwx", str(self.rootfs_path)],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                return False, f"Failed to set default mask ACL: {result.stderr}"
            print(f"✓ Set default ACL mask: d:m::rwx")
            
            # Default other: no access
            result = subprocess.run(
                ["setfacl", "-d", "-m", "o::---", str(self.rootfs_path)],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                return False, f"Failed to set default other ACL: {result.stderr}"
            print(f"✓ Set default ACL for others: d:o::---")

            # Display final ACLs
            result = subprocess.run(
                ["getfacl", str(self.rootfs_path)],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                print(f"\n📋 Final ACLs for {self.rootfs_path}:")
                for line in result.stdout.strip().split('\n'):
                    print(f"   {line}")

            return True, f"Successfully created rootfs at {self.rootfs_path}"

        except Exception as e:
            return False, f"Error creating rootfs directory: {e}"

    def remove_rootfs_directory(self) -> Tuple[bool, str]:
        """
        Remove the rootfs directory.

        Returns:
            Tuple of (success, message)
        """
        try:
            if not self.rootfs_path.exists():
                return True, "rootfs directory does not exist"

            shutil.rmtree(self.rootfs_path)
            return True, f"Successfully removed {self.rootfs_path}"

        except Exception as e:
            return False, f"Error removing rootfs directory: {e}"

    def get_rootfs_path(self) -> Path:
        """Get the rootfs path."""
        return self.rootfs_path

