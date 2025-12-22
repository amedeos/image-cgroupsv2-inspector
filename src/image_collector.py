"""
Image Collector Module
Collects container image information from OpenShift cluster resources.
"""

import os
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

import pandas as pd
from kubernetes import client

from .openshift_client import OpenShiftClient


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

    def to_dict(self) -> Dict[str, str]:
        """Convert to dictionary for DataFrame creation."""
        return {
            "container_name": self.container_name,
            "namespace": self.namespace,
            "object_type": self.object_type,
            "object_name": self.object_name,
            "image_name": self.image_name,
            "image_id": self.image_id
        }


class ImageCollector:
    """
    Collects container image information from various OpenShift resources.
    """

    def __init__(self, openshift_client: OpenShiftClient):
        """
        Initialize the image collector.

        Args:
            openshift_client: Connected OpenShift client instance.
        """
        self.client = openshift_client
        self.images: List[ContainerImageInfo] = []

    def _extract_container_statuses(
        self,
        container_statuses: Optional[List],
        containers: List,
        namespace: str,
        object_type: str,
        object_name: str
    ) -> None:
        """
        Extract image information from container statuses.

        Args:
            container_statuses: List of container statuses (may be None)
            containers: List of container specs
            namespace: Namespace of the resource
            object_type: Type of the parent object (Pod, Job, etc.)
            object_name: Name of the parent object
        """
        # Create a mapping of container name to image ID from statuses
        status_map: Dict[str, str] = {}
        if container_statuses:
            for status in container_statuses:
                image_id = status.image_id if status.image_id else ""
                status_map[status.name] = image_id

        # Extract information for each container
        for container in containers:
            image_id = status_map.get(container.name, "")
            
            info = ContainerImageInfo(
                container_name=container.name,
                image_name=container.image,
                namespace=namespace,
                image_id=image_id,
                object_type=object_type,
                object_name=object_name
            )
            self.images.append(info)

    def collect_from_pods(self) -> int:
        """
        Collect images from all Pods in the cluster.

        Returns:
            Number of containers found.
        """
        print("  Collecting images from Pods...")
        core_v1 = self.client.get_core_v1_api()
        count = 0
        
        try:
            pods = core_v1.list_pod_for_all_namespaces()
            
            for pod in pods.items:
                namespace = pod.metadata.namespace
                pod_name = pod.metadata.name
                
                # Get all containers (regular + init)
                containers = pod.spec.containers or []
                init_containers = pod.spec.init_containers or []
                all_containers = containers + init_containers
                
                # Get container statuses
                container_statuses = []
                if pod.status:
                    container_statuses = (pod.status.container_statuses or []) + \
                                        (pod.status.init_container_statuses or [])
                
                self._extract_container_statuses(
                    container_statuses,
                    all_containers,
                    namespace,
                    "Pod",
                    pod_name
                )
                count += len(all_containers)
                
        except Exception as e:
            print(f"    Warning: Error collecting from Pods: {e}")
        
        print(f"    Found {count} containers in Pods")
        return count

    def collect_from_deployments(self) -> int:
        """
        Collect images from all Deployments in the cluster.

        Returns:
            Number of containers found.
        """
        print("  Collecting images from Deployments...")
        apps_v1 = self.client.get_apps_v1_api()
        count = 0
        
        try:
            deployments = apps_v1.list_deployment_for_all_namespaces()
            
            for deployment in deployments.items:
                namespace = deployment.metadata.namespace
                deployment_name = deployment.metadata.name
                
                # Get containers from pod template
                containers = deployment.spec.template.spec.containers or []
                init_containers = deployment.spec.template.spec.init_containers or []
                all_containers = containers + init_containers
                
                # Deployments don't have direct container statuses
                # We collect from the template spec
                for container in all_containers:
                    info = ContainerImageInfo(
                        container_name=container.name,
                        image_name=container.image,
                        namespace=namespace,
                        image_id="",  # Not available at deployment level
                        object_type="Deployment",
                        object_name=deployment_name
                    )
                    self.images.append(info)
                    count += 1
                    
        except Exception as e:
            print(f"    Warning: Error collecting from Deployments: {e}")
        
        print(f"    Found {count} containers in Deployments")
        return count

    def collect_from_statefulsets(self) -> int:
        """
        Collect images from all StatefulSets in the cluster.

        Returns:
            Number of containers found.
        """
        print("  Collecting images from StatefulSets...")
        apps_v1 = self.client.get_apps_v1_api()
        count = 0
        
        try:
            statefulsets = apps_v1.list_stateful_set_for_all_namespaces()
            
            for sts in statefulsets.items:
                namespace = sts.metadata.namespace
                sts_name = sts.metadata.name
                
                containers = sts.spec.template.spec.containers or []
                init_containers = sts.spec.template.spec.init_containers or []
                all_containers = containers + init_containers
                
                for container in all_containers:
                    info = ContainerImageInfo(
                        container_name=container.name,
                        image_name=container.image,
                        namespace=namespace,
                        image_id="",
                        object_type="StatefulSet",
                        object_name=sts_name
                    )
                    self.images.append(info)
                    count += 1
                    
        except Exception as e:
            print(f"    Warning: Error collecting from StatefulSets: {e}")
        
        print(f"    Found {count} containers in StatefulSets")
        return count

    def collect_from_daemonsets(self) -> int:
        """
        Collect images from all DaemonSets in the cluster.

        Returns:
            Number of containers found.
        """
        print("  Collecting images from DaemonSets...")
        apps_v1 = self.client.get_apps_v1_api()
        count = 0
        
        try:
            daemonsets = apps_v1.list_daemon_set_for_all_namespaces()
            
            for ds in daemonsets.items:
                namespace = ds.metadata.namespace
                ds_name = ds.metadata.name
                
                containers = ds.spec.template.spec.containers or []
                init_containers = ds.spec.template.spec.init_containers or []
                all_containers = containers + init_containers
                
                for container in all_containers:
                    info = ContainerImageInfo(
                        container_name=container.name,
                        image_name=container.image,
                        namespace=namespace,
                        image_id="",
                        object_type="DaemonSet",
                        object_name=ds_name
                    )
                    self.images.append(info)
                    count += 1
                    
        except Exception as e:
            print(f"    Warning: Error collecting from DaemonSets: {e}")
        
        print(f"    Found {count} containers in DaemonSets")
        return count

    def collect_from_jobs(self) -> int:
        """
        Collect images from all Jobs in the cluster.

        Returns:
            Number of containers found.
        """
        print("  Collecting images from Jobs...")
        batch_v1 = self.client.get_batch_v1_api()
        count = 0
        
        try:
            jobs = batch_v1.list_job_for_all_namespaces()
            
            for job in jobs.items:
                namespace = job.metadata.namespace
                job_name = job.metadata.name
                
                containers = job.spec.template.spec.containers or []
                init_containers = job.spec.template.spec.init_containers or []
                all_containers = containers + init_containers
                
                for container in all_containers:
                    info = ContainerImageInfo(
                        container_name=container.name,
                        image_name=container.image,
                        namespace=namespace,
                        image_id="",
                        object_type="Job",
                        object_name=job_name
                    )
                    self.images.append(info)
                    count += 1
                    
        except Exception as e:
            print(f"    Warning: Error collecting from Jobs: {e}")
        
        print(f"    Found {count} containers in Jobs")
        return count

    def collect_from_cronjobs(self) -> int:
        """
        Collect images from all CronJobs in the cluster.

        Returns:
            Number of containers found.
        """
        print("  Collecting images from CronJobs...")
        batch_v1 = self.client.get_batch_v1_api()
        count = 0
        
        try:
            cronjobs = batch_v1.list_cron_job_for_all_namespaces()
            
            for cj in cronjobs.items:
                namespace = cj.metadata.namespace
                cj_name = cj.metadata.name
                
                # CronJob has job template -> pod template
                containers = cj.spec.job_template.spec.template.spec.containers or []
                init_containers = cj.spec.job_template.spec.template.spec.init_containers or []
                all_containers = containers + init_containers
                
                for container in all_containers:
                    info = ContainerImageInfo(
                        container_name=container.name,
                        image_name=container.image,
                        namespace=namespace,
                        image_id="",
                        object_type="CronJob",
                        object_name=cj_name
                    )
                    self.images.append(info)
                    count += 1
                    
        except Exception as e:
            print(f"    Warning: Error collecting from CronJobs: {e}")
        
        print(f"    Found {count} containers in CronJobs")
        return count

    def collect_from_replicasets(self) -> int:
        """
        Collect images from all ReplicaSets in the cluster.

        Returns:
            Number of containers found.
        """
        print("  Collecting images from ReplicaSets...")
        apps_v1 = self.client.get_apps_v1_api()
        count = 0
        
        try:
            replicasets = apps_v1.list_replica_set_for_all_namespaces()
            
            for rs in replicasets.items:
                namespace = rs.metadata.namespace
                rs_name = rs.metadata.name
                
                containers = rs.spec.template.spec.containers or []
                init_containers = rs.spec.template.spec.init_containers or []
                all_containers = containers + init_containers
                
                for container in all_containers:
                    info = ContainerImageInfo(
                        container_name=container.name,
                        image_name=container.image,
                        namespace=namespace,
                        image_id="",
                        object_type="ReplicaSet",
                        object_name=rs_name
                    )
                    self.images.append(info)
                    count += 1
                    
        except Exception as e:
            print(f"    Warning: Error collecting from ReplicaSets: {e}")
        
        print(f"    Found {count} containers in ReplicaSets")
        return count

    def collect_all(self) -> int:
        """
        Collect images from all supported resource types.

        Returns:
            Total number of containers found.
        """
        print("\n📦 Collecting container images from cluster...")
        self.images = []  # Reset
        
        total = 0
        total += self.collect_from_pods()
        total += self.collect_from_deployments()
        total += self.collect_from_statefulsets()
        total += self.collect_from_daemonsets()
        total += self.collect_from_jobs()
        total += self.collect_from_cronjobs()
        total += self.collect_from_replicasets()
        
        print(f"\n✓ Total containers found: {total}")
        return total

    def to_dataframe(self) -> pd.DataFrame:
        """
        Convert collected images to a pandas DataFrame.

        Returns:
            DataFrame with image information.
        """
        # Define column order (image_name and image_id last)
        columns = [
            "container_name", "namespace", "object_type",
            "object_name", "image_name", "image_id"
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

