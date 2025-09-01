#!/usr/bin/env python3
"""
Download data from the SARAO Archive using rclone.
"""

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, parse_qs

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


@dataclass
class RcloneConfig:
    remote_name: str = "sarao"
    endpoint: str = "https://archive-gw-1.kat.ac.za"
    provider: str = "Ceph"
    acl: str = "public-read"
    chunk_size: str = "5G"
    timeout: str = "25s"
    retries: int = 10


class SARAODownloader:
    def __init__(self, url: str, config: Optional[RcloneConfig] = None):
        self.url = url
        self.config = config or RcloneConfig()
        self.source, self.token = self._extract_source_and_token()
        self.log_file = Path("sarao_download.log")

    def _extract_source_and_token(self) -> tuple[str, str]:
        """Extract source path and token from URL."""
        parsed = urlparse(self.url)
        allowed_domains = {"preview.archive.sarao.ac.za", "archive-gw-1.kat.ac.za"}
        
        if parsed.netloc not in allowed_domains:
            raise ValueError(f"Invalid URL domain. Allowed: {allowed_domains}")

        path = parsed.path.lstrip("/")
        token = parse_qs(parsed.query).get("token", [""])[0]
        if not token:
            raise ValueError("No token found in URL")

        return path, token

    def _check_rclone_installed(self) -> bool:
        """Check if rclone is available."""
        return shutil.which("rclone") is not None

    def _get_rclone_env(self) -> dict:
        """Generate rclone environment variables."""
        return {
            f"RCLONE_CONFIG_{self.config.remote_name.upper()}_TYPE": "s3",
            f"RCLONE_CONFIG_{self.config.remote_name.upper()}_PROVIDER": self.config.provider,
            f"RCLONE_CONFIG_{self.config.remote_name.upper()}_ENV_AUTH": "false",
            f"RCLONE_CONFIG_{self.config.remote_name.upper()}_ACCESS_KEY_ID": self.token,
            f"RCLONE_CONFIG_{self.config.remote_name.upper()}_SECRET_ACCESS_KEY": self.token,
            f"RCLONE_CONFIG_{self.config.remote_name.upper()}_ENDPOINT": self.config.endpoint,
            f"RCLONE_CONFIG_{self.config.remote_name.upper()}_ACL": self.config.acl,
        }

    def check_size(self) -> str:
        """Check size of remote data and return human-readable format."""
        cmd = [
            "rclone",
            "size",
            f"{self.config.remote_name}:{self.source}",
            "--json",
        ]
        try:
            env = os.environ.copy()
            env.update(self._get_rclone_env())
            result = subprocess.run(cmd, env=env, check=True, capture_output=True, text=True)
            size_data = json.loads(result.stdout)
            
            # Convert bytes to human-readable format
            bytes_size = size_data["bytes"]
            if bytes_size >= 1024 ** 3:  # GB
                readable_size = f"{bytes_size / (1024 ** 3):.2f} GB"
            elif bytes_size >= 1024 ** 2:  # MB
                readable_size = f"{bytes_size / (1024 ** 2):.2f} MB"
            else:  # KB or bytes
                readable_size = f"{bytes_size / 1024:.2f} KB" if bytes_size >= 1024 else f"{bytes_size} bytes"
            
            return f"Files: {size_data['count']}, Size: {readable_size}"
        except subprocess.CalledProcessError as e:
            logger.error(f"Size check failed: {e.stderr}")
            raise
        except json.JSONDecodeError:
            logger.error("Failed to parse size information")
            raise

    def download(self, dest: Path = Path(".")) -> bool:
        """Download data to destination."""
        if not self._check_rclone_installed():
            logger.error("rclone not installed. See: https://rclone.org/downloads/")
            return False

        cmd = [
            "rclone",
            "copy",
            f"{self.config.remote_name}:{self.source}",
            str(dest),
            "--progress",
            f"--s3-chunk-size={self.config.chunk_size}",
            f"--timeout={self.config.timeout}",
            f"--retries={self.config.retries}",
        ]

        try:
            env = os.environ.copy()
            env.update(self._get_rclone_env())
            with open(self.log_file, "w") as log:
                proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                for line in proc.stdout:
                    log.write(line)
                    if "Transferred:" in line:
                        print(f"\r{line.strip()}", end="")
                proc.wait()
                return proc.returncode == 0
        except Exception as e:
            logger.error(f"Download failed: {e}")
            return False


def main():
    parser = argparse.ArgumentParser(description="Download data from SARAO Archive")
    parser.add_argument("-u", "--url", required=True, help="Download URL from SARAO Archive")
    parser.add_argument("-d", "--dest", default=".", help="Destination directory")
    args = parser.parse_args()

    try:
        downloader = SARAODownloader(args.url)
        logger.info("Checking size...")
        size_info = downloader.check_size()
        logger.info(f"Size info: {size_info}")

        logger.info("Starting download...")
        if downloader.download(Path(args.dest)):
            logger.info("Download completed successfully!")
        else:
            logger.error("Download failed. Check logs.")
            sys.exit(1)
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()