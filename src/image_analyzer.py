"""
Image Analyzer Module
Analyzes container images for Java, NodeJS, and .NET binaries to check cgroup v2 compatibility.

Supported runtimes and minimum versions for cgroup v2:
- OpenJDK / HotSpot: jdk8u372, 11.0.16, 15 and later
- NodeJs: 20.3.0 or later
- IBM Semeru Runtimes: jdk8u345-b01, 11.0.16.0, 17.0.4.0, 18.0.2.0 and later
- IBM SDK Java Technology Edition (IBM Java): 8.0.7.15 and later
- .NET: 5.0 and later
"""

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Optional, Tuple


@dataclass
class BinaryInfo:
    """Information about a found binary."""
    path: str
    version: str
    version_output: str
    is_compatible: bool
    runtime_type: str  # OpenJDK, IBM Semeru, IBM Java, NodeJS, etc.


@dataclass
class ImageAnalysisResult:
    """Result of analyzing a container image."""
    image_name: str
    image_id: str
    java_binaries: List[BinaryInfo] = field(default_factory=list)
    node_binaries: List[BinaryInfo] = field(default_factory=list)
    dotnet_binaries: List[BinaryInfo] = field(default_factory=list)
    error: Optional[str] = None
    
    @property
    def java_found(self) -> str:
        """Return comma-separated list of Java binaries found."""
        if not self.java_binaries:
            return "None"
        return "; ".join([b.path for b in self.java_binaries])
    
    @property
    def java_versions(self) -> str:
        """Return comma-separated list of Java versions."""
        if not self.java_binaries:
            return "None"
        return "; ".join([b.version for b in self.java_binaries])
    
    @property
    def java_compatible(self) -> str:
        """Return compatibility status for Java."""
        if not self.java_binaries:
            return "N/A"
        compatible = all(b.is_compatible for b in self.java_binaries)
        return "Yes" if compatible else "No"
    
    @property
    def node_found(self) -> str:
        """Return comma-separated list of Node binaries found."""
        if not self.node_binaries:
            return "None"
        return "; ".join([b.path for b in self.node_binaries])
    
    @property
    def node_versions(self) -> str:
        """Return comma-separated list of Node versions."""
        if not self.node_binaries:
            return "None"
        return "; ".join([b.version for b in self.node_binaries])
    
    @property
    def node_compatible(self) -> str:
        """Return compatibility status for Node."""
        if not self.node_binaries:
            return "N/A"
        compatible = all(b.is_compatible for b in self.node_binaries)
        return "Yes" if compatible else "No"
    
    @property
    def dotnet_found(self) -> str:
        """Return comma-separated list of .NET binaries found."""
        if not self.dotnet_binaries:
            return "None"
        return "; ".join([b.path for b in self.dotnet_binaries])
    
    @property
    def dotnet_versions(self) -> str:
        """Return comma-separated list of .NET versions."""
        if not self.dotnet_binaries:
            return "None"
        return "; ".join([b.version for b in self.dotnet_binaries])
    
    @property
    def dotnet_compatible(self) -> str:
        """Return compatibility status for .NET."""
        if not self.dotnet_binaries:
            return "N/A"
        compatible = all(b.is_compatible for b in self.dotnet_binaries)
        return "Yes" if compatible else "No"


