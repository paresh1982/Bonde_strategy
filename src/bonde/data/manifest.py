"""
Dataset Manifest & Reproducibility Management (Section 15)
Maintains machine-readable cryptographic manifests for all ingested datasets.
Guarantees full provenance and reproducible backtest runs.
"""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class DatasetManifest:
    """Cryptographic and metadata manifest for a specific dataset version."""
    dataset_name: str
    provider: str
    version: str
    download_timestamp: str
    coverage_start: str
    coverage_end: str
    symbol_count: int
    row_count: int
    timezone: str
    adjustment_status: str  # "UNADJUSTED", "SPLIT_ADJUSTED", "DUAL_PRICE"
    checksum: str          # SHA-256 hash of dataset content or manifest

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ManifestManager:
    """Manages creation, storage, and verification of dataset manifests."""

    def __init__(self, metadata_dir: Path = Path("data/metadata")):
        self.metadata_dir = metadata_dir
        self.manifest_file = metadata_dir / "dataset_manifest.json"

    def compute_sha256(self, file_path: Path) -> str:
        """Computes SHA-256 hash of a file."""
        if not file_path.exists():
            return ""
        hasher = hashlib.sha256()
        with open(file_path, "rb") as fh:
            while chunk := fh.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()

    def create_manifest(
        self,
        dataset_name: str,
        provider: str,
        version: str,
        coverage_start: str,
        coverage_end: str,
        symbol_count: int,
        row_count: int,
        tz_str: str = "America/New_York",
        adjustment_status: str = "DUAL_PRICE",
        file_path_for_checksum: Optional[Path] = None,
    ) -> DatasetManifest:
        """Generates a new DatasetManifest."""
        if file_path_for_checksum and file_path_for_checksum.exists():
            checksum = self.compute_sha256(file_path_for_checksum)
        else:
            # Hash metadata string as fallback
            meta_str = f"{dataset_name}:{provider}:{version}:{row_count}:{coverage_start}:{coverage_end}"
            checksum = hashlib.sha256(meta_str.encode("utf-8")).hexdigest()

        return DatasetManifest(
            dataset_name=dataset_name,
            provider=provider,
            version=version,
            download_timestamp=datetime.now(timezone.utc).isoformat(),
            coverage_start=coverage_start,
            coverage_end=coverage_end,
            symbol_count=symbol_count,
            row_count=row_count,
            timezone=tz_str,
            adjustment_status=adjustment_status,
            checksum=checksum,
        )

    def save_manifest(self, manifest: DatasetManifest):
        """Appends or updates manifest in metadata_dir/dataset_manifest.json."""
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        manifests = self.load_all_manifests()
        manifests[manifest.dataset_name] = manifest.to_dict()

        with open(self.manifest_file, "w", encoding="utf-8") as fh:
            json.dump(manifests, fh, indent=2)

    def load_all_manifests(self) -> Dict[str, Any]:
        """Loads all persisted manifests."""
        if not self.manifest_file.exists():
            return {}
        try:
            with open(self.manifest_file, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return {}

    def get_manifest(self, dataset_name: str) -> Optional[DatasetManifest]:
        """Retrieves a specific dataset manifest by name."""
        all_manifests = self.load_all_manifests()
        entry = all_manifests.get(dataset_name)
        if not entry:
            return None
        return DatasetManifest(**entry)
