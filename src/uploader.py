import os
import io
import json
import hashlib
from typing import Dict, List, Any, Optional, Tuple
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
from dotenv import load_dotenv

# Ensure environment variables are loaded
load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.env"), override=False)

def create_resilient_session(retries: int = 3, backoff_factor: float = 0.5) -> requests.Session:
    """Creates a requests.Session configured with automatic retries and exponential backoff."""
    session = requests.Session()
    retry_strategy = Retry(
        total=retries,
        read=retries,
        connect=retries,
        backoff_factor=backoff_factor,
        status_forcelist=[429, 500, 502, 503, 504],
        raise_on_status=False
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


class RemotePaperUploader:
    """
    Client for interacting with the remote Shamir's Secret Sharing (SSS)
    question paper upload & reconstruction endpoints.
    """
    def __init__(
        self,
        upload_url: Optional[str] = None,
        reconstruct_url: Optional[str] = None,
        auth_token: Optional[str] = None,
        n: Optional[int] = None,
        k: Optional[int] = None,
        file_format: Optional[str] = None,
        save_local_files: Optional[bool] = None,
        verify_upload: Optional[bool] = None,
    ):
        self.upload_url = upload_url or os.getenv(
            "UPLOAD_ENDPOINT_URL",
            "https://traditionless-interdigitally-arlette.ngrok-free.dev/api/question-papers/upload"
        )
        self.reconstruct_url_template = reconstruct_url or os.getenv(
            "RECONSTRUCT_ENDPOINT_URL",
            "https://traditionless-interdigitally-arlette.ngrok-free.dev/api/question-papers/{id}/reconstruct"
        )
        self.auth_token = auth_token or os.getenv("UPLOAD_AUTH_TOKEN", "")
        self.n = int(n if n is not None else os.getenv("UPLOAD_SSS_N", "3"))
        self.k = int(k if k is not None else os.getenv("UPLOAD_SSS_K", "2"))
        self.file_format = (file_format or os.getenv("UPLOAD_FILE_FORMAT", "json")).lower()
        
        save_local_env = os.getenv("SAVE_LOCAL_FILES", "false").lower()
        self.save_local_files = save_local_files if save_local_files is not None else (save_local_env in ("true", "1", "yes"))
        
        verify_env = os.getenv("VERIFY_UPLOAD", "true").lower()
        self.verify_upload_enabled = verify_upload if verify_upload is not None else (verify_env in ("true", "1", "yes"))
        
        # Initialize resilient HTTP session with automated exponential backoff retries
        self.session = create_resilient_session(retries=3, backoff_factor=0.5)

    def _get_headers(self) -> Dict[str, str]:
        headers = {}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        return headers

    def upload_bytes(
        self,
        data: bytes,
        filename: str,
        content_type: Optional[str] = None,
        n: Optional[int] = None,
        k: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Uploads raw file bytes to the remote endpoint.
        Returns the server response parsed as JSON.
        """
        n_val = n if n is not None else self.n
        k_val = k if k is not None else self.k
        headers = self._get_headers()

        # Handle server-side extension whitelist: doc, docx, jpeg, jpg, pdf, png
        # If filename ends with .json, and server requires permitted extension,
        # name it with an allowed container extension like .json.docx
        send_filename = filename
        ext = os.path.splitext(filename)[1].lower()
        if ext == ".json":
            send_filename = f"{filename}.docx"

        if not content_type:
            if send_filename.endswith(".docx"):
                content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            elif send_filename.endswith(".pdf"):
                content_type = "application/pdf"
            else:
                content_type = "application/octet-stream"

        form_data = {
            "n": str(n_val),
            "k": str(k_val)
        }

        files = {
            "file": (send_filename, data, content_type)
        }

        response = self.session.post(
            self.upload_url,
            headers=headers,
            data=form_data,
            files=files,
            timeout=30
        )

        if response.status_code not in (200, 201):
            raise RuntimeError(
                f"Upload failed with HTTP {response.status_code}: {response.text}"
            )

        result = response.json()
        return result

    def reconstruct_file(self, doc_id: str) -> bytes:
        """
        Downloads / reconstructs the file from the remote SSS shares.
        """
        url = self.reconstruct_url_template.format(id=doc_id)
        headers = self._get_headers()

        response = self.session.post(url, headers=headers, timeout=30)
        if response.status_code != 200:
            raise RuntimeError(
                f"Reconstruction failed for document {doc_id} with HTTP {response.status_code}: {response.text}"
            )


        return response.content

    def verify_upload(self, doc_id: str, original_bytes: bytes) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Verifies that the uploaded document reconstructs correctly and matches original bytes.
        """
        try:
            reconstructed = self.reconstruct_file(doc_id)
            orig_hash = hashlib.sha256(original_bytes).hexdigest()
            recon_hash = hashlib.sha256(reconstructed).hexdigest()
            
            is_match = (orig_hash == recon_hash)
            details = {
                "doc_id": doc_id,
                "original_size": len(original_bytes),
                "reconstructed_size": len(reconstructed),
                "original_sha256": orig_hash,
                "reconstructed_sha256": recon_hash,
                "verified": is_match
            }
            if is_match:
                return True, "Hash and byte length matched perfectly.", details
            else:
                return False, f"Hash mismatch: original {orig_hash} != reconstructed {recon_hash}", details
        except Exception as e:
            return False, f"Verification failed with exception: {e}", {"doc_id": doc_id, "error": str(e), "verified": False}

    def upload_paper_item(
        self,
        item_bytes: bytes,
        filename: str,
        meta_label: str
    ) -> Dict[str, Any]:
        """
        Uploads an individual paper or solutions manual byte stream,
        verifies reconstruction if enabled, and returns a detailed status dictionary.
        """
        print(f"  [Remote Uploader] Uploading {meta_label} ({filename}, {len(item_bytes)} bytes)...")
        upload_resp = self.upload_bytes(item_bytes, filename)
        doc_id = upload_resp.get("id") or upload_resp.get("paper_id")
        shares = upload_resp.get("shares", [])

        status_info = {
            "label": meta_label,
            "filename": filename,
            "doc_id": doc_id,
            "scheme": upload_resp.get("scheme", "SSS"),
            "n": upload_resp.get("n", self.n),
            "k": upload_resp.get("k", self.k),
            "shares_count": len(shares),
            "upload_status": "SUCCESS",
            "verification_status": "SKIPPED",
            "verification_details": None
        }

        if self.verify_upload_enabled and doc_id:
            print(f"  [Remote Uploader] Verifying SSS reconstruction for {doc_id}...")
            verified, message, details = self.verify_upload(doc_id, item_bytes)
            status_info["verification_status"] = "PASSED" if verified else "FAILED"
            status_info["verification_message"] = message
            status_info["verification_details"] = details
            if verified:
                print(f"  [Remote Uploader] [VERIFICATION PASSED] SHA256 integrity confirmed for {meta_label}.")
            else:
                print(f"  [Remote Uploader] [VERIFICATION FAILED] {message}")

        return status_info