class ImageAnalyzer:
    """
    Analyzes container images for Java, NodeJS, and .NET binaries.
    """
    
    # Patterns to find binaries
    JAVA_BINARY_PATTERN = re.compile(r'.*/java$')
    NODE_BINARY_PATTERN = re.compile(r'.*/node$')
    DOTNET_BINARY_PATTERN = re.compile(r'.*/dotnet$')
    
    # Paths to exclude - patterns that path must NOT start with
    EXCLUDE_PATH_PREFIXES = [
        '/var/lib/alternatives/',       # Linux alternatives system config files
        '/var/lib/dpkg/alternatives/',  # Debian/Ubuntu dpkg alternatives
        '/etc/alternatives/',           # Alternative symlinks config
        '/usr/share/bash-completion/',  # Bash completion scripts (not binaries)
        '/etc/bash_completion.d/',      # Bash completion scripts (not binaries)
    ]
    
    # Paths to exclude - patterns that path must NOT contain
    EXCLUDE_PATH_CONTAINS = [
        '/.dotnet/optimizationdata/',   # .NET optimization data files (not binaries)
    ]
    
    def _is_excluded_path(self, path: str) -> bool:
        """
        Check if a path should be excluded from analysis.
        
        Args:
            path: Container path to check
            
        Returns:
            True if path should be excluded
        """
        # Check prefix exclusions
        if any(path.startswith(excl) for excl in self.EXCLUDE_PATH_PREFIXES):
            return True
        # Check contains exclusions
        if any(excl in path for excl in self.EXCLUDE_PATH_CONTAINS):
            return True
        return False
    
    # Version parsing patterns
    JAVA_VERSION_PATTERN = re.compile(
        r'(?:openjdk|java) version ["\']?(\d+(?:\.\d+)*(?:_\d+)?(?:-b\d+)?)["\']?',
        re.IGNORECASE
    )
    JAVA_VERSION_ALT_PATTERN = re.compile(
        r'(?:openjdk|java) (\d+(?:\.\d+)*)',
        re.IGNORECASE
    )
    NODE_VERSION_PATTERN = re.compile(r'v?(\d+\.\d+\.\d+)')
    # .NET version pattern - matches output like "8.0.122" or "3.0.100"
    DOTNET_VERSION_PATTERN = re.compile(r'^(\d+\.\d+\.\d+)', re.MULTILINE)
    
    # IBM patterns
    IBM_SEMERU_PATTERN = re.compile(r'IBM Semeru', re.IGNORECASE)
    IBM_SDK_PATTERN = re.compile(r'IBM (?:J9|SDK)', re.IGNORECASE)
    
    def __init__(self, rootfs_base_path: str, pull_secret_path: Optional[str] = None):
        """
        Initialize the image analyzer.
        
        Args:
            rootfs_base_path: Base path where rootfs directory exists
            pull_secret_path: Path to the pull-secret file for authentication
        """
        self.rootfs_base = Path(rootfs_base_path).resolve()
        self.rootfs_path = self.rootfs_base / "rootfs"
        self.pull_secret_path = Path(pull_secret_path) if pull_secret_path else None
        
        # Ensure rootfs directory exists
        self.rootfs_path.mkdir(parents=True, exist_ok=True)
        
        # Track analyzed images to avoid re-pulling
        self._analyzed_images: Dict[str, ImageAnalysisResult] = {}
    
    def _run_command(self, cmd: List[str], timeout: int = 300, debug: bool = False) -> Tuple[int, str, str]:
        """
        Run a command and return exit code, stdout, stderr.
        
        Args:
            cmd: Command to run
            timeout: Timeout in seconds
            debug: If True, print command and output
            
        Returns:
            Tuple of (exit_code, stdout, stderr)
        """
        try:
            if debug:
                print(f"      [DEBUG] Running: {' '.join(cmd)}")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            if debug:
                print(f"      [DEBUG] Exit code: {result.returncode}")
                if result.stdout:
                    print(f"      [DEBUG] stdout: {result.stdout[:200]}")
                if result.stderr:
                    print(f"      [DEBUG] stderr: {result.stderr[:200]}")
            
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            if debug:
                print(f"      [DEBUG] Command timed out after {timeout}s")
            return -1, "", "Command timed out"
        except Exception as e:
            if debug:
                print(f"      [DEBUG] Exception: {e}")
            return -1, "", str(e)
    
    def _setup_auth(self) -> Optional[str]:
        """
        Set up authentication for podman using pull-secret.
        
        Returns:
            Path to auth file or None
        """
        if not self.pull_secret_path or not self.pull_secret_path.exists():
            return None
        
        # Podman uses ~/.docker/config.json or XDG_RUNTIME_DIR/containers/auth.json
        # We'll use the --authfile option directly
        return str(self.pull_secret_path)
    
    def _pull_image(self, image_name: str, debug: bool = False) -> Tuple[bool, str]:
        """
        Pull a container image using podman.
        
        Args:
            image_name: Full image name with registry and tag/digest
            debug: Enable debug output
            
        Returns:
            Tuple of (success, error_message)
        """
        cmd = ["podman", "pull"]
        
        auth_file = self._setup_auth()
        if auth_file:
            cmd.extend(["--authfile", auth_file])
            if debug:
                print(f"      [DEBUG] Using authfile: {auth_file}")
        
        cmd.append(image_name)
        
        if debug:
            print(f"      [DEBUG] Pulling image...")
        
        exit_code, stdout, stderr = self._run_command(cmd, timeout=600, debug=debug)
        
        if exit_code != 0:
            return False, f"Failed to pull image: {stderr}"
        
        if debug:
            print(f"      [DEBUG] Pull successful")
        
        return True, ""
    
    def _create_and_export_container(self, image_name: str, debug: bool = False) -> Tuple[bool, str, str]:
        """
        Create a container from image and export its filesystem.
        
        Args:
            image_name: Image to create container from
            debug: Enable debug output
            
        Returns:
            Tuple of (success, tar_path, error_message)
        """
        tar_path = self.rootfs_path / "image-rootfs.tar"
        
        if debug:
            print(f"      [DEBUG] Tar will be saved to: {tar_path}")
            print(f"      [DEBUG] rootfs_path: {self.rootfs_path}")
        
        # Create container (don't start it)
        if debug:
            print(f"      [DEBUG] Creating container from image...")
        
        exit_code, stdout, stderr = self._run_command(
            ["podman", "create", image_name],
            timeout=120,
            debug=debug
        )
        
        if exit_code != 0:
            return False, "", f"Failed to create container: {stderr}"
        
        container_id = stdout.strip()
        
        if debug:
            print(f"      [DEBUG] Container created: {container_id}")
        
        try:
            # Export container filesystem
            if debug:
                print(f"      [DEBUG] Exporting container to tar...")
            
            exit_code, stdout, stderr = self._run_command(
                ["podman", "export", container_id, "-o", str(tar_path)],
                timeout=600,
                debug=debug
            )
            
            if exit_code != 0:
                return False, "", f"Failed to export container: {stderr}"
            
            # Verify tar was created
            if tar_path.exists():
                tar_size = tar_path.stat().st_size
                if debug:
                    print(f"      [DEBUG] Tar created: {tar_path} ({tar_size} bytes)")
            else:
                return False, "", f"Tar file was not created at {tar_path}"
            
            return True, str(tar_path), ""
            
        finally:
            # Always remove the container
            if debug:
                print(f"      [DEBUG] Removing container {container_id}...")
            self._run_command(["podman", "rm", "-f", container_id], debug=debug)
    
    def _extract_tar(self, tar_path: str, debug: bool = False) -> Tuple[bool, str]:
        """
        Extract tar file to rootfs directory using command-line tar.
        
        Uses command-line tar instead of Python tarfile module for better
        handling of special files, permissions, and symlinks.
        
        Args:
            tar_path: Path to tar file
            debug: Enable debug output
            
        Returns:
            Tuple of (success, error_message)
        """
        extract_path = self.rootfs_path / "extracted"
        
        if debug:
            print(f"      [DEBUG] Extracting tar to: {extract_path}")
        
        try:
            # Clean existing extraction
            if extract_path.exists():
                if debug:
                    print(f"      [DEBUG] Cleaning existing extraction...")
                shutil.rmtree(extract_path, ignore_errors=True)
            extract_path.mkdir(parents=True)
            
            if debug:
                print(f"      [DEBUG] Extracting tar file: {tar_path}")
            
            # Use command-line tar with options to handle permissions gracefully
            # --no-same-owner: don't try to preserve ownership
            # --no-same-permissions: don't try to preserve permissions exactly
            # --warning=no-unknown-keyword: suppress warnings
            # --exclude: skip problematic paths
            cmd = [
                "tar",
                "-xf", str(tar_path),
                "-C", str(extract_path),
                "--no-same-owner",
                "--no-same-permissions",
                "--warning=no-unknown-keyword",
            ]
            
            exit_code, stdout, stderr = self._run_command(cmd, timeout=300, debug=debug)
            
            # tar may return non-zero for minor issues but still extract most files
            # We check if extraction actually produced files
            if extract_path.exists():
                # Fix permissions to allow reading and deletion
                # chmod -R u+rwX adds read, write, and execute (for dirs) for owner
                if debug:
                    print(f"      [DEBUG] Fixing permissions on extracted files...")
                
                chmod_cmd = ["chmod", "-R", "u+rwX", str(extract_path)]
                self._run_command(chmod_cmd, timeout=120, debug=debug)
                
                # Also remove any ACL restrictions that might prevent deletion
                # setfacl -R -b removes all ACLs
                setfacl_cmd = ["setfacl", "-R", "-b", str(extract_path)]
                self._run_command(setfacl_cmd, timeout=120, debug=debug)
                
                # Count extracted items
                file_count = sum(1 for _ in extract_path.rglob('*'))
                if debug:
                    print(f"      [DEBUG] Extraction complete: {file_count} items in {extract_path}")
                
                if file_count > 0:
                    # Show first few items
                    if debug:
                        items = list(extract_path.iterdir())[:10]
                        print(f"      [DEBUG] Top-level items: {[i.name for i in items]}")
                    return True, ""
                else:
                    return False, "Tar extraction produced no files"
            else:
                return False, f"Extract path not created: {extract_path}"
            
        except Exception as e:
            if debug:
                print(f"      [DEBUG] Extract error: {e}")
            return False, f"Failed to extract tar: {e}"
    
    def _find_binaries(self, base_path: Path, pattern: re.Pattern) -> List[str]:
        """
        Find binaries matching pattern in extracted filesystem.
        
        Args:
            base_path: Base path to search
            pattern: Regex pattern to match
            
        Returns:
            List of paths to found binaries
        """
        found = []
        
        try:
            for root, dirs, files in os.walk(base_path, followlinks=True):
                for file in files:
                    full_path = os.path.join(root, file)
                    rel_path = os.path.relpath(full_path, base_path)
                    
                    if pattern.match(f"/{rel_path}"):
                        # Check if file exists (could be broken symlink)
                        if os.path.exists(full_path) or os.path.islink(full_path):
                            # For symlinks, resolve to actual file
                            resolved_path = full_path
                            if os.path.islink(full_path):
                                try:
                                    # Try to resolve symlink within the extracted fs
                                    link_target = os.readlink(full_path)
                                    if os.path.isabs(link_target):
                                        # Absolute symlink - resolve relative to base_path
                                        resolved_path = os.path.join(base_path, link_target.lstrip('/'))
                                    else:
                                        resolved_path = os.path.join(os.path.dirname(full_path), link_target)
                                    resolved_path = os.path.normpath(resolved_path)
                                except Exception:
                                    pass
                            
                            # Check if resolved path exists and is a file
                            if os.path.isfile(resolved_path):
                                found.append(resolved_path)
                            elif os.path.isfile(full_path):
                                found.append(full_path)
        except Exception:
            pass
        
        return found
    
    def _get_java_version_in_container(self, image_name: str, binary_path: str, debug: bool = False) -> Tuple[str, str, str]:
        """
        Get Java version by running the binary inside the container.
        
        Args:
            image_name: Container image name
            binary_path: Path to java binary inside the container
            debug: Enable debug output
            
        Returns:
            Tuple of (version, full_output, runtime_type)
        """
        # Java outputs version to stderr
        # Use --entrypoint to override any ENTRYPOINT in the image (e.g., Spring Boot apps)
        # Additional options handle permission issues with non-root user images
        exit_code, stdout, stderr = self._run_command(
            [
                "podman", "run", "--rm",
                "--entrypoint", binary_path,
                "--privileged",
                "--security-opt=no-new-privileges",
                "--cap-drop=all",
                "--cap-add=chown",
                "--cap-add=dac_override",
                "--cap-add=fowner",
                "--cap-add=setuid",
                "--cap-add=setgid",
                "--user", "0:0",
                "--env", "GUID=0",
                "--env", "PUID=0",
                image_name,
                "-version"
            ],
            timeout=60,
            debug=debug
        )
        
        output = stderr + stdout
        
        # Determine runtime type
        runtime_type = "Unknown"
        if self.IBM_SEMERU_PATTERN.search(output):
            runtime_type = "IBM Semeru"
        elif self.IBM_SDK_PATTERN.search(output):
            runtime_type = "IBM Java"
        elif "OpenJDK" in output or "openjdk" in output.lower():
            runtime_type = "OpenJDK"
        elif "HotSpot" in output:
            runtime_type = "HotSpot"
        
        # Extract version
        match = self.JAVA_VERSION_PATTERN.search(output)
        if match:
            return match.group(1), output, runtime_type
        
        match = self.JAVA_VERSION_ALT_PATTERN.search(output)
        if match:
            return match.group(1), output, runtime_type
        
        return "unknown", output, runtime_type
    
    def _get_node_version_in_container(self, image_name: str, binary_path: str, debug: bool = False) -> Tuple[str, str]:
        """
        Get Node.js version by running the binary inside the container.
        
        Args:
            image_name: Container image name
            binary_path: Path to node binary inside the container
            debug: Enable debug output
            
        Returns:
            Tuple of (version, full_output)
        """
        # Use --entrypoint to override any ENTRYPOINT in the image
        # Additional options handle permission issues with non-root user images
        exit_code, stdout, stderr = self._run_command(
            [
                "podman", "run", "--rm",
                "--entrypoint", binary_path,
                "--privileged",
                "--security-opt=no-new-privileges",
                "--cap-drop=all",
                "--cap-add=chown",
                "--cap-add=dac_override",
                "--cap-add=fowner",
                "--cap-add=setuid",
                "--cap-add=setgid",
                "--user", "0:0",
                "--env", "GUID=0",
                "--env", "PUID=0",
                image_name,
                "--version"
            ],
            timeout=60,
            debug=debug
        )
        
        output = stdout + stderr
        
        match = self.NODE_VERSION_PATTERN.search(output)
        if match:
            return match.group(1), output
        
        return "unknown", output
    
    def _check_java_compatibility(self, version: str, runtime_type: str) -> bool:
        """
        Check if Java version is compatible with cgroup v2.
        
        Minimum versions:
        - OpenJDK / HotSpot: jdk8u372, 11.0.16, 15+
        - IBM Semeru: jdk8u345-b01, 11.0.16.0, 17.0.4.0, 18.0.2.0+
        - IBM Java: 8.0.7.15+
        
        Args:
            version: Java version string
            runtime_type: Type of Java runtime
            
        Returns:
            True if compatible
        """
        try:
            # Parse version - handle formats like 1.8.0_372, 11.0.16, 17.0.4.0
            version = version.replace("-b", ".").replace("_", ".")
            parts = [int(p) for p in version.split(".") if p.isdigit()]
            
            if not parts:
                return False
            
            major = parts[0]
            
            # Handle 1.x versions (Java 8 and earlier)
            if major == 1 and len(parts) > 1:
                major = parts[1]
                minor = parts[2] if len(parts) > 2 else 0
                update = parts[3] if len(parts) > 3 else 0
            else:
                minor = parts[1] if len(parts) > 1 else 0
                update = parts[2] if len(parts) > 2 else 0
            
            # Java 15+ is always compatible
            if major >= 15:
                return True
            
            # Java 11: need 11.0.16+
            if major == 11:
                if minor > 0:
                    return True
                return update >= 16
            
            # Java 8: need 8u372+ (OpenJDK) or 8u345+ (IBM Semeru) or 8.0.7.15+ (IBM Java)
            if major == 8:
                if runtime_type == "IBM Java":
                    # 8.0.7.15+
                    if minor > 0:
                        return True
                    if update > 7:
                        return True
                    if update == 7 and len(parts) > 3 and parts[3] >= 15:
                        return True
                    return False
                elif runtime_type == "IBM Semeru":
                    # 8u345+
                    return update >= 345
                else:
                    # OpenJDK: 8u372+
                    return update >= 372
            
            # Java 17: need 17.0.4+ for IBM Semeru
            if major == 17 and runtime_type == "IBM Semeru":
                return minor > 0 or update >= 4
            
            # Java 18: need 18.0.2+ for IBM Semeru
            if major == 18 and runtime_type == "IBM Semeru":
                return minor > 0 or update >= 2
            
            # Other versions between 9-14: not compatible
            if 9 <= major <= 14:
                return False
            
            # Assume compatible for other cases
            return True
            
        except Exception:
            return False
    
    def _check_node_compatibility(self, version: str) -> bool:
        """
        Check if Node.js version is compatible with cgroup v2.
        
        Minimum version: 20.3.0
        
        Args:
            version: Node.js version string
            
        Returns:
            True if compatible
        """
        try:
            parts = [int(p) for p in version.split(".")]
            
            if len(parts) < 3:
                return False
            
            major, minor, patch = parts[0], parts[1], parts[2]
            
            # Need 20.3.0+
            if major > 20:
                return True
            if major == 20:
                if minor > 3:
                    return True
                if minor == 3:
                    return patch >= 0
            
            return False
            
        except Exception:
            return False
    
    def _get_dotnet_version_in_container(self, image_name: str, binary_path: str, debug: bool = False) -> Tuple[str, str]:
        """
        Get .NET version by running the binary inside the container.
        
        Args:
            image_name: Container image name
            binary_path: Path to dotnet binary inside the container
            debug: Enable debug output
            
        Returns:
            Tuple of (version, full_output)
        """
        # Use --entrypoint to override any ENTRYPOINT in the image
        # Additional options handle permission issues with non-root user images
        exit_code, stdout, stderr = self._run_command(
            [
                "podman", "run", "--rm",
                "--entrypoint", binary_path,
                "--privileged",
                "--security-opt=no-new-privileges",
                "--cap-drop=all",
                "--cap-add=chown",
                "--cap-add=dac_override",
                "--cap-add=fowner",
                "--cap-add=setuid",
                "--cap-add=setgid",
                "--user", "0:0",
                "--env", "GUID=0",
                "--env", "PUID=0",
                image_name,
                "--version"
            ],
            timeout=60,
            debug=debug
        )
        
        output = stdout + stderr
        
        match = self.DOTNET_VERSION_PATTERN.search(output)
        if match:
            return match.group(1), output
        
        return "unknown", output
    
    def _check_dotnet_compatibility(self, version: str) -> bool:
        """
        Check if .NET version is compatible with cgroup v2.
        
        Minimum version: 5.0
        .NET 5.0 and later have full cgroups v2 support.
        .NET Core 3.x and earlier do NOT support cgroups v2.
        
        Args:
            version: .NET version string (e.g., "8.0.122", "3.0.100")
            
        Returns:
            True if compatible (version >= 5.0)
        """
        try:
            parts = [int(p) for p in version.split(".")]
            
            if len(parts) < 2:
                return False
            
            major = parts[0]
            
            # .NET 5.0+ is compatible with cgroups v2
            return major >= 5
            
        except Exception:
            return False
    
    def _cleanup(self, image_name: str, keep_image: bool = False, debug: bool = False) -> None:
        """
        Clean up rootfs and optionally remove the image.
        
        Args:
            image_name: Image to remove
            keep_image: If True, don't remove the image
            debug: Enable debug output
        """
        # Clean rootfs
        extract_path = self.rootfs_path / "extracted"
        if extract_path.exists():
            if debug:
                print(f"      [DEBUG] Cleaning up extracted files: {extract_path}")
            
            # Fix permissions before removal to ensure we can delete everything
            # chmod -R u+rwX adds read, write, and execute (for dirs) for owner
            chmod_cmd = ["chmod", "-R", "u+rwX", str(extract_path)]
            self._run_command(chmod_cmd, timeout=120)
            
            # Remove ACLs that might prevent deletion
            setfacl_cmd = ["setfacl", "-R", "-b", str(extract_path)]
            self._run_command(setfacl_cmd, timeout=120)
            
            # Now remove the directory
            try:
                shutil.rmtree(extract_path)
            except Exception as e:
                if debug:
                    print(f"      [DEBUG] shutil.rmtree failed: {e}, trying rm -rf")
                # Fallback to rm -rf
                self._run_command(["rm", "-rf", str(extract_path)], timeout=120)
        
        tar_path = self.rootfs_path / "image-rootfs.tar"
        if tar_path.exists():
            if debug:
                print(f"      [DEBUG] Removing tar file: {tar_path}")
            try:
                tar_path.unlink()
            except Exception:
                pass
        
        # Remove image
        if not keep_image:
            if debug:
                print(f"      [DEBUG] Removing image: {image_name[:50]}...")
            self._run_command(["podman", "rmi", "-f", image_name])
    
    def analyze_image(self, image_name: str, image_id: str = "", debug: bool = False) -> ImageAnalysisResult:
        """
        Analyze a container image for Java and NodeJS binaries.
        
        Args:
            image_name: Full image name
            image_id: Image ID (optional, for deduplication)
            debug: Enable debug output
            
        Returns:
            ImageAnalysisResult with found binaries and versions
        """
        # Check if already analyzed (use image_name as key if no image_id)
        cache_key = image_id if image_id else image_name
        if cache_key in self._analyzed_images:
            if debug:
                print(f"      [DEBUG] Using cached result for {image_name[:50]}...")
            return self._analyzed_images[cache_key]
        
        result = ImageAnalysisResult(image_name=image_name, image_id=image_id)
        
        if debug:
            print(f"      [DEBUG] rootfs_base: {self.rootfs_base}")
            print(f"      [DEBUG] rootfs_path: {self.rootfs_path}")
            print(f"      [DEBUG] rootfs_path exists: {self.rootfs_path.exists()}")
        
        try:
            print(f"    Pulling image: {image_name[:80]}...")
            
            # Pull image
            success, error = self._pull_image(image_name, debug=debug)
            if not success:
                result.error = error
                print(f"    ✗ Pull failed: {error[:100]}")
                return result
            
            print(f"    Exporting container filesystem...")
            
            # Create and export container
            success, tar_path, error = self._create_and_export_container(image_name, debug=debug)
            if not success:
                result.error = error
                print(f"    ✗ Export failed: {error[:100]}")
                self._cleanup(image_name, debug=debug)
                return result
            
            print(f"    Extracting filesystem...")
            
            # Extract tar
            success, error = self._extract_tar(tar_path, debug=debug)
            if not success:
                result.error = error
                print(f"    ✗ Extract failed: {error[:100]}")
                self._cleanup(image_name, debug=debug)
                return result
            
            extract_path = self.rootfs_path / "extracted"
            
            if debug:
                print(f"      [DEBUG] extract_path: {extract_path}")
                print(f"      [DEBUG] extract_path exists: {extract_path.exists()}")
                if extract_path.exists():
                    items = list(extract_path.iterdir())[:5]
                    print(f"      [DEBUG] First items: {[str(i.name) for i in items]}")
            
            # Find Java binaries
            print(f"    Searching for Java binaries...")
            java_paths = self._find_binaries(extract_path, self.JAVA_BINARY_PATTERN)
            
            # Deduplicate - only check unique binaries (skip symlinks to same target)
            java_checked = set()
            for java_path in java_paths:
                rel_path = os.path.relpath(java_path, extract_path)
                container_path = f"/{rel_path}"
                
                # Skip paths that are not real binaries
                if self._is_excluded_path(container_path):
                    if debug:
                        print(f"      [DEBUG] Skipping excluded path: {container_path}")
                    continue
                
                # Skip if we already checked a binary with this resolved path
                resolved = os.path.realpath(java_path)
                if resolved in java_checked:
                    continue
                java_checked.add(resolved)
                
                # Run version check inside container
                version, output, runtime_type = self._get_java_version_in_container(
                    image_name, container_path, debug=debug
                )
                is_compatible = self._check_java_compatibility(version, runtime_type)
                
                result.java_binaries.append(BinaryInfo(
                    path=container_path,
                    version=version,
                    version_output=output,
                    is_compatible=is_compatible,
                    runtime_type=runtime_type
                ))
            
            # Find Node binaries
            print(f"    Searching for Node.js binaries...")
            node_paths = self._find_binaries(extract_path, self.NODE_BINARY_PATTERN)
            
            # Deduplicate - only check unique binaries
            node_checked = set()
            for node_path in node_paths:
                rel_path = os.path.relpath(node_path, extract_path)
                container_path = f"/{rel_path}"
                
                # Skip paths that are not real binaries
                if self._is_excluded_path(container_path):
                    if debug:
                        print(f"      [DEBUG] Skipping excluded path: {container_path}")
                    continue
                
                # Skip if we already checked a binary with this resolved path
                resolved = os.path.realpath(node_path)
                if resolved in node_checked:
                    continue
                node_checked.add(resolved)
                
                # Run version check inside container
                version, output = self._get_node_version_in_container(
                    image_name, container_path, debug=debug
                )
                is_compatible = self._check_node_compatibility(version)
                
                result.node_binaries.append(BinaryInfo(
                    path=container_path,
                    version=version,
                    version_output=output,
                    is_compatible=is_compatible,
                    runtime_type="NodeJS"
                ))
            
            # Find .NET binaries
            print(f"    Searching for .NET binaries...")
            dotnet_paths = self._find_binaries(extract_path, self.DOTNET_BINARY_PATTERN)
            
            # Deduplicate - only check unique binaries
            dotnet_checked = set()
            for dotnet_path in dotnet_paths:
                rel_path = os.path.relpath(dotnet_path, extract_path)
                container_path = f"/{rel_path}"
                
                # Skip paths that are not real binaries
                if self._is_excluded_path(container_path):
                    if debug:
                        print(f"      [DEBUG] Skipping excluded path: {container_path}")
                    continue
                
                # Skip if we already checked a binary with this resolved path
                resolved = os.path.realpath(dotnet_path)
                if resolved in dotnet_checked:
                    continue
                dotnet_checked.add(resolved)
                
                # Run version check inside container
                version, output = self._get_dotnet_version_in_container(
                    image_name, container_path, debug=debug
                )
                is_compatible = self._check_dotnet_compatibility(version)
                
                result.dotnet_binaries.append(BinaryInfo(
                    path=container_path,
                    version=version,
                    version_output=output,
                    is_compatible=is_compatible,
                    runtime_type=".NET"
                ))
            
            # Report findings
            if result.java_binaries:
                for b in result.java_binaries:
                    compat = "✓" if b.is_compatible else "✗"
                    print(f"      {compat} Java ({b.runtime_type}): {b.version} at {b.path}")
            
            if result.node_binaries:
                for b in result.node_binaries:
                    compat = "✓" if b.is_compatible else "✗"
                    print(f"      {compat} Node.js: {b.version} at {b.path}")
            
            if result.dotnet_binaries:
                for b in result.dotnet_binaries:
                    compat = "✓" if b.is_compatible else "✗"
                    print(f"      {compat} .NET: {b.version} at {b.path}")
            
            if not result.java_binaries and not result.node_binaries and not result.dotnet_binaries:
                print(f"      No Java, Node.js, or .NET binaries found")
            
        except Exception as e:
            result.error = str(e)
        
        finally:
            # Always cleanup
            self._cleanup(image_name, debug=debug)
        
        # Cache result
        self._analyzed_images[cache_key] = result
        
        return result
    
    def get_cached_result(self, image_name: str, image_id: str = "") -> Optional[ImageAnalysisResult]:
        """
        Get cached analysis result if available.
        
        Args:
            image_name: Image name
            image_id: Image ID
            
        Returns:
            Cached result or None
        """
        cache_key = image_id if image_id else image_name
        return self._analyzed_images.get(cache_key)

