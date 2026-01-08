"""
Image Collector Module
Collects container image information from OpenShift cluster resources.

This module implements smart collection that avoids duplicates by tracking
parent-child relationships between Kubernetes objects:
- Deployment -> ReplicaSet -> Pod
- StatefulSet -> Pod
- DaemonSet -> Pod
- CronJob -> Job -> Pod
- ReplicaSet (standalone) -> Pod
- Job (standalone) -> Pod
- Pod (standalone)

Only the highest-level controller is included in the output.
"""

import fnmatch
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Set

import pandas as pd
from kubernetes import client

from .openshift_client import OpenShiftClient
from .image_analyzer import ImageAnalyzer, ImageAnalysisResult

# Default namespace patterns to exclude (infrastructure namespaces)
DEFAULT_EXCLUDE_NAMESPACE_PATTERNS = ["openshift-*", "kube-*"]


class ContainerImageInfo:
    """Data class for container image information."""
    
    def __init__(
        self,
        container_name: str,
        image_name: str,
        namespace: str,
        image_id: str,
        object_type: str,
        object_name: str
    ):
        self.container_name = container_name
        self.image_name = image_name
        self.namespace = namespace
        self.image_id = image_id
        self.object_type = object_type
        self.object_name = object_name
        
        # Analysis results (populated by ImageAnalyzer)
        self.java_binary: str = ""
        self.java_version: str = ""
        self.java_compatible: str = ""
        self.node_binary: str = ""
        self.node_version: str = ""
        self.node_compatible: str = ""
        self.analysis_error: str = ""

    def to_dict(self) -> Dict[str, str]:
        """Convert to dictionary for DataFrame creation."""
        return {
            "container_name": self.container_name,
            "namespace": self.namespace,
            "object_type": self.object_type,
            "object_name": self.object_name,
            "image_name": self.image_name,
            "image_id": self.image_id,
            "java_binary": self.java_binary,
            "java_version": self.java_version,
            "java_cgroup_v2_compatible": self.java_compatible,
            "node_binary": self.node_binary,
            "node_version": self.node_version,
            "node_cgroup_v2_compatible": self.node_compatible,
            "analysis_error": self.analysis_error
        }


