from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class ApplyResult:
    success: bool
    screenshot: Optional[str] = None
    error: Optional[str] = None
    retriable: bool = False


class BaseApplier(ABC):
    def __init__(self, profile: dict, answer_key: dict, resume_path: str):
        self.profile = profile
        self.answer_key = answer_key
        self.resume_path = resume_path

    @abstractmethod
    def apply(self, apply_url: str) -> ApplyResult:
        pass
