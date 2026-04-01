"""Resume tailoring via Finetune Resume API.

Before each application, the worker can call this to generate a
job-specific resume. The tailored resume replaces the generic one
for that particular application.

Requires FINETUNE_RESUME_URL and FINETUNE_RESUME_API_KEY in .env.
If not configured, falls back to the user's default resume.
"""

import os
import logging
import httpx

logger = logging.getLogger(__name__)

FINETUNE_URL = os.environ.get("FINETUNE_RESUME_URL", "https://www.finetuneresume.app")
FINETUNE_API_KEY = os.environ.get("FINETUNE_RESUME_API_KEY", "")
RESUME_DIR = os.environ.get("RESUME_DIR", "/tmp/autoapply/resumes")


def is_configured() -> bool:
    """Check if Finetune Resume integration is configured."""
    return bool(FINETUNE_URL and FINETUNE_API_KEY)


def tailor_resume(
    base_resume_path: str,
    job_title: str,
    company_name: str,
    job_description: str,
    finetune_level: str = "good",
) -> str:
    """Generate a job-specific tailored resume via Finetune Resume API.

    Args:
        base_resume_path: Path to the user's default resume PDF
        job_title: The job title being applied to
        company_name: The company name
        job_description: Full job description text
        finetune_level: "basic", "good", or "super"

    Returns:
        Path to the tailored resume PDF (or base_resume_path if tailoring fails)
    """
    if not is_configured():
        logger.debug("Finetune Resume not configured — using base resume")
        return base_resume_path

    if not job_description or len(job_description) < 50:
        logger.debug("Job description too short for tailoring — using base resume")
        return base_resume_path

    try:
        os.makedirs(RESUME_DIR, exist_ok=True)

        # Call the Finetune Resume API
        with httpx.Client(timeout=120) as client:
            # Step 1: Generate tailored resume
            resp = client.post(
                f"{FINETUNE_URL}/api/generate-resume",
                json={
                    "jobDescription": job_description,
                    "companyName": company_name,
                    "finetuneLevel": finetune_level,
                },
                headers={
                    "Authorization": f"Bearer {FINETUNE_API_KEY}",
                    "Content-Type": "application/json",
                },
            )

            if resp.status_code != 200:
                logger.warning(f"Finetune Resume API returned {resp.status_code}: {resp.text[:200]}")
                return base_resume_path

            data = resp.json()
            pdf_url = data.get("pdfUrl") or data.get("pdf_url")

            if not pdf_url:
                logger.warning("Finetune Resume API returned no PDF URL")
                return base_resume_path

            # Step 2: Download the tailored PDF
            safe_company = "".join(c for c in company_name if c.isalnum() or c in "._- ")[:30]
            tailored_filename = f"tailored_{safe_company}_{job_title[:20].replace(' ', '_')}.pdf"
            tailored_path = os.path.join(RESUME_DIR, tailored_filename)

            pdf_resp = client.get(pdf_url)
            pdf_resp.raise_for_status()

            with open(tailored_path, "wb") as f:
                f.write(pdf_resp.content)

            logger.info(f"Resume tailored for {company_name} — {job_title} → {tailored_path}")
            return tailored_path

    except Exception as e:
        logger.warning(f"Resume tailoring failed ({company_name}): {e} — using base resume")
        return base_resume_path
