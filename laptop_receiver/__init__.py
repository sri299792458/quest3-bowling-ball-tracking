"""Standalone laptop receiver package.

Keep package-level imports intentionally light.

Some submodules depend on optional heavier packages such as `cv2`, `torch`,
or SAM2-related runtime pieces. Import those explicitly from their modules
instead of making every CLI entrypoint pay that import cost.
"""

__all__: list[str] = []