class ImageCollector:
    """
    Collects container image information from various OpenShift resources.
    
    Implements smart deduplication: only the highest-level controller
    (Deployment, StatefulSet, DaemonSet, CronJob) is reported, not the
    generated child objects (ReplicaSets, Jobs, Pods).
    
    Supports two modes:
    - Single namespace mode: collect only from a specific namespace
    - All namespaces mode: collect from all namespaces (with optional exclusions)
    """

    def __init__(
        self, 
        openshift_client: OpenShiftClient,
        exclude_namespace_patterns: Optional[List[str]] = None,
        namespace: Optional[str] = None
    ):
        """
        Initialize the image collector.

        Args:
            openshift_client: Connected OpenShift client instance.
            exclude_namespace_patterns: List of glob patterns for namespaces to exclude.
                                       Supports wildcards like 'openshift-*'.
                                       Default: ['openshift-*', 'kube-*']
                                       Ignored when namespace is specified.
            namespace: If specified, only collect from this namespace.
                      When set, exclude_namespace_patterns is ignored.
        """
        self.client = openshift_client
        self.images: List[ContainerImageInfo] = []
        self.namespace = namespace  # Single namespace mode if set
        
        # Set up namespace exclusion patterns (only used when namespace is None)
        if namespace:
            # Single namespace mode - no exclusion patterns needed
            self.exclude_patterns = []
        elif exclude_namespace_patterns is None:
            self.exclude_patterns = DEFAULT_EXCLUDE_NAMESPACE_PATTERNS.copy()
        else:
            self.exclude_patterns = exclude_namespace_patterns
        
        # Cache of excluded namespaces (populated during collection)
        self._excluded_namespaces_cache: Set[str] = set()

    def _is_namespace_excluded(self, namespace: str) -> bool:
        """
        Check if a namespace should be excluded based on the configured patterns.
        
        Args:
            namespace: Namespace name to check
            
        Returns:
            True if the namespace matches any exclusion pattern
        """
        # Check cache first
        if namespace in self._excluded_namespaces_cache:
            return True
        
        # Check against patterns
        for pattern in self.exclude_patterns:
            if fnmatch.fnmatch(namespace, pattern):
                self._excluded_namespaces_cache.add(namespace)
                return True
        
        return False

    def _get_owner_references(self, metadata) -> List[Dict[str, str]]:
        """
        Extract owner references from object metadata.
        
        Args:
            metadata: Kubernetes object metadata
            
        Returns:
            List of owner reference dicts with 'kind' and 'name' keys
        """
        owners = []
        if metadata.owner_references:
            for ref in metadata.owner_references:
                owners.append({
                    "kind": ref.kind,
                    "name": ref.name
                })
        return owners

    def _is_owned_by(self, metadata, owner_kinds: List[str]) -> bool:
        """
        Check if an object is owned by any of the specified kinds.
        
        Args:
            metadata: Kubernetes object metadata
            owner_kinds: List of owner kinds to check (e.g., ["Deployment", "StatefulSet"])
            
        Returns:
            True if owned by any of the specified kinds
        """
        owners = self._get_owner_references(metadata)
        for owner in owners:
            if owner["kind"] in owner_kinds:
                return True
        return False

    def _add_container_info(
        self,
        containers: List,
        namespace: str,
        object_type: str,
        object_name: str,
        image_id_map: Optional[Dict[str, str]] = None
    ) -> int:
        """
        Add container information to the images list.
        
        Args:
            containers: List of container specs
            namespace: Namespace of the resource
            object_type: Type of the object
            object_name: Name of the object
            image_id_map: Optional mapping of container name to image ID
            
        Returns:
            Number of containers added
        """
        count = 0
        image_id_map = image_id_map or {}
        
        for container in containers:
            image_id = image_id_map.get(container.name, "")
            
            info = ContainerImageInfo(
                container_name=container.name,
                image_name=container.image,
                namespace=namespace,
                image_id=image_id,
                object_type=object_type,
                object_name=object_name
            )
            self.images.append(info)
            count += 1
            
        return count

    def collect_from_pods(self) -> int:
        """
        Collect images from standalone Pods only (not managed by controllers).
        
        Pods managed by Deployment, StatefulSet, DaemonSet, ReplicaSet, Job,
        or OpenShift-specific controllers are skipped.
        
        Also skips:
        - Static pods (mirror pods managed by kubelet on nodes)
        - OpenShift installer/pruner pods
        - CatalogSource pods (operator marketplace)

        Returns:
            Number of containers found.
        """
        print("  Collecting images from standalone Pods...")
        core_v1 = self.client.get_core_v1_api()
        count = 0
        skipped = 0
        
        # Controller kinds that generate pods
        controller_kinds = [
            "ReplicaSet", "StatefulSet", "DaemonSet", "Job", 
            "Deployment", "ReplicationController", "Node",
            "CatalogSource", "ConfigMap"
        ]
        
        # Pod name patterns to skip (static/infrastructure pods)
        skip_patterns = [
            "installer-",
            "revision-pruner-",
            "guard-",
            "kube-rbac-proxy-crio-",
        ]
        
        try:
            # Use namespaced or cluster-wide API based on configuration
            if self.namespace:
                pods = core_v1.list_namespaced_pod(namespace=self.namespace)
            else:
                pods = core_v1.list_pod_for_all_namespaces()
            
            for pod in pods.items:
                namespace = pod.metadata.namespace
                pod_name = pod.metadata.name
                
                # Skip excluded namespaces (uses configured patterns)
                # In single namespace mode, this is a no-op
                if self._is_namespace_excluded(namespace):
                    skipped += 1
                    continue
                
                # Skip pods that are managed by a controller
                if self._is_owned_by(pod.metadata, controller_kinds):
                    skipped += 1
                    continue
                
                # Skip static pods (they have annotation kubernetes.io/config.mirror)
                annotations = pod.metadata.annotations or {}
                if "kubernetes.io/config.mirror" in annotations:
                    skipped += 1
                    continue
                
                # Skip pods matching infrastructure patterns
                if any(pattern in pod_name for pattern in skip_patterns):
                    skipped += 1
                    continue
                
                # Get all containers (regular + init)
                containers = pod.spec.containers or []
                init_containers = pod.spec.init_containers or []
                all_containers = containers + init_containers
                
                # Get container statuses for image IDs
                image_id_map: Dict[str, str] = {}
                if pod.status:
                    all_statuses = (pod.status.container_statuses or []) + \
                                   (pod.status.init_container_statuses or [])
                    for status in all_statuses:
                        if status.image_id:
                            image_id_map[status.name] = status.image_id
                
                count += self._add_container_info(
                    all_containers,
                    namespace,
                    "Pod",
                    pod_name,
                    image_id_map
                )
                
        except Exception as e:
            print(f"    Warning: Error collecting from Pods: {e}")
        
        print(f"    Found {count} containers in standalone Pods (skipped {skipped} managed/static pods)")
        return count

    def collect_from_deployments(self) -> int:
        """
        Collect images from Deployments.
        
        Deployments are top-level controllers. Their ReplicaSets and Pods
        will be skipped during collection.

        Returns:
            Number of containers found.
        """
        print("  Collecting images from Deployments...")
        apps_v1 = self.client.get_apps_v1_api()
        count = 0
        skipped_ns = 0
        
        try:
            # Use namespaced or cluster-wide API based on configuration
            if self.namespace:
                deployments = apps_v1.list_namespaced_deployment(namespace=self.namespace)
            else:
                deployments = apps_v1.list_deployment_for_all_namespaces()
            
            for deployment in deployments.items:
                namespace = deployment.metadata.namespace
                
                # Skip excluded namespaces (no-op in single namespace mode)
                if self._is_namespace_excluded(namespace):
                    skipped_ns += 1
                    continue
                
                deployment_name = deployment.metadata.name
                
                # Get containers from pod template
                containers = deployment.spec.template.spec.containers or []
                init_containers = deployment.spec.template.spec.init_containers or []
                all_containers = containers + init_containers
                
                count += self._add_container_info(
                    all_containers,
                    namespace,
                    "Deployment",
                    deployment_name
                )
                    
        except Exception as e:
            print(f"    Warning: Error collecting from Deployments: {e}")
        
        print(f"    Found {count} containers in Deployments")
        return count

    def collect_from_statefulsets(self) -> int:
        """
        Collect images from StatefulSets.
        
        StatefulSets are top-level controllers. Their Pods will be skipped.

        Returns:
            Number of containers found.
        """
        print("  Collecting images from StatefulSets...")
        apps_v1 = self.client.get_apps_v1_api()
        count = 0
        
        try:
            # Use namespaced or cluster-wide API based on configuration
            if self.namespace:
                statefulsets = apps_v1.list_namespaced_stateful_set(namespace=self.namespace)
            else:
                statefulsets = apps_v1.list_stateful_set_for_all_namespaces()
            
            for sts in statefulsets.items:
                namespace = sts.metadata.namespace
                
                # Skip excluded namespaces (no-op in single namespace mode)
                if self._is_namespace_excluded(namespace):
                    continue
                
                sts_name = sts.metadata.name
                
                containers = sts.spec.template.spec.containers or []
                init_containers = sts.spec.template.spec.init_containers or []
                all_containers = containers + init_containers
                
                count += self._add_container_info(
                    all_containers,
                    namespace,
                    "StatefulSet",
                    sts_name
                )
                    
        except Exception as e:
            print(f"    Warning: Error collecting from StatefulSets: {e}")
        
        print(f"    Found {count} containers in StatefulSets")
        return count

    def collect_from_daemonsets(self) -> int:
        """
        Collect images from DaemonSets.
        
        DaemonSets are top-level controllers. Their Pods will be skipped.

        Returns:
            Number of containers found.
        """
        print("  Collecting images from DaemonSets...")
        apps_v1 = self.client.get_apps_v1_api()
        count = 0
        
        try:
            # Use namespaced or cluster-wide API based on configuration
            if self.namespace:
                daemonsets = apps_v1.list_namespaced_daemon_set(namespace=self.namespace)
            else:
                daemonsets = apps_v1.list_daemon_set_for_all_namespaces()
            
            for ds in daemonsets.items:
                namespace = ds.metadata.namespace
                
                # Skip excluded namespaces (no-op in single namespace mode)
                if self._is_namespace_excluded(namespace):
                    continue
                
                ds_name = ds.metadata.name
                
                containers = ds.spec.template.spec.containers or []
                init_containers = ds.spec.template.spec.init_containers or []
                all_containers = containers + init_containers
                
                count += self._add_container_info(
                    all_containers,
                    namespace,
                    "DaemonSet",
                    ds_name
                )
                    
        except Exception as e:
            print(f"    Warning: Error collecting from DaemonSets: {e}")
        
        print(f"    Found {count} containers in DaemonSets")
        return count

    def collect_from_jobs(self) -> int:
        """
        Collect images from standalone Jobs only (not managed by CronJob).
        
        Jobs managed by CronJob are skipped since the CronJob is already collected.

        Returns:
            Number of containers found.
        """
        print("  Collecting images from standalone Jobs...")
        batch_v1 = self.client.get_batch_v1_api()
        count = 0
        skipped = 0
        
        try:
            # Use namespaced or cluster-wide API based on configuration
            if self.namespace:
                jobs = batch_v1.list_namespaced_job(namespace=self.namespace)
            else:
                jobs = batch_v1.list_job_for_all_namespaces()
            
            for job in jobs.items:
                namespace = job.metadata.namespace
                
                # Skip excluded namespaces (no-op in single namespace mode)
                if self._is_namespace_excluded(namespace):
                    continue
                
                job_name = job.metadata.name
                
                # Skip jobs that are managed by a CronJob
                if self._is_owned_by(job.metadata, ["CronJob"]):
                    skipped += 1
                    continue
                
                containers = job.spec.template.spec.containers or []
                init_containers = job.spec.template.spec.init_containers or []
                all_containers = containers + init_containers
                
                count += self._add_container_info(
                    all_containers,
                    namespace,
                    "Job",
                    job_name
                )
                    
        except Exception as e:
            print(f"    Warning: Error collecting from Jobs: {e}")
        
        print(f"    Found {count} containers in standalone Jobs (skipped {skipped} CronJob-managed)")
        return count

    def collect_from_cronjobs(self) -> int:
        """
        Collect images from CronJobs.
        
        CronJobs are top-level controllers. Their Jobs and Pods will be skipped.

        Returns:
            Number of containers found.
        """
        print("  Collecting images from CronJobs...")
        batch_v1 = self.client.get_batch_v1_api()
        count = 0
        
        try:
            # Use namespaced or cluster-wide API based on configuration
            if self.namespace:
                cronjobs = batch_v1.list_namespaced_cron_job(namespace=self.namespace)
            else:
                cronjobs = batch_v1.list_cron_job_for_all_namespaces()
            
            for cj in cronjobs.items:
                namespace = cj.metadata.namespace
                
                # Skip excluded namespaces (no-op in single namespace mode)
                if self._is_namespace_excluded(namespace):
                    continue
                
                cj_name = cj.metadata.name
                
                # CronJob has job template -> pod template
                containers = cj.spec.job_template.spec.template.spec.containers or []
                init_containers = cj.spec.job_template.spec.template.spec.init_containers or []
                all_containers = containers + init_containers
                
                count += self._add_container_info(
                    all_containers,
                    namespace,
                    "CronJob",
                    cj_name
                )
                    
        except Exception as e:
            print(f"    Warning: Error collecting from CronJobs: {e}")
        
        print(f"    Found {count} containers in CronJobs")
        return count

    def collect_from_replicasets(self) -> int:
        """
        Collect images from standalone ReplicaSets only (not managed by Deployment).
        
        ReplicaSets managed by Deployment are skipped since the Deployment is collected.

        Returns:
            Number of containers found.
        """
        print("  Collecting images from standalone ReplicaSets...")
        apps_v1 = self.client.get_apps_v1_api()
        count = 0
        skipped = 0
        
        try:
            # Use namespaced or cluster-wide API based on configuration
            if self.namespace:
                replicasets = apps_v1.list_namespaced_replica_set(namespace=self.namespace)
            else:
                replicasets = apps_v1.list_replica_set_for_all_namespaces()
            
            for rs in replicasets.items:
                namespace = rs.metadata.namespace
                
                # Skip excluded namespaces (no-op in single namespace mode)
                if self._is_namespace_excluded(namespace):
                    continue
                
                rs_name = rs.metadata.name
                
                # Skip ReplicaSets that are managed by a Deployment
                if self._is_owned_by(rs.metadata, ["Deployment"]):
                    skipped += 1
                    continue
                
                # Also skip ReplicaSets with 0 replicas (old/unused)
                if rs.spec.replicas == 0:
                    skipped += 1
                    continue
                
                containers = rs.spec.template.spec.containers or []
                init_containers = rs.spec.template.spec.init_containers or []
                all_containers = containers + init_containers
                
                count += self._add_container_info(
                    all_containers,
                    namespace,
                    "ReplicaSet",
                    rs_name
                )
                    
        except Exception as e:
            print(f"    Warning: Error collecting from ReplicaSets: {e}")
        
        print(f"    Found {count} containers in standalone ReplicaSets (skipped {skipped} managed/empty)")
        return count

    def collect_all(self) -> int:
        """
        Collect images from all supported resource types.
        
        Collection order is important for deduplication:
        1. Top-level controllers first (Deployment, StatefulSet, DaemonSet, CronJob)
        2. Then intermediate controllers (ReplicaSet, Job) - only standalone ones
        3. Finally Pods - only standalone ones

        Returns:
            Total number of containers found.
        """
        if self.namespace:
            print(f"\n📦 Collecting container images from namespace: {self.namespace}")
        else:
            print("\n📦 Collecting container images from cluster...")
        print("  (Only top-level controllers are reported, child objects are skipped)")
        if self.exclude_patterns:
            print(f"  (Excluding namespaces matching: {', '.join(self.exclude_patterns)})")
        self.images = []  # Reset
        self._excluded_namespaces_cache.clear()  # Clear cache for fresh collection
        
        total = 0
        
        # 1. Top-level controllers (always collected)
        total += self.collect_from_deployments()
        total += self.collect_from_statefulsets()
        total += self.collect_from_daemonsets()
        total += self.collect_from_cronjobs()
        
        # 2. Intermediate controllers (only standalone)
        total += self.collect_from_replicasets()  # Skip Deployment-managed
        total += self.collect_from_jobs()         # Skip CronJob-managed
        
        # 3. Pods (only standalone)
        total += self.collect_from_pods()         # Skip all controller-managed
        
        print(f"\n✓ Total containers found: {total}")
        if self._excluded_namespaces_cache:
            print(f"  (Excluded {len(self._excluded_namespaces_cache)} namespaces: {', '.join(sorted(self._excluded_namespaces_cache)[:5])}{'...' if len(self._excluded_namespaces_cache) > 5 else ''})")
        return total

    def to_dataframe(self) -> pd.DataFrame:
        """
        Convert collected images to a pandas DataFrame.

        Returns:
            DataFrame with image information.
        """
        # Define column order (image_name and image_id, then analysis results)
        columns = [
            "container_name", "namespace", "object_type", "object_name",
            "image_name", "image_id",
            "java_binary", "java_version", "java_cgroup_v2_compatible",
            "node_binary", "node_version", "node_cgroup_v2_compatible",
            "analysis_error"
        ]
        
        if not self.images:
            return pd.DataFrame(columns=columns)
        
        data = [img.to_dict() for img in self.images]
        return pd.DataFrame(data, columns=columns)

    def save_to_csv(self, cluster_name: str, output_dir: str = "output") -> str:
        """
        Save collected images to a CSV file.

        Args:
            cluster_name: Name of the cluster (for filename).
            output_dir: Directory to save the CSV file.

        Returns:
            Path to the saved CSV file.
        """
        # Create output directory if it doesn't exist
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        # Generate filename with cluster name and timestamp
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"{cluster_name}-{timestamp}.csv"
        filepath = output_path / filename
        
        # Convert to DataFrame and save
        df = self.to_dataframe()
        df.to_csv(filepath, index=False)
        
        print(f"\n✓ Saved {len(df)} records to {filepath}")
        return str(filepath)

    def get_unique_images(self) -> pd.DataFrame:
        """
        Get unique images across all containers.

        Returns:
            DataFrame with unique images.
        """
        df = self.to_dataframe()
        return df.drop_duplicates(subset=["image_name"]).reset_index(drop=True)

    def analyze_images(
        self, 
        rootfs_path: str, 
        pull_secret_path: Optional[str] = None,
        debug: bool = False,
        cluster_name: Optional[str] = None,
        output_dir: str = "output"
    ) -> tuple:
        """
        Analyze all collected images for Java and NodeJS binaries.
        
        This method:
        1. Gets unique images to avoid re-analyzing the same image
        2. For each unique image, exports and analyzes the container
        3. Updates all ContainerImageInfo objects with the analysis results
        4. Saves CSV after each image (for resumability if interrupted)
        5. Cleans up after each image to save disk space
        
        Args:
            rootfs_path: Path where rootfs directory exists
            pull_secret_path: Path to pull-secret for authentication
            debug: Enable debug output
            cluster_name: Cluster name for CSV filename (if provided, saves after each image)
            output_dir: Directory to save CSV output
            
        Returns:
            Tuple of (number of images analyzed, CSV filepath or None)
        """
        print("\n🔬 Analyzing images for Java and NodeJS binaries...")
        print("  (Each image will be pulled, analyzed, and cleaned up)")
        if cluster_name:
            print("  (CSV will be saved after each image for resumability)")
        
        # Create analyzer
        analyzer = ImageAnalyzer(rootfs_path, pull_secret_path)
        
        if debug:
            print(f"  [DEBUG] Analyzer rootfs_base: {analyzer.rootfs_base}")
            print(f"  [DEBUG] Analyzer rootfs_path: {analyzer.rootfs_path}")
        
        # Get unique images
        unique_images = set()
        for img in self.images:
            # Use image_name as key (image_id might be empty for non-Pod objects)
            unique_images.add(img.image_name)
        
        print(f"  Found {len(unique_images)} unique images to analyze")
        
        # Generate CSV filename once (fixed for this run)
        csv_filepath = None
        if cluster_name:
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            filename = f"{cluster_name}-{timestamp}.csv"
            csv_filepath = output_path / filename
        
        # Analyze each unique image
        analyzed_count = 0
        results_cache: Dict[str, ImageAnalysisResult] = {}
        
        for idx, image_name in enumerate(unique_images, 1):
            print(f"\n  [{idx}/{len(unique_images)}] Analyzing: {image_name[:70]}...")
            
            try:
                result = analyzer.analyze_image(image_name, debug=debug)
                results_cache[image_name] = result
                analyzed_count += 1
                
            except Exception as e:
                print(f"    Error analyzing image: {e}")
                import traceback
                if debug:
                    traceback.print_exc()
                # Create error result
                results_cache[image_name] = ImageAnalysisResult(
                    image_name=image_name,
                    image_id="",
                    error=str(e)
                )
            
            # Update all ContainerImageInfo objects with current results
            for img in self.images:
                result = results_cache.get(img.image_name)
                if result:
                    img.java_binary = result.java_found
                    img.java_version = result.java_versions
                    img.java_compatible = result.java_compatible
                    img.node_binary = result.node_found
                    img.node_version = result.node_versions
                    img.node_compatible = result.node_compatible
                    img.analysis_error = result.error or ""
            
            # Save CSV after each image analysis (only analyzed images for efficiency)
            if csv_filepath:
                # Filter to only include containers whose images have been analyzed
                analyzed_image_names = set(results_cache.keys())
                df = self.to_dataframe()
                df_analyzed = df[df['image_name'].isin(analyzed_image_names)]
                df_analyzed.to_csv(csv_filepath, index=False)
                print(f"    💾 Progress saved: {len(df_analyzed)} rows ({idx}/{len(unique_images)} images)")
        
        print(f"\n✓ Analyzed {analyzed_count} unique images")
        
        # Final save with ALL rows (now all images are analyzed)
        if csv_filepath:
            df = self.to_dataframe()
            df.to_csv(csv_filepath, index=False)
            print(f"  Final CSV saved to: {csv_filepath} ({len(df)} rows)")
        
        return analyzed_count, str(csv_filepath) if csv_filepath else None

