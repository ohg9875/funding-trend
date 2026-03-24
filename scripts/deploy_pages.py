"""
GitHub Pages 배포 스크립트
가장 최신 funding_page_*.html 파일을 docs/index.html로 복사
"""
import glob
import logging
import os
import shutil

logger = logging.getLogger(__name__)


def deploy_to_pages(pages_dir: str = "data/pages", docs_dir: str = "docs") -> bool:
    """
    최신 HTML을 docs/index.html로 복사.
    반환: True(성공) / False(파일 없음)
    """
    html_files = sorted(glob.glob(os.path.join(pages_dir, "funding_page_*.html")), reverse=True)
    if not html_files:
        logger.warning("배포할 HTML 파일 없음 — 스킵")
        return False

    latest = html_files[0]
    os.makedirs(docs_dir, exist_ok=True)
    dest = os.path.join(docs_dir, "index.html")
    shutil.copy2(latest, dest)
    logger.info(f"배포 완료: {latest} → {dest}")
    return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    ok = deploy_to_pages()
    print("배포 성공" if ok else "배포할 파일 없음")
